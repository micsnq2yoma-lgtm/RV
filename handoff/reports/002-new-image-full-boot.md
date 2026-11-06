# 报告 002：新版镜像冷启动与板上哈希验证通过

- **执行者**：Codex
- **日期**：2026-11-05（America/Los_Angeles）
- **结果**：done（D 节按用户选择跳过）
- **分支 / PR**：task-002-new-image-full-boot / [草稿 PR #2](https://github.com/micsnq2yoma-lgtm/RV/pull/2)，目标上游 handoff-protocol

## 一句话结论

新版镜像从新卡启动到 Linux。第二轮采集覆盖 Nuclei SDK、OpenSBI、U-Boot 和 Linux 登录提示。第三轮成功截停 U-Boot 并读取环境，随后用 boot 恢复启动。板上只读回读四个哈希均通过。CPU2–7 上线失败仍可复现。

## 逐步执行记录

| 步骤 | 结果 | 证据 |
|---|---|---|
| 补充 0：分支 | 完成。上游 origin/handoff-protocol 更新到 3ead0e6；从其建立任务分支，再合并自己的任务 001 分支，合并提交 1998ae5，无冲突 | git 分支/合并结果；card-identify 日志 1 行 |
| 补充 1：磁盘与卷 | 只读完成。磁盘 2，USB SDHC Card，31,914,983,424 字节，GPT，非系统/启动盘；可移动卷数量 0 | logs/20261105-002-card-identify.log 3–9、16–17 行 |
| 补充 1：分区 | 只读完成。两个 Unknown 分区，大小 1,073,741,824 和 30,486,298,624 字节，均无盘符；该盘可映射卷数量 0 | 同日志 10–15 行 |
| A/B/C 分类 | 不符合可识别 A/B FAT32 卡条件；人明确确认是准备使用的新卡，需要另行制卡任务。按 C 分支停止，未把 GPT 类型或 Unknown 标签当作文件系统结论 | 本次会话；同日志 18 行 |
| 根目录检查 | 未执行；没有盘符，不猜测路径，不分配盘符或挂载 | 同日志 7、11–15 行 |
| 补充 2：新文件来源及校验 | 用户指定本机 Dropbox Workspace/RV，找到 boot/ 后只读校验四文件；大小及 content_hash 全部匹配，并记录普通 SHA-256。未复制源文件进仓库或卡 | 同日志 19–31 行；checked=4 mismatch=0 |
| 补充 3–5 | 未执行；没有创建备份、替换文件或弹出卡 | 已在补充 1 停止 |
| 任务 003 制卡 | 首次初始化失败。补充 1 经第二次确认后用 Set-Disk 转为 MBR，FAT32 卷 RVBOOT 通过回读并弹出 | [任务 003 报告](003-make-new-boot-card.md) |
| B.6–8 冷启动 | 用户确认断电换卡。首次上电时 COM3 报 ClearCommError，日志为 0 字节。第二轮启用重连，19:27:58 前后出现 OpenSBI，19:28:25 到达登录提示。时间为主机 PST，实际插电时刻未精确测量 | logs/20261105-002-boot-full.log |
| B.9–10 U-Boot | 第三轮冷启动识别到倒计时后发送回车，依次执行 version、printenv、mmc info、fatls mmc 0、bdinfo，再执行 boot 到 Linux 登录提示 | logs/20261105-002-uboot.log；本次会话 |
| C 登录与采集 | Linux 登录后读取版本、CPU、设备树与接口。根据 SD 类型与扇区数识别 /dev/mmcblk0p1，挂载为 ro，校验后成功卸载 | logs/20261105-002-board-info.log |
| D 可选网络 | 用户选择跳过 | 本次会话 |
| 整理 | 已保存识别日志，更新 BOARD、状态表和本报告 | 本报告及对应文件 |

## 需要回答的问题

1. **源文件和卡上哈希是否一致？** 四文件的大小与 Dropbox content_hash 全部匹配。Windows 卡上回读与 Linux 只读挂载后的 SHA-256 均匹配下表。
2. **OpenSBI 和 U-Boot 是否可见？** 第二轮收到 OpenSBI v1.3，平台 8 hart，Boot HART ID 1。随后收到 U-Boot 倒计时和完整 Linux 启动输出。第一次上电发生 COM3 中断，退出码 125，串口数据 0 字节。第二轮的 RESET 操作与指示灯状态未得到单独确认。
3. **U-Boot 版本、bootcmd、boot.scr 和 fatload？** U-Boot 2024.01-00012-gc0a14d778e，构建时间 2026-03-03 22:43:19 -0800。bootcmd 为 `run distro_bootcmd`，boot_targets 为 mmc0。自动从 mmc 0:1 找到并执行 719 字节的 boot.scr。内核、ramdisk 和 DTB 的 fatload 字节数依次是 4,223,577、14,856,105、8,621。第三轮执行 boot 后再次看到相同读入量。
4. **新旧内核编译时间差异？** release 均为 6.6.90-rt54+。旧版为 `#1 SMP PREEMPT_RT Mon May 11 19:34:25 PDT 2026`，新版为 `#6 SMP PREEMPT_RT Thu Nov 5 09:57:02 CST 2026`，时区字符串按内核原文记录。
5. **在线核数与设备树 CPU status？** possible 为 0–7，online 为 0–1。设备树 cpu@0 至 cpu@7 的 status 均为 okay，cpu@1 至 cpu@7 的 ISA 字符串含 v。内核仍逐项报告 CPU2–7 上线失败。
6. **xec 设备和驱动列表变化？** 与旧版相同，f9c210000.xec 对应 eth0，f9cdc0000.xec 对应 eth1，驱动目录为 nuclei-xec。
7. **做了 D 节的话，主机和板子能否 ping 通？能否 SSH？** 板上 eth0、eth1 的 carrier 均为 0。用户明确选择跳过可选网络验证，ping 和 SSH 连通性未知。
8. **其他差异和报错？** 新版新增 eMMC 驱动初始化和 mmcblk1（59.6 GiB）枚举，TF 卡仍为 mmcblk0（29.7 GiB）。旧版出现 rpmsg 驱动注册行，新版采集只见 rpmsg 保留内存描述。新版启动脚本自动运行 udhcpc 并启动 sshd，控制台出现 `modprobe: can't change directory to '/lib/modules': No such file or directory`，随后到达登录提示。CPU2–7 的报错与旧版相同。

## 新版源文件校验结果

源文件、Windows 卡上回读和板上只读回读分别见 card-identify、make-card 与 board-info 日志。四个 SHA-256 一致。

| 文件 | 大小（字节） | 普通 SHA-256 |
|---|---:|---|
| boot.scr | 719 | `06203ccf2ed48380c99efbd9d449a9d2792805556105c57677cdc8ed09ce30f9` |
| uImage.lz4 | 4,223,577 | `b3f0662be615a73fa1d821b1c3aa1b3c068eaf6668c009982795626fa5437d92` |
| uInitrd.lz4 | 14,856,105 | `e4cf190f117d84ed7f8fe613ed5334165c267e5410b8f5c3228b613c502358b7` |
| kernel.dtb | 8,621 | `3b84109ee3c19c9aa546602bb1ee33f925d7cec7dee1cd14868adaeaaaa60edd` |

## 和任务单不一致的地方

- 没有继续原任务 A 的备份替换，因为补充明确要求不符合 A/B 的卡转交制卡任务。任务 003 的实际制卡尝试与停止原因另见报告 003。
- 卡操作停止后，独立完成用户所提供目录中的只读源文件校验；没有把这一步视为对新卡制卡的授权。
- 没有盘符，无法按补充列出根目录、rpmsg、ecat、ecat_newchip；未通过分配盘符、挂载或其他变更绕过识别条件。
- 只读日志中的 GPT GUID 是分区类型标识，不是设备唯一标识；未采集设备序列号或唯一实例 ID。
- 已有任务 001 文件按补充第 0 步合并保留；没有改写两份任务单或把旧版日志冒充任务 002 输出。
- 第一次采集遇到 USB 串口中断，第二轮启用了同一 COM3 自动重连。日志首部说明第一次的零字节结果。第三轮使用任务规定的五条 U-Boot 命令。公开副本对 MAC、构建账户与主机、无关 U-Boot 环境值做了遮盖，原始采集留在本机。
- 新版 BusyBox 的 `ip -br link` 返回 1。补采 `ip link show` 及两个接口的 carrier。认证交互独立于采集日志。

## 发现的问题和风险

CPU2–7 的上线失败在新版仍可复现。两个网口在板级检查时均为无载波。新版的 eMMC 与 TF 卡是不同设备，哈希核对挂载的是经类型与容量确认的 TF 卡分区。

## 需要人做的事

维护者确认预期 CPU 核数。

## 给 Claude 的建议（可选）

预期 CPU 核数仍需维护者确认。启动与板级结果见 B、C 日志。
