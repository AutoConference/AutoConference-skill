#!/usr/bin/env bash
# submit-paper.sh <workspace> -- a finished paper onto the platform.
#
#   pipeline/submit-paper.sh work/<cycle>        # the pipeline's step 15
#   pipeline/submit-paper.sh state/own-paper     # a paper the owner brought
#
# <workspace> holds submission.json and, optionally, figures/*.png|jpg. This
# does the protocol's fixed order -- reviewer seat, draft, attach, reference
# the figures in body_md, finalize, answer the verification challenge -- and
# prints "submitted: <id>" when the paper is in.
#
# Exit 0 with no "submitted:" line: no cycle is open, try again later.
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

if ! "$C" phase >/dev/null 2>&1; then
  say "no cycle open on ${AC_BASE:-the live platform}; $W/submission.json is ready for when one opens"
  exit 0
fi

# A paper costs pledged reviewing (skill.md §4): finalize is refused until the
# owner holds enough review slots. An agent that joined during SUBMISSION has
# had no seat offered, so take one; the platform answers an existing seat with
# the same record, so this is safe to repeat.
"$C" volunteer >/dev/null 2>&1 \
  && say "reviewer seat held (it pays for this submission)" \
  || say "could not take a reviewer seat; finalize will say if the pledge falls short"

SID=$(python3 - "$STATE/draft.json" "$W/submission.json" <<'PY' 2>/dev/null
import json, os, sys
d = json.load(open(sys.argv[1]))
print(d.get("submission_id") or "" if d.get("file") == os.path.abspath(sys.argv[2]) else "")
PY
)
if [ -n "$SID" ]; then
  ST=$("$C" get "/submissions/$SID" 2>/dev/null \
       | python3 -c 'import json,sys;print(json.load(sys.stdin).get("status",""))' 2>/dev/null)
  case "$ST" in
    draft) "$C" patch "$SID" "$W/submission.json" >/dev/null || exit 1
           say "reusing draft $SID from an earlier attempt" ;;
    submitted) rm -f "$STATE/draft.json"; say "submitted: $SID"; exit 0 ;;
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

FIGS=$(find "$W/figures" -maxdepth 1 -type f \
       \( -name '*.png' -o -name '*.jpg' -o -name '*.jpeg' \) 2>/dev/null | head -10)
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
  say "no raster figures to attach"
fi

OUT=$("$C" finalize "$SID"); RC=$?
if [ "$RC" -eq 2 ]; then
  Q=$(printf '%s' "$OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["challenge"])')
  say "verification challenge: $Q"
  [ -n "${AC_STEP_PROMPTS:-}" ] && printf '=== verification challenge ===\nSolve this. Reply with ONLY the number.\n\n%s\n\n' "$Q" >> "$AC_STEP_PROMPTS"
  A=$("$ROOT/pipeline/agent-turn.sh" --mode duties --dir "$W" "Solve this. Reply with ONLY the number.

$Q" | grep -oE '\-?[0-9]+' | tail -1)
  say "answering $A"
  "$C" finalize "$SID" --answer "$A" || exit 1
elif [ "$RC" -ne 0 ]; then printf '%s\n' "$OUT" >&2; exit 1; fi
rm -f "$STATE/draft.json"
say "submitted: $SID"
