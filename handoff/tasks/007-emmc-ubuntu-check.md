# 任务 007：检查 eMMC 上的 Ubuntu，并用 `/mount_emmc.sh` 进入它

- **对应阶段**：新增（使用 eMMC 系统）
- **作者**：Claude
- **日期**：2026-11-07
- **电机是否可能动作**：**否**
- **前置条件**：卡上是 boot_1106（自带 `/mount_emmc.sh`）。本任务和任务 006 相互独立，先做哪个都行；两个任务不要在同一次开机里交叉进行。分支 `task-007-emmc-ubuntu`，基于 `task-004-boot-1106`，再合并上游 `handoff-protocol`。

## 背景

- 板载 eMMC 在 Linux 下是 `mmcblk1`（59.6 GiB，型号 CJUD4R），上面只有一个分区 `mmcblk1p1`。TF 卡是 `mmcblk0`。
- U-Boot 里只有一个 `nuclei_mmc` 设备，`boot_targets=mmc0`，也就是只从 TF 卡启动。**U-Boot 目前看不到 eMMC，不能直接从 eMMC 启动。**
- boot_1106 新增的 `/mount_emmc.sh` 是维护者给的使用方式：先从 TF 卡启动 Buildroot，然后把 `/dev/mmcblk1p1`（ext4）挂载到 `/mnt/ubuntu`，再挂上 proc、sys、dev、dev/pts、run，复制 DNS 配置，最后 `chroot` 进去运行 `/bin/bash`。用法是 `sh /mount_emmc.sh start|stop|status`。退出 chroot 后挂载会保留，要再执行 `stop` 才会卸载。
- eMMC 上到底有没有完整的 Ubuntu，还没有验证过。

## 不要做的事

- 不格式化、不分区、不 `dd` eMMC，也不改动 `mmcblk1boot0`、`mmcblk1boot1`。
- 在 chroot 里**不执行** `apt upgrade`、`apt install`、`passwd` 这类命令，不改 Ubuntu 的配置文件，不启动服务（`systemctl` 在 chroot 里也用不了）。本任务只做查看。
- 不加载 EtherCAT 模块，不运行控制程序。

## 步骤

1. 启动并登录（上电后需要按一次 RESET，见 `handoff/DECISIONS.md`）。日志存为 `logs/20261107-007-boot.log`。

2. **先只读查看**，输出存到 `logs/20261107-007-emmc.log`：
   ```sh
   cat /sys/block/mmcblk1/device/type /sys/block/mmcblk1/device/name /sys/block/mmcblk1/size
   cat /proc/partitions | grep mmcblk1
   blkid /dev/mmcblk1p1 2>/dev/null || true
   mkdir -p /mnt/emmc_ro && mount -o ro /dev/mmcblk1p1 /mnt/emmc_ro
   df -h /mnt/emmc_ro
   ls -la /mnt/emmc_ro
   cat /mnt/emmc_ro/etc/os-release
   ls -l /mnt/emmc_ro/bin/bash /mnt/emmc_ro/sbin/init /mnt/emmc_ro/lib/systemd/systemd 2>&1
   ls /mnt/emmc_ro/lib/modules 2>&1
   ls /mnt/emmc_ro/home 2>&1
   du -sh /mnt/emmc_ro/usr 2>/dev/null
   umount /mnt/emmc_ro
   ```
   - 如果挂载失败，或者里面不是 Ubuntu：记录现象，**停在这一步**，状态标为 `blocked`，问人 eMMC 是否已经烧写了 Ubuntu。

3. **用维护者的脚本进入 Ubuntu**，输出追加到同一个日志：
   ```sh
   sh /mount_emmc.sh status
   sh /mount_emmc.sh start
   ```
   `start` 会进入一个交互式的 bash（提示符会变）。`serial_console.py exec` 需要能识别新的提示符；如果识别不了，就改用 `capture` 加手动发送的方式。在 chroot 里执行：
   ```sh
   cat /etc/os-release
   uname -a
   id
   which apt python3 gcc make git 2>&1
   python3 --version 2>&1
   gcc --version 2>&1 | head -1
   ls /usr/lib/riscv64-linux-gnu 2>/dev/null | head -5
   df -h /
   exit
   ```
   退出后执行：
   ```sh
   sh /mount_emmc.sh status
   sh /mount_emmc.sh stop
   sh /mount_emmc.sh status
   ```
   最后确认 `/mnt/ubuntu` 下已经没有任何挂载。

4. 整理：新建 `docs/EMMC.md`，记录 eMMC 型号和容量、分区和文件系统、Ubuntu 版本、可用的工具（python3、gcc 等），以及进入和退出的步骤。写报告 `handoff/reports/007-emmc-ubuntu-check.md`，更新 `STATUS.md`，发 PR。

## 失败时怎么办

| 现象 | 处理 |
|---|---|
| `start` 报错，没有进入 chroot | 脚本会自动撤销挂载。执行 `status` 确认已经撤销，记录错误信息后停止 |
| 进入 chroot 后串口卡住 | 发送 `exit`，或者按 Ctrl-D。还是不行的话，**[需人工]** 请人按 RESET。重启后 `/mnt/ubuntu` 的挂载自然就没了（根文件系统在内存里），但要在报告里写明这次是非正常卸载，以后用 eMMC 前最好检查一下文件系统 |
| `stop` 报 `Cannot unmount` | 执行 `fuser -m /mnt/ubuntu`（如果有这个命令）或 `ps`，看是谁在占用，记录下来。**不要**用 `umount -l` 强行卸载 |

## 需要回答的问题

1. eMMC 的分区和文件系统是什么？装的是哪个版本的 Ubuntu？占用了多少空间？
2. `/mount_emmc.sh start` 能否正常进入？chroot 里有哪些开发工具（python3、gcc、make、git）？
3. `stop` 能否干净地卸载？
4. eMMC 的 Ubuntu 里有没有 `/lib/modules/6.6.90-rt54+`、systemd 这些文件？这关系到以后能不能直接从 eMMC 启动。
