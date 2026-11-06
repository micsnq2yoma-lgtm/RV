# 任务 003 补充 1：清空后的 GPT 磁盘转换为 MBR，继续制卡

- **补充的任务**：`003-make-new-boot-card.md`
- **作者**：Claude
- **日期**：2026-11-06
- **起因**：报告 003 中，`Clear-Disk` 执行后磁盘 2 仍然是 **GPT 分区表、没有分区**，所以 `Initialize-Disk -PartitionStyle MBR` 报错“磁盘已初始化”。这是任务单的问题：我原以为 `Clear-Disk` 会把磁盘清成未初始化（RAW）状态，实际在这张卡上它保留了 GPT 分区表。Codex 遇到报错就停下来，处理正确。

## 当前状态

卡上原有的两个分区已经清除，旧内容已经没了。所以这一步没有新增的数据风险，只需要把空的 GPT 分区表换成 MBR，然后接着做任务 003 的后续步骤。

## 步骤

1. **只读核对**：
   ```powershell
   Get-Disk | Format-Table -AutoSize Number, FriendlyName, BusType, Size, PartitionStyle, IsSystem, IsBoot
   Get-Partition -DiskNumber <N> -ErrorAction SilentlyContinue
   ```
   目标磁盘必须**同时**满足：`BusType` 是 `USB` 或 `SD`；`Size` = 31914983424；型号 `SDHC Card`；`IsSystem` 和 `IsBoot` 都是 `False`；`PartitionStyle` = `GPT`；**没有任何分区**。只要有一项不符，就停下汇报。

2. **[需人工]** 磁盘状态和人上次确认时不一样了，要请人**再确认一次**，例如回复“确认继续制卡磁盘 N”。

3. **修改管理员脚本 `scripts/make_boot_card.ps1`**，然后在 UAC 下运行：
   - 把执行前的检查改成“GPT、0 个分区”（不再要求两个旧分区），其他身份条件不变。
   - **删掉 `Clear-Disk`**：磁盘已经是空的，不需要再清一次。
   - 把 `Initialize-Disk -PartitionStyle MBR` 换成：
     ```powershell
     Set-Disk -Number $ConfirmedDiskNumber -PartitionStyle MBR
     ```
     `Set-Disk` 只能用于没有分区的磁盘，正好符合当前状态。执行后读回 `PartitionStyle`，必须是 `MBR`。
   - 后面的 `New-Partition -UseMaximumSize -MbrType FAT32 -AssignDriveLetter` 和 `Format-Volume -FileSystem FAT32 -NewFileSystemLabel RVBOOT` 保持不变；FAT32 失败时的 16 GB 方案也保持不变。

4. **如果 `Set-Disk` 报错**：只允许用下面这一个备用方法，而且必须在第 1 步的核对结果不变的前提下：
   ```
   diskpart
   list disk
   select disk <N>
   detail disk
   convert mbr
   exit
   ```
   在 `detail disk` 之后，把输出给人看，确认是这张 SDHC 卡后才执行 `convert mbr`。**不要执行 `clean`**。`convert mbr` 报错就停下汇报。

5. 转换成 MBR 并格式化成功后，从任务 003 的 **C 节第 6 步**继续：复制、校验、弹出、上板，以及任务 002 的 B–E 节，要求和原来一样。

## 报告要求

在报告 003 里追加一节“补充 1 执行记录”：人第二次确认的原话；用的是 `Set-Disk` 还是 `diskpart`；转换后的分区表、分区、文件系统、卷标、盘符。任务 003 原来的 4 个问题，按最终结果更新回答。
