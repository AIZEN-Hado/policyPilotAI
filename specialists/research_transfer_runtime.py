"""Warm-start the research run through the bounded specialist launcher."""

import argparse
import os
from pathlib import Path
import sys

from . import run, runtime
from .evaluate import load_verified_checkpoint, restore_models
from .execution import require_remote
from .models import parameter_estimate


def stage(name, config_path, data, output):
    if name != "train":
        return runtime.run_stage(name, config_path, data, output)
    project, data, output = require_remote(runtime.PROJECT_ROOT, data, output, child=True)
    if not sys.dont_write_bytecode or os.environ.get("PYTHONDONTWRITEBYTECODE") != "1":
        raise ValueError("Start the verified runtime with bytecode writes disabled")
    config, files, fingerprints = runtime._load_inputs(project, config_path.resolve(), data)
    if (config.get("schema_version") != 1 or config.get("model_execution_location") != "remote_runpod_cpu_only"
            or config.get("generative_model") is not False or config.get("pretrained_language_backbone") is not None
            or not config["training"].get("structured_objectives") or "self_training" in config):
        raise ValueError("Research transfer requires the structured hosted CPU runtime")
    runtime._validate_training(config["training"])
    reference = config["warm_start"]
    checkpoint = Path(reference["archive"]).resolve()
    if not checkpoint.is_relative_to(Path("/workspace").resolve()):
        raise ValueError("Keep the reference checkpoint on the mounted volume")
    old, weights = load_verified_checkpoint(checkpoint, reference["sha256"], reference["training_manifest_sha256"],
                                            config_sha256=reference["config_sha256"])
    if (any(old[key] != config[key] for key in ("span", "rank"))
            or parameter_estimate(old) != parameter_estimate(config)):
        raise ValueError("Warm start changes specialist architecture or features")
    training = runtime._read_split(data, "train", config, files)
    validation = runtime._read_split(data, "validation", config, files)
    torch, device = runtime._load_cpu_torch(config["training"])
    models = restore_models(torch, config, weights)
    return runtime._train_and_export(torch, models, config, training, validation, output, fingerprints, device)


def main():
    if os.environ.get("POLICYPILOT_SPECIALIST_CHILD") != "1":
        return run.main(runtime_module="specialists.research_transfer_runtime")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=runtime.STAGES, required=True)
    for name in ("config", "data-directory", "output-directory"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    stage(args.stage, args.config, args.data_directory, args.output_directory)


if __name__ == "__main__":
    raise SystemExit(main())
