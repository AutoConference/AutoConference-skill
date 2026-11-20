"""Small CPU PINN subproblems with explicit equations and held-out checks.

Supported equations are a harmonic oscillator and exponential decay. Input
data chooses their parameters; no Python or equation strings are evaluated.
API reference: https://deepxde.readthedocs.io/en/latest/demos/pinn_forward/ode.system.html
"""
from __future__ import annotations

import importlib.metadata
import json
import math
import os
from pathlib import Path

from .common import read_json, safe_output


def probe() -> dict:
    try:
        os.environ["DDE_BACKEND"] = "pytorch"
        import deepxde as dde
        import torch
        if dde.backend.backend_name != "pytorch":
            raise RuntimeError("this adapter requires the PyTorch backend in a fresh process")
        return {"available": True, "reason": "DeepXDE with the PyTorch CPU backend is available.",
                "versions": {name: importlib.metadata.version(name) for name in ("deepxde", "torch", "numpy")}}
    except (ImportError, OSError, RuntimeError, importlib.metadata.PackageNotFoundError) as exc:
        return {"available": False, "reason": f"DeepXDE PyTorch backend unavailable: {exc}", "versions": {}}


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if not low <= value <= high:
        raise ValueError(f"{name} must be in [{low}, {high}]")
    return float(value)


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def validate_problem(data):
    if not isinstance(data, dict):
        raise ValueError("problem must be an object")
    equation = data.get("equation")
    if equation not in ("harmonic_oscillator", "exponential_decay"):
        raise ValueError("equation must be harmonic_oscillator or exponential_decay")
    allowed = {"equation", "duration", "initial_position", "initial_velocity", "omega"} if equation == "harmonic_oscillator" else {"equation", "duration", "initial_value", "rate"}
    if set(data) - allowed:
        raise ValueError("problem contains unsupported fields")
    problem = {"equation": equation, "duration": _number(data.get("duration", 1), "duration", 0.01, 10)}
    if equation == "harmonic_oscillator":
        problem.update(omega=_number(data.get("omega", 1), "omega", 0.01, 10),
                       initial_position=_number(data.get("initial_position", 0), "initial_position", -100, 100),
                       initial_velocity=_number(data.get("initial_velocity", 1), "initial_velocity", -100, 100))
    else:
        problem.update(rate=_number(data.get("rate", 1), "rate", 0.01, 10),
                       initial_value=_number(data.get("initial_value", 1), "initial_value", -100, 100))
    return problem


def run(request: dict, workspace: Path) -> dict:
    tier = request.get("tier")
    if type(tier) is not int or tier not in (25, 75, 100):
        raise ValueError("DeepXDE run tier must be 25, 75 or 100")
    inputs, params = request.get("inputs", {}), request.get("params", {})
    if not isinstance(inputs, dict) or set(inputs) != {"problem"}:
        raise ValueError("inputs must contain exactly problem (JSON)")
    if not isinstance(params, dict) or set(params) - {"iterations", "domain_points", "width", "hidden_layers", "learning_rate", "seed", "test_points"}:
        raise ValueError("unsupported DeepXDE parameters")
    problem = validate_problem(read_json(workspace, inputs["problem"]))
    iterations = _integer(params.get("iterations", 200), "iterations", 1, 2000)
    points = _integer(params.get("domain_points", 32), "domain_points", 8, 512)
    width = _integer(params.get("width", 16), "width", 4, 64)
    layers = _integer(params.get("hidden_layers", 2), "hidden_layers", 1, 3)
    tests = _integer(params.get("test_points", 64), "test_points", 8, 512)
    rate = _number(params.get("learning_rate", 0.01), "learning_rate", 0.00001, 0.05)
    seed = _integer(params.get("seed", 17), "seed", 0, 2147483647)

    os.environ["DDE_BACKEND"] = "pytorch"
    import deepxde as dde
    import numpy as np
    import torch
    if dde.backend.backend_name != "pytorch":
        raise ValueError("DeepXDE must use the PyTorch backend; start this adapter in a fresh process")
    # DeepXDE may select CUDA on import. This adapter's declared resource is CPU.
    torch.set_default_device("cpu")
    torch.set_num_threads(1)
    dde.config.set_default_float("float64")
    dde.config.set_random_seed(seed)

    oscillator = problem["equation"] == "harmonic_oscillator"
    dimensions = 2 if oscillator else 1
    duration = problem["duration"]
    geometry = dde.geometry.TimeDomain(0, duration)

    def exact_np(t):
        if oscillator:
            omega, x0, v0 = problem["omega"], problem["initial_position"], problem["initial_velocity"]
            return np.hstack((x0 * np.cos(omega * t) + v0 / omega * np.sin(omega * t),
                              -x0 * omega * np.sin(omega * t) + v0 * np.cos(omega * t)))
        return problem["initial_value"] * np.exp(-problem["rate"] * t)

    def residual(t, y):
        if oscillator:
            return [dde.grad.jacobian(y, t, i=0) - y[:, 1:2],
                    dde.grad.jacobian(y, t, i=1) + problem["omega"] ** 2 * y[:, 0:1]]
        return dde.grad.jacobian(y, t) + problem["rate"] * y

    grid = np.linspace(0, duration, tests).reshape(-1, 1)
    metrics = {"equations": dimensions, "duration": duration, "evaluation_points": tests}
    if tier == 25:
        t = torch.tensor(grid, dtype=torch.float64, requires_grad=True)
        if oscillator:
            omega, x0, v0 = problem["omega"], problem["initial_position"], problem["initial_velocity"]
            y = torch.cat((x0 * torch.cos(omega * t) + v0 / omega * torch.sin(omega * t),
                           -x0 * omega * torch.sin(omega * t) + v0 * torch.cos(omega * t)), dim=1)
        else:
            y = problem["initial_value"] * torch.exp(-problem["rate"] * t)
        terms = residual(t, y)
        if not isinstance(terms, list):
            terms = [terms]
        residual_values = torch.cat(terms, dim=1).detach().cpu().numpy()
        metrics["reference_residual_rms"] = float(np.sqrt(np.mean(residual_values ** 2)))
        predictions = exact_np(grid)
        details = {"kind": "analytic_reference_checked_with_DeepXDE_autodiff", "times": grid[:, 0].tolist(),
                   "reference": predictions.tolist(), "residual": residual_values.tolist()}
        notes = ["25 checks the supplied equation and analytic reference; no PINN is trained."]
    else:
        initial = exact_np(np.zeros((1, 1)))[0]
        def initial_function(value):
            def constant(t):
                return np.full((len(t), 1), value)
            return constant

        conditions = [dde.icbc.IC(geometry, initial_function(float(initial[i])),
                                  lambda _, on_initial: on_initial, component=i) for i in range(dimensions)]
        data = dde.data.PDE(geometry, residual, conditions, num_domain=points, num_boundary=2,
                            train_distribution="pseudo", solution=exact_np, num_test=tests)
        net = dde.nn.FNN([1] + [width] * layers + [dimensions], "tanh", "Glorot uniform")
        model = dde.Model(data, net)
        model.compile("adam", lr=rate)
        loss, state = model.train(iterations=iterations, display_every=iterations)
        predictions = model.predict(grid)
        if not np.isfinite(predictions).all() or not np.isfinite(state.loss_train).all():
            raise ValueError("PINN training produced non-finite values; inspect the scaling and solver settings")
        metrics.update(training_iterations=iterations,
                       final_training_loss=float(np.sum(state.loss_train)),
                       reference_rmse=float(np.sqrt(np.mean((predictions - exact_np(grid)) ** 2))))
        details = {"kind": "trained_PINN", "times": grid[:, 0].tolist(),
                   "predictions": predictions.tolist(), "reference": exact_np(grid).tolist()}
        notes = ["75 trains the bounded ODE PINN and reports error against its analytic reference."]
        if tier == 100:
            # Midpoints are independent of the plotted grid; the residual is
            # recomputed via autodiff, not taken from the optimizer's loss.
            heldout = ((np.arange(tests) + 0.5) * duration / tests).reshape(-1, 1)
            predicted_holdout = model.predict(heldout)
            independent = model.predict(heldout, operator=residual)
            if isinstance(independent, list):
                independent = np.hstack(independent)
            if not np.isfinite(independent).all():
                raise ValueError("PINN held-out residual is non-finite")
            metrics["heldout_residual_rms"] = float(np.sqrt(np.mean(np.asarray(independent) ** 2)))
            metrics["heldout_reference_rmse"] = float(np.sqrt(np.mean((predicted_holdout - exact_np(heldout)) ** 2)))
            metrics["initial_condition_max_error"] = float(np.max(np.abs(model.predict(np.zeros((1, 1)))[0] - initial)))
            details["heldout"] = {"times": heldout[:, 0].tolist(), "predictions": predicted_holdout.tolist(),
                                  "residual": np.asarray(independent).tolist()}
            notes = ["100 adds independent residual, initial-condition and reference checks to the bounded ODE solve."]
    dde.grad.clear()
    relative = f"{request.get('_output_dir', 'runs/science-extensions/deepxde')}/solution.json"
    output = safe_output(workspace, relative)
    output.write_text(json.dumps({"problem": problem, "seed": seed, "backend": "pytorch-cpu", **details},
                                 indent=2, allow_nan=False), encoding="utf-8")
    return {"metrics": metrics, "artifacts": [relative],
            "notes": notes + ["Supports only the two explicit ODE families; this does not establish a general PDE solver or PINN accuracy guarantee."]}
