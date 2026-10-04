# ODE–JEPA + SIGReg — LeWM PushT Protocol Results

**Status:** PushT end-to-end complete (official HDF5)  
**Date:** 2026-10-04  
**Machine:** boyi-pc · RTX 4060 Laptop · conda env `ode-jepa` (torch cu124)  
**Code:** `research/ode-jepa/`  
**Config:** `configs/lewm_pusht_ode_jepa.yaml`

## Protocol

| Item | Value |
|------|-------|
| Loss | `L = L_JEPA + λ·SIGReg(Z)`, λ=0.1, M=1024 |
| Predictor | action-conditioned ODESolve of `v_θ` |
| Data | Official HF `quentinll/lewm-pusht` → `pusht_expert_train.h5` |
| Stop-grad / EMA | **none** on SIGReg+pred path |
| JVP / B0–B2 / dyn-recon primary | **not used** |
| Synthetic data | **forbidden** for reported metrics |

### Data verification

| Field | Value |
|-------|-------|
| `STABLEWM_HOME` | `research/ode-jepa/data/stable-wm` |
| File | `pusht_expert_train.h5` |
| Size | 46,300,921,856 bytes (46.301 GB) |
| SHA256 | `b6ebd9ac94bbe9e383f6e7a9cd92d74e9aa665ea57b758ed3717b0ee7df8d4fb` |
| HDF5 magic | OK |
| Layout | flat `pixels`/`action` + `ep_offset`/`ep_len` (Blosc → `hdf5plugin`) |
| Episodes in file | 18,685 |
| Train subset this run | first **2,000** official episodes, window_stride=20, image_size=96 → 10,990 windows (cached from HDF5; **not synthetic**) |

Artifacts: `data/stable-wm/VERIFY.md`, `outputs/lewm_pusht/train_summary.json`.

## Training curves (10 epochs)

Device `cuda:0`, batch 32, **293 s** wall time on the official cached subset.

| Epoch | train `loss/total` | train `loss/jepa` | train `loss/sigreg` | val `loss/total` |
|------:|-------------------:|------------------:|--------------------:|-----------------:|
| 1 | 1.2868 | 2.28e-05 | 12.868 | 1.2624 |
| 2 | 1.2866 | 2.64e-08 | 12.866 | 1.2624 |
| 5 | 1.2866 | 7.26e-09 | 12.866 | 1.2624 |
| 10 | 1.2866 | 3.13e-09 | 12.866 | 1.2624 |

**Readout:** JEPA → ~0 by epoch 2; SIGReg plateaus ~12.86 (compact ConvEncoder does not reproduce LeWM ViT-tiny anti-collapse). Checkpoint: `outputs/lewm_pusht/ode_jepa_sigreg_last.pt`.

## Planning eval (CEM) — primary = real env

| Backend | Status | Success rate | Mean return | Notes |
|---------|--------|--------------|-------------|-------|
| **`gym_pusht/PushT-v0` pixels CEM** | ok | **0.0** (0/20) | 3.00 | Primary planning metric |
| HDF5 latent proxy | ok | 1.0 (20) | — | **Non-informative** under collapsed latents |

Source: `outputs/lewm_pusht/plan_eval.json` (`primary_backend=env`).

Env deps note: `pymunk==6.6.0` required (`pymunk` 7.x breaks gym-pusht: `Space.add_collision_handler`).

## Prior synthetic phase-1 — NON-FINAL

Archived: `configs/archive/phase1_synthetic/`, `outputs/phase1/`. Do not cite as main results.

## How to continue

1. Full 18,685-episode train: `data.max_episodes: null` (slow Blosc I/O; prefer Lance via `stable-worldmodel` or larger cache).
2. Replace ConvEncoder with LeWM ViT-tiny (`third_party/le-wm` + `stable_pretraining`); keep ODE predictor + λ=0.1 SIGReg until `loss/sigreg` decreases.
3. `pip install "stable-worldmodel[train,env]"` for `swm/PushT-v1` / LeWM `eval.py` parity; then cube / two-rooms / reacher from HF collection `quentinll/lewm`.
4. Re-run CEM after representations are non-degenerate.

## Paths

- Kit brief: `research/ode-jepa/PAPER_BRIEF.md`
- Train: `research/ode-jepa/outputs/lewm_pusht/train_summary.json`
- Eval: `research/ode-jepa/outputs/lewm_pusht/plan_eval.json`
- Store: `docs/ode-jepa-lewm-protocol-results.md`
