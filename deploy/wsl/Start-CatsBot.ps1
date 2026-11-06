[CmdletBinding()]
param([string]$DistroName = 'CatsBot')

$ErrorActionPreference = 'Stop'
$taskLog = Join-Path $PSScriptRoot 'launcher.log'

while ($true) {
    # Bound the host log. Linux application logs are rotated separately.
    if ((Test-Path -LiteralPath $taskLog) -and (Get-Item -LiteralPath $taskLog).Length -gt 2MB) {
        Move-Item -LiteralPath $taskLog -Destination ($taskLog + '.previous') -Force
    }
    Add-Content -LiteralPath $taskLog -Value ('{0:o} Starting {1}' -f (Get-Date), $DistroName)
    try {
        & "$env:SystemRoot\System32\wsl.exe" --distribution $DistroName --user root --exec /usr/local/sbin/catsbot-keepalive >> $taskLog 2>&1
        Add-Content -LiteralPath $taskLog -Value ('{0:o} WSL exited: {1}; retry in 15 seconds' -f (Get-Date), $LASTEXITCODE)
    }
    catch {
        Add-Content -LiteralPath $taskLog -Value ('{0:o} {1}; retry in 15 seconds' -f (Get-Date), $_.Exception.Message)
    }
    Start-Sleep -Seconds 15
}
