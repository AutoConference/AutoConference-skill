Proposal readiness check (before final recommendation):

Apply this check to the provisional recommendation and its strongest
literature-derived alternative, whether optional topic leads are on or off.
Use the owner's direction, existing evidence and actual resource limits. Keep
a concrete owner-supplied question or reference-paper intent; repair its plan,
not its topic, unless the owner approves a change. Do not prefer a news-derived
idea just because it is recent. Do not add a new research phase or expand the
search, model-call or experiment budget for this check.

1. Executable method. Specify the key inputs, outputs, state and decision rule
   in a short algorithm or operational definition. Name the closest existing
   method and the exact difference being tested. A named mechanism or an LLM
   asked to judge something is not an implementation: define its interface,
   trusted evidence, failure handling and an independently checkable outcome.
   Separate source-supported facts from proposed design choices. Do not invent
   a source, novelty claim, dataset, model capability or completed result.
2. Effective experiment. Trace the proposed intervention through the real input,
   preprocessing and execution path: does it actually change what the model or
   tool receives? Identify the assumption most likely to invalidate the test
   and a minimal sanity check for it. Separate the proposed mechanism's effect
   from the surrounding workflow with a matched baseline or ablation. Specify
   the independent evaluation unit, data split, success/failure labels and how
   ambiguous cases are handled; related variants must not leak across splits.
   Distinguish support, contradiction and insufficient evidence. A wide interval
   or a nonsignificant result does not establish absence or failure. Relate any
   proposed effect threshold to sample size or mark its precision as unknown.
3. Deliverable scope. Name the model/tool and public data to use (or explicitly
   mark availability unverified), human labeling needs, and workload as cases x
   conditions x repetitions x calls/samples. Include calibration, baselines,
   failure cases and validation in the same budget. Use measured throughput
   where available; otherwise give assumptions and a small cost preflight,
   never made-up measured runtime. Reduce scope if it cannot fit; do not replace
   the owner's question or hide the hard part behind an unspecified component.

Make one bounded repair pass. Compare the resulting plans under the same
importance, evidence, implementability and resource criteria before choosing.
Leave the core method and controls in FINAL_PROPOSAL.md and the executable
details in EXPERIMENT_PLAN.md; a separate reassuring paragraph cannot repair
an unchanged plan. Keep a short Plan readiness note in FINAL_PROPOSAL.md:
what changed, the critical unresolved assumption, its first check and a status:
ready to pilot, needs verification, or not viable within the current budget.
Unverified dependencies or an undefined core mechanism cannot be ready to pilot.
If neither candidate is viable, say so instead of forcing a winner; if an
owner decision is needed, use the existing ask-human/stop flow. These are
planning judgments, not experimental results or a replacement for the later
feasibility and calibration gates. Never claim a planned check was executed.
