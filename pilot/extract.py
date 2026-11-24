"""Bounded local Poppler/Tesseract extraction. No model or network calls."""
import os
from pathlib import Path
import re
import resource
import subprocess
import tempfile
import unicodedata

MAX_PAGE_TEXT = 18000
MIN_ALPHANUMERIC = 50
PARSER_VERSION = 'poppler-tesseract-v2'
PARSER_METADATA = {
    'name': 'poppler_tesseract',
    'version': 2,
    'quality_assessment': 'heuristic',
}

class ExtractionError(Exception): pass

def limits():
    resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
    resource.setrlimit(resource.RLIMIT_FSIZE,(40*1024*1024,40*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(45,45))

def run(args,timeout=60):
    try:
        p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=timeout,check=True,preexec_fn=limits,env={**os.environ,'OMP_THREAD_LIMIT':'2'})
        return p.stdout.decode('utf-8',errors='replace')
    except (subprocess.SubprocessError,OSError):
        raise ExtractionError('Document parsing failed or exceeded processing limits') from None

def quality_reasons(text, source):
    """Routing signals, not confidence scores or proof of text correctness.

    Unicode alphanumerics keep Hindi and other scripts useful as text signals.
    Long, repetitive natural text alone is not evidence of corruption. Without
    page-image/layout evidence these signals cannot detect mixed image/text pages.
    """
    reasons = []
    if sum(char.isalnum() for char in text) < MIN_ALPHANUMERIC:
        reasons.append(source + '_insufficient_alphanumeric')
    if '\ufffd' in text:
        reasons.append(source + '_replacement_characters')
    if any(unicodedata.category(char) == 'Cc' and char not in '\t\n\r\f' for char in text):
        reasons.append(source + '_control_characters')
    visible = [char for char in text if not char.isspace()]
    # Failed font maps often expose repeated cid placeholders or a substantial
    # layer of private-use/unassigned glyphs and miscellaneous symbols. Require
    # substantial evidence, avoiding punctuation-heavy clauses and table rows.
    cid_matches = list(re.finditer(r'\(cid:\d+\)', text))
    suspicious = sum(unicodedata.category(char) in {'Co', 'Cn', 'So', 'Sk'} for char in visible)
    if ((len(cid_matches) >= 5 and sum(len(match[0]) for match in cid_matches) >= len(text) * .2)
            or (suspicious >= 40 and suspicious >= len(visible) * .5)):
        reasons.append(source + '_garbled_text')
    return reasons

def bounded_text(text):
    # Check before stripping or starting rendering/OCR; each competing source is
    # independently bounded, including native text retained for provenance.
    if len(text) > MAX_PAGE_TEXT:
        raise ExtractionError('Page text exceeds processing limit')
    return text.strip()

def ocr_page(path, number, prefix, invoke):
    image = prefix.with_suffix('.png')
    try:
        invoke(['pdftoppm', '-f', str(number), '-l', str(number), '-scale-to', '2200',
                '-singlefile', '-png', str(path), str(prefix)], 45)
        return bounded_text(invoke(['tesseract', str(image), 'stdout', '-l', 'eng+hin', '--psm', '3'], 60))
    finally:
        image.unlink(missing_ok=True)

def extract_pdf(path,max_pages=20):
    info=run(['pdfinfo',str(path)],15)
    match=re.search(r'^Pages:\s+(\d+)',info,re.M)
    if not match or not 1 <= int(match[1]) <= max_pages:
        raise ExtractionError('PDF exceeds the page limit or has invalid page metadata')
    count=int(match[1]); pages=[]
    with tempfile.TemporaryDirectory(prefix='claim-ocr-') as temp:
        for number in range(1,count+1):
            text=bounded_text(run(['pdftotext','-f',str(number),'-l',str(number),'-layout',str(path),'-'],20))
            mode='native_text'
            reasons=quality_reasons(text, 'native')
            native_text=None
            if reasons:
                native_text=text
                text=ocr_page(path,number,Path(temp)/'page',run)
                mode='ocr'
                reasons += ['ocr_used'] + quality_reasons(text, 'ocr')
            page={'page':number,'text':text,'method':mode,
                  'needs_verification': mode=='ocr' or bool(quality_reasons(text, 'native')),
                  'parser_version':PARSER_VERSION,
                  'parser':dict(PARSER_METADATA),'quality_reasons':reasons}
            if native_text is not None:
                page['native_text']=native_text
            pages.append(page)
    return pages
