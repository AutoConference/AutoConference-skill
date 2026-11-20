"""SAM 2.1 image segmentation, using explicitly supplied local tiny weights.

Official API: https://github.com/facebookresearch/sam2
CPU and CUDA are supported; this adapter never downloads weights.
"""
from __future__ import annotations

import importlib.metadata
import json
import math
from pathlib import Path

from .common import read_json, safe_input, safe_output


def probe() -> dict:
    versions = {}
    try:
        for name in ("SAM-2", "torch", "torchvision", "Pillow"):
            versions[name] = importlib.metadata.version(name)
        from sam2.build_sam import build_sam2  # noqa: F401
        from sam2.sam2_image_predictor import SAM2ImagePredictor  # noqa: F401
        return {"available": True, "reason": "SAM 2 available; a local SAM 2.1 tiny checkpoint and image are required.", "versions": versions}
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return {"available": False, "reason": f"SAM 2 unavailable: {type(exc).__name__}: {exc}", "versions": versions}


def _output_dir(workspace, request):
    return safe_output(workspace, request.get("_output_dir", "runs/extension-runs/sam2") + "/sam2-masks.json").parent


def _prompts(data, tier, width, height):
    if not isinstance(data, dict):
        raise ValueError("prompts must be a JSON object")
    if set(data) - {"points", "labels", "box"}:
        raise ValueError("prompts accepts only points, labels and box")
    points, labels, box = data.get("points"), data.get("labels"), data.get("box")
    if points is None and labels is not None:
        raise ValueError("labels require point coordinates")
    if points is not None:
        if not isinstance(points, list) or not 1 <= len(points) <= 32:
            raise ValueError("points must contain 1..32 image coordinates")
        for p in points:
            if not isinstance(p, list) or len(p) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in p):
                raise ValueError("each point must contain two finite coordinates")
            if not 0 <= p[0] < width or not 0 <= p[1] < height:
                raise ValueError("point must be inside the image")
        if not isinstance(labels, list) or len(labels) != len(points) or any(type(x) is not int or x not in (0, 1) for x in labels):
            raise ValueError("labels must be 0/1, one per point")
    if box is not None:
        if tier == 25:
            raise ValueError("tier 25 accepts point assistance only; choose tier 75 for box-guided segmentation")
        if not isinstance(box, list) or len(box) != 4 or any(type(x) not in (int, float) or not math.isfinite(x) for x in box):
            raise ValueError("box must contain four finite XYXY coordinates")
        if not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
            raise ValueError("box must be a nonempty rectangle inside the image")
    if points is None and box is None:
        raise ValueError("point prompts or a box are required")
    return points, labels, box


def run(request: dict, workspace: Path) -> dict:
    tier = request.get("tier")
    if type(tier) is not int or tier not in (25, 75, 100):
        raise ValueError("tier must be 25, 75 or 100")
    inputs, params = request.get("inputs", {}), request.get("params", {})
    required = {"image", "checkpoint"} if tier == 100 else {"image", "checkpoint", "prompts"}
    if not isinstance(inputs, dict) or set(inputs) != required:
        raise ValueError("inputs must contain exactly " + ", ".join(sorted(required)))
    if not isinstance(params, dict) or set(params) - {"device", "points_per_side"}:
        raise ValueError("params accepts only device and points_per_side")
    if tier != 100 and "points_per_side" in params:
        raise ValueError("points_per_side is used only by tier 100 automatic segmentation")
    checkpoint = safe_input(workspace, inputs.get("checkpoint"))
    image_path = safe_input(workspace, inputs.get("image"))
    if not checkpoint.is_file() or checkpoint.suffix != ".pt":
        raise ValueError("checkpoint must be a local SAM 2.1 tiny .pt weights file")
    device = params.get("device", "cpu")
    if device not in ("cpu", "cuda"):
        raise ValueError("device must be cpu or cuda")
    points_per_side = params.get("points_per_side", 4)
    if type(points_per_side) is not int or not 2 <= points_per_side <= 16:
        raise ValueError("points_per_side must be 2..16")
    import numpy as np
    import torch
    from PIL import Image
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    if device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is unavailable")
    with Image.open(image_path) as opened:
        if max(opened.size) > 2048 or min(opened.size) < 16:
            raise ValueError("image sides must each be 16..2048 pixels")
        image = np.array(opened.convert("RGB"), copy=True)
    height, width = image.shape[:2]
    prompt = None
    if tier != 100:
        prompt = _prompts(read_json(workspace, inputs.get("prompts")), tier, width, height)
    model = build_sam2("configs/sam2.1/sam2.1_hiera_t.yaml", str(checkpoint),
                       device=device, apply_postprocessing=False)
    masks, details = [], []
    with torch.inference_mode():
        if tier == 100:
            from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator
            generator = SAM2AutomaticMaskGenerator(
                model, points_per_side=points_per_side, points_per_batch=4,
                crop_n_layers=0, min_mask_region_area=0, output_mode="binary_mask",
            )
            proposed = generator.generate(image)
            # The bounded proposal grid controls inference; retaining the best 64
            # also bounds file count and downstream records for high-object images.
            proposed = sorted(proposed, key=lambda item: item["predicted_iou"], reverse=True)[:64]
            for item in proposed:
                masks.append(item["segmentation"])
                details.append({"predicted_iou": float(item["predicted_iou"]),
                                "stability_score": float(item["stability_score"]),
                                "area_pixels": int(item["area"]), "bbox_xywh": item["bbox"]})
        else:
            predictor = SAM2ImagePredictor(model)
            predictor.set_image(image)
            points, labels, box = prompt
            predicted, scores, _ = predictor.predict(
                point_coords=np.asarray(points, dtype=np.float32) if points is not None else None,
                point_labels=np.asarray(labels, dtype=np.int32) if labels is not None else None,
                box=np.asarray(box, dtype=np.float32) if box is not None else None,
                multimask_output=tier == 75,
            )
            for mask, score in zip(predicted, scores):
                masks.append(mask.astype(bool))
                details.append({"predicted_iou": float(score), "area_pixels": int(mask.sum())})
    outdir = _output_dir(workspace, request)
    artifacts = []
    for index, (mask, detail) in enumerate(zip(masks, details)):
        if not math.isfinite(detail["predicted_iou"]):
            raise ValueError("SAM returned a non-finite quality estimate")
        filename = outdir / f"mask-{index:02d}.png"
        if filename.is_symlink():
            raise ValueError("output files must not be symbolic links")
        Image.fromarray(mask.astype(np.uint8) * 255).save(filename)
        detail["mask"] = filename.name  # stable across the original run and a clean replay
        artifacts.append(filename.relative_to(workspace.resolve()).as_posix())
    # Masks are local binary artifacts; the text summary is included in the
    # platform's existing research record even when PNGs are left out.
    summary = outdir / "sam2-masks.json"
    if summary.is_symlink():
        raise ValueError("output files must not be symbolic links")
    summary.write_text(json.dumps({"tier": tier, "image_size": [width, height],
                                  "masks": details}, indent=2, allow_nan=False), encoding="utf-8")
    artifacts.append(summary.relative_to(workspace.resolve()).as_posix())
    metrics = {"masks": len(masks), "image_width": width, "image_height": height,
               "total_mask_area_pixels": sum(item["area_pixels"] for item in details)}
    if details:
        metrics["mean_predicted_iou"] = sum(item["predicted_iou"] for item in details) / len(details)
    return {"metrics": metrics, "artifacts": artifacts, "notes": [
        "SAM quality estimates are model predictions, not measured IoU against ground truth.",
        "Image segmentation only. Robotics action inference and LIBERO rollout are separate tasks.",
        "Tier 100 uses a bounded automatic proposal grid; zero surviving masks is a valid result.",
    ]}
