"""Measure one local llama.cpp CLI run. No downloads, provider calls or training."""
import argparse
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True, help='Local Q4_K_M GGUF file')
    parser.add_argument('--binary', default='llama-cli')
    parser.add_argument('--output', type=Path, default=Path('/tmp/policypilot-model-benchmark.json'))
    args = parser.parse_args()
    if sys.platform != 'linux':
        raise SystemExit('This peak-RSS measurement is defined for Linux.')
    binary = shutil.which(args.binary)
    if not binary or not args.model.is_file():
        raise SystemExit('Install llama.cpp and supply an existing GGUF file. Nothing was downloaded.')
    prompt = ('Read this synthetic excerpt: "Registration fees are excluded." '
              'Return JSON with keys summary, quote, and needs_review. '
              'Quote the exact exclusion. Do not calculate a payout.')
    command = [binary, '-m', str(args.model.resolve()), '-c', '2048', '-n', '256',
               '-t', '4', '-ngl', '0', '--temp', '0', '-p', prompt]
    # Run exactly one child in this fresh script so RUSAGE_CHILDREN is meaningful.
    # Peak RSS is measured, not constrained by an address-space limit: mapped files
    # and reserved virtual address space are not interchangeable with resident RAM.
    start = time.monotonic()
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=180, check=False)
    except subprocess.TimeoutExpired:
        raise SystemExit('Benchmark exceeded 180 seconds and was terminated. No fit claim made.') from None
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024
    limit = 2_000_000_000
    report = {
        'model_filename': args.model.name,
        'model_bytes': args.model.stat().st_size,
        'context_tokens': 2048, 'max_output_tokens': 256, 'threads': 4,
        'peak_rss_bytes': peak, 'target_ram_bytes': limit,
        'wall_seconds': round(time.monotonic()-start, 2),
        'exit_code': result.returncode,
        'memory_target_passed': result.returncode == 0 and peak < limit,
        'scope': 'One CPU CLI process with a short synthetic prompt. Not server/concurrent/long-context peak or task-quality acceptance.',
        'model_output': result.stdout[-16000:],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Peak resident RAM: {peak/1e9:.2f} GB; elapsed: {report["wall_seconds"]} seconds')
    print('PASS for this short prompt only' if report['memory_target_passed'] else 'FAIL: model run or RAM target')
    print(f'Synthetic benchmark report saved to {args.output}')
    return 0 if report['memory_target_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
