# The study brief

`SKILL.md` is the discipline and knows nothing about any particular study. The
study lives in `STUDY.md` at the root of the repository being worked in. This
file says what that brief must contain.

The split exists because the skill was written against one study and had its
facts welded into it — the paper, the frozen settings, a broken entry point, a
missing YAML key. All of that is true of one repository and false of the next,
while the discipline around it — an ablation is the unit of a claim, seeds are
the error bar and not the claim, every run leaves a record only it could have
written — is true of any of them. Mixing the two meant the general part could
not be reused and the specific part could not be reviewed.

`study-bound-to-disagree.md` in this directory is the worked instance.

## Why a brief and not inference

An agent could read a repository and guess most of this. It must not, for two
reasons that are not about convenience.

**The frozen list is a decision, not a fact about the code.** Which settings
define what the metric *means* — evaluation precision, confidence level, the
data splits, the bound or scoring code itself — cannot be derived by reading a
file. They are the venue's answer to "what would make two numbers
incomparable". An agent that infers them will infer the ones that are easy to
hold fixed, which is the opposite of the ones that matter.

**Nothing in the skill knows which direction is better.** A delta of −0.045 is
an improvement or a regression depending on the metric, and the gate
deliberately refuses to guess: `check_manuscript_readiness.py` reports a signed
delta and never labels it. If the brief does not say, every ablation table is
unreadable.

So: **if `STUDY.md` is absent, stop.** A brief the agent wrote for itself
records its own assumptions and then validates against them.

## Required sections

| Section | Must answer | Why it cannot be inferred |
|---|---|---|
| The work you are building on | What is the method, in a paragraph, and which paper is it from? | The agent needs the idea to form a hypothesis, and the citation to avoid quoting a paper it has not read |
| The open question | What are you investigating? Any entry points already known? | Otherwise the agent picks the question its tooling makes cheapest — which is how a record fills with seed sweeps |
| The metric | Its exact name, and **whether lower or higher is better** | The gate reports signed deltas and refuses to guess direction |
| Can the metric be satisfied degenerately? | Is there a trivial behaviour that scores well — emitting `Any`, returning `{}`, predicting the majority class? And what does it score? | The skill treats "removal improved the metric" as the interesting result. On a gameable metric that rule promotes an artefact. Naming the behaviour fixes the sign; naming its score is what lets a delta be attributed, and it belongs in the record as a `reference` row |
| Does the metric embed a scale? | Is a horizon, budget or sample count part of the metric's own name — "crashes in 24 hours", "accuracy at 10k steps"? | Then that parameter is frozen, not scale. Shrinking it to fit the budget does not make the experiment smaller, it changes the quantity |
| Is the metric constrained? | Is it defined only inside a region — "goodput at fixed fairness", "accuracy at fixed epsilon"? | Then an ablation can leave that region rather than score worse, and its row is `off-constraint` rather than a number |
| Frozen | Which settings, files and splits may not be touched, and why each one changes what the metric means | A decision about comparability, not a property of the code |
| The method surface | What may be changed: the stages, their settings, the files they live in | This is the module list `ablation-plan.tsv` must account for; the brief and the plan describe the same object from two directions |
| How to run one experiment | The exact command, where results land, how to read the metric | Reading it wrong is how a training log ends up in the context window |
| The budget | How long one experiment may take before it is killed | A property of the scale this study runs at |
| Known breakages | Traps already hit and diagnosed | The whole value is that the next agent does not rediscover them; it is worthless unless it is added to |

## Three boundaries the brief has to draw

**Scale versus evaluation semantics.** Epoch budgets, subsets and compression
sizes are scale: they may move, provided both sides of every comparison move
together and `results.tsv` records which values were used. The frozen list is
the other kind. Anything genuinely ambiguous belongs in the frozen list and
should say so — holding a scale setting fixed costs a slower run, while moving
an evaluation setting costs a run whose numbers compare to nothing.

**A scale the budget may cut versus a scale the metric names.** Epochs and
subsets may shrink to fit the budget. A horizon inside the metric's own
definition may not — running a 24-hour benchmark for six hours produces a
different quantity, not a cheaper measurement of the same one. When the budget
and the metric cannot both be met, record that and run fewer configurations
rather than shorter ones.

**A module versus a hyperparameter.** A module is a stage that can be removed,
replaced by a trivial or random alternative, or frozen at initialisation. A
hyperparameter is a dial. The method surface should list modules; a dial that
cannot be described as a removal in `ablation-plan.tsv`'s `removal` column is a
sweep, and belongs in `results.tsv` with `how=swept`, where it will not
discharge a module.

## Keeping it honest

The brief is the one claim in this system that nothing checks. The gate reads a
ledger and cannot know whether the method has five stages or one — so a brief
that names one convenient module passes every automated check there is.

Two things make that visible rather than solved:

- **`ablation-plan.tsv` carries a `source` column** (`file:function`) for every
  module, so a reader can open the file and see what the plan omitted.
- **The brief is tracked in git.** A module that disappears from it does so in a
  diff.

Comparing the brief against the method's actual stage order is an exit criterion
in `manuscript-readiness.md`, and it belongs to a person.
