"""Allowlisted source package; excludes credentials, evaluation answers and legacy data."""
from pathlib import Path
import hashlib
import json
import tarfile
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/policypilot-live-pilot.tar.gz'
out.parent.mkdir(exist_ok=True)
files=[ROOT/'README.md',ROOT/'.dockerignore',ROOT/'render.yaml',ROOT/'render-demo.yaml',
       ROOT/'docs/IMPLEMENTATION_PLAN.md',ROOT/'docs/PERSISTENT_STORAGE_PLAN.md',
       ROOT/'docs/SYNTHETIC_DATA_SPEC.md',ROOT/'docs/SPECIALIST_NETWORK_PLAN.md',
       ROOT/'docs/LEGACY_OLLAMA_PROTOTYPE.md',ROOT/'docs/PRETRAINED_PARSER_PLAN.md',
       ROOT/'docs/RENDER_RELEASE_PLAN.md',ROOT/'docs/design/WHITE_ONYX_MINT.md']
files += [p for p in (ROOT/'pilot').rglob('*') if p.is_file() and '__pycache__' not in p.parts
          and (p.suffix in {'.py','.sql','.js','.html','.css','.txt','.md','.pdf'} or p.name=='Dockerfile')]
allowed={'compose.yaml','Caddyfile','db-init.sql','configure.py','start.sh','smoke.py','backup.sh','package.py',
         'HOSTINGER_RUNBOOK.md','render-start.sh','hash_password.py','RENDER_RUNBOOK.md','check_r2.py',
         'preview_ui.py','ui_preview.js','release_web.sh','live.env.example','configure_cloud.py','CLOUD_SETUP.md',
         'publish_images.py','RENDER_IMAGE_DEMO.md','LIVE_RELEASE_REQUIREMENTS.md',
         'diagnose_login.py','remove_serverless.py'}
files += [p for p in (ROOT/'deploy').iterdir() if p.is_file() and p.name in allowed]
files += list((ROOT/'deploy/tests').glob('test_*.py'))
files += list((ROOT/'deploy/tests').glob('check_*.mjs'))
files += list((ROOT/'data/synthetic/exemplars').rglob('*.pdf'))
files += [ROOT/'data/synthetic/README.md']
with tarfile.open(out,'w:gz') as archive:
    for p in sorted(files):
        if p.is_symlink() or not p.is_file():
            raise ValueError('Expected a regular file: '+str(p.relative_to(ROOT)))
        archive.add(p,arcname=str(p.relative_to(ROOT)),recursive=False)
with tarfile.open(out) as archive:
    names=archive.getnames()
    assert not any('.env' in Path(n).parts or 'evaluation' in Path(n).parts or '.git' in Path(n).parts for n in names)
    assert 'pilot/static/index.html' in names and 'deploy/compose.yaml' in names
    assert 'render.yaml' in names and 'deploy/render-start.sh' in names
    assert not any(Path(n).name.endswith('.env') for n in names)
    for path in files:
        member=archive.extractfile(str(path.relative_to(ROOT)))
        assert member is not None
        assert hashlib.sha256(member.read()).digest()==hashlib.sha256(path.read_bytes()).digest()
digest=hashlib.sha256(out.read_bytes()).hexdigest()
out.with_suffix(out.suffix+'.sha256').write_text(digest+'  '+out.name+'\n')
manifest={'artifact_type':'source_release_not_trained_model','archive':out.name,'sha256':digest,
          'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)},
          'verified':'Every archived file was read back and its SHA-256 matched its source.'}
out.with_suffix(out.suffix+'.manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(f'Packaged {len(files)} files: {out}')
print('Verified archive contents and SHA-256:',digest)
