<#
.SYNOPSIS
Configure eth0 and UTC over an already logged-in Buildroot serial shell.
.EXAMPLE
./scripts/board_bootstrap.ps1 -Port COM3
#>
[CmdletBinding()]
param(
    [string]$Port = 'COM3',
    [string]$Python,
    [string]$LogPath
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $repo '.venv/Scripts/python.exe' }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'Specify -Python with a Python executable that has pyserial installed.'
}
if (-not $LogPath) { $LogPath = Join-Path $repo '.venv/board-bootstrap.log' }
$logDirectory = Split-Path -Parent ([IO.Path]::GetFullPath($LogPath))
[void][IO.Directory]::CreateDirectory($logDirectory)
$body = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'board_net_up.sh')).Replace("`r`n", "`n")
$utc = [DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss')
# The shell file is used directly; keep configuration logic in one place.
$command = "set -- '$utc'`n" + $body
$temporary = [IO.Path]::GetTempFileName()
try {
    [IO.File]::WriteAllText($temporary, $command, [Text.UTF8Encoding]::new($false))
    Write-Host 'Requires a logged-in Buildroot shell and a released serial port.'
    & $Python (Join-Path $PSScriptRoot 'serial_console.py') --port $Port --baud 115200 --log $LogPath --timeout 20 exec --command-file $temporary
    $result = $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath $temporary -Force
}
exit $result
