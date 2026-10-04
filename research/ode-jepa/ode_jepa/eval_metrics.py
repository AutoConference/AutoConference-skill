"""Evaluation metrics: recon proxies, smoothness, open-loop drift, collapse."""

from __future__ import annotations

from typing import Dict, Optional

import torch
import torch.nn.functional as F


def psnr(pred: torch.Tensor, target: torch.Tensor, max_val: float = 1.0) -> float:
    """Peak signal-to-noise ratio (image tensors in [0, max_val])."""
    mse = F.mse_loss(pred, target).clamp_min(1e-12)
    val = 20.0 * torch.log10(torch.tensor(max_val, device=pred.device)) - 10.0 * torch.log10(mse)
    return float(val.detach())


def lpips_stub(pred: torch.Tensor, target: torch.Tensor) -> float:
    """Placeholder LPIPS: MSE in a tiny random projection space.

    Replace with real ``lpips`` package when doing paper-quality eval.
    """
    b = pred.shape[0]
    p = pred.reshape(b, -1)
    t = target.reshape(b, -1)
    g = torch.Generator(device=pred.device)
    g.manual_seed(0)
    w = torch.randn(p.shape[-1], 64, generator=g, device=pred.device, dtype=pred.dtype)
    w = w / (w.norm(dim=0, keepdim=True) + 1e-8)
    return float(F.mse_loss(p @ w, t @ w).detach())


def feature_recon_mse(s_hat: torch.Tensor, s: torch.Tensor) -> float:
    """Reconstruction proxy in frozen-feature space."""
    return float(F.mse_loss(s_hat, s).detach())


def pixel_stub_mse(s_hat: torch.Tensor, s: torch.Tensor) -> float:
    """Pixel-stub recon: MSE after a fixed random projection of features.

    Stands in for decoded-pixel MSE when RAE ``g_obs`` is unavailable.
    """
    flat_hat = s_hat.reshape(-1, s_hat.shape[-1])
    flat = s.reshape(-1, s.shape[-1])
    g = torch.Generator(device=s.device)
    g.manual_seed(1)
    w = torch.randn(flat.shape[-1], 32, generator=g, device=s.device, dtype=s.dtype)
    w = w / (w.norm(dim=0, keepdim=True) + 1e-8)
    return float(F.mse_loss(flat_hat @ w, flat @ w).detach())


@torch.no_grad()
def latent_smoothness(z: torch.Tensor) -> Dict[str, float]:
    """Latent path smoothness proxies on (B, T, D) sequences.

    - path_length: mean L2 distance between consecutive latents
    - hf_energy: high-frequency energy via second differences
    - pca_path_proxy: path length in top-2 PCA plane of flattened traj
    """
    if z.dim() != 3 or z.shape[1] < 2:
        return {
            "smooth/path_length": 0.0,
            "smooth/hf_energy": 0.0,
            "smooth/pca_path_proxy": 0.0,
        }
    dz = z[:, 1:] - z[:, :-1]
    path = dz.norm(dim=-1).mean()
    if z.shape[1] >= 3:
        ddz = z[:, 2:] - 2 * z[:, 1:-1] + z[:, :-2]
        hf = (ddz.pow(2).mean()).sqrt()
    else:
        hf = torch.zeros((), device=z.device, dtype=z.dtype)

    # Cheap PCA path proxy: project centered traj onto top-2 SVD dirs of batch pool.
    b, t, d = z.shape
    flat = z.reshape(b * t, d)
    mean = flat.mean(dim=0, keepdim=True)
    x = flat - mean
    # Economy SVD on a subsample for stability.
    n = min(x.shape[0], 256)
    xs = x[:n]
    try:
        _, _, vh = torch.linalg.svd(xs, full_matrices=False)
        basis = vh[:2].T  # (D, 2)
        proj = (z - mean.view(1, 1, -1)) @ basis  # (B, T, 2)
        pca_path = (proj[:, 1:] - proj[:, :-1]).norm(dim=-1).mean()
    except Exception:
        pca_path = path

    return {
        "smooth/path_length": float(path),
        "smooth/hf_energy": float(hf),
        "smooth/pca_path_proxy": float(pca_path),
    }


@torch.no_grad()
def open_loop_drift(
    z_gt: torch.Tensor,
    z_roll: torch.Tensor,
) -> Dict[str, float]:
    """Open-loop rollout drift vs GT latent path.

    Args:
        z_gt: (B, T, D) encoder latents
        z_roll: (B, T, D) ODE-integrated latents from z_0
    """
    mse_t = (z_roll - z_gt).pow(2).mean(dim=-1)  # (B, T)
    # Normalize by latent scale
    scale = z_gt.pow(2).mean().clamp_min(1e-12)
    rel = mse_t.mean() / scale
    end = mse_t[:, -1].mean()
    mid = mse_t[:, mse_t.shape[1] // 2].mean() if mse_t.shape[1] > 1 else end
    # Cumulative growth: end / (first-step + eps)
    first = mse_t[:, 1].mean() if mse_t.shape[1] > 1 else end
    growth = end / first.clamp_min(1e-12)
    return {
        "drift/mse_mean": float(mse_t.mean()),
        "drift/mse_mid": float(mid),
        "drift/mse_end": float(end),
        "drift/rel_mse": float(rel),
        "drift/growth": float(growth),
    }


@torch.no_grad()
def latent_variance(z: torch.Tensor, eps: float = 1e-8) -> Dict[str, float]:
    """Collapse diagnostic: variance of latents across batch/time.

    Args:
        z: (B, T, D) or (N, D)
    """
    if z.dim() == 3:
        z_flat = z.reshape(-1, z.shape[-1])
    else:
        z_flat = z
    var_per_dim = z_flat.var(dim=0, unbiased=False)
    return {
        "collapse/var_mean": float(var_per_dim.mean()),
        "collapse/var_min": float(var_per_dim.min()),
        "collapse/var_max": float(var_per_dim.max()),
        "collapse/active_frac": float((var_per_dim > eps).float().mean()),
    }


@torch.no_grad()
def pairwise_cosine_similarity(z: torch.Tensor, max_pairs: int = 256) -> Dict[str, float]:
    """Mean / std cosine sim of random latent pairs (high ⇒ collapse risk)."""
    if z.dim() == 3:
        z_flat = z.reshape(-1, z.shape[-1])
    else:
        z_flat = z
    n = z_flat.shape[0]
    if n < 2:
        return {"collapse/pair_cos_mean": 0.0, "collapse/pair_cos_std": 0.0}
    z_n = F.normalize(z_flat, dim=-1)
    g = torch.Generator(device=z.device)
    g.manual_seed(0)
    i = torch.randint(0, n, (max_pairs,), generator=g, device=z.device)
    j = torch.randint(0, n, (max_pairs,), generator=g, device=z.device)
    same = i == j
    if same.any():
        j = torch.where(same, (j + 1) % n, j)
    cos = (z_n[i] * z_n[j]).sum(dim=-1)
    return {
        "collapse/pair_cos_mean": float(cos.mean()),
        "collapse/pair_cos_std": float(cos.std(unbiased=False)),
    }


@torch.no_grad()
def predictor_encoder_degeneracy(z_pred: torch.Tensor, z_enc: torch.Tensor) -> Dict[str, float]:
    """How aligned predicted vs encoded latents are (identity collapse check)."""
    p = F.normalize(z_pred.reshape(z_pred.shape[0], -1), dim=-1)
    e = F.normalize(z_enc.reshape(z_enc.shape[0], -1), dim=-1)
    cos = (p * e).sum(dim=-1)
    return {
        "collapse/pred_enc_cos": float(cos.mean()),
        "collapse/pred_enc_mse": float(F.mse_loss(z_pred, z_enc)),
    }


@torch.no_grad()
def rollout_latents(model, z_0: torch.Tensor, t: int) -> torch.Tensor:
    """Open-loop ODE rollout from z_0 to T frames at uniform τ."""
    device = z_0.device
    dtype = z_0.dtype
    b = z_0.shape[0]
    zs = [z_0]
    for ti in range(1, t):
        tau = torch.full((b,), float(ti) / float(max(t - 1, 1)), device=device, dtype=dtype)
        zs.append(model.predict_latent(z_0, tau, c=None))
    return torch.stack(zs, dim=1)


@torch.no_grad()
def evaluate_batch(
    frames_pred: Optional[torch.Tensor],
    frames_gt: Optional[torch.Tensor],
    z: torch.Tensor,
    z_pred: Optional[torch.Tensor] = None,
    z_tgt: Optional[torch.Tensor] = None,
    s_hat: Optional[torch.Tensor] = None,
    s: Optional[torch.Tensor] = None,
    z_roll: Optional[torch.Tensor] = None,
) -> Dict[str, float]:
    """Aggregate metrics for one eval batch."""
    out: Dict[str, float] = {}
    out.update(latent_variance(z))
    out.update(pairwise_cosine_similarity(z))
    out.update(latent_smoothness(z))
    if frames_pred is not None and frames_gt is not None:
        out["psnr"] = psnr(frames_pred, frames_gt)
        out["lpips_stub"] = lpips_stub(frames_pred, frames_gt)
    if s_hat is not None and s is not None:
        out["recon/feature_mse"] = feature_recon_mse(s_hat, s)
        out["recon/pixel_stub_mse"] = pixel_stub_mse(s_hat, s)
        # Feature-space PSNR proxy (treat features as signal in [approx range])
        out["recon/feature_psnr_proxy"] = psnr(
            (s_hat - s_hat.min()) / (s_hat.max() - s_hat.min() + 1e-8),
            (s - s.min()) / (s.max() - s.min() + 1e-8),
        )
    if z_pred is not None and z_tgt is not None:
        out.update(predictor_encoder_degeneracy(z_pred, z_tgt))
    if z_roll is not None:
        out.update(open_loop_drift(z, z_roll))
    return out


@torch.no_grad()
def evaluate_model(model, frames: torch.Tensor) -> Dict[str, float]:
    """Full phase-1 eval on a video batch (B, T, C, H, W)."""
    model.eval()
    s = model.encode_frames(frames)
    s0 = s[:, 0]
    z = model.dynamics_encode(s, s0)
    s_hat = model.dynamics_decode(z, s0)
    b, t, _ = z.shape
    tau_end = torch.ones(b, device=frames.device, dtype=frames.dtype)
    z_hat_T = model.predict_latent(z[:, 0], tau_end, c=None)
    z_roll = rollout_latents(model, z[:, 0], t)
    return evaluate_batch(
        None,
        None,
        z,
        z_pred=z_hat_T,
        z_tgt=z[:, -1],
        s_hat=s_hat,
        s=s,
        z_roll=z_roll,
    )
