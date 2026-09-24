# Evidence interface

The contract between whatever produces evidence and this writing skill. The two
sides are developed independently, so this file is the only thing either needs
to know about the other.

The writing skill never runs an experiment, never reads a training log, and
never opens a raw result. It reads two things: **aggregates** and a **readiness
verdict**. Everything upstream of those is the research side's business.

```
research side                    interface                writing side
─────────────                    ─────────                ────────────
runs experiments      ──────▶    runs/*.json              (never read)
preserves manifests   ──────▶    runs/*.meta.json         (never read)
aggregates            ──────▶    runs/aggregate__*.json   ──▶ tables, figures, opening
decides eligibility   ──────▶    readiness.json           ──▶ gate for --submission
```

## 1. Aggregate artifact

One file per method, or per compared configuration. The writing side reads only
these, so a number that is not in one cannot reach the paper.

```json
{
  "label":          "random-matrix",
  "method":         "random",
  "metric":         "p2l_bound",
  "estimator":      "mean over trajectory seeds, per split seed",
  "primary_inputs": ["runs/random-split1-traj0__<commit>.json", "..."],
  "per_split": {
    "1": {"mean": 0.379, "std": 0.026, "n": 3, "values": [0.352, 0.382, 0.403]}
  },
  "overall": {"mean": 0.387, "std": 0.013, "range": 0.030, "n_splits": 5},
  "paired_contrast": {"mean": 0.011, "uncertainty": 0.005,
                      "against": "max-error", "per_split": [0.022, 0.011]}
}
```

| Field | Required | Meaning |
|---|---|---|
| `label` | yes | Identifies this aggregate; appears in figure manifests |
| `method` | yes | Must match a `method` named in the project config's figure specs |
| `metric` | yes | Rendered in the opening figure and float captions; underscores become spaces. `metric_display` overrides the rendering |
| `estimator` | yes | Stated so a reader knows what `mean` means |
| `primary_inputs` | yes | Every raw run this aggregate combines, as paths |
| `per_split` | yes | Per-condition mean, std, `n`, and the raw `values` |
| `overall` | yes | Across-condition summary |
| `paired_contrast` | for the headline | Contrast, its uncertainty, and what it is against; `ci_low`/`ci_high` when the paper will print the contrast's interval |
| `per_split.*.ci_low`, `ci_high` | no | An interval for that condition's mean, when the research side computed one (a Wilson interval for a rate, say); `null` for an exact computation. A number a slot may be filled from, like any other field here |

**`paired_contrast` is not the number the opening figure annotates.** The figure
labels the primary arm's margin over *the strongest other arm in that
condition*, which may be a different arm in each condition; `paired_contrast` is
against the one arm `against` names. The two coincide only when that arm is
strongest everywhere. Both are defensible, they are different statistics, and a
manuscript that quotes one in prose and shows the other in a figure reads as
internally inconsistent to a reviewer while passing every gate.
`make_paper_data.py --opening` compares them and says so when they disagree.
Derive `paired_contrast` from the named arm's own `per_split` means, never from
a design constant, or the two will disagree for a reason no reader can see.

`make_paper_data.py` refuses to write when a required field is absent, when
`primary_inputs` is empty, or when a listed input is not on disk. A broken
evidence chain becomes a failure at generation time rather than a plausible
number in a table.

Three rules the research side owns, because the writing side cannot check them:

1. **Equal coverage.** Compared methods must have the same conditions and the
   same repetition count. The generator checks that keys match; it cannot tell
   whether the runs were comparable.
2. **`values` is raw.** The `values` list must be the actual per-run results, not
   a resampled or smoothed series. Figure bands are drawn from it.
3. **One aggregate, one method.** Do not merge two methods into one aggregate to
   make a table shorter.

## 2. Readiness verdict

```json
{
  "verdict": "READY",
  "generated_at": "2026-08-27T00:00:00Z",
  "claims": [
    {
      "claim":       "random selection and max-error selection are indistinguishable",
      "scope":       "MNIST, reduced probe scale, 5 split seeds, 3 trajectories",
      "aggregates":  ["runs/aggregate__random.json", "runs/aggregate__maxerr.json"],
      "supported":   true,
      "notes":       "contrast 0.011 does not clear the 0.032 trajectory spread"
    }
  ],
  "blocked_on": []
}
```

`verdict` is `READY` or `BLOCKED`. Nothing else is accepted.

**The writing skill will not enter submission mode on a `BLOCKED` verdict.** It
will still draft, still compile a draft, and still run every gate; what it will
not do is emit `PAPER_READY` or run `build_paper.sh --final`. A blocked verdict
is a correct outcome, not an obstacle to route around.

When `verdict` is `BLOCKED`, `blocked_on` names what is missing, in the same
shape as a claim, so the research side can queue the smallest sufficient rerun.

## 3. Project config

The writing skill has no knowledge of a project's method names, venue, or
directory layout. That binding lives in one file, by default `paper.json` beside
the paper tree. See `config.example.json`.

```json
{
  "paper_dir": "paper",
  "venue":   {"name": "NeurIPS 2025", "max_main_pages": 9},
  "figures": {"distribution": {"series": [{"column": "random", "method": "random"}]}}
}
```

Adding a comparison arm is a config edit plus a table row, not a code change.

## 4. What each side may not do

**The research side may not** write LaTeX, edit anything under the paper tree,
or decide how a result is phrased.

**The writing side may not** run an experiment, edit an aggregate, relax a
readiness verdict, or fill a `\slot` from anything other than an aggregate. If a
number is needed and no aggregate carries it, the answer is to ask the research
side for it, not to compute it from what is at hand.

Both sides may read this file. Neither should need to read the other's code.
