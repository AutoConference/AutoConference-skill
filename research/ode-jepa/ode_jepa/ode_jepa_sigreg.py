"""ODE-integrated JEPA + SIGReg world model (LeWM data / planning protocol).

Loss recipe (single):
    L = L_JEPA + λ · SIGReg(Z)
with λ=0.1, M=1024 by default.

No JVP, no dyn-recon primary, no stop-grad / EMA on the SIGReg+pred path.
Predictor is an action-conditioned ODESolve of v_θ.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from ode_jepa.sigreg import SIGReg


class ConvEncoder(nn.Module):
    """Compact pixel encoder (trainable). ViT-tiny optional when transformers present."""

    def __init__(self, embed_dim: int = 192, image_size: int = 96, in_ch: int = 3) -> None:
        super().__init__()
        self.image_size = image_size
        self.net = nn.Sequential(
            nn.Conv2d(in_ch, 32, 5, stride=2, padding=2),
            nn.GELU(),
            nn.Conv2d(32, 64, 3, stride=2, padding=1),
            nn.GELU(),
            nn.Conv2d(64, 128, 3, stride=2, padding=1),
            nn.GELU(),
            nn.AdaptiveAvgPool2d(1),
        )
        self.proj = nn.Sequential(
            nn.Linear(128, embed_dim * 2),
            nn.GELU(),
            nn.Linear(embed_dim * 2, embed_dim),
        )

    def forward(self, pixels: torch.Tensor) -> torch.Tensor:
        """pixels: (B*T, C, H, W) -> (B*T, D)"""
        h = self.net(pixels).flatten(1)
        return self.proj(h)


class ActionEmbedder(nn.Module):
    def __init__(self, action_dim: int, embed_dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(action_dim, embed_dim),
            nn.SiLU(),
            nn.Linear(embed_dim, embed_dim),
        )

    def forward(self, action: torch.Tensor) -> torch.Tensor:
        return self.net(action.float())


class ActionConditionedVelocity(nn.Module):
    """v_θ(z, τ; z_0, a_emb)."""

    def __init__(self, latent_dim: int, hidden: int = 512, time_dim: int = 64) -> None:
        super().__init__()
        self.time_dim = time_dim
        in_dim = latent_dim + time_dim + latent_dim + latent_dim  # z, t, z0, a
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden),
            nn.GELU(),
            nn.Linear(hidden, hidden),
            nn.GELU(),
            nn.Linear(hidden, latent_dim),
        )

    def _time_embed(self, tau: torch.Tensor) -> torch.Tensor:
        if tau.dim() == 1:
            tau = tau.unsqueeze(-1)
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
        a_emb: torch.Tensor,
    ) -> torch.Tensor:
        return self.net(torch.cat([z, self._time_embed(tau), z_0, a_emb], dim=-1))


class ODESolver(nn.Module):
    def __init__(self, velocity: ActionConditionedVelocity, n_steps: int = 4) -> None:
        super().__init__()
        self.velocity = velocity
        self.n_steps = n_steps

    def integrate(
        self,
        z_0: torch.Tensor,
        a_emb: torch.Tensor,
        tau_end: float = 1.0,
        n_steps: Optional[int] = None,
    ) -> torch.Tensor:
        steps = int(n_steps or self.n_steps)
        z = z_0
        t = torch.zeros(z_0.shape[0], device=z_0.device, dtype=z_0.dtype)
        dt = torch.full_like(t, float(tau_end) / float(steps))
        for _ in range(steps):
            dt_z = dt.unsqueeze(-1)
            v1 = self.velocity(z, t, z_0, a_emb)
            v2 = self.velocity(z + 0.5 * dt_z * v1, t + 0.5 * dt, z_0, a_emb)
            v3 = self.velocity(z + 0.5 * dt_z * v2, t + 0.5 * dt, z_0, a_emb)
            v4 = self.velocity(z + dt_z * v3, t + dt, z_0, a_emb)
            z = z + (dt_z / 6.0) * (v1 + 2 * v2 + 2 * v3 + v4)
            t = t + dt
        return z


class ODEJEPASigReg(nn.Module):
    """End-to-end pixel JEPA with ODE predictor + SIGReg anti-collapse."""

    def __init__(
        self,
        embed_dim: int = 192,
        action_dim: int = 2,
        image_size: int = 96,
        ode_steps: int = 4,
        hidden: int = 512,
        history_size: int = 3,
        sigreg_knots: int = 17,
        sigreg_num_proj: int = 1024,
        lambda_sigreg: float = 0.1,
    ) -> None:
        super().__init__()
        self.embed_dim = embed_dim
        self.action_dim = action_dim
        self.image_size = image_size
        self.history_size = history_size
        self.lambda_sigreg = float(lambda_sigreg)

        self.encoder = ConvEncoder(embed_dim=embed_dim, image_size=image_size)
        self.action_encoder = ActionEmbedder(action_dim, embed_dim)
        self.velocity = ActionConditionedVelocity(embed_dim, hidden=hidden)
        self.ode = ODESolver(self.velocity, n_steps=ode_steps)
        self.sigreg = SIGReg(knots=sigreg_knots, num_proj=sigreg_num_proj)

    def encode_pixels(self, pixels: torch.Tensor) -> torch.Tensor:
        """pixels (B, T, C, H, W) -> emb (B, T, D). Gradients flow (no stop-grad)."""
        b, t, c, h, w = pixels.shape
        return self.encoder(pixels.reshape(b * t, c, h, w)).view(b, t, -1)

    def predict_next(self, z_t: torch.Tensor, a_t: torch.Tensor) -> torch.Tensor:
        """One-step ODE prediction: z_t, a_t -> ẑ_{t+1}."""
        a_emb = self.action_encoder(a_t)
        return self.ode.integrate(z_t, a_emb, tau_end=1.0)

    def predict_sequence(self, emb: torch.Tensor, action: torch.Tensor) -> torch.Tensor:
        """Teacher-forced one-step ODE preds for each context frame.

        emb: (B, T, D), action: (B, T, A) — predicts next embedding at each t.
        """
        b, t, d = emb.shape
        preds = []
        for i in range(t):
            preds.append(self.predict_next(emb[:, i], action[:, i]))
        return torch.stack(preds, dim=1)

    def forward_loss(
        self,
        pixels: torch.Tensor,
        action: torch.Tensor,
        *,
        history_size: Optional[int] = None,
        num_preds: int = 1,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """Compute L = L_JEPA + λ SIGReg(Z). No stop-grad on targets."""
        hs = int(history_size or self.history_size)
        action = torch.nan_to_num(action, 0.0)
        emb = self.encode_pixels(pixels)  # (B, T, D)
        ctx_emb = emb[:, :hs]
        ctx_act = action[:, :hs]
        tgt_emb = emb[:, num_preds : num_preds + hs]
        # Align lengths if sequence shorter than expected.
        t_use = min(ctx_emb.size(1), tgt_emb.size(1), ctx_act.size(1))
        ctx_emb = ctx_emb[:, :t_use]
        ctx_act = ctx_act[:, :t_use]
        tgt_emb = tgt_emb[:, :t_use]

        pred_emb = self.predict_sequence(ctx_emb, ctx_act)
        # No .detach() on tgt — gradients through encoder + predictor (LeWM-style).
        l_jepa = F.mse_loss(pred_emb, tgt_emb)
        l_sig = self.sigreg(emb.transpose(0, 1))
        loss = l_jepa + self.lambda_sigreg * l_sig
        logs = {
            "loss/total": float(loss.detach()),
            "loss/jepa": float(l_jepa.detach()),
            "loss/sigreg": float(l_sig.detach()),
        }
        return loss, logs

    @torch.no_grad()
    def rollout(
        self,
        pixels: torch.Tensor,
        action_sequence: torch.Tensor,
        history_size: Optional[int] = None,
    ) -> torch.Tensor:
        """Open-loop latent rollout for planning.

        pixels: (B, H, C, H, W) initial history
        action_sequence: (B, S, T, A) candidate plans (S samples)
        Returns predicted embeddings (B, S, T_pred, D) including history.
        """
        hs = int(history_size or self.history_size)
        b, s, t_plan, _ = action_sequence.shape
        # encode history once, expand over samples
        emb0 = self.encode_pixels(pixels[:, :hs])  # (B, H, D)
        emb = emb0.unsqueeze(1).expand(b, s, -1, -1).reshape(b * s, hs, -1).clone()
        acts = action_sequence.reshape(b * s, t_plan, -1)
        # execute first hs actions already "used"; predict remaining with open-loop
        for ti in range(hs, t_plan):
            z_t = emb[:, -1]
            a_t = acts[:, ti - 1]  # action that transitions into next
            z_next = self.predict_next(z_t, a_t)
            emb = torch.cat([emb, z_next.unsqueeze(1)], dim=1)
        # one more step with last action
        z_next = self.predict_next(emb[:, -1], acts[:, -1])
        emb = torch.cat([emb, z_next.unsqueeze(1)], dim=1)
        return emb.view(b, s, -1, self.embed_dim)

    def planning_cost(
        self,
        pixels: torch.Tensor,
        goal_pixels: torch.Tensor,
        action_candidates: torch.Tensor,
        history_size: Optional[int] = None,
    ) -> torch.Tensor:
        """MSE cost between final predicted emb and goal emb — CEM objective."""
        hs = int(history_size or self.history_size)
        goal_emb = self.encode_pixels(goal_pixels[:, :1])  # (B, 1, D)
        pred = self.rollout(pixels, action_candidates, history_size=hs)
        # last predicted state vs goal
        last = pred[:, :, -1:, :]
        goal = goal_emb.unsqueeze(1).expand_as(last)
        cost = F.mse_loss(last, goal, reduction="none").sum(dim=tuple(range(2, last.ndim)))
        return cost  # (B, S)
