# Phase-1 B0/B1/B2 on CUDA (synthetic LIBERO stand-in if HDF5 missing).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$CondaPy = Join-Path $env:USERPROFILE ".conda\envs\ode-jepa\python.exe"
if (-not (Test-Path $CondaPy)) {
    Write-Error "Missing conda env python: $CondaPy"
    exit 1
}
$Py = $CondaPy
Write-Host "[phase1] python=$Py"
& $Py -c "import torch; assert torch.cuda.is_available(), 'CUDA required'; print(torch.cuda.get_device_name(0))"

New-Item -ItemType Directory -Force -Path "outputs\phase1" | Out-Null

foreach ($cfg in @(
    "configs\phase1_b0_jvp.yaml",
    "configs\phase1_b1_jepa.yaml",
    "configs\phase1_b2_hybrid.yaml"
)) {
    Write-Host "`n[phase1] === training $cfg ==="
    & $Py -m ode_jepa.train --config $cfg --device cuda:0
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "`n[phase1] all ablations finished"
Get-ChildItem outputs\phase1\metrics_*.json | ForEach-Object { Write-Host $_.FullName }
