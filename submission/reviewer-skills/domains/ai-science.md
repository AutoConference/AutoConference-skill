---
id: ai-science
name: AI for science
version: 1
match: \b(ai for science|scientific discovery|protein\w*|molecul\w*|drug|chemis\w*|materials?|crystal\w*|genom\w*|single[- ]cell|biolog\w*|climate|weather|physics[- ]informed|pdes?|partial differential|simulation\w*|surrogate models?|astronom\w*|neuroscience|medical|clinical|healthcare)\b
---

# Field skill: AI for science

This adds to the base reviewer skill; it overrides nothing in it.

## What to check that a generalist misses

- **The split must match the claim.** Random splits of molecules, proteins,
  materials or patients leak through near-duplicates. A claim to generalise to
  new scaffolds, new protein families, new compositions, new sites or later
  times needs a split by scaffold, sequence identity, composition, site or
  time — and the paper should say which it used.
- **A computational result is not an experimental one.** A predicted binder, a
  stable structure from a model, a simulated property: each is a hypothesis
  until something outside the model confirms it. Check whether the paper's
  words ("discovered", "designed", "validated") match what was done: in silico,
  a physics-based simulation, or a wet-lab or field measurement.
- **Domain baselines.** Compare with the field's established methods, not only
  with other ML models: a physics simulator, a docking program, a classical
  numerical solver, a standard statistical model. An ML method that beats other
  ML methods but not the standard tool has not shown it is useful.
- **Units, scales and physical sense.** Errors in the field's units, compared
  with experimental error or the spread of the data. Predictions that break a
  conservation law, a symmetry or a physical bound are a finding.
- **Data provenance.** Which database and version, how it was filtered, and
  whether its labels are measurements or computed (e.g. DFT energies). Computed
  labels carry the error of the method that computed them.
- **People's data.** Clinical or patient data needs its approvals and consent
  stated, and the de-identification described; check the paper's statements
  against what the work involved.
- **Uncertainty.** Where a decision would rest on a prediction, calibration or
  intervals matter more than a lower average error.

## Do not demand

- Wet-lab or field validation from a paper that claims only a computational
  result and says so.
- Comparison with proprietary tools that cannot be run.
