import json
import time
import httpx
import psycopg
from psycopg.types.json import Jsonb
from . import config
from .db import connect
from .storage import get_storage, materialize
from .storage_cleanup import cleanup_pending
from .inference import generate
from .core import make_chunks, select_evidence, coverage_report, validate_output
from .extract import extract_pdf, ExtractionError, MIN_ALPHANUMERIC
from .field_rules import extract_review_fields

from .review_prompt import SCHEMA, SYSTEM

def process(case):
    cid=case['id']
    with connect() as conn:
        docs=conn.execute('SELECT * FROM documents WHERE case_id=%s ORDER BY id',(cid,)).fetchall()
    page_count=0
    for doc in docs:
        doc['id']=str(doc['id'])
        with materialize(get_storage(),doc['id'],doc['bytes'],doc['sha256'],config.MAX_FILE) as path:
            pages=extract_pdf(path,config.MAX_PAGES)
        page_count+=len(pages)
        if page_count>60: raise ExtractionError('Case exceeds the 60-page processing limit')
        doc['pages']=pages
        if doc['kind'] in {'policy','schedule'} and not any(
                sum(c.isalnum() for c in p['text']) >= MIN_ALPHANUMERIC for p in pages):
            raise ExtractionError('Policy or schedule text is unreadable; provide a clearer PDF')
        with connect() as conn:
            conn.execute('UPDATE documents SET pages=%s WHERE id=%s',(Jsonb(pages),doc['id']))
            conn.execute('INSERT INTO events(case_id,action,actor) VALUES(%s,%s,%s)',(cid,'document_text_extracted','local-worker'))
    chunks=make_chunks(docs)
    if not chunks: raise ExtractionError('No readable text found; supply clearer documents')
    selected,truncated=select_evidence(chunks,case['description'])
    coverage=coverage_report(chunks,selected)
    # A chunk-only report cannot see an uploaded PDF with no readable text.
    readable_documents={str(c['document_id']) for c in chunks}
    unreadable_documents=sorted(d['id'] for d in docs if d['id'] not in readable_documents)
    coverage['unreadable_document_ids']=unreadable_documents
    if not {'policy','schedule'}.issubset({e['kind'] for e in selected}):
        raise ExtractionError('Policy and schedule evidence did not fit the review context; reduce the case size')
    with connect() as conn:
        conn.execute('INSERT INTO events(case_id,action,actor) VALUES(%s,%s,%s)',(cid,'private_inference_started','local-worker'))
    response=generate(SYSTEM,json.dumps({'claim_description':case['description'],'excerpts':selected,
        'partial_context':truncated,'evidence_coverage':coverage},ensure_ascii=False),SCHEMA)
    result=validate_output(response,selected,truncated)
    result['review_fields']=extract_review_fields(docs)
    result['model']=config.MODEL
    result['retrieval']='case-scoped priority lexical selection v2'
    result['evidence_coverage']=coverage
    result['evidence_budget']={'unit':'text_characters','limit':12000,
        'used':sum(len(e['text']) for e in selected),'model_token_budget_verified':False}
    result['ocr_pages']=sum(p['method']=='ocr' for d in docs for p in d['pages'])
    result['total_pages']=page_count
    result['evidence_ids']=[e['id'] for e in selected]
    result['parser_versions']=sorted({p.get('parser_version','legacy-unversioned') for d in docs for p in d['pages']})
    result['extraction_warnings']=[{'document_id':d['id'],'filename':d['filename'],
        'page':p['page'],'method':p['method'],'quality_reasons':p.get('quality_reasons',[])}
        for d in docs for p in d['pages'] if p.get('needs_verification')]
    if result['ocr_pages']:
        result['questions'].insert(0,'Verify text extracted from scanned pages against the originals before relying on it.')
    elif result['extraction_warnings']:
        result['questions'].insert(0,'Some extracted pages need verification against the originals before relying on them.')
    if coverage['omitted_document_ids']:
        result['questions'].insert(0,f"{len(coverage['omitted_document_ids'])} uploaded documents had no selected excerpts. Review those originals before deciding.")
    if unreadable_documents:
        result['questions'].insert(0,f"{len(unreadable_documents)} uploaded documents had no readable extracted text. Provide clearer copies and review the originals.")
    with connect() as conn:
        conn.execute("UPDATE cases SET state='ready',result=%s,error=NULL,updated_at=now() WHERE id=%s",(Jsonb(result),cid))
        conn.execute('INSERT INTO events(case_id,action,actor) VALUES(%s,%s,%s)',(cid,'assessment_ready_for_review','local-worker'))

def main():
    # One worker per deployment; lock lasts as long as this dedicated connection.
    # Restart recovers interrupted work rather than losing in-process background tasks.
    with psycopg.connect(config.DATABASE_URL,autocommit=True) as lock:
        lock.execute('SELECT pg_advisory_lock(519825)')
        with connect() as conn:
            conn.execute("UPDATE cases SET state='queued',error=NULL WHERE state='processing'")
        while True:
            lock.execute('SELECT 1')
            cleanup_pending()
            if not config.PROCESSING_ENABLED:
                time.sleep(5);continue
            with connect() as conn:
                case=conn.execute("SELECT * FROM cases WHERE state='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
                if case:
                    conn.execute("UPDATE cases SET state='processing',updated_at=now() WHERE id=%s",(case['id'],))
                    conn.execute('INSERT INTO events(case_id,action,actor) VALUES(%s,%s,%s)',(case['id'],'processing_started','local-worker'))
            if not case:
                time.sleep(2); continue
            try: process(case)
            except Exception as exc:
                if isinstance(exc,ExtractionError): message=str(exc)
                elif isinstance(exc,(ValueError,KeyError)): message='Model response could not be verified. Review documents or retry.'
                else: message='Private processing unavailable. Check model readiness and retry.'
                with connect() as conn:
                    conn.execute("UPDATE cases SET state='failed',error=%s,result=NULL,updated_at=now() WHERE id=%s",(message,case['id']))
                    conn.execute('INSERT INTO events(case_id,action,actor) VALUES(%s,%s,%s)',(case['id'],'processing_failed','local-worker'))

if __name__=='__main__': main()
