# Prose rules

Load for any manuscript-facing writing pass: drafting, revising, compressing, or
captioning. These are writing-quality controls that make the argument legible.
They are not detector-evasion tactics, and none of them may be applied at the
cost of technical precision.

## Voice

Write from inside the contribution. The manuscript is the authors' argument, not
a report about a manuscript.

- Prefer: "We study...", "The bound loosens because...", "The ordering reverses
  when...".
- Avoid: "This paper proposes...", "The authors demonstrate...", "The reviewer
  will note...", except when describing someone else's work.
- Keep reviewer-facing reasoning entirely internal. The paper persuades with
  evidence, never with commentary about what a reviewer might want.
- Never narrate the writing process, the agent loop, the gate, or the internal
  status of a method. "The confirmed configuration" is engineering language;
  the paper says what the configuration is.

## Paragraph contract

Each paragraph carries one retained message. Each sentence does one of five
jobs:

1. state or narrow the message;
2. explain the mechanism or reason;
3. supply evidence, a citation, or an example;
4. contrast with an alternative;
5. transition to the next needed idea.

A sentence that does none of these is cut. A paragraph whose sentences all do
job 1 is a summary, not an argument.

Section-level progression:

```
known context -> unresolved gap -> root cause -> insight -> mechanism -> evidence -> bounded claim
```

Do not jump from motivation to a method name. Do not assert a claim before the
reader has seen why it should be true.

## Banned patterns

| Pattern | Instead |
|---|---|
| Throat-clearing openers: "It is important to note that", "In order to", "We now turn to" | Start with the scientific subject |
| Defensive framing: "we merely", "a simple extension", "despite being limited" | State the scientific reason |
| Label soup in running prose: `Q1`, `C2`, `RQ3`, `H1` | Natural names: "the variance question" |
| Punctuation as structure: em-dash interruptions, colon chains, arrow stacks | Sentences |
| Hype without evidence: "significant", "robust", "novel", "comprehensive", "dramatically" | The measured effect and its scope |
| Synonym cycling for a defined term | The one canonical term, every time |
| Forced three-item lists | The number of items the evidence supports |
| Abstract that is mostly numbers | Contribution first, one or two decisive numbers |
| Generic caveats sprinkled through the paper | One Limitations section |

## Measurable limits

`scripts/check_prose_quality.py` enforces these on the LaTeX sources:

| Check | Limit |
|---|---|
| Em dashes (`---` or `—`) in authored prose | ≤ 3 per paper, 0 preferred |
| Throat-clearing openers | 0 |
| Hype terms without a nearby number | flagged for review |
| Five consecutive sentences within a 5-word length band | flagged |
| Semicolons | ≤ 2 per 1000 prose words |
| Abstract numeric density | ≤ 30% of tokens |
| Third-person manuscript narration | 0 |

Math, `verbatim`, citation keys, labels, and LaTeX commands are excluded before
counting, so a `---` inside a table rule or a hyphenated identifier is not
mistaken for an em dash.

## The banana rule

Do not call a banana an elongated yellow fruit to avoid repetition. If the
method section says "split seed", the experiments section, the tables, and the
figure captions all say "split seed". A synonym makes the reader ask whether a
new object has been introduced.

Mechanical enforcement: every canonical term has a macro in `paper/macros.tex`,
and prose uses the macro. `check_prose_quality.py` reports any hand-typed
occurrence of a term that has a macro.

A macro body must be a distinctive technical object: a method name, a factor, a
metric, a dataset. Do not create a macro for a generic phrase such as "this
study" or "the model" — the term check then fires on ordinary English and the
warning stops carrying information.

Acronym austerity: define every acronym at first use, and do not invent an
acronym that appears fewer than four times.

## Five revision passes

Run these in order after all sections are drafted, one pass at a time over the
whole manuscript.

**Pass 1 — clutter.** Strip each sentence to its cleanest form.

| Cluttered | Replace |
|---|---|
| Due to the fact that | Because |
| In order to | To |
| A number of | Several |
| It is worth noting that | (delete) |
| On the basis of | Based on |
| Have an effect on | Affect |
| Give rise to | Cause |

Remove redundancies ("completely eliminate" → "eliminate") and AI-isms (delve,
pivotal, landscape, tapestry, underscore, intriguingly, leverage as a verb).

**Pass 2 — verbs.** Find the actor and rebuild as subject–verb–object. Resurrect
smothered verbs: "we performed an analysis of" → "we analyzed". Passive stays
where the agent is genuinely irrelevant or the venue requires it.

**Pass 3 — architecture.** Split sentences over 40 words. Keep subject and verb
adjacent. Put familiar context first and new information last. Break the mold if
every paragraph runs problem → method → benefit → summary. Do not start
consecutive sentences with "This" or "We".

**Pass 4 — keywords.** Extract every defined term from the method and verify it
appears verbatim in experiments, tables, and captions.

**Pass 5 — numbers and citations.** Every number in the abstract matches the
main table. Every percentage matches its raw counts. Significant figures are
consistent. Every `\cite` key resolves to a verified entry. Flag any statistic
cited only through a secondary source.

## Claim calibration

Calibrate in both directions.

- If the evidence supports the claim, state it directly. Stacked hedges around a
  supported result are a defect, not caution.
- If the evidence does not support the claim, narrow the claim or cut it. Never
  substitute a softer-sounding synonym for fixing scope, modality, comparison
  direction, or aggregation.
- Necessary assumptions, uncertainty, and scope are part of the claim and stay
  in the sentence. Generic disclaimers ("further research is needed", "may not
  generalize") belong in Limitations or nowhere.
- Never write "we do not claim...", "we do not address...", or any other
  instruction confession. Say what the paper does.

## Material facts

An observed, verified fact that changes the supported claim, the fairness of a
comparison, reproducibility, or a required disclosure is never softened or
omitted. If it makes the paper weaker, the paper gets weaker. Route speculative
drawbacks and remote hypotheticals out of the manuscript instead; they belong in
a note to the operator, not in a paragraph.

## Final self-audit

Before declaring prose ready, scan for:

- a paragraph with no retained message;
- a term with more than one name;
- a strong adjective not grounded in evidence;
- an abstract dominated by numbers;
- an equation or float with no narrative purpose;
- third-person narration about the paper;
- punctuation doing the work of logic;
- a run of paragraphs with identical shape;
- any hard failure reported by `check_prose_quality.py`.
