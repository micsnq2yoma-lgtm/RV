[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$CardRoot,

    [string]$ManifestPath = (Join-Path $PSScriptRoot '..\MANIFEST.tsv'),

    [ValidateRange(1, 1000000)]
    [int]$ExpectedCount = 152
)

# Read-only size verification. Works on either the source folder or a mounted card.
# No filesystem or disk configuration changes are made by this script.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$resolvedRoot = (Resolve-Path -LiteralPath $CardRoot).ProviderPath
if (-not (Get-Item -LiteralPath $resolvedRoot).PSIsContainer) {
    throw 'CardRoot must be a directory or volume root.'
}
$rootPrefix = $resolvedRoot.TrimEnd([char[]]'\/') + [IO.Path]::DirectorySeparatorChar
$checked = 0
$missing = 0
$sizeMismatch = 0

foreach ($line in Get-Content -LiteralPath $ManifestPath -Encoding utf8) {
    if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith('#')) { continue }
    $fields = $line.Split("`t")
    if ($fields.Count -ne 2) { throw 'Invalid manifest row: expected path and size separated by a tab.' }
    if (-not $fields[0].StartsWith('tf-card/', [StringComparison]::Ordinal)) { continue }

    $relative = $fields[0].Substring('tf-card/'.Length)
    $expectedSize = [long]0
    if ([string]::IsNullOrWhiteSpace($relative) -or
        -not [long]::TryParse($fields[1], [ref]$expectedSize) -or $expectedSize -lt 0) {
        throw 'Invalid card manifest path or size.'
    }
    $nativeRelative = $relative.Replace('/', [IO.Path]::DirectorySeparatorChar)
    $targetPath = [IO.Path]::GetFullPath((Join-Path $resolvedRoot $nativeRelative))
    if (-not $targetPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Manifest path escapes CardRoot.'
    }

    $checked++
    if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
        Write-Output ('MISSING ' + $relative)
        $missing++
        continue
    }
    $actualSize = (Get-Item -LiteralPath $targetPath).Length
    if ($actualSize -ne $expectedSize) {
        Write-Output ('SIZE ' + $relative + ' expected=' + $expectedSize + ' actual=' + $actualSize)
        $sizeMismatch++
    }
}

Write-Output ('checked=' + $checked + ' missing=' + $missing + ' size_mismatch=' + $sizeMismatch)
if ($checked -ne $ExpectedCount) {
    throw ('Expected ' + $ExpectedCount + ' tf-card entries, found ' + $checked)
}
if ($missing -ne 0 -or $sizeMismatch -ne 0) { exit 1 }
exit 0
