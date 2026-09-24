# Worked instance

A complete paper produced by the template in the parent directory, kept here as
proof that the contract is reachable rather than aspirational.

**Every number in it is synthetic.** The aggregates under `runs/` were written by
a fixed generator, not by an experiment, and the paper says so on its own front
page. It exists to demonstrate the machinery, not to report a result. The
bibliography is the one exception: all 41 entries were retrieved from the arXiv
API, so the citations are real papers with real metadata.

## What it demonstrates

| | |
|---|---:|
| Main body | 3229 words |
| Numbered equations, all narrated | 5 |
| Tables | 4, across 3 floats |
| Figures | 2 (one Tier B plot, one Tier C diagram) plus the page-1 teaser |
| Distinct citations | 41, against 41 bibliography entries, all resolved against arXiv |
| Pages | 14: main body 1–8, references 9–11, appendix 12–14 |
| `check_paper_structure.py --submission` | PASS, 0 errors, 0 issues |
| `check_prose_quality.py` | PASS, 0 errors |
| `build_paper.sh --final` | compiles; 0 open slots; no overfull box |
| `check_render.py` | PASS, 0 errors, against the compiled PDF |

The compiled result is `output/pdf/example-paper.pdf`.

It is also a demonstration of what the skill is *for*. The synthetic study was
designed to produce an honest null: the mean contrast between the two selection
methods is smaller than the largest within-split trajectory spread, and its sign
reverses at one split. The design rule in the method section therefore forbids
reporting a ranking, and the paper reports the contrast, the reversal, and the
null. A less disciplined write-up of the same 45 runs would have reported a
winner.

## Rebuilding it

From the repository root:

```bash
cd example
W=../paper-writing/scripts

python3 $W/make_paper_data.py --config paper.json --figure distribution runs/aggregate__*.json
python3 $W/make_paper_data.py --config paper.json --teaser runs/aggregate__*.json \
  --question "Does the selection method change the certified bound, once split and trajectory randomness are measured apart?" \
  --finding  "No. The mean contrast is smaller than the largest within-split trajectory spread, and its sign reverses at one split."

$W/build_paper.sh --paper-dir paper --final
$W/render_paper.sh --pdf output/pdf/paper.pdf
python3 $W/check_paper_structure.py --paper-dir paper --submission \
  --pdf output/pdf/paper.pdf --max-main-pages 9
python3 $W/check_prose_quality.py paper/
python3 $W/check_citations.py paper/references.bib
python3 $W/check_render.py output/pdf/paper.pdf
```

Delete `example/paper/data/bounds.dat` and rebuild to watch the figure ladder
work: the plot and the sentence that narrates it both disappear, and nothing is
left behind to mark their absence.
