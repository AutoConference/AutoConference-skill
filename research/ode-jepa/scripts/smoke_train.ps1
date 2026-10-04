# Smoke-train B1 on synthetic sequences (CPU or CUDA).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$CondaPy = Join-Path $env:USERPROFILE ".conda\envs\ode-jepa\python.exe"
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $CondaPy) {
    $Py = $CondaPy
    Write-Host "[smoke] using conda env ode-jepa: $Py"
} elseif (Test-Path $VenvPy) {
    $Py = $VenvPy
    Write-Host "[smoke] using venv python: $Py"
} else {
    $Py = (Get-Command python -ErrorAction Stop).Source
    Write-Host "[smoke] using system python: $Py"
}

& $Py -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
if ($LASTEXITCODE -ne 0) {
    Write-Error "torch not importable. conda create -n ode-jepa python=3.10; pip install torch --index-url https://download.pytorch.org/whl/cu124"
    exit 1
}

$Device = "cpu"
$cuda = & $Py -c "import torch; print('1' if torch.cuda.is_available() else '0')"
if ($cuda.Trim() -eq "1") { $Device = "cuda" }

& $Py -m ode_jepa.train --config configs/b1_jepa.yaml --max-steps 10 --device $Device
exit $LASTEXITCODE
