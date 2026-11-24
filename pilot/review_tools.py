"""Pure review projections and immutable evidence snapshot identity."""
import hashlib
import json
from datetime import UTC, datetime
from html import escape
from uuid import UUID

from .field_rules import _date_value

FIELDS = ('POLICY_ID', 'MEMBER_ID', 'ADMISSION_DATE', 'DISCHARGE_DATE', 'ROOM_LIMIT', 'SUM_INSURED')
NOTICE = 'Synthetic hospitalization reimbursement demonstration. Reviewer agreement is not ground-truth accuracy or coverage authorization.'


def evidence_revision(result, documents):
    payload = {'result': result, 'documents': sorted(
        [{'id': str(d['id']), 'sha256': d.get('sha256'), 'pages': d.get('pages')} for d in documents],
        key=lambda d: d['id'])}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def record_review_snapshot(conn, case_id, result, documents):
    from psycopg.types.json import Jsonb
    revision = evidence_revision(result, documents)
    conn.execute('INSERT INTO review_snapshots(case_id,evidence_revision,result) VALUES(%s,%s,%s) '
                 'ON CONFLICT(case_id,evidence_revision) DO NOTHING', (case_id, revision, Jsonb(result)))
    return revision


def checklist(documents):
    kinds = {d['kind'] for d in documents}
    return [{'kind': kind, 'label': label, 'present': kind in kinds, 'required': required}
            for kind, label, required in (
                ('schedule', 'Policy schedule', True), ('policy', 'Policy wording', True),
                ('claim_form', 'Claim form', True), ('discharge', 'Discharge summary', True),
                ('bill', 'Hospital bill', True), ('endorsement', 'Endorsements', False),
                ('receipt', 'Receipts', False))]


def suggestions(result, field, source):
    if source == 'neural':
        return ((result.get('specialists') or {}).get('suggestions') or {}).get(field, [])
    return (((result.get('review_fields') or {}).get('fields') or {}).get(field) or {}).get('candidates', [])


def latest_corrections(corrections):
    latest = {}
    for correction in corrections:
        latest[correction['field']] = correction
    return list(latest.values())


def timeline(result, corrections):
    entries = []
    for field in ('ADMISSION_DATE', 'DISCHARGE_DATE'):
        for source in ('rules', 'neural'):
            entries.extend(dict(candidate, field=field, source=source, confirmed=False)
                           for candidate in suggestions(result, field, source))
        entries.extend(dict(c, source='reviewer', confirmed=True) for c in corrections if c['field'] == field)
    for entry in entries:
        value = entry.get('value') or entry.get('source_text') or ''
        try:
            normalized, reason = _date_value(value)
        except (ValueError, TypeError, OverflowError):
            normalized, reason = None, 'unrecognized_date'
        entry.update(normalized_date=normalized, unresolved_reason=reason)
    entries.sort(key=lambda e: (e['normalized_date'] is None, e['normalized_date'] or '', e['field']))
    dates = {f: [e['normalized_date'] for e in entries if e['field'] == f and e['normalized_date']]
             for f in ('ADMISSION_DATE', 'DISCHARGE_DATE')}
    warnings = ['discharge_before_admission'] if any(d < a for d in dates['DISCHARGE_DATE'] for a in dates['ADMISSION_DATE']) else []
    return entries, warnings


def metrics(snapshots, corrections):
    latest = {}
    for correction in corrections:
        latest[(str(correction['case_id']), correction['evidence_revision'], correction['field'])] = correction
    manual_fields = sum(c['outcome'] == 'no_prediction' for c in latest.values())
    outcomes = [c for c in latest.values() if c['outcome'] != 'no_prediction']
    def counts(rows):
        corrected = sum(r['outcome'] == 'corrected' for r in rows)
        return {'reviewed_fields': len(rows), 'accepted': len(rows) - corrected, 'corrected': corrected,
                'correction_rate': corrected / len(rows) if rows else None}
    by_snapshot = {(str(s['case_id']), s['evidence_revision']): s['result'] for s in snapshots}
    groups = {}
    neural = [r for r in outcomes if r['source'] == 'neural']
    for row in neural:
        result = by_snapshot.get((str(row['case_id']), row['evidence_revision']), {})
        checkpoint = (result.get('specialists') or {}).get('checkpoint')
        identity = checkpoint if isinstance(checkpoint, str) else json.dumps(checkpoint, sort_keys=True)
        groups.setdefault((identity, row['field']), []).append(row)
    disagreements = 0
    for snapshot in snapshots:
        for field in FIELDS:
            rules = {c.get('value') for c in suggestions(snapshot['result'], field, 'rules') if c.get('value') is not None}
            models = {c.get('value') for c in suggestions(snapshot['result'], field, 'neural') if c.get('value') is not None}
            disagreements += bool(rules and models and rules != models)
    return {**counts(outcomes), 'neural': counts(neural), 'by_checkpoint': [
        {'checkpoint': key[0], 'field': key[1], **counts(rows)} for key, rows in sorted(groups.items())],
        'manual_fields': manual_fields, 'disagreements': disagreements,
        'inference_runs': sum((s['result'].get('specialists') or {}).get('state') in {'ready', 'unavailable'} for s in snapshots),
        'unavailable_runs': sum((s['result'].get('specialists') or {}).get('state') == 'unavailable' for s in snapshots),
        'notice': NOTICE, 'denominator': 'Latest reviewed field per case and evidence snapshot; unreviewed predictions excluded.'}


def render_report(case, documents, tools, acknowledged, origin):
    esc = lambda value: escape(str(value if value is not None else '—'), quote=True)
    cid = str(UUID(str(case['id'])))
    inventory = {str(d['id']): d for d in documents}
    def source(item):
        did = str(item.get('document_id', ''))
        if did not in inventory:
            return esc(item.get('source_text', ''))
        url = origin.rstrip('/') + '/api/cases/' + cid + '/documents/' + str(UUID(did))
        page = item.get('page')
        if isinstance(page, int) and page > 0:
            url += '#page=' + str(page)
        name = inventory[did]['filename']
        label = str(name) + (', page ' + str(page) if page else '')
        span = (' (characters ' + str(item['start_offset']) + '–' + str(item['end_offset']) + ')'
                if 'start_offset' in item else '')
        return '<a href="' + esc(url) + '">' + esc(label) + '</a>' + esc(span) + '<br>' + esc(item.get('source_text', ''))
    def table(title, headings, rows):
        body = ''.join('<tr>' + ''.join('<td>' + cell + '</td>' for cell in row) + '</tr>' for row in rows)
        return '<h2>' + esc(title) + '</h2>' + ('<p>No data.</p>' if not body else
            '<table border="1" cellpadding="6"><thead><tr>' + ''.join('<th>' + esc(h) + '</th>' for h in headings) +
            '</tr></thead><tbody>' + body + '</tbody></table>')
    result = case.get('result') or {}
    specialist = result.get('specialists') or {'state': 'disabled'}
    html = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Review report</title><body><h1>' +
            esc(case['title']) + '</h1><p>' + esc(NOTICE) + '</p><p>Case: ' + esc(cid) + '</p><p>' +
            esc(case.get('description', '')) + '</p><p>Generated: ' + esc(datetime.now(UTC).isoformat()) +
            '</p><p>Review revision: ' + esc(tools['review_revision']) + '</p><p>Acknowledged: ' + esc(acknowledged) +
            '</p><p>Original links require authenticated access to the application.</p>')
    html += table('Document inventory', ['Document', 'Kind'], [(source({'document_id': d['id']}), esc(d['kind'])) for d in documents])
    html += table('Synthetic checklist', ['Document type', 'Present', 'Requirement'],
                  [(esc(i['label']), esc(i['present']), esc('Required in this demonstration' if i['required'] else 'Optional')) for i in tools['checklist']])
    for kind, title in [('rules', 'Rule field candidates'), ('neural', 'Neural field suggestions')]:
        html += table(title, ['Field', 'Value', 'Evidence'],
                      [(esc(field), esc(c.get('value')), source(c)) for field in FIELDS for c in suggestions(result, field, kind)])
    html += '<p>Neural availability: ' + esc(specialist.get('state')) + '; checkpoint: ' + esc(specialist.get('checkpoint')) + '</p>'
    html += table('Timeline', ['Field', 'Value', 'Status', 'Evidence'],
                  [(esc(e['field']), esc(e.get('value') or e.get('source_text')), esc('Reviewer confirmed' if e.get('confirmed') else e.get('unresolved_reason') or 'Candidate'), source(e)) for e in tools['timeline']])
    html += '<p>Timeline warnings: ' + esc(', '.join(tools['timeline_warnings']) or 'None') + '</p>'
    html += table('Correction history', ['Field', 'Value', 'Outcome', 'Reason', 'Reviewer / time', 'Evidence'],
                  [(esc(c['field']), esc(c['value']), esc(c['outcome']), esc(c['reason']), esc(str(c['actor']) + ' / ' + str(c['created_at'])), source(c)) for c in tools['corrections']])
    html += table('Extraction warnings', ['Document', 'Page', 'Warnings'],
                  [(esc(w.get('filename')), esc(w.get('page')), esc(', '.join(w.get('quality_reasons', [])))) for w in result.get('extraction_warnings', [])])
    if result.get('findings'):
        html += '<h2>Additional findings</h2><pre>' + esc(json.dumps(result['findings'], indent=2, default=str)) + '</pre>'
    return html + '</body></html>'
