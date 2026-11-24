"""Build standalone workspace and sign-in previews using checked synthetic exemplars."""
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'pilot/static'
sys.path.insert(0, str(ROOT))
from pilot.pdf_review import pdf_review_available, review_documents
from pilot.storage import LocalStorage

POLICY = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
          "img-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'")
KINDS = {'01_schedule.pdf': 'schedule', '02_wording.pdf': 'policy', '04_claim_form.pdf': 'claim_form',
         '05_discharge.pdf': 'discharge', '06_bill.pdf': 'bill'}


def packet(case):
    documents, originals = [], {}
    with tempfile.TemporaryDirectory(prefix='preview-packet-') as directory:
        storage = LocalStorage(directory)
        for name, kind in KINDS.items():
            source = ROOT / 'data/synthetic/exemplars' / case / name
            pdf = source.read_bytes()
            doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'policypilot:sample:{case}/{name}'))
            originals[doc_id] = base64.b64encode(pdf).decode('ascii')
            storage.put(doc_id, source)
            documents.append({'id': doc_id, 'kind': kind, 'filename': name, 'bytes': len(pdf),
                              'sha256': hashlib.sha256(pdf).hexdigest()})
        result = review_documents(documents, storage, max_file=10 * 1024 * 1024, max_pages=20)
    return {'documents': documents, 'originals': originals, 'result': result}


def inline(page):
    page = page.replace('<head>', f'<head><meta http-equiv="Content-Security-Policy" content="{POLICY}">')
    return re.sub(r'<link rel="stylesheet" href="/([a-z-]+\.css)">',
                  lambda match: '<style>' + (STATIC / match[1]).read_text() + '</style>', page)


def main():
    if not pdf_review_available():
        raise SystemExit('Preview generation needs prlimit, pdfinfo and pdftotext on PATH. '
                         'The generated HTML opens offline without these tools.')
    page = inline((STATIC / 'index.html').read_text())
    scripts = re.findall(r'<script src="/([a-z.-]+)" defer></script>', page)
    page = re.sub(r'<script src="/[a-z.-]+" defer></script>', '', page)
    controls = '''<aside class="preview-notice"><span><strong>Offline preview</strong> · Synthetic PDFs with precomputed fields. Changes last until reload.</span>
<div class="preview-links"><a href="./policypilot-login-preview.html">Sign-in preview</a><button class="textbutton" id="preview-reset">Reset preview</button></div></aside>'''
    page = page.replace('<main id="main" tabindex="-1">', '<main id="main" tabindex="-1">' + controls)
    form = '''<section id="preview-attach" class="upload">
<p class="small">Try the review with five synthetic PDFs from case SYN-C003.</p>
<button class="secondary" id="attach-sample" type="button">Attach sample packet</button></section>'''
    page = re.sub(r'<form id="upload-form".*?</form>', lambda m: m[0].replace('<form ', '<form hidden ', 1) + form,
                  page, count=1, flags=re.S)
    packets = {case: packet(case) for case in ('SYN-C001', 'SYN-C003')}
    data = json.dumps(packets, ensure_ascii=False, separators=(',', ':')).replace('<', r'\u003c')
    scripts = [(ROOT / 'deploy/ui_preview.js').read_text(), *((STATIC / name).read_text() for name in scripts)]
    page = page.replace('</body>', '<script type="application/json" id="sample-packets">' + data + '</script>'
                        + ''.join('<script>' + script + '</script>' for script in scripts) + '</body>')
    output = ROOT / 'artifacts/policypilot-ui-preview.html'
    output.parent.mkdir(exist_ok=True)
    output.write_text(page)
    login = inline((STATIC / 'login.html').read_text())
    login = login.replace('<script src="/login.js" defer></script>', '')
    login = login.replace('<form id="login-form">', '<p class="preview-notice">Offline sign-in preview. Use fictional credentials.</p><form id="login-form">')
    login = login.replace('class="login-brand" href="/"', 'class="login-brand" href="./policypilot-ui-preview.html"')
    login = login.replace('</body>', '''<script>
 document.getElementById('login-form').onsubmit=event=>{
  event.preventDefault();event.target.reset();location.href='./policypilot-ui-preview.html';
 };
</script></body>''')
    (output.parent / 'policypilot-login-preview.html').write_text(login)
    print('Standalone workspace and sign-in previews saved in', output.parent)


if __name__ == '__main__':
    main()
