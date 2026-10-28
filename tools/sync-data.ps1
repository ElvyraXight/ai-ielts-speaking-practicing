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

# 私有仓库用单独的 deploy key：.ssh-data\ssh_data.bat 会把 -F 配置传给 ssh。
# 注意：仓库级的 core.sshCommand 优先级高于 GIT_SSH，而全局配置里可能已经设了
# 一个（代码仓库用的）. 所以这里给数据仓库单独写一份仓库级 core.sshCommand，
# 克隆时用 -c 临时指定，避免被全局配置顶掉。
$wrapper = Join-Path $root '.ssh-data\ssh_data.bat'
$has_wrapper = Test-Path $wrapper
$ssh_wrapper = ''
if ($has_wrapper) {
    $env:GIT_SSH = $wrapper
    $ssh_wrapper = $wrapper -replace '\\', '/'
}

if (-not (Test-Path (Join-Path $repo '.git'))) {
    if (Test-Path $repo) { Remove-Item $repo -Recurse -Force }
    Write-Host "cloning $Remote ..."
    if ($has_wrapper) {
        git -c "core.sshCommand=$ssh_wrapper" clone $Remote $repo
    } else {
        git clone $Remote $repo
    }
    if ($LASTEXITCODE -ne 0) { throw "clone failed: $Remote （私有仓库要先在 GitHub 上创建，并添加 .ssh-data\ielts_data.pub 为 deploy key）" }
}

if ($has_wrapper) {
    git -C $repo config core.sshCommand $ssh_wrapper
}

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
Get-ChildItem -Path $source -Filter '*.json' -File | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $dataDir $_.Name) -Force
}

if (-not (git -C $repo remote)) {
    git -C $repo remote add origin $Remote
}

git -C $repo add -A
$pending = git -C $repo status --porcelain
if ($pending) {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'
    git -C $repo commit -m "sync $stamp" | Out-Null
    Write-Host "committed: $stamp"
} else {
    Write-Host 'no local changes.'
}

git -C $repo push origin HEAD
if ($LASTEXITCODE -ne 0) { throw 'push failed' }
Write-Host 'pushed.'
