#!/usr/bin/env bash
set -euo pipefail
javac -d . dnd/Main.java dnd/model/*.java dnd/storage/*.java dnd/json/*.java dnd/game/*.java dnd/handlers/*.java dnd/server/*.java
exec java dnd.Main
