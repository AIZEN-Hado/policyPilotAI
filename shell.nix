# nix-shell uses your installed channel; nix develop uses the revision in flake.nix.
{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  packages = [
    (pkgs.python312.withPackages (ps: with ps; [ fastapi uvicorn httpx psycopg boto3 ]))
    pkgs.nodejs
    pkgs.poppler-utils
    (pkgs.tesseract.override { enableLanguages = [ "eng" "hin" ]; })
    pkgs.docker-client
  ];
  shellHook = ''
    export PYTHONNOUSERSITE=1
    echo "PolicyPilot tools ready. Run: python scripts/dev/check.py"
    echo "Nix package versions may differ from pilot/requirements.txt; Docker remains the release test environment."
  '';
}
