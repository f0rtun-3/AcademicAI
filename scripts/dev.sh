#!/bin/bash
# Start AcademicAI for local development: the Flask API and the Vite dev server
# together, with the demo database and the console email backend.
#
#   ./scripts/dev.sh            # or: make dev
#   ./scripts/dev.sh --fresh    # use instance/academicai.db instead of the demo
#
# Ctrl-C stops both.
#
# WHY THIS SCRIPT EXISTS
# ----------------------
# Three things have to be right at once, and getting any of them wrong looks
# like "the site is broken":
#
#   1. VITE, NOT A STATIC SERVER. index.html loads /src/main.jsx. A static
#      server (VS Code Live Server, python -m http.server) hands the browser
#      raw JSX with Content-Type: text/jsx, which no browser will execute - so
#      the page renders blank. Vite compiles it to JavaScript on request. Vite
#      also proxies /api to Flask and serves index.html for unknown paths, so
#      deep links and refreshes work.
#
#   2. python -u. With EMAIL_BACKEND=console there is no mail server; the
#      verification code is printed to stdout. Python block-buffers stdout when
#      it is redirected, so without -u the code sits in a buffer and never
#      reaches the log.
#
#   3. A non-default secret key. The app refuses to start in production with
#      the packaged default, and sessions should not silently survive a
#      restart with a shared placeholder.
#
# It is a DEVELOPMENT script. It refuses to run against ACADEMICAI_ENV=production.

set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd)

DB=instance/demo.db
for arg in "$@"; do
  case "$arg" in
    --fresh) DB=instance/academicai.db ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ "${ACADEMICAI_ENV:-development}" = "production" ]; then
  echo "refusing to run: ACADEMICAI_ENV=production. This script is for local development." >&2
  exit 1
fi

[ -x .venv/bin/python ] || { echo "No virtualenv. Run: make install" >&2; exit 1; }
[ -d frontend/node_modules ] || { echo "Frontend deps missing. Run: cd frontend && npm install" >&2; exit 1; }

# .env first, so its values are in the environment BEFORE the defaults below
# are applied. Without this the defaults win and a key pasted into .env is
# silently ignored - the script would keep the console backend even though
# .env asked for a real provider.
#
# Anything already exported in the shell still beats both.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Anything already exported wins, so a one-off override still works.
export ACADEMICAI_DB_PATH="${ACADEMICAI_DB_PATH:-$DB}"
export ACADEMICAI_EMAIL_BACKEND="${ACADEMICAI_EMAIL_BACKEND:-console}"
export ACADEMICAI_RATE_LIMIT="${ACADEMICAI_RATE_LIMIT:-0}"
export ACADEMICAI_WORKER_INTERVAL="${ACADEMICAI_WORKER_INTERVAL:-15}"
export ACADEMICAI_SECRET_KEY="${ACADEMICAI_SECRET_KEY:-$(
  # Per-machine, stable across restarts so sessions survive a reload, and not
  # the packaged default. Derived rather than committed: no key in git.
  printf '%s' "academicai-dev-$(hostname)-$ROOT" | shasum -a 256 | cut -c1-48
)}"

busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
claim() {
  local port=$1 what=$2
  busy "$port" || return 0
  local pids; pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | tr '\n' ' ')
  echo "  port $port is already in use by pid(s) $pids"
  # Only reclaim something that looks like a previous run of this project. A
  # stranger's process on 5000 is not this script's to kill.
  if ps -o command= -p ${pids%% *} 2>/dev/null | grep -qE "wsgi\.py|vite|npm run dev|run_worker\.py"; then
    echo "  looks like a previous $what; stopping it"
    kill $pids 2>/dev/null
    sleep 2
  else
    echo "  NOT stopping it - it does not look like AcademicAI. Free port $port and retry." >&2
    exit 1
  fi
}

echo "AcademicAI · development"
echo "  database   $ACADEMICAI_DB_PATH"
case "$ACADEMICAI_EMAIL_BACKEND" in
  resend)
    if [ -n "${ACADEMICAI_RESEND_API_KEY:-}" ]; then
      echo "  email      resend (REAL email is sent, from $ACADEMICAI_EMAIL_FROM)"
    else
      echo "  email      resend, but ACADEMICAI_RESEND_API_KEY is EMPTY - sends will fail" >&2
    fi ;;
  *)
    echo "  email      $ACADEMICAI_EMAIL_BACKEND (codes are printed, not sent)" ;;
esac
echo "  rate limit ${ACADEMICAI_RATE_LIMIT}"
echo
claim 5000 "API"
claim 5173 "Vite dev server"

mkdir -p instance
API_LOG=instance/api.log
: > "$API_LOG"

# -u so the console email backend's output is not buffered away.
.venv/bin/python -u backend/wsgi.py >>"$API_LOG" 2>&1 &
API_PID=$!

( cd frontend && exec npm run dev ) > instance/vite.log 2>&1 &
VITE_PID=$!

# The background worker. Without it NOTHING scheduled ever happens: reminders
# stay PENDING past their time, queued notification email is never sent, and
# election and removal ballots never close. The API only ever enqueues work -
# it is this loop that performs it, and running the stack without it makes
# every timed feature look broken rather than merely undelivered.
#
# 15s here rather than the 60s production default, so a reminder set for "two
# minutes from now" during development fires while you are still watching.
#
# Run from the PROJECT ROOT, not from backend/. ACADEMICAI_DB_PATH is a
# RELATIVE path, so `cd backend` first makes it resolve to
# backend/instance/demo.db - the worker then creates its own empty database
# and processes nothing, forever, while reporting healthy cycles. PYTHONPATH
# is what lets the entry point import `academicai` without that cd.
WORKER_LOG=instance/worker.log
: > "$WORKER_LOG"
PYTHONPATH="$ROOT/backend" .venv/bin/python -u backend/run_worker.py >>"$WORKER_LOG" 2>&1 &
WORKER_PID=$!

# Kill a process and everything it spawned. `npm run dev` forks node, which
# forks esbuild; killing npm alone can leave those holding port 5173.
kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null
}

CLEANED=0
cleanup() {
  [ "$CLEANED" = 1 ] && return
  CLEANED=1
  echo
  echo "stopping…"
  # Tails first, so they stop echoing while the servers shut down.
  for t in ${TAIL_API:-} ${TAIL_VITE:-} ${TAIL_WORKER:-}; do kill_tree "$t"; done
  kill_tree "$API_PID"
  kill_tree "$VITE_PID"
  [ -n "${WORKER_PID:-}" ] && kill_tree "$WORKER_PID"
  wait "$API_PID" "$VITE_PID" ${WORKER_PID:-} 2>/dev/null
}
# EXIT as well as the signals: the script must not leave servers running no
# matter how it ends. INT is what Ctrl-C sends in a real terminal; note that a
# job launched in the BACKGROUND from a non-interactive shell inherits SIGINT
# as ignored, and an ignored signal cannot be trapped - send TERM to stop one
# of those.
trap cleanup INT TERM
trap cleanup EXIT

wait_for() {
  local url=$1 name=$2 i
  for i in $(seq 1 60); do
    if curl -fsS -m 2 "$url" >/dev/null 2>&1; then return 0; fi
    kill -0 "$API_PID" 2>/dev/null || { echo "API died on startup:" >&2; tail -20 "$API_LOG" >&2; exit 1; }
    sleep 0.5
  done
  echo "$name did not come up in 30s" >&2
  return 1
}

wait_for http://127.0.0.1:5000/api/health "API" || { tail -20 "$API_LOG" >&2; cleanup; }
wait_for http://127.0.0.1:5173/ "Vite" || { tail -20 instance/vite.log >&2; cleanup; }

cat <<BANNER

  ────────────────────────────────────────────────────────────
   Open   http://localhost:5173
  ────────────────────────────────────────────────────────────

   API      http://127.0.0.1:5000/api/health
   Worker   every ${ACADEMICAI_WORKER_INTERVAL}s — reminders, queued email, ballot closing
   Logs     instance/api.log · instance/vite.log · instance/worker.log

   Do NOT use VS Code Live Server for this project: it serves
   raw JSX the browser cannot execute, has no /api proxy and
   no SPA fallback. Use the URL above.

BANNER

if [ "$ACADEMICAI_DB_PATH" = "instance/demo.db" ] && [ -f instance/demo.db ]; then
  cat <<'LOGINS'
   Demo sign-ins (password: Password123)
     ada@student.babcock.edu.ng     elected rep — sees everything
     bola@student.babcock.edu.ng    ordinary student

LOGINS
fi

cat <<'CODES'
   Signing up? There is no mail server, so read the code with:
     ./scripts/dev_code.sh

   A reminder's time arriving sends EMAIL. With the console backend
   that email is printed here as [work] [email] … rather than
   delivered, and the reminder flips to SENT in the UI.

   Ctrl-C stops all three.

CODES

# Stream both logs, labelled, until Ctrl-C.
# Each pipeline runs inside a { } group so $! is the GROUP's pid and both
# tail and sed are its children. Backgrounding the pipeline directly gives the
# pid of the LAST stage (sed); tail is then a sibling, not a child, and
# survived cleanup as an orphan holding the log open.
{ tail -f "$API_LOG" | sed -u 's/^/[api]  /'; } &
TAIL_API=$!
{ tail -f instance/vite.log | sed -u 's/^/[vite] /'; } &
TAIL_VITE=$!
{ tail -f "$WORKER_LOG" | sed -u 's/^/[work] /'; } &
TAIL_WORKER=$!

# Block until a server exits or a signal arrives. If one dies on its own, stop
# the other too rather than leaving half the stack up.
wait -n "$API_PID" "$VITE_PID" "$WORKER_PID" 2>/dev/null \
  || wait "$API_PID" "$VITE_PID" "$WORKER_PID" 2>/dev/null
