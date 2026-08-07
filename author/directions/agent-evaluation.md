# Evaluation methodology for agent systems

> Evaluation / methodology. Suits an agent that can run modest experiments and cares about measurement.

Agent benchmarks are unusually easy to get wrong: the task distribution leaks into the prompt, the scoring
rubric rewards format over substance, a single seed hides variance the size of the effect, or the baseline
is an agent nobody tried to make work.

Pick one such failure mode and demonstrate it concretely. Take a published agent benchmark, construct the
control the original omitted, and show how much of the reported gap it accounts for. A trivial baseline
that recovers most of the headline number is a strong result.

Report variance. Most agent evaluations report a mean over a handful of runs and no spread, which makes the
comparisons uninterpretable; simply doing this properly on an existing benchmark is a contribution.

Do not propose a new benchmark unless you can also show why the existing ones fail at the specific thing
yours measures.
