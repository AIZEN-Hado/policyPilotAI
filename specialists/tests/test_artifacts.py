import gzip
import io
import json
import os
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
import unittest

from specialists.artifacts import (
    MANIFEST_NAME,
    package_directory,
    sha256_file,
    verify_archive,
    verify_manifest,
    write_manifest,
)


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(TemporaryDirectory())
        self.root = Path(temporary)
        self.source = self.root / "source"
        self.source.mkdir()
        self.config = self.source / "config.json"
        self.config.write_text('{}\n', encoding="utf-8")
        self.notes = self.source / "tasks" / "notes.txt"
        self.notes.parent.mkdir()
        self.notes.write_text('sample\n', encoding="utf-8")

    def test_manifest_and_reproducible_archive_round_trip(self):
        path = write_manifest(self.source, metadata={"kind": "synthetic"})
        self.assertEqual(path, self.source / MANIFEST_NAME)
        manifest = verify_manifest(self.source)
        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["metadata"], {"kind": "synthetic"})
        self.assertEqual(manifest["files"], [
            {"path": "config.json", "sha256": sha256_file(self.config), "bytes": 3},
            {"path": "tasks/notes.txt", "sha256": sha256_file(self.notes), "bytes": 7},
        ])

        archive = self.root / "first.tar.gz"
        receipt = package_directory(self.source, archive)
        self.assertEqual(receipt, verify_archive(archive))
        self.assertEqual(receipt, {
            "bytes": archive.stat().st_size,
            "sha256": sha256_file(archive),
            "manifest": manifest,
        })
        self.assertEqual(receipt, package_directory(self.source, self.root / "second.tar.gz"))
        with self.assertRaises(FileExistsError):
            package_directory(self.source, archive)

    def test_manifest_rejects_tampered_and_untracked_payloads(self):
        write_manifest(self.source)
        self.config.write_text('[]\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify_manifest(self.source)

        write_manifest(self.source)
        (self.source / "extra.txt").write_text('extra', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inventory"):
            verify_manifest(self.source)

    def test_manifest_and_archive_limits_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "byte limit"):
            write_manifest(self.source, max_bytes=9)
        write_manifest(self.source, max_bytes=10)
        archive = self.root / "valid.tar.gz"
        package_directory(self.source, archive, max_bytes=10)
        with self.assertRaisesRegex(ValueError, "byte limit"):
            verify_archive(archive, max_bytes=9)

    def test_gitignored_cache_and_other_untracked_files_still_fail_verification(self):
        write_manifest(self.source)
        (self.source / ".cache").write_text('extra', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inventory"):
            verify_manifest(self.source)

    def test_unsafe_source_paths_and_nested_archive_output_are_rejected(self):
        write_manifest(self.source)
        with self.assertRaisesRegex(ValueError, "outside its source"):
            package_directory(self.source, self.source / "nested" / "build.tar.gz")
        self.assertFalse((self.source / "nested").exists())

        link = self.source / "config-link.json"
        link.symlink_to(self.config)
        with self.assertRaisesRegex(ValueError, "contains a link"):
            verify_manifest(self.source)
        with self.assertRaisesRegex(ValueError, "regular file"):
            sha256_file(link)
        link.unlink()

        fifo = self.source / "data-fifo"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, "special file"):
            write_manifest(self.source)

    def _write_archive(self, extras=(), changed_config=None):
        manifest = write_manifest(self.source)
        archive = self.root / "modified.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            self._add_member(stream, MANIFEST_NAME, manifest.read_bytes())
            content = self.config.read_bytes() if changed_config is None else changed_config
            self._add_member(stream, "config.json", content)
            self._add_member(stream, "tasks/notes.txt", self.notes.read_bytes())
            for member, content in extras:
                if member.type == tarfile.REGTYPE:
                    member.size = len(content)
                    stream.addfile(member, io.BytesIO(content))
                else:
                    stream.addfile(member)
        return archive

    @staticmethod
    def _add_member(stream, name, content):
        member = tarfile.TarInfo(name)
        member.size = len(content)
        stream.addfile(member, io.BytesIO(content))

    def test_archive_rejects_traversal_duplicates_and_extra_members(self):
        for name, error in [
            ("../escape.txt", "Unsafe artifact path"),
            ("/absolute.txt", "Unsafe artifact path"),
            ("tasks\\..\\escape.txt", "Unsafe artifact path"),
            ("manifest.json", "duplicate member"),
            ("config.json", "duplicate member"),
            ("extra.txt", "inventory"),
        ]:
            with self.subTest(name=name):
                archive = self._write_archive([(tarfile.TarInfo(name), b"sample")])
                with self.assertRaisesRegex(ValueError, error):
                    verify_archive(archive)

    def test_archive_rejects_links_and_changed_content(self):
        for member_type in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            with self.subTest(member_type=member_type):
                member = tarfile.TarInfo("config-link.json")
                member.type = member_type
                member.linkname = "config.json"
                archive = self._write_archive([(member, b"")])
                with self.assertRaisesRegex(ValueError, "non-regular file"):
                    verify_archive(archive)
        archive = self._write_archive(changed_config=b'[]\n')
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify_archive(archive)

    def test_manifest_rejects_duplicate_and_traversal_entries(self):
        path = write_manifest(self.source)
        original = json.loads(path.read_text(encoding="utf-8"))
        with self.subTest(kind="duplicate"):
            manifest = {**original, "files": [original["files"][0]] * 2}
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unique and sorted"):
                verify_manifest(self.source)
        with self.subTest(kind="traversal"):
            manifest = {**original, "files": [{**original["files"][0], "path": "../config.json"}]}
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsafe artifact path"):
                verify_manifest(self.source)

    def test_archive_rejects_corrupted_gzip_trailer(self):
        archive = self._write_archive()
        content = bytearray(archive.read_bytes())
        content[-8] ^= 1
        archive.write_bytes(content)
        with self.assertRaises(gzip.BadGzipFile):
            verify_archive(archive)


if __name__ == "__main__":
    unittest.main()
