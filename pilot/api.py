import hashlib
import hmac
import json
import os
import uuid
import tempfile
import threading
from datetime import UTC
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from . import config
from .core import KINDS
from .db import connect
from .storage import get_storage, materialize
from psycopg.types.json import Jsonb
from .pdf_review import pdf_review_available, review_documents
from .extract import ExtractionError
from . import auth
from .inference import connection_status
from .storage_cleanup import cleanup_pending,cleanup_tick
from .specialist_client import review_specialists, specialist_status
from .review_tools import record_review_snapshot

app = FastAPI(title='PolicyPilot private pilot', docs_url=None, redoc_url=None, openapi_url=None)
STATIC = Path(__file__).parent/'static'

class TemporaryFileResponse(FileResponse):
    def __init__(self, document, path, **kwargs):
        super().__init__(path, **kwargs)
        self.document = document

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.document.__exit__(None,None,None)

@app.middleware('http')
async def boundary(request: Request, call_next):
    try:
        response=await authorize(request,call_next)
    except Exception:
        # No request bodies, filenames, model output or exception strings in logs.
        response=JSONResponse({'detail':'Service unavailable. Retry or contact the operator.'},status_code=503)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Strict-Transport-Security']='max-age=31536000'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'"
    return response

async def authorize(request,call_next):
    if request.method not in {'GET','HEAD','OPTIONS'} and request.headers.get('origin') != config.APP_ORIGIN:
        return JSONResponse({'detail':'Origin rejected'},status_code=403)
    if config.AUTH_MODE == 'session':
        public_get = request.method in {'GET','HEAD'} and request.url.path in {
            '/login','/login.js','/login.css','/style.css','/theme.css','/healthz'}
        public_login = request.method == 'POST' and request.url.path == '/api/auth/login'
        if not public_get and not public_login:
            user=await run_in_threadpool(auth.current_user,request.cookies.get(auth.COOKIE,''),
                                        connect,config.PILOT_USER,config.PILOT_PASSWORD_HASH)
            if not user:
                if request.method in {'GET','HEAD'} and request.url.path == '/':
                    return RedirectResponse('/login',status_code=303)
                return JSONResponse({'detail':'Authentication required'},status_code=401)
            request.state.reviewer=user
    else:
        token=request.headers.get('x-proxy-token','')
        if not hmac.compare_digest(token.encode(),config.PROXY_TOKEN.encode()):
            return JSONResponse({'detail':'Authentication required'},status_code=401)
    return await call_next(request)

def actor(request):
    if config.AUTH_MODE == 'session':
        return request.state.reviewer
    return request.headers.get('x-reviewer','pilot-reviewer')[:80]

@app.get('/healthz')
def healthz():
    with connect() as conn: conn.execute('SELECT 1')
    return {'status':'ok','deployment_mode':'pdf-field-review'}

@app.get('/login')
def login_page():
    if config.AUTH_MODE != 'session': raise HTTPException(404)
    return FileResponse(STATIC/'login.html')

@app.post('/api/auth/login')
async def login(request:Request):
    if config.AUTH_MODE != 'session': raise HTTPException(404)
    if request.headers.get('content-type','').split(';')[0] != 'application/json':
        raise HTTPException(415,'JSON required')
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>8192: raise HTTPException(413,'Login request too large')
        body.extend(chunk)
    try:
        values=json.loads(body)
        username,password=values['username'],values['password']
        if not isinstance(username,str) or not isinstance(password,str) or len(username)>80 or len(password)>1024:
            raise ValueError()
        username.encode('utf-8'); password.encode('utf-8')
    except (ValueError,TypeError,KeyError):
        raise HTTPException(422,'Username and password required')
    token,error=await run_in_threadpool(auth.login,username,password,connect,
                                      config.PILOT_USER,config.PILOT_PASSWORD_HASH)
    if error:
        return JSONResponse({'detail':'Too many attempts. Try again in 15 minutes.' if error=='throttled'
                             else 'Invalid username or password'},
                            status_code=429 if error=='throttled' else 401)
    response=JSONResponse({'status':'signed_in'})
    response.set_cookie(auth.COOKIE,token,max_age=auth.SESSION_SECONDS,
                        secure=True,httponly=True,samesite='strict',path='/')
    return response

@app.post('/api/auth/logout',status_code=204)
def logout(request:Request):
    if config.AUTH_MODE != 'session': raise HTTPException(404)
    auth.logout(request.cookies.get(auth.COOKIE,''),connect)
    response=Response(status_code=204)
    response.delete_cookie(auth.COOKIE,secure=True,httponly=True,samesite='strict',path='/')
    return response

@app.get('/api/auth/me')
def me(request:Request):
    return {'username':actor(request),'auth_mode':config.AUTH_MODE,'model_operator':is_operator(request)}

def is_operator(request):
    # Session-only maintenance: proxy headers cannot grant operator access.
    return (config.AUTH_MODE=='session' and bool(os.environ.get('MODEL_OPERATOR'))
            and actor(request)==os.environ['MODEL_OPERATOR'])

def require_operator(request):
    if not is_operator(request): raise HTTPException(403,'Operator access required')

@app.get('/api/inference')
def inference_status():
    return connection_status()

@app.get('/api/storage/cleanup')
def cleanup_status(request:Request):
    require_operator(request)
    with connect() as conn:
        return conn.execute('SELECT count(*) AS pending, '
                            'count(*) FILTER (WHERE eligible_at<=now()) AS eligible FROM storage_cleanup').fetchone()

@app.post('/api/storage/cleanup')
def cleanup_retry(request:Request):
    require_operator(request)
    # One bounded pass. Failed objects retain their retry timestamp and intent.
    return cleanup_pending(batch_size=1)

@app.get('/api/cases/{cid}/messages')
def messages(cid:uuid.UUID):
    with connect() as conn:
        get_case(conn,cid)
        docs=conn.execute('SELECT id,sha256 FROM documents WHERE case_id=%s',(cid,)).fetchall()
        snap=hashlib.sha256(json.dumps(sorted((str(d['id']),d['sha256']) for d in docs),
                                      separators=(',',':')).encode()).hexdigest()
        rows=conn.execute('SELECT id,question,response,state,snapshot,created_at FROM case_messages '
                          'WHERE case_id=%s ORDER BY id LIMIT 100',(cid,)).fetchall()
        for row in rows:
            row['stale']=row.pop('snapshot')!=snap
        return rows

def get_case(conn,cid,lock=False):
    row=conn.execute('SELECT * FROM cases WHERE id=%s'+(' FOR UPDATE' if lock else ''),(cid,)).fetchone()
    if not row: raise HTTPException(404,'Case not found')
    return row

def event(conn,cid,action,user):
    conn.execute('INSERT INTO events(case_id,action,actor) VALUES(%s,%s,%s)',(cid,action,user))


ACKNOWLEDGEMENT_ACTION = 'draft_review_acknowledged_not_coverage_authorization'


def review_revision(case):
    if case['state'] != 'ready' or not case['result']:
        return None
    updated = case['updated_at'].astimezone(UTC).isoformat()
    return hashlib.sha256(f"{case['id']}:{updated}".encode()).hexdigest()


class NewCase(BaseModel):
    title: str = Field(min_length=3,max_length=120)
    description: str = Field(min_length=20,max_length=3000)

@app.get('/api/health')
def health():
    with connect() as conn: conn.execute('SELECT 1')
    return {'status':'ok','mode':'single-workspace pilot'}

@app.get('/api/readiness')
def readiness():
    with connect() as conn: conn.execute('SELECT 1')
    state=connection_status()
    return {'database':'ready','inference':state['state'],'model':state['model'],
            'processing_enabled':state['processing_enabled'],'pdf_review_enabled':pdf_review_available(),
            'specialists':specialist_status()}

@app.post('/api/cases',status_code=201)
def create_case(body:NewCase,request:Request):
    cid=uuid.uuid4()
    with connect() as conn:
        if conn.execute('SELECT count(*) AS n FROM cases').fetchone()['n']>=100:
            raise HTTPException(409,'Pilot case limit reached; delete unused cases first')
        conn.execute('INSERT INTO cases(id,title,description) VALUES(%s,%s,%s)',(cid,body.title.strip(),body.description.strip()))
        event(conn,cid,'case_created',actor(request))
    return {'id':str(cid)}

@app.get('/api/cases')
def cases(background:BackgroundTasks):
    background.add_task(cleanup_tick)
    with connect() as conn:
        return conn.execute('SELECT id,title,state,created_at,updated_at FROM cases ORDER BY created_at DESC LIMIT 100').fetchall()

@app.get('/api/cases/{cid}')
def detail(cid:uuid.UUID):
    with connect() as conn:
        # Keep result citations, extracted pages and audit events on one snapshot.
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        row=get_case(conn,cid)
        row['documents']=conn.execute('SELECT id,filename,kind,bytes,pages FROM documents WHERE case_id=%s ORDER BY filename',(cid,)).fetchall()
        row['events']=conn.execute('SELECT action,actor,created_at FROM events WHERE case_id=%s ORDER BY id DESC LIMIT 30',(cid,)).fetchall()
        revision = review_revision(row)
        row['review_revision'] = revision
        row['review_acknowledged'] = revision is not None and conn.execute(
            'SELECT 1 FROM events WHERE case_id=%s AND review_revision=%s LIMIT 1', (cid, revision),
        ).fetchone() is not None
    if row['state'] in {'queued','processing'} and not config.PROCESSING_ENABLED and not row['error']:
        row['error'] = ('Model processing is disabled on this service. You can download the originals. '
                        'Contact the operator about the previous processing job.')
    return row

@app.put('/api/cases/{cid}/documents',status_code=201)
async def upload(cid:uuid.UUID,request:Request,kind:str,filename:str):
    if kind not in KINDS: raise HTTPException(422,'Choose a supported document type')
    filename=Path(filename.replace('\\','/')).name[:120]
    if not filename.lower().endswith('.pdf'): raise HTTPException(415,'Upload a PDF, including scanned PDFs')
    if request.headers.get('content-type','').split(';')[0]!='application/pdf': raise HTTPException(415,'PDF content type required')
    did=uuid.uuid4(); staging=tempfile.TemporaryDirectory(prefix='claim-upload-')
    path=Path(staging.name)/'upload.pdf'; size=0; digest=hashlib.sha256(); head=b''
    try:
        with path.open('xb') as output:
            os.chmod(path,0o600)
            async for chunk in request.stream():
                size+=len(chunk)
                if size>config.MAX_FILE: raise HTTPException(413,'Maximum PDF size is 10 MB')
                head=(head+chunk)[:8]; digest.update(chunk); output.write(chunk)
        if not head.startswith(b'%PDF-') or size<20: raise HTTPException(415,'Invalid PDF signature')
        # Persist cleanup intent before touching object storage. A killed process or
        # uncertain DB commit cannot leave an untracked object indefinitely.
        with connect() as conn:
            conn.execute('INSERT INTO storage_cleanup(document_id) VALUES(%s)',(did,))
        with connect() as conn:
            conn.execute('SELECT document_id FROM storage_cleanup WHERE document_id=%s FOR UPDATE',(did,))
            row=get_case(conn,cid,True)
            if row['state'] in {'queued','processing'}: raise HTTPException(409,'Wait for processing to finish')
            docs=conn.execute('SELECT sha256 FROM documents WHERE case_id=%s',(cid,)).fetchall()
            if len(docs)>=config.MAX_DOCS: raise HTTPException(409,'Maximum 12 PDFs per case')
            if any(d['sha256']==digest.hexdigest() for d in docs): raise HTTPException(409,'This PDF is already attached')
            get_storage().put(did,path)
            conn.execute('INSERT INTO documents(id,case_id,filename,kind,sha256,bytes) VALUES(%s,%s,%s,%s,%s,%s)',(did,cid,filename,kind,digest.hexdigest(),size))
            conn.execute('UPDATE documents SET pages=NULL WHERE case_id=%s AND pages IS NOT NULL', (cid,))
            conn.execute("UPDATE cases SET state='draft',result=NULL,error=NULL,updated_at=now() WHERE id=%s",(cid,))
            event(conn,cid,'document_uploaded',actor(request))
            conn.execute('DELETE FROM storage_cleanup WHERE document_id=%s',(did,))
    finally:
        staging.cleanup()
    return {'id':str(did)}

@app.get('/api/cases/{cid}/documents/{did}')
def original(cid:uuid.UUID,did:uuid.UUID):
    with connect() as conn:
        row=conn.execute('SELECT filename,bytes,sha256 FROM documents WHERE id=%s AND case_id=%s',(did,cid)).fetchone()
        if not row: raise HTTPException(404,'Document not found')
    document=materialize(get_storage(),did,row['bytes'],row['sha256'],config.MAX_FILE)
    path=document.__enter__()
    try:
        return TemporaryFileResponse(document,path,media_type='application/pdf',filename=row['filename'],
                                     content_disposition_type='attachment')
    except BaseException:
        document.__exit__(None,None,None)
        raise

# Bound concurrent Poppler parses on the single-process demo service.
pdf_review_slot = threading.BoundedSemaphore(1)


def review_document_rows(conn, cid):
    return conn.execute(
        'SELECT id,filename,kind,bytes,sha256 FROM documents WHERE case_id=%s ORDER BY id', (cid,),
    ).fetchall()


@app.post('/api/cases/{cid}/pdf-review')
def run_pdf_review(cid: uuid.UUID, request: Request):
    if not pdf_review_slot.acquire(blocking=False):
        raise HTTPException(409, 'Another PDF review is running. Try again shortly.')
    try:
        with connect() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            case = get_case(conn, cid)
            if case['state'] == 'ready' and (case['result'] or {}).get('source') == 'native_pdf_fields':
                return {'state': 'ready'}
            if case['state'] not in {'draft', 'failed'}:
                raise HTTPException(409, 'This case already has an assessment or is queued for model processing.')
            documents = review_document_rows(conn, cid)
        if not documents:
            raise HTTPException(422, 'Attach at least one PDF.')
        if len(documents) > config.MAX_DOCS:
            raise HTTPException(422, f'Review supports at most {config.MAX_DOCS} PDFs per case.')
        if not pdf_review_available():
            raise HTTPException(503, 'PDF review is unavailable on this service. You can download the originals.')
        extracted = [dict(document) for document in documents]
        try:
            result = review_documents(extracted, get_storage(), max_file=config.MAX_FILE,
                                      max_pages=config.MAX_PAGES)
        except ExtractionError as exc:
            raise HTTPException(422, str(exc)) from None
        # Specialist availability is independent of the optional generative worker.
        # Preserve the original rules and show neural suggestions separately.
        result['specialists'] = review_specialists(extracted)
        with connect() as conn:
            current = get_case(conn, cid, True)
            if (current['state'] != case['state'] or current['updated_at'] != case['updated_at']
                    or review_document_rows(conn, cid) != documents):
                raise HTTPException(409, 'The case changed during review. Reopen it to see the latest documents.')
            for document in extracted:
                conn.execute('UPDATE documents SET pages=%s WHERE id=%s AND case_id=%s',
                             (Jsonb(document['pages']), document['id'], cid))
            conn.execute("UPDATE cases SET state='ready',result=%s,error=NULL,updated_at=now() WHERE id=%s",
                         (Jsonb(result), cid))
            record_review_snapshot(conn, cid, result, extracted)
            event(conn, cid, 'pdf_fields_reviewed', actor(request))
        return {'state': 'ready'}
    finally:
        pdf_review_slot.release()


@app.post('/api/cases/{cid}/assess',status_code=202)
def assess(cid:uuid.UUID,request:Request):
    if not config.PROCESSING_ENABLED:
        raise HTTPException(503,'Model processing is not connected. Your documents remain saved.')
    with connect() as conn:
        row=get_case(conn,cid,True)
        if row['state'] in {'queued','processing'}: return {'state':row['state']}
        kinds={d['kind'] for d in conn.execute('SELECT kind FROM documents WHERE case_id=%s',(cid,)).fetchall()}
        if not {'policy','schedule'}.issubset(kinds) or not (kinds & {'bill','discharge'}):
            raise HTTPException(422,'Attach policy wording, schedule and at least a bill or discharge summary')
        conn.execute("UPDATE cases SET state='queued',result=NULL,error=NULL,updated_at=now() WHERE id=%s",(cid,))
        event(conn,cid,'assessment_queued',actor(request))
    return {'state':'queued'}


class ReviewAcknowledgement(BaseModel):
    review_revision: str = Field(max_length=64)


@app.post('/api/cases/{cid}/review')
def review(cid: uuid.UUID, request: Request, body: ReviewAcknowledgement | None = None):
    with connect() as conn:
        revision = review_revision(get_case(conn, cid, True))
        if not revision:
            raise HTTPException(409, 'Complete the PDF review or assessment first.')
        if body is None or body.review_revision != revision:
            raise HTTPException(409, 'This evidence review has changed. Reopen the case and check the current evidence before recording your acknowledgement.')
        reviewer = actor(request)
        recorded = conn.execute(
            'SELECT 1 FROM events WHERE case_id=%s AND review_revision=%s AND actor=%s LIMIT 1',
            (cid, revision, reviewer),
        ).fetchone()
        if not recorded:
            conn.execute(
                'INSERT INTO events(case_id,action,actor,review_revision) VALUES(%s,%s,%s,%s)',
                (cid, ACKNOWLEDGEMENT_ACTION, reviewer, revision),
            )
    return {'status': 'recorded'}

@app.delete('/api/cases/{cid}',status_code=204)
def delete_case(cid:uuid.UUID,background:BackgroundTasks):
    with connect() as conn:
        row=get_case(conn,cid,True)
        if row['state'] in {'queued','processing'}: raise HTTPException(409,'Wait for processing before deleting')
        docs=conn.execute('SELECT id FROM documents WHERE case_id=%s',(cid,)).fetchall()
        # Revoke application access now; retry physical removal in the worker.
        # Backups and bucket versions have separately configured retention.
        for d in docs:
            conn.execute('INSERT INTO storage_cleanup(document_id,eligible_at) VALUES(%s,now()) '
                         'ON CONFLICT(document_id) DO UPDATE SET eligible_at=now()', (d['id'],))
        conn.execute('DELETE FROM cases WHERE id=%s',(cid,))
    background.add_task(cleanup_tick)

from .review_routes import register_review_routes

register_review_routes(app, lambda: connect(), get_case, actor, review_revision, event)

app.mount('/',StaticFiles(directory=STATIC,html=True),name='web')
