# 任务 005：重新换上 boot_1106，并统计冷启动故障出现的频率

- **对应阶段**：docs/PLAN.md 第 2 阶段收尾
- **作者**：Claude
- **日期**：2026-11-07
- **电机是否可能动作**：**否**
- **前置条件**：在 PR #3 的分支 `task-004-boot-1106` 上继续工作，结果推到 PR #3。卡上还留着 `backup-20261107\`，当前根目录是回退后的 11-05 版。

## 背景和判断（来自报告 004）

- 完全断电后上电，启动停在 OpenSBI：`sbi_hsm_hart_start_finish: ERR: The hart is in invalid state [0]`。这时 U-Boot 还没运行，**TF 卡上的文件一个都没读**。旧版 11-05 镜像回退后，同样的错误照样出现；按一下 RESET 就能正常启动。所以这个故障**和 boot_1106 无关**，是闪存里固件（Nuclei SDK 引导程序和 OpenSBI）在冷启动时的问题。它很可能和 CPU2–7 起不来是同一类原因：OpenSBI 报告 `Platform HSM Device: ---`，其他核的启动状态管理有问题。
- 任务 004 回退的做法符合当时的失败规则，没有问题。但 boot_1106 本身已经验证过：复位启动、哈希、三处改动都确认了。维护者要的就是这个版本，所以要**重新换上**。
- boot_1106 的改动：新增 `/mount_emmc.sh`；`sshd_config` 里设了 `PermitRootLogin yes`；`/etc`、`/etc/ssh` 两个目录的权限改成了 0775。

## 不要做的事

- 不加载模块，不运行控制程序，不动 eth1。
- 不改闪存里的固件，不进 U-Boot 写环境变量。
- 卡上只动根目录的 `uInitrd.lz4`。

## 步骤

### A. 重新换上 boot_1106 的 uInitrd

1. **[需人工]** 请人给开发板断电，把卡插到主机上。找到唯一的 `RVBOOT` 卷（找卷的方法和任务 004 一样）。
2. 卡上已经有 `backup-20261107\`（11-05 版），**不要覆盖，也不要再建新备份**。核对卡根目录的四个文件：`uInitrd.lz4` 应该是 11-05 版（SHA-256 `e4cf190f…`），其他三个和报告 004 的表一致。
3. 把本机 Dropbox `boot_1106\uInitrd.lz4` 复制到卡根目录，然后回读：大小 14,857,818，SHA-256 `82a45be4f417110b532bd785f1d49353025ad0b62046754e74ceb1ee2c84181b`。弹出卡。输出存到 `logs/20261107-005-reapply.log`。
4. **[需人工]** 请人把卡插回断电状态的开发板。

### B. 统计冷启动故障

每一轮都按下面的流程做，一共 **5 轮**。每轮都要先请人操作：

- a. **[需人工]** 请人断开开发板主电源**和**调试 USB，等指示灯全部熄灭后，再等 10 秒。
- b. 先插调试 USB，等 COM3 出现后开始 `capture`：超时 120 秒，结束正则 `login:|invalid state`，开启自动重连。
- c. **[需人工]** 请人接通主电源。
- d. 如果日志里出现 `invalid state`：再抓 120 秒，请人按一次 RESET，记录能否到达 `login:`。
- e. 记录这一轮的结果：直接到 `login:` / 卡在 `invalid state` 后 RESET 恢复 / 其他（写清现象）。

日志每轮一个文件：`logs/20261107-005-cold-N.log`，N 为 1 到 5。

5 轮之后，**再做 2 轮“只按 RESET、不断电”**，作为对照：在 `login:` 提示符下请人按 RESET，抓到 `login:` 为止，日志是 `logs/20261107-005-reset-N.log`。

还要请人说明一件事：板子的主电源和调试 USB **哪个先接**，平时是怎么接的。先插调试 USB 的时候，板子有没有被它部分供电（指示灯是否会微亮）。

### C. 新镜像上的检查

5. 选一次到达 `login:` 的启动，**[需人工]** 请人登录，执行下面的命令，输出存到 `logs/20261107-005-board-info.log`：
   ```sh
   cat /proc/version
   ls -l /mount_emmc.sh
   grep -E '^PermitRootLogin' /etc/ssh/sshd_config
   ls -ld /etc /etc/ssh
   cat /sys/devices/system/cpu/online
   mount -o ro /dev/mmcblk0p1 /media && sha256sum /media/uInitrd.lz4; umount /media
   ```
   TF 卡设备名的判断方法和之前一样。`uInitrd.lz4` 的哈希必须是 `82a45be4…`。

### D. 整理

6. `docs/BOARD.md`：把当前镜像改成 boot_1106；新增一节“冷启动已知问题”，写上统计结果和临时办法（例如“上电后按一次 RESET”）。
7. 写报告 `handoff/reports/005-reapply-boot-1106-coldboot-stats.md`，在 `STATUS.md` 里加上 005，并把 004 的状态改成 `done（冷启动故障与镜像无关，见 005）`，推到 PR #3。

## 失败时怎么办

| 现象 | 处理 |
|---|---|
| RESET 之后也起不来 | 停止统计，记录现象，请人换回旧卡试一下，然后汇报 |
| 复位能到 `login:`，但新镜像下出现新的报错或登录失败 | 记录下来，暂时不回退（这个版本是维护者要的），汇报 |

## 需要回答的问题

1. 卡上的 `uInitrd.lz4` 是否已经是 boot_1106 版（`82a45be4…`）？
2. 5 次完全断电冷启动中，几次直接启动成功，几次卡在 `invalid state`？卡住之后 RESET 能不能每次都恢复？
3. 2 次只按 RESET 的结果如何？
4. 平时主电源和调试 USB 的接法是什么？先插调试 USB 时，板子有没有被部分供电？
5. 新镜像下的三处改动在板上是否都确认了？
