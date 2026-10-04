"""Train ODE–JEPA + SIGReg on official PushT HDF5 only.

Refuses synthetic / missing data. Default loss: L = L_JEPA + λ SIGReg(Z).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import torch
from torch.utils.data import DataLoader, random_split
from tqdm import tqdm

from ode_jepa.ode_jepa_sigreg import ODEJEPASigReg
from ode_jepa.pusht_h5 import resolve_pusht_h5, verify_h5


def load_config(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def set_seed(seed: int) -> None:
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def train(cfg: Dict[str, Any], config_path: Optional[str] = None) -> Dict[str, Any]:
    # Hard refuse synthetic
    if cfg.get("data", {}).get("allow_synthetic", False):
        raise RuntimeError("allow_synthetic is forbidden for official LeWM protocol runs.")
    if str(cfg.get("data", {}).get("source", "")).lower() in {"synthetic", "blob", "procedural"}:
        raise RuntimeError("Synthetic data sources are forbidden.")

    set_seed(int(cfg.get("seed", 0)))
    device = torch.device(cfg.get("device", "cuda" if torch.cuda.is_available() else "cpu"))
    dcfg = cfg["data"]
    tcfg = cfg["train"]
    mcfg = cfg["model"]
    lcfg = cfg["loss"]

    h5_name = dcfg.get("dataset_name", "pusht_expert_train")
    h5_path = Path(dcfg["h5_path"]) if dcfg.get("h5_path") else resolve_pusht_h5(h5_name)
    meta = verify_h5(h5_path, min_bytes=int(dcfg.get("min_bytes", 100_000_000)))
    print(f"[train] official HDF5 ok: {meta}")

    history = int(mcfg.get("history_size", 3))
    num_preds = int(mcfg.get("num_preds", 1))
    seq_len = history + num_preds

    from ode_jepa.pusht_h5 import PushTH5Dataset

    ds = PushTH5Dataset(
        h5_path,
        seq_len=seq_len,
        frameskip=int(dcfg.get("frameskip", 5)),
        image_size=int(mcfg.get("image_size", 96)),
        max_episodes=dcfg.get("max_episodes"),
        window_stride=dcfg.get("window_stride"),
    )
    # Infer action dim from one sample
    sample = ds[0]
    action_dim = int(sample["action"].shape[-1])
    print(f"[train] windows={len(ds)} action_dim={action_dim} seq_len={seq_len}")

    n_val = max(1, int(len(ds) * float(dcfg.get("val_frac", 0.1))))
    n_train = len(ds) - n_val
    train_ds, val_ds = random_split(
        ds, [n_train, n_val], generator=torch.Generator().manual_seed(int(cfg.get("seed", 0)))
    )
    bs = int(tcfg.get("batch_size", 32))
    train_loader = DataLoader(
        train_ds, batch_size=bs, shuffle=True, num_workers=int(tcfg.get("num_workers", 0)),
        drop_last=True, pin_memory=device.type == "cuda",
    )
    val_loader = DataLoader(
        val_ds, batch_size=bs, shuffle=False, num_workers=0, drop_last=False,
    )

    model = ODEJEPASigReg(
        embed_dim=int(mcfg.get("embed_dim", 192)),
        action_dim=action_dim,
        image_size=int(mcfg.get("image_size", 96)),
        ode_steps=int(mcfg.get("ode_steps", 4)),
        hidden=int(mcfg.get("hidden", 512)),
        history_size=history,
        sigreg_knots=int(lcfg.get("sigreg_knots", 17)),
        sigreg_num_proj=int(lcfg.get("sigreg_num_proj", 1024)),
        lambda_sigreg=float(lcfg.get("lambda_sigreg", 0.1)),
    ).to(device)

    opt = torch.optim.AdamW(
        model.parameters(),
        lr=float(tcfg.get("lr", 5e-5)),
        weight_decay=float(tcfg.get("weight_decay", 1e-3)),
    )

    epochs = int(tcfg.get("max_epochs", 10))
    out_dir = Path(tcfg.get("output_dir", "outputs/lewm_pusht"))
    out_dir.mkdir(parents=True, exist_ok=True)
    history_logs: List[Dict[str, Any]] = []
    t0 = time.time()
    global_step = 0

    print(
        f"[train] ODE-JEPA+SIGReg device={device} epochs={epochs} bs={bs} "
        f"lambda={model.lambda_sigreg} M={model.sigreg.num_proj}"
    )
    if config_path:
        print(f"[train] config={config_path}")

    for epoch in range(epochs):
        model.train()
        epoch_losses: List[Dict[str, float]] = []
        pbar = tqdm(train_loader, desc=f"epoch {epoch+1}/{epochs}")
        for batch in pbar:
            pixels = batch["pixels"].to(device)
            action = batch["action"].to(device)
            loss, logs = model.forward_loss(
                pixels, action, history_size=history, num_preds=num_preds
            )
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), float(tcfg.get("grad_clip", 1.0)))
            opt.step()
            epoch_losses.append(logs)
            global_step += 1
            pbar.set_postfix({k: f"{v:.4f}" for k, v in logs.items()})

        def _mean(xs: List[Dict[str, float]]) -> Dict[str, float]:
            if not xs:
                return {}
            keys = xs[0].keys()
            return {k: float(sum(d[k] for d in xs) / len(xs)) for k in keys}

        train_mean = _mean(epoch_losses)

        model.eval()
        val_losses: List[Dict[str, float]] = []
        with torch.no_grad():
            for batch in val_loader:
                pixels = batch["pixels"].to(device)
                action = batch["action"].to(device)
                _, logs = model.forward_loss(
                    pixels, action, history_size=history, num_preds=num_preds
                )
                val_losses.append(logs)
        val_mean = _mean(val_losses)
        row = {
            "epoch": epoch + 1,
            "step": global_step,
            "train": train_mean,
            "val": val_mean,
            "seconds": round(time.time() - t0, 2),
        }
        history_logs.append(row)
        print(json.dumps(row))

        ckpt = {
            "model": model.state_dict(),
            "cfg": cfg,
            "epoch": epoch + 1,
            "action_dim": action_dim,
            "h5_meta": meta,
            "train": train_mean,
            "val": val_mean,
        }
        torch.save(ckpt, out_dir / f"ode_jepa_sigreg_epoch{epoch+1}.pt")
        torch.save(ckpt, out_dir / "ode_jepa_sigreg_last.pt")

        with open(out_dir / "train_history.json", "w", encoding="utf-8") as f:
            json.dump({"h5_meta": meta, "history": history_logs}, f, indent=2)

    summary = {
        "protocol": "ODE-JEPA+SIGReg on official pusht_expert_train HDF5",
        "h5_meta": meta,
        "epochs": epochs,
        "batch_size": bs,
        "device": str(device),
        "lambda_sigreg": model.lambda_sigreg,
        "sigreg_num_proj": model.sigreg.num_proj,
        "seconds": round(time.time() - t0, 2),
        "final_train": history_logs[-1]["train"] if history_logs else {},
        "final_val": history_logs[-1]["val"] if history_logs else {},
        "checkpoint": str(out_dir / "ode_jepa_sigreg_last.pt"),
        "history_path": str(out_dir / "train_history.json"),
        "note": "Phase-1 synthetic B0/B1/B2 numbers are non-final and not used here.",
    }
    with open(out_dir / "train_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    return summary


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ODE-JEPA+SIGReg trainer (official HDF5 only)")
    p.add_argument("--config", type=str, required=True)
    p.add_argument("--max-epochs", type=int, default=None)
    p.add_argument("--batch-size", type=int, default=None)
    p.add_argument("--device", type=str, default=None)
    p.add_argument("--output-dir", type=str, default=None)
    return p.parse_args(argv)


def main(argv: Optional[list] = None) -> None:
    args = parse_args(argv)
    cfg = load_config(args.config)
    if args.max_epochs is not None:
        cfg.setdefault("train", {})["max_epochs"] = args.max_epochs
    if args.batch_size is not None:
        cfg.setdefault("train", {})["batch_size"] = args.batch_size
    if args.device is not None:
        cfg["device"] = args.device
    if args.output_dir is not None:
        cfg.setdefault("train", {})["output_dir"] = args.output_dir
    train(cfg, config_path=args.config)


if __name__ == "__main__":
    main()
