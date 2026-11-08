<#
.SYNOPSIS
Run a command as root on the board and preserve ssh's output and exit code.
.EXAMPLE
./scripts/board_ssh.ps1 192.168.137.50 'uname -a'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$BoardIP,
    [Parameter(Mandatory = $true, Position = 1)]
    [string]$Command,
    [string]$KnownHostsFile
)

$ErrorActionPreference = 'Stop'
$boardAddress = $null
if (-not [System.Net.IPAddress]::TryParse($BoardIP, [ref]$boardAddress)) {
    throw 'BoardIP must be an IPv4 or IPv6 address.'
}
$sshExecutable = (Get-Command ssh -CommandType Application -ErrorAction Stop).Source
$sshArguments = @('-o', 'ConnectTimeout=10', '-o', 'NumberOfPasswordPrompts=1', '-o', 'ProxyCommand=none', '-o', 'ProxyJump=none')
if ($KnownHostsFile) {
    if (-not (Test-Path -LiteralPath $KnownHostsFile -PathType Leaf)) {
        throw 'KnownHostsFile must identify an existing file.'
    }
    $knownHostsPath = (Resolve-Path -LiteralPath $KnownHostsFile -ErrorAction Stop).ProviderPath
    $knownHostsPath = $knownHostsPath.Replace('\', '/')
    $sshArguments += @('-o', ('UserKnownHostsFile="' + $knownHostsPath + '"'), '-o', 'StrictHostKeyChecking=yes')
}
$sshArguments += @('--', ('root@' + $boardAddress.ToString()), $Command)
& $sshExecutable @sshArguments
exit $LASTEXITCODE
