# tools/sync-data.ps1
# Copy data\*.json into the private backup repo and push it.
# First run: clones the private repo into .data-repo (it must already exist on GitHub).

param(
    [string]$Remote = 'git@github.com:ElvyraXight/ai-ielts-speaking-data.git'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$repo = Join-Path $root '.data-repo'
$dataDir = Join-Path $repo 'data'
$source = Join-Path $root 'data'

if (-not (Test-Path (Join-Path $repo '.git'))) {
    if (Test-Path $repo) { Remove-Item $repo -Recurse -Force }
    Write-Host "cloning $Remote ..."
    git clone $Remote $repo
    if ($LASTEXITCODE -ne 0) { throw "clone failed: $Remote （私有仓库要先在 GitHub 上创建）" }
}

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
Get-ChildItem -Path $source -Filter '*.json' -File | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $dataDir $_.Name) -Force
}

git -C $repo add -A
$pending = git -C $repo status --porcelain
if (-not $pending) {
    Write-Host 'nothing changed.'
    exit 0
}

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'
git -C $repo commit -m "sync $stamp" | Out-Null
git -C $repo push origin HEAD
if ($LASTEXITCODE -ne 0) { throw 'push failed' }
Write-Host "synced at $stamp"
