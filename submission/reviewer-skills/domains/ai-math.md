---
id: ai-math
name: AI for mathematics
version: 1
match: \b(theorem proving|automated reasoning|formal(i[sz]ation|ly verified)?|lean ?4?|isabelle|coq|rocq|proof assistant|minif2f|putnam|imo|olympiad|conjecture|combinatori\w*|symbolic|mathematical reasoning|math(ematics)? benchmark|autoformali[sz]ation)\b
---

# Field skill: AI for mathematics

This adds to the base reviewer skill; it overrides nothing in it.

## What to check that a generalist misses

- **Checked by whom.** A proof a proof assistant accepted is checked; a proof
  in natural language a model wrote is not, however fluent. Say which kind each
  result is. For formal proofs: which system and version, which library
  version, and whether `sorry`, `admit`, `axiom` or an unsound tactic appears
  anywhere — search the attached files for them.
- **The statement proved is the statement claimed.** Autoformalised theorems
  can be weaker than the original (a missing hypothesis, a different
  quantifier, a special case). Compare the formal statement with the informal
  one for the central results, and for a sample of the benchmark.
- **Benchmark hygiene.** miniF2F, ProofNet, Putnam and olympiad sets have known
  errors and public solutions. Which split, which fixes, and could the model
  have seen the solutions? Pass@k needs k and the sampling budget, and a
  comparison at equal compute.
- **Search and compute.** Tree search and repeated sampling can turn compute
  into solved problems. Report the attempts per problem and the wall-clock or
  token budget, and compare at equal budget.
- **New mathematics.** A claimed new result (a bound, a construction, a
  counterexample) is checked like any result: is the object given in full, can
  it be verified independently (a certificate, a program a reader can run), and
  is it actually new — search the literature for it.
- **"Reasoning" claims.** A higher score on a math benchmark shows a higher
  score. A claim about how the model reasons needs evidence about the
  reasoning: error analysis, interventions, or checked intermediate steps.

## Do not demand

- A formal proof of every statement in a paper whose contribution is not
  formal verification.
- Results on every theorem-proving benchmark; one appropriate one, used
  carefully, supports a focused claim.
