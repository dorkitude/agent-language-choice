#!/bin/sh
# POSIX shell script: compile Main.java then run it, reading stdin -> stdout.
set -e
cd "$(dirname "$0")"
javac Main.java
java Main
