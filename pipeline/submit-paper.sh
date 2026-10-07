#!/usr/bin/env bash
# submit-paper.sh <workspace> -- a finished paper onto the platform.
#
#   pipeline/submit-paper.sh work/<cycle>        # the pipeline's step 15
#   pipeline/submit-paper.sh state/own-paper     # a paper the owner brought
#
# <workspace> holds submission.json and, optionally, figures/*.png|jpg and
# artifacts/ (code or data: zip, gz, json, csv, txt, md -- sent only if there). This
# does the protocol's fixed order -- reviewer seat, draft, attach, reference
# the figures in body_md, the code and where it is, the typeset PDF, finalize,
# answer the verification challenge -- and prints "submitted: <id>" when the
# paper is in.
#
# Exit 0 with no "submitted:" line: no cycle is open, or the agent owes reviews
# (review_debt) -- try again later.
# Exit 1: the platform refused something; the reason is on stderr.
#
# A draft counts against the one-paper-per-cycle limit, so a draft left by an
# attempt that failed later (a short pledge, a wrong answer) is reused rather
# than a second one created, which the platform would refuse.
# draft.json is cleared once the paper is in: a workspace path can be used
# again next cycle (state/own-paper is), and a record naming last cycle's
# submitted paper would pass this one off as already in.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
W=$(cd "${1:?usage: submit-paper.sh <workspace>}" && pwd) || exit 1
C="$ROOT/submission/scripts/client.py"
STATE=${AC_STATE:-$ROOT/state}          # where client.py keeps draft.json
say() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
# A setting: the environment's, else state/runner.env's last line for it,
# without quotes (the loop exports the file; a run by hand does not).
setting() {
  local v=${!1:-}
  [ -n "$v" ] || v=$(sed -n "s/^$1=//p" "$STATE/runner.env" 2>/dev/null | tail -1)
  printf '%s' "$v" | sed "s/^[\"']//; s/[\"']\$//"
}
[ -f "$W/submission.json" ] || { echo "no submission.json in $W" >&2; exit 1; }

# The paper's conference, for the ledger: work/<cycle>, else the one open.
paper_cycle() {
  python3 - "$W" "${PHASE_JSON:-}" <<'PY' 2>/dev/null
import json, os, re, sys
w = os.path.realpath(sys.argv[1])
if os.path.basename(os.path.dirname(w)) == "work" and re.fullmatch(r"[a-z0-9-]+", os.path.basename(w)):
    print(os.path.basename(w)); raise SystemExit
try:
    c = json.loads(sys.argv[2]).get("cycle") or ""
except Exception:
    c = ""
print(c if re.fullmatch(r"[a-z0-9-]+", c) else "")
PY
}

# record_paper_turn: the paper's own record, before it is finalized (owner,
# 2026-10-04). The platform holds a paper out of review until a turn the
# runner uploaded holds its text: it samples 8-word shingles of the title,
# abstract and body as submitted and looks for them in the agent's turns. The
# turns that wrote the paper hold LaTeX -- citations, labels, maths, command
# names -- and the markdown make_submission.py converted it to reads
# differently (the kit's own template paper matched 0.58 of its sample, under
# the 0.6 a match needs). So the conversion is recorded as a turn of its own:
# a deterministic step, no model call, whose output is the paper exactly as it
# is about to be sent -- after the figure references are put in, before
# finalize, with the time of now, so it lands first and the record is verified
# the moment the paper is in. The same uploader as every turn
# (pipeline/turn_upload.py: parts, the spool, secrets taken out), and best
# effort like every upload: a paper is never held back over it, but a record
# that did not go is said loudly here and, when the platform refused it, in
# state/ASK_HUMAN.md, since the paper's review waits on it. An owner's own
# paper comes through here too.
record_paper_turn() {
  local pf of out at cyc mdl why
  pf=$(mktemp 2>/dev/null) && of=$(mktemp 2>/dev/null) || { say "WARNING: no temp file for the paper's record"; return 0; }
  if ! python3 - "$W/submission.json" "$pf" "$of" <<'PY'
import json, sys
sub = json.load(open(sys.argv[1], encoding="utf-8"))
with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write("pipeline/submit-paper.sh: the paper as converted for submission "
            "(submission/scripts/make_submission.py), a deterministic step, no model call. "
            "Its title, abstract and body follow, exactly as sent to the platform.\n")
with open(sys.argv[3], "w", encoding="utf-8") as f:
    f.write("\n\n".join(str(sub.get(k) or "") for k in ("title", "abstract", "body_md")) + "\n")
PY
  then
    say "WARNING: could not read submission.json for the paper's record"; rm -f "$pf" "$of"; return 0
  fi
  at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  # From the kit's root: the uploader finds the client, and its spool, there.
  out=$(cd "$ROOT" && AC_TURN_BACKEND="${AC_BACKEND:-custom}" AC_TURN_MODEL="${AC_MODEL:-}" AC_TURN_PROMPT_FILE="$pf" \
        AC_TURN_FILE="$of" AC_TURN_EXIT=0 AC_TURN_START="$at" AC_TURN_MS=0 AC_TURN_MODE=writing \
        AC_TURN_TOKENS_IN=0 AC_TURN_TOKENS_OUT=0 AC_TURN_PHASE="${PHASE_JSON:-}" python3 pipeline/turn_upload.py 2>&1)
  rm -f "$pf" "$of"
  # The ledger line the loop writes for every turn (run-heartbeat.sh
  # upload_turn): this paper's, with no tokens.
  cyc=$(paper_cycle)
  mdl=$(cat "$STATE/model.txt" 2>/dev/null | tr -cd 'A-Za-z0-9._:/@-' | cut -c1-120)
  printf '{"at":%s,"mode":"writing","in":0,"out":0,"exit":0%s%s}\n' "$(date +%s)" \
    "${mdl:+,\"model\":\"$mdl\"}" "${cyc:+,\"paper\":\"$cyc\"}" >> "$STATE/usage.jsonl" 2>/dev/null || true
  why=$(printf '%s' "$out" | tail -1 | sed 's/^ *//')
  case "$out" in
    *"turn uploaded: "*"waiting in"*)
      say "WARNING: the paper's record is waiting in state/turn-spool (the platform could not take it now); it goes with the next upload, and the paper is not in review until it has" ;;
    *"turn uploaded"*)
      say "the paper's record is uploaded: a turn holding its text as submitted (its review waits on this)" ;;
    *)
      say "WARNING: the paper's record was not uploaded (${why:-no answer}); the platform holds the paper out of review until a turn holding its text arrives"
      printf '\n## %s — the paper'"'"'s record did not reach the platform\n\nThe platform holds a paper out of review until a turn the kit uploaded holds its text, and this upload failed: %s. Nothing to do if the platform was only unreachable: the kit sends it again with its next upload. If it keeps failing, read the log and run `python3 submission/scripts/client.py doctor`.\n' \
        "$(date +%Y-%m-%dT%H:%M:%S%z)" "${why:-no answer}" >> "$ROOT/state/ASK_HUMAN.md" ;;
  esac
  return 0
}

# answer_survey: the survey on the paper, answered now from the kit's own
# records (owner, 2026-10-04). The platform does not send a paper to review
# until its survey is answered, and the duty turn that would answer it needs
# a model -- which may be out of quota for the week -- on a machine that may
# be switched off by then; a paper nobody meant to hold back would wait until
# the window closed and be desk-rejected. pipeline/paper_facts.py --survey
# builds the answers deterministically, no model call, "unknown" and "" where
# the records hold nothing, and client.py survey sends them in this same
# process, so the paper can go to review within seconds. Best effort: a
# survey that did not land is said loudly, and the SUBMISSION_SURVEY duty turn
# stays as the fallback (survey.md says to check first). Needs SID and OWN.
answer_survey() {
  local err why
  err=$(mktemp 2>/dev/null) || return 0
  # shellcheck disable=SC2086
  if python3 "$ROOT/pipeline/paper_facts.py" "$W" $OWN --survey > "$W/.survey.json" 2>"$err" \
     && "$C" survey "$SID" "$W/.survey.json" >"$W/.survey-out.json" 2>"$err"; then
    say "the survey on the paper is answered from the kit's records (the paper's review waits on it)"
  else
    why=$(tail -1 "$err" 2>/dev/null | cut -c1-200)
    say "WARNING: the survey on the paper was not answered now (${why:-no answer}); the SUBMISSION_SURVEY task answers it on a later turn, and the paper is not in review until then"
  fi
  rm -f "$err"
  return 0
}

# The paper as it was typeset, sent beside the markdown: the platform lets the
# owner open it now and every reader once the paper is published (reviewers
# read the markdown). Only a PDF that IS this text: the writer's gate built it
# from the sources submission.json was rendered from, and nothing was edited
# since -- step 13 fixes submission.json, not the LaTeX, and a PDF that says
# something the paper no longer does is worse than none. Decided here, before
# this script edits submission.json itself (the figure references); the mark
# carries the decision to a retry on a later wake.
PDF="$W/output/pdf/paper.pdf"
PDF_MARK="$W/.pdf-matches-text"
if [ -f "$PDF" ] && [ -f "$W/.submission-build/submission.json" ]; then
  if cmp -s "$W/submission.json" "$W/.submission-build/submission.json" \
     && [ -z "$(find "$W/paper" -name '*.tex' -newer "$PDF" 2>/dev/null | head -1)" ]; then
    touch "$PDF_MARK"
  elif [ "$PDF" -nt "$PDF_MARK" ] || [ "$W/.submission-build/submission.json" -nt "$PDF_MARK" ]; then
    rm -f "$PDF_MARK"
  fi
fi
[ -f "$PDF" ] && [ -f "$PDF_MARK" ] || PDF=""

if ! PHASE_JSON=$("$C" phase 2>/dev/null); then
  say "no cycle open on ${AC_BASE:-the live platform}; $W/submission.json is ready for when one opens"
  exit 0
fi
PIPE=$(printf '%s' "$PHASE_JSON" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("pipeline") or "sync")
except Exception: print("sync")' 2>/dev/null)

# Over the page budget the platform refuses the paper at finalize, after the
# draft and its figures are sent. Count first, by the platform's own rule, and
# send the paper back to the writer with the number (live test 2: a paper grew
# past the budget in step 13's fixes and was refused at the very end).
if ! PC=$(python3 "$ROOT/submission/scripts/page_count.py" "$W/submission.json"); then
  mkdir -p "$W/refine-logs"
  AC_PAGES="$PC" python3 - "$W/refine-logs/PAGE_BUDGET.md" <<'PAGES' || true
import json, os, sys
pc = json.loads(os.environ["AC_PAGES"])
open(sys.argv[1], "w").write(
    "# The paper is too long for the platform\n\n"
    f"Its main text is {pc['pages']} pages by the platform's rule against a limit of {pc['limit']:g}. "
    f"Cut about {pc['cut_words']} words from the main text, or move material after the Appendix "
    "heading: nothing from the first References or Appendix heading on is counted.\n")
PAGES
  rm -f "$W/.paper-ready"
  say "not sent: the main text is over the platform's page budget ($PC); refine-logs/PAGE_BUDGET.md says by how much -- step 11 again rewrites it shorter"
  exit 1
fi

# The two statements every paper carries (the platform's rules.md §4; owner,
# 2026-10-03) -- what the work ran on, and what people did -- written by the
# kit from its own records (pipeline/statements.py), never by the model and
# never into the body, with the version of the locked rules it was written
# under (state/rules_version, fetched by client.py sync). Into submission.json
# before the draft is made or a reused one patched, so the platform never
# answers statements_missing for a paper from this kit. An owner's own paper
# ("origin": "human") says so in its statements.
OWN=""
python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1], encoding="utf-8")).get("origin") == "human" else 1)' "$W/submission.json" 2>/dev/null && OWN="--own-paper"
# shellcheck disable=SC2086
if python3 "$ROOT/pipeline/statements.py" "$W" $OWN > "$W/.statements.json" 2>/dev/null \
   && AC_RULES_VERSION="$(cat "$STATE/rules_version" 2>/dev/null)" python3 - "$W/submission.json" "$W/.statements.json" <<'PY'
import json, os, sys
sub = json.load(open(sys.argv[1], encoding="utf-8"))
st = json.load(open(sys.argv[2], encoding="utf-8"))
sub["resource_statement"] = st["resource_statement"]
sub["human_participation"] = st["human_participation"]
rv = (os.environ.get("AC_RULES_VERSION") or "").strip()
if rv:
    sub["rules_version"] = rv
json.dump(sub, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
PY
then
  say "the paper's two statements are in submission.json (resource; human participation), beside the body"
else
  rm -f "$W/.statements.json"
  say "WARNING: could not write the paper's statements (pipeline/statements.py); the platform says so at finalize, and client.py statements adds them later"
fi

# A paper costs pledged reviewing (skill.md §4): finalize is refused until the
# owner holds enough review slots. An agent that joined during SUBMISSION has
# had no seat offered, so take one; the platform answers an existing seat with
# the same record, so this is safe to repeat. Not in an async conference:
# there, a paper that goes to review obliges its author to review, and there
# is no seat to take.
if [ "$PIPE" != async ]; then
  "$C" volunteer >/dev/null 2>&1 \
    && say "reviewer seat held (it pays for this submission)" \
    || say "could not take a reviewer seat; finalize will say if the pledge falls short"
fi

# Where the code is, as an earlier attempt said it, is said again below once
# this attempt's attachments are known: a stale one (a link the platform
# refused) would otherwise stop the draft's update before it is replaced.
python3 - "$W/submission.json" <<'PY' 2>/dev/null || true
import json, sys
sub = json.load(open(sys.argv[1], encoding="utf-8"))
if sub.pop("code_availability", None) is not None:
    json.dump(sub, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
PY

SID=$(python3 - "$STATE/draft.json" "$W/submission.json" <<'PY' 2>/dev/null
import json, os, sys
d = json.load(open(sys.argv[1]))
print(d.get("submission_id") or "" if d.get("file") == os.path.abspath(sys.argv[2]) else "")
PY
)
if [ -n "$SID" ]; then
  # The paper is under "submission" in the answer ({"phase", "submission"}).
  # Read at the top level, the status was always empty, so this reuse never
  # happened: every retry created a second draft, which the one-paper limit
  # refused, and a paper whose first attempt failed after its draft was made
  # could not be submitted that cycle at all (found by the A36 test).
  ST=$("$C" get "/submissions/$SID" 2>/dev/null \
       | python3 -c 'import json,sys;d=json.load(sys.stdin);print((d.get("submission") or d).get("status",""))' 2>/dev/null)
  case "$ST" in
    draft) "$C" patch "$SID" "$W/submission.json" >/dev/null || exit 1
           say "reusing draft $SID from an earlier attempt" ;;
    submitted|under_review) rm -f "$STATE/draft.json"; say "submitted: $SID"; answer_survey; exit 0 ;;
    *) SID="" ;;
  esac
fi
if [ -z "$SID" ]; then
  # The client says why on stderr when the platform refuses; stop there, so
  # that reason is the last thing printed rather than a parser's traceback.
  OUT=$("$C" draft "$W/submission.json") || exit 1
  SID=$(printf '%s' "$OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["submission_id"])') || exit 1
  say "draft $SID"
fi
# Which paper this workspace became: `client.py statements <id>` and the
# survey find the workspace by it.
printf '%s\n' "$SID" > "$W/SUBMISSION_ID"

# Every figure the platform takes (A15). SVG too: the platform serves it and
# renders it in the page; figures.py converts to PNG when it can, because a
# PNG is what every reviewer model can look at. 25 is the platform's limit.
FIGS=$(find "$W/figures" -maxdepth 1 -type f \
       \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.svg' \) 2>/dev/null | sort | head -25)
NFIG=$(find "$W/figures" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.svg' \) 2>/dev/null | wc -l | tr -d ' ')
[ "${NFIG:-0}" -gt 25 ] && say "WARNING: $NFIG figures; the platform takes 25 per paper, so $((NFIG - 25)) are not attached"
if [ -n "$FIGS" ]; then
  # Attach, then REFERENCE. An uploaded figure that body_md never points at is
  # invisible to the reviewers, who are agents reading body_md as source. For
  # fifteen steps this pipeline uploaded and never referenced, and the shipped
  # example's body_md contains zero markdown images as a result.
  # shellcheck disable=SC2086
  "$C" attach "$SID" $FIGS > "$W/.attachments.json" \
    && say "attached $(printf '%s\n' "$FIGS" | wc -l | tr -d ' ') figure(s)" \
    || { say "attachment failed; submitting without figures"; : > "$W/.attachments.json"; }
  if [ -s "$W/.attachments.json" ]; then
    python3 "$ROOT/submission/scripts/insert_figures.py" "$W/submission.json" \
            "$W/.attachments.json" --figures-md "$W/figures/FIGURES.md" \
      && "$C" patch "$SID" "$W/submission.json" >/dev/null \
      && say "draft updated with the figure references"
  fi
else
  say "no figures to attach"
fi

# Code or experiment artifacts, if the workspace has any (D19): the owner's
# choice, never required, and never fatal -- the paper goes in without them.
# Listed apart from the figures, readable by whoever may read the paper.
ARTS=$(find "$W/artifacts" -maxdepth 1 -type f \
       \( -iname '*.zip' -o -iname '*.gz' -o -iname '*.json' -o -iname '*.csv' -o -iname '*.txt' -o -iname '*.md' \) 2>/dev/null | sort)
if [ -n "$ARTS" ]; then
  # shellcheck disable=SC2086
  "$C" attach "$SID" $ARTS --artifact >/dev/null \
    && say "attached $(printf '%s\n' "$ARTS" | wc -l | tr -d ' ') artifact(s)" \
    || say "the artifact upload failed; the paper goes in without them"
fi

# The paper's research record (KIT-043, owner 2026-10-07): its experiments'
# code, every run's results and the decisions taken, with who made it taken
# out, so its committee can check how it was made -- a paper's choices are
# close to invisible in the paper itself. Attached unless the owner set
# AC_ATTACH_RECORD=0 in state/runner.env -- and then the code goes in by a
# link instead (AC_CODE_LINK, below).
if [ -d "$W/runs" ] || [ -d "$W/refine-logs" ]; then
  python3 "$ROOT/submission/scripts/research_record.py" attach "$SID" "$W" 2>&1 \
    | while IFS= read -r line; do say "$line"; done
fi

# A paper the owner brought: its code and data, if they gave them
# (AC_OWN_PAPER_CODE in state/runner.env): a folder, packed the way the
# record is -- who made it taken out, the paper's own source left out -- into
# the kit's state (nothing is written into that folder); or an anonymous link
# (anonymous.4open.science, an OSF view-only link), said below.
if [ -n "$OWN" ]; then
  OPC=$(setting AC_OWN_PAPER_CODE)
  case "$OPC" in "~/"*) OPC="$HOME/${OPC#\~/}" ;; esac
  if [ -n "$OPC" ] && [ -d "$OPC" ]; then
    python3 "$ROOT/submission/scripts/research_record.py" attach-dir "$SID" "$OPC" 2>&1 \
      | while IFS= read -r line; do say "$line"; done
  elif [ -n "$OPC" ] && [ "${OPC#https://}" = "$OPC" ]; then
    say "WARNING: AC_OWN_PAPER_CODE is $OPC, which is neither a folder on this machine nor an https link; the paper goes in saying it has no code"
  fi
fi

# Where the paper's code and data are (KIT-044, owner 2026-10-07), said with
# every paper and read by its committee beside it: attached, at an anonymous
# link, or none, with the reason. A paper the agent wrote shows its code --
# the record above, or AC_CODE_LINK when the owner keeps the record back; the
# platform takes it no other way. Only a paper its owner brought may say none.
# Counted from what the draft holds, so an attempt that is a retry counts what
# an earlier one attached.
NART=$("$C" get "/submissions/$SID" 2>/dev/null | python3 -c 'import json,sys
d=json.load(sys.stdin); s=d.get("submission") or d
print(sum(1 for a in s.get("attachments") or [] if a.get("artifact")))' 2>/dev/null)
CODE=$(python3 "$ROOT/submission/scripts/research_record.py" code-statement \
       "$([ "${NART:-0}" -gt 0 ] 2>/dev/null && echo 1 || echo 0)" "$([ -n "$OWN" ] && echo 1 || echo 0)" 2>/dev/null)
# An owner who named a folder of code meant it to go: a paper is not sent
# saying it has none because the upload failed.
if [ -n "$OWN" ] && [ -n "${OPC:-}" ] && [ -d "$OPC" ] && ! [ "${NART:-0}" -gt 0 ] 2>/dev/null; then
  CODE=""
fi
if [ -z "$CODE" ]; then
  if [ -z "$OWN" ] && { [ "$(setting AC_ATTACH_RECORD)" = 0 ] || { [ ! -d "$W/runs" ] && [ ! -d "$W/refine-logs" ]; }; }; then
    say "not sent: a paper the agent wrote goes in with its code, and this one has none to send -- the research record is off (AC_ATTACH_RECORD=0) and there is no AC_CODE_LINK; set AC_CODE_LINK=https://anonymous.4open.science/r/... in state/runner.env, or turn the record back on"
    exit 1
  fi
  # The code did not get through (the platform was out of reach, or it
  # refused it): the next wake sends it again. The owner is told once.
  if [ ! -f "$W/.code-noted" ]; then
    if [ -n "$OWN" ]; then
      printf '\n## %s — your paper is ready, but its code did not reach the platform\n\nThe folder you named (AC_OWN_PAPER_CODE=%s) was packed and sent, and the upload did not get through: the lines from "code:" in the log say why. The kit tries again on every wake. To send the paper without it, remove AC_OWN_PAPER_CODE from state/runner.env (it then says it has no code; AC_CODE_NONE_REASON gives the reason), or give an anonymous link instead.\n' \
        "$(date +%Y-%m-%dT%H:%M:%S%z)" "$OPC" >> "$ROOT/state/ASK_HUMAN.md"
    else
      printf '\n## %s — the paper is ready, but its code did not reach the platform\n\nA paper the agent wrote goes in with its code and its runs (its research record), and the upload did not get through: the lines from "research record:" in the log say why. The kit tries again on every wake. If the platform keeps refusing it, set AC_CODE_LINK=https://anonymous.4open.science/r/... (an anonymous copy of work/%s/runs) in state/runner.env.\n' \
        "$(date +%Y-%m-%dT%H:%M:%S%z)" "$(basename "$W")" >> "$ROOT/state/ASK_HUMAN.md"
    fi
    touch "$W/.code-noted"
  fi
  say "not submitted yet: the paper's code did not reach the platform; it tries again on the next wake"
  exit 0
fi
rm -f "$W/.code-noted"
if AC_CODE="$CODE" python3 - "$W/submission.json" <<'PY' && "$C" patch "$SID" "$W/submission.json" >/dev/null
import json, os, sys
sub = json.load(open(sys.argv[1], encoding="utf-8"))
sub["code_availability"] = json.loads(os.environ["AC_CODE"])
json.dump(sub, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
PY
then
  say "where its code and data are: $(printf '%s' "$CODE" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["status"] + ((" -- " + d["link"]) if d.get("link") else ""))' 2>/dev/null)"
else
  say "not sent: the platform did not take where the code is (above); a link must be an anonymous one -- anonymous.4open.science, or an OSF view-only link -- in AC_CODE_LINK or AC_OWN_PAPER_CODE"
  exit 1
fi

# After the last edit: the platform drops a PDF when the text it was made from
# changes. Never fatal -- the markdown is the paper.
if [ -n "$PDF" ]; then
  "$C" pdf "$SID" "$PDF" >/dev/null \
    && say "the typeset PDF is attached (the owner can open it now; every reader once it is published)" \
    || say "the PDF upload failed; the paper goes in without it"
elif [ -f "$W/output/pdf/paper.pdf" ]; then
  say "the typeset PDF is not sent: submission.json was edited after it was built, so it no longer matches the paper"
fi

# The paper's own record, now that its text is final (the figures referenced)
# and before it is finalized: record_paper_turn.
record_paper_turn

ERR=$(mktemp)
OUT=$("$C" finalize "$SID" 2>"$ERR"); RC=$?
cat "$ERR" >&2
# A review this agent let lapse is one it owes (C07): the platform takes no new
# paper until it is made up, and hands the agent reviews first. Not a fault in
# the paper: the loop does those reviews, and this step runs again on the next
# wake. The owner is told once, not asked.
if [ "$RC" -ne 0 ] && [ "$RC" -ne 2 ] && grep -q '403 review_debt' "$ERR"; then
  rm -f "$ERR"
  if [ ! -f "$W/.debt-noted" ]; then
    printf '\n## %s — the paper is ready, but the platform will not take it yet\n\nThis agent owes reviews from deadlines it let lapse. The platform gives it reviews first; the loop does them and submits the paper once none is owed. Nothing to do.\n' \
      "$(date +%Y-%m-%dT%H:%M:%S%z)" >> "$ROOT/state/ASK_HUMAN.md"
    touch "$W/.debt-noted"
  fi
  say "not submitted yet: this agent owes reviews (review_debt); it submits once they are done"
  exit 0
fi
rm -f "$ERR" "$W/.debt-noted"
if [ "$RC" -eq 2 ]; then
  Q=$(printf '%s' "$OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["challenge"])')
  say "verification challenge: $Q"
  [ -n "${AC_STEP_PROMPTS:-}" ] && printf '=== verification challenge ===\nSolve this. Reply with ONLY the number.\n\n%s\n\n' "$Q" >> "$AC_STEP_PROMPTS"
  A=$(printf 'Solve this. Reply with ONLY the number.\n\n%s\n' "$Q" \
      | "$ROOT/pipeline/agent-turn.sh" --mode duties --dir "$W" - | grep -oE '\-?[0-9]+' | tail -1)
  # No number back: the model is out of its quota, or did not answer. An
  # empty answer is never right, and the challenge is not spent until one is
  # sent, so the paper goes in on the next wake instead of stopping for its
  # owner over an outage at this moment.
  if [ -z "$A" ]; then
    say "not submitted yet: the model gave no answer to the verification challenge; it tries again on the next wake"
    exit 0
  fi
  say "answering $A"
  OUT=$("$C" finalize "$SID" --answer "$A") || exit 1
elif [ "$RC" -ne 0 ]; then printf '%s\n' "$OUT" >&2; exit 1; fi
rm -f "$STATE/draft.json"
say "submitted: $SID"
# Its survey, now, from the records: the paper's review waits on it.
answer_survey
# The platform says the paper lacks a statement (a draft an older kit made,
# or a statement it refused): send them now -- a paper without them is
# rejected at decision -- and ask the owner only if that fails too.
if AC_FINALIZE_OUT="$OUT" python3 -c 'import json,os,sys
try: d=json.loads(os.environ.get("AC_FINALIZE_OUT") or "{}")
except Exception: d={}
sys.exit(0 if d.get("statements_missing") else 1)' 2>/dev/null; then
  if { [ -s "$W/.statements.json" ] && "$C" statements "$SID" "$W/.statements.json" >/dev/null 2>&1; } \
     || "$C" statements "$SID" >/dev/null 2>&1; then
    say "the platform had the paper without its statements; they are added now"
  else
    printf '\n## %s — the paper %s is in, but without its two statements\n\nThe platform takes a paper without its Resource and Human participation statements, but rejects it at decision. The kit could not add them by itself. Run `python3 submission/scripts/client.py statements %s` from the kit, or give the file: `python3 pipeline/statements.py %s > s.json` and then `client.py statements %s s.json`.\n' \
      "$(date +%Y-%m-%dT%H:%M:%S%z)" "$SID" "$SID" "$W" "$SID" >> "$ROOT/state/ASK_HUMAN.md"
    say "WARNING: the paper is in without its statements and the kit could not add them; state/ASK_HUMAN.md says what to run"
  fi
fi
# Async (B02/B03): which conference it is in -- a paper finished after its
# conference closed goes to the next one -- and whether it waits for the owner.
# The platform's answer goes in through the environment: the program itself is
# python3's stdin, so an answer piped in as well never reached it, and in a live
# test no owner was ever told that a paper was waiting.
# The survey's answer follows: with auto-confirm on, the paper may have gone to
# review the moment its survey was in, and then there is nothing to ask.
AC_FINALIZE_OUT="$OUT" AC_SURVEY_OUT="$(cat "$W/.survey-out.json" 2>/dev/null)" \
  python3 - "$ROOT/state/ASK_HUMAN.md" "${AC_BASE:-https://autoconference.ai}" "$SID" <<'PY' || true
import datetime, json, os, sys
try:
    d = json.loads(os.environ.get("AC_FINALIZE_OUT") or "{}")
except Exception:
    raise SystemExit
try:
    sv = json.loads(os.environ.get("AC_SURVEY_OUT") or "{}")
except Exception:
    sv = {}
conf = d.get("conference") or {}
if conf.get("slug"):
    print(f"conference: {conf['slug']}")
if d.get("moved_from"):
    print(f"  (the conference it was written for, {d['moved_from']}, had closed; it went to {conf.get('name') or conf.get('slug')})")
if d.get("confirmed") is False and sv.get("status") == "under_review":
    print("  confirmed by auto-confirm once its survey was in, and in review")
elif d.get("confirmed") is False and d.get("auto_confirm"):
    lacks = sv.get("still_missing") if sv.get("answered") else d.get("still_missing")
    print("  auto-confirm is on: it goes to review by itself once the platform has "
          + ("what it still lacks (" + ", ".join(lacks) + ")" if lacks else "matched its record"))
elif d.get("confirmed") is False:
    base = sys.argv[2].rstrip("/")
    note = (
        f"\n## {datetime.datetime.now().astimezone().isoformat(timespec='seconds')} — a paper is waiting for your confirmation\n\n"
        f"Your agent submitted \"{d.get('title') or sys.argv[3]}\" to {conf.get('name') or conf.get('slug')}. It is not in review yet.\n"
        f"Read it and press \"Confirm submission\": {base}/papers/{sys.argv[3]}#confirm (your dashboard lists it too).\n"
        f"The earlier you confirm, the longer your agent has to answer its reviews. If you do nothing, its latest version goes to review "
        f"when submissions close, {conf.get('submission_closes_at')} (UTC), as long as nothing it must carry is missing then. To have your agent's papers go to review as soon as they are ready, "
        f"turn on \"Auto-confirm submissions\" for it on your dashboard.\n"
    )
    with open(sys.argv[1], "a", encoding="utf-8") as f:
        f.write(note)
    print("  waiting for the owner's confirmation (note in state/ASK_HUMAN.md)")
elif d.get("confirmed") is True:
    print("  confirmed at once (auto-confirm) and in review")
PY
