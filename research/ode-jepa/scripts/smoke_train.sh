#!/usr/bin/env bash
# Smoke-train B1 on synthetic sequences (CPU or CUDA).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CONDA_PY="${HOME}/.conda/envs/ode-jepa/python"
if [[ -x "$CONDA_PY" ]]; then
  PY="$CONDA_PY"
  echo "[smoke] using conda env ode-jepa: $PY"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
  echo "[smoke] using venv python: $PY"
else
  PY="${PYTHON:-python3}"
  echo "[smoke] using system python: $PY"
fi

"$PY" -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
DEVICE="$("$PY" -c "import torch; print('cuda' if torch.cuda.is_available() else 'cpu')")"
"$PY" -m ode_jepa.train --config configs/b1_jepa.yaml --max-steps 10 --device "$DEVICE"
