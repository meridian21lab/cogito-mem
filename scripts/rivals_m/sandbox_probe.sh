#!/bin/sh
# Run inside run_sandboxed.sh. Every line below the first two should be refused.
echo "HOME=$HOME"
echo "secret-looking variables: $(env | grep -iE 'key|token|anthropic|openai|claude' | cut -d= -f1 | tr '\n' ' ')"
ls /Users/ksirg/.claude 2>&1 | head -1
ls /Users/ksirg/.cogito-mem 2>&1 | head -1
head -c 40 /Users/ksirg/devel/cogito-mem/.env 2>&1 | head -1 | cut -c1-60
touch /Users/ksirg/rival-write-test 2>&1
/usr/bin/curl -s -m 5 -o /dev/null -w "curl http %{http_code}\n" https://example.com
echo "curl exit $?"
touch "$HOME/ok" && echo "own home writable"
