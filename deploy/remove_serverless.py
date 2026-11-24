"""Retire only this project's recorded endpoint/templates/registry. Never start compute."""
import argparse
from datetime import datetime,timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
ENDPOINT='tjkkm5pkp7lrej'


class CleanupError(Exception):pass


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9_-]{3,160}',value):raise CleanupError('Invalid recorded resource identity')
    return value


def save(path,value):
    path.parent.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as output:
        temporary=Path(output.name)
        try:
            json.dump(value,output,indent=2);output.write('\n');output.flush();os.fsync(output.fileno())
            os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)


def token():
    value=os.environ.get('RUNPOD_API_KEY')
    path=ROOT/'deploy/cloud.env'
    if not value and path.exists():
        if path.stat().st_mode & 0o077:raise CleanupError('deploy/cloud.env must have owner-only permissions')
        for line in path.read_text().splitlines():
            name,separator,raw=line.strip().removeprefix('export ').partition('=')
            if separator and name=='RUNPOD_API_KEY':
                values=shlex.split(raw,comments=True)
                if len(values)!=1:raise CleanupError('Invalid local credential assignment; value withheld')
                value=values[0]
    if not value:raise CleanupError('Local setup key is missing; never paste it into chat')
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class API:
    def __init__(self,key):
        self.key=key;self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def call(self,path,method='GET',body=None,missing_ok=False):
        request=urllib.request.Request('https://api.runpod.io'+path,method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json','Accept':'application/json'})
        try:
            with self.opener.open(request,timeout=15) as response:
                if response.code==204:return None
                raw=response.read(4*1024*1024+1)
                if len(raw)>4*1024*1024:raise ValueError()
                data=json.loads(raw)
                if not isinstance(data,dict):raise ValueError()
                return data
        except urllib.error.HTTPError as exc:
            if exc.code==404 and missing_ok:return None
            raise CleanupError('Provider '+method+' HTTP '+str(exc.code)+'; response body withheld. Inspect cleanup report before continuing.') from None
        except (OSError,ValueError):
            raise CleanupError('Provider '+method+' unavailable or unconfirmed; no automatic retry. Inspect cleanup report.') from None


def rows(api,path,key):
    result=[];cursor=None;seen=set()
    for _ in range(30):
        page=api.call(path+('?' +urllib.parse.urlencode({'cursor':cursor}) if cursor else ''))
        if not isinstance(page.get(key),list):raise CleanupError('Provider inventory shape is unknown')
        result.extend(page[key]);paging=page.get('pagination')
        if not isinstance(paging,dict) or type(paging.get('hasNextPage')) is not bool:
            raise CleanupError('Provider inventory pagination was not confirmed')
        if not paging['hasNextPage']:return result
        cursor=paging.get('nextCursor')
        if not isinstance(cursor,str) or cursor in seen:break
        seen.add(cursor)
    raise CleanupError('Provider inventory completeness not confirmed')


def zero(data):
    summary=data.get('summary',{})
    return data.get('workers')==[] and all(type(summary.get(key)) is int and summary[key]==0
        for key in ('running','idle','initializing','throttled','unhealthy','total'))


def retire(api,state,destination,apply=False,clock=time.monotonic,sleep=time.sleep):
    if state.get('endpoint_id')!=ENDPOINT:raise CleanupError('Recorded endpoint does not match this project')
    registry=identifier(state['registry_id'])
    names={state['endpoint_name']}|{item['name'] for item in state.get('endpoint_name_history',[]) if isinstance(item,dict) and isinstance(item.get('name'),str)}
    report={'endpoint_id':ENDPOINT,'recorded_at':datetime.now(timezone.utc).isoformat(),
            'apply_requested':apply,'jobs_submitted':0,'compute_started':False,'storage_deleted':False,
            'deleted':[],'endpoint_absent_verified':False,'result':'CHECK'}
    if destination.exists():
        previous=json.loads(destination.read_text())
        if previous.get('endpoint_id')!=ENDPOINT:raise CleanupError('Existing cleanup report belongs to another endpoint')
        for item in previous.get('deleted',[]):
            if isinstance(item,dict) and item.get('kind') in ('endpoint','template','registry'):
                report['deleted'].append({'kind':item['kind'],'id':identifier(item.get('id'))})
    save(destination,report)
    route='/v2/serverless/'+ENDPOINT
    def remove(path,kind,rid):
        report['pending_action']={'operation':'delete','kind':kind,'id':rid};save(destination,report)
        api.call(path,'DELETE')
        if api.call(path,missing_ok=True) is not None:raise CleanupError('Resource absence was not verified after deletion')
        report['deleted'].append({'kind':kind,'id':rid});report.pop('pending_action',None);save(destination,report)
    actual=api.call(route,missing_ok=True)
    if actual is not None:
        if (actual.get('id')!=ENDPOINT or actual.get('name') not in names or actual.get('registry')!=registry
                or actual.get('type')!='QUEUE' or actual.get('mounts')!={'network':[],'global':[]}):
            raise CleanupError('Endpoint identity/storage differs from the recorded disposable worker; no deletion attempted')
        workers=actual.get('workers',{})
        report['worker_limits']={key:workers.get(key) for key in ('min','max') if type(workers.get(key)) is int}
        empty=zero(api.call(route+'/workers'));report['zero_workers_verified']=empty
        save(destination,report)
        if apply:
            if workers.get('min')!=0 or workers.get('max')!=0:
                report['pending_action']={'operation':'disable','kind':'endpoint','id':ENDPOINT};save(destination,report)
                api.call(route,'PATCH',{'workers':{'min':0,'max':0}})
            check=api.call(route)
            if (check.get('id')!=ENDPOINT or check.get('workers',{}).get('min')!=0
                    or check.get('workers',{}).get('max')!=0):raise CleanupError('Disabled worker limits were not verified')
            empty=zero(api.call(route+'/workers'))
            end=clock()+45
            while not empty and clock()<end:
                sleep(2);empty=zero(api.call(route+'/workers'))
            if not empty:raise CleanupError('Workers have not stopped; endpoint deletion deferred')
            report['zero_workers_verified']=True;remove(route,'endpoint',ENDPOINT)
    if actual is None or apply:report['endpoint_absent_verified']=api.call(route,missing_ok=True) is None
    templates=rows(api,'/v2/templates','templates')
    owned=[row for row in templates if isinstance(row,dict) and row.get('name') in names]
    report['owned_template_ids']=[identifier(row.get('id')) for row in owned]
    report['registry_id']=registry;save(destination,report)
    if apply:
        endpoints=rows(api,'/v2/serverless','endpoints');pods=rows(api,'/v2/pods','pods')
        for template in owned:
            rid=identifier(template['id'])
            if any(row.get('templateId')==rid or row.get('template')==rid for row in endpoints+pods):
                raise CleanupError('An existing resource references a retired template; no cascade or forced detach')
            detail=api.call('/v2/templates/'+rid,missing_ok=True)
            if detail is None:continue
            if detail.get('id')!=rid or detail.get('name') not in names:
                raise CleanupError('Template identity changed; no deletion attempted')
            remove('/v2/templates/'+rid,'template',rid)
        # A dedicated credential is safe to remove only after all account
        # references are gone. Unknown/unrelated resources are never altered.
        remaining=rows(api,'/v2/templates','templates')
        current_registry=api.call('/v2/registries/'+registry,missing_ok=True)
        if current_registry is not None:
            if current_registry.get('id')!=registry or current_registry.get('name')!=state['registry_name']:
                raise CleanupError('Registry identity changed; no deletion attempted')
            if endpoints or pods or remaining:
                report['registry_retained_for_reference_review']=True
            else:remove('/v2/registries/'+registry,'registry',registry)
        report['result']='PARTIAL' if report.get('registry_retained_for_reference_review') else 'PASS'
    else:report['result']='PREVIEW'
    save(destination,report)
    if json.loads(destination.read_text())!=report:raise CleanupError('Cleanup report read-back mismatch')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    journal=ROOT/'artifacts/retired-serverless/runpod-disabled-setup.json'
    if not journal.exists():journal=ROOT/'artifacts/runpod-disabled-setup.json'
    state=json.loads(journal.read_text())
    path=ROOT/'artifacts/serverless-retirement.json'
    with (ROOT/'artifacts/serverless-retirement.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise CleanupError('Another retirement operation is active') from None
        report=retire(API(token()),state,path,args.apply)
    print(json.dumps(report,indent=2));print('Saved and verified:',path)
    print('No compute started, jobs submitted, model/document storage deleted or historical reservations changed.')
    if not args.apply:print('Preview only; use --apply to remove the scoped resources after deploying the app cleanup.')


if __name__=='__main__':
    try:main()
    except CleanupError as exc:raise SystemExit('CHECK: '+str(exc)) from None
    except (OSError,ValueError,KeyError,TypeError,KeyboardInterrupt):
        raise SystemExit('CHECK: cleanup interrupted or local journal invalid; details withheld. Inspect the saved retirement report.') from None
