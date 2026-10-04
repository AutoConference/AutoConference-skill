# ODE–JEPA Phase-1 Results

**Date:** 2026-10-04  
**Machine:** boyi-pc · `cuda:0` (NVIDIA GeForce RTX 4060 Laptop GPU)  
**Python:** `C:\Users\LiBoyi\.conda\envs\ode-jepa\python.exe` (torch 2.6.0+cu124)

## Data mode

**Synthetic stand-in for LIBERO subset** — LIBERO HDF5 is not present under checked paths (`third_party/ODEWorld/assets/data`, `D:\datasets\libero`, local `data/`), and the scaffold HDF5 loader is not wired. Protocol uses longer curved-blob RGB clips than smoke:

| Setting | Smoke | Phase-1 |
|---------|-------|---------|
| `seq_len` | 8 | **16** |
| `n_synthetic` | 64 | **256** |
| `max_steps` | 10–20 | **250** |
| `batch_size` | 4 | 8 |
| `ode_steps` | 4 | 8 |
| obs encoder | stub CNN (frozen) | stub CNN (frozen) |

Configs: `configs/phase1_b{0,1,2}_*.yaml`. Metrics JSON: `outputs/phase1/metrics_b{0,1,2}.json`.

## Comparison table (final eval)

| Metric | B0 (recon+JVP) | B1 (recon+JEPA) | B2 (hybrid) |
|--------|----------------|-----------------|-------------|
| Train steps | 250 | 250 | 250 |
| Wall time (s) | 73.3 | 94.3 | 95.5 |
| Final `loss/total` | 1.36e-06 | 1.35e-06 | 1.35e-06 |
| Final `loss/rec` | 1.36e-06 | 1.35e-06 | 1.35e-06 |
| Final `loss/jvp` | 1.29e-11 | — | 1.71e-11 |
| Final `loss/jepa` | — | 1.98e-10 | 1.84e-10 |
| **recon/feature_mse** | 1.47e-06 | 1.47e-06 | 1.47e-06 |
| **recon/pixel_stub_mse** | 1.52e-06 | 1.51e-06 | 1.51e-06 |
| recon/feature_psnr_proxy | 45.64 | 45.64 | 45.64 |
| **smooth/path_length** | 5.92e-05 | 5.66e-05 | 5.75e-05 |
| smooth/hf_energy | 5.93e-06 | 5.67e-06 | 5.77e-06 |
| smooth/pca_path_proxy | 1.81e-05 | 1.60e-05 | 1.68e-05 |
| **drift/mse_mean** | 1.49e-04 | 9.74e-05 | **6.69e-05** |
| drift/mse_end | 5.14e-04 | 3.21e-10 | 3.06e-10 |
| drift/rel_mse | 0.040 | 0.044 | **0.025** |
| drift/growth | **258.9** | 2.1e-04 | 2.6e-04 |
| collapse/var_mean | 3.27e-09 | 3.06e-09 | 3.14e-09 |
| collapse/active_frac | 0.047 | 0.039 | 0.040 |
| collapse/pair_cos_mean | 1.000 | 1.000 | 1.000 |
| **collapse/pred_enc_cos** | 0.938 | **1.000** | **1.000** |
| collapse/pred_enc_mse | 5.14e-04 | 3.21e-10 | 3.06e-10 |

## Readout (phase-1 synthetic)

1. **Losses stabilized** well before 250 steps (total loss ~1e-6 by ~step 40–50 for all ablations).
2. **All three show near-total latent collapse** on this stub protocol: `pair_cos ≈ 1`, `var_mean ~ 1e-9`, `active_frac < 0.05`. Likely driven by the frozen stub CNN + easy synthetic blobs, not a definitive LIBERO finding.
3. **B0 (JVP)** keeps lower predictor–encoder cosine (0.94) and much higher end-of-horizon open-loop drift / growth — JVP alone does not pin the integrated endpoint as tightly as JEPA.
4. **B1 (JEPA)** and **B2 (hybrid)** nearly eliminate end-frame drift (`drift/mse_end ~ 1e-10`) via endpoint alignment; **B2** has the best mean-path relative drift (`rel_mse = 0.025`).
5. Recon proxies are essentially tied across B0/B1/B2 (~1.47e-06 feature MSE).

## Artifacts

| File | Description |
|------|-------------|
| `outputs/phase1/metrics_b0.json` | Full B0 summary + metrics |
| `outputs/phase1/metrics_b1.json` | Full B1 summary + metrics |
| `outputs/phase1/metrics_b2.json` | Full B2 summary + metrics |
| `outputs/phase1/b{0,1,2}_phase1.pt` | Checkpoints |
| `outputs/phase1/results_table.md` | This table |

## Next (when LIBERO available)

1. Wire ODEWorld HDF5 loader; point `data.libero_root`.
2. Swap stub DINO for frozen DINOv2 + RAE decode for real PSNR/LPIPS on 16/64-frame clips.
3. Re-run B0/B1/B2; treat this synthetic table as scaffold sanity + metric plumbing only.
