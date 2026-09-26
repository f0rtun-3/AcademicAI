#!/bin/bash
# Prints the verification / reset codes the console email backend emitted.
#
# DEVELOPMENT ONLY. With EMAIL_BACKEND=console there is no mail server, so the
# code is printed to the API's stdout instead of being delivered. Start the API
# with `python -u`, or print() output sits in a buffer and never reaches the log.
#
#   ./scripts/dev_code.sh                      # every code, newest last
#   ./scripts/dev_code.sh instance/api.log me@x  # only codes sent to one address
LOG=${1:-instance/api.log}
WHO=${2:-}
[ -f "$LOG" ] || { echo "No log at $LOG"; exit 1; }
python3 - "$LOG" "$WHO" <<'PY'
import re, sys
log, who = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
lines = open(log, errors="replace").read().splitlines()

# Flask's access log goes to stderr and interleaves with these emails in the
# same file, so the code is found by its SHAPE - a long opaque token on a line
# of its own - rather than by counting lines after the header.
TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,}$")
HEADER = re.compile(r"^\[email\] to=(\S+) subject=(.+)$")

found, pending = [], None
for line in lines:
    m = HEADER.match(line)
    if m:
        pending = (m.group(1), m.group(2))
        continue
    if pending and TOKEN.match(line.strip()):
        to, subject = pending
        if not who or who.lower() in to.lower():
            found.append((to, subject, line.strip()))
        pending = None

if not found:
    print(f"No code for {who} yet." if who else "No code in the log yet.")
    print("Trigger one (sign up, or press 'Send a new code'), then run this again.")
    sys.exit(1)
for to, subject, code in found:
    print(f"{to}\n  {subject}\n  code: {code}\n")
PY
