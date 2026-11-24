{
  description = "PolicyPilot local development tools (deployment uses pilot/Dockerfile)";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/da6dc0e7b26060f2f71ce3ef7088fb56ee44fa36";
  outputs = { self, nixpkgs }: {
    devShells = nixpkgs.lib.genAttrs [ "x86_64-linux" "aarch64-linux" ] (system: {
      default = import ./shell.nix { pkgs = import nixpkgs { inherit system; }; };
    });
  };
}
