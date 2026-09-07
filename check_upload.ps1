# Compare this folder against GitHub and report anything that never made it up.
# Run:  .\check_upload.ps1
$repo = $PSScriptRoot
Set-Location $repo

if (-not (Test-Path "$repo\.git")) {
    Write-Host "This folder is not a git repo, so nothing here was ever pushed." -ForegroundColor Red
    Write-Host "What is on GitHub came from somewhere else and cannot be compared."
    exit 1
}

git fetch origin master 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "Could not reach GitHub." -ForegroundColor Red; exit 1 }

Write-Host "`nBranch: $(git rev-parse --abbrev-ref HEAD)"
$counts = (git rev-list --left-right --count origin/master...HEAD) -split '\s+'
Write-Host "Behind GitHub master: $($counts[0]) commit(s)"
Write-Host "Ahead  of it:         $($counts[1]) commit(s)  <- these are NOT on GitHub"

$dirty = git status --porcelain
if ($dirty) {
    Write-Host "`nEdited or new, not committed (NOT on GitHub):" -ForegroundColor Yellow
    $dirty | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "`nNo uncommitted changes."
}

# .gitignore hides *.txt, data/ and model weights, so real source can vanish silently.
$hidden = git status --porcelain --ignored |
    Where-Object { $_ -match '^!! ' -and $_ -notmatch '__pycache__|\.pytest_cache|\.venv|/$' }
if ($hidden) {
    Write-Host "`nIgnored by .gitignore, so never uploaded:" -ForegroundColor Yellow
    $hidden | ForEach-Object { Write-Host "  $_" }
    Write-Host "  (.env and data/ are meant to stay local. Anything else here is a real gap.)"
}

Write-Host "`nIf all three sections are empty, GitHub has everything." -ForegroundColor Green
