"""Offline, bounded causal-LM evaluation using lm-evaluation-harness.

API: https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/models/huggingface.py
No provider, Hub download, remote model code, or built-in downloadable task is used.
"""
from __future__ import annotations

import importlib.metadata
import json
import math
import os
from pathlib import Path

from .common import read_json, safe_input, safe_output


def probe() -> dict:
    versions = {}
    try:
        for name in ("lm_eval", "transformers", "torch", "accelerate"):
            versions[name] = importlib.metadata.version(name)
        from lm_eval.models.huggingface import HFLM  # noqa: F401
        return {"available": True, "reason": "Local HF backend available; a local safetensors model and evaluation data are required.", "versions": versions}
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return {"available": False, "reason": f"Local HF backend unavailable: {type(exc).__name__}: {exc}", "versions": versions}


def _rows(data, tier):
    rows = data.get("records") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not 1 <= len(rows) <= 128:
        raise ValueError("records must contain 1..128 local evaluation examples")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each record must be an object")
        for key in ("context", "continuation"):
            if not isinstance(row.get(key), str) or not row[key] or len(row[key]) > 8192:
                raise ValueError(f"{key} must be a nonempty string of at most 8192 characters")
        if tier >= 75:
            choices, target = row.get("choices"), row.get("target_index")
            if not isinstance(choices, list) or not 2 <= len(choices) <= 8 or any(
                not isinstance(x, str) or not x or len(x) > 8192 for x in choices
            ):
                raise ValueError("tiers 75/100 require 2..8 nonempty choices per record")
            if type(target) is not int or not 0 <= target < len(choices):
                raise ValueError("target_index must identify a choice")
            if row["continuation"] != choices[target]:
                raise ValueError("continuation must equal the target choice")
    return rows


def _output(workspace: Path, request: dict) -> Path:
    relative = request.get("_output_dir", "runs/extension-runs/lm_eval")
    return safe_output(workspace, relative + "/lm-eval-details.json")


def run(request: dict, workspace: Path) -> dict:
    tier = request.get("tier")
    if type(tier) is not int or tier not in (25, 75, 100):
        raise ValueError("tier must be 25, 75 or 100")
    inputs, params = request.get("inputs", {}), request.get("params", {})
    if not isinstance(inputs, dict) or set(inputs) != {"data", "model_dir"}:
        raise ValueError("inputs must contain exactly data and model_dir")
    if not isinstance(params, dict) or set(params) - {"device", "max_new_tokens", "max_length"}:
        raise ValueError("params accepts only device, max_new_tokens and max_length")
    rows = _rows(read_json(workspace, inputs.get("data")), tier)
    model_dir = safe_input(workspace, inputs.get("model_dir"))
    if not model_dir.is_dir() or not (model_dir / "config.json").is_file():
        raise ValueError("model_dir must be a local Hugging Face model directory")
    # A model directory can contain links to a Hub cache outside this workspace.
    for item in model_dir.rglob("*"):
        if item.is_symlink():
            raise ValueError("local model directory must not contain symbolic links")
    if not list(model_dir.glob("*.safetensors")):
        raise ValueError("local model must have safetensors weights; pickle weights are not loaded")
    index = model_dir / "model.safetensors.index.json"
    if index.exists():
        shard_map = json.loads(index.read_text(encoding="utf-8")).get("weight_map", {})
        if not isinstance(shard_map, dict) or not shard_map:
            raise ValueError("invalid safetensors shard index")
        for shard in shard_map.values():
            if not isinstance(shard, str) or Path(shard).name != shard or ":" in shard or "\\" in shard:
                raise ValueError("safetensors shards must be files inside model_dir")
            if not shard.endswith(".safetensors") or not (model_dir / shard).is_file():
                raise ValueError("missing local safetensors shard")
    device = params.get("device", "cpu")
    if device not in ("cpu", "cuda"):
        raise ValueError("device must be cpu or cuda")
    max_tokens = params.get("max_new_tokens", 32)
    max_length = params.get("max_length", 512)
    if type(max_tokens) is not int or not 1 <= max_tokens <= 128:
        raise ValueError("max_new_tokens must be 1..128")
    if type(max_length) is not int or not 32 <= max_length <= 4096:
        raise ValueError("max_length must be 32..4096")
    # Set before importing either HF library; constructors below also insist on local files.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from lm_eval.api.instance import Instance
    from lm_eval.models.huggingface import HFLM

    if device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is unavailable")
    torch.manual_seed(0)
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(
        str(model_dir), local_files_only=True, trust_remote_code=False, use_safetensors=True,
        torch_dtype=torch.float32 if device == "cpu" else torch.float16,
    ).to(device).eval()
    actual_max = getattr(model.config, "n_positions", getattr(model.config, "max_position_embeddings", max_length))
    max_length = min(max_length, int(actual_max))
    for row in rows:
        texts = row.get("choices", [row["continuation"]]) if tier >= 75 else [row["continuation"]]
        if any(len(tokenizer.encode(row["context"] + text)) > max_length for text in texts):
            raise ValueError("an example exceeds model context; shorten it explicitly rather than truncating evaluation")
        if tier == 100 and len(tokenizer.encode(row["context"])) + max_tokens > max_length:
            raise ValueError("generation would exceed model context; reduce max_new_tokens")
    lm = HFLM(pretrained=model, tokenizer=tokenizer, backend="causal", batch_size=1,
              max_length=max_length, device=device)
    requests, spans = [], []
    for index, row in enumerate(rows):
        choices = row["choices"] if tier >= 75 else [row["continuation"]]
        begin = len(requests)
        for choice in choices:
            requests.append(Instance(request_type="loglikelihood", doc=row,
                arguments=(row["context"], choice), idx=len(requests), metadata=("ac_local", index, 1)))
        spans.append((begin, len(requests)))
    values = lm.loglikelihood(requests)
    details, target_values, successes = [], [], []
    for row, (begin, end) in zip(rows, spans):
        scores = [float(v[0]) for v in values[begin:end]]
        if not all(math.isfinite(value) for value in scores):
            raise ValueError("model returned a non-finite likelihood")
        target_index = row["target_index"] if tier >= 75 else 0
        target_values.append(scores[target_index])
        item = {"index": len(details), "loglikelihoods": scores}
        if tier >= 75:
            predicted = max(range(len(scores)), key=scores.__getitem__)
            item.update(predicted_index=predicted, target_index=target_index)
            successes.append(int(predicted == target_index))
        details.append(item)
    metrics = {"examples": len(rows), "mean_target_loglikelihood": sum(target_values) / len(rows)}
    if tier >= 75:
        metrics["choice_accuracy"] = sum(successes) / len(rows)
    if tier == 100:
        generations = lm.generate_until([
            Instance(request_type="generate_until", doc=row, arguments=(row["context"], {
                "until": [tokenizer.eos_token] if tokenizer.eos_token else [],
                "max_gen_toks": max_tokens, "do_sample": False,
            }), idx=index, metadata=("ac_local", index, 1))
            for index, row in enumerate(rows)
        ])
        exact = []
        for row, item, generated in zip(rows, details, generations):
            item["generated"] = generated
            exact.append(int(generated.strip() == row["continuation"].strip()))
        metrics["generation_exact_match"] = sum(exact) / len(exact)
    output = _output(workspace, request)
    output.write_text(json.dumps({"tier": tier, "records": details}, indent=2, allow_nan=False), encoding="utf-8")
    return {"metrics": metrics, "artifacts": [output.relative_to(workspace.resolve()).as_posix()], "notes": [
        "Local causal-model evaluation only; scores measure this supplied dataset, not research-idea quality.",
        "Choice ranking uses unnormalized completion log-likelihood; unequal answer lengths can affect ranking.",
    ]}
