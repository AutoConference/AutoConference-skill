# ODE-LeWM paper

Conference-style writeup of the ODE latent-dynamics predictor for LeWM-style JEPA world models.

## Build

```bash
cd research/lewm-ode-paper
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

Requires TeX Live with `ecai.cls` (vendored here from the kit's AGP template).

## Layout

| File | Content |
|------|---------|
| `main.tex` | Frontmatter + section inputs |
| `sec/0_abs.tex` … `sec/5_conclusion.tex` | Abstract → conclusion |
| `refs.bib` | Bibliography |
| `figs/` | Train loss curves (discrete + ODE) |
| `ecai.cls` | ECAI class |

## Key claims (honest)

- Official PushT HF data; fixed 1k split seed 3072 (901/99).
- Discrete vs ODE CEM both **5/93 (5.38%)**; ODE lower loss 0.234/0.506 vs 0.248/0.536.
- Not paper-scale (~96% PushT); 1k subset limitation.
