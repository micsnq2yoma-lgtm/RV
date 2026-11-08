<#
.SYNOPSIS
Transfer one file to or from the board using its legacy SCP service.
.EXAMPLE
./scripts/board_scp.ps1 192.168.137.50 ./example.txt /tmp/example.txt
.EXAMPLE
./scripts/board_scp.ps1 192.168.137.50 ./download.txt /tmp/example.txt -Download
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$BoardIP,
    [Parameter(Mandatory = $true, Position = 1)]
    [string]$LocalPath,
    [Parameter(Mandatory = $true, Position = 2)]
    [string]$RemotePath,
    [switch]$Download,
    [string]$KnownHostsFile
)

$ErrorActionPreference = 'Stop'
$boardAddress = $null
if (-not [System.Net.IPAddress]::TryParse($BoardIP, [ref]$boardAddress)) {
    throw 'BoardIP must be an IPv4 or IPv6 address.'
}
if (-not $RemotePath.StartsWith('/') -or $RemotePath -match '[\r\n]') {
    throw 'RemotePath must be an absolute POSIX path without line breaks.'
}
if (-not $Download) {
    if (-not (Test-Path -LiteralPath $LocalPath -PathType Leaf)) {
        throw 'LocalPath must identify an existing file for upload.'
    }
    $LocalPath = (Resolve-Path -LiteralPath $LocalPath).ProviderPath
}

# Quote the path for the remote shell used by legacy SCP, including apostrophes.
$singleQuote = "'"
$escapedSingleQuote = $singleQuote + '"' + $singleQuote + '"' + $singleQuote
$quotedRemotePath = $singleQuote + $RemotePath.Replace($singleQuote, $escapedSingleQuote) + $singleQuote
$remoteHost = $boardAddress.ToString()
if ($boardAddress.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetworkV6) {
    $remoteHost = '[' + $remoteHost + ']'
}
$remoteTarget = 'root@' + $remoteHost + ':' + $quotedRemotePath
$scpExecutable = (Get-Command scp -CommandType Application -ErrorAction Stop).Source
# Buildroot's sshd has no verified SFTP subsystem, so use its SCP endpoint.
$scpArguments = @('-O', '-o', 'ConnectTimeout=10', '-o', 'NumberOfPasswordPrompts=1', '-o', 'ProxyCommand=none', '-o', 'ProxyJump=none')
if ($KnownHostsFile) {
    if (-not (Test-Path -LiteralPath $KnownHostsFile -PathType Leaf)) {
        throw 'KnownHostsFile must identify an existing file.'
    }
    $knownHostsPath = (Resolve-Path -LiteralPath $KnownHostsFile -ErrorAction Stop).ProviderPath
    $knownHostsPath = $knownHostsPath.Replace('\', '/')
    $scpArguments += @('-o', ('UserKnownHostsFile="' + $knownHostsPath + '"'), '-o', 'StrictHostKeyChecking=yes')
}
if ($Download) {
    & $scpExecutable @scpArguments '--' $remoteTarget $LocalPath
} else {
    & $scpExecutable @scpArguments '--' $LocalPath $remoteTarget
}
exit $LASTEXITCODE
