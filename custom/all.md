# Owner instructions — every research step (ODE–JEPA + SIGReg)

You are writing for AutoConference mode 2 (`owner_direction`) on Boyi’s kit.

## Primary materials (read these)

1. `research/ode-jepa/PAPER_BRIEF.md` — SIGReg+ODE-JEPA direction, official LeWM data only.
2. `research/ode-jepa/outputs/lewm_pusht/train_summary.json` — PushT train metrics.
3. `research/ode-jepa/outputs/lewm_pusht/plan_eval.json` — CEM/MPC planning numbers.
4. Project-store: `docs/ode-jepa-research.md`, `docs/ode-jepa-lewm-protocol-results.md`.

## Hard rules

- Primary seed arXiv:2603.19312 (LeWM); secondary ODEWorld 2607.27924 for ODE predictor inspiration. Cite; do not copy text.
- **Official LeWM / stable-worldmodel HDF5 only** for training and reported metrics. Never use synthetic / procedural trajectories for claims.
- Single loss: `L = L_JEPA + λ·SIGReg(Z)` with λ=0.1, M=1024. No JVP, no B0/B1/B2 ablations, no dyn-recon as primary, no stop-grad/EMA on SIGReg+pred path.
- Prior synthetic phase-1 (`outputs/phase1/`, archived configs) is **non-final** — say so if mentioned.
- Prefer study kind **computational**. Every printed main-result number must trace to `outputs/lewm_pusht/` (or the protocol results doc).
- GPU: only `AC_GPUS=0` (RTX 4060 Laptop).
