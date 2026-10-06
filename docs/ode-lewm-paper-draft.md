# ODEWorld paper draft

**Title:** ODEWorld: Continuous Latent Dynamics for Visual World Modeling

**Kit path:** `research/lewm-ode-paper/`  
**PDF:** `research/lewm-ode-paper/main.pdf` (also mirrored at `docs/media/ode-lewm-paper.pdf`)

## Summary

Visual world models for control increasingly use JEPA-style next-embedding prediction with SIGReg and latent CEM planning. Most stacks still advance latent state with a **discrete autoregressive** map. **ODEWorld** replaces that step with an action-conditioned neural ODE integrated by fixed-step RK4 over \(\tau \in [0,1]\), keeping encoder, SIGReg, projectors, and CEM unchanged.

## PushT 1k results (seed 3072, 901/99 split)

| Method | fit/loss | val/loss | CEM val-99 |
|--------|----------|----------|------------|
| Discrete AR baseline | 0.248 | 0.536 | 5/93 (5.38%) |
| ODEWorld (RK4) | **0.234** | **0.506** | 5/93 (5.38%) |

Full-data prior work reports ~96% PushT success; our 1k subset is a controlled comparison, not a scale claim.

## Framing

- **Title / abstract / intro / method / conclusion:** ODEWorld-centric; no LeWM naming.
- **Related work:** LeWM cited as prior JEPA+SIGReg+CEM baseline where appropriate.
- **Experiments table:** “Discrete AR baseline” and “Prior full-data JEPA” with `\cite{maes2026lewm}` only.

## Build

```bash
cd research/lewm-ode-paper && latexmk -pdf main.tex
```

**Page count:** 7 (ECAI `ecai.cls`).
