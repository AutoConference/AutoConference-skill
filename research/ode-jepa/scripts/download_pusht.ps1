# Download + decompress official LeWM PushT HDF5 into $STABLEWM_HOME
$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $env:STABLEWM_HOME) {
  $env:STABLEWM_HOME = Join-Path (Split-Path $PSScriptRoot -Parent) "data\stable-wm"
}
New-Item -ItemType Directory -Force -Path $env:STABLEWM_HOME | Out-Null
Write-Host "STABLEWM_HOME=$env:STABLEWM_HOME"

$py = Join-Path $env:USERPROFILE ".conda\envs\ode-jepa\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

& $py -m pip install -U "huggingface_hub[cli]" zstandard h5py 2>&1 | Select-Object -Last 20

$dst = Join-Path $env:STABLEWM_HOME "hf_pusht"
New-Item -ItemType Directory -Force -Path $dst | Out-Null

Write-Host "Downloading quentinll/lewm-pusht ..."
hf download quentinll/lewm-pusht --repo-type dataset --local-dir $dst

$zst = Join-Path $dst "pusht_expert_train.h5.zst"
$h5 = Join-Path $env:STABLEWM_HOME "pusht_expert_train.h5"
if (-not (Test-Path $zst)) { throw "Missing $zst after download" }

if (-not (Test-Path $h5)) {
  Write-Host "Decompressing $zst -> $h5 ..."
  & $py -c @"
import zstandard as zstd, pathlib, sys
src = pathlib.Path(r'$zst')
dst = pathlib.Path(r'$h5')
dctx = zstd.ZstdDecompressor()
with src.open('rb') as fi, dst.open('wb') as fo:
    dctx.copy_stream(fi, fo)
print('wrote', dst, 'bytes', dst.stat().st_size)
"@
} else {
  Write-Host "HDF5 already present: $h5"
}

& $py -c @"
from pathlib import Path
import sys
sys.path.insert(0, r'$(Split-Path $PSScriptRoot -Parent)')
from ode_jepa.pusht_h5 import verify_h5
print(verify_h5(Path(r'$h5')))
"@
