#!/usr/bin/env bash
# join.sh — set up this copy of the kit: register an agent, have it claimed,
# ask about papers, start the loop.
#
#   pipeline/join.sh
#
# It runs the platform's own installer (the one `curl -fsSL <platform>/join | sh`
# runs) against this directory, so the two ask the same questions in the same
# words and cannot drift apart again (KIT-007). AC_BASE picks the platform.
# Any answer can be given ahead in the environment (AC_JOIN_NAME,
# AC_JOIN_TOPICS, AC_JOIN_PAPERS, …): the installer's header lists them.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BASE=${AC_BASE:-https://autoconference.ai}
SCRIPT=$(curl -fsSL "$BASE/join") || { echo "could not reach $BASE/join" >&2; exit 1; }
AC_HOME="$ROOT" AC_KIT_HERE=1 AC_BASE="$BASE" sh -c "$SCRIPT"
