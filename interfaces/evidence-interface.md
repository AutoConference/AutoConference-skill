# Evidence interface

The contract between whatever produces evidence and this writing skill, and
the chain the kit checks a paper's numbers along. The two sides are developed
independently, so this file is the only thing either needs to know about the
other.

## The chain

A number in a paper is believed because each link from the code that made it
to the page it is printed on was checked, by the tool fit for that link:

```
code ──(1)──▶ declared outputs ──(2)──▶ aggregates ──(3)──▶ the paper's numbers
     replay                      aggregation           provenance / evidence
     (step 10)                   replay (step 11a)     match (step 14)
```

1. **Code → declared outputs.** Each experiment in `runs/REPLAY_MANIFEST.json`
   names the script that ran it and the one output it writes. Step 10 re-runs
   every script in a clean copy and compares every number of that output
   (`exact`, `tolerant`, `timing`). A declared output is a summary of a run --
   its metrics, its settings -- at most 32 MiB; per-instance data
   (predictions, logits, per-example labels) goes in other files beside it.
   Those other files are the run's raw data: kept, attached with the research
   record, read by the code that summarises them -- and never read by a gate
   as evidence. A number that exists only among millions of raw values is not
   evidence of anything: almost any number can be found there.
2. **Declared outputs → aggregates.** `runs/aggregate.py` writes every
   `runs/aggregate__<method>.json` and `runs/DESIGN.json` from the declared
   outputs only, and is named in the manifest as its `aggregation`. Step 11a's
   gate re-runs it in a clean copy holding the code and the declared outputs as
   step 10 verified them, and nothing else under `runs/`; what it writes must
   equal what is there, number for number. An aggregate cannot carry a number
   its inputs do not produce.
3. **Aggregates → the paper.** Every number the paper prints comes from the
   evidence: the aggregates and `DESIGN.json` (verified by link 2), the
   declared outputs (verified by link 1), and this machine's description. The
   writer prints a value with `\ev{key}` (below), and the converter records
   where each came from; step 14 re-reads that field and checks the printed
   value. A number typed by hand must equal an evidence value -- of the metric
   the sentence names, when it names one -- or the paper goes back to be
   rewritten. Raw data is never searched.

The kit records what each gate verified (`.aris/evidence.json`: the hash of
every declared output, aggregate, `DESIGN.json`, `aggregate.py` and the
manifest), and step 14 refuses evidence that changed after it was verified.
Step 14 does not take that record's word for the aggregates: it re-runs link 2
itself, so an aggregate edited by hand -- its hash written into the record or
not -- is caught where the paper's numbers are checked. Every path the
manifest names stays inside the workspace (outputs inside `runs/`), and a
folder under `runs/` linked to another tree brings none of its files in. The
research record and the turns that wrote the paper are attached for the
committee, so what a gate cannot see -- a declared output edited together
with the gate's own record of it -- reviewers can.

```
research side                    interface                writing side
─────────────                    ─────────                ────────────
runs experiments      ──────▶    declared outputs         (never read)
keeps raw data        ──────▶    other files in runs/     (never read)
aggregates, by code   ──────▶    runs/aggregate__*.json   ──▶ \ev values, tables, figures
                                 runs/DESIGN.json         ──▶ \ev values (the design's parameters)
decides eligibility   ──────▶    readiness.json           ──▶ gate for --submission
```

## 1. Aggregate artifact

One file per method, or per compared configuration, written by
`runs/aggregate.py`. The writing side reads only these (and `DESIGN.json`), so
a number that is not in one cannot reach the paper.

```json
{
  "label":          "random-matrix",
  "method":         "random",
  "metric":         "p2l_bound",
  "estimator":      "mean over trajectory seeds, per split seed",
  "primary_inputs": ["runs/results/random-split1-traj0.json", "..."],
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
| `primary_inputs` | yes | Every declared output this aggregate combines, as paths. Each must be an experiment's `output` in the manifest |
| `per_split` | yes | Per-condition mean, std, `n`, and the raw `values` |
| `overall` | yes | Across-condition summary |
| `paired_contrast` | for the headline | Contrast, its uncertainty, and what it is against; `ci_low`/`ci_high` when the paper will print the contrast's interval |
| `per_split.*.ci_low`, `ci_high` | no | An interval for that condition's mean, when the research side computed one (a Wilson interval for a rate, say); `null` for an exact computation |

Any number the paper will print that is not a per-run result -- a difference,
a ratio, an interval endpoint, a percentage change -- is computed here, by
`aggregate.py`, as a field of an aggregate. The paper never computes one.

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

### The aggregation entry

```json
{"experiments": [...],
 "aggregation": {"script": "aggregate.py", "outputs": ["aggregate__*.json", "DESIGN.json"],
                 "timeout_s": 600}}
```

`outputs` are paths or `*` patterns relative to `runs/`. The script reads only
the experiments' declared outputs (it finds no other file under `runs/` in the
clean copy), and writes every output listed; every number of every output must
come out the same.

### DESIGN.json

The design's parameters the paper states -- sample sizes, horizons, noise
orders, the number of seeds -- as `aggregate.py` reads them from the declared
outputs, which record the settings each run used. A parameter the paper states
that no run recorded is not a parameter of this study.

## 2. Printing a number: `\ev`

`make_paper_data.py --evidence runs/aggregate__*.json runs/DESIGN.json` writes
`paper/data/evidence.tex` (the values), `paper/data/evidence.json` (each key's
file, field and value) and `paper/data/EVIDENCE.md` (the list, to read). Every
layout loads it. In the paper:

| Write | Prints |
|---|---|
| `\ev{random/overall/mean}` | the value: an integer as it is, any other number to 3 decimals |
| `\ev[2]{random/overall/mean}` | to 2 decimals (0-4) |
| `\evpct{random/overall/mean}` | times 100, to 1 decimal, for a percentage (`\evpct[0]` ... `\evpct[2]`) |

A key is the file (`random` for `aggregate__random.json`, `design` for
`DESIGN.json`) and the field's path, `/`-separated: `random/per_split/1/mean`,
`random/per_split/1/values/0`, `design/n_seeds`. An unknown key stops the
build: a value cannot be mistyped into the paper. Rounding is half up, from the
number as the file writes it; `-0.000` prints as `0.000`.

`make_submission.py` prints each `\ev` the same way and writes
`evidence-ledger.json` beside `submission.json`: for each printed value, its
key, file, field, precision, the text printed, and where it stands in the
paper (the abstract or the body, and the offset). Step 14 re-reads each field
from its file, which must be evidence the gates verified, checks the text,
and finds it at each place the ledger names. Only those places are vouched
for: the same digits typed anywhere else are checked like any typed number.

A number may still be typed by hand -- a count in a sentence, a value in a
table someone built by hand -- and is checked the old way, against the
evidence only. `\ev` is the way that cannot go wrong.

## 3. Readiness verdict

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

## 4. Project config

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

## 5. What each side may not do

**The research side may not** write LaTeX, edit anything under the paper tree,
decide how a result is phrased, or write an aggregate by hand: `aggregate.py`
writes them, and its gate re-runs it.

**The writing side may not** run an experiment, edit anything under `runs/`,
relax a readiness verdict, or print a number from anything other than the
evidence. If a number is needed and no aggregate carries it, the answer is to
ask the research side for it -- a field `aggregate.py` computes -- not to
compute it from what is at hand.

Both sides may read this file. Neither should need to read the other's code.

## 6. Papers begun before this chain (kit 0.17 and earlier)

A paper whose aggregates were written before the aggregation entry existed is
checked with what it has: its aggregates and `DESIGN.json` count as evidence,
unverified, and a number found only in a raw results file of at most 8 MiB is
reported as such, not failed. Its next paper uses the chain.
