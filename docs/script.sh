#!/usr/bin/env sh

set -e -x

nix build
cp result/*.pdf .
chmod 664 *.pdf
unlink result
