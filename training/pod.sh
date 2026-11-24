#!/bin/sh
# Existing Pod only. No packages installed, model pulled, or provider resources created here.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
exec python -m training.run "$@"
