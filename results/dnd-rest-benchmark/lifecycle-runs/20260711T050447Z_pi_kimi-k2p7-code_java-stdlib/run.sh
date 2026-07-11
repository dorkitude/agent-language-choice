#!/usr/bin/env bash
set -euo pipefail
javac Main.java
exec java Main
