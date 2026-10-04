"""Sketched Isotropic Gaussian Regularizer (SIGReg), vendored from LeWM.

Source: lucas-maes/le-wm ``module.SIGReg`` (MIT-style research code).
Paper: Maes et al., LeWorldModel, arXiv:2603.19312.
"""

from __future__ import annotations

import torch
from torch import nn


class SIGReg(nn.Module):
    """Sketch Isotropic Gaussian Regularizer (single-GPU).

    Matches random 1-D projections of embeddings to an isotropic Gaussian
    via an Epps–Pulley characteristic-function statistic.
    """

    def __init__(self, knots: int = 17, num_proj: int = 1024) -> None:
        super().__init__()
        self.num_proj = int(num_proj)
        t = torch.linspace(0, 3, int(knots), dtype=torch.float32)
        dt = 3 / (int(knots) - 1)
        weights = torch.full((int(knots),), 2 * dt, dtype=torch.float32)
        weights[[0, -1]] = dt
        window = torch.exp(-t.square() / 2.0)
        self.register_buffer("t", t)
        self.register_buffer("phi", window)
        self.register_buffer("weights", weights * window)

    def forward(self, proj: torch.Tensor) -> torch.Tensor:
        """
        Args:
            proj: ``(T, B, D)`` latent embeddings (time-major).
        Returns:
            Scalar SIGReg statistic (mean over projections and time).
        """
        a = torch.randn(proj.size(-1), self.num_proj, device=proj.device, dtype=proj.dtype)
        a = a.div_(a.norm(p=2, dim=0).clamp_min(1e-8))
        x_t = (proj @ a).unsqueeze(-1) * self.t.to(dtype=proj.dtype)
        err = (x_t.cos().mean(-3) - self.phi.to(dtype=proj.dtype)).square() + x_t.sin().mean(-3).square()
        statistic = (err @ self.weights.to(dtype=proj.dtype)) * proj.size(-2)
        return statistic.mean()
