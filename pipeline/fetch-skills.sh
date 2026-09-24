#!/usr/bin/env bash
# Build .claude/skills/ — the tree Claude Code looks in.
#
# Generated rather than committed, because it is a flat index over three source
# directories and a committed copy would be a second thing to keep in sync. The
# links are relative, so they keep working wherever the repo is checked out.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

rm -rf .claude/skills
mkdir -p .claude/skills

n=0
for group in ours aris ccfa; do
  for dir in skills/$group/*/; do
    name=$(basename "$dir")
    [ -f "$dir/SKILL.md" ] || continue          # tools/, LICENSE, references live here too
    ln -sfn "../../$dir" ".claude/skills/$name"
    n=$((n + 1))
  done
done
# ARIS's cross-skill contracts, referenced by name from inside its skills
ln -sfn ../../skills/aris/shared-references .claude/skills/shared-references

# ARIS's helper-resolution chain, layer 1 (see skills/aris/shared-references/integration-contract.md)
mkdir -p .aris
ln -sfn ../skills/aris/tools .aris/tools
# The ledger describes the machine the experiments run on, so it is this
# install's own (state/, written when writing is first switched on), not the
# one pipeline/env-ledger.md recorded for the box the pipeline was built on.
ln -sfn ../state/env-ledger.md .aris/env-ledger.md
echo submission > .aris/assurance.txt

echo "mounted $n skills into .claude/skills/"
