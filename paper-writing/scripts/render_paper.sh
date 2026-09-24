#!/usr/bin/env bash
# Render every page of a compiled paper to PNG for visual QA.
#
#   render_paper.sh [--pdf FILE] [--out DIR] [--dpi N]
#
# Text extraction cannot validate layout. Look at the pages.
set -euo pipefail

pdf="${AC_PDF:-output/pdf/paper-draft.pdf}"
out="${AC_RENDER_DIR:-output/pages}"
dpi=150

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pdf) pdf="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --dpi) dpi="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -f "$pdf" ]] || { echo "no PDF at $pdf; build it first" >&2; exit 2; }
mkdir -p "$out"
find "$out" -maxdepth 1 -type f -name 'page-*.png' -delete
pdftoppm -png -r "$dpi" "$pdf" "$out/page"
echo "rendered $(ls "$out"/page-*.png | wc -l | tr -d ' ') pages to $out"
