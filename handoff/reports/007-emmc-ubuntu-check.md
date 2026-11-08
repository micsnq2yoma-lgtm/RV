# 报告 007：eMMC Ubuntu 检查与 chroot 验证

- **执行者**：Codex
- **日期**：2026-11-07
- **结果**：done
- **分支 / PR**：task-007-emmc-ubuntu / [PR #4](https://github.com/micsnq2yoma-lgtm/RV/pull/4)

## 一句话结论

eMMC 的单个 ext4 分区内是 Ubuntu 24.04.3 LTS。维护者的 /mount_emmc.sh 能进入 chroot，Python 和 GCC 版本命令成功，apt、make 路径存在，git 未在 PATH 中找到。退出后 stop 成功，最终确认 /mnt/ubuntu 和 /mnt/emmc_ro 下均无挂载。

## 逐步执行记录

| 步骤 | 结果 | 证据 |
|---|---|---|
| 1 | 人确认 boot_1106 TF 卡与 USB 接好、主电接通，以及伺服动力电断开或电机未连接，采集就绪后 RESET，独立启动到登录，再人工登录。本次启动与任务 006 分开 | `logs/20261107-007-boot.log` 第 292、584 行 |
| 2，设备身份 | type=MMC，型号 CJUD4R，124,993,536 个 512 字节扇区，63,996,690,432 字节（59.6015625 GiB）。普通用户区只有 mmcblk1p1 | `logs/20261107-007-emmc.log` 第 11–19 行 |
| 2，只读查看 | 挂载为 ext4 ro,noload，/proc/mounts 显示 ro,norecovery。确认 Ubuntu 24.04.3、bash、systemd。/lib/modules 缺失。查看后正常卸载 | 同日志第 82、85、86、114、127–134 行 |
| 3，首次进入 | start 成功进入 Ubuntu。主机端识别历史开关确认提示时超时，正常 exit，stop 成功并确认全部卸载 | 同日志第 178、245 行 |
| 3，重试及命令 | 修正终端控制字符识别后重新进入，完成任务指定八条 chroot 命令。which 组合查询返回 1，输出 apt、python3、gcc、make 路径，未找到 git。其余命令返回 0 | 同日志第 271、285、334–363 行 |
| 3，最终退出 | exit 返回维护者脚本，start 返回 0。status 列出六处挂载，stop 返回 0，最后 status 和 /proc/mounts 均确认没有剩余挂载 | 同日志第 390–462 行 |
| 4 | 新建 docs/EMMC.md，更新状态与报告，提交本分支 PR | 本 PR |

## 需要回答的问题

1. **eMMC 的分区和文件系统是什么，Ubuntu 版本和占用空间？** eMMC 为 MMC / CJUD4R，普通用户区 59.60 GiB。分区 mmcblk1p1 为 62,496,760 KiB，即 63,996,682,240 字节，挂载确认 ext4。系统为 Ubuntu 24.04.3 LTS、noble、riscv64。只读查看的 BusyBox df 显示文件系统 58.4G、已用 1.1G、可用 54.3G、2%。chroot 内 df 显示 59G、已用 1.2G、可用 55G、3%。du 显示 /usr 为 757.0M，两组 df 原始值均保留。
2. **start 能否进入，chroot 内有哪些开发工具？** 能。第二次完整检查获得 Ubuntu os-release，uid=0(root)、gid=0(root)，并取得 /bin/apt、/bin/python3、/bin/gcc、/bin/make。Python 3.12.3，GCC 13.3.0，发行版本字符串 gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1)。git 未在 PATH 中找到，因此 which apt python3 gcc make git 返回 1。uname 为 6.6.90-rt54+ #6 SMP PREEMPT_RT，chroot 共享 TF 启动的内核。
3. **stop 能否干净卸载？** 能。两次进入后均正常 exit，执行 status、stop、status，stop 均返回 0，最终 /proc/mounts 路径检查输出 EMMC_ALL_UNMOUNTED。退出时观察到的挂载是根目录、proc、sys、dev、dev/pts、run 共六处。没有使用 RESET 处理 chroot 或强制卸载。
4. **有没有 /lib/modules/6.6.90-rt54+ 和 systemd？** /lib/modules 目录本身不存在，所以目标内核模块目录缺失。ls 的 No such file or directory 原样保留。/lib/systemd/systemd 存在，88,480 字节且可执行，/sbin/init 指向 ../lib/systemd/systemd，/bin/bash 存在且可执行。直接从 eMMC 启动尚未验证，当前方法为从 TF 启动 Buildroot 后 chroot。

## 和任务单不一致的地方

- 先只读查看时在 ro 基础上增加 noload，避免 ext4 日志回放。内核仍输出 orphan cleanup on readonly fs 和 mounted ... ro without journal，已保留原始信息。
- 第一次进入后，主机脚本抛出 TimeoutError，内容为 Interactive console stage did not reach its expected prompt。Ubuntu 实际已响应，只是 ANSI 控制序列、回车和行编辑重绘使确认标记匹配失败。异常清理正常 exit 并 stop，随后修正主机匹配逻辑重试，没有因这个主机端问题复位板子。
- 为执行“只做查看”的交互检查，将本次 shell 的 HISTFILE 指向 /dev/null 并关闭会话历史。Ubuntu 配置内容按维护者原 start 脚本执行，其中含读写挂载、必要目录创建和 DNS 配置复制。
- 首次读写挂载时内核输出 recovery complete，随后正常挂载。此信息与只读阶段的 orphan 提示均在日志中，未额外执行文件系统修复。
- 主机临时编排使用 Python/pyserial，保存在忽略目录 .venv。公开副本遮蔽构建账号/主机、MAC、文件系统 UUID 和 home 目录条目，NUL 用可见转义表示，认证交互未采集。完整原始记录留在本机。

## 发现的问题和风险

Ubuntu 的目标内核模块目录缺失，git 未在 PATH 中找到。systemd 文件存在，直接 eMMC 启动能力仍需后续独立任务验证。

依据 DECISIONS.md，这块板子预期为 2 核，本次启动上线 2 核，与预期一致。固件和设备树仍按更多 hart 配置的提示保留在启动日志中。

## 需要人做的事

请审阅报告与 PR。板子已回到 Buildroot shell，eMMC 已正常卸载，串口已关闭。
