# ODE–JEPA + SIGReg — Research Brief

**Status:** active (official LeWM PushT protocol)  
**Owner:** Boyi Li (`boyil2@illinois.edu`)  
**AutoConference agent:** [boyil-world-models](https://autoconference.ai/agents/boyil-world-models)  
**Primary seed:** [LeWM, arXiv:2603.19312](https://arxiv.org/abs/2603.19312)  
**Secondary:** [ODEWorld, arXiv:2607.27924](https://arxiv.org/abs/2607.27924)  
**Local kit:** `C:\Users\LiBoyi\Desktop\Folders\autoconference\research\ode-jepa\`

## 1. Goal

Train an **action-conditioned ODE-integrated JEPA** with LeWM’s **single loss recipe**

```
L = L_JEPA + λ · SIGReg(Z),   λ = 0.1,   M = 1024
```

on **official LeWM / stable-worldmodel HDF5** (`pusht_expert_train` under `%STABLEWM_HOME%`). Report PushT training curves and LeWM-protocol CEM/MPC planning success. No synthetic trajectories for training or reported metrics.

## 2. Architecture

| Module | Role | Trainable |
|--------|------|-----------|
| Encoder | pixels → `z_t` | yes |
| Action embedder | `a_t` → emb | yes |
| `v_θ(z, τ; z_0, a)` | ODE velocity | yes |
| ODESolve | next-latent prediction | — |
| SIGReg | isotropic-Gaussian regularizer | — |

No stop-grad / EMA on the SIGReg + prediction path. No JVP. No dyn-recon as primary. No B0/B1/B2 ablation suite.

## 3. Data (hard rule)

- Hugging Face: `quentinll/lewm-pusht` → `pusht_expert_train.h5.zst` → decompress to `%STABLEWM_HOME%\pusht_expert_train.h5`
- Default config: `configs/lewm_pusht_ode_jepa.yaml`
- Download: `scripts/download_pusht.ps1`
- Missing data → download; **never fabricate**

## 4. Prior synthetic phase-1 — NON-FINAL

Scaffold B0/B1/B2 runs on curved-blob RGB (`outputs/phase1/`, archived configs under `configs/archive/phase1_synthetic/`) are **not** main results. Mark any prior claims accordingly.

## 5. AutoConference (mode 2)

- `AC_MODE=owner_direction`
- `AC_AUTHOR=1`
- `AC_SEED_PAPER=2603.19312` (ODEWorld 2607.27924 secondary)
- `AC_GPUS=0`
- Human involvement: `substantial`

**Dashboard direction:**

> ODE–JEPA + SIGReg: action-conditioned ODESolve JEPA with L=L_JEPA+λ·SIGReg(Z) (λ=0.1, M=1024) on official LeWM PushT HDF5 only; LeWM CEM/MPC planning eval; no synthetic data, no JVP/B0–B2 ablations. See research/ode-jepa/PAPER_BRIEF.md.

## 6. Success bar

PushT official-HDF5 training curves + LeWM-protocol planning success documented in `docs/ode-jepa-lewm-protocol-results.md`. Multi-env (cube/two-rooms/reacher) is follow-on after PushT E2E.
