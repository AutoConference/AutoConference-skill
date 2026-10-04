"""Minimal ODE-JEPA model stubs inspired by ODEWorld (arXiv:2607.27924).

Frozen DINO is stubbed for smoke training; swap in real DINOv2 / RAE from
``third_party/ODEWorld`` when checkpoints and data are available.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


class FrozenDINOWrapper(nn.Module):
    """Frozen observation encoder stub: image -> feature ``s`` (B, D_s).

    When ``use_stub=True`` (default), applies a small frozen CNN-like MLP on
    flattened / pooled pixels so synthetic smoke trains need no HuggingFace
    weights. Set ``use_stub=False`` later and load real DINOv2.
    """

    def __init__(
        self,
        in_ch: int = 3,
        feat_dim: int = 768,
        image_size: int = 64,
        use_stub: bool = True,
    ) -> None:
        super().__init__()
        self.feat_dim = feat_dim
        self.image_size = image_size
        self.use_stub = use_stub
        # Lightweight spatial stem + projection (kept frozen).
        self.stem = nn.Sequential(
            nn.Conv2d(in_ch, 32, kernel_size=5, stride=2, padding=2),
            nn.GELU(),
            nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
            nn.GELU(),
            nn.AdaptiveAvgPool2d(1),
        )
        self.proj = nn.Linear(64, feat_dim)
        for p in self.parameters():
            p.requires_grad = False
        self.eval()

    def train(self, mode: bool = True):  # noqa: D401 — keep frozen
        return super().train(False)

    @torch.no_grad()
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (B, C, H, W) in [0, 1] or roughly normalized.
        Returns:
            s: (B, feat_dim)
        """
        h = self.stem(x).flatten(1)
        return self.proj(h)


class DynamicsEncoder(nn.Module):
    """``f_dyn(s_t; s_0) -> z_t`` with context conditioning."""

    def __init__(self, feat_dim: int = 768, latent_dim: int = 768, hidden: int = 1024) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(feat_dim * 2, hidden),
            nn.GELU(),
            nn.Linear(hidden, hidden),
            nn.GELU(),
            nn.Linear(hidden, latent_dim),
        )

    def forward(self, s_t: torch.Tensor, s_0: torch.Tensor) -> torch.Tensor:
        return self.net(torch.cat([s_t, s_0], dim=-1))


class DynamicsDecoder(nn.Module):
    """``g_dyn(z_t; s_0) -> ŝ_t``."""

    def __init__(self, feat_dim: int = 768, latent_dim: int = 768, hidden: int = 1024) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(latent_dim + feat_dim, hidden),
            nn.GELU(),
            nn.Linear(hidden, hidden),
            nn.GELU(),
            nn.Linear(hidden, feat_dim),
        )

    def forward(self, z_t: torch.Tensor, s_0: torch.Tensor) -> torch.Tensor:
        return self.net(torch.cat([z_t, s_0], dim=-1))


class VelocityMLP(nn.Module):
    """ODE velocity field ``v_θ(z, τ; z_0, c)``."""

    def __init__(
        self,
        latent_dim: int = 768,
        cond_dim: int = 0,
        hidden: int = 1024,
        time_dim: int = 64,
    ) -> None:
        super().__init__()
        self.time_dim = time_dim
        self.cond_dim = cond_dim
        in_dim = latent_dim + time_dim + latent_dim + max(cond_dim, 0)
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden),
            nn.GELU(),
            nn.Linear(hidden, hidden),
            nn.GELU(),
            nn.Linear(hidden, latent_dim),
        )

    def _time_embed(self, tau: torch.Tensor) -> torch.Tensor:
        """Fourier features for scalar τ in [0, 1]."""
        if tau.dim() == 1:
            tau = tau.unsqueeze(-1)
        # (B, 1) -> (B, time_dim)
        half = self.time_dim // 2
        freqs = torch.arange(half, device=tau.device, dtype=tau.dtype)
        freqs = (2.0 ** freqs) * torch.pi
        ang = tau * freqs.unsqueeze(0)
        return torch.cat([ang.sin(), ang.cos()], dim=-1)

    def forward(
        self,
        z: torch.Tensor,
        tau: torch.Tensor,
        z_0: torch.Tensor,
        c: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        te = self._time_embed(tau)
        parts = [z, te, z_0]
        if self.cond_dim > 0:
            if c is None:
                c = z.new_zeros(z.shape[0], self.cond_dim)
            parts.append(c)
        return self.net(torch.cat(parts, dim=-1))


class ODESolver(nn.Module):
    """Fixed-step RK4 integrator for latent ODE dynamics."""

    def __init__(self, velocity: VelocityMLP, n_steps: int = 8) -> None:
        super().__init__()
        self.velocity = velocity
        self.n_steps = n_steps

    def step(
        self,
        z: torch.Tensor,
        tau: torch.Tensor,
        dt: torch.Tensor,
        z_0: torch.Tensor,
        c: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        # dt/tau are (B,); broadcast over latent dim for z updates.
        if dt.dim() == 1:
            dt_z = dt.unsqueeze(-1)
        else:
            dt_z = dt
        v1 = self.velocity(z, tau, z_0, c)
        v2 = self.velocity(z + 0.5 * dt_z * v1, tau + 0.5 * dt, z_0, c)
        v3 = self.velocity(z + 0.5 * dt_z * v2, tau + 0.5 * dt, z_0, c)
        v4 = self.velocity(z + dt_z * v3, tau + dt, z_0, c)
        return z + (dt_z / 6.0) * (v1 + 2 * v2 + 2 * v3 + v4)

    def integrate(
        self,
        z_0: torch.Tensor,
        tau_end: torch.Tensor,
        c: Optional[torch.Tensor] = None,
        n_steps: Optional[int] = None,
    ) -> torch.Tensor:
        """Integrate from τ=0 to ``tau_end`` (per-sample or scalar)."""
        steps = n_steps or self.n_steps
        if tau_end.dim() == 0:
            tau_end = tau_end.expand(z_0.shape[0])
        if tau_end.dim() == 1:
            tau_end = tau_end
        z = z_0
        # Use max horizon; scale dt per sample.
        t = torch.zeros(z_0.shape[0], device=z_0.device, dtype=z_0.dtype)
        dt = tau_end / float(steps)
        for _ in range(steps):
            z = self.step(z, t, dt, z_0, c)
            t = t + dt
        return z

    def forward(
        self,
        z_0: torch.Tensor,
        tau_end: torch.Tensor,
        c: Optional[torch.Tensor] = None,
        n_steps: Optional[int] = None,
    ) -> torch.Tensor:
        return self.integrate(z_0, tau_end, c=c, n_steps=n_steps)


class ODEJEPAModel(nn.Module):
    """Bundles frozen obs encoder + trainable dynamics + ODE predictor."""

    def __init__(
        self,
        feat_dim: int = 768,
        latent_dim: int = 768,
        hidden: int = 512,
        image_size: int = 64,
        ode_steps: int = 8,
        cond_dim: int = 0,
        use_stub_dino: bool = True,
    ) -> None:
        super().__init__()
        self.f_obs = FrozenDINOWrapper(
            feat_dim=feat_dim, image_size=image_size, use_stub=use_stub_dino
        )
        self.f_dyn = DynamicsEncoder(feat_dim, latent_dim, hidden)
        self.g_dyn = DynamicsDecoder(feat_dim, latent_dim, hidden)
        self.velocity = VelocityMLP(latent_dim, cond_dim=cond_dim, hidden=hidden)
        self.ode = ODESolver(self.velocity, n_steps=ode_steps)
        self.feat_dim = feat_dim
        self.latent_dim = latent_dim

    def encode_frames(self, frames: torch.Tensor) -> torch.Tensor:
        """
        Args:
            frames: (B, T, C, H, W)
        Returns:
            s: (B, T, D)
        """
        b, t, c, h, w = frames.shape
        s = self.f_obs(frames.reshape(b * t, c, h, w))
        return s.view(b, t, -1)

    def dynamics_encode(self, s: torch.Tensor, s_0: torch.Tensor) -> torch.Tensor:
        """s: (B, T, D) or (B, D); s_0: (B, D)."""
        if s.dim() == 2:
            return self.f_dyn(s, s_0)
        b, t, d = s.shape
        s0 = s_0.unsqueeze(1).expand(b, t, d).reshape(b * t, d)
        z = self.f_dyn(s.reshape(b * t, d), s0)
        return z.view(b, t, -1)

    def dynamics_decode(self, z: torch.Tensor, s_0: torch.Tensor) -> torch.Tensor:
        if z.dim() == 2:
            return self.g_dyn(z, s_0)
        b, t, d = z.shape
        s0 = s_0.unsqueeze(1).expand(b, t, s_0.shape[-1]).reshape(b * t, -1)
        s_hat = self.g_dyn(z.reshape(b * t, d), s0)
        return s_hat.view(b, t, -1)

    def predict_latent(
        self,
        z_0: torch.Tensor,
        tau_end: torch.Tensor,
        c: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        return self.ode(z_0, tau_end, c=c)


def build_model(cfg: dict) -> ODEJEPAModel:
    m = cfg.get("model", cfg)
    return ODEJEPAModel(
        feat_dim=int(m.get("feat_dim", 768)),
        latent_dim=int(m.get("latent_dim", 768)),
        hidden=int(m.get("hidden", 512)),
        image_size=int(m.get("image_size", 64)),
        ode_steps=int(m.get("ode_steps", 8)),
        cond_dim=int(m.get("cond_dim", 0)),
        use_stub_dino=bool(m.get("use_stub_dino", True)),
    )
