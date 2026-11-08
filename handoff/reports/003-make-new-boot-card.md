# 报告 003：空 GPT 卡已转为 MBR，制卡与回读校验完成

- **执行者**：Codex
- **日期**：2026-11-05（America/Los_Angeles）
- **结果**：done（制卡与弹出）。上板验证由任务 002 跟踪。
- **分支 / PR**：`task-002-new-image-full-boot` / [草稿 PR #2](https://github.com/micsnq2yoma-lgtm/RV/pull/2)，目标上游 handoff-protocol

## 一句话结论

第一次尝试在清除分区后因 Initialize-Disk 报错而停止。按补充 1 恢复后，磁盘 2 通过 Set-Disk 转为 MBR，创建 FAT32 卷 RVBOOT。复制 152 个文件后，四个启动文件的哈希和全部清单大小均通过回读校验，Windows 已安全弹出 F:。

## 首次执行记录

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
| D / 002 B–E | 首次制卡尝试停在初始化阶段 | 补充 1 后的上板结果见任务 002 报告 |

## 补充 1 执行记录

| 步骤 | 结果 |
|---|---|
| 只读核对 | 磁盘 2，USB / SDHC Card，31,914,983,424 字节，非系统或启动盘，GPT、0 个分区 |
| 第二次人工确认 | 用户原话“确认继续制卡磁盘 2” |
| 管理员启动 | 随工具提供的 PowerShell 发起提权时，用户反馈未看到 UAC，Windows 返回操作取消。改用系统自带的 Windows PowerShell 发起同一脚本，管理员助手成功启动 |
| 转换与格式化 | Set-Disk 转为 MBR，回读通过。分区 1 为 31,913,410,560 字节，FAT32，卷标 RVBOOT，盘符 F:，卷大小 31,896,633,344 字节。采用整卡方案 |
| 复制 | robocopy 返回 3，复制 152 文件，失败 0。日志列出目标侧的额外项，源清单条目均通过回读 |
| 校验与弹出 | 四文件大小、普通 SHA-256 与 Dropbox content_hash 均匹配。checked=152、missing=0、size_mismatch=0。Explorer Eject 后 F: 消失 |

原始记录见 `logs/20261105-003-make-card.log` 和 `logs/20261105-003-robocopy.log`。

## 需要回答的问题

1. 操作的是磁盘 2，USB / SDHC Card，31,914,983,424 字节。两次确认原话分别为“确认格式化磁盘2”和“确认继续制卡磁盘 2”。
2. MBR、单分区 31,913,410,560 字节、FAT32、RVBOOT。弹出前盘符为 F:。采用整卡方案。
3. 根目录四个启动文件的 content_hash 和 SHA-256 全部匹配。卡上清单结果为 `checked=152 missing=0 size_mismatch=0`。
4. 新卡启动到 Linux，板上四个 SHA-256 回读通过。八个问题及 D 节跳过记录见任务 002 报告。[任务 002 报告](002-new-image-full-boot.md)

## 和任务单不一致的地方

- 将只读源预检提前，以确认有效源文件后再请求当场格式化确认。
- 使用管理员助手执行任务给定的 PowerShell cmdlet，因为当前普通进程无管理员令牌；UAC 由用户手动批准。
- 对 “already initialized” 先查看磁盘状态；仍是 GPT，不能执行任务预期的 MBR 建分区流程。按失败规则停止，没有重试清盘、改用 diskpart 或尝试其他转换方法。

## 发现的问题和风险

首次尝试后磁盘保留了 GPT 分区表，导致 Initialize-Disk 报错。补充 1 用 Set-Disk 完成转换，随后通过卡上回读。启动表现由任务 002 上板确认。

## 需要人做的事

用户已完成断电换卡与上电配合。原卡用于回退，当前板上运行新版镜像。
