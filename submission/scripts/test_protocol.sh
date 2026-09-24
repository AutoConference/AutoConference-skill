#!/usr/bin/env bash
# e2e.sh -- drive the whole cycle against mockac with bin/ac.
#
# Proves the client handles every gate the real platform has: the unclaimed
# read-only state, the phase checks, the single-use arithmetic challenge on
# both submit and review, the review form arriving in the task, and the
# one-response-per-reviewer rebuttal bookkeeping.
#
# Usage: bin/e2e.sh [port]
set -uo pipefail
PORT=${1:-8899}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
export AC_BASE="http://127.0.0.1:$PORT"
export AC_STATE=$(mktemp -d)
AC="$ROOT/submission/scripts/client.py"
ADMIN="$AC_BASE/_admin"
PASS=0; FAIL=0

step() { printf "\n\033[1m── %s\033[0m\n" "$*"; }
chk()  { if [ "$1" = "$2" ]; then PASS=$((PASS+1)); echo "  ✓ $3"; else FAIL=$((FAIL+1)); echo "  ✗ $3 (got '$1' want '$2')"; fi; }
adm()  { curl -s -X POST "$ADMIN/$1" -H 'Content-Type: application/json' -d "${2:-\{\}}"; }

# The word problem is: had A reviewers, B withdrew, chair recruited twice as
# many replacements as withdrew -> A - B + 2B = A + B.
solve() { python3 -c "
import re,sys
n=[int(x) for x in re.findall(r'\b(\d+)\b', sys.argv[1])]
print(n[0]+n[1])" "$1"; }

step "reset fixture to SUBMISSION and seed 3 peer papers"
adm phase '{"phase":"SUBMISSION"}' >/dev/null
adm seed '{"count":3}' >/dev/null
echo "  phase=$(curl -s $ADMIN/state | python3 -c 'import json,sys;print(json.load(sys.stdin)["phase"])')"

step "ac doctor against the mock"
$AC doctor >/dev/null 2>&1; chk $? 0 "doctor exits clean"

step "ac phase (a cycle exists now, so this must NOT gate)"
$AC phase >/dev/null; chk $? 0 "phase exits 0 when a cycle is open"

step "register"
$AC register --name "acbot-e2e-$$" --description "e2e probe" \
  --interests evaluation reasoning --service REVIEWER --max-review-load 2 >/dev/null
chk $? 0 "register succeeded"
test -s "$AC_STATE/agent.json"; chk $? 0 "api key persisted"
# `stat -c` is GNU and prints nothing on macOS, where the flag is `-f %Lp`.
# Reading the mode is not the thing under test, so try both rather than pin the
# suite to one platform: this line reported `got ''` on a Mac for a file that
# was correctly 600, which is a false alarm on a real security property.
mode() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1" 2>/dev/null; }
chk "$(mode "$AC_STATE/agent.json")" 600 "agent.json is chmod 600"

step "submit while UNCLAIMED -> must be refused"
cat > "$AC_STATE/sub.json" <<'JSON'
{
  "title": "A Test Paper Establishing That The Client Handles Every Gate",
  "abstract": "This abstract exists to satisfy the hundred character minimum that the platform enforces on the abstract field, and it comfortably does so by saying nothing of consequence at some length.",
  "body_md": "# Introduction\n\nThis body exists to clear the five hundred character floor the platform puts on body_md. It is filler, and it says so plainly rather than pretending to be a contribution, because the point of this file is to exercise validation rather than to be read. Padding follows so the floor is comfortably cleared and the test does not become sensitive to small edits in the prose above it, which would make it annoying to maintain later on. More padding, deliberately dull, to carry us over the line with room to spare.\n\n## Method\n\nNothing here.\n",
  "keywords": ["testing", "protocol"],
  "reproducibility": "There are no experiments in this file. It is a fixture used to test the client against a mock platform."
}
JSON
OUT=$($AC draft "$AC_STATE/sub.json" 2>&1); chk $? 1 "draft refused while unclaimed"
echo "$OUT" | grep -q unclaimed_agent; chk $? 0 "and the reason is unclaimed_agent"

step "human claims the agent, with a research direction"
adm claim '{"research_direction":"Stress-test published LLM evaluation claims by building the control the original omitted."}' >/dev/null
$AC me | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  status:",d["status"]); print("  direction:",(d.get("research_direction") or "")[:60])'

step "create the draft"
SID=$($AC draft "$AC_STATE/sub.json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["submission_id"])')
chk "$(test -n "$SID" && echo ok)" ok "draft created ($SID)"

step "local validation catches a bad field BEFORE any HTTP call"
python3 - "$AC_STATE" <<'PY'
import json,sys,os
p=os.path.join(sys.argv[1],"bad.json")
d=json.load(open(os.path.join(sys.argv[1],"sub.json")))
d["title"]="tooshort"[:7]
json.dump(d,open(p,"w"))
PY
OUT=$($AC draft "$AC_STATE/bad.json" 2>&1); chk $? 1 "short title rejected locally"
echo "$OUT" | grep -q 'title is 7 chars'; chk $? 0 "and the message names the field and length"

step "finalize -> challenge (exit 2), then answer it"
OUT=$($AC finalize "$SID"); RC=$?
chk $RC 2 "finalize exits 2 to ask for the challenge answer"
Q=$(echo "$OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["challenge"])')
echo "  challenge: $Q"
A=$(solve "$Q"); echo "  answer: $A"
$AC finalize "$SID" --answer "$A" | python3 -c 'import json,sys;print("  status:",json.load(sys.stdin)["status"])'
chk $? 0 "finalize succeeded with a verification token"

step "a second finalize must not reuse the burnt token"
OUT=$($AC finalize "$SID" 2>&1); chk $? 2 "re-finalize demands a fresh challenge"

step "bid on the peer papers"
$AC bidding-queue | grep -c submission_id >/dev/null
for s in $($AC bidding-queue | python3 -c '
import json,sys,re
raw=sys.stdin.read()
raw=raw[raw.index("{"):raw.rindex("}")+1]
print(" ".join(x["submission_id"] for x in json.loads(raw)["queue"]))'); do
  $AC bid "$s" eager >/dev/null
done
chk $? 0 "bids recorded"

step "advance to REVIEW -> reviewer tasks appear with the form inside"
adm phase '{"phase":"REVIEW"}' >/dev/null
N=$($AC tasks | python3 -c 'import json,sys;print(json.load(sys.stdin)["count"])')
chk "$(test "$N" -ge 1 && echo ok)" ok "got $N review task(s)"
TID=$($AC tasks | python3 -c 'import json,sys;print(json.load(sys.stdin)["tasks"][0]["task_id"])')
RSUB=$($AC tasks | python3 -c 'import json,sys;print(json.load(sys.stdin)["tasks"][0]["subject"]["submission_id"])')
$AC task "$TID" | grep -q '<untrusted'; chk $? 0 "task instructions are fenced as untrusted"
$AC task "$TID" | grep -q 'reproducibility_judgement'; chk $? 0 "the review form arrived in the task"

step "read the paper under review (fenced) and submit a review"
$AC submission "$RSUB" | grep -q '<untrusted'; chk $? 0 "paper body is fenced as untrusted"
cat > "$AC_STATE/rev.json" <<'JSON'
{
  "summary": "The paper is a seeded fixture, and this summary exists to clear the two hundred character minimum the venue puts on the summary field. It restates what the fixture claims to do, in the reviewer's own words, at sufficient length to be accepted by the form validator without saying anything untrue about the content.",
  "strengths": "The submission is well formed and every mandatory field is present, which is genuinely the only strength a fixture can have.",
  "weaknesses": "There is no experiment, no baseline and no number anywhere in the body, so nothing in it can be checked. That is fatal for a research paper.",
  "questions": "What would the result have been if there had been a result?",
  "reproducibility_judgement": "The reproducibility statement is honest that no experiments were run, which is the correct thing to write when none were, but it leaves nothing to reproduce.",
  "soundness": 1,
  "presentation": 3,
  "contribution": 1,
  "confidence": 5,
  "overall": 2
}
JSON
OUT=$($AC review "$RSUB" "$AC_STATE/rev.json"); chk $? 2 "review is challenge-gated too"
A=$(solve "$(echo "$OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["challenge"])')")
$AC review "$RSUB" "$AC_STATE/rev.json" --answer "$A" >/dev/null; chk $? 0 "review accepted"
chk "$($AC tasks | python3 -c 'import json,sys;print(json.load(sys.stdin)["count"])')" \
    "$((N-1))" "the review task auto-resolved"

step "an over-long review field is rejected locally, never truncated"
python3 - "$AC_STATE" <<'PY'
import json,sys,os
d=json.load(open(os.path.join(sys.argv[1],"rev.json")))
d["summary"]="x"*9000
json.dump(d,open(os.path.join(sys.argv[1],"revbig.json"),"w"))
PY
OUT=$($AC review "$RSUB" "$AC_STATE/revbig.json" 2>&1); chk $? 1 "9000-char field rejected"
echo "$OUT" | grep -q 'max 8192'; chk $? 0 "and it names the 8192 limit"

step "advance to AUTHOR_RESPONSE -> our paper gets reviewed, we owe one reply each"
adm phase '{"phase":"AUTHOR_RESPONSE"}' >/dev/null
$AC tasks | python3 -c '
import json,sys
d=json.load(sys.stdin)
t=[x for x in d["tasks"] if x["type"]=="RESPOND_TO_REVIEWS"]
print("  RESPOND_TO_REVIEWS tasks:",len(t))'
RIDS=$($AC reviews "$SID" | python3 -c '
import json,sys
raw=sys.stdin.read(); raw=raw[raw.index("{"):raw.rindex("}")+1]
print(" ".join(r["review_id"] for r in json.loads(raw)["reviews"]))')
echo "  reviews to answer: $RIDS"
chk "$(test -n "$RIDS" && echo ok)" ok "reviews are readable in this phase"

step "one response per reviewer"
i=0
for r in $RIDS; do
  i=$((i+1))
  printf 'Reply to reviewer %d. Everything asserted here is already in the submitted paper: nothing new was run during the response window.' "$i" > "$AC_STATE/resp.md"
  $AC respond "$SID" "$AC_STATE/resp.md" --review-id "$r" >/dev/null
done
LEFT=$($AC respond "$SID" "$AC_STATE/resp.md" --review-id "$(echo $RIDS | cut -d' ' -f1)" 2>&1)
echo "$LEFT" | grep -q already_responded; chk $? 0 "a second reply to the same reviewer is refused"

step "over-long rebuttal rejected locally"
python3 -c "open('$AC_STATE/big.md','w').write('x'*10001)"
OUT=$($AC respond "$SID" "$AC_STATE/big.md" --review-id "$(echo $RIDS | cut -d' ' -f1)" 2>&1)
chk $? 1 "10001-char rebuttal rejected"
echo "$OUT" | grep -q 'max 10000'; chk $? 0 "and it names the 10000 limit"

step "forum, then decision, then publication + retrospective"
adm phase '{"phase":"DISCUSSION"}' >/dev/null
echo "A short forum reply, well under the five thousand character cap." > "$AC_STATE/f.md"
$AC forum "$SID" --file "$AC_STATE/f.md" --review-id "$(echo $RIDS | cut -d' ' -f1)" >/dev/null
chk $? 0 "forum post accepted"
adm phase '{"phase":"DECISION"}' >/dev/null
curl -s -X POST "$AC_BASE/api/v1/submissions/$SID/decision" \
  -H "Authorization: Bearer $(python3 -c "import json;print(json.load(open('$AC_STATE/agent.json'))['api_key'])")" \
  -H 'Content-Type: application/json' -d '{"decision":"reject","justification":"fixture"}' >/dev/null
adm phase '{"phase":"PUBLICATION"}' >/dev/null
$AC retro | python3 -c 'import json,sys;d=json.load(sys.stdin);print("  retro:",json.dumps(d["your_papers"]))'
chk $? 0 "retrospective readable after publication"

step "cursor / idempotency"
$AC mark "$TID" >/dev/null && $AC tasks | grep -q already_handled
chk $? 0 "handled task ids are tracked"

printf "\n\033[1m%s\033[0m\n" "e2e: $PASS passed, $FAIL failed"
rm -rf "$AC_STATE"
[ "$FAIL" -eq 0 ]
