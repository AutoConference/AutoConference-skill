# Equation grammar

How many numbered displays the method carries is the drawn `equations` register:
`none`, `sparse` (~4), `moderate` (5–8), `dense` (9–12), or `sectioned`
(section-prefixed numbers and an algorithm float). `DESIGN-BRIEF.md` states the
floor the gate enforces. The exemplar is `dense`: ten displays across three
method subsections and one more in the appendix.

Everything below is how a display is written **once the register calls for one**.
It applies unchanged to all five registers; with `none`, the method carries its
math inline and this file governs nothing but the appendix.

Measured from arXiv:2506.21656 (`sections/03_method.tex`).

## The narration sandwich

Every display equation sits inside three prose moves. This is the single most
important rule in this file, because an unnarrated equation is what makes a
method section unreadable.

```
1. Motivation sentence   what this quantity is, and why it is needed now
2. The display           numbered, labeled
3. `where` sentence      every new symbol defined, in order of appearance
4. Role sentence         what this equation does for the experiment or claim
```

Move 4 may merge into the `where` sentence for a definitional display, but it
cannot be dropped for an objective, an estimator, or a decision rule.

Worked shape:

```latex
To quantify how much of the bound's variation comes from the data split rather
than the optimization path, we decompose the observed bound for split $i$ and
trajectory $j$ into a split effect and a trajectory residual:
\begin{equation}\label{eq:decomposition}
  b_{ij} = \mu + \alpha_i + \varepsilon_{ij},
  \qquad
  \sum_i \alpha_i = 0,
\end{equation}
where $b_{ij}$ is the certified bound, $\mu$ the grand mean, $\alpha_i$ the
effect of split seed $i$, and $\varepsilon_{ij}$ the trajectory residual under a
fixed split. \Cref{eq:decomposition} is what makes a per-method contrast
meaningful: a difference smaller than the spread of $\varepsilon_{ij}$ is not
evidence about the method.
```

## Numbering and labeling

- Number every display that later prose refers to. An unreferenced numbered
  equation is either a missing reference or an unnecessary number.
- Label as `eq:<short-name>`, matching the concept, not the position.
- Reference with `\Cref{eq:...}`, which the preamble renders as `Eq. N`.
- Use `\begin{equation}` for a single display. Use `\begin{align}` only when the
  alignment carries meaning; a chain of three aligned lines with no interleaved
  prose is a derivation and belongs in the appendix.

## Symbol discipline

- Define a symbol once, at first use, and never redefine it.
- Bold vector and set objects with `\bm{...}`; keep scalars plain.
- Calligraphic for spaces and datasets: `\mathcal{D}`, `\mathcal{T}`.
- Subscript by role, not by index letter, when the role is the point:
  `\beta_{\text{desc}}` reads; `\beta_1` does not.
- Once a macro exists for a term in `paper/macros.tex`, prose uses the macro.
  The equation and the sentence around it must name the same object the same
  way.

## Inline versus display

Put the formulation's defining tuple inline so the method opens with reading:

```latex
Formally, an evaluation instance is a tuple
$\mathcal{T} = (\mathcal{S}, m, \tau) \xrightarrow{\;\pi\;} b$,
where $\mathcal{S}$ is the split, $m$ the selection method, $\tau$ the
trajectory seed, and $b$ the certified bound.
```

Reserve displays for objectives, estimators, decision rules, and any expression
the paper argues about. A quantity mentioned once belongs inline.

## Wide equations

When a display exceeds the text width, wrap it rather than shrinking the whole
document:

```latex
\begin{equation}\label{eq:objective}
\scalebox{0.99}{$
  \mathcal{L}(\theta) = -\mathbb{E}_{(x,y)\sim\mathcal{D}}
  \bigl[\log \sigma( \beta_1 f_1(x,y) + \beta_2 f_2(x,y) )\bigr],
$}
\end{equation}
```

Do not let an equation produce an overfull `\hbox`. Split it, introduce an
intermediate definition, or move the expanded form to the appendix.

## Spacing

The preamble already sets float and caption spacing. For equations:

- No blank line before `\begin{equation}` when the motivation sentence runs into
  it; a blank line starts a new paragraph and breaks the sandwich.
- Use `\qquad` to separate a display's main expression from a side condition.
- Avoid stacking two displays with no prose between them. If two equations must
  be adjacent, they are one display with `\qquad` or an `align`.

## Principles as a device

When a design choice needs justification that is argument rather than algebra,
the exemplar sets it as a labeled principle:

```latex
\vspace{.1cm}
\textbf{Principle 1}: \textit{One-sentence statement of the rule, in italics.}

Then a paragraph of evidence for why the rule holds, ending in the concrete
parameter or mechanism the rule produces.
```

Use this at most twice per paper. More than that and it becomes a template.

## Appendix math

Derivations, proofs, closed forms, and the full statistical procedure go to the
appendix. When a main-body statement is restated in the appendix, the statement
must match word for word; only the proof differs. A renamed variable or a
dropped case split between the two is a defect, not a stylistic choice.

## Gate checks

`check_paper_structure.py` enforces:

- at least as many numbered equations in the method as the drawn register's
  floor (`equation_floor` in `paper.json` → `design`);
- every `\begin{equation}` carries a `\label`;
- every equation label is referenced at least once;
- a `where` or `here` narration sentence follows each display within two lines;
- no two displays are adjacent with no prose between them.
