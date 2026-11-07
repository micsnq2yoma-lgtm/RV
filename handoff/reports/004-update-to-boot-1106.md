# 报告 004：启动卡更新为 boot_1106

- **执行者**：Codex
- **日期**：2026-11-07
- **结果**：failed
- **分支 / PR**：task-004-boot-1106 / [草稿 #3](https://github.com/micsnq2yoma-lgtm/RV/pull/3)

后续状态按任务 005 的维护者判断调整为 done。以下保留任务 004 当时的 failed 结果及回退记录，当前卡已重新换上 boot_1106，见 [报告 005](005-reapply-boot-1106-coldboot-stats.md)。

## 一句话结论

boot_1106 的源文件、卡上文件及板上回读校验通过，复位启动和人工登录成功。完全断电后停在 OpenSBI hart 状态错误。按失败规则已恢复任务 002 的 11-05 版 initramfs，并验证 RESET 后恢复到登录。旧版完全断电启动也出现同一错误，原因未确认。

## 逐步执行记录

| 步骤 | 结果 | 证据 |
|---|---|---|
| A，1–4 | 五项大小、Dropbox content_hash 全部匹配。zip 根目录四文件和解压目录 SHA-256 相同，三个不变文件匹配报告 002 | `logs/20261107-004-source.log` |
| B，5–7 | 旧镜像大小 14,856,105，content_hash 66c8ab49… 匹配。新增 1、删除 0、修改 3 | `logs/20261107-004-initrd-diff.log` |
| C，8–12 | 人确认断电并插卡。重新插拔后唯一 RVBOOT 为 F:，FAT32，31,896,633,344 字节。备份四文件后覆盖并回读通过，安全弹出后 F: 消失 | `logs/20261107-004-card-update.log` |
| D，13–15 | 首轮 300 秒零字节。后续采集含两段 SDK，RESET 打断第一段 U-Boot，第二段启动到 login。人手动登录，并确认凭据与任务 002 相同 | `logs/20261107-004-boot-retry.log` 第 584、874 行 |
| D，16–17 | 板级命令、三个变更核实及 TF 卡只读回读完成，随后卸载 | `logs/20261107-004-board-info.log` 第 242、243、295、297、306、307 行 |
| D，补充冷启动 | 只切主电后 300 秒零字节，回车仍为原 root shell，uptime=510.68 秒。随后人确认主电、调试 USB 都断开且灯全灭，再连接上电，采集停在 OpenSBI hart 状态错误，300 秒结束时未到 U-Boot | `logs/20261107-004-boot-retry.log`、`logs/20261107-004-boot.log` 第 99 行 |
| 失败回退 | 卡上新四文件与备份旧四文件先逐项验证，仅恢复备份的 uInitrd，四文件旧版哈希均通过，安全弹出 | `logs/20261107-004-rollback.log` |
| 恢复启动验证 | 旧版完全断电后也出现相同 OpenSBI 错误。按 RESET 后进入 U-Boot，ramdisk 14,856,105 字节，最终到 login | `logs/20261107-004-rollback-boot.log` 第 105、396、688 行 |

## 需要回答的问题

1. **五个源文件的哈希是否全部一致，zip 和文件夹是否相同？** 全部符合任务表。zip 四文件直接位于根目录，逐项 SHA-256 相同，三个不变文件与报告 002 相同。完整值见 source 日志。
2. **initramfs 改了什么？** 616 → 617 条目，新增 1、删除 0、修改 3。新增 `/mount_emmc.sh`，4420 字节，0755，提供 eMMC Ubuntu 挂载、chroot 与卸载逻辑。`etc/ssh/sshd_config` 将注释的 `PermitRootLogin prohibit-password` 改为有效的 `PermitRootLogin yes`。`etc`、`etc/ssh` 权限均由 0755 改为 0775。差异中没有新增 `/lib/modules`。关键文本的完整差异已记录。
3. **卡上备份和新文件哈希是否正确？** 正确。先对旧卡四文件核对报告 002 的 SHA-256，再备份至 `F:\backup-20261107`，备份验证后才覆盖。Windows 新四文件回读及 Linux 只读挂载的 SHA-256 全部匹配下表。
4. **新版能否冷启动到登录，ramdisk 读到多少字节？** 已验证复位后自动启动至登录，ramdisk 为 14,857,818 字节，kernel 为 4,223,577，dtb 为 8,621。完全断电后未通过，最后为 `sbi_hsm_hart_start_finish: ERR: The hart is in invalid state [0]`，未出现 U-Boot 或镜像加载记录。旧版也复现同一错误，RESET 后恢复到登录。
5. **`/lib/modules` 报错和登录方式？** 启动仍出现 `modprobe: can't change directory to '/lib/modules': No such file or directory`，板上也确认目录缺失。人手动登录成功并确认用户名、密码与任务 002 相同。认证交互未采集。
6. **板上核实哪些变化？** `/mount_emmc.sh` 存在，大小 4420、权限 0755，SHA-256 为 `d31e23ca801f024d30f1b9210651017f224dc7b5298b328661b53e69379cfcad`。`/etc/ssh/sshd_config` SHA-256 为 `6ad3b8d4098d897d1c4d5594dfe8846ead0e999711e61f51095387660b1bc004`，有效配置为 `PermitRootLogin yes`。两哈希都与主机解析新版 initramfs 的结果相同。`ls -ld` 确认 `/etc` 和 `/etc/ssh` 均为 drwxrwxr-x。
7. **有没有新报错，CPU2–7 有无变化？** 新增观察为完全断电后 OpenSBI 的 hart 状态错误，旧版回退后同样出现，原因未确认。复位启动与采集的 dmesg 错误摘录未见新增 Linux 启动错误。CPU2–7 仍逐个 failed to come online，online=0-1。内核仍为 6.6.90-rt54+，#6 SMP PREEMPT_RT Thu Nov 5 09:57:02 CST 2026。Buildroot 2024.08，sshd 正在运行。只读查询显示 eth0、eth1 均 NO-CARRIER。

以下为测试过的 boot_1106 四文件。回退后卡上 uInitrd.lz4 为 14,856,105 字节，SHA-256 为 `e4cf190f117d84ed7f8fe613ed5334165c267e5410b8f5c3228b613c502358b7`，其余三个文件与下表相同。

| 文件 | 大小（字节） | SHA-256 |
|---|---:|---|
| boot.scr | 719 | `06203ccf2ed48380c99efbd9d449a9d2792805556105c57677cdc8ed09ce30f9` |
| uImage.lz4 | 4,223,577 | `b3f0662be615a73fa1d821b1c3aa1b3c068eaf6668c009982795626fa5437d92` |
| uInitrd.lz4 | 14,857,818 | `82a45be4f417110b532bd785f1d49353025ad0b62046754e74ceb1ee2c84181b` |
| kernel.dtb | 8,621 | `3b84109ee3c19c9aa546602bb1ee33f925d7cec7dee1cd14868adaeaaaa60edd` |

## 和任务单不一致的地方

- Windows 初次没有 RVBOOT 卷，按任务要求停下询问，用户重插后成功识别。CIM 卷查询不可用或超时，改用 .NET DriveInfo 核对唯一卷的卷标、文件系统与精确容量。
- 回退时读卡器也曾未枚举出 RVBOOT，脚本在写入前报 `Expected one RVBOOT volume`，用户重插后成功。
- 首次人工登录后 COM3 两次拒绝访问，用户完全退出终端后采集成功。
- 额外权限检查中 `stat` 不存在，复合命令末项成功而返回 0，日志保留了 stat 的错误。改用 `ls -ld` 验证权限。类似地，`ls /lib/modules | head` 的返回码 0 来自 head，目录缺失以实际输出为准。
- 先完成复位启动后的人工登录和板级验证，再补做完整断电冷启动。仅切主电保留了原会话，因此补做主电和 USB 全断的启动。USB 重新枚举后采集的早期部分有乱码，原样保留，不能据此复原最初 SDK 文本。采集、主机临时编排复用任务 002 的本地 Python 方式，临时助手保存在忽略目录 .venv。
- 公开日志标注了脱敏范围，遮蔽构建账号/主机、MAC 与本机源目录前缀，认证交互未采集。原始日志保留在本机忽略目录 .venv。主机差异仅记录配置与脚本文本。

## 发现的问题和风险

CPU2–7 上线失败与 `/lib/modules` 缺失仍可复现。新版允许 SSH root 登录，且两个配置目录权限为 0775。完全断电后，新旧两版都在 OpenSBI 阶段出现 hart 状态错误，未到 U-Boot 或 initramfs 加载。依据这一启动阶段顺序，尚不能将该故障归因于 boot_1106 的根文件系统变化。按任务要求记录为 failed 并回退。任务 004 结束时板子保留 11-05 版，RESET 后在登录提示处，串口采集已关闭。

## 需要人做的事

请审阅失败记录，确认完全断电启动时 OpenSBI hart 状态异常的后续排查任务。任务 004 结束时卡上为回退后的 11-05 版，后续状态见任务 005。备份目录 backup-20261107 仍在卡上。
