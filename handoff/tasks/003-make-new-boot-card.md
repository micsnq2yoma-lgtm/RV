# 任务 003：把 32 GB 新卡做成启动卡，然后接着完成任务 002

- **对应阶段**：docs/PLAN.md 第 1 阶段（制卡）和第 2 阶段
- **作者**：Claude
- **日期**：2026-11-05
- **电机是否可能动作**：**否**
- **人的授权**：人在 2026-11-05 向 Claude 明确表示，这张约 32 GB 的卡（报告 002 里的磁盘 2：USB、`SDHC Card`、31,914,983,424 字节、GPT、两个 Linux 分区）**上面的内容不要了，同意格式化**。按 AGENTS.md 安全规则第 5 条，执行时还要**当场**再请人核对一次磁盘编号。
- **前置条件**：在 PR #2 的分支 `task-002-new-image-full-boot` 上继续工作，本任务的改动也提交到这个分支和 PR #2。开发板上原来那张约 7.5 GB 的卡**不要动**，留作回退。

## 目标

把这张卡做成一个 MBR 分区表、单个 FAT32 分区的启动卡，内容和 Dropbox `/Workspace/RV/TF卡镜像/` 一致（根目录已经是新版启动文件），全部校验通过；然后执行任务 002 的 B–E 节，完成新镜像的上电验证。

## 不要做的事

- 除了下文核对过的磁盘，不要对任何磁盘执行 `Clear-Disk`、`Initialize-Disk`、`New-Partition`、`Format-Volume`、`diskpart`。
- 不要用 `dd`、Rufus、balenaEtcher 一类工具写原始镜像。
- 不要把 Dropbox 里的文件复制进仓库。
- 任务 002 原有的限制仍然有效：不加载模块，不运行控制程序，U-Boot 里只执行只读命令，不动 eth1。

## 步骤

### A. 再次核对目标磁盘（只读）

1. 重新列出磁盘。磁盘编号可能变了，**不要沿用报告 002 里的 2**：
   ```powershell
   Get-Disk | Format-Table -AutoSize Number, FriendlyName, BusType, Size, PartitionStyle, IsSystem, IsBoot, OperationalStatus
   Get-Partition | Format-Table -AutoSize DiskNumber, PartitionNumber, DriveLetter, Size, GptType
   ```
2. 目标磁盘必须**同时**满足：`BusType` 是 `USB` 或 `SD`；`Size` = 31914983424；`IsSystem` 和 `IsBoot` 都是 `False`；分区布局和报告 002 一样（1,073,741,824 + 30,486,298,624 字节两个分区）。只要有一项不符，就停下汇报。
3. **[需人工]** 把这块磁盘的编号、大小、型号和分区情况展示给人，请人回复一句明确的话，例如“确认格式化磁盘 N”。人回复的编号必须和你核对出来的一致。

### B. 分区和格式化

4. 用下面这段脚本，把 `$N` 设成上一步人确认的编号。脚本在执行前会再检查一遍：
   ```powershell
   $N = <人确认的编号>
   $d = Get-Disk -Number $N
   if ($d.Size -ne 31914983424 -or $d.IsSystem -or $d.IsBoot -or $d.BusType -notin 'USB','SD') { throw "disk $N does not match - abort" }
   Clear-Disk -Number $N -RemoveData -RemoveOEM -Confirm:$false
   Initialize-Disk -Number $N -PartitionStyle MBR
   $p = New-Partition -DiskNumber $N -UseMaximumSize -MbrType FAT32 -AssignDriveLetter
   Format-Volume -Partition $p -FileSystem FAT32 -NewFileSystemLabel RVBOOT -Confirm:$false
   Get-Partition -DiskNumber $N | Get-Volume | Format-Table -AutoSize DriveLetter, FileSystemLabel, FileSystem, Size
   ```
   - 如果 `Initialize-Disk` 报磁盘已经初始化，先执行 `Get-Disk -Number $N` 看清状态再继续，**不要换别的磁盘编号重试**。
   - 如果 `Format-Volume` 拒绝把整块盘格式化成 FAT32，就删掉这个分区，用 `-Size 16GB` 重新建一个，再格式化。在报告里注明。
   - 记下分到的盘符，下文写作 `X:`。确认文件系统显示为 `FAT32`。
5. 所有输出存到 `logs/20261105-003-make-card.log`。

### C. 复制内容

6. 源目录是本机 Dropbox 同步的 `Workspace\RV\TF卡镜像\`（报告 002 里找到 `boot\` 的那个 `Workspace\RV` 目录）。先确认源目录里的文件都已经下载到本地，没有“仅在线”占位文件：
   ```powershell
   $src = '<Workspace\RV 的路径>\TF卡镜像'
   Get-ChildItem $src -Recurse -File | Where-Object { $_.Attributes -match 'Offline|RecallOnDataAccess' } | Select-Object FullName
   ```
   有输出的话，**[需人工]** 请人在 Dropbox 里把这个文件夹设为“可离线使用”，等同步完成后再继续。
7. 复制：
   ```powershell
   robocopy $src X:\ /E /COPY:D /R:2 /W:2 /NP /LOG+:logs\20261105-003-robocopy.log
   ```
   robocopy 的返回码小于 8 表示成功。
8. 校验：
   - 根目录四个启动文件：`python scripts/dropbox_content_hash.py X:\boot.scr X:\uImage.lz4 X:\uInitrd.lz4 X:\kernel.dtb`，大小和 content_hash 必须和任务 002 的表格一致，普通 SHA-256 必须和报告 002 记录的一致。
   - 全部文件：拿卡上每个文件的大小和仓库 `MANIFEST.tsv` 里 `tf-card/` 开头的条目逐一对比，`tf-card/` 对应 `X:\`。要求 157 条中的 152 条全部存在、大小一致；另外 5 条在 `tf-card/` 之外（`boot/`、`boot.zip`），不在卡上。写一段 PowerShell 完成对比，打印 `checked`、`missing`、`size_mismatch` 三个数，并把这段脚本存为 `scripts/verify_card.ps1`。
   - 结果追加到 `logs/20261105-003-make-card.log`。任何一项不一致就停下汇报。
9. 弹出卡：`(New-Object -ComObject Shell.Application).Namespace(17).ParseName('X:').InvokeVerb('Eject')`，确认盘符消失。

### D. 上板验证（执行任务 002 的 B–E 节）

10. **[需人工]** 请人：给开发板断电，取下原来那张卡（妥善保存，作为回退），插入这张新卡。
11. 按 `handoff/tasks/002-new-image-full-boot.md` 的 B、C、D、E 节执行，日志文件名按任务 002 的写法。说明两点：
    - C 节第 12 步，板上的 TF 卡设备名可能还是 `/dev/mmcblk0p1`，以 `ls /dev/mmcblk*` 为准。
    - 任务 002 “失败时怎么办”里“恢复备份”那一条，改成：**[需人工]** 请人把原来那张卡插回去，确认能正常启动。

### E. 整理

12. 写报告 `handoff/reports/003-make-new-boot-card.md`，内容是 A–C 节：磁盘核对、人的确认原话、格式化结果、复制和校验结果。
13. 把 D 节的上板结果补进 `handoff/reports/002-new-image-full-boot.md`，逐条回答任务 002 的问题。
14. 更新 `handoff/STATUS.md`：加上 003 这一行，002 和 003 的状态改成实际结果；`docs/BOARD.md` 加上新卡的信息。然后推送到 PR #2。

## 失败时怎么办

| 现象 | 处理 |
|---|---|
| 磁盘核对有任何一项不符 | 停下，不格式化，汇报 |
| `Clear-Disk` 或 `Initialize-Disk` 报错 | 停下，贴出错误。不要换别的方法强行处理（例如 diskpart `clean`），等 Claude 出新的指示 |
| 格式化后文件系统不是 FAT32 | 按第 4 步的 16 GB 方案重做一次，还不行就停下汇报 |
| 复制或校验有不一致 | 只针对出问题的文件重新复制一次，还不一致就停下汇报 |
| 新卡上板后完全没有输出，或者 U-Boot 报找不到文件 | 记录现象，请人换回原来那张卡，确认能启动，然后汇报 |

## 需要回答的问题

1. 格式化的是哪块磁盘（编号、大小、型号）？人确认时的原话是什么？
2. 最终的分区表、分区大小、文件系统、卷标、盘符是什么？是否用了 16 GB 方案？
3. 根目录四个启动文件的 content_hash 和 SHA-256 是否全部一致？MANIFEST 对比结果的 `checked`、`missing`、`size_mismatch` 分别是多少？
4. 任务 002 的 8 个问题，在报告 002 里逐条回答。
