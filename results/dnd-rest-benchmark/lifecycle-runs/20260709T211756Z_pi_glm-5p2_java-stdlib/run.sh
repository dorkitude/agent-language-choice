#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
javac Main.java
exec java Main
