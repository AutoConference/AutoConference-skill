"""Bounded Bayesian experiment selection using BoTorch, with caller-owned data.

Source: https://botorch.org/docs/v0.15.0/getting_started
This adapter proposes experiments; it never invents observations for them.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import math
from pathlib import Path

from .common import read_json


def probe() -> dict:
    versions = {}
    try:
        for name in ("torch", "botorch", "gpytorch"):
            importlib.import_module(name)
            versions[name] = importlib.metadata.version(name)
        return {"available": True, "reason": "CPU Gaussian-process fitting is available.", "versions": versions}
    except (ImportError, OSError, RuntimeError, importlib.metadata.PackageNotFoundError) as exc:
        return {"available": False, "reason": f"Install compatible torch, botorch and gpytorch: {exc}", "versions": versions}


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _matrix(value, name, columns=None, maximum=256):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{name} needs 1..{maximum} rows")
    if columns is None:
        columns = len(value[0]) if isinstance(value[0], list) else 0
    if not 1 <= columns <= 8:
        raise ValueError(f"{name} needs 1..8 columns")
    if any(not isinstance(row, list) or len(row) != columns for row in value):
        raise ValueError(f"{name} rows must have {columns} columns")
    return [[_number(v, name) for v in row] for row in value]


def _vector(value, name, length):
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{name} needs {length} values")
    return [_number(v, name) for v in value]


def _integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def run(request: dict, workspace: Path) -> dict:
    tier = request["tier"]
    if type(tier) is not int or tier not in (25, 75, 100):
        raise ValueError("BoTorch accepts tiers 25, 75 or 100; tier 0 is handled by the runner")
    inputs = request.get("inputs", {})
    if not isinstance(inputs, dict) or set(inputs) != {"observations"}:
        raise ValueError("inputs must contain exactly observations (JSON)")
    params = request.get("params", {})
    if not isinstance(params, dict) or set(params) - {"seed", "maxiter", "observation_noise_variance", "maximize"}:
        raise ValueError("unsupported BoTorch parameters; use seed, maxiter, observation_noise_variance or maximize")
    data = read_json(workspace, inputs["observations"])
    if not isinstance(data, dict):
        raise ValueError("observations must be a JSON object")
    rows = _matrix(data.get("train_x"), "train_x")
    if len(rows) < 3:
        raise ValueError("train_x needs at least 3 observed experiments")
    d = len(rows[0])
    values = _vector(data.get("train_y"), "train_y", len(rows))
    bounds_rows = _matrix(data.get("bounds"), "bounds", columns=d, maximum=2)
    if len(bounds_rows) != 2 or any(lo >= hi for lo, hi in zip(*bounds_rows)):
        raise ValueError("bounds must have lower and upper rows with lower < upper")

    def in_bounds(points, label):
        if any(not bounds_rows[0][j] <= p[j] <= bounds_rows[1][j] for p in points for j in range(d)):
            raise ValueError(f"{label} contains a point outside the declared bounds")

    in_bounds(rows, "train_x")
    if len(set(tuple(row) for row in rows)) != len(rows):
        raise ValueError("train_x contains duplicate locations; aggregate repeated measurements first")
    candidates = _matrix(data.get("candidates"), "candidates", d) if tier == 25 else None
    if candidates:
        in_bounds(candidates, "candidates")
    holdout_x = holdout_y = None
    if tier == 100:
        holdout_x = _matrix(data.get("holdout_x"), "holdout_x", d, maximum=128)
        holdout_y = _vector(data.get("holdout_y"), "holdout_y", len(holdout_x))
        in_bounds(holdout_x, "holdout_x")
        if set(map(tuple, rows)) & set(map(tuple, holdout_x)):
            raise ValueError("holdout_x overlaps train_x; held-out diagnostics require separate locations")
    seed = _integer(params.get("seed", 0), "seed", 0, 2**31 - 1)
    maxiter = _integer(params.get("maxiter", 50), "maxiter", 1, 200)
    noise = _number(params.get("observation_noise_variance", 0.0001), "observation_noise_variance")
    if noise <= 0:
        raise ValueError("observation_noise_variance must be positive in the units of train_y squared")
    maximize = params.get("maximize", True)
    if type(maximize) is not bool:
        raise ValueError("maximize must be a boolean")

    import torch
    from botorch.acquisition.analytic import LogExpectedImprovement
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.models.transforms.input import Normalize
    from botorch.models.transforms.outcome import Standardize
    from botorch.optim import optimize_acqf
    from gpytorch.mlls import ExactMarginalLogLikelihood

    torch.manual_seed(seed)
    torch.set_num_threads(1)
    x = torch.tensor(rows, dtype=torch.double)
    y = torch.tensor(values, dtype=torch.double).unsqueeze(-1)
    bounds = torch.tensor(bounds_rows, dtype=torch.double)
    model = SingleTaskGP(x, y, train_Yvar=torch.full_like(y, noise),
                         input_transform=Normalize(d=d, bounds=bounds),
                         outcome_transform=Standardize(m=1))
    fit_gpytorch_mll(ExactMarginalLogLikelihood(model.likelihood, model),
                    optimizer_kwargs={"options": {"maxiter": maxiter}})
    model.eval()
    metrics = {"observations": len(rows), "dimensions": d,
               "best_observed": float(y.max() if maximize else y.min())}
    output = {}
    if tier == 25:
        with torch.no_grad():
            posterior = model.posterior(torch.tensor(candidates, dtype=torch.double))
            mean = posterior.mean.squeeze(-1)
            std = posterior.variance.squeeze(-1).clamp_min(0).sqrt()
        output["checked_candidates"] = candidates
        output["posterior_mean"] = mean.tolist()
        output["posterior_std"] = std.tolist()
        metrics.update({"checked_candidates": len(candidates), "mean_posterior_std": float(std.mean())})
    else:
        acquisition = LogExpectedImprovement(model, best_f=metrics["best_observed"], maximize=maximize)
        candidate, log_ei = optimize_acqf(acquisition, bounds=bounds, q=1,
                                         num_restarts=4, raw_samples=32,
                                         options={"maxiter": maxiter, "batch_limit": 4})
        with torch.no_grad():
            posterior = model.posterior(candidate)
        output["next_candidate"] = candidate.squeeze(0).tolist()
        metrics.update({"log_expected_improvement": float(log_ei),
                        "candidate_predicted_mean": float(posterior.mean.squeeze()),
                        "candidate_predicted_std": float(posterior.variance.squeeze().clamp_min(0).sqrt())})
    if tier == 100:
        with torch.no_grad():
            prediction = model.posterior(torch.tensor(holdout_x, dtype=torch.double))
            residual = prediction.mean.squeeze(-1) - torch.tensor(holdout_y, dtype=torch.double)
            std = prediction.variance.squeeze(-1).clamp_min(0).sqrt()
        metrics.update({"holdout_points": len(holdout_x),
                        "holdout_rmse": float(residual.square().mean().sqrt()),
                        "holdout_latent_95pct_coverage": float((residual.abs() <= 1.96 * std).double().mean())})
        output["holdout_predicted_mean"] = prediction.mean.squeeze(-1).tolist()
        output["holdout_predicted_std"] = std.tolist()
    if not all(math.isfinite(v) for v in metrics.values()):
        raise ValueError("BoTorch produced a non-finite result")
    return {"metrics": metrics, "data": output, "artifacts": [], "notes": [
        "The suggested point has not been evaluated. Predictions are not experimental findings.",
        "Tier 100 checks the supplied held-out locations after fitting only train_x/train_y; coverage uses latent-function uncertainty."]}
