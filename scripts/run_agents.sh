#!/usr/bin/env bash
# Run the two extraction agents over the batches in batches/.
#
#   bash scripts/run_agents.sh            # all batches
#   bash scripts/run_agents.sh 1 2        # batches 001..002 (pilot)
#
# Output: events/a/batch_NNN.json (prompt extract.md) and
#         events/b/batch_NNN.json (prompt verify.md).
# A batch whose output already exists and is valid JSON is skipped, so the
# script can be re-run after a reboot, a usage cap or a Ctrl-C and it only does
# what is missing. Rate limits / API errors: wait and retry, never give up on
# the batch (it is just left for the next run after MAX_TRIES).
#
# Env knobs: WORKERS (3), MODEL_A (sonnet), MODEL_B (sonnet), MAX_TRIES (6),
#            PUSH_EVERY (10: commit+push events/ every N finished jobs; 0 = off).
set -u
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

WORKERS="${WORKERS:-3}"
MODEL_A="${MODEL_A:-sonnet}"
MODEL_B="${MODEL_B:-sonnet}"
MAX_TRIES="${MAX_TRIES:-6}"
PUSH_EVERY="${PUSH_EVERY:-10}"

FIRST="${1:-1}"
LAST="${2:-$(ls batches/batch_*.txt | wc -l | tr -d ' ')}"

mkdir -p events/a events/b events/raw logs
LOG="logs/agents_$(date +%Y%m%d_%H%M%S).log"
ln -sfn "$(basename "$LOG")" logs/agents_latest.log
log() { printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG"; }

# Validate a JSON file: must parse and contain an "eventos" list.
valid_json() {
  python3 - "$1" <<'EOF'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    sys.exit(0 if isinstance(d.get("eventos"), list) else 1)
except Exception:
    sys.exit(1)
EOF
}

# Pull the JSON object out of a model reply (tolerates ``` fences / prose).
extract_json() {
  python3 - "$1" "$2" <<'EOF'
import json, re, sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
# claude -p --output-format json wraps the reply: take .result if present
try:
    outer = json.loads(raw)
    if isinstance(outer, dict) and "result" in outer:
        raw = outer["result"] if isinstance(outer["result"], str) else json.dumps(outer["result"])
except Exception:
    pass
raw = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw.strip())
i, j = raw.find("{"), raw.rfind("}")
if i < 0 or j < 0:
    sys.exit(1)
d = json.loads(raw[i : j + 1])
if not isinstance(d.get("eventos"), list):
    sys.exit(1)
json.dump(d, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
EOF
}

run_one() {  # run_one <agent a|b> <batch_NNN>
  local agent="$1" b="$2" prompt model out raw tries=0
  if [ "$agent" = a ]; then prompt=prompts/extract.md; model="$MODEL_A"; else prompt=prompts/verify.md; model="$MODEL_B"; fi
  out="events/$agent/$b.json"
  raw="events/raw/${b}_$agent.txt"
  if [ -s "$out" ] && valid_json "$out"; then return 0; fi
  while [ "$tries" -lt "$MAX_TRIES" ]; do
    tries=$((tries + 1))
    log "START $agent $b (try $tries, model $model)"
    cat "$prompt" "batches/$b.txt" \
      | claude -p --model "$model" --output-format json \
                 --tools "" --no-session-persistence --strict-mcp-config \
      > "$raw" 2> "$raw.err"
    local rc=$?
    if [ $rc -eq 0 ] && extract_json "$raw" "$out.tmp"; then
      mv "$out.tmp" "$out"
      log "DONE  $agent $b ($(python3 -c "import json;print(len(json.load(open('$out'))['eventos']))") eventos)"
      return 0
    fi
    local msg
    msg="$(python3 -c "
import json,sys
try:
    d=json.load(open(sys.argv[1])); print(d.get('result') or d.get('error') or '')
except Exception:
    print(open(sys.argv[1],errors='replace').read()[:300])
" "$raw" | tr '\n' ' ' | cut -c1-300) $(tr '\n' ' ' < "$raw.err" | cut -c1-200)"
    log "FAIL  $agent $b rc=$rc: $msg"
    rm -f "$out.tmp"
    # rate limit / usage cap: wait longer
    if printf '%s' "$msg" | grep -qiE 'rate.?limit|overloaded|429|usage limit|quota|capacity|hit your limit|resets'; then
      log "WAIT  10 min (rate limit)"; sleep 600
    else
      sleep $((60 * tries))
    fi
  done
  log "GIVEUP $agent $b after $MAX_TRIES tries"
  return 1
}
export -f run_one log valid_json extract_json
export LOG MODEL_A MODEL_B MAX_TRIES

# Build job list: agent a and b for each batch, interleaved.
jobs_file="$(mktemp)"
for n in $(seq "$FIRST" "$LAST"); do
  b=$(printf 'batch_%03d' "$n")
  [ -f "batches/$b.txt" ] || continue
  echo "a $b" >> "$jobs_file"
  echo "b $b" >> "$jobs_file"
done
total=$(wc -l < "$jobs_file" | tr -d ' ')
log "jobs: $total ($WORKERS workers, models a=$MODEL_A b=$MODEL_B)"

# Periodic commit of finished events so progress is visible / survives reboots.
pusher() {
  local done_prev=0
  while sleep 300; do
    local done_now
    done_now=$(ls events/a/*.json events/b/*.json 2>/dev/null | wc -l | tr -d ' ')
    if [ "$PUSH_EVERY" -gt 0 ] && [ $((done_now - done_prev)) -ge "$PUSH_EVERY" ]; then
      done_prev=$done_now
      git add events/a events/b >/dev/null 2>&1
      git commit -qm "events: $done_now/$total jobs" >/dev/null 2>&1 && git pull -q --rebase && git push -q \
        && log "PUSH  $done_now/$total" || log "PUSH  failed (will retry)"
    fi
  done
}
pusher & pusher_pid=$!
trap 'kill $pusher_pid 2>/dev/null' EXIT

xargs -P "$WORKERS" -L 1 bash -c 'run_one "$0" "$1"' < "$jobs_file"
rm -f "$jobs_file"

done_a=$(ls events/a/*.json 2>/dev/null | wc -l | tr -d ' ')
done_b=$(ls events/b/*.json 2>/dev/null | wc -l | tr -d ' ')
log "finished: events/a $done_a, events/b $done_b of $((total / 2)) batches each"
[ "$done_a" -ge $((total / 2)) ] && [ "$done_b" -ge $((total / 2)) ]
