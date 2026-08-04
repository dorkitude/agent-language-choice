#!/usr/bin/env bash
set -euo pipefail
rustc --edition=2024 src/main.rs -o dndrest
./dndrest
