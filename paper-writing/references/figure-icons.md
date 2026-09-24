# Icons in structural figures

The system figure in all seven source papers is not boxes and arrows. It is
boxes and arrows **with icons**, and that is most of what separates a figure a
reader calls designed from one they call a flowchart. P1 puts a robot on the
policy model, a snowflake on the frozen reference and a flame on the trained
one. P7 draws four snowflakes, a flame beside the adapter it tunes, two circled
operators, and a legend in the corner that keys all of them.

This file is the vocabulary. `references/figure-ladder.md` still governs what a
figure is allowed to *claim*; nothing here changes that. An icon is a label, not
evidence.

## Where they come from

FontAwesome 5 Free, loaded by `template/preamble.tex`. Vector glyphs, embedded
in the PDF, recoloured from the palette's `ACIcon` token. No external asset, no
raster, no network fetch, nothing to redistribute separately.

The load is **guarded**. A TeX tree without `fontawesome5` still builds a
complete paper; every icon renders as nothing. A missing glyph is worth less
than a failed build.

**Version 5, not 6, and this is not a preference.** `fontawesome6` missed the
TeX Live 2025 freeze and is absent from arXiv's TeX tree, so a paper that loads
it compiles here and fails there. Version 5 is present. Do not "upgrade" this.

**Licence.** The glyphs reach the PDF through the font, and the font is SIL
Open Font License 1.1. Embedding an OFL font in a document carries no
attribution obligation, and the PDF is not a derivative of the font. The LaTeX
package itself is LPPL. Nothing has to be redistributed alongside the paper and
no credit line is required. (The CC BY 4.0 that Font Awesome also offers applies
to the raw SVG assets, which this route never touches.)

## The five roles

An overview grammar never names a glyph. It names a role, and the role is a
macro the design fills:

| Macro | Role | Drawn default |
|---|---|---|
| `\acIconInput` | what enters the system | `Database` |
| `\acIconModel` | the backbone every compared arm shares | `ProjectDiagram` |
| `\acIconMech` | the mechanism this paper contributes | `Cogs` |
| `\acIconOut` | what is produced and reported | `Crosshairs` |
| `\acIconEvid` | the statistics or evidence the mechanism reads | `ChartBar` |

`scripts/design_paper.py` draws all five (axis 17), each from its own random
stream, and writes them into `paper/design.tex`. Two roles never draw the same
glyph: the same icon twice in one figure reads as a link between two stages that
are not linked.

Two more exist because their meaning is conventional and a reader recognises
them before reading the legend:

| Macro | Meaning |
|---|---|
| `\acsnow` | not updated during training |
| `\acflame` | updated during training |

**These are a convention, not a requirement.** A snowflake and a flame are what
the literature happens to use for frozen and trained, and they are provided
because recognising them costs the reader nothing. They are not the only way to
say it and not every figure needs them: a paper with no training regime to
state should not carry a badge, and a paper whose distinction is something else
entirely — sampled versus exhaustive, online versus offline, public versus held
out — should say *that*, with whichever of the 935 glyphs says it, in an
`\aciconat{<colour>}{<Name>}` beside the stage it belongs to.

What is NOT negotiable is that the badge must be earned. Do not put a flame on
a stage because the figure looks emptier without one. If the paper never says
that stage is trained, the figure must not say it either.

## Changing one

If the drawn glyph is wrong for the paper's domain — a molecular-property paper
drew `Font` for its input — renew it **once**, in `paper/macros.tex`:

```latex
\renewcommand{\acIconInput}{Atom}
```

Nothing else changes. Every overview grammar reads the macro.

Pick from the role's column below. A name outside these lists fails
`check_paper_structure.py`.

## The lists

**935 names, in `references/figure-icons.verified.txt`.** That file is
generated, not curated: every icon in FontAwesome 5.15.4 whose metadata says it
ships a free *solid* glyph (1002 of them), compiled one document at a time,
with each name the package rejected deleted. The 67 that failed are almost all
`*Alt` variants the LaTeX package names differently.

An earlier version of this file carried 79 names I had picked by hand. That was
8% of what the font ships, and it is exactly why a writer could not find a glyph
that fitted and fell back on a bare box. **If a name is in that file, you may
use it.** The gate checks against the file, not against the role lists below.

### The role lists are the draw's taste, not your limit

`ICON_ROLES` in `scripts/design_paper.py` holds a curated subset per role, and
the draw picks from it so that an unfilled paper gets a sensible figure rather
than a random one. It is a starting point:

| role | pool | what the draw is reaching for |
|---|---|---|
| `input` | 37 | what enters: data, text, images, signal, people |
| `model` | 18 | the backbone every arm shares |
| `mech` | 35 | the operation this paper contributes |
| `out` | 15 | what is produced and reported |
| `evid` | 21 | the measurement the mechanism reads |

A pool is not "glyphs that render" — it is **glyphs that are defensible when
nobody checks**. It was pruned after a batch of six drew two figures that
misdescribed their own contribution: a **wand** (`Magic`) landed on a few-shot
segmentation method, and a **die** (`Random`) on a contrastive objective. A
wand on the card carrying the paper's contribution tells a reviewer the
mechanism is unexplained. `Burn` went for a different reason — it is a flame,
and `\acflame` already means *updated during training* in the same figure.

Also gone: hand tools and art supplies from `mech`; trophies, medals and
gavels from `out`, which on an output card read as a leaderboard brag rather
than as what the system produces; premises and consumer hardware from `model`.
The reasons are written out above `ICON_ROLES` in `scripts/design_paper.py`.

If the drawn glyph is not the right one for your paper, **change it**, and do
not feel bound by the role's pool — a paper about molecules should have an atom
on its input whatever the pool suggested, and a paper about audio should have a
waveform or a microphone. Pick from the 935.

## Glyphs no icon font has

Things the source figures draw that FontAwesome does not supply. Each is a
Tier C drawing: structure only, never a magnitude, never an image that does not
exist.

| Macro | Draws | Used for |
|---|---|---|
| `\actokens{6}` | a strip of six small squares | a representation, drawn instead of named |
| `\acgrid{5}` | a 5×5 checkered square | an attention or score matrix |
| `\acop{W}` | a circled letter | an operator, the way P7 keys its two concatenations |

A stage that **repeats** is the `acdeck` node style rather than a macro, because
an arrow has to be able to land on it. `mechanism-zoom` draws its module this
way, three offset cards under a `× N` tag, the way P7 marks its stacked block.
If the paper's module runs once, delete the two backing nodes and the tag.

`\acgrid` is the one to be careful with. It says "a matrix of scores happens
here" and nothing about their values. It must never be read as a heat map of
real numbers, and a caption must not invite that reading.

## What is deliberately absent

**Photographic thumbnails.** P1 puts a real photograph of a vehicle and a
flower inside its framework figure; P7 puts real video frames inside its
pipeline. We cannot, because no such imagery exists for a generated paper, and
`figure-ladder.md` forbids inventing it. The icon layer is the substitute, not
an equivalent.

**3D and isometric renders.** P7's point cloud and trajectory plot are Tier A
artwork from real geometry. Synthesising one would be publishing a fixture as a
result.

**A generated figure.** Not the same question as a generated icon, and the
answer is still no -- but one of the reasons first given here was wrong, and
the record is corrected rather than quietly fixed.

The claim was that "a system figure is mostly text, and small text is where
image models are least reliable". **That is no longer true.** Sivia
(github.com/exsinger-hub/Sivia, MIT) ships six worked scientific overviews,
every one of them `generated_conceptual_illustration`, and their small text,
inline math and label hierarchy are clean -- its DiffDock figure sets
$L_{conf} = CE(d(x,y), b)$ correctly beside molecular surface renders. Judged
on looks, those figures are better than anything this TikZ layer produces.

Two reasons survive, and they are the ones that decide it for an unattended
pipeline:

- **Cost per figure.** Each of those six was produced from a hand-written
  specification of **24,000 to 30,000 characters**. That is a human writing a
  short paper about a picture, once per picture.
- **Factual errors survive review.** Three of the six are still
  `draft_pending_review`, and AutoTool's open note is a routing defect -- "an
  extra arrowhead near Add to history makes its direction ambiguous" -- on a
  figure whose own prompt file shows it is on its **fifth draft**, opening with
  pixel surgery ("DELETE ONLY its lower segment from y=945 to y=968"). An arrow
  pointing at the wrong box is a factual error in the paper rather than a
  cosmetic one, and here it outlived four rounds of correction.

Add that the output cannot be reproduced from a seed the way every other axis
in this family can, and the route is wrong for a paper this pipeline generates
unattended. It is the *right* route for one hero figure with a human in the
loop, which is a different job than this skill does.

What Sivia is worth taking is its design discipline, which is backend-neutral
and applies to a TikZ figure unchanged -- see `references/figure-grammar.md`.

**A generated icon** is a fairer question, because an icon has no text in it, so
the strongest objection to a generated figure does not apply. It was asked for
directly, and here is the honest position:

- It is the *third* thing to try, not the first. The vocabulary is 935 glyphs
  and the earlier shortage was a curation mistake, not a real limit. Exhaust it
  before reaching further.
- The second thing is a second icon set. Lucide, Tabler, Phosphor and Material
  Symbols are MIT / ISC / Apache, need no attribution, are fetchable in bulk,
  and carry glyphs FontAwesome genuinely lacks (a real graphics-card icon, for
  one). They are SVG, so using them needs an SVG-to-TikZ conversion step; that
  is a real piece of work, not a configuration change. **Flaticon specifically
  does not work**: its free tier requires a visible attribution for every icon,
  which would put a credit line in every paper, and it has no bulk interface an
  agent could use without violating its terms.
- If it comes to generating: generate a *set* in one pass with one described
  style, never one icon at a time. Five glyphs generated separately do not share
  a line weight, a corner radius or a perspective, and the source papers' figures
  read as designed precisely because theirs do. Then vectorise, because the
  output is raster and the paper is not, and commit the result so the paper
  stays reproducible.

**Photographic thumbnails and 3D renders** remain out for a different reason
entirely: they need real imagery that does not exist, and inventing it is
fabrication rather than decoration.
