#!/bin/sh
# Finish the remaining live cleanup and research imports from a network-enabled terminal.
set -eu
cd "$(dirname "$0")/.."

output=data/outputs/research
mkdir -p "$output/sources"
scratch=$(mktemp -d "$output/sources/.closeout.XXXXXX")
trap 'rm -rf "$scratch"' EXIT

download_and_import() {
    dataset=$1
    url=$2
    archive=$3
    destination=$4
    if [ ! -f "$archive" ]; then
        printf 'Downloading %s research archive.\n' "$dataset"
        curl --fail --location --retry 2 --connect-timeout 15 --max-time 180 \
            --output "$scratch/$dataset.zip" "$url" || return 1
        python -B -m specialists.research_data "$dataset" "$scratch/$dataset.zip" "$destination" || return 1
        mv "$scratch/$dataset.zip" "$archive" || return 1
    else
        python -B -m specialists.research_data "$dataset" "$archive" "$destination" || return 1
    fi
}

status=0
python -B deploy/smoke.py https://policypilot-demo.onrender.com --cleanup-only || status=1

download_and_import cms \
    'https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/de1_0_2008_to_2010_inpatient_claims_sample_1.zip' \
    "$output/sources/cms-inpatient-sample1.zip" "$output/cms-inpatient-sample1-v1" || status=1

download_and_import fieldbench \
    'https://zenodo.org/records/23065721/files/fieldbench-corpus-v0.4.2.zip?download=1' \
    "$output/sources/fieldbench-v0.4.2.zip" "$output/fieldbench-v0.4.2" || status=1

if [ "$status" -ne 0 ]; then
    echo 'Closeout incomplete. Successful imports are saved and verified on the next run.' >&2
    exit "$status"
fi
echo 'PASS: live cleanup queue is empty and both research datasets are prepared.'
