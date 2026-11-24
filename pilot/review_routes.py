"""Authenticated review tools registered inside the application's existing boundary."""
import uuid
from decimal import Decimal, InvalidOperation
import re
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from .field_rules import _date_value
from . import config
from .review_tools import (FIELDS, NOTICE, checklist, evidence_revision, latest_corrections,
                           metrics, record_review_snapshot, render_report, suggestions, timeline)


class Correction(BaseModel):
    review_revision: str = Field(min_length=64, max_length=64)
    field: Literal['POLICY_ID', 'MEMBER_ID', 'ADMISSION_DATE', 'DISCHARGE_DATE', 'ROOM_LIMIT', 'SUM_INSURED']
    value: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=2000)
    document_id: uuid.UUID
    page: int = Field(ge=1, strict=True)
    start_offset: int = Field(ge=0, strict=True)
    end_offset: int = Field(ge=1, strict=True)
    source: Literal['rules', 'neural']


def register_review_routes(app, connect, get_case, actor, review_revision, event):
    def documents(conn, cid):
        return conn.execute('SELECT id,filename,kind,sha256,pages FROM documents WHERE case_id=%s ORDER BY id', (cid,)).fetchall()

    def project(conn, case, docs):
        revision = review_revision(case)
        evidence = evidence_revision(case.get('result'), docs) if revision else None
        history = conn.execute('SELECT * FROM review_corrections WHERE case_id=%s ORDER BY created_at,id', (case['id'],)).fetchall()
        current = latest_corrections([c for c in history if c['evidence_revision'] == evidence])
        entries, warnings = timeline(case.get('result') or {}, current)
        return {'checklist': checklist(docs), 'timeline': entries, 'timeline_warnings': warnings,
                'corrections': history, 'current_corrections': current, 'review_revision': revision,
                'evidence_revision': evidence, 'notice': NOTICE}

    @app.get('/api/cases/{cid}/tools')
    def tools(cid: uuid.UUID):
        with connect() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            case = get_case(conn, cid)
            return project(conn, case, documents(conn, cid))

    @app.post('/api/cases/{cid}/corrections', status_code=201)
    def correct(cid: uuid.UUID, body: Correction, request: Request):
        value, reason = body.value.strip(), body.reason.strip()
        if not value or not reason or any('\x00' in text for text in (value, reason)):
            raise HTTPException(422, 'A value and review reason are required.')
        with connect() as conn:
            case = get_case(conn, cid, True)
            revision = review_revision(case)
            if not revision or body.review_revision != revision:
                raise HTTPException(409, 'The evidence review changed. Reload the case before saving.')
            docs = documents(conn, cid)
            document = next((d for d in docs if str(d['id']) == str(body.document_id)), None)
            page = next((p for p in (document or {}).get('pages') or [] if p['page'] == body.page), None)
            if page is None or not 0 <= body.start_offset < body.end_offset <= len(page['text']):
                raise HTTPException(422, 'Choose a valid source span from this case.')
            source_text = page['text'][body.start_offset:body.end_offset]
            if not source_text.strip():
                raise HTTPException(422, 'The source span must contain evidence text.')
            if body.field.endswith('_DATE'):
                try:
                    normalized, _ = _date_value(value)
                    value = normalized or value
                except (ValueError, TypeError):
                    pass
            elif body.field in {'ROOM_LIMIT', 'SUM_INSURED'}:
                digits = re.sub(r'^(?:INR|Rs\.?|₹)\s*', '', value, flags=re.IGNORECASE).replace(',', '')
                try:
                    number = Decimal(digits)
                    if not number.is_finite() or number < 0 or number > Decimal('1e20'):
                        raise InvalidOperation
                    value = format(number, '.2f')
                except InvalidOperation:
                    raise HTTPException(422, 'Enter a finite, nonnegative monetary amount.') from None
            else:
                value = value.upper()
            result = case['result']
            previous = suggestions(result, body.field, body.source)
            if body.source == 'neural' and ((result.get('specialists') or {}).get('state') != 'ready' or not previous):
                raise HTTPException(422, 'There is no neural suggestion for this field to review.')
            matched = any(c.get('value') == value and str(c.get('document_id')) == str(body.document_id)
                          and c.get('page') == body.page and c.get('start_offset') == body.start_offset
                          and c.get('end_offset') == body.end_offset for c in previous)
            outcome = 'no_prediction' if not previous else ('accepted' if matched else 'corrected')
            evidence = record_review_snapshot(conn, cid, result, docs)
            correction_id = uuid.uuid4()
            conn.execute('INSERT INTO review_corrections(id,case_id,evidence_revision,review_revision,field,value,reason,'
                         'document_id,page,start_offset,end_offset,source_text,source,outcome,previous_suggestions,actor) '
                         'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                         (correction_id, cid, evidence, revision, body.field, value, reason, body.document_id,
                          body.page, body.start_offset, body.end_offset, source_text, body.source, outcome,
                          Jsonb(previous), actor(request)))
            conn.execute('UPDATE cases SET updated_at=now() WHERE id=%s', (cid,))
            event(conn, cid, 'field_review_' + outcome, actor(request))
            new_revision = review_revision(get_case(conn, cid))
        return {'id': str(correction_id), 'status': 'recorded', 'outcome': outcome, 'review_revision': new_revision}

    @app.get('/api/cases/{cid}/report', response_class=HTMLResponse)
    def report(cid: uuid.UUID):
        with connect() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            case = get_case(conn, cid)
            docs = documents(conn, cid)
            data = project(conn, case, docs)
            acknowledged = data['review_revision'] is not None and conn.execute(
                'SELECT 1 FROM events WHERE case_id=%s AND review_revision=%s LIMIT 1',
                (cid, data['review_revision'])).fetchone() is not None
            content = render_report(case, docs, data, acknowledged, config.APP_ORIGIN)
        return HTMLResponse(content, headers={'Content-Disposition': f'attachment; filename="review-{cid}.html"'})

    @app.get('/api/review-metrics')
    def dashboard():
        with connect() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            snapshots = conn.execute('SELECT * FROM review_snapshots ORDER BY created_at,case_id,evidence_revision').fetchall()
            corrections = conn.execute('SELECT * FROM review_corrections ORDER BY created_at,id').fetchall()
            return metrics(snapshots, corrections)
