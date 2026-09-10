#!/usr/bin/env bash
set -euo pipefail
if [[ ! -f Main.class || Main.java -nt Main.class ]]; then
  javac Main.java
fi
exec java Main
