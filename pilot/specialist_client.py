"""Bounded, authenticated specialist transport; never substitutes rules for a model."""
import ipaddress
import json
import math
import os
import re
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

LABELS = ('POLICY_ID', 'MEMBER_ID', 'ADMISSION_DATE', 'DISCHARGE_DATE', 'ROOM_LIMIT', 'SUM_INSURED')
KINDS = ('policy', 'schedule', 'claim_form', 'discharge', 'bill', 'receipt')
MAX_BYTES = 1_000_000
MAX_TEXT = 160_000
MAX_PAGES = 60
MAX_ITEMS = 250
TIMEOUT = 12


def result(state, detail, checkpoint=None):
    return dict(state=state, checkpoint=checkpoint, suggestions={k: [] for k in LABELS},
                evidence={k: [] for k in LABELS}, detail=detail)


def configuration():
    url = os.environ.get('SPECIALIST_URL', '').strip()
    if not url:
        return None
    token = os.environ.get('SPECIALIST_TOKEN', '')
    digest = os.environ.get('SPECIALIST_CHECKPOINT_SHA256', '')
    parsed = urlsplit(url)
    local = parsed.hostname == 'localhost'
    try:
        local = local or ipaddress.ip_address(parsed.hostname or '').is_loopback
    except ValueError:
        pass
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or
            (parsed.scheme == 'http' and not local) or not 16 <= len(token) <= 512 or
            any(ord(c) < 33 or ord(c) > 126 for c in token) or not re.fullmatch('[0-9a-f]{64}', digest)):
        raise ValueError('Invalid specialist configuration')
    return url.rstrip('/'), token, digest


def specialist_status():
    try:
        configured = configuration()
        return {'state': 'configured' if configured else 'disabled',
                'checkpoint': configured[2] if configured else None,
                'detail': 'Availability is checked during review.' if configured else 'Neural assistance is disabled.'}
    except ValueError:
        return {'state': 'unavailable', 'checkpoint': None, 'detail': 'Invalid specialist configuration.'}


def prepare_documents(documents):
    if not isinstance(documents, list) or len(documents) > 60:
        raise ValueError('Document limit exceeded')
    output, seen, total, count = [], set(), 0, 0
    skipped = False
    for doc in documents:
        if doc['kind'] not in KINDS:
            skipped = True
            continue
        identity = str(doc['id'])
        if not identity or len(identity) > 128 or identity in seen:
            raise ValueError('Invalid document identity')
        seen.add(identity)
        filename = doc['filename']
        if not isinstance(filename, str) or len(filename) > 512:
            raise ValueError('Invalid filename')
        pages, numbers = [], set()
        for page in doc['pages']:
            number, text = page['page'], page['text']
            if type(number) is not int or not 1 <= number <= 10000 or number in numbers or not isinstance(text, str):
                raise ValueError('Invalid page')
            numbers.add(number)
            count += 1
            total += len(text)
            if count > MAX_PAGES or total > MAX_TEXT:
                raise ValueError('Text limit exceeded')
            pages.append({'page': number, 'text': text})
        output.append({'id': identity, 'filename': filename, 'kind': doc['kind'], 'pages': pages})
    if not output:
        raise ValueError('No supported documents')
    return output, skipped


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Specialist redirects are disabled')


def _transport(url, token, payload):
    request = Request(url + '/review', data=payload, headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with build_opener(ProxyHandler({}), NoRedirect).open(request, timeout=TIMEOUT) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Response exceeds limit')
    return json.loads(data)


def validate_response(response, documents, digest):
    if not isinstance(response, dict) or response.get('state') != 'ready' or response.get('checkpoint') != digest:
        raise ValueError('Unexpected checkpoint or state')
    pages = {(doc['id'], page['page']): (doc, page) for doc in documents for page in doc['pages']}
    clean = result('ready', 'Neural suggestions require reviewer verification; ranking scores are not probabilities.', digest)
    for collection in ('suggestions', 'evidence'):
        values = response.get(collection)
        if not isinstance(values, dict) or set(values) != set(LABELS):
            raise ValueError('Invalid labels')
        for label, items in values.items():
            if not isinstance(items, list) or len(items) > MAX_ITEMS:
                raise ValueError('Prediction limit exceeded')
            seen = set()
            for item in items:
                if not isinstance(item, dict) or type(item.get('page')) is not int:
                    raise ValueError('Invalid citation')
                doc, page = pages[(item['document_id'], item['page'])]
                start, end = item['start_offset'], item['end_offset']
                if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(page['text']) or
                        item['filename'] != doc['filename'] or item['source_text'] != page['text'][start:end]):
                    raise ValueError('Citation does not match source')
                citation = {key: item[key] for key in ('document_id', 'filename', 'page', 'start_offset', 'end_offset', 'source_text')}
                citation['review_reasons'] = ['neural_suggestion_unverified']
                if collection == 'suggestions':
                    # Values are literal spans, never arbitrary service-generated conclusions.
                    if item.get('value') != item['source_text']:
                        raise ValueError('Value does not match span')
                    from .field_rules import _candidate
                    try:
                        normalized = _candidate(doc, page, label, start, end)
                        citation['value'] = normalized['value']
                        citation['review_reasons'].extend(normalized['review_reasons'])
                    except (ValueError, ArithmeticError):
                        citation['value'] = None
                        citation['review_reasons'].append('unrecognized_neural_value')
                else:
                    score = item['score']
                    if type(score) not in (int, float) or not math.isfinite(score):
                        raise ValueError('Invalid rank score')
                    citation['score'] = score
                key = (doc['id'], page['page'], start, end)
                if key not in seen:
                    clean[collection][label].append(citation)
                    seen.add(key)
            if collection == 'evidence':
                clean[collection][label].sort(key=lambda item: item['score'], reverse=True)
    return clean


def review_specialists(documents):
    try:
        config = configuration()
        if config is None:
            return result('disabled', 'Neural assistance is disabled.')
        url, token, digest = config
        submitted, skipped = prepare_documents(documents)
        payload = json.dumps({'documents': submitted}, ensure_ascii=False).encode('utf-8')
        if len(payload) > MAX_BYTES:
            raise ValueError('Request exceeds limit')
        clean = validate_response(_transport(url, token, payload), submitted, digest)
        originals = {(str(doc['id']), page['page']): page for doc in documents for page in doc.get('pages', [])}
        for collection in ('suggestions', 'evidence'):
            for items in clean[collection].values():
                for item in items:
                    page = originals[(item['document_id'], item['page'])]
                    item['review_reasons'].extend(page.get('quality_reasons', []))
                    if page.get('needs_verification') or page.get('method') == 'ocr':
                        item['review_reasons'].append('check_against_original')
                    item['review_reasons'] = list(dict.fromkeys(item['review_reasons']))
        if skipped:
            clean['detail'] += ' Unsupported document kinds (including endorsements) were excluded.'
        return clean
    except Exception:
        # Do not disclose service responses, credentials, or document contents.
        return result('unavailable', 'Neural assistance is unavailable; rule review remains available.')
