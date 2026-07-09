#!/bin/sh
# Apply timestamped key-value patches. Reads JSON Lines from stdin,
# writes "key=value" lines (sorted by key) to stdout.
exec php main.php
