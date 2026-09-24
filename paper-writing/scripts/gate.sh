#!/usr/bin/env bash
# Run every gate once, in the right order, with the right flags.
#
#   gate.sh                      from the project root (holds paper.json, paper/)
#   gate.sh --draft              draft build; slots render grey; no submission rules
#   gate.sh --skip-citations     everything except the network-bound citation gate
#   gate.sh --no-render          skip the page renders (keeps check_render.py)
#
# Reads the venue page budget from paper.json, so the ceiling is never typed
# by hand. Prints one line per gate and a final verdict; exits non-zero if any
# gate is blocked. The writer's loop is: edit -> gate.sh -> fix every ERROR ->
# gate.sh. Running the checkers one at a time, or after every small edit, is
# how a paper gets fifty builds instead of five.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project="$(pwd)"
mode="final"; citations=1; render=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --draft) mode="draft"; shift ;;
    --skip-citations) citations=0; shift ;;
    --no-render) render=0; shift ;;
    --project) project="$(cd "$2" && pwd)"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
cd "$project" || exit 2
[[ -f paper/main.tex ]] || { echo "no paper/main.tex under $project" >&2; exit 2; }

budget=$(python3 - <<'PY'
import json, sys
try:
    cfg = json.load(open("paper.json"))
    print(cfg.get("venue", {}).get("max_main_pages", 9))
except Exception:
    print(9)
PY
)

status=0
line() { printf "  %-12s %s\n" "$1" "$2"; }
run_gate() {  # name, command...
  local name="$1"; shift
  local out
  if out=$("$@" 2>&1); then
    line "$name" "$(echo "$out" | grep -m1 -E '^(PASS|BLOCKED|Pages:|rendered)' || echo "$out" | tail -1)"
  else
    status=1
    line "$name" "$(echo "$out" | grep -m1 -E '^(PASS|BLOCKED)' || echo "FAILED")"
    echo "$out" | grep -E '^\s*(ERROR|error:|! )' | head -12 | sed 's/^/               /'
  fi
}

echo "gate.sh  ($mode build, page budget $budget)"
if [[ "$mode" == "final" ]]; then
  run_gate "build" "$here/build_paper.sh" --paper-dir paper --final
  pdf=output/pdf/paper.pdf
else
  run_gate "build" "$here/build_paper.sh" --paper-dir paper
  pdf=output/pdf/paper-draft.pdf
fi
if [[ $status -ne 0 ]]; then
  # Every gate below reads the compiled PDF. A previous run's PDF is still on
  # disk after a failed build, and checking it would report the last good
  # paper's verdict for the broken one.
  echo "BLOCKED  the build failed; the remaining gates would read the previous build's PDF"
  exit 1
fi
[[ -f "$pdf" ]] || { echo "  no PDF produced; fix the build first"; exit 1; }
if [[ $render -eq 1 ]]; then
  run_gate "render" "$here/render_paper.sh" --pdf "$pdf"
fi
if [[ "$mode" == "final" ]]; then
  run_gate "structure" python3 "$here/check_paper_structure.py" --paper-dir paper --submission --pdf "$pdf" --max-main-pages "$budget"
else
  run_gate "structure" python3 "$here/check_paper_structure.py" --paper-dir paper --pdf "$pdf" --max-main-pages "$budget"
fi
run_gate "prose" python3 "$here/check_prose_quality.py" paper/
if [[ $citations -eq 1 ]]; then
  run_gate "citations" python3 "$here/check_citations.py" paper/references.bib
else
  line "citations" "(skipped)"
fi
run_gate "render-check" python3 "$here/check_render.py" "$pdf"

if [[ $status -eq 0 ]]; then
  echo "ALL GATES PASS  ($pdf)"
  echo "  now look at page 1, every float page, and the appendix in output/pages/ -- no gate reads the drawn shapes"
else
  echo "BLOCKED  fix every ERROR above, then run gate.sh again"
fi
exit $status
