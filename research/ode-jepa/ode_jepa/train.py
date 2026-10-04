"""Legacy CLI trainer for archived B0/B1/B2 ablations.

WARNING: Synthetic fallback is DISABLED by default. Prefer
``python -m ode_jepa.train_lewm_ode --config configs/lewm_pusht_ode_jepa.yaml``
for official LeWM PushT HDF5 + SIGReg. Phase-1 synthetic numbers are non-final.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# Allow `python -m ode_jepa.train` and `python ode_jepa/train.py`
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import torch
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm

from ode_jepa.eval_metrics import evaluate_model
from ode_jepa.losses import compute_losses
from ode_jepa.models import build_model


def load_config(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class SyntheticSequences(Dataset):
    """Smooth synthetic RGB video clips (LIBERO stand-in for phase-1)."""

    def __init__(
        self,
        n_samples: int = 64,
        t: int = 8,
        image_size: int = 64,
        seed: int = 0,
    ) -> None:
        super().__init__()
        self.n_samples = n_samples
        self.t = t
        self.image_size = image_size
        g = torch.Generator().manual_seed(seed)
        self.base = torch.rand(n_samples, 3, generator=g)
        self.vel = (torch.rand(n_samples, 2, generator=g) - 0.5) * 0.12
        self.radius = 0.05 + 0.08 * torch.rand(n_samples, generator=g)
        self.phase = torch.rand(n_samples, generator=g) * 6.2832

    def __len__(self) -> int:
        return self.n_samples

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        h = w = self.image_size
        yy, xx = torch.meshgrid(
            torch.linspace(-1, 1, h),
            torch.linspace(-1, 1, w),
            indexing="ij",
        )
        frames = []
        bx, by = self.vel[idx]
        color = self.base[idx].view(3, 1, 1)
        rad = float(self.radius[idx])
        ph = float(self.phase[idx])
        for ti in range(self.t):
            # Mild curved motion so open-loop drift is informative.
            ang = ph + 0.15 * ti
            cx = float(bx) * ti + 0.25 * torch.sin(torch.tensor(ang)).item()
            cy = float(by) * ti + 0.25 * torch.cos(torch.tensor(ang)).item()
            blob = torch.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / max(rad, 1e-3))
            # Secondary dim blob for richer features.
            blob2 = torch.exp(-((xx + 0.4 * cx) ** 2 + (yy - 0.3 * cy) ** 2) / 0.12)
            img = color * blob.unsqueeze(0) + 0.35 * color.flip(0) * blob2.unsqueeze(0)
            img = img + 0.03 * torch.randn_like(img)
            frames.append(img.clamp(0, 1))
        video = torch.stack(frames, dim=0)  # (T, C, H, W)
        return {"frames": video, "tau_end": torch.tensor(1.0)}


def try_libero_loader(cfg: Dict[str, Any]) -> Optional[DataLoader]:
    """Return a LIBERO DataLoader if data path exists; else None."""
    data_cfg = cfg.get("data", {})
    root = data_cfg.get("libero_root") or data_cfg.get("root")
    if not root:
        return None
    root_p = Path(root)
    if not root_p.exists():
        return None
    # Full LIBERO HDF5 pipeline lives in third_party/ODEWorld; not wired yet.
    print(f"[train] LIBERO root found at {root_p}, but HDF5 loader not wired; using synthetic.")
    return None


def make_loader(cfg: Dict[str, Any], *, for_eval: bool = False) -> Tuple[DataLoader, str]:
    libero = try_libero_loader(cfg)
    if libero is not None:
        return libero, "libero"
    dcfg = cfg.get("data", {})
    # Refuse silent synthetic fallback unless explicitly opted in (archived configs only).
    if not bool(dcfg.get("allow_synthetic", False)):
        raise RuntimeError(
            "Synthetic data fallback is disabled. Use official LeWM HDF5 via "
            "`python -m ode_jepa.train_lewm_ode --config configs/lewm_pusht_ode_jepa.yaml`, "
            "or set data.allow_synthetic=true only for archived scaffold smoke tests "
            "(non-final; never for reported metrics)."
        )
    n = int(dcfg.get("n_synthetic_eval", 32) if for_eval else dcfg.get("n_synthetic", 64))
    seed = int(cfg.get("seed", 0)) + (999 if for_eval else 0)
    ds = SyntheticSequences(
        n_samples=n,
        t=int(dcfg.get("seq_len", 8)),
        image_size=int(cfg.get("model", {}).get("image_size", 64)),
        seed=seed,
    )
    bs = int(cfg.get("train", {}).get("batch_size", 4))
    if for_eval:
        bs = min(bs, n)
    loader = DataLoader(
        ds,
        batch_size=bs,
        shuffle=not for_eval,
        num_workers=0,
        drop_last=not for_eval,
    )
    return loader, "synthetic"


def set_seed(seed: int) -> None:
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _mean_dicts(dicts: List[Dict[str, float]]) -> Dict[str, float]:
    if not dicts:
        return {}
    keys = dicts[0].keys()
    out: Dict[str, float] = {}
    for k in keys:
        vals = [d[k] for d in dicts if k in d]
        out[k] = float(sum(vals) / max(len(vals), 1))
    return out


@torch.no_grad()
def run_eval(model, loader: DataLoader, device: torch.device, max_batches: int = 8) -> Dict[str, float]:
    model.eval()
    model.f_obs.eval()
    batches: List[Dict[str, float]] = []
    for i, batch in enumerate(loader):
        if i >= max_batches:
            break
        frames = batch["frames"].to(device)
        batches.append(evaluate_model(model, frames))
    return _mean_dicts(batches)


def train(cfg: Dict[str, Any], config_path: Optional[str] = None) -> Dict[str, Any]:
    set_seed(int(cfg.get("seed", 0)))
    device = torch.device(cfg.get("device", "cuda" if torch.cuda.is_available() else "cpu"))
    train_cfg = cfg.get("train", {})
    loss_cfg = cfg.get("loss", {})
    ablation = str(cfg.get("ablation", loss_cfg.get("ablation", "b1"))).lower()

    model = build_model(cfg).to(device)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(
        params,
        lr=float(train_cfg.get("lr", 1e-4)),
        weight_decay=float(train_cfg.get("weight_decay", 1e-4)),
    )

    loader, data_source = make_loader(cfg)
    eval_loader, _ = make_loader(cfg, for_eval=True)
    max_steps = int(train_cfg.get("max_steps", 20))
    log_every = int(train_cfg.get("log_every", 1))
    eval_every = int(train_cfg.get("eval_every", max(max_steps // 4, 50)))
    out_dir = Path(train_cfg.get("output_dir", "outputs/smoke"))
    out_dir.mkdir(parents=True, exist_ok=True)

    protocol_note = cfg.get(
        "protocol_note",
        "synthetic stand-in for LIBERO subset (HDF5 absent / loader unwired)",
    )
    print(f"[train] ablation={ablation} device={device} data={data_source} max_steps={max_steps}")
    print(f"[train] protocol={protocol_note}")
    if config_path:
        print(f"[train] config={config_path}")

    model.train()
    model.f_obs.eval()

    step = 0
    history: List[Dict[str, Any]] = []
    t0 = time.time()
    pbar = tqdm(total=max_steps, desc=f"{ablation}-phase1")
    while step < max_steps:
        for batch in loader:
            if step >= max_steps:
                break
            frames = batch["frames"].to(device)  # (B, T, C, H, W)
            with torch.no_grad():
                s = model.encode_frames(frames)
            loss, logs = compute_losses(
                model,
                s,
                ablation=ablation,
                lambda_rec=float(loss_cfg.get("lambda_rec", 1.0)),
                lambda_jepa=float(loss_cfg.get("lambda_jepa", 1.0)),
                lambda_v=float(loss_cfg.get("lambda_v", 1.0)),
                jvp_mode=str(loss_cfg.get("jvp_mode", "finite_diff")),
            )
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, float(train_cfg.get("grad_clip", 1.0)))
            opt.step()

            if step % log_every == 0:
                history.append({"step": step, **logs})
                pbar.set_postfix({k: f"{v:.4f}" for k, v in logs.items() if k.startswith("loss/")})

            if step > 0 and step % eval_every == 0:
                mid_metrics = run_eval(model, eval_loader, device)
                history.append({"step": step, "eval": True, **mid_metrics})
                model.train()
                model.f_obs.eval()

            step += 1
            pbar.update(1)
    pbar.close()

    # Final eval
    final_metrics = run_eval(model, eval_loader, device)
    model.train()

    ckpt_name = train_cfg.get("ckpt_name", f"{ablation}_phase1.pt")
    ckpt_path = out_dir / ckpt_name
    torch.save(
        {
            "model": model.state_dict(),
            "cfg": cfg,
            "step": step,
            "data_source": data_source,
            "final_metrics": final_metrics,
        },
        ckpt_path,
    )

    # Loss trajectory helpers for results table
    loss_keys = [k for k in (history[-1].keys() if history else []) if k.startswith("loss/")]
    first_losses = {k: history[0][k] for k in loss_keys} if history else {}
    last_train = next((h for h in reversed(history) if "eval" not in h), {})
    last_losses = {k: last_train[k] for k in loss_keys if k in last_train}

    summary = {
        "ablation": ablation,
        "steps": step,
        "device": str(device),
        "data_source": data_source,
        "protocol_note": protocol_note,
        "seq_len": int(cfg.get("data", {}).get("seq_len", 8)),
        "n_synthetic": int(cfg.get("data", {}).get("n_synthetic", 64)),
        "seconds": round(time.time() - t0, 3),
        "checkpoint": str(ckpt_path),
        "first_losses": first_losses,
        "last_losses": last_losses,
        "metrics": final_metrics,
        "history_tail": history[-5:] if history else [],
    }

    metrics_name = train_cfg.get("metrics_name", f"metrics_{ablation}.json")
    metrics_path = out_dir / metrics_name
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    summary_name = train_cfg.get("summary_name", f"{ablation}_phase1_summary.json")
    with open(out_dir / summary_name, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps({k: summary[k] for k in ("ablation", "steps", "device", "data_source", "seconds", "metrics")}, indent=2))
    print(f"[train] wrote {metrics_path}")
    return summary


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ODE-JEPA trainer (synthetic if no LIBERO)")
    p.add_argument("--config", type=str, required=True, help="Path to YAML config")
    p.add_argument("--max-steps", type=int, default=None, help="Override train.max_steps")
    p.add_argument("--device", type=str, default=None, help="cuda|cpu|cuda:0")
    p.add_argument("--output-dir", type=str, default=None, help="Override train.output_dir")
    return p.parse_args(argv)


def main(argv: Optional[list] = None) -> None:
    args = parse_args(argv)
    cfg = load_config(args.config)
    if args.max_steps is not None:
        cfg.setdefault("train", {})["max_steps"] = args.max_steps
    if args.device is not None:
        cfg["device"] = args.device
    if args.output_dir is not None:
        cfg.setdefault("train", {})["output_dir"] = args.output_dir
    train(cfg, config_path=args.config)


if __name__ == "__main__":
    main()
