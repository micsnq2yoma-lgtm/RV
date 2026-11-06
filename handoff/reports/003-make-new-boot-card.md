# 报告 003：清除分区后 MBR 初始化失败

- **执行者**：Codex
- **日期**：2026-11-05（America/Los_Angeles）
- **结果**：failed
- **分支 / PR**：`task-002-new-image-full-boot` / [草稿 PR #2](https://github.com/micsnq2yoma-lgtm/RV/pull/2)，目标上游 handoff-protocol

## 一句话结论

在用户当场确认并手动批准 UAC 后，对磁盘 2 执行 Clear-Disk；旧分区已消失，但 Initialize-Disk -PartitionStyle MBR 返回 “The disk has already been initialized.”。复核仍为 GPT、无分区，按任务规则停止，没有创建 FAT32 卷或复制文件。

## 逐步执行记录

| 步骤 | 结果 | 证据 |
|---|---|---|
| 上游同步 | 合并任务 003（上游 96234ec，合并 b303b67），沿用任务 002 分支 | Git 历史；make-card 日志 1 行 |
| A.1–2 目标复核 | USB / SDHC Card，磁盘 2，31,914,983,424 字节，IsSystem/IsBoot 均为 False；GPT 两分区 1,073,741,824 + 30,486,298,624 字节 | `logs/20261105-003-make-card.log` 2–6 行 |
| A.3 人工确认 | 用户原话“确认格式化磁盘2”，随后确认“已手动批准 UAC” | 同日志 12、25 行；本次会话 |
| C.6 源预检 | 提前核对 Dropbox Workspace/RV/TF 卡镜像目录：152 文件、320,009,161 字节、Offline/RecallOnDataAccess 数量 0；`verify_card.ps1` 源目录 checked=152、missing=0、size_mismatch=0 | 同日志 7–10 行；源根目录四文件的大小、content_hash、普通 SHA-256 与任务 002 已验证值一致 |
| B.4 管理员再核对 | 原进程无管理员令牌；通过 UAC 启动相同 Storage cmdlet 的管理员脚本。脚本再次检查同一目标与旧分区布局 | 同日志 13–15 行；`scripts/make_boot_card.ps1` |
| B.4 Clear-Disk | 仅磁盘 2；命令返回后进入初始化，原两个分区消失 | 同日志 16–17、28–30 行 |
| B.4 Initialize-Disk | 失败：`The disk has already been initialized.`。查看当前状态为 GPT，不能按预期的 MBR 继续 | 同日志 18–24、26–29 行 |
| B.4 后续和 C.7–9 | 未执行 New-Partition、Format-Volume、16 GiB 方案、robocopy、卡上校验或弹出 | 同日志 31 行；没有 robocopy 日志 |
| D / 002 B–E | 未上板或验证；原约 7.5 GiB 卡未操作。只更新阻塞报告 | 任务 002 报告与状态表 |

## 需要回答的问题

1. **格式化的是哪块磁盘？人确认时的原话是什么？** 操作目标为磁盘 2，USB / SDHC Card，31,914,983,424 字节。用户原话“确认格式化磁盘2”。只完成清除旧分区，未完成格式化。
2. **最终的分区表、分区大小、文件系统、卷标、盘符是什么？是否用了 16 GB 方案？** 失败后复核仍为 GPT，Get-Partition 未返回分区；无 FAT32 文件系统、RVBOOT 卷标或盘符。未用 16 GiB 方案，失败发生在初始化而不是 FAT32 格式化阶段。
3. **根目录四个启动文件的 content_hash 和 SHA-256 是否全部一致？MANIFEST 对比结果是多少？** 源文件已核对一致，源目录清单 `checked=152 missing=0 size_mismatch=0`。没有复制到卡，卡上四文件哈希及三个清单计数均未运行，不能用源预检充当卡上结果。
4. **任务 002 的 8 个问题。** 逐条见 [任务 002 报告](002-new-image-full-boot.md)。源哈希已确认，卡上与 B–E 的启动、板级、网络结果仍未确认。

## 和任务单不一致的地方

- 将只读源预检提前，以确认有效源文件后再请求当场格式化确认。
- 使用管理员助手执行任务给定的 PowerShell cmdlet，因为当前普通进程无管理员令牌；UAC 由用户手动批准。
- 对 “already initialized” 先查看磁盘状态；仍是 GPT，不能执行任务预期的 MBR 建分区流程。按失败规则停止，没有重试清盘、改用 diskpart 或尝试其他转换方法。

## 发现的问题和风险

磁盘 2 的原两个分区已经清除，卡不是可启动的 FAT32 成品。当前实际布局与执行前的两分区不再相同；不能把同一脚本当成可直接重跑的操作。没有触碰其他磁盘、原约 7.5 GiB 卡、板上模块或网络。

## 需要人做的事

请规划方审阅 `Initialize-Disk` 报错和当前 GPT、无分区的状态，给出新的制卡指示。新卡未制成前不要将其作为任务 002 的启动卡使用；任务 002 保持 blocked。
