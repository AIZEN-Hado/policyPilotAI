"""Dependency-free source-preserving chunks, lexical retrieval and quote checks."""
import re
import unicodedata

KINDS = {'policy', 'schedule', 'endorsement', 'claim_form', 'bill', 'discharge', 'receipt', 'other'}
CHUNK_CHARACTERS = 1200
FALLBACK_OVERLAP = 150
_METADATA = ('needs_verification', 'quality_reasons', 'parser_version')


def _trim_span(text, start, end):
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _bounded_units(text, start, end):
    """Keep lines/rows and sentences intact when possible; bound long runs."""
    cursor = start
    for line in text[start:end].splitlines(keepends=True):
        line_end = cursor + len(line)
        if len(line) <= CHUNK_CHARACTERS:
            yield cursor, line_end
        else:
            sentence_start = cursor
            boundaries = [cursor + m.end() for m in re.finditer(r'[.!?।](?:[ \t]+|$)', line)]
            for sentence_end in boundaries + [line_end]:
                if sentence_end <= sentence_start:
                    continue
                if sentence_end - sentence_start <= CHUNK_CHARACTERS:
                    yield sentence_start, sentence_end
                else:
                    for offset in range(sentence_start, sentence_end,
                                        CHUNK_CHARACTERS - FALLBACK_OVERLAP):
                        window_end = min(offset + CHUNK_CHARACTERS, sentence_end)
                        yield offset, window_end
                        if window_end == sentence_end:
                            break
                sentence_start = sentence_end
        cursor = line_end


def _page_spans(text):
    """Pack whole paragraphs first, then whole lines for oversized paragraphs."""
    cursor, units = 0, []
    for separator in list(re.finditer(r'\r?\n[ \t]*\r?\n', text)) + [None]:
        end = separator.start() if separator else len(text)
        start, end = _trim_span(text, cursor, end)
        if start < end:
            if end - start <= CHUNK_CHARACTERS:
                units.append((start, end))
            else:
                units.extend(_bounded_units(text, start, end))
        cursor = separator.end() if separator else len(text)
    pending = None
    for start, end in units:
        start, end = _trim_span(text, start, end)
        if start == end:
            continue
        if pending is not None and end - pending[0] <= CHUNK_CHARACTERS:
            pending = pending[0], end
        else:
            if pending is not None:
                yield pending
            pending = start, end
    if pending is not None:
        yield pending


def _metadata(source):
    metadata = {key: source[key] for key in _METADATA if key in source}
    if 'quality_reasons' in metadata:
        metadata['quality_reasons'] = list(metadata['quality_reasons'])
    method = source.get('extraction_method', source.get('method'))
    if method is not None:
        metadata['extraction_method'] = method
    return metadata


def make_chunks(documents):
    """Offsets index the original page text, before any whitespace trimming."""
    chunks = []
    for doc in documents:
        for page in doc['pages']:
            text = page['text']
            for number, (start, end) in enumerate(_page_spans(text)):
                chunk = {'id': f"{doc['id']}:p{page['page']}:c{number}",
                         'document_id': doc['id'], 'filename': doc['filename'],
                         'kind': doc['kind'], 'page': page['page'],
                         'start_offset': start, 'end_offset': end,
                         'text': text[start:end]}
                chunk.update(_metadata(doc))
                chunk.update(_metadata(page))
                chunks.append(chunk)
    return chunks


def _terms(text):
    # Combining marks are part of words, including Hindi vowel signs. Search
    # normalization never changes the source text or the citation validator.
    normalized = unicodedata.normalize('NFKC', text).casefold()
    normalized = ''.join(c if unicodedata.category(c)[0] in 'LMN' else ' '
                         for c in normalized)
    return {term for term in normalized.split() if len(term) >= 3}


def select_evidence(chunks, query, limit=12000):
    """Case-scoped lexical ranking with a hard text CHARACTER budget, not tokens.

    Policy and schedule representatives reserve room for one another. Applicable
    endorsements cannot be inferred here: supplied endorsements take next priority.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError('Evidence character budget must be a nonnegative integer')
    terms = _terms(query)
    ranked = sorted(chunks, key=lambda chunk: (
        -len(terms & _terms(chunk['text'])), str(chunk['document_id']),
        chunk['page'], chunk.get('start_offset', 0), chunk['id']))
    selected, used, total = [], set(), 0

    def add(chunk):
        nonlocal total
        if chunk['id'] in used or total + len(chunk['text']) > limit:
            return False
        selected.append(chunk)
        used.add(chunk['id'])
        total += len(chunk['text'])
        return True

    mandatory = [kind for kind in ('policy', 'schedule')
                 if any(c['kind'] == kind for c in ranked)]
    for index, kind in enumerate(mandatory):
        reserve = sum(min(len(c['text']) for c in ranked if c['kind'] == later)
                      for later in mandatory[index + 1:])
        candidates = [c for c in ranked if c['kind'] == kind]
        fitting = next((c for c in candidates if len(c['text']) <= limit - total - reserve), None)
        if fitting is None:
            fitting = next((c for c in candidates if len(c['text']) <= limit - total), None)
        if fitting is not None:
            add(fitting)

    # Give each remaining document a representative, with endorsements first.
    represented = {c['document_id'] for c in selected}
    for chunk in sorted(ranked, key=lambda c: c['kind'] != 'endorsement'):
        if chunk['document_id'] not in represented and add(chunk):
            represented.add(chunk['document_id'])

    # After representatives, prefer relevant passages and their page neighbors;
    # neighbors can contain exceptions or table continuations, not proven support.
    neighbors = {}
    for chunk in chunks:
        neighbors.setdefault((chunk['document_id'], chunk['page']), []).append(chunk)
    for page_chunks in neighbors.values():
        page_chunks.sort(key=lambda c: (c.get('start_offset', 0), c['id']))
    for chunk in ranked:
        add(chunk)
        if chunk['id'] in used:
            page_chunks = neighbors[(chunk['document_id'], chunk['page'])]
            index = next(i for i, c in enumerate(page_chunks) if c['id'] == chunk['id'])
            for neighbor in page_chunks[max(0, index - 1):index + 2]:
                add(neighbor)
    return selected, len(used) < len(chunks)


def coverage_report(chunks, selected):
    """Describe supplied extracted chunks only, never original PDF completeness."""
    selected_ids = {chunk['id'] for chunk in selected}
    counts, selected_counts = {}, {}
    for chunk in chunks:
        doc = str(chunk['document_id'])
        counts[doc] = counts.get(doc, 0) + 1
        if chunk['id'] in selected_ids:
            selected_counts[doc] = selected_counts.get(doc, 0) + 1
    selected_total = sum(selected_counts.values())
    return {'coverage_basis': 'supplied_extracted_chunks_only',
            'total_chunks': len(chunks), 'selected_chunks': selected_total,
            'omitted_document_ids': sorted(doc for doc in counts if doc not in selected_counts),
            'partially_selected_document_ids': sorted(doc for doc in selected_counts
                                                     if selected_counts[doc] < counts[doc]),
            'missing_kinds': sorted({c['kind'] for c in chunks}
                                    - {c['kind'] for c in chunks if c['id'] in selected_ids}),
            'complete': selected_total == len(chunks)}


def validate_output(raw, evidence, truncated=False):
    """Validate local schema and literal quote membership, not finding meaning."""
    if not isinstance(raw, dict) or set(raw) != {'summary', 'findings', 'questions'}:
        raise ValueError('Output must match the required object schema')
    sources = {e['id']: e for e in evidence}
    findings = raw['findings']
    if not isinstance(findings, list) or len(findings) > 12:
        raise ValueError('Invalid findings')
    valid = []
    for item in findings:
        if not isinstance(item, dict) or set(item) != {'statement', 'quote', 'source_id'}:
            raise ValueError('Invalid finding schema')
        if not isinstance(item['source_id'], str):
            raise ValueError('Invalid source identifier')
        source = sources.get(item['source_id'])
        quote, statement = item['quote'], item['statement']
        if not isinstance(quote, str) or not 12 <= len(quote) <= 800:
            raise ValueError('Invalid quotation')
        if source is None or quote not in source['text']:
            raise ValueError('Unsupported citation')
        if not isinstance(statement, str) or not 1 <= len(statement) <= 1200:
            raise ValueError('Invalid finding text')
        finding = {'statement': statement, 'quote': quote, 'source_id': source['id'],
                   'document_id': source['document_id'], 'filename': source['filename'],
                   'page': source['page']}
        finding.update(_metadata(source))
        for key in ('start_offset', 'end_offset'):
            if key in source:
                finding[key] = source[key]
        if 'start_offset' in source:
            finding['quote_start_offset'] = source['start_offset'] + source['text'].index(quote)
            finding['quote_end_offset'] = finding['quote_start_offset'] + len(quote)
        valid.append(finding)
    questions = raw['questions']
    if not isinstance(questions, list) or len(questions) > 12 or any(
            not isinstance(q, str) or not 1 <= len(q) <= 1000 for q in questions):
        raise ValueError('Invalid questions')
    summary = raw['summary']
    if not isinstance(summary, str) or not 1 <= len(summary) <= 2400:
        raise ValueError('Invalid summary')
    if truncated:
        questions = ['Only selected excerpts fit the model context. Review all original documents before deciding.'] + questions
    return {'status': 'REVIEW_REQUIRED' if valid else 'REQUIRES_MORE_INFO', 'summary': summary,
            'findings': valid, 'questions': questions, 'context_truncated': truncated,
            'notice': 'AI draft. Quoted text is checked against supplied excerpts; interpretation and completeness require human verification. No payable amount or final coverage decision is authorized.'}
