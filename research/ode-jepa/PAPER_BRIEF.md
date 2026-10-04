# PAPER_BRIEF — ODE–JEPA + SIGReg (official LeWM data)

**For:** AutoConference mode-2 authoring loop (`AC_MODE=owner_direction`, `AC_AUTHOR=1`)  
**Primary seed:** [LeWorldModel (LeWM), arXiv:2603.19312](https://arxiv.org/abs/2603.19312)  
**Secondary:** [ODEWorld, arXiv:2607.27924](https://arxiv.org/abs/2607.27924) (ODE-integrated predictor)  
**Code:** `research/ode-jepa/`  
**Default config:** `configs/lewm_pusht_ode_jepa.yaml`  
**Owner docs:** Project store `docs/ode-jepa-research.md`, `docs/ode-jepa-lewm-protocol-results.md`

---

## Title / direction

**Working title:** *ODE–JEPA with SIGReg: Continuous Latent Prediction under Isotropic-Gaussian Regularization*

**Direction (`AC_DIRECTION`):** Train an action-conditioned **ODE-integrated JEPA** world model with the **single LeWM loss recipe** `L = L_JEPA + λ·SIGReg(Z)` (λ=0.1, M=1024) on **official LeWM / stable-worldmodel PushT HDF5 only** (`pusht_expert_train` under `$STABLEWM_HOME`). No synthetic trajectories for training or reported metrics. No JVP, no B0/B1/B2 ablations, no dyn-recon as primary, no stop-grad/EMA on the SIGReg+prediction path. Evaluate with LeWM-style CEM/MPC planning on the real PushT protocol.

---

## Method

| Module | Role | Trainable |
|--------|------|-----------|
| Encoder `f` | pixels → latent `z_t` | yes (end-to-end) |
| Action embedder | `a_t` → action embedding | yes |
| Velocity `v_θ(z, τ; z_0, a)` | ODE dynamics field | yes |
| ODESolve | integrate `v_θ` for next-latent prediction | — |
| SIGReg | isotropic-Gaussian regularizer on `Z` | — (statistic) |

**Single loss:**

```
L = L_JEPA + λ · SIGReg(Z)
λ = 0.1,  M = num_proj = 1024
```

- `L_JEPA`: MSE between ODE-predicted next embeddings and encoder embeddings (gradients flow through both; **no stop-grad / EMA**).
- `SIGReg(Z)`: Sketched Isotropic Gaussian Regularizer (LeWM / Epps–Pulley), applied to time-major latents.

Vendored reference: `third_party/le-wm` ([lucas-maes/le-wm](https://github.com/lucas-maes/le-wm)).

---

## Data (hard constraint)

- **Only** official Hugging Face LeWM PushT: `quentinll/lewm-pusht` → `pusht_expert_train.h5` under `%STABLEWM_HOME%`.
- Download helper: `scripts/download_pusht.ps1`.
- Missing data → download/decompress; **never fabricate** or fall back to synthetic blobs.
- Archived synthetic ablation YAMLs live under `configs/archive/phase1_synthetic/` and are **non-final**.

---

## Prior synthetic phase-1 (NON-FINAL)

Early scaffold runs under `outputs/phase1/` used curved-blob RGB + B0/B1/B2 (JVP/JEPA/hybrid). Those numbers validate metric plumbing only. **Do not cite them as main results.** Prefer PushT official-HDF5 curves + planning success in `docs/ode-jepa-lewm-protocol-results.md`.

---

## Experiments (committed slice)

1. Train PushT ~10 epochs (LeWM App. E scale); on OOM reduce **batch size only**.
2. CEM/MPC planning eval (LeWM protocol); report success rate on real env when deps allow, else document HDF5 latent proxy + continue-env steps.
3. Multi-env (cube / two-rooms / reacher) is follow-on — complete PushT end-to-end first.

---

## Authoring instructions for the loop

- Cite LeWM (2603.19312) as primary seed; ODEWorld (2607.27924) for continuous ODE prediction inspiration.
- Every printed main-result number must trace to `outputs/lewm_pusht/` or the protocol results doc.
- Human involvement: **substantial**.
- Allowed research tree: `C:\Users\LiBoyi\Desktop\Folders\autoconference\research\ode-jepa`
