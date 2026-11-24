"""External live test: authentication, CSRF, upload, OCR/model pipeline and persistence.
Run only against your own deployment. Password is read interactively, never via argv.
"""
import argparse
import socket
import base64
import getpass
import http.cookiejar
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

parser=argparse.ArgumentParser()
parser.add_argument('origin',help='https://claims.your-domain.example')
parser.add_argument('--case',choices=['SYN-C001','SYN-C003'],default='SYN-C001')
parser.add_argument('--auth-mode',choices=['session','proxy'],default='session')
parser.add_argument('--run-inference',action='store_true',help='Explicitly invoke potentially billable inference; requires a separately verified budget')
parser.add_argument('--review-fields', action='store_true', help='Verify embedded PDF fields and citations on the live app')
parser.add_argument('--cleanup-only', action='store_true',
                    help='Retry up to 20 eligible document deletions using an operator session')
args=parser.parse_args()
if args.review_fields and args.run_inference:
    parser.error('Choose either field review or inference')
if args.cleanup_only and (args.auth_mode!='session' or args.review_fields or args.run_inference):
    parser.error('Cleanup requires session auth and runs independently of review and inference')
origin=args.origin.rstrip('/')
parsed=urllib.parse.urlsplit(origin)
if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
    raise SystemExit('An exact HTTPS origin is required')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None
cookies=http.cookiejar.CookieJar()
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies),NoRedirect())
anonymous=urllib.request.build_opener(NoRedirect())

def request(path,method='GET',body=None,content='application/json',authenticated=True,csrf=True,raw=False,expect_error=None):
    headers={'Content-Type':content}
    if authenticated and args.auth_mode=='proxy': headers['Authorization']='Basic '+auth
    if csrf: headers['Origin']=origin
    req=urllib.request.Request(origin+path,data=body,headers=headers,method=method)
    try:
        response=(opener if authenticated else anonymous).open(req,timeout=30)
    except urllib.error.HTTPError as exc:
        with exc:
            if exc.code == expect_error:
                return
            if path == '/api/auth/login' and exc.code == 401:
                raise SystemExit('Login rejected (HTTP 401). Check the reviewer username and app password.') from None
            raise SystemExit(f'{method} {path.split("?")[0]} returned HTTP {exc.code}.') from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason,socket.gaierror):
            raise SystemExit('DNS lookup failed while connecting to '+parsed.hostname+'. Check DNS and any configured HTTPS proxy.') from None
        raise SystemExit('Could not connect to '+parsed.hostname+'. Check your internet connection, then retry.') from None
    except TimeoutError:
        raise SystemExit('Connection to '+parsed.hostname+' timed out. Check the service and internet connection, then retry.') from None
    with response as r:
        if expect_error is not None:
            raise SystemExit(f'{method} {path} returned HTTP {r.status}; expected {expect_error}.')
        data=r.read()
        return data if raw else json.loads(data) if data else None

request('/api/cases', authenticated=False, expect_error=401)
print('PASS: protected API reachable; anonymous request rejected.')
user=input('Pilot username [reviewer]: ').strip() or 'reviewer'
password=getpass.getpass('Pilot password: ')
if args.auth_mode=='proxy':
    auth=base64.b64encode((user+':'+password).encode()).decode()
if args.auth_mode=='session':
    request('/api/auth/login','POST',json.dumps({'username':user,'password':password}).encode())
    identity=request('/api/auth/me')
    assert identity['username']==user,'Server-side identity did not match'
    password=None; auth=None
if args.cleanup_only:
    try:
        if not identity.get('model_operator'):
            raise SystemExit('Document cleanup requires an operator account.')
        path='/api/storage/cleanup'
        before=request(path)
        for _ in range(min(before['eligible'],20)):
            result=request(path,'POST')
            if result['failed']:
                raise SystemExit('A document deletion failed. The server kept its retry entry.')
            if result['removed']+result['retained']==0:
                break
        after=request(path)
        if after['pending']:
            raise SystemExit(f"Cleanup still has {after['pending']} pending and {after['eligible']} eligible.")
        print(f"PASS: cleanup queue empty ({before['pending']} pending at start).")
    finally:
        request('/api/auth/logout','POST')
    raise SystemExit(0)
request('/api/cases', 'POST', b'{}', csrf=False, expect_error=403)
if args.run_inference:
    ready=request('/api/readiness')
    assert ready['inference'] in {'ready','model_registered_not_generation_tested'},'Private model not registered'
case=request('/api/cases','POST',json.dumps({'title':'Live verification '+args.case,'description':'Review this fictional hospitalization claim against its attached policy and identify missing or conflicting evidence.'}).encode())
cid=case['id']
root=Path(__file__).resolve().parents[1]/'data/synthetic/exemplars'/args.case
kinds={'01':'schedule','02':'policy','03':'endorsement','04':'other','05':'discharge','06':'bill','07':'receipt','08':'other','09':'other'}
if args.review_fields:
    kinds['04'] = 'claim_form'
pdfs=sorted(root.glob('*.pdf'))
assert pdfs,'Synthetic bundle is missing'
for pdf in pdfs:
    query=urllib.parse.urlencode({'kind':kinds[pdf.name[:2]],'filename':pdf.name})
    request(f'/api/cases/{cid}/documents?{query}','PUT',pdf.read_bytes(),'application/pdf')
if not args.run_inference:
    if args.review_fields:
        request(f'/api/cases/{cid}/pdf-review', 'POST')
    row=request('/api/cases/'+cid)
    if args.review_fields:
        assert row['state'] == 'ready'
        admission = row['result']['review_fields']['fields']['ADMISSION_DATE']
        assert admission['status'] == ('conflicting' if args.case == 'SYN-C003' else 'found')
        assert admission['candidates']
        for citation in admission['candidates']:
            doc = next(d for d in row['documents'] if d['id'] == citation['document_id'])
            text = doc['pages'][citation['page'] - 1]['text']
            assert text[citation['start_offset']:citation['end_offset']] == citation['source_text']
        if args.case == 'SYN-C003':
            bill = next(d for d in row['documents'] if d['filename'] == '06_bill.pdf')
            page = bill['pages'][0]
            assert page['method'] == 'ocr' and page['needs_verification']
            assert row['result']['ocr_pages'] == 1
            for label in ('POLICY_ID', 'MEMBER_ID'):
                candidates = row['result']['review_fields']['fields'][label]['candidates']
                citation = next(c for c in candidates if c['document_id'] == bill['id'])
                assert citation['page'] == page['page'] and 'check_against_original' in citation['review_reasons']
                assert page['text'][citation['start_offset']:citation['end_offset']] == citation['source_text']
            print('PASS: scanned bill OCR, original-page warning, and exact identifier citations.')
        request(f'/api/cases/{cid}/review', 'POST',
                json.dumps({'review_revision': row['review_revision']}).encode())
        assert any(e['action'] == 'draft_review_acknowledged_not_coverage_authorization'
                   for e in request('/api/cases/' + cid)['events'])
        print('PASS: PDF field review and admission-date citations.')
    assert len(row['documents'])==len(pdfs),'Uploaded documents missing'
    for doc in row['documents']:
        content=request(f'/api/cases/{cid}/documents/'+doc['id'],raw=True)
        assert content==(root/doc['filename']).read_bytes(),'Downloaded PDF differs'
    request('/api/cases/'+cid,'DELETE')
    request('/api/cases/'+cid, expect_error=404)
    if args.auth_mode=='session':
        request('/api/auth/logout','POST')
        request('/api/cases', expect_error=401)
    print('PASS: authentication, origin rejection, synthetic upload/download, case deletion and logout. No inference invoked.')
    print('File removal remains queued; verify worker cleanup and bucket deletion separately.')
    raise SystemExit(0)
request(f'/api/cases/{cid}/assess','POST')
print('Authentication and upload checks passed. Waiting for actual local processing…')
deadline=time.monotonic()+900
while time.monotonic()<deadline:
    row=request('/api/cases/'+cid)
    if row['state']=='failed': raise SystemExit('Live processing failed: '+row['error']+'; case retained for inspection')
    if row['state']=='ready': break
    time.sleep(5)
else: raise SystemExit('Processing exceeded 15 minutes; case retained for inspection')
assert row['result']['model'],'Missing model provenance'
assert row['result']['total_pages']>0,'No processed pages'
assert row['result']['findings'],'No source-backed findings; inspect the retained case'
if args.case=='SYN-C003': assert row['result']['ocr_pages']>=1,'Image-only PDF did not exercise OCR'
assert any(e['action']=='private_inference_started' for e in row['events'])
request(f'/api/cases/{cid}/review','POST',json.dumps({'review_revision':row['review_revision']}).encode())
row=request('/api/cases/'+cid)
assert any(e['action']=='draft_review_acknowledged_not_coverage_authorization' for e in row['events'])
print('Live pipeline passed. Case retained for browser inspection:',cid)
print('Also restart services and verify this case persists before release.')
