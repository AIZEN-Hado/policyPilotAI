"""Publish the built application image privately to GHCR; never starts compute."""
import argparse
from collections import deque
from datetime import datetime,timezone
import getpass
import json
from pathlib import Path
import re
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


class PublishError(Exception):pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def github(path,token,missing_ok=False):
    request=urllib.request.Request('https://api.github.com'+path,headers={
        'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
        'X-GitHub-Api-Version':'2026-03-10','User-Agent':'PolicyPilot-ImagePublisher'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        with opener.open(request,timeout=20) as response:
            raw=response.read(1024*1024+1)
            if len(raw)>1024*1024:raise PublishError('GitHub response too large')
            value=json.loads(raw)
            if not isinstance(value,dict):raise PublishError('Unexpected GitHub response')
            return value
    except urllib.error.HTTPError as exc:
        if exc.code==404 and missing_ok:return None
        raise PublishError(f'GitHub HTTP {exc.code}; response details withheld. Check the classic token and package scopes.') from None
    except (OSError,ValueError):
        raise PublishError('GitHub network/response error; credentials were not printed') from None


def safe_docker_detail(text,secrets=()):
    for value in secrets:
        if value:text=text.replace(value,'[redacted]')
    text=re.sub(r'https?://[^\s\x22\x27<>]+','[URL withheld]',text)
    text=re.sub(r'(?i)\b(bearer|basic)\s+\S+',r'\1 [redacted]',text)
    text=re.sub(r'\b(?:ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+)\b','[redacted]',text)
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    return '\n'.join(lines[-6:])[-1800:] or 'Docker returned no diagnostic text.'


def push_image(target,secrets=(),timeout=3600):
    """Show sanitized progress, retaining a bounded diagnostic tail on failure."""
    try:
        process=subprocess.Popen(['docker','push',target],stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT,text=True,errors='replace')
    except OSError:
        raise PublishError('Docker push could not start. Local images were preserved.') from None
    events=queue.Queue(maxsize=256)
    stopped=threading.Event()

    def read_output():
        try:
            for line in process.stdout:
                while not stopped.is_set():
                    try:
                        events.put(line,timeout=0.2)
                        break
                    except queue.Full:pass
                if stopped.is_set():break
        finally:
            while not stopped.is_set():
                try:
                    events.put(None,timeout=0.2)
                    break
                except queue.Full:pass

    reader=threading.Thread(target=read_output,daemon=True)
    reader.start()
    tail=deque(maxlen=6)
    deadline=time.monotonic()+timeout
    heartbeat=time.monotonic()
    try:
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:
                raise PublishError(f'Docker push exceeded {timeout} seconds. Retry the same tag to reuse completed layers. Local images were preserved.')
            try:line=events.get(timeout=min(1,remaining))
            except queue.Empty:
                if time.monotonic()-heartbeat>=30:
                    print('Still waiting for Docker upload progress; no compute started.',flush=True)
                    heartbeat=time.monotonic()
                continue
            if line is None:break
            if line.strip():
                safe=safe_docker_detail(line,secrets)
                print(safe,flush=True)
                tail.append(safe)
                heartbeat=time.monotonic()
        try:code=process.wait(timeout=max(0.01,deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            raise PublishError('Docker push timed out after its output closed. Local images were preserved.') from None
        if code:
            raise PublishError(f'Docker push failed (exit {code}). Sanitized diagnostic:\n'+'\n'.join(tail))
        return '\n'.join(tail)
    finally:
        stopped.set()
        if process.poll() is None:
            process.kill()
            process.wait()
        reader.join(timeout=2)
        process.stdout.close()


def docker(*args,input_text=None,secrets=(),push_timeout=3600):
    if args[0]=='push':return push_image(args[1],secrets,timeout=push_timeout)
    try:
        result=subprocess.run(['docker',*args],input=input_text,text=True,capture_output=True,
                              timeout=60)
    except (OSError,subprocess.SubprocessError):
        raise PublishError('Docker operation failed or timed out. Local images were preserved.') from None
    if result.returncode:
        protected=tuple(secrets)+((input_text.strip(),) if input_text else ())
        detail=safe_docker_detail(result.stderr or result.stdout,protected)
        raise PublishError(f'Docker {args[0]} failed (exit {result.returncode}). Sanitized diagnostic:\n'+detail)
    return result.stdout


def assert_private(package):
    if package is not None and package.get('visibility')!='private':
        raise PublishError('Target package is not confirmed private. No further upload will be attempted.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('username')
    parser.add_argument('--version',help='Retry an existing image tag instead of generating a new one')
    parser.add_argument('--only',choices=('api',),help='Upload only this image; preserve matching saved image references')
    parser.add_argument('--push-timeout',type=int,default=3600,help='Upload timeout per image in seconds (default: 3600)')
    args=parser.parse_args()
    if args.push_timeout<1:raise PublishError('Push timeout must be positive')
    username=args.username.lower()
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?',username):
        raise PublishError('Invalid personal GitHub username')
    if args.version and not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}',args.version):
        raise PublishError('Invalid image version tag')
    images=[]
    for name in ('policypilot-api',):
        if args.only and name!='policypilot-'+args.only:continue
        metadata=json.loads(docker('image','inspect',name+':demo'))[0]
        if metadata.get('Os')!='linux' or metadata.get('Architecture')!='amd64':
            raise PublishError('Selected images must be built for linux/amd64 before publishing')
        images.append((name,metadata['Id']))
    token=getpass.getpass('GitHub classic token (read:packages + write:packages; hidden): ')
    if not token:raise PublishError('Token missing. Nothing uploaded.')
    identity=github('/user',token)
    if str(identity.get('login','')).lower()!=username:
        raise PublishError('Token owner does not match the requested personal namespace')
    for name,_ in images:
        assert_private(github(f'/users/{username}/packages/container/{name}',token,missing_ok=True))
    docker('login','ghcr.io','--username',username,'--password-stdin',input_text=token+'\n')
    print('GHCR login passed. Docker may cache credentials in its configured credential store.',flush=True)
    version=args.version or 'v0.1.0-demo.'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    report={'namespace':username,'version':version,'images':[],'compute_started':False}
    path=ROOT/'artifacts/published-images.json'
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        previous=json.loads(path.read_text())
        if previous.get('namespace')==username and previous.get('version')==version:
            if not isinstance(previous.get('images'),list):raise PublishError('Saved image report is invalid; keep it for inspection.')
            report={**previous,'images':[row for row in previous['images'] if row.get('name')=='policypilot-api']}
    for name,image_id in images:
        target=f'ghcr.io/{username}/{name}:{version}'
        docker('tag',name+':demo',target)
        print('Uploading '+target+' — this can take several minutes.',flush=True)
        docker('push',target,secrets=(token,),push_timeout=args.push_timeout)
        package=None
        for attempt in range(3):
            package=github(f'/users/{username}/packages/container/{name}',token,missing_ok=True)
            if package is not None:break
            if attempt<2:time.sleep(2)
        if package is None:raise PublishError('Upload returned, but GitHub package metadata is not visible yet. Verify before retrying.')
        assert_private(package)
        metadata=json.loads(docker('image','inspect',target))[0]
        prefix=f'ghcr.io/{username}/{name}@sha256:'
        references=[value for value in metadata.get('RepoDigests',[]) if value.startswith(prefix)
                    and re.fullmatch('[0-9a-f]{64}',value[len(prefix):])]
        if not references:raise PublishError('Registry digest not confirmed after push. Keep local images.')
        if metadata.get('Id')!=image_id:raise PublishError('Local image changed during publication')
        report['images']=[entry for entry in report['images'] if entry.get('name')!=name]
        report['images'].append({'name':name,'tag':target,'reference':references[0],
                                 'image_id':image_id,'visibility':'private'})
        path.write_text(json.dumps(report,indent=2)+'\n')
        print('PASS: private image uploaded: '+references[0],flush=True)
    print('Saved image references:',path)
    print('No compute or inference started. API image only; keep local images until deployment succeeds.')


if __name__=='__main__':
    try:main()
    except (PublishError,ValueError,KeyError,IndexError):
        import sys
        exc=sys.exception()
        message=str(exc) if isinstance(exc,PublishError) else 'Unexpected local image metadata; no further uploads attempted.'
        raise SystemExit(message) from None
