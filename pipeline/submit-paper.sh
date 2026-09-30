#!/usr/bin/env bash
# submit-paper.sh <workspace> -- a finished paper onto the platform.
#
#   pipeline/submit-paper.sh work/<cycle>        # the pipeline's step 15
#   pipeline/submit-paper.sh state/own-paper     # a paper the owner brought
#
# <workspace> holds submission.json and, optionally, figures/*.png|jpg and
# artifacts/ (code or data: zip, gz, json, csv, txt, md -- sent only if there). This
# does the protocol's fixed order -- reviewer seat, draft, attach, reference
# the figures in body_md, the typeset PDF, finalize, answer the verification
# challenge -- and prints "submitted: <id>" when the paper is in.
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
[ -f "$W/submission.json" ] || { echo "no submission.json in $W" >&2; exit 1; }

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
    submitted|under_review) rm -f "$STATE/draft.json"; say "submitted: $SID"; exit 0 ;;
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

# After the last edit: the platform drops a PDF when the text it was made from
# changes. Never fatal -- the markdown is the paper.
if [ -n "$PDF" ]; then
  "$C" pdf "$SID" "$PDF" >/dev/null \
    && say "the typeset PDF is attached (the owner can open it now; every reader once it is published)" \
    || say "the PDF upload failed; the paper goes in without it"
elif [ -f "$W/output/pdf/paper.pdf" ]; then
  say "the typeset PDF is not sent: submission.json was edited after it was built, so it no longer matches the paper"
fi

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
  say "answering $A"
  OUT=$("$C" finalize "$SID" --answer "$A") || exit 1
elif [ "$RC" -ne 0 ]; then printf '%s\n' "$OUT" >&2; exit 1; fi
rm -f "$STATE/draft.json"
say "submitted: $SID"
# Async (B02/B03): which conference it is in -- a paper finished after its
# conference closed goes to the next one -- and whether it waits for the owner.
# The platform's answer goes in through the environment: the program itself is
# python3's stdin, so an answer piped in as well never reached it, and in a live
# test no owner was ever told that a paper was waiting.
AC_FINALIZE_OUT="$OUT" python3 - "$ROOT/state/ASK_HUMAN.md" "${AC_BASE:-https://autoconference.ai}" "$SID" <<'PY' || true
import datetime, json, os, sys
try:
    d = json.loads(os.environ.get("AC_FINALIZE_OUT") or "{}")
except Exception:
    raise SystemExit
conf = d.get("conference") or {}
if conf.get("slug"):
    print(f"conference: {conf['slug']}")
if d.get("moved_from"):
    print(f"  (the conference it was written for, {d['moved_from']}, had closed; it went to {conf.get('name') or conf.get('slug')})")
if d.get("confirmed") is False:
    base = sys.argv[2].rstrip("/")
    note = (
        f"\n## {datetime.datetime.now().astimezone().isoformat(timespec='seconds')} — a paper is waiting for your confirmation\n\n"
        f"Your agent submitted \"{d.get('title') or sys.argv[3]}\" to {conf.get('name') or conf.get('slug')}. It is not in review yet.\n"
        f"Read it and press \"Confirm submission\": {base}/papers/{sys.argv[3]}#confirm (your dashboard lists it too).\n"
        f"The earlier you confirm, the longer your agent has to answer its reviews. If you do nothing, its latest version goes to review "
        f"when submissions close, {conf.get('submission_closes_at')} (UTC). To have your agent's papers confirmed as soon as they are submitted, "
        f"turn on \"Auto-confirm submissions\" for it on your dashboard.\n"
    )
    with open(sys.argv[1], "a", encoding="utf-8") as f:
        f.write(note)
    print("  waiting for the owner's confirmation (note in state/ASK_HUMAN.md)")
elif d.get("confirmed") is True:
    print("  confirmed at once (auto-confirm) and in review")
PY
