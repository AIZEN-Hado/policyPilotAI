"""Case review using embedded or OCR PDF text and labeled fields."""
import os
from pathlib import Path
import re
from shutil import which
import subprocess
import tempfile
import time

from .extract import ExtractionError, MAX_PAGE_TEXT, PARSER_METADATA, PARSER_VERSION, ocr_page, quality_reasons
from .field_rules import extract_review_fields
from .storage import materialize

CASE_PAGE_LIMIT = 60
REVIEW_DEADLINE_SECONDS = 75
NATIVE_PARSER_VERSION = 'poppler-native-v1'
NATIVE_PARSER_METADATA = {'name': 'poppler', 'version': 1, 'quality_assessment': 'heuristic'}


def pdf_review_available():
    return all(which(binary) for binary in ('prlimit', 'pdfinfo', 'pdftotext'))


def ocr_available():
    return all(which(binary) for binary in ('pdftoppm', 'tesseract'))


def remaining_time(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise ExtractionError('PDF review exceeded the time limit.')
    return seconds


def review_documents(documents, storage, *, max_file, max_pages):
    deadline = time.monotonic() + REVIEW_DEADLINE_SECONDS
    count = 0
    ocr_count = 0
    versions = set()
    warnings = []
    for document in documents:
        remaining_time(deadline)
        remaining = min(max_pages, CASE_PAGE_LIMIT - count)
        if remaining < 1:
            raise ExtractionError(f'Case exceeds the {CASE_PAGE_LIMIT}-page limit.')
        with materialize(storage, document['id'], document['bytes'], document['sha256'], max_file) as pdf:
            pages = read_pages(pdf, remaining, deadline)
        document['pages'] = pages
        count += len(pages)
        ocr_count += sum(page['method'] == 'ocr' for page in pages)
        versions.update(page['parser_version'] for page in pages)
        warnings.extend({
            'document_id': str(document['id']), 'filename': document['filename'], 'page': page['page'],
            'method': page['method'], 'quality_reasons': page['quality_reasons'],
        } for page in pages if page['needs_verification'])
    fields = extract_review_fields(documents)
    remaining_time(deadline)
    return {
        'source': 'native_pdf_fields', 'model': 'Labeled PDF fields',
        'total_pages': count, 'ocr_pages': ocr_count, 'parser_versions': sorted(versions),
        'summary': f'Reviewed {count} pages. {len(warnings)} pages need an original-PDF check.',
        'review_fields': fields, 'findings': [], 'questions': [], 'extraction_warnings': warnings,
        'notice': 'Verify OCR, flagged pages, and field applicability against the original PDFs before deciding.',
    }


def read_pages(pdf, limit, deadline):
    with tempfile.TemporaryDirectory(prefix='claim-native-') as directory:
        metadata = Path(directory) / 'info.txt'
        with metadata.open('wb') as stdout:
            run_poppler(['pdfinfo', str(pdf)], deadline, stdout=stdout)
        info = metadata.read_bytes()
        pages_match = re.search(rb'^Pages:[ \t]+([0-9]{1,10})[ \t]*$', info, re.MULTILINE)
        if not pages_match or not 1 <= (count := int(pages_match[1])) <= limit:
            raise ExtractionError(f'PDF has invalid page metadata or exceeds the remaining {limit}-page limit.')

        output = Path(directory) / 'pages.txt'
        run_poppler(['pdftotext', '-layout', '-enc', 'UTF-8', str(pdf), str(output)], deadline)
        if output.stat().st_size > count * (4 * MAX_PAGE_TEXT + 1):
            raise ExtractionError('PDF text exceeds the processing limit.')
        # Poppler emits a form feed at each page end, including empty pages.
        # Checking against the page count prevents citation offsets drifting.
        # PostgreSQL JSONB cannot store NUL. Replacement characters preserve the
        # text positions and cause the saved page to be flagged for verification.
        chunks = output.read_text(encoding='utf-8', errors='replace').replace('\x00', '\ufffd').split('\f')
        if chunks.pop() or len(chunks) != count:
            raise ExtractionError('PDF text page boundaries could not be verified.')
        if any(len(text) > MAX_PAGE_TEXT for text in chunks):
            raise ExtractionError('Page text exceeds the processing limit.')
        use_ocr = ocr_available()
        return [review_page(pdf, number, text.strip(), Path(directory) / 'scan', deadline, use_ocr)
                for number, text in enumerate(chunks, 1)]


def review_page(pdf, number, text, prefix, deadline, use_ocr):
    reasons = quality_reasons(text, 'native')
    page = {'page': number, 'text': text, 'method': 'native_text', 'parser_version': NATIVE_PARSER_VERSION,
            'parser': dict(NATIVE_PARSER_METADATA), 'needs_verification': bool(reasons), 'quality_reasons': reasons}
    if not reasons:
        return page
    if not use_ocr:
        reasons.append('ocr_unavailable')
        return page
    try:
        recognized = ocr_page(pdf, number, prefix, lambda args, _timeout: run_review_ocr(args, deadline))
    except ExtractionError:
        remaining_time(deadline)
        reasons.append('ocr_failed')
        return page
    recognized = recognized.replace('\x00', '\ufffd')
    reasons.extend(['ocr_used', *quality_reasons(recognized, 'ocr')])
    page.update(text=recognized, native_text=text, method='ocr', parser_version=PARSER_VERSION,
                parser=dict(PARSER_METADATA))
    return page


def run_review_ocr(args, deadline):
    with tempfile.TemporaryFile() as output:
        run_poppler(args, deadline, stdout=output)
        if output.tell() > 4 * MAX_PAGE_TEXT:
            raise ExtractionError('Page text exceeds the processing limit.')
        output.seek(0)
        return output.read().decode('utf-8', errors='replace')


def run_poppler(args, deadline, stdout=subprocess.DEVNULL):
    try:
        subprocess.run(
            ['prlimit', '--as=268435456', '--fsize=8388608', '--cpu=15', '--', *args],
            timeout=min(remaining_time(deadline), 15), check=True, stderr=subprocess.DEVNULL,
            stdout=stdout, env={**os.environ, 'OMP_THREAD_LIMIT': '2'},
        )
    except subprocess.TimeoutExpired:
        raise ExtractionError('PDF review exceeded the time limit.') from None
    except (subprocess.SubprocessError, OSError):
        raise ExtractionError('PDF text could not be read within the processing limits.') from None
