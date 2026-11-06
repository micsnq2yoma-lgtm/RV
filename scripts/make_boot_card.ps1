# Task 003 addendum 1. Run only after live confirmation of the empty GPT disk.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(0, 128)]
    [int]$ConfirmedDiskNumber,

    [Parameter(Mandatory = $true)]
    [string]$LogPath,

    [Parameter(Mandatory = $true)]
    [string]$StatusPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$phase = 'preflight'
$usedFallback = $false

function Write-CardLog([string]$Message) {
    $entry = '[' + (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss.fffzzz') + '] ' + $Message
    Add-Content -LiteralPath $LogPath -Value $entry -Encoding utf8
}

function Save-CardStatus([bool]$Completed, [string]$ErrorText = '') {
    $state = [ordered]@{
        disk_number = $ConfirmedDiskNumber
        phase = $phase
        completed = $Completed
        error = $ErrorText
        time = (Get-Date -Format o)
    }
    if ($Completed) {
        $state['partition_number'] = $partition.PartitionNumber
        $state['drive_letter'] = [string]$volume.DriveLetter
        $state['file_system'] = [string]$volume.FileSystem
        $state['label'] = [string]$volume.FileSystemLabel
        $state['volume_size'] = $volume.Size
        $state['partition_size'] = $partition.Size
        $state['fallback_16_gib'] = $usedFallback
    }
    $state | ConvertTo-Json | Set-Content -LiteralPath $StatusPath -Encoding utf8
}

try {
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Administrator token required; no disk operation performed.'
    }
    $disk = Get-Disk -Number $ConfirmedDiskNumber
    $parts = @(Get-Partition -DiskNumber $ConfirmedDiskNumber -ErrorAction SilentlyContinue)
    $model = Get-CimInstance Win32_DiskDrive -Filter ('Index=' + $ConfirmedDiskNumber) |
        Select-Object -ExpandProperty Model
    if ($disk.Size -ne 31914983424 -or $disk.IsSystem -or $disk.IsBoot -or
        $disk.BusType -notin @('USB', 'SD') -or $disk.PartitionStyle -ne 'GPT' -or
        $disk.NumberOfPartitions -ne 0 -or $parts.Count -ne 0 -or
        ([string]$model).Trim() -ne 'SDHC Card') {
        throw 'Disk identity or empty GPT layout does not match; abort without writes.'
    }
    Write-CardLog ('ADMIN_RECHECK ' + ($disk | Select-Object Number,BusType,Size,PartitionStyle,IsSystem,IsBoot |
        ConvertTo-Json -Compress))
    Write-CardLog ('ADMIN_RECHECK_MODEL=' + $model + ' partition_count=0')
    Save-CardStatus $false

    $phase = 'Set-Disk'
    Write-CardLog ('COMMAND: Set-Disk -Number ' + $ConfirmedDiskNumber + ' -PartitionStyle MBR')
    Save-CardStatus $false
    Set-Disk -Number $ConfirmedDiskNumber -PartitionStyle MBR
    $converted = Get-Disk -Number $ConfirmedDiskNumber
    Write-CardLog ('CONVERTED ' + ($converted |
        Select-Object Number,PartitionStyle,Size,NumberOfPartitions | ConvertTo-Json -Compress))
    if ($converted.PartitionStyle -ne 'MBR' -or $converted.NumberOfPartitions -ne 0) {
        throw 'MBR readback did not confirm an empty MBR disk; stop.'
    }

    $phase = 'New-Partition'
    Write-CardLog ('COMMAND: New-Partition -DiskNumber ' + $ConfirmedDiskNumber + ' -UseMaximumSize -MbrType FAT32 -AssignDriveLetter')
    Save-CardStatus $false
    $partition = New-Partition -DiskNumber $ConfirmedDiskNumber -UseMaximumSize -MbrType FAT32 -AssignDriveLetter
    Write-CardLog ('PARTITION ' + ($partition |
        Select-Object DiskNumber,PartitionNumber,DriveLetter,Offset,Size,MbrType | ConvertTo-Json -Compress))

    $phase = 'Format-Volume'
    Write-CardLog 'COMMAND: Format-Volume -Partition <new partition on confirmed disk> -FileSystem FAT32 -NewFileSystemLabel RVBOOT -Confirm:$false'
    Save-CardStatus $false
    $needsFallback = $false
    try {
        Format-Volume -Partition $partition -FileSystem FAT32 -NewFileSystemLabel RVBOOT -Confirm:$false | Out-Null
        $volume = Get-Partition -DiskNumber $ConfirmedDiskNumber -PartitionNumber $partition.PartitionNumber | Get-Volume
        $needsFallback = $volume.FileSystem -ne 'FAT32'
    } catch {
        if ($_.Exception.Message -notmatch '(?i)too (large|big)|size (is )?(not supported|unsupported)|超出.*大小|卷.*过大|大小.*不支持') { throw }
        Write-CardLog ('FULL_VOLUME_FORMAT_REJECTED: ' + $_.Exception.Message)
        $needsFallback = $true
    }
    if ($needsFallback) {
        $phase = 'FAT32-16GiB-fallback'
        Save-CardStatus $false
        $disk = Get-Disk -Number $ConfirmedDiskNumber
        $current = @(Get-Partition -DiskNumber $ConfirmedDiskNumber)
        if ($disk.Size -ne 31914983424 -or $disk.IsSystem -or $disk.IsBoot -or
            $disk.BusType -notin @('USB', 'SD') -or $disk.PartitionStyle -ne 'MBR' -or
            $current.Count -ne 1 -or $current[0].PartitionNumber -ne $partition.PartitionNumber -or
            $current[0].Offset -ne $partition.Offset -or $current[0].Size -ne $partition.Size) {
            throw 'Target partition changed; refuse the 16 GiB fallback.'
        }
        Write-CardLog 'FAT32_FALLBACK: remove only the just-created partition; create and format a 16 GiB partition.'
        Remove-Partition -DiskNumber $ConfirmedDiskNumber -PartitionNumber $partition.PartitionNumber -Confirm:$false
        $partition = New-Partition -DiskNumber $ConfirmedDiskNumber -Size 16GB -MbrType FAT32 -AssignDriveLetter
        Format-Volume -Partition $partition -FileSystem FAT32 -NewFileSystemLabel RVBOOT -Confirm:$false | Out-Null
        $volume = Get-Partition -DiskNumber $ConfirmedDiskNumber -PartitionNumber $partition.PartitionNumber | Get-Volume
        $usedFallback = $true
    }
    Write-CardLog ('VOLUME ' + ($volume |
        Select-Object DriveLetter,FileSystemLabel,FileSystem,Size,HealthStatus | ConvertTo-Json -Compress))
    if ($volume.FileSystem -ne 'FAT32' -or $volume.FileSystemLabel -ne 'RVBOOT') { throw 'Final FAT32/RVBOOT readback did not match; stop.' }
    if ([string]::IsNullOrEmpty([string]$volume.DriveLetter)) { throw 'No drive letter assigned; stop.' }

    $phase = 'done'
    Save-CardStatus $true
    Write-CardLog ('FORMAT_COMPLETED fallback_16_gib=' + $usedFallback)
    exit 0
}
catch {
    $failure = ($_ | Out-String).TrimEnd()
    Write-CardLog ('FAILED_PHASE=' + $phase)
    foreach ($line in ($failure -split "`r?`n")) { Write-CardLog $line }
    try {
        Write-CardLog ('CURRENT_DISK ' + (Get-Disk -Number $ConfirmedDiskNumber |
            Select-Object Number,Size,PartitionStyle,IsSystem,IsBoot | ConvertTo-Json -Compress))
    } catch { Write-CardLog 'Unable to read current disk state after failure.' }
    Save-CardStatus $false $failure
    exit 1
}
