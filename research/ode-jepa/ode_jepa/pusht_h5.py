"""Official LeWM / stable-worldmodel PushT HDF5 loader.

Only loads real ``pusht_expert_train`` (or compatible) HDF5 under STABLEWM_HOME.
Never synthesizes trajectories.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
from torch.utils.data import Dataset


def get_stablewm_home() -> Path:
    env = os.environ.get("STABLEWM_HOME")
    if env:
        return Path(env)
    return Path.home() / ".stable-wm"


def resolve_pusht_h5(name: str = "pusht_expert_train") -> Path:
    home = get_stablewm_home()
    candidates = [
        home / f"{name}.h5",
        home / f"{name}.hdf5",
        home / name / f"{name}.h5",
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError(
        f"Official PushT HDF5 not found under STABLEWM_HOME={home}. "
        f"Expected one of: {[str(c) for c in candidates]}. "
        "Download from Hugging Face (quentinll/lewm-pusht) and decompress; "
        "do NOT use synthetic data."
    )


def file_sha256(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def verify_h5(path: Path, min_bytes: int = 100_000_000) -> Dict[str, Any]:
    size = path.stat().st_size
    if size < min_bytes:
        raise RuntimeError(f"HDF5 too small ({size} bytes): {path}")
    # cheap header check
    with open(path, "rb") as f:
        magic = f.read(8)
    if magic != b"\x89HDF\r\n\x1a\n":
        raise RuntimeError(f"Not a valid HDF5 file (bad magic): {path}")
    return {"path": str(path), "size_bytes": size, "size_gb": round(size / 1e9, 3)}


def _as_float_img(x: np.ndarray) -> torch.Tensor:
    """Convert HWC/CHW uint8/float to float CHW in [0, 1]."""
    t = torch.as_tensor(np.asarray(x))
    if t.ndim == 2:
        t = t.unsqueeze(0).repeat(3, 1, 1)
    elif t.ndim == 3 and t.shape[-1] in (1, 3):
        t = t.permute(2, 0, 1)
    t = t.float()
    if t.max() > 1.5:
        t = t / 255.0
    return t.clamp(0, 1)


class PushTH5Dataset(Dataset):
    """Windowed trajectory dataset over official PushT expert HDF5.

    Supports common layouts used by stable-worldmodel / LeWM dumps:
    - groups per episode with datasets pixels/action
    - flat datasets with episode_ends / episode_index
    """

    def __init__(
        self,
        h5_path: str | Path,
        *,
        seq_len: int = 4,
        frameskip: int = 5,
        image_size: int = 96,
        max_episodes: Optional[int] = None,
        window_stride: Optional[int] = None,
    ) -> None:
        import h5py
        try:
            import hdf5plugin  # noqa: F401 — registers Blosc etc. for LeWM HDF5
        except ImportError as e:
            raise ImportError(
                "hdf5plugin is required to read LeWM PushT HDF5 (Blosc filter 32001). "
                "pip install hdf5plugin"
            ) from e

        self.h5_path = Path(h5_path)
        self.seq_len = int(seq_len)
        self.frameskip = int(frameskip)
        self.image_size = int(image_size)
        self.window_stride = window_stride
        self._file: Optional[Any] = None

        # Larger chunk cache speeds Blosc pixel reads on Windows.
        self._rdcc_nbytes = 512 * 1024 * 1024
        with h5py.File(self.h5_path, "r", rdcc_nbytes=self._rdcc_nbytes) as f:
            self._layout, self._index = self._build_index(f, max_episodes)

        if not self._index:
            raise RuntimeError(f"No usable windows in {self.h5_path}")

    def _build_index(
        self, f, max_episodes: Optional[int]
    ) -> Tuple[str, List[Tuple[Any, ...]]]:
        import h5py

        need = self.seq_len * self.frameskip
        index: List[Tuple[Any, ...]] = []

        # Layout A: top-level episode groups
        ep_keys = [k for k in f.keys() if isinstance(f[k], h5py.Group)]
        pixel_keys = {"pixels", "observation", "obs", "images", "image", "rgb"}
        action_keys = {"action", "actions"}

        if ep_keys and any(
            any(pk in f[k] for pk in pixel_keys) for k in ep_keys[: min(5, len(ep_keys))]
        ):
            if max_episodes is not None:
                ep_keys = ep_keys[: max_episodes]
            for ek in ep_keys:
                g = f[ek]
                pk = next((p for p in pixel_keys if p in g), None)
                ak = next((a for a in action_keys if a in g), None)
                if pk is None or ak is None:
                    continue
                n = int(g[pk].shape[0])
                for start in range(0, n - need, max(need // 2, 1)):
                    index.append(("ep", ek, pk, ak, start))
            return "episodes", index

        # Layout B: flat arrays + episode_ends / ep_offset+ep_len (LeWM PushT)
        pk = next((p for p in pixel_keys if p in f), None)
        ak = next((a for a in action_keys if a in f), None)
        if pk is not None and ak is not None and (
            "episode_ends" in f or "ends" in f or ("ep_offset" in f and "ep_len" in f)
        ):
            if "ep_offset" in f and "ep_len" in f:
                starts = np.asarray(f["ep_offset"]).reshape(-1)
                lengths = np.asarray(f["ep_len"]).reshape(-1)
                ends = starts + lengths
            else:
                ends = np.asarray(f["episode_ends"] if "episode_ends" in f else f["ends"]).reshape(-1)
                starts = np.concatenate([[0], ends[:-1]])
            n_eps = len(ends)
            if max_episodes is not None:
                n_eps = min(n_eps, max_episodes)
            step = int(self.window_stride) if self.window_stride is not None else max(need // 2, 1)
            for i in range(n_eps):
                s, e = int(starts[i]), int(ends[i])
                for start in range(s, max(s, e - need) + 1, step):
                    if start + need <= e:
                        index.append(("flat", pk, ak, start))
            return "flat", index

        # Layout C: data/demo_* as in robomimic-like
        if "data" in f and isinstance(f["data"], h5py.Group):
            demos = sorted(f["data"].keys())
            if max_episodes is not None:
                demos = demos[:max_episodes]
            for dk in demos:
                g = f["data"][dk]
                # nested obs
                if "obs" in g and "action" in g:
                    obs = g["obs"]
                    pk = next((p for p in ("agentview_image", "pixels", "image", "rgb") if p in obs), None)
                    if pk is None and len(obs.keys()) > 0:
                        # first image-like
                        for cand in obs.keys():
                            if len(obs[cand].shape) >= 3:
                                pk = cand
                                break
                    if pk is None:
                        continue
                    n = int(g["action"].shape[0])
                    for start in range(0, n - need, max(need // 2, 1)):
                        index.append(("robomimic", dk, pk, start))
            if index:
                return "robomimic", index

        raise RuntimeError(
            f"Unrecognized HDF5 layout at {self.h5_path}. Top keys: {list(f.keys())}"
        )

    def __len__(self) -> int:
        return len(self._index)

    def _hf(self):
        import h5py
        try:
            import hdf5plugin  # noqa: F401
        except ImportError:
            pass

        if self._file is None:
            self._file = h5py.File(
                self.h5_path, "r", rdcc_nbytes=getattr(self, "_rdcc_nbytes", 256 * 1024 * 1024)
            )
        return self._file

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        import torch.nn.functional as TF

        f = self._hf()
        item = self._index[idx]
        fs = self.frameskip
        T = self.seq_len
        span = (T - 1) * fs + 1

        if item[0] == "ep":
            _, ek, pk, ak, start = item
            g = f[ek]
            pix_np = np.asarray(g[pk][start : start + span : fs])
            act_np = np.asarray(g[ak][start : start + span : fs])
        elif item[0] == "flat":
            _, pk, ak, start = item
            pix_np = np.asarray(f[pk][start : start + span : fs])
            act_np = np.asarray(f[ak][start : start + span : fs])
        else:  # robomimic
            _, dk, pk, start = item
            g = f["data"][dk]
            pix_np = np.asarray(g["obs"][pk][start : start + span : fs])
            act_np = np.asarray(g["action"][start : start + span : fs])

        # pix_np: (T, H, W, C) or similar
        frames = [_as_float_img(pix_np[i]) for i in range(len(pix_np))]
        actions = [torch.as_tensor(np.asarray(act_np[i])).float().reshape(-1) for i in range(len(act_np))]
        pixels = torch.stack(frames, dim=0)
        action = torch.stack(actions, dim=0)
        if pixels.shape[-1] != self.image_size or pixels.shape[-2] != self.image_size:
            pixels = TF.interpolate(
                pixels,
                size=(self.image_size, self.image_size),
                mode="bilinear",
                align_corners=False,
            )
        return {"pixels": pixels, "action": action}

    def __del__(self):
        try:
            if self._file is not None:
                self._file.close()
        except Exception:
            pass
