<#
.SYNOPSIS
Forward the board's loopback proxy port to this PC's loopback proxy over SSH.
.EXAMPLE
./scripts/board_proxy_tunnel.ps1 -BoardIP 192.168.50.2 -ProxyPort 7897
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$BoardIP,
    [ValidateRange(1, 65535)]
    [int]$ProxyPort = 7897,
    [string]$KnownHostsFile
)
$ErrorActionPreference = 'Stop'
$boardAddress = $null
if (-not [Net.IPAddress]::TryParse($BoardIP, [ref]$boardAddress)) {
    throw 'BoardIP must be an IPv4 or IPv6 address.'
}
$sshExecutable = (Get-Command ssh -CommandType Application -ErrorAction Stop).Source
$sshArguments = @('-N', '-T', '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
    '-o', 'ConnectTimeout=10', '-o', 'NumberOfPasswordPrompts=1',
    '-o', 'ProxyCommand=none', '-o', 'ProxyJump=none')
if ($KnownHostsFile) {
    if (-not (Test-Path -LiteralPath $KnownHostsFile -PathType Leaf)) {
        throw 'KnownHostsFile must identify an existing trusted file.'
    }
    $knownHostsPath = (Resolve-Path -LiteralPath $KnownHostsFile).ProviderPath.Replace('\', '/')
    $sshArguments += @('-o', ('UserKnownHostsFile="' + $knownHostsPath + '"'), '-o', 'StrictHostKeyChecking=yes')
}
$sshArguments += @('-R', ('127.0.0.1:{0}:127.0.0.1:{0}' -f $ProxyPort), '--', ('root@' + $boardAddress.ToString()))
Write-Host ('开发板 127.0.0.1:{0} -> 电脑 127.0.0.1:{0}。按 Ctrl+C 关闭。' -f $ProxyPort)
& $sshExecutable @sshArguments
exit $LASTEXITCODE
