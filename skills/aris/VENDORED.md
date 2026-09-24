# Vendored: ARIS

**[Auto-claude-code-research-in-sleep](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep)**
by [@wanshuiyin](https://github.com/wanshuiyin). MIT, © 2026 wanshuiyin — see `LICENSE`.

Commit `9cbb6aab1084cd622ccb016cc156008fbdaa1402`, the one `pipeline/run-pipeline.sh`
was built and run against, unmodified. Only what the pipeline mounted when it
was run is included: fifteen skills, `shared-references/` (the contracts those
skills link to), `tools/` (the helpers they resolve through `.aris/tools`) and
the licence. Every mounted skill's description costs context in every step, so
the set was kept to what the steps use; `docs/skills.md` lists it with reasons.

`pipeline/fetch-skills.sh` mounts it into `.claude/skills/`. To move to a newer ARIS,
replace this directory from a new commit and update the hash here and in
`docs/credits.md`.
