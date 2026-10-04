"""Training losses for B0 (JVP), B1 (JEPA), B2 (hybrid)."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import torch
import torch.nn.functional as F


def dyn_recon_loss(s_hat: torch.Tensor, s: torch.Tensor) -> torch.Tensor:
    """L_dyn-recon = ‖g_dyn(f_dyn(s; s_0); s_0) − s‖²."""
    return F.mse_loss(s_hat, s)


def jepa_loss(z_pred: torch.Tensor, z_target: torch.Tensor) -> torch.Tensor:
    """L_JEPA = ‖ẑ_T − sg(z_T)‖² (caller should stop-grad target)."""
    return F.mse_loss(z_pred, z_target)


def jepa_cosine(z_pred: torch.Tensor, z_target: torch.Tensor) -> torch.Tensor:
    """Optional cosine distance for logging."""
    p = F.normalize(z_pred.flatten(1), dim=-1)
    t = F.normalize(z_target.flatten(1), dim=-1)
    return (1.0 - (p * t).sum(dim=-1)).mean()


def finite_diff_jvp(
    f_dyn,
    s_t: torch.Tensor,
    s_0: torch.Tensor,
    s_dot: torch.Tensor,
    eps: float = 1e-3,
) -> torch.Tensor:
    """Approximate JVP of f_dyn w.r.t. s_t along s_dot via central differences.

    JVP ≈ (f(s + ε ṡ) − f(s − ε ṡ)) / (2ε)
    """
    # Normalize direction magnitude for numerical stability.
    scale = s_dot.norm(dim=-1, keepdim=True).clamp_min(1e-6)
    direction = s_dot / scale
    eps_t = eps
    z_pos = f_dyn(s_t + eps_t * direction, s_0)
    z_neg = f_dyn(s_t - eps_t * direction, s_0)
    return (z_pos - z_neg) / (2.0 * eps_t) * scale


def autograd_jvp(
    f_dyn,
    s_t: torch.Tensor,
    s_0: torch.Tensor,
    s_dot: torch.Tensor,
) -> torch.Tensor:
    """Exact JVP via torch.autograd.functional.jvp when available."""
    s_t = s_t.detach().requires_grad_(True)

    def fn(s: torch.Tensor) -> torch.Tensor:
        return f_dyn(s, s_0)

    try:
        _, jvp_out = torch.autograd.functional.jvp(fn, (s_t,), (s_dot,), create_graph=False)
        return jvp_out
    except Exception:
        return finite_diff_jvp(f_dyn, s_t.detach(), s_0, s_dot)


def jvp_velocity_loss(
    v_pred: torch.Tensor,
    jvp_target: torch.Tensor,
) -> torch.Tensor:
    """L_v = ‖v_θ(z_t, τ; …) − sg(JVP)‖²."""
    return F.mse_loss(v_pred, jvp_target)


def estimate_s_dot_central(s: torch.Tensor, dt: float = 1.0) -> torch.Tensor:
    """Central finite-diff velocity along time for (B, T, D) features.

    Endpoints use forward/backward differences.
    """
    b, t, d = s.shape
    s_dot = torch.zeros_like(s)
    if t == 1:
        return s_dot
    s_dot[:, 1:-1] = (s[:, 2:] - s[:, :-2]) / (2.0 * dt)
    s_dot[:, 0] = (s[:, 1] - s[:, 0]) / dt
    s_dot[:, -1] = (s[:, -1] - s[:, -2]) / dt
    return s_dot


def compute_losses(
    model,
    s: torch.Tensor,
    *,
    ablation: str = "b1",
    lambda_rec: float = 1.0,
    lambda_jepa: float = 1.0,
    lambda_v: float = 1.0,
    jvp_mode: str = "finite_diff",
    cond: Optional[torch.Tensor] = None,
) -> Tuple[torch.Tensor, Dict[str, float]]:
    """Compute weighted loss for one batch of latent feature sequences.

    Args:
        model: ODEJEPAModel
        s: (B, T, D) observation features (from frozen DINO / stub)
        ablation: ``b0`` | ``b1`` | ``b2``
    """
    ablation = ablation.lower()
    b, t, d = s.shape
    device = s.device
    s_0 = s[:, 0]
    z = model.dynamics_encode(s, s_0)  # (B, T, Z)
    s_hat = model.dynamics_decode(z, s_0)
    l_rec = dyn_recon_loss(s_hat, s)

    logs: Dict[str, float] = {"loss/rec": float(l_rec.detach())}
    total = lambda_rec * l_rec

    # Target index T-1 (end of fragment); τ = (T-1)/(T-1) = 1 when T>1 else 0.
    t_idx = t - 1
    tau_end = torch.ones(b, device=device, dtype=s.dtype) if t > 1 else torch.zeros(b, device=device, dtype=s.dtype)
    z_0 = z[:, 0]
    z_T = z[:, t_idx]
    z_hat_T = model.predict_latent(z_0, tau_end, c=cond)

    if ablation in ("b1", "b2"):
        l_jepa = jepa_loss(z_hat_T, z_T.detach())
        total = total + lambda_jepa * l_jepa
        logs["loss/jepa"] = float(l_jepa.detach())
        logs["loss/jepa_cos"] = float(jepa_cosine(z_hat_T.detach(), z_T.detach()).detach())

    if ablation in ("b0", "b2"):
        # Sample a mid timestep for velocity supervision.
        mid = max(t // 2, 0)
        tau_mid = torch.full(
            (b,),
            float(mid) / float(max(t - 1, 1)),
            device=device,
            dtype=s.dtype,
        )
        s_dot = estimate_s_dot_central(s.detach())[:, mid]
        s_mid = s[:, mid]
        if jvp_mode == "autograd":
            jvp_tgt = autograd_jvp(model.f_dyn, s_mid, s_0, s_dot)
        else:
            jvp_tgt = finite_diff_jvp(model.f_dyn, s_mid, s_0, s_dot)
        jvp_tgt = jvp_tgt.detach()
        v_pred = model.velocity(z[:, mid], tau_mid, z_0, cond)
        l_v = jvp_velocity_loss(v_pred, jvp_tgt)
        total = total + lambda_v * l_v
        logs["loss/jvp"] = float(l_v.detach())

    logs["loss/total"] = float(total.detach())
    return total, logs
