# 首次推送：需先 gh auth login
$ErrorActionPreference = "Stop"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
Set-Location $PSScriptRoot\..

$repoName = if ($args[0]) { $args[0] } else { "etf-consensus" }

gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "请先登录 GitHub: gh auth login" -ForegroundColor Yellow
    gh auth login -h github.com -p https -w
}

if (-not (git remote get-url origin 2>$null)) {
    gh repo create $repoName --public --source=. --remote=origin --description "ETF consensus daily scan and portfolio backtest for Cursor Automations"
} else {
    Write-Host "remote origin 已存在"
}

git push -u origin HEAD
Write-Host "完成。请在 Cursor Automations 中绑定: $(gh repo view --json url -q .url)"
