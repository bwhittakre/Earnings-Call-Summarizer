param([string]$ImageUri = "example.invalid/earnings-monitor:synth")

$ErrorActionPreference = "Stop"
$infra = Resolve-Path "$PSScriptRoot/../../infra/aws"
Push-Location $infra
try {
    if (-not (Test-Path ".venv")) {
        python -m venv .venv
    }
    & .venv/Scripts/python -m pip install --requirement requirements.txt
    & .venv/Scripts/python -m pytest
    npx --yes aws-cdk synth -c "container_image=$ImageUri"
}
finally {
    Pop-Location
}
