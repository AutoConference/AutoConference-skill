# ODEWorld paper (ECAI-style)

LaTeX draft for **ODEWorld: Continuous Latent Dynamics for Visual World Modeling**.

## Build

```bash
cd research/lewm-ode-paper
latexmk -pdf main.tex
```

Output: `main.pdf`.

## Scope

Continuous ODE latent predictor (RK4 one-step) inside a JEPA + SIGReg + CEM
visual world model. PushT 1k matched comparison vs. discrete AR baseline.
