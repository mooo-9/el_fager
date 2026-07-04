# Install the committed git hooks into .git/hooks (run once after clone).
$repo = Split-Path -Parent $PSScriptRoot
Copy-Item "$PSScriptRoot\pre-push" "$repo\.git\hooks\pre-push" -Force
Write-Host "Installed pre-push hook: pytest must pass before any push."
