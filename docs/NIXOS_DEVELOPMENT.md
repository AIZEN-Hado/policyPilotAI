# NixOS development

The host uses Nix, while the release container uses Debian. The Dockerfile's apt
commands run inside its image; do not run them on the NixOS host.

From the repository root:

```sh
nix --extra-experimental-features 'nix-command flakes' develop path:.
python scripts/dev/check.py
python scripts/dev/check.py --require-docker
```

The explicit `path:.` includes files in a checkout even before Git tracks them.
The flake fixes a nixpkgs revision; generate and retain `flake.lock` on first
successful resolution. Network access and permission to use the Nix daemon are
required for missing packages. No machine-specific store paths are embedded.

For machines without flakes, `nix-shell` uses the installed channel. It is a
convenience fallback, not an identical pinned environment. Python dependencies
come from Nix to avoid incompatible generic Linux wheels on NixOS. Their versions
can differ from the release pins, so passing here does not replace container tests.

The shell includes Python 3.12, API dependencies, Node for JavaScript checks,
Poppler and Tesseract with English/Hindi data, and a Docker client. It does not
start services, download model weights, install system packages or change NixOS.
The check script fails if dependencies, OCR language data or tests are missing;
skipped API tests cannot produce a green readiness result.

## Docker access

The Docker client is already installed on the current machine, but this authoring
session receives permission denied on its daemon socket. Check `docker info` in
your ordinary terminal. A sandbox denial is not evidence that the host daemon
needs reinstalling. Do not make the Docker socket world writable.

If Docker is not enabled on your machine, configure it through your own NixOS
configuration using the [official NixOS instructions](https://wiki.nixos.org/wiki/Docker).
Membership in the Docker group grants root-equivalent control. This project does
not change `/etc/nixos` or user groups automatically.

## Runtime verification still required

Run the release dependency tests inside the built app image, then PostgreSQL
integration, real OCR, private inference, browser flows and recovery checks from
[the phased plan](RENDER_RELEASE_PLAN.md). The existing `deploy/start.sh` is a
VPS deployment script, not a local development command or a Render installer.
