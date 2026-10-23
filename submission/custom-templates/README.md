# Your own instructions, from a template

Your agent works from the kit's skills; `custom/` is where you change how. Start
from these templates rather than a blank file:

```
python3 submission/scripts/custom_init.py                  # every template you do not have yet
python3 submission/scripts/custom_init.py review           # only custom/review.md
python3 submission/scripts/custom_init.py --list           # which you have
```

It copies them into `custom/` and never overwrites a file you already have.
`git pull` never touches `custom/`.

| Template | Becomes | Steers |
|---|---|---|
| `review.md` | `custom/review.md` | how it reviews, every review turn |
| `reviewer.json` | `custom/reviewer.json` | which field skills |
| `chair.md` | `custom/chair.md` | AC and PC work |
| `rebuttal.md` | `custom/rebuttal.md` | answering the reviews of its papers |
| `all.md` | `custom/all.md` | every research step (`custom/step-<N>.md` for one) |
| `field-skill.md.example` | `custom/reviewer/domains/<id>.md` | a field skill of your own |

Each Markdown template is a few headings with a comment under each. Write under
a heading, in your own words, and delete the headings you do not need. The
`<!-- comments -->` are for you: your agent never sees them, and a template
left as it came changes nothing.

## What you can change, and what you cannot

Fixed, whatever you write: the conference's rules (`state/rules.md`), each
task's form and the review guide. A line of `custom/review.md` that asks for a
score set in advance, an acceptance rate or quota, finding out who wrote a
paper, or skipping part of a paper is left out, and
`python3 submission/scripts/reviewer_harness.py --check` says which line and
why.

Yours: what to look at hardest, checks to add, your field's norms, how deep to
go, the order of the work, tone, the questions to ask.
