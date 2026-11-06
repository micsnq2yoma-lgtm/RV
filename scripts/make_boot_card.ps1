# Task 003 administrator helper. Run only after live confirmation of this disk.
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
    }
    $state | ConvertTo-Json | Set-Content -LiteralPath $StatusPath -Encoding utf8
}

try {
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Administrator token required; no disk operation performed.'
    }
    $disk = Get-Disk -Number $ConfirmedDiskNumber
    $parts = @(Get-Partition -DiskNumber $ConfirmedDiskNumber | Sort-Object PartitionNumber)
    $model = Get-CimInstance Win32_DiskDrive -Filter ('Index=' + $ConfirmedDiskNumber) |
        Select-Object -ExpandProperty Model
    if ($disk.Size -ne 31914983424 -or $disk.IsSystem -or $disk.IsBoot -or
        $disk.BusType -notin @('USB', 'SD') -or $disk.PartitionStyle -ne 'GPT' -or
        $parts.Count -ne 2 -or $parts[0].Size -ne 1073741824 -or
        $parts[1].Size -ne 30486298624 -or $model.Trim() -ne 'SDHC Card') {
        throw 'Disk identity or original partition layout changed; abort without writes.'
    }
    Write-CardLog ('ADMIN_RECHECK ' + ($disk | Select-Object Number,BusType,Size,PartitionStyle,IsSystem,IsBoot |
        ConvertTo-Json -Compress))
    Write-CardLog ('ADMIN_RECHECK_MODEL=' + $model)
    Save-CardStatus $false

    $phase = 'Clear-Disk'
    Write-CardLog ('COMMAND: Clear-Disk -Number ' + $ConfirmedDiskNumber + ' -RemoveData -RemoveOEM -Confirm:$false')
    Save-CardStatus $false
    Clear-Disk -Number $ConfirmedDiskNumber -RemoveData -RemoveOEM -Confirm:$false

    $phase = 'Initialize-Disk'
    Write-CardLog ('COMMAND: Initialize-Disk -Number ' + $ConfirmedDiskNumber + ' -PartitionStyle MBR')
    Save-CardStatus $false
    Initialize-Disk -Number $ConfirmedDiskNumber -PartitionStyle MBR | Out-Null
    Write-CardLog ('INITIALIZED ' + (Get-Disk -Number $ConfirmedDiskNumber |
        Select-Object Number,PartitionStyle,Size | ConvertTo-Json -Compress))

    $phase = 'New-Partition'
    Write-CardLog ('COMMAND: New-Partition -DiskNumber ' + $ConfirmedDiskNumber + ' -UseMaximumSize -MbrType FAT32 -AssignDriveLetter')
    Save-CardStatus $false
    $partition = New-Partition -DiskNumber $ConfirmedDiskNumber -UseMaximumSize -MbrType FAT32 -AssignDriveLetter
    Write-CardLog ('PARTITION ' + ($partition |
        Select-Object DiskNumber,PartitionNumber,DriveLetter,Offset,Size,MbrType | ConvertTo-Json -Compress))

    $phase = 'Format-Volume'
    Write-CardLog 'COMMAND: Format-Volume -Partition <new partition on confirmed disk> -FileSystem FAT32 -NewFileSystemLabel RVBOOT -Confirm:$false'
    Save-CardStatus $false
    Format-Volume -Partition $partition -FileSystem FAT32 -NewFileSystemLabel RVBOOT -Confirm:$false | Out-Null
    $volume = Get-Partition -DiskNumber $ConfirmedDiskNumber -PartitionNumber $partition.PartitionNumber | Get-Volume
    Write-CardLog ('VOLUME ' + ($volume |
        Select-Object DriveLetter,FileSystemLabel,FileSystem,Size,HealthStatus | ConvertTo-Json -Compress))
    if ($volume.FileSystem -ne 'FAT32') { throw 'Formatted filesystem is not FAT32; stop for task-approved fallback review.' }
    if ([string]::IsNullOrEmpty([string]$volume.DriveLetter)) { throw 'No drive letter assigned; stop.' }

    $phase = 'done'
    Save-CardStatus $true
    Write-CardLog 'FORMAT_COMPLETED; full-card partition used; no 16 GiB fallback.'
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
