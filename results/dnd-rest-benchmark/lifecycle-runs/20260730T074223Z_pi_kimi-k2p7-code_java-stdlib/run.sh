#!/usr/bin/env bash
set -euo pipefail
PORT=${PORT:-8080}
javac --add-modules jdk.httpserver Main.java
exec java --add-modules jdk.httpserver -cp . Main
