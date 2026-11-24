from contextlib import redirect_stdout
import csv
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from specialists import research_data
from specialists.contracts import SPLITS, validate_row


def _jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


class ResearchDataTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.output = self.root / 'output'
        self.output.mkdir()

    def test_cms_renders_exact_dates_and_isolates_synthetic_beneficiaries(self):
        archive = self.root / 'cms.zip'
        source = io.StringIO()
        writer = csv.writer(source)
        extra_fields = [f'field_{index}' for index in range(77)]
        writer.writerow([*research_data.CMS_COLUMNS, *extra_fields])
        for member in range(100):
            writer.writerow([f'BEN-{member}', 'a', '20080102', '20080105', *([''] * 77)])
            writer.writerow([f'BEN-{member}', 'b', '20080402', '20080402', *([''] * 77)])
        writer.writerow(['BEN-0', 'c', '20080102', '20080105', *([''] * 77)])
        writer.writerow(['BEN-0', 'd', '20080402', '20080401', *([''] * 77)])
        with ZipFile(archive, 'w') as zipped:
            zipped.writestr(research_data.CMS_MEMBER, source.getvalue())

        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            research_data.prepare_cms(archive, self.output, '0' * 64)
        with self.assertRaisesRegex(ValueError, '66,773'):
            research_data.prepare_cms(archive, self.output)
        output = self.root / 'cms-research'
        args = ['cms', str(archive), str(output)]
        with patch.object(research_data, 'CMS_ROWS', 202), redirect_stdout(io.StringIO()) as stdout:
            research_data.main(args)
            original = (output / 'manifest.json').read_bytes()
            manifest = json.loads(stdout.getvalue())
            research_data.main(args)
            self.assertEqual((output / 'manifest.json').read_bytes(), original)
        metadata = manifest['metadata']
        self.assertEqual(metadata['sha256'], hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertEqual(metadata['source_counts'], {
            'source_rows': 202, 'collapsed_repeat_stays': 1, 'skipped_invalid_or_reversed_dates': 1,
        })

        seen = set()
        for split in SPLITS:
            rows = _jsonl(output / f'{split}-span.jsonl')
            lineage = _jsonl(output / f'{split}-lineage.jsonl')
            self.assertTrue(rows)
            self.assertEqual({row['case_id'] for row in rows}, {row['case_id'] for row in lineage})
            groups = {row['synthetic_beneficiary_sha256'] for row in lineage}
            self.assertFalse(groups & seen)
            self.assertEqual(len(rows), len(groups) * 2)
            seen.update(groups)
            for row in rows:
                validate_row(row)
                self.assertEqual({span['label'] for span in row['spans']}, {'ADMISSION_DATE', 'DISCHARGE_DATE'})
                self.assertNotIn('BEN-', row['text'])

    def test_fieldbench_keeps_only_explicit_synthetic_cc0_and_original_gold(self):
        archive = self.root / 'fieldbench.tar.gz'
        records = [
            ('insurance_claims', 'claim', 'synthetic', 'CC0-1.0'),
            ('insurance_policies', 'policy', 'synthetic', 'CC0 1.0'),
            ('insurance_claims', 'other', 'synthetic', 'CC BY 4.0'),
            ('insurance_claims', 'actual', 'real', 'CC0 1.0'),
            ('medical_records', 'unrequested', 'synthetic', 'CC0'),
        ]
        markdown = '# Unmodified text\r\n\r\nField: D-1\r\n'
        expected = {'upstream_field': 'D-1', 'upstream_missing': None}
        with tarfile.open(archive, 'w:gz') as tar:
            for category, doc_id, source, license_name in records:
                files = {
                    f'manifests/{doc_id}.json': json.dumps({'category': category, 'doc_id': doc_id,
                                                          'source': source, 'license': license_name}),
                    f'documents/{doc_id}.md': markdown,
                    f'expected/{doc_id}.expected.json': json.dumps(expected),
                }
                for name, value in files.items():
                    data = value.encode()
                    entry = tarfile.TarInfo(name=f'fieldbench-corpus/{category}/{name}')
                    entry.size = len(data)
                    tar.addfile(entry, io.BytesIO(data))

        with self.assertRaisesRegex(ValueError, 'pinned v0.4.2'):
            research_data.prepare_fieldbench(archive, self.output)
        checksum = hashlib.md5(archive.read_bytes(), usedforsecurity=False).hexdigest()
        with patch.object(research_data, 'FIELDBENCH_MD5', checksum):
            metadata = research_data.prepare_fieldbench(archive, self.output)
        rows = _jsonl(self.output / 'value-only-holdout.jsonl')
        self.assertEqual(metadata['document_counts'], {'insurance_claims': 1, 'insurance_policies': 1})
        self.assertEqual([row['doc_id'] for row in rows], ['claim', 'policy'])
        self.assertTrue(all(row['text'] == markdown and row['expected'] == expected for row in rows))
        self.assertTrue(all(row['provenance']['doc_id'] == row['doc_id'] for row in rows))
        self.assertTrue(all('spans' not in row for row in rows))

    def test_fieldbench_rejects_mismatched_provenance_in_zip(self):
        archive = self.root / 'fieldbench.zip'
        with ZipFile(archive, 'w') as zipped:
            zipped.writestr('insurance_claims/manifests/claim.json', json.dumps({
                'doc_id': 'other', 'source': 'synthetic', 'license': 'CC0',
            }))
        with self.assertRaisesRegex(ValueError, 'does not match its path'):
            list(research_data._fieldbench_rows(archive))
