#!/usr/bin/env bash
# Compile a paper tree.
#
#   build_paper.sh                          draft build; \slot renders grey
#   build_paper.sh --final                  submission build; a surviving \slot
#                                           is a hard LaTeX error
#   build_paper.sh --paper-dir DIR --out DIR
#
# Defaults: --paper-dir ./paper, --out ./output/pdf. Environment overrides:
# AC_PAPER_DIR, AC_OUTPUT_DIR.
#
# Contract: references/paper-writing-template.md
set -euo pipefail

paper_dir="${AC_PAPER_DIR:-paper}"
output_dir="${AC_OUTPUT_DIR:-output/pdf}"
mode="draft"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --final)     mode="final"; shift ;;
    --paper-dir) paper_dir="$2"; shift 2 ;;
    --out)       output_dir="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -f "$paper_dir/main.tex" ]] || { echo "no main.tex under $paper_dir" >&2; exit 2; }
paper_dir="$(cd "$paper_dir" && pwd)"
mkdir -p "$output_dir"; output_dir="$(cd "$output_dir" && pwd)"
build_dir="$paper_dir/build"
mkdir -p "$build_dir"

if [[ "$mode" == "final" ]]; then
  output_pdf="$output_dir/paper.pdf"
  entry="$paper_dir/main_final.tex"
  # Flip the slot switch without editing the source tree. The generated entry
  # point sits beside main.tex so \input and the style file still resolve.
  trap 'rm -f "$entry"' EXIT
  sed 's|^\\input{preamble}$|\\input{preamble}\\ACfinaltrue|' "$paper_dir/main.tex" > "$entry"
else
  output_pdf="$output_dir/paper-draft.pdf"
  entry="$paper_dir/main.tex"
fi

if command -v latexmk >/dev/null 2>&1; then
  (cd "$paper_dir" && latexmk -pdf -interaction=nonstopmode -halt-on-error \
    -outdir="$build_dir" "$entry")
elif command -v tectonic >/dev/null 2>&1; then
  (cd "$paper_dir" && tectonic --keep-logs --keep-intermediates \
    --outdir "$build_dir" "$entry")
else
  echo "Neither latexmk nor tectonic is installed." >&2
  exit 1
fi

cp "$build_dir/$(basename "${entry%.tex}").pdf" "$output_pdf"
pdfinfo "$output_pdf" | awk '/^(Pages|Page size):/'
echo "build mode: $mode"
echo "paper: $output_pdf"

if [[ "$mode" == "draft" ]]; then
  # `|| true` is load-bearing. With `set -euo pipefail`, a grep that matches
  # nothing exits 1, the pipeline inherits it, and `set -e` killed this script
  # one line before it printed the count -- so a draft build reported FAILURE at
  # exactly the moment the writer finished filling every slot, which is the one
  # outcome this line exists to announce.
  slots=$(grep -rho '^[^%]*\\slot{' "$paper_dir" --include='*.tex' \
            | grep -v newcommand | wc -l | tr -d ' ' || true)
  echo "open slots: $slots (a final build fails while any remain)"
fi
