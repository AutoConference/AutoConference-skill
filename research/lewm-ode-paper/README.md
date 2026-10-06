# ODEWorld paper

Conference-style writeup of **ODEWorld**: continuous latent dynamics
(ODE drop-in predictor) for LeWM-style JEPA world models.

Prior art with the same product string (Liu et al., arXiv:2607.27924) is
cited as related work; our method is the LeWM-stack drop-in.

## Build

```bash
cd research/lewm-ode-paper
latexmk -pdf main.tex
# or: pdflatex + bibtex + pdflatex ×2
```

Requires TeX Live with `ecai.cls` (vendored here) and `algorithm` / `algpseudocode`.

## Layout

| File | Content |
|------|---------|
| `main.tex` | Frontmatter + section inputs |
| `sec/0_abs.tex` … `sec/5_conclusion.tex` | Abstract → conclusion |
| `refs.bib` | Bibliography |
| `figs/` | Train loss curves (discrete + ODE) |
| `ecai.cls` | ECAI class |

## Length

Expanded manuscript targets **6–8 pages** (ECAI `ecai.cls`).

## Key claims (honest)

- Official PushT HF data; fixed 1k split seed 3072 (901/99).
- Discrete vs ODEWorld CEM both **5/93 (5.38%)**; ODEWorld lower loss 0.234/0.506 vs 0.248/0.536.
- Not paper-scale (~96% PushT); 1k subset limitation.
