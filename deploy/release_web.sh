#!/bin/sh
# Check the workspace and the exact API image before the private registry upload.
set -eu

cd "$(dirname "$0")/.."
if [ "$#" -ne 1 ]; then
    echo 'Usage: sh deploy/release_web.sh GITHUB_USERNAME' >&2
    exit 2
fi

python deploy/preview_ui.py
python -m unittest discover -s deploy/tests -v
node deploy/tests/check_ui.mjs
node deploy/tests/check_evidence_search.mjs

docker buildx build --platform linux/amd64 --load -f pilot/Dockerfile -t policypilot-api:demo .
docker run --rm --network none --entrypoint python policypilot-api:demo -m pilot.check_tests
python deploy/publish_images.py "$1" --only api
