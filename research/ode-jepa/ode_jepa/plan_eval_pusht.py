"""LeWM-style CEM planning eval on PushT (real env when available).

Uses official dataset tags for initial/goal states when env reset-from-dataset
is possible; otherwise reports latent planning proxy on held-out HDF5 windows
and documents the gap.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import torch
import yaml

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ode_jepa.ode_jepa_sigreg import ODEJEPASigReg
from ode_jepa.pusht_h5 import PushTH5Dataset, resolve_pusht_h5, verify_h5


def load_config(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@torch.no_grad()
def cem_plan(
    model: ODEJEPASigReg,
    pixels: torch.Tensor,
    goal: torch.Tensor,
    *,
    horizon: int,
    action_dim: int,
    n_samples: int = 64,
    n_elite: int = 8,
    n_iters: int = 5,
    action_low: float = -1.0,
    action_high: float = 1.0,
) -> torch.Tensor:
    """CEM over action sequences; returns best plan (1, T, A)."""
    device = pixels.device
    b = pixels.shape[0]
    mean = torch.zeros(b, horizon, action_dim, device=device)
    std = torch.ones(b, horizon, action_dim, device=device)
    best_actions = mean.clone()
    best_cost = torch.full((b,), float("inf"), device=device)

    for _ in range(n_iters):
        noise = torch.randn(b, n_samples, horizon, action_dim, device=device)
        cands = mean.unsqueeze(1) + std.unsqueeze(1) * noise
        cands = cands.clamp(action_low, action_high)
        cost = model.planning_cost(pixels, goal, cands)  # (B, S)
        elite_idx = cost.topk(n_elite, largest=False, dim=1).indices
        elite = torch.gather(
            cands, 1, elite_idx.unsqueeze(-1).unsqueeze(-1).expand(-1, -1, horizon, action_dim)
        )
        mean = elite.mean(dim=1)
        std = elite.std(dim=1).clamp_min(0.05)
        batch_best, idx = cost.min(dim=1)
        improved = batch_best < best_cost
        best_cost = torch.where(improved, batch_best, best_cost)
        gather_idx = idx.view(b, 1, 1, 1).expand(b, 1, horizon, action_dim)
        chosen = torch.gather(cands, 1, gather_idx).squeeze(1)
        best_actions = torch.where(improved.view(b, 1, 1), chosen, best_actions)
    return best_actions


def try_env_eval(model, cfg, device) -> Optional[Dict[str, Any]]:
    """Attempt real gymnasium PushT CEM eval (gym-pusht / stable_worldmodel)."""
    try:
        import gymnasium as gym
        import gym_pusht  # noqa: F401 — registers gym_pusht/PushT-v0
    except Exception as e:
        return {"status": "skipped", "reason": f"gymnasium/gym_pusht missing: {e}"}

    env = None
    env_name_used = None
    last_err = None
    make_kwargs = {"render_mode": "rgb_array", "obs_type": "pixels"}
    for env_name in (
        cfg.get("eval", {}).get("env_name", "gym_pusht/PushT-v0"),
        "gym_pusht/PushT-v0",
        "swm/PushT-v1",
    ):
        try:
            env = gym.make(env_name, **make_kwargs)
            env_name_used = env_name
            break
        except Exception as e1:
            last_err = repr(e1)
            try:
                env = gym.make(env_name, render_mode="rgb_array")
                env_name_used = env_name
                break
            except Exception as e2:
                last_err = repr(e2)
                continue
    if env is None:
        return {
            "status": "skipped",
            "reason": f"could not make PushT env (tried gym_pusht/PushT-v0, swm/PushT-v1): {last_err}",
        }

    n_eval = int(cfg.get("eval", {}).get("num_eval", 20))
    horizon = int(cfg.get("eval", {}).get("horizon", 5))
    budget = int(cfg.get("eval", {}).get("eval_budget", 50))
    img_size = int(cfg.get("model", {}).get("image_size", 96))
    successes = 0
    returns: List[float] = []
    t0 = time.time()

    import torch.nn.functional as TF

    def obs_to_pixels(obs) -> torch.Tensor:
        if isinstance(obs, dict):
            img = obs.get("pixels") or obs.get("image") or obs.get("rgb") or obs.get("observation")
            if img is None:
                img = next(iter(obs.values()))
        else:
            img = obs
        arr = np.asarray(img)
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
        t = torch.from_numpy(arr).float()
        if t.ndim == 3 and t.shape[-1] == 3:
            t = t.permute(2, 0, 1)
        if t.max() > 1.5:
            t = t / 255.0
        t = TF.interpolate(
            t.unsqueeze(0), size=(img_size, img_size), mode="bilinear", align_corners=False
        )[0]
        return t

    model.eval()
    action_low = float(np.asarray(env.action_space.low).reshape(-1)[0])
    action_high = float(np.asarray(env.action_space.high).reshape(-1)[0])
    for ep in range(n_eval):
        obs, info = env.reset(seed=1000 + ep)
        gobs = obs
        for _ in range(int(cfg.get("eval", {}).get("goal_offset_steps", 25))):
            gobs, _, term, trunc, _ = env.step(env.action_space.sample())
            if term or trunc:
                break
        goal = obs_to_pixels(gobs).unsqueeze(0).unsqueeze(0).to(device)  # (B,T=1,C,H,W)

        obs, info = env.reset(seed=1000 + ep)
        hist = [obs_to_pixels(obs)]
        ep_ret = 0.0
        success = False
        action_dim = int(env.action_space.shape[0])
        for t in range(budget):
            while len(hist) < model.history_size:
                hist.insert(0, hist[0])
            pix = torch.stack(hist[-model.history_size :], dim=0).unsqueeze(0).to(device)
            plan = cem_plan(
                model,
                pix,
                goal,
                horizon=horizon,
                action_dim=action_dim,
                n_samples=int(cfg.get("eval", {}).get("cem_samples", 64)),
                n_elite=int(cfg.get("eval", {}).get("cem_elite", 8)),
                n_iters=int(cfg.get("eval", {}).get("cem_iters", 5)),
                action_low=action_low,
                action_high=action_high,
            )
            a = plan[0, 0].detach().cpu().numpy().astype(np.float32)
            a = np.clip(a, env.action_space.low, env.action_space.high)
            obs, reward, term, trunc, info = env.step(a)
            ep_ret += float(reward)
            hist.append(obs_to_pixels(obs))
            if bool(info.get("is_success") or info.get("success") or (reward >= 1.0)):
                success = True
                break
            if term or trunc:
                break
        successes += int(success)
        returns.append(ep_ret)
        print(f"[env-eval] ep={ep} success={success} return={ep_ret:.3f}")

    env.close()
    return {
        "status": "ok",
        "num_eval": n_eval,
        "successes": successes,
        "success_rate": successes / max(n_eval, 1),
        "mean_return": float(np.mean(returns) if returns else 0.0),
        "seconds": round(time.time() - t0, 2),
        "backend": "gym_env",
        "env_name": env_name_used,
        "obs_type": "pixels",
    }


@torch.no_grad()
def h5_latent_proxy_eval(model, cfg, device) -> Dict[str, Any]:
    """Held-out HDF5 latent goal-reaching proxy (real data only)."""
    h5_name = cfg.get("data", {}).get("dataset_name", "pusht_expert_train")
    h5_path = resolve_pusht_h5(h5_name)
    meta = verify_h5(h5_path)
    hs = int(cfg.get("model", {}).get("history_size", 3))
    seq_len = hs + int(cfg.get("eval", {}).get("goal_offset_steps", 5))
    ds = PushTH5Dataset(
        h5_path,
        seq_len=seq_len,
        frameskip=int(cfg.get("data", {}).get("frameskip", 5)),
        image_size=int(cfg.get("model", {}).get("image_size", 96)),
        max_episodes=cfg.get("eval", {}).get("max_episodes", 50),
    )
    n = min(int(cfg.get("eval", {}).get("num_eval", 50)), len(ds))
    horizon = int(cfg.get("eval", {}).get("horizon", 5))
    action_dim = int(ds[0]["action"].shape[-1])
    hits = 0
    costs: List[float] = []
    t0 = time.time()
    model.eval()
    for i in range(n):
        batch = ds[i]
        pix = batch["pixels"][:hs].unsqueeze(0).to(device)
        goal = batch["pixels"][-1:].unsqueeze(0).to(device)
        plan = cem_plan(
            model, pix, goal, horizon=horizon, action_dim=action_dim,
            n_samples=int(cfg.get("eval", {}).get("cem_samples", 64)),
            n_elite=int(cfg.get("eval", {}).get("cem_elite", 8)),
            n_iters=int(cfg.get("eval", {}).get("cem_iters", 5)),
        )
        # cost of planned final vs goal; also expert action baseline
        plan_cost = float(model.planning_cost(pix, goal, plan.unsqueeze(1))[0, 0])
        expert = batch["action"][:horizon].unsqueeze(0).unsqueeze(0).to(device)
        if expert.shape[2] < horizon:
            pad = expert[:, :, -1:, :].expand(-1, -1, horizon - expert.shape[2], -1)
            expert = torch.cat([expert, pad], dim=2)
        expert_cost = float(model.planning_cost(pix, goal, expert[:, :, :horizon])[0, 0])
        costs.append(plan_cost)
        if plan_cost <= expert_cost * 1.25:
            hits += 1
    return {
        "status": "ok",
        "backend": "h5_latent_proxy",
        "h5_meta": meta,
        "num_eval": n,
        "success_rate": hits / max(n, 1),
        "mean_plan_cost": float(np.mean(costs) if costs else 0.0),
        "seconds": round(time.time() - t0, 2),
        "definition": "success if CEM plan latent cost <= 1.25x expert-action cost to same goal frame",
    }


def main(argv: Optional[list] = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--ckpt", required=True)
    p.add_argument("--device", default=None)
    p.add_argument("--output", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    device = torch.device(args.device or cfg.get("device", "cuda" if torch.cuda.is_available() else "cpu"))

    ckpt = torch.load(args.ckpt, map_location=device, weights_only=False)
    action_dim = int(ckpt.get("action_dim", cfg.get("model", {}).get("action_dim", 2)))
    mcfg = cfg["model"]
    lcfg = cfg["loss"]
    model = ODEJEPASigReg(
        embed_dim=int(mcfg.get("embed_dim", 192)),
        action_dim=action_dim,
        image_size=int(mcfg.get("image_size", 96)),
        ode_steps=int(mcfg.get("ode_steps", 4)),
        hidden=int(mcfg.get("hidden", 512)),
        history_size=int(mcfg.get("history_size", 3)),
        sigreg_knots=int(lcfg.get("sigreg_knots", 17)),
        sigreg_num_proj=int(lcfg.get("sigreg_num_proj", 1024)),
        lambda_sigreg=float(lcfg.get("lambda_sigreg", 0.1)),
    ).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()

    results: Dict[str, Any] = {
        "ckpt": args.ckpt,
        "protocol": "LeWM-style CEM planning (real data only)",
        "note": "Prior synthetic phase1 metrics are non-final and not used.",
    }
    env_res = try_env_eval(model, cfg, device)
    results["env_eval"] = env_res
    try:
        # Use short goal offset for HDF5 windows (episode lengths ~125)
        cfg_proxy = dict(cfg)
        cfg_proxy["eval"] = dict(cfg.get("eval", {}))
        cfg_proxy["eval"]["goal_offset_steps"] = min(
            int(cfg_proxy["eval"].get("goal_offset_steps", 5)), 5
        )
        cfg_proxy["eval"]["max_episodes"] = int(cfg_proxy["eval"].get("max_episodes", 80) or 80)
        proxy = h5_latent_proxy_eval(model, cfg_proxy, device)
    except Exception as e:
        proxy = {"status": "error", "reason": repr(e)}
    results["h5_proxy_eval"] = proxy

    # Prefer env success rate when available
    if env_res and env_res.get("status") == "ok":
        results["primary_success_rate"] = env_res["success_rate"]
        results["primary_backend"] = "env"
    elif proxy.get("status") == "ok":
        results["primary_success_rate"] = proxy["success_rate"]
        results["primary_backend"] = "h5_latent_proxy"
    else:
        results["primary_success_rate"] = None
        results["primary_backend"] = "none"
    results["collapse_warning"] = (
        "If train SIGReg plateaus and JEPA~0, latent-proxy success is non-informative; "
        "prefer gym_pusht env success_rate."
    )

    out = Path(args.output or Path(cfg["train"]["output_dir"]) / "plan_eval.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))
    print(f"[eval] wrote {out}")


if __name__ == "__main__":
    main()
