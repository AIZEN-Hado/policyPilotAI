"""Standard-library helpers shared by preparation and bounded model processes."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / 'data/synthetic/finetune-v1'
EVALUATION = ROOT / 'evaluation/finetune-v1'


def validate_cuda_build(capability, cuda_build, architectures):
    """Reject an incompatible Blackwell wheel before allocating probe tensors."""
    if capability[0] < 10:
        return
    try:
        major, minor = (int(value) for value in cuda_build.split('.')[:2])
    except (AttributeError, ValueError, TypeError):
        raise ValueError('Blackwell requires a verified CUDA-enabled PyTorch build') from None
    if (major, minor) < (12, 8):
        raise ValueError('Blackwell requires PyTorch built with CUDA 12.8 or newer; install the candidate cu128 wheel before model loading')
    target = str(capability[0]) + str(capability[1])
    if not {'sm_' + target, 'compute_' + target}.intersection(architectures):
        raise ValueError('PyTorch wheel lacks this Blackwell GPU architecture; choose a matching development image/cu128 wheel')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if read_json(path) != value:
        raise ValueError('JSON read-back verification failed')


def records(path):
    path = Path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Experiment JSONL exceeds the small-corpus limit')
    result = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    seen = set()
    for row in result:
        if not isinstance(row, dict) or row.get('synthetic') is not True:
            raise ValueError('Only explicitly synthetic records are accepted')
        if not isinstance(row.get('id'), str) or row['id'] in seen:
            raise ValueError('Missing or duplicate case identity')
        seen.add(row['id'])
    if not result:
        raise ValueError('Empty experiment corpus')
    return result


def prompt_messages(row):
    messages = row['messages']
    if not isinstance(messages, list) or len(messages) not in (2, 3):
        raise ValueError('Invalid message count')
    roles = ['system', 'user', 'assistant'][:len(messages)]
    if [m.get('role') for m in messages] != roles or any(not isinstance(m.get('content'), str) for m in messages):
        raise ValueError('Invalid message roles/content')
    return messages[:2]


def supervised_tokens(tokenizer, messages, maximum):
    """Train assistant tokens only; reject long examples instead of clipping labels."""
    prefix = tokenizer.apply_chat_template(messages[:2], tokenize=True, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False)
    if len(full) > maximum:
        raise ValueError('Example exceeds context; shorten data before paid training')
    if full[:len(prefix)] != prefix or len(full) <= len(prefix):
        raise ValueError('Tokenizer chat prefix is not aligned with the assistant answer')
    return full, [-100] * len(prefix) + full[len(prefix):]
