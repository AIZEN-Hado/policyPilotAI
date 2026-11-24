"""GPU-only child. Use training.run for deadlines, memory measurement and receipts."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import random
import shutil
import subprocess

from .artifacts import MANIFEST, snapshot, verify
from .common import CORPUS, ROOT, digest, prompt_messages, read_json, records, save_json, supervised_tokens, validate_cuda_build


def preflight(config, torch):
    if not torch.cuda.is_available():
        raise ValueError('CUDA is required; no CPU fallback or real-model download is allowed')
    if torch.cuda.device_count() != 1:
        raise ValueError('Expose exactly one GPU for this bounded experiment')
    memory = torch.cuda.get_device_properties(0).total_memory
    if memory < config['minimum_gpu_memory_bytes']:
        raise ValueError('The prepared experiment requires a 24 GB class GPU')
    capability = torch.cuda.get_device_capability(0)
    architectures = torch.cuda.get_arch_list()
    validate_cuda_build(capability, torch.version.cuda, architectures)
    compiler = shutil.which(os.environ.get('CC', 'cc'))
    if compiler is None:
        raise ValueError('C compiler missing. Use a development image with GCC and C headers before loading bitsandbytes')
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as folder:
        source = Path(folder) / 'probe.c'
        source.write_text('#include <Python.h>\nint main(void) { return 0; }\n')
        import sysconfig
        process = subprocess.run([compiler, '-I' + sysconfig.get_path('include'), '-c', str(source),
                                  '-o', str(Path(folder) / 'probe.o')], capture_output=True, timeout=15)
        if process.returncode:
            raise ValueError('C compiler/Python development headers probe failed; do not load the large model')
    import bitsandbytes as bnb
    layer = bnb.nn.Linear4bit(16, 16, bias=False, compute_dtype=torch.float16,
                             quant_type='nf4', compress_statistics=True).cuda()
    x = torch.ones((2, 16), device='cuda', dtype=torch.float16, requires_grad=True)
    loss = layer(x).float().square().mean()
    loss.backward()
    torch.cuda.synchronize()
    if x.grad is None or not torch.isfinite(x.grad).all().item():
        raise ValueError('Native 4-bit GPU forward/backward probe failed')
    del x, loss, layer
    # Tiny randomly initialized Qwen2: validates architecture imports and CUDA
    # backward, not the real checkpoint or task quality. No download occurs.
    from transformers import Qwen2Config, Qwen2ForCausalLM
    tiny = Qwen2ForCausalLM(Qwen2Config(vocab_size=64, hidden_size=32, intermediate_size=64,
                                      num_hidden_layers=1, num_attention_heads=4,
                                      num_key_value_heads=2, max_position_embeddings=64)).cuda()
    ids = torch.tensor([[1, 2, 3, 4]], device='cuda')
    loss = tiny(input_ids=ids, labels=ids).loss
    loss.backward()
    if not torch.isfinite(loss).item():
        raise ValueError('Tiny synthetic Qwen2 CUDA loss is nonfinite')
    del tiny, loss, ids
    torch.cuda.empty_cache()
    return {'gpu_name': torch.cuda.get_device_name(0), 'gpu_memory_bytes': memory,
            'gpu_compute_capability': list(capability), 'torch_compiled_architectures': architectures,
            'torch_cuda_build': torch.version.cuda, 'compiler_and_python_headers': True,
            'native_4bit_forward_backward': True, 'tiny_synthetic_qwen_cuda_backward': True,
            'real_model_tested': False}


def check_versions():
    expected = {}
    for line in (ROOT / 'training/requirements.txt').read_text().splitlines():
        if '==' in line and not line.lstrip().startswith('#'):
            name, version = line.split('==')
            actual = importlib.metadata.version(name)
            if actual.split('+')[0] != version:
                raise ValueError(f'Candidate environment version mismatch: {name}; install the pinned experiment environment first')
            expected[name] = actual
    return expected


def load(config, workspace, torch, cache_only=False):
    from huggingface_hub import snapshot_download
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    receipt_path = workspace / 'base-receipt.json'
    if not receipt_path.exists() and shutil.disk_usage(workspace).free < 18_000_000_000:
        raise ValueError('At least 18 GB free is required before staging the pinned original checkpoint')
    location = Path(snapshot_download(
        repo_id=config['model'], revision=config['revision'], cache_dir=workspace / 'cache/hub',
        local_files_only=cache_only,
        allow_patterns=['*.safetensors', '*.safetensors.index.json', 'config.json', 'generation_config.json',
                        'tokenizer.json', 'tokenizer_config.json', 'vocab.json', 'merges.txt', 'LICENSE', 'README.md']))
    if location.name != config['revision']:
        raise ValueError('Resolved checkpoint revision differs from the pinned commit')
    files = sorted(p for p in location.iterdir() if p.is_file())
    if not any(p.suffix == '.safetensors' for p in files):
        raise ValueError('Pinned base has no safetensors checkpoint')
    if receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt.get('model') != config['model'] or receipt.get('revision') != config['revision']:
            raise ValueError('Cached base receipt belongs to another model revision')
        # Verify staged base bytes on every invocation; this costs I/O time but
        # never silently blesses modified shared-volume weights.
        if receipt['files'] != {p.name: digest(p) for p in files}:
            raise ValueError('Cached pinned base changed since staging')
    else:
        save_json(receipt_path, {'model': config['model'], 'revision': config['revision'],
                                'license': config['license'], 'files': {p.name: digest(p) for p in files}})
    tokenizer = AutoTokenizer.from_pretrained(location, local_files_only=True, trust_remote_code=False)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = 'right'
    model = AutoModelForCausalLM.from_pretrained(
        location, local_files_only=True, trust_remote_code=False, use_safetensors=True,
        low_cpu_mem_usage=True, torch_dtype=torch.float16, device_map={'': 0},
        attn_implementation='sdpa', quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16))
    model.config.pad_token_id = tokenizer.pad_token_id
    return model, tokenizer


def predict(model, tokenizer, row, config, torch, max_new_tokens=None):
    messages = prompt_messages(row)
    ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_tensors='pt')
    maximum = max_new_tokens or config['max_new_tokens']
    if ids.shape[1] + maximum > config['max_sequence_tokens']:
        raise ValueError('Prompt plus response exceeds experiment context; no silent truncation')
    model.eval()
    with torch.inference_mode():
        output = model.generate(input_ids=ids.to('cuda'), attention_mask=torch.ones_like(ids).to('cuda'),
                                max_new_tokens=maximum, do_sample=False, use_cache=True,
                                pad_token_id=tokenizer.pad_token_id, eos_token_id=tokenizer.eos_token_id)
    tokens = output[0, ids.shape[1]:].tolist()
    text = tokenizer.decode(tokens, skip_special_tokens=True)
    # Retain invalid/truncated synthetic responses as failures, never repair JSON.
    try:
        value = json.loads(text) if tokens and tokens[-1] == tokenizer.eos_token_id else None
    except ValueError:
        value = None
    return {'id': row['id'], 'synthetic': True, 'output': value,
            'raw_synthetic_response': text, 'generated_tokens': len(tokens),
            'ended_with_eos': bool(tokens and tokens[-1] == tokenizer.eos_token_id)}


def train(model, tokenizer, config, output, torch, workspace):
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    rows = records(CORPUS / 'train.jsonl')
    for row in rows:
        prompt_messages(row)
        if row.get('split') != 'train' or len(row['messages']) != 3:
            raise ValueError('Training can consume only the prepared train split')
    encoded = [supervised_tokens(tokenizer, row['messages'], config['max_sequence_tokens']) for row in rows]
    random.Random(config['seed']).shuffle(encoded)
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                           gradient_checkpointing_kwargs={'use_reentrant': False})
    model = get_peft_model(model, LoraConfig(
        task_type='CAUSAL_LM', r=config['lora_rank'], lora_alpha=config['lora_alpha'],
        lora_dropout=config['lora_dropout'], target_modules=config['target_modules'], bias='none'))
    parameters = [p for p in model.parameters() if p.requires_grad]
    if not parameters:
        raise ValueError('No trainable LoRA parameters')
    optimizer = torch.optim.AdamW(parameters, lr=config['learning_rate'])
    scaler = torch.amp.GradScaler('cuda')
    losses = []
    model.train()
    optimizer.zero_grad(set_to_none=True)
    accumulation = config['gradient_accumulation']
    for step in range(config['max_steps']):
        total = 0.0
        for micro in range(accumulation):
            ids, labels = encoded[(step * accumulation + micro) % len(encoded)]
            inputs = torch.tensor([ids], device='cuda')
            targets = torch.tensor([labels], device='cuda')
            with torch.autocast('cuda', dtype=torch.float16):
                loss = model(input_ids=inputs, attention_mask=torch.ones_like(inputs), labels=targets).loss
            if not torch.isfinite(loss).item():
                raise ValueError('Training loss became nonfinite')
            total += float(loss.detach().cpu())
            scaler.scale(loss / accumulation).backward()
            del loss, inputs, targets
        scaler.unscale_(optimizer)
        norm = torch.nn.utils.clip_grad_norm_(parameters, 1.0)
        if not torch.isfinite(norm).item():
            raise ValueError('Training gradient norm became nonfinite; no adapter acceptance')
        scaler.step(optimizer)
        scaler.update()
        optimizer.zero_grad(set_to_none=True)
        losses.append(total / accumulation)
        print('Completed optimizer step', step + 1, 'of', config['max_steps'], flush=True)
    adapter = output / 'adapter'
    adapter.mkdir()
    model.save_pretrained(adapter, safe_serialization=True)
    tokenizer.save_pretrained(adapter)
    save_json(adapter / 'provenance.json', {
        'base_model': config['model'], 'base_revision': config['revision'],
        'base_receipt_sha256': digest(workspace / 'base-receipt.json'),
        'dataset_manifest_sha256': digest(CORPUS / 'manifest.json'),
        'config_sha256': digest(ROOT / 'training/config.json'), 'synthetic_only': True,
        'optimizer_steps': len(losses), 'examples_seen': len(losses) * accumulation,
        'trainable_parameters': sum(p.numel() for p in parameters), 'losses': losses,
        'validation_labels_used': False, 'held_out_test_accessed': False,
        'model_quality_verified': False, 'artifact_scope': 'LoRA adapter; pinned original base required'} )
    if not (adapter / 'adapter_model.safetensors').is_file():
        raise ValueError('Expected a safetensors LoRA adapter')
    snapshot(adapter, {'base_model': config['model'], 'base_revision': config['revision'],
                       'dataset_manifest_sha256': digest(CORPUS / 'manifest.json')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('preflight', 'baseline', 'train', 'predict', 'reload'), required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--adapter', type=Path)
    parser.add_argument('--prompts', type=Path, default=CORPUS / 'validation-prompts.jsonl')
    parser.add_argument('--limit', type=int, default=9)
    args = parser.parse_args()
    if os.environ.get('POLICYPILOT_BOUNDED_CHILD') != '1':
        raise ValueError('Use python -m training.run; direct GPU child execution is disabled')
    if (not os.environ.get('RUNPOD_POD_ID') or not args.workspace.resolve().is_relative_to(Path('/workspace'))
            or not os.path.ismount('/workspace')):
        raise ValueError('A provider Pod ID and persistent network volume at /workspace are required')
    versions = check_versions()
    import torch
    config = read_json(ROOT / 'training/config.json')
    if config.get('model_execution_location') != 'remote_gpu_pod_only':
        raise ValueError('Model execution must remain restricted to the remote GPU Pod')
    try:
        execute(args, config, torch, versions)
    finally:
        import resource
        save_json(args.output / 'model-memory.json', {
            'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            'cuda_peak_allocated_bytes': torch.cuda.max_memory_allocated() if torch.cuda.is_initialized() else 0,
            'cuda_peak_reserved_bytes': torch.cuda.max_memory_reserved() if torch.cuda.is_initialized() else 0,
            'scope': 'This single model process; receipt may be absent after forced termination.'})


def execute(args, config, torch, versions):
    random.seed(config['seed']); torch.manual_seed(config['seed'])
    probe = preflight(config, torch)
    probe['versions'] = versions
    save_json(args.output / 'preflight.json', probe)
    if args.mode == 'preflight':
        return
    model, tokenizer = load(config, args.workspace, torch, cache_only=args.mode == 'reload')
    if args.mode == 'train':
        train(model, tokenizer, config, args.output, torch, args.workspace)
        return
    if args.mode in ('predict', 'reload'):
        if args.adapter is None:
            raise ValueError('Frozen adapter is required')
        manifest = verify(args.adapter)
        provenance = read_json(args.adapter / 'provenance.json')
        if (manifest['metadata']['base_revision'] != config['revision']
                or provenance.get('base_model') != config['model']
                or provenance.get('base_revision') != config['revision']
                or provenance.get('base_receipt_sha256') != digest(args.workspace / 'base-receipt.json')):
            raise ValueError('Adapter and pinned base provenance do not match')
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.adapter, is_trainable=False,
                                         local_files_only=True, device_map={'': 0})
    prompts = records(args.prompts)
    if any(len(row['messages']) != 2 or row.get('split') not in ('validation', 'test') for row in prompts):
        raise ValueError('Prediction requires prompt-only evaluation examples')
    if args.mode == 'reload':
        row = predict(model, tokenizer, prompts[0], config, torch, max_new_tokens=32)
        save_json(args.output / 'reload.json', {
            'reload_and_generation_passed': row['generated_tokens'] > 0,
            'adapter_manifest_sha256': digest(args.adapter / MANIFEST),
            'base_revision': config['revision'], 'generated_tokens': row['generated_tokens'],
            'synthetic_prompt_id': row['id'], 'task_quality_verified': False})
        return
    selected = prompts if args.limit == 0 else prompts[:args.limit]
    path = args.output / 'predictions.jsonl'
    with path.open('x') as stream:
        for row in selected:
            result = predict(model, tokenizer, row, config, torch)
            result.update(base_revision=config['revision'], adapter_manifest_sha256=(digest(args.adapter / MANIFEST) if args.adapter else None),
                          prompt_sha256=digest(args.prompts))
            stream.write(json.dumps(result, allow_nan=False) + '\n')
            stream.flush()
    save_json(args.output / 'generation.json', {'cases': len(selected), 'prompt_sha256': digest(args.prompts),
                                             'predictions_sha256': digest(path), 'model_quality_verified': False})


if __name__ == '__main__':
    main()
