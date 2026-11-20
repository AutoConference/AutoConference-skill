"""Prepare and audit supplied RL trajectories with TorchRL replay buffers and GAE.

This bounded adapter does not train or execute a policy. It preserves the
distinction between terminal states and truncated episodes when bootstrapping.
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
        for name in ("torch", "torchrl", "tensordict"):
            importlib.import_module(name)
            versions[name] = importlib.metadata.version(name)
        return {"available": True, "reason": "CPU replay buffers and advantage estimation are available.", "versions": versions}
    except (ImportError, OSError, RuntimeError, importlib.metadata.PackageNotFoundError) as exc:
        return {"available": False, "reason": f"Install compatible torch, torchrl and tensordict: {exc}", "versions": versions}


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _sequence(value, name, length=None, boolean=False):
    if not isinstance(value, list) or not 1 <= len(value) <= 10000 or (length is not None and len(value) != length):
        raise ValueError(f"{name} needs 1..10000 entries, aligned with the rewards")
    if boolean:
        if any(type(v) is not bool for v in value):
            raise ValueError(f"{name} entries must be booleans")
        return value
    return [_number(v, name) for v in value]


def reference_gae(rewards, values, next_values, done, terminated, gamma, lmbda):
    """Independent scalar recurrence for the tier 100 boundary audit."""
    advantage = [0.0] * len(rewards)
    carry = 0.0
    for i in range(len(rewards) - 1, -1, -1):
        delta = rewards[i] + gamma * (not terminated[i]) * next_values[i] - values[i]
        carry = delta + gamma * lmbda * (not done[i]) * carry
        advantage[i] = carry
    return advantage


def run(request: dict, workspace: Path) -> dict:
    tier = request["tier"]
    if type(tier) is not int or tier not in (25, 75, 100):
        raise ValueError("TorchRL accepts tiers 25, 75 or 100; tier 0 is handled by the runner")
    inputs = request.get("inputs", {})
    if not isinstance(inputs, dict) or set(inputs) != {"trajectory"}:
        raise ValueError("inputs must contain exactly trajectory (JSON)")
    params = request.get("params", {})
    if not isinstance(params, dict) or set(params) - {"gamma", "lambda", "seed", "batch_size"}:
        raise ValueError("unsupported TorchRL parameters; use gamma, lambda, seed or batch_size")
    data = read_json(workspace, inputs["trajectory"])
    if not isinstance(data, dict):
        raise ValueError("trajectory must be a JSON object")
    rewards = _sequence(data.get("rewards"), "rewards")
    n = len(rewards)
    values = _sequence(data.get("values"), "values", n)
    next_values = _sequence(data.get("next_values"), "next_values", n)
    done = _sequence(data.get("done"), "done", n, boolean=True)
    terminated = _sequence(data.get("terminated"), "terminated", n, boolean=True)
    if any(terminal and not end for terminal, end in zip(terminated, done)):
        raise ValueError("Every terminated step must also have done=true")
    gamma = _number(params.get("gamma", 0.99), "gamma")
    lmbda = _number(params.get("lambda", 0.95), "lambda")
    if not 0 <= gamma <= 1 or not 0 <= lmbda <= 1:
        raise ValueError("gamma and lambda must be in [0, 1]")
    seed = params.get("seed", 0)
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("seed must be an integer in [0, 2**31)")
    batch_size = params.get("batch_size", min(n, 8))
    if type(batch_size) is not int or not 1 <= batch_size <= min(n, 512):
        raise ValueError("batch_size must be an integer from 1 to min(trajectory length, 512)")

    import torch
    from tensordict import TensorDict
    from torchrl.data import LazyTensorStorage, TensorDictReplayBuffer
    from torchrl.objectives.value import GAE

    torch.manual_seed(seed)
    torch.set_num_threads(1)
    column = lambda entries, dtype: torch.tensor(entries, dtype=dtype).unsqueeze(-1)
    td = TensorDict({
        "state_value": column(values, torch.double),
        "next": TensorDict({"state_value": column(next_values, torch.double),
                            "reward": column(rewards, torch.double),
                            "done": column(done, torch.bool),
                            "terminated": column(terminated, torch.bool)}, batch_size=[n])
    }, batch_size=[n], names=["time"])
    buffer = TensorDictReplayBuffer(storage=LazyTensorStorage(max_size=n), batch_size=batch_size)
    buffer.extend(td)
    roundtrip = buffer[:]
    roundtrip_error = float((roundtrip["next", "reward"] - td["next", "reward"]).abs().max())
    if roundtrip_error != 0:
        raise ValueError("Replay buffer changed the supplied rewards")
    metrics = {"transitions": n, "episode_ends": sum(done), "terminal_ends": sum(terminated),
               "truncated_ends": sum(end and not terminal for end, terminal in zip(done, terminated)),
               "reward_sum": sum(rewards), "replay_roundtrip_error": roundtrip_error}
    output = {}
    if tier >= 75:
        estimator = GAE(gamma=gamma, lmbda=lmbda, value_network=None,
                        average_gae=False, differentiable=False, vectorized=False)
        with torch.no_grad():
            enriched = estimator(td.clone(), time_dim=0)
        advantage = enriched["advantage"].squeeze(-1)
        targets = enriched["value_target"].squeeze(-1)
        if not torch.isfinite(advantage).all() or not torch.isfinite(targets).all():
            raise ValueError("TorchRL produced non-finite advantage estimates")
        output.update({"advantage": advantage.tolist(), "value_target": targets.tolist()})
        metrics.update({"advantage_mean": float(advantage.mean()),
                        "advantage_std": float(advantage.std(unbiased=False)),
                        "value_target_mean": float(targets.mean())})
    if tier == 100:
        reference = torch.tensor(reference_gae(rewards, values, next_values, done, terminated, gamma, lmbda),
                                 dtype=torch.double)
        audit_error = float((advantage - reference).abs().max())
        # TorchRL represents scalar discount buffers in float32 on some versions.
        # Scale the tolerance to the recurrence magnitude, rather than quietly
        # passing a changed terminal/truncation convention.
        tolerance = 2e-6 * max(1.0, float(reference.abs().max()))
        if audit_error > tolerance:
            raise ValueError(f"Boundary audit failed: GAE max error {audit_error} > {tolerance}")
        buffer.empty()
        buffer.extend(enriched)
        sample = buffer.sample()
        output["sample_indices"] = sample["index"].tolist()
        output["sample_advantage"] = sample["advantage"].squeeze(-1).tolist()
        metrics.update({"boundary_audit_max_error": audit_error, "boundary_audit_tolerance": tolerance,
                        "sample_size": batch_size})
    if not all(math.isfinite(v) for v in metrics.values()):
        raise ValueError("TorchRL adapter produced a non-finite metric")
    return {"metrics": metrics, "data": output, "artifacts": [], "notes": [
        "Inputs are caller-provided trajectories and value estimates; no policy was trained or evaluated.",
        "GAE resets its recurrence at done; it bootstraps next_value at truncation but never at termination."]}
