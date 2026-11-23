param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'release_2025.py') sync --destination $Destination
if ($LASTEXITCODE -ne 0) { throw '2025 sync failed. Original 2024 project must stay unchanged.' }
