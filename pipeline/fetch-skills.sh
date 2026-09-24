#!/usr/bin/env bash
# Build the skill tree the research steps run with: state/skill-mount/.claude/skills.
#
# Not <kit>/.claude/skills: the inbox duties run from the kit root, and Claude
# Code loads every skill in the working directory's .claude/skills into each
# turn -- so a review would be written with seventeen research skills in view.
# The mount lives under state/ instead, and run-pipeline.sh links it into each
# research workspace only.
#
# Generated rather than committed, because it is a flat index over three source
# directories and a committed copy would be a second thing to keep in sync. The
# links are relative, so they keep working wherever the repo is checked out.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
MOUNT=state/skill-mount/.claude/skills      # four levels below the kit root

rm -rf "$MOUNT"
mkdir -p "$MOUNT"

n=0
for group in ours aris ccfa; do
  for dir in skills/$group/*/; do
    name=$(basename "$dir")
    [ -f "$dir/SKILL.md" ] || continue          # tools/, LICENSE, references live here too
    ln -sfn "../../../../$dir" "$MOUNT/$name"
    n=$((n + 1))
  done
done
# ARIS's cross-skill contracts, referenced by name from inside its skills
ln -sfn ../../../../skills/aris/shared-references "$MOUNT/shared-references"

# ARIS's helper-resolution chain, layer 1 (see skills/aris/shared-references/integration-contract.md)
mkdir -p .aris
ln -sfn ../skills/aris/tools .aris/tools
# The ledger describes the machine the experiments run on, so it is this
# install's own (state/, written when writing is first switched on), not the
# one pipeline/env-ledger.md recorded for the box the pipeline was built on.
ln -sfn ../state/env-ledger.md .aris/env-ledger.md
echo submission > .aris/assurance.txt

echo "mounted $n skills into $MOUNT/"
