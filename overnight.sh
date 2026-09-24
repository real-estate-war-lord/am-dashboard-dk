#!/usr/bin/env bash
# overnight.sh — Macro Dashboard v3.0 UI overhaul as sequential, unattended Claude Code phases.
#
#   ./overnight.sh preflight         # before bed: checks, venv + Playwright, branch v3.0-ui, plan commit, test call
#   ./overnight.sh run [P1 P2 …]     # the night (default P1…P9); AUTO_RELEASE=1 publishes if everything is green
#   ./overnight.sh gate P3           # the self-check (used by the agent and by this wrapper)
#   ./overnight.sh release           # morning: merge v3.0-ui → main, tag v3.0, push (GitHub Pages deploys)
#   ./overnight.sh status            # quick look at the report
#
# macOS-safe: no GNU timeout / grep -P needed. Never pushes except in `release` (or AUTO_RELEASE=1 after an
# all-green night). Logs and the report live in logs/ (git-excluded), so the working tree stays clean.
set -u
REPO="$(cd "$(dirname "$0")" && pwd)"; cd "$REPO" || exit 1
BRANCH="v3.0-ui"
ALL_PHASES=(P1 P2 P3 P4 P5 P6 P7 P8 P9)
PHASE_TIMEOUT="${PHASE_TIMEOUT:-6000}"     # seconds per claude call (100 min)
LIMIT_WAIT="${LIMIT_WAIT:-1200}"           # seconds to sleep when a usage limit is hit
LIMIT_MAX_WAITS="${LIMIT_MAX_WAITS:-15}"   # up to 5 h of waiting in total
PORT="${PORT:-8080}"
MODEL_ARGS=(); [ -n "${MODEL:-}" ] && MODEL_ARGS=(--model "$MODEL")
# Permissions: NO bypass. File edits are auto-accepted inside the repo; shell access is an explicit allow-list.
# In print mode anything not listed is simply denied (no prompt), so the night can never do more than this.
ALLOWED_TOOLS="Read,Edit,Write,Glob,Grep,\
Bash(git status:*),Bash(git diff:*),Bash(git log:*),Bash(git show:*),Bash(git add:*),Bash(git commit:*),Bash(git mv:*),Bash(git rm:*),Bash(git checkout -- :*),Bash(git restore:*),\
Bash(./overnight.sh gate:*),Bash(python3 scripts/build_dashboard.py:*),Bash(.venv-ui/bin/python3 tests/ui_smoke.py:*),Bash(.venv-ui/bin/python3 tests/ui_ac.py:*),Bash(.venv-ui/bin/python3 docs/v3/ui_smoke_v3.py:*),\
Bash(node --test:*),Bash(node --check:*),Bash(ls:*),Bash(wc:*),Bash(grep:*),Bash(head:*),Bash(tail:*),Bash(mkdir:*)"
DENIED_TOOLS="Bash(git push:*),Bash(git reset:*),Bash(git branch:*),Bash(git merge:*),Bash(curl:*),Bash(pip:*),Bash(npm:*),WebFetch,WebSearch"
CLAUDE_PERMS=(--permission-mode acceptEdits --allowedTools "$ALLOWED_TOOLS" --disallowedTools "$DENIED_TOOLS")
PY="$REPO/.venv-ui/bin/python3"; [ -x "$PY" ] || PY=python3
RUN_ID="${RUN_ID:-$(date +%Y%m%d)}"
LOGS="$REPO/logs/overnight-$RUN_ID"; mkdir -p "$LOGS"
REPORT="$LOGS/OVERNIGHT_REPORT.md"
PH_DIR="$REPO/docs/v3/phases"
FORBIDDEN='^(\.github/|data/|config/|dist/public/|scripts/)'
ALLOWED_SCRIPT='^scripts/build_dashboard\.py$'

log()    { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOGS/run.log"; }
report() { printf '%s\n' "$*" >> "$REPORT"; }
with_timeout() { local s="$1"; shift; perl -e 'alarm shift; exec @ARGV or die "exec: $!"' "$s" "$@"; }

exclude_local() {   # keep venv + logs out of git without touching .gitignore
  grep -qxF '.venv-ui/' .git/info/exclude 2>/dev/null || echo '.venv-ui/' >> .git/info/exclude
  grep -qxF 'logs/' .git/info/exclude 2>/dev/null || echo 'logs/' >> .git/info/exclude
}

serve() {
  if ! curl -s -o /dev/null "http://localhost:$PORT/"; then
    (cd dist && nohup python3 -m http.server "$PORT" >"$LOGS/http.log" 2>&1 &)
    sleep 1
  fi
}

phase_le() { # phase_le P3 → prints P1..P3
  local up="$1" p; for p in "${ALL_PHASES[@]}"; do echo "$p"; [ "$p" = "$up" ] && break; done
}

gate() {   # $1 = phase id. Exit 0 = green. Output → logs/<run>/<phase>.gate.log
  local ph="${1:-adhoc}" out="$LOGS/${1:-adhoc}.gate.log"
  local smoke="tests/ui_smoke.py"; [ -f "$smoke" ] || smoke="docs/v3/ui_smoke_v3.py"
  (
    # explicit `|| exit 1` on purpose: `set -e` is ignored when gate is called from an `||` context
    echo "== build";    "$PY" scripts/build_dashboard.py || exit 1
    echo "== js tests"; node --test tests/*.test.js || exit 1
    echo "== py tests (informational)"; "$PY" -m unittest discover -s tests -p 'test_*.py' || echo "(python unit tests failed — informational only)"
    serve
    echo "== smoke 1440/1366/390"
    "$PY" "$smoke" --url "http://localhost:$PORT/" --no-network --phase "$ph" --out "$LOGS/shots" \
         --viewports "1440x900,1366x768,390x844" || exit 1
    if [ -f tests/ui_ac.py ]; then
      echo "== acceptance suite up to $ph"
      "$PY" tests/ui_ac.py --url "http://localhost:$PORT/" --phase-upto "$ph" --out "$LOGS/ac/$ph" || exit 1
    fi
    echo "== budgets"
    sz=$(wc -c < src/app.js | tr -d ' ');   [ "$sz" -le 460800 ] || { echo "app.js $sz B > 450 KB"; exit 1; }
    sz=$(wc -c < src/style.css | tr -d ' '); [ "$sz" -le 143360 ] || { echo "style.css $sz B > 140 KB"; exit 1; }
    echo "GATE GREEN"
  ) >"$out" 2>&1
  local rc=$?
  echo "gate $ph: $([ $rc -eq 0 ] && echo GREEN || echo RED) — log: $out  shots: $LOGS/shots/$ph"
  return $rc
}

check_commit() {   # ≥1 new commit since the tag, clean tree, no forbidden paths
  local ph="$1"
  [ "$(git rev-list --count "v3-$ph-start..HEAD")" -ge 1 ] || { echo "no commit made"; return 1; }
  [ -z "$(git status --porcelain)" ] || { echo "working tree not clean"; git status --porcelain | head; return 1; }
  local bad; bad=$(git diff --name-only "v3-$ph-start..HEAD" | grep -E "$FORBIDDEN" | grep -vE "$ALLOWED_SCRIPT")
  [ -z "$bad" ] || { echo "forbidden paths changed: $bad"; return 1; }
  [ ! -f "$PH_DIR/$ph.FAILED.md" ] || { echo "agent reported failure ($ph.FAILED.md)"; return 1; }
}

hit_limit() { grep -qiE "usage limit|rate.?limit|limit (reached|exceeded)|resets at|overloaded" "$1"; }

run_claude() {   # $1 prompt file, $2 log file
  local waits=0
  while :; do
    with_timeout "$PHASE_TIMEOUT" claude -p "${CLAUDE_PERMS[@]}" --output-format text \
        "${MODEL_ARGS[@]}" < "$1" > "$2" 2>&1
    local rc=$?
    if [ $rc -ne 0 ] && hit_limit "$2" && [ $waits -lt "$LIMIT_MAX_WAITS" ]; then
      waits=$((waits + 1)); log "usage/rate limit — sleeping $LIMIT_WAIT s ($waits/$LIMIT_MAX_WAITS)"
      cp "$2" "$2.limit$waits"; sleep "$LIMIT_WAIT"; continue
    fi
    return $rc
  done
}

run_phase() {   # $1 phase, $2 attempt, $3 optional gate log from the failed attempt
  local ph="$1" att="$2" prev="${3:-}" t0=$SECONDS
  local prompt="$LOGS/$ph.attempt$att.prompt.md"
  {
    cat "$PH_DIR/_COMMON.md"; echo; echo "---"; echo
    echo "# YOUR PHASE: $ph  (replace <PHASE> with $ph everywhere above)"; echo
    cat "$PH_DIR/$ph.md"
    if [ -n "$prev" ] && [ -f "$prev" ]; then
      echo; echo "## RETRY — the previous attempt of this phase was rolled back. Its gate/commit output:"
      echo '```'; tail -n 150 "$prev"; echo '```'
      echo "Start from the clean state, avoid what failed, keep the scope tight."
    fi
  } > "$prompt"
  log "$ph attempt $att: claude running (timeout ${PHASE_TIMEOUT}s)"
  run_claude "$prompt" "$LOGS/$ph.attempt$att.log"
  log "$ph attempt $att: claude exited $? after $(( (SECONDS - t0) / 60 )) min"
  local why; why=$(check_commit "$ph") || { log "$ph: $why"; echo "$why" > "$LOGS/$ph.gate.log"; return 1; }
  gate "$ph" >/dev/null || { log "$ph: gate RED ($LOGS/$ph.gate.log)"; return 1; }
  log "$ph: GREEN at $(git rev-parse --short HEAD)"
}

rollback() {
  local ph="$1"
  [ -f "$PH_DIR/$ph.FAILED.md" ] && cp "$PH_DIR/$ph.FAILED.md" "$LOGS/"
  git reset -q --hard "v3-$ph-start"; git clean -qfd -e logs -e .venv-ui
}

preflight() {
  local bad=0
  exclude_local
  echo "· python: $(python3 --version 2>&1)   node: $(node --version 2>&1)   claude: $(claude --version 2>&1 | head -1)"
  command -v node >/dev/null || { echo "✗ node missing"; bad=1; }
  command -v claude >/dev/null || { echo "✗ claude CLI missing"; bad=1; }
  command -v caffeinate >/dev/null || echo "· caffeinate missing — keep the Mac awake yourself"
  if [ -n "$(git status --porcelain -- . ':!docs/v3' ':!overnight.sh')" ]; then
    echo "✗ uncommitted changes outside docs/v3 + overnight.sh:"; git status --porcelain | head; exit 1
  fi
  if ! git rev-parse --verify -q "$BRANCH" >/dev/null; then
    git checkout -q main && git pull -q --ff-only origin main || { echo "✗ could not update main from GitHub"; exit 1; }
    echo "· main is at $(git log -1 --format='%h %s')"
    git checkout -q -b "$BRANCH" main
  fi
  git checkout -q "$BRANCH" || { echo "✗ cannot switch to $BRANCH"; exit 1; }
  if [ -n "$(git status --porcelain -- docs/v3 overnight.sh)" ]; then
    chmod +x overnight.sh; git add docs/v3 overnight.sh
    git commit -q -m "v3.0 P0: UI spec, engineering brief, phase prompts, overnight runner" && echo "✓ plan committed on $BRANCH"
  fi
  if [ ! -x "$REPO/.venv-ui/bin/python3" ]; then
    echo "· creating .venv-ui with Playwright (one-off, ~150 MB)…"
    python3 -m venv .venv-ui && .venv-ui/bin/pip -q install playwright && .venv-ui/bin/python3 -m playwright install chromium || { echo "✗ Playwright install failed"; bad=1; }
    PY="$REPO/.venv-ui/bin/python3"
  fi
  "$PY" -c "from playwright.sync_api import sync_playwright; print('✓ playwright ok')" || bad=1
  "$PY" scripts/build_dashboard.py >/dev/null && echo "✓ build ok" || { echo "✗ build failed"; bad=1; }
  node --test tests/*.test.js >/dev/null 2>&1 && echo "✓ js tests ok" || { echo "✗ js tests failed"; bad=1; }
  serve
  "$PY" docs/v3/ui_smoke_v3.py --url "http://localhost:$PORT/" --no-network --allow-errors --phase baseline --out "$LOGS/shots" >/dev/null 2>&1 \
     && echo "✓ baseline smoke ran (v2.6 errors are expected and allowed)" || echo "· baseline smoke could not run — see $LOGS"
  echo "· testing an unattended claude call…"
  if with_timeout 180 claude -p "${CLAUDE_PERMS[@]}" "Run the shell command: ls docs/v3 — then reply with exactly: READY" 2>&1 | grep -q READY; then echo "✓ claude -p works unattended with the allow-list"; else echo "✗ claude -p did not answer READY — run 'claude' once interactively to log in"; bad=1; fi
  [ $bad -eq 0 ] && echo "✓ PREFLIGHT OK — start the night with:  ./overnight.sh run" || { echo "✗ PREFLIGHT FAILED"; exit 1; }
}

release() {
  git checkout -q "$BRANCH" || exit 1
  [ -z "$(git status --porcelain)" ] || { echo "✗ tree not clean"; exit 1; }
  gate P9 || { echo "✗ gate not green — not releasing"; exit 1; }
  git fetch -q origin
  git checkout -q main && git merge -q --ff-only origin/main 2>/dev/null
  git merge -q --no-ff "$BRANCH" -m "Release v3.0 — UI overhaul" || { echo "✗ merge conflict — resolve by hand"; git merge --abort; git checkout -q "$BRANCH"; exit 1; }
  git tag -f v3.0 >/dev/null
  git push -q origin main && git push -q -f origin v3.0 && echo "✓ v3.0 pushed — GitHub Pages deploys in a few minutes"
  git checkout -q "$BRANCH"
}

main_run() {
  local phases=("$@"); [ ${#phases[@]} -gt 0 ] || phases=("${ALL_PHASES[@]}")
  exclude_local; git checkout -q "$BRANCH" || { echo "run preflight first"; exit 1; }
  [ -f "$REPORT" ] || { report "# Overnight report — v3.0 UI ($(date '+%F %H:%M'))"; report "";
    report "Branch \`$BRANCH\`. Logs \`$LOGS\`. Review server: http://localhost:$PORT/"; report "";
    report "| Phase | Result | Commit | Min | Notes |"; report "|---|---|---|---|---|"; }
  local fails=0 allgreen=1
  for ph in "${phases[@]}"; do
    local t0=$SECONDS; git tag -f "v3-$ph-start" >/dev/null
    if run_phase "$ph" 1 || { rollback "$ph"; run_phase "$ph" 2 "$LOGS/$ph.gate.log"; }; then
      report "| $ph | ✓ green | $(git rev-parse --short HEAD) | $(( (SECONDS - t0) / 60 )) | shots/$ph |"; fails=0
    else
      rollback "$ph"; allgreen=0; fails=$((fails + 1))
      report "| $ph | ✗ rolled back | – | $(( (SECONDS - t0) / 60 )) | $ph.attempt2.log, $ph.gate.log |"
      [ "$ph" = P1 ] && { report ""; report "**Stopped: P1 (foundation) failed — nothing else can build on it.**"; break; }
      [ $fails -ge 2 ] && { report ""; report "**Stopped: two phases in a row failed.**"; break; }
    fi
  done
  report ""
  if [ $allgreen -eq 1 ] && [ "${AUTO_RELEASE:-0}" = 1 ] && [ ${#phases[@]} -eq ${#ALL_PHASES[@]} ]; then
    log "all phases green — AUTO_RELEASE=1 → releasing"; release >>"$LOGS/release.log" 2>&1 \
      && report "**Released v3.0 to GitHub Pages automatically.**" || report "**Auto-release failed — see release.log; run ./overnight.sh release by hand.**"
  else
    report "Not released. Review, then publish with: \`./overnight.sh release\`"
  fi
  report ""; report "Morning: read docs/v3/RELEASE_NOTES_FI.md and docs/v3/QA.md, open http://localhost:$PORT/ , screenshots in $LOGS/shots/P9/"
  log "done — $REPORT"
}

case "${1:-}" in
  preflight) preflight ;;
  gate)      gate "${2:-adhoc}" ;;
  release)   release ;;
  status)    cat "$REPORT" 2>/dev/null || ls -t logs/ ;;
  run)       shift
             if command -v caffeinate >/dev/null && [ -z "${CAFFEINATED:-}" ]; then
               CAFFEINATED=1 RUN_ID="$RUN_ID" exec caffeinate -dimsu "$0" run "$@"; fi
             main_run "$@" ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
