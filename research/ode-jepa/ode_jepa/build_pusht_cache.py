"""Build a fast local cache from official PushT HDF5 (still real LeWM data).

Writes downsampled uint8 windows + actions to a torch file for rapid epoch loops.
Never synthesizes trajectories.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as TF
from tqdm import tqdm

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ode_jepa.pusht_h5 import PushTH5Dataset, resolve_pusht_h5, verify_h5


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--max-episodes", type=int, default=2000)
    p.add_argument("--frameskip", type=int, default=5)
    p.add_argument("--seq-len", type=int, default=4)
    p.add_argument("--window-stride", type=int, default=20)
    p.add_argument("--image-size", type=int, default=96)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    h5 = resolve_pusht_h5()
    meta = verify_h5(h5)
    ds = PushTH5Dataset(
        h5,
        seq_len=args.seq_len,
        frameskip=args.frameskip,
        image_size=args.image_size,
        max_episodes=args.max_episodes,
        window_stride=args.window_stride,
    )
    out = Path(
        args.out
        or Path(h5).parent
        / f"pusht_cache_ep{args.max_episodes}_s{args.image_size}_fs{args.frameskip}.pt"
    )
    pixels = []
    actions = []
    for i in tqdm(range(len(ds)), desc="cache-official"):
        item = ds[i]
        # store uint8 CHW for compactness
        pix = (item["pixels"].clamp(0, 1) * 255.0).round().to(torch.uint8)
        pixels.append(pix)
        actions.append(item["action"].float())
    payload = {
        "pixels": torch.stack(pixels, dim=0),  # N,T,C,H,W uint8
        "action": torch.stack(actions, dim=0),
        "meta": {
            **meta,
            "max_episodes": args.max_episodes,
            "frameskip": args.frameskip,
            "seq_len": args.seq_len,
            "window_stride": args.window_stride,
            "image_size": args.image_size,
            "n_windows": len(pixels),
            "source": "official_lewm_pusht_expert_train",
            "synthetic": False,
        },
    }
    torch.save(payload, out)
    side = out.with_suffix(".json")
    with open(side, "w", encoding="utf-8") as f:
        json.dump(payload["meta"], f, indent=2)
    print(json.dumps({"out": str(out), **payload["meta"]}, indent=2))


if __name__ == "__main__":
    main()
