# Assembles deploy\hf-space\build\: everything the Space needs, in the layout the
# scorer expects (see Dockerfile). Run from anywhere:
#
#   powershell -File deploy\hf-space\prepare.ps1
#   powershell -File deploy\hf-space\prepare.ps1 -Model final-model-child-augmented-v1 -Calibration calibration-child-augmented.json
#
# Then upload `build` to the Space (see DEPLOY.md). Nothing here touches the network.
param(
    [string]$Model = 'final-model-v2',
    [string]$Calibration = 'calibration.json'
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$repo = Resolve-Path (Join-Path $here '..\..')
$build = Join-Path $here 'build'

if (Test-Path $build) { Remove-Item -Recurse -Force $build }
New-Item -ItemType Directory -Path $build | Out-Null

foreach ($f in 'Dockerfile', 'requirements.txt', 'README.md', 'app.py') {
    Copy-Item (Join-Path $here $f) $build
}

function Copy-Clean($from, $to) {
    New-Item -ItemType Directory -Path $to -Force | Out-Null
    Copy-Item -Recurse -Force (Join-Path $from '*') $to
    Get-ChildItem $to -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
}

Copy-Clean (Join-Path $repo 'gop\basaquest_gop') (Join-Path $build 'gop\basaquest_gop')
Copy-Item (Join-Path $repo "gop\$Calibration") (Join-Path $build 'gop\calibration.json')
Copy-Clean (Join-Path $repo 'g2p\filipino_g2p') (Join-Path $build 'g2p\filipino_g2p')

# The model: what the scorer loads. training_args.bin is training bookkeeping, not needed.
$modelSource = Join-Path $repo "models\$Model"
$modelTarget = Join-Path $build 'models\final-model-v2'
New-Item -ItemType Directory -Path $modelTarget -Force | Out-Null
Get-ChildItem $modelSource -File | Where-Object { $_.Name -ne 'training_args.bin' } | Copy-Item -Destination $modelTarget

# The CPU build of torch, fetched here from the fast address (see the Dockerfile for why
# the image build does not download it itself). Skipped if the file is already there.
$wheelName = 'torch-2.15.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl'
$wheelDir = Join-Path $build 'wheels'
New-Item -ItemType Directory -Path $wheelDir -Force | Out-Null
$wheelPath = Join-Path $wheelDir $wheelName
$wheelCache = Join-Path $here $wheelName
if (-not (Test-Path $wheelCache)) {
    Write-Host 'Downloading the CPU build of torch (about 210 MB)...'
    curl.exe -L --fail --retry 5 -o $wheelCache ('https://download.pytorch.org/whl/cpu/torch-2.15.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl')
}
Copy-Item $wheelCache $wheelPath

$size = [math]::Round(((Get-ChildItem $build -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB)
Write-Host "Built $build ($size MB) from model '$Model' and calibration '$Calibration'."
