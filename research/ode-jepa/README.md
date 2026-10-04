# ODE–JEPA + SIGReg

Action-conditioned **ODE-integrated JEPA** with LeWM’s **SIGReg** anti-collapse regularizer, trained and evaluated on **official LeWM / stable-worldmodel PushT HDF5 only**.

- Primary seed: [LeWM, arXiv:2603.19312](https://arxiv.org/abs/2603.19312) · code [`third_party/le-wm`](https://github.com/lucas-maes/le-wm)
- Secondary: [ODEWorld, arXiv:2607.27924](https://arxiv.org/abs/2607.27924) (ODE predictor)
- Default config: `configs/lewm_pusht_ode_jepa.yaml`
- Brief: `PAPER_BRIEF.md`

**Loss (single recipe):** `L = L_JEPA + λ · SIGReg(Z)` with `λ=0.1`, `M=1024`.  
No JVP, no B0/B1/B2 ablations, no dyn-recon as primary, no stop-grad/EMA on the SIGReg+pred path.  
**No synthetic training data** for reported metrics.

## Layout

```text
ode-jepa/
├── configs/lewm_pusht_ode_jepa.yaml   # default (official HDF5)
├── configs/archive/phase1_synthetic/  # NON-FINAL scaffold ablations
├── ode_jepa/                          # SIGReg, ODE-JEPA, PushT HDF5, train/eval
├── third_party/le-wm/                 # vendored LeWM
├── scripts/download_pusht.ps1
└── outputs/lewm_pusht/                # train curves + planning eval
```

## Install (conda env `ode-jepa`)

```powershell
$py = "$env:USERPROFILE\.conda\envs\ode-jepa\python.exe"
& $py -m pip install -r requirements.txt
& $py -m pip install "stable-worldmodel[train,env]" stable-pretraining h5py zstandard huggingface_hub
```

## Data

```powershell
$env:STABLEWM_HOME = "C:\Users\LiBoyi\Desktop\Folders\autoconference\research\ode-jepa\data\stable-wm"
.\scripts\download_pusht.ps1
# verifies pusht_expert_train.h5 size + HDF5 magic
```

## Train (~10 epochs)

```powershell
$env:STABLEWM_HOME = "...\research\ode-jepa\data\stable-wm"
$py = "$env:USERPROFILE\.conda\envs\ode-jepa\python.exe"
& $py -m ode_jepa.train_lewm_ode --config configs\lewm_pusht_ode_jepa.yaml
# OOM → reduce batch only, e.g. --batch-size 16
```

## Plan eval (CEM)

```powershell
& $py -m ode_jepa.plan_eval_pusht --config configs\lewm_pusht_ode_jepa.yaml --ckpt outputs\lewm_pusht\ode_jepa_sigreg_last.pt
```

## Non-final synthetic phase-1

Archived under `configs/archive/phase1_synthetic/` and `outputs/phase1/`. Do not use for paper claims.
