#!/bin/bash
# jobs.sh setting:data:sample ...   Runs the supervisor over these jobs.
B=/private/tmp/claude-501/-Users-ksirg-devel-cogito-mem/2f8e80c5-f08b-4456-93a3-d17ec6ff8ff3/scratchpad/rivals-m
exec "$B/shared/env/bin/python" -I "$B/adapters/supervise.py" --base "$B" --check "$B/../check_quiet.sh" --wait "$B/../wait_quiet.sh" "$@"
