# 任务 002 补充 1：TF 卡已插到 Windows 主机上

- **补充的任务**：`002-new-image-full-boot.md`
- **作者**：Claude
- **日期**：2026-11-05
- **起因**：人已经把一张 TF 卡插到了 Windows 主机上，让 Codex 接手完成后续步骤。还不确定这张卡是开发板上取下来的那张，还是一张新卡。

本补充替换任务 002 的第 1 步，第 2–5 步按下面的写法执行。B 节及之后的步骤不变。

## 0. 分支准备

PR #1 还没合并。新建分支 `task-002-new-image-full-boot`，基线用上游的 `handoff-protocol`（`https://github.com/micsnq2yoma-lgtm/RV`，里面有任务 002 和本补充），再把你自己的 `task-001-tf-card-boot-bringup` 合并进来，这样 `serial_console.py` 和 `docs/BOARD.md` 也都在。PR 的目标分支是上游的 `handoff-protocol`。

## 1. 认出这张卡（只读）

```powershell
Get-Disk | Where-Object { $_.BusType -in 'SD','USB','MMC' -or $_.IsBoot -eq $false } |
  Format-Table -AutoSize Number, FriendlyName, BusType, Size, PartitionStyle, IsSystem, IsBoot
Get-Volume | Where-Object DriveType -eq 'Removable' |
  Format-Table -AutoSize DriveLetter, FileSystemLabel, FileSystem, Size, SizeRemaining
```

- **只认** `DriveType` 为 `Removable`、`IsSystem`/`IsBoot` 都是 `False`、大小和 TF 卡相符（通常 4–128 GB）的那一个。可能是 TF 卡的盘符有不止一个时，**[需人工]** 请人确认。
- 找到盘符（下文记作 `X:`）后，列出根目录：`Get-ChildItem X:\ -Force`，再列一下 `X:\rpmsg`、`X:\ecat`、`X:\ecat_newchip`（如果存在）。
- 输出存到 `logs/20261105-002-card-identify.log`。

根据结果分三种情况：

| 情况 | 判断依据 | 怎么做 |
|---|---|---|
| **A. 开发板上的那张卡** | 文件系统是 FAT32；根目录有 `boot.scr`、`uImage.lz4`、`uInitrd.lz4`、`kernel.dtb`，还有 `rpmsg/`、`ecat/` 或 `ecat_newchip/`；`uImage.lz4` 是 4,245,866 字节（旧版） | 继续第 2 步 |
| **B. 已经是新版** | 情况 A 的特征都有，但四个文件的大小和 content_hash 已经和任务 002 的表格一致 | 跳过第 3、4 步，只记录哈希，然后从第 5 步继续 |
| **C. 别的卡**：空卡、NTFS/exFAT、内容不认识 | 不符合 A、B | **停下。不要格式化，不要写入。** 把列出的内容报告给人，问这张卡要怎么用。如果人要求把它做成新的启动卡，需要 Claude 另出任务单（格式化必须由人明确确认盘符，见 AGENTS.md 安全规则第 5 条） |

## 2. 找到新版启动文件并校验

按顺序找，找到一处就停：

1. 人放在主机上的临时目录。先问人有没有。
2. 本机的 Dropbox 同步目录，只读查找：
   ```powershell
   $cands = @("$env:USERPROFILE\Dropbox", "$env:USERPROFILE\Dropbox (Personal)") + `
     (Get-ChildItem "$env:USERPROFILE" -Directory -Filter 'Dropbox*' -ErrorAction SilentlyContinue).FullName
   $cands | Select-Object -Unique | ForEach-Object { Join-Path $_ 'Workspace\RV\boot' } | Where-Object { Test-Path $_ }
   ```
   注意：Dropbox 的“仅在线”文件打开时才会下载。复制前先确认文件大小正确。
3. 都没有：**[需人工]** 请人从 Dropbox 网页 `/Workspace/RV/boot/` 下载这四个文件，放到一个临时目录（**不要放进仓库**），然后告诉你路径。

找到后执行：

```powershell
python scripts/dropbox_content_hash.py <目录>\boot.scr <目录>\uImage.lz4 <目录>\uInitrd.lz4 <目录>\kernel.dtb
```

大小和 content_hash 必须和任务 002 的表格**四项全部一致**，否则停下汇报。

## 3. 备份卡上的旧文件

```powershell
$bk = 'X:\backup-20261105'
if (Test-Path $bk) { Get-ChildItem $bk; throw 'backup dir already exists - ask human' }
New-Item -ItemType Directory $bk | Out-Null
'boot.scr','uImage.lz4','uInitrd.lz4','kernel.dtb' | ForEach-Object { Copy-Item "X:\$_" $bk }
python scripts/dropbox_content_hash.py X:\backup-20261105\boot.scr X:\backup-20261105\uImage.lz4 X:\backup-20261105\uInitrd.lz4 X:\backup-20261105\kernel.dtb
```

备份里文件的 SHA-256 应该和报告 001 里记录的旧版一致（`uImage.lz4` 是 `ac207eca…`）。`backup-20261105` 已经存在的话，**不要覆盖**，先问人。

## 4. 换上新文件并核对

```powershell
'boot.scr','uImage.lz4','uInitrd.lz4','kernel.dtb' | ForEach-Object { Copy-Item "<目录>\$_" "X:\$_" -Force }
python scripts/dropbox_content_hash.py X:\boot.scr X:\uImage.lz4 X:\uInitrd.lz4 X:\kernel.dtb
```

四项都要和任务 002 的表格一致。把这里打印出的普通 SHA-256 记下来，C 节在板子上核对时要用。第 3、4 步的输出都追加到 `logs/20261105-002-card-identify.log`。

除了 `backup-20261105/` 和根目录的这四个文件，卡上的其他东西一律不动。

## 5. 弹出卡

```powershell
(New-Object -ComObject Shell.Application).Namespace(17).ParseName('X:').InvokeVerb('Eject')
```

确认盘符消失后，**[需人工]** 请人把卡插回**断电状态**的开发板，然后从任务 002 的 B 节第 6 步继续。

## 报告要求

在报告 002 里写明：这张卡属于 A、B、C 中的哪种情况；新文件从哪里找到的；备份和替换前后的哈希。
