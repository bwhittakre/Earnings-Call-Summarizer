param(
    [Parameter(Mandatory = $true)][string]$RepositoryUri,
    [string]$Tag = (git rev-parse --short HEAD),
    [string]$Region = "us-east-1"
)

$ErrorActionPreference = "Stop"
$registry = $RepositoryUri.Split("/")[0]

aws ecr get-login-password --region $Region |
    docker login --username AWS --password-stdin $registry

docker buildx build `
    --platform linux/amd64,linux/arm64 `
    --file services/earnings_monitor/Dockerfile `
    --tag "${RepositoryUri}:${Tag}" `
    --push .

Write-Output "${RepositoryUri}:${Tag}"
