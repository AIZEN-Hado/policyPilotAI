"""Explicit CPU inference entrypoint. Does not invoke or relax research execution guards."""
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile
import threading
import time

from pilot.specialist_client import LABELS, MAX_BYTES, MAX_ITEMS, prepare_documents, result
from .artifacts import verify_archive
from .contracts import TOKEN_PATTERN
from .features import decode_spans, ranking_features
from .models import MAX_WEIGHT_BYTES, build_models, parameter_estimate
from .runtime import ARCHITECTURES, _encode_span, _feature_spec, _predict_rank, _predict_spans, _validate_training

QUERIES = {
    'POLICY_ID': 'What is the policy number?', 'MEMBER_ID': 'What is the member ID?',
    'ADMISSION_DATE': 'What is the admission date?', 'DISCHARGE_DATE': 'What is the discharge date?',
    'ROOM_LIMIT': 'What is the daily room rent limit?', 'SUM_INSURED': 'What is the sum insured?',
}
ARCHIVE_LIMIT = 64 * 1024 * 1024
MAX_WINDOWS = 192


def load_checkpoint(path, digest, torch_module=None):
    """Freeze archive bytes before verification and deserialize only verified state dictionaries."""
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('A pinned archive SHA256 is required')
    from .artifacts import _open_regular
    with _open_regular(Path(path)) as stream:
        data = stream.read(ARCHIVE_LIMIT + 1)
    if len(data) > ARCHIVE_LIMIT or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Checkpoint archive fingerprint mismatch')
    with tempfile.TemporaryDirectory(prefix='specialist-verified-') as directory:
        archive = Path(directory) / 'checkpoint.tar.gz'
        archive.write_bytes(data)
        verified = verify_archive(archive, max_bytes=ARCHIVE_LIMIT)
        entries = {entry['path']: entry for entry in verified['manifest']['files']}
        if not {'metadata.json', 'span.pt', 'rank.pt', 'validation.json', 'reload.json'} <= set(entries):
            raise ValueError('Checkpoint is missing trained artifacts')
        with tarfile.open(archive, 'r:gz') as bundle:
            metadata = json.load(bundle.extractfile('metadata.json'))
            config = metadata['config']
            _validate_training(config['training'])
            if (config.get('schema_version') != 1 or config.get('generative_model') is not False or
                    config.get('pretrained_language_backbone') is not None or
                    metadata.get('schema_version') != 1 or metadata.get('architectures') != ARCHITECTURES or
                    metadata.get('parameters') != parameter_estimate(config) or
                    metadata.get('features') != _feature_spec(config)):
                raise ValueError('Checkpoint configuration or features mismatch')
            span = config['span']
            if (not 32 <= span['max_tokens'] <= 512 or not 1 <= span['max_chars_per_token'] <= 128 or
                    type(span.get('contextual_values', False)) is not bool or
                    span.get('context_feature_version', 1) not in (1, 2)):
                raise ValueError('Unsupported span preprocessing')
            fingerprints = metadata['input_fingerprints']
            from .evaluate import load_verified_checkpoint
            # Preserve the existing completed-training and independent-reload gates.
            load_verified_checkpoint(archive, digest, fingerprints['dataset_manifest_sha256'],
                                     config_sha256=fingerprints['config_sha256'])
            if any(not re.fullmatch('[0-9a-f]{64}', fingerprints.get(key, ''))
                   for key in ('config_sha256', 'dataset_manifest_sha256')):
                raise ValueError('Missing training input fingerprints')
            if not fingerprints.get('files') or any(not re.fullmatch('[0-9a-f]{64}', value)
                                                   for value in fingerprints['files'].values()):
                raise ValueError('Missing training dataset fingerprints')
            if metadata['validation_sha256'] != entries['validation.json']['sha256']:
                raise ValueError('Validation fingerprint mismatch')
            validation = json.load(bundle.extractfile('validation.json'))
            if validation.get('input_fingerprints') != fingerprints or validation.get('method') != 'neural_specialists':
                raise ValueError('Validation training identity mismatch')
            weights = {}
            for task in ('span', 'rank'):
                entry = entries[task + '.pt']
                if metadata['weights'][task] != entry:
                    raise ValueError('Weight fingerprint mismatch')
                updates = metadata['training_updates'][task]
                if type(updates.get('steps')) is not int or updates['steps'] < 1:
                    raise ValueError('Missing training updates')
                weights[task] = bundle.extractfile(task + '.pt').read()
            if sum(map(len, weights.values())) > min(config['max_weight_bytes'], MAX_WEIGHT_BYTES):
                raise ValueError('Weight budget exceeded')
    if torch_module is None:
        import torch as torch_module
    torch_module.set_num_threads(2)
    models = build_models(torch_module, config)
    for task, model in models.items():
        state = torch_module.load(io.BytesIO(weights[task]), map_location='cpu', weights_only=True)
        if any(not torch_module.isfinite(tensor).all().item() for tensor in state.values()):
            raise ValueError('Nonfinite checkpoint weights')
        model.load_state_dict(state, strict=True)
        model.eval()
    return Engine(torch_module, models, config, digest)


def windows(documents, max_tokens):
    output = []
    stride = max_tokens - min(64, max_tokens // 4)
    for doc in documents:
        for page in doc['pages']:
            tokens = list(TOKEN_PATTERN.finditer(page['text']))
            for index in range(0, len(tokens), stride):
                chosen = tokens[index:index + max_tokens]
                start, end = chosen[0].start(), chosen[-1].end()
                output.append((doc, page, start, end))
                if len(output) > MAX_WINDOWS:
                    raise ValueError('Window limit exceeded')
                if index + max_tokens >= len(tokens):
                    break
    return output


def citation(doc, page, start, end):
    return dict(document_id=doc['id'], filename=doc['filename'], page=page['page'],
                start_offset=start, end_offset=end, source_text=page['text'][start:end],
                review_reasons=['neural_suggestion_unverified'])


class Engine:
    def __init__(self, torch, models, config, digest):
        self.torch, self.models, self.config, self.digest = torch, models, config, digest

    def review(self, documents):
        documents, skipped = prepare_documents(documents)
        if skipped:
            raise ValueError('Unsupported document kind')
        chunks = windows(documents, self.config['span']['max_tokens'])
        response = result('ready', 'Scores order evidence; they are not probabilities.', self.digest)
        response['detail'] += ' Decoder: ' + ('joint-structured-v1.' if self.config['training'].get('structured_objectives', False) else 'bio-argmax-v1.')
        seen = {label: set() for label in LABELS}
        deadline = time.monotonic() + 10
        structured = self.config['training'].get('structured_objectives', False)
        for doc, page, offset, end in chunks:
            if time.monotonic() > deadline:
                raise TimeoutError('Inference deadline exceeded')
            row = {'kind': doc['kind'], 'text': page['text'][offset:end], 'spans': []}
            encoded = _encode_span(row, self.config['span'])
            if structured:
                from .runtime import _batch_span
                from .joint_selection import joint_tags
                from .structured import value_candidates
                with self.torch.inference_mode():
                    inputs, _ = _batch_span(self.torch, [(row, encoded)], 'cpu')
                    logits = self.models['span'](*inputs)
                    if not self.torch.isfinite(logits).all().item():
                        raise ValueError('Nonfinite span logits')
                    tags, _ = joint_tags(logits[0].cpu().tolist(), value_candidates(row['text'], encoded['offsets']))
            else:
                tags = _predict_spans(self.torch, self.models['span'], [(row, encoded)], 1, 'cpu', False)[0]
            for span in decode_spans(row['text'], encoded['offsets'], tags):
                label = span['label']
                start, stop = offset + span['start'], offset + span['end']
                key = (doc['id'], page['page'], start, stop)
                if key not in seen[label]:
                    item = citation(doc, page, start, stop)
                    item['value'] = item['source_text']
                    response['suggestions'][label].append(item)
                    seen[label].add(key)
                    if len(seen[label]) > MAX_ITEMS:
                        raise ValueError('Prediction limit exceeded')
            examples = [({'relevant': False}, ranking_features(query, row['text'], doc['kind'], self.config['rank']))
                        for query in QUERIES.values()]
            scores = _predict_rank(self.torch, self.models['rank'], examples, 6, 'cpu', structured)
            for label, score in zip(QUERIES, scores, strict=True):
                response['evidence'][label].append({**citation(doc, page, offset, end), 'score': score})
        for label in LABELS:
            response['evidence'][label] = sorted(response['evidence'][label], key=lambda item: -item['score'])[:10]
        return response


def create_app(engine=None):
    """Factory loads the checkpoint once; failures prevent the service from starting."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    token = os.environ.get('SPECIALIST_TOKEN', '')
    if not 16 <= len(token) <= 512 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError('A service token of at least 16 printable characters is required')
    if engine is None:
        engine = load_checkpoint(os.environ['SPECIALIST_ARCHIVE'], os.environ['SPECIALIST_CHECKPOINT_SHA256'])
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    lock = threading.Lock()

    @app.post('/review')
    async def review(request: Request):
        if not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + token):
            return JSONResponse({'detail': 'Unauthorized'}, status_code=401)
        if not lock.acquire(blocking=False):
            return JSONResponse({'detail': 'Busy'}, status_code=503)
        transferred = False
        try:
            import asyncio
            async def read_body():
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise ValueError('Request too large')
                return body
            body = await asyncio.wait_for(read_body(), timeout=3)
            payload = json.loads(body)
            # The worker thread owns the lock until completion even if the HTTP caller disconnects.
            def run():
                try:
                    return engine.review(payload['documents'])
                finally:
                    lock.release()
            task = asyncio.create_task(asyncio.to_thread(run))
            transferred = True
            response = await asyncio.shield(task)
            encoded = json.dumps(response, allow_nan=False).encode()
            if len(encoded) > MAX_BYTES:
                raise ValueError('Response too large')
            return JSONResponse(response)
        except Exception:
            return JSONResponse({'detail': 'Inference unavailable'}, status_code=503)
        finally:
            if not transferred:
                lock.release()
    return app
