# 任务 002：换上新版启动文件，完整抓取上电过程

- **对应阶段**：docs/PLAN.md 第 0 阶段收尾和第 2 阶段
- **作者**：Claude
- **日期**：2026-11-05
- **电机是否可能动作**：**否**。不加载 EtherCAT 模块，不运行控制程序。
- **前置条件**：PR #1（任务 001）已合并，或者至少在它的分支上继续工作；`scripts/serial_console.py` 可用；COM3 / 115200。

## 背景（来自报告 001）

- TF 卡根目录的四个启动文件和卡上 `rpmsg/` 里的副本完全相同，**是旧版**。原因在规划这边：Dropbox 里的文件更新后，制卡用的还是更新前的那份。这不是 Codex 的问题。
- 任务 001 没抓到 U-Boot 输出。时间线是：115200 下上电，180 秒收到 0 字节；57600 下上电收到乱码；之后 115200 只收到 `Login timed out` 和登录提示。也就是说，**还没有一次在 115200 下从断电开始的完整抓取**。
- CPU2–7 启动失败，只有 2 个核在线；`f8b160000.xec` 不存在，`ecat_newchip` 的脚本地址和 eth1（`f9cdc0000.xec`）相符；两个网口都没有链路。

## 新版启动文件的校验值

人从 Dropbox `/Workspace/RV/boot/`（或 `/Workspace/RV/TF卡镜像/` 根目录，两处现在是一样的）下载。Dropbox 只提供 `content_hash`，所以用 `scripts/dropbox_content_hash.py` 计算后比对：

| 文件 | 大小（字节） | Dropbox content_hash |
|---|---:|---|
| boot.scr | 719 | `4e6d99cfe01c1c2b4f3f4bdee2d8acf90c00854ad915478ad5b366cf6c7f24da` |
| uImage.lz4 | 4,223,577 | `8ba0c95464d0507cb92ff57e8f949d10f0803d34b2f99855c0fe0fa145e59fdf` |
| uInitrd.lz4 | 14,856,105 | `66c8ab497246147fbbed00cdb8956cf56415203061fd5dd5a591af1e009d0d28` |
| kernel.dtb | 8,621 | `8abd45134a73698081794bf7b69b12833f6b9710955f6035ac67f5f14b93b502` |

## 不要做的事

- 不加载 `.ko`，不运行 `load_ec_*.sh`、`ethercat`、`Trajectory_main`、`ec_*example*`。
- 不在 U-Boot 里执行 `saveenv`、`env save`、`setenv`，也不执行任何写 flash 或写 mmc 的命令。U-Boot 里**只允许**执行 B 节列出的只读命令和 `boot`。
- 除了 A 节的备份和替换，不改 TF 卡上的其他内容。
- 不动 eth1：它是 EtherCAT 主站口。

## 步骤

### A. 替换启动文件（在 Windows 主机上操作）

1. **[需人工]** 请人：给开发板断电，取出 TF 卡，用读卡器插到主机上；把 Dropbox 里的四个新版文件下载到主机上一个临时目录（不要放进仓库）。问清楚 TF 卡在主机上的盘符。
2. 校验下载的文件：`python scripts/dropbox_content_hash.py <四个文件>`，大小和 content_hash 必须和上表**全部一致**。有任何一项不一致，就停下汇报。
3. 在卡上建 `backup-20261105/`，把卡根目录现有的四个文件**复制**进去（AGENTS.md 安全规则第 4 条）。先列出卡根目录，确认只操作这四个文件。
4. 把四个新文件复制到卡根目录，覆盖旧文件。然后再对卡上这四个文件运行一次 `dropbox_content_hash.py`，确认和上表一致；同时记下它们的普通 SHA-256，供 C 节在板上核对。
5. 用 Windows 的“安全删除硬件”弹出卡，**[需人工]** 请人把卡插回开发板。

### B. 从断电开始完整抓取上电过程

6. 先确认开发板处于**断电**状态，COM3 存在。启动 `capture`：115200，日志写到 `logs/20261105-002-boot-full.log`，超时 300 秒，结束正则 `login:`。
7. **[需人工]** 请人给开发板上电。要拔插电源，不要按复位键。记下上电的大致时刻。
8. 如果这次 300 秒内**一个字节都没收到**，或者只收到登录提示：
   - 请人说明板子上有哪些指示灯、分别是什么状态；
   - 再抓一次，这次请人上电后**马上按一下复位键**（如果有）；
   - 仍然没有 U-Boot 输出的话，可能是 OpenSBI 和 U-Boot 走的是另一个串口，或者用了别的波特率。报告 001 显示主机上有 “USB Serial Converter A” 和 “USB Serial Converter B” 两个通道，但只有一个 COM3。查一下 COM3 对应的是哪个通道，另一个通道有没有启用 VCP——**只看不改驱动**。需要启用的话，告诉人，由人来操作。把现象记下来，跳到 C 节继续。
9. 如果能看到 U-Boot 的倒计时（`Hit any key to stop autoboot`）：
   - 再做一次断电上电，倒计时期间发送一个回车，停在 `=> ` 提示符；
   - 依次执行下面的只读命令，输出存到 `logs/20261105-002-uboot.log`：
     ```
     version
     printenv
     mmc info
     fatls mmc 0
     bdinfo
     ```
   - 然后执行 `boot` 继续启动，并继续抓取到 `login:`。
10. 从日志里确认：OpenSBI 版本和 hart 数；U-Boot 是否执行了 `boot.scr`；三次 `fatload` 各读到多少字节，是否等于 4223577、14856105、8621。

### C. 启动后核对

11. **[需人工]** 登录。凭据由人手动输入或提供，不要写进日志或仓库。
12. 执行下面的命令，输出存到 `logs/20261105-002-board-info.log`：
    ```sh
    cat /proc/version
    uname -r
    cat /sys/devices/system/cpu/possible /sys/devices/system/cpu/online
    dmesg | grep -iE "smp|CPU[0-9]+|hart|failed" | head -40
    for c in /proc/device-tree/cpus/cpu@*; do echo "$c $(cat $c/status 2>/dev/null | tr -d '\0') $(cat $c/riscv,isa 2>/dev/null | tr -d '\0')"; done
    ls /sys/bus/platform/devices/ | grep -i xec
    ls /sys/bus/platform/drivers/ | grep -i xec
    ip -br link
    mount -o ro /dev/mmcblk0p1 /media && sha256sum /media/boot.scr /media/uImage.lz4 /media/uInitrd.lz4 /media/kernel.dtb; umount /media
    dmesg | grep -iE "error|fail|warn" | head -50
    ```
    卡上四个文件的 SHA-256 必须和第 4 步记下的值一致。

13. 和报告 001 的旧版镜像对比：内核编译时间（`Linux version ... #1 SMP ...` 那一行）、在线核数、CPU2–7 是否还失败、`xec` 设备和驱动列表、报错有没有变化。

### D. 网络（可选，需要人同意）

14. **[需人工]** 问人：能不能用网线把**主机直连 eth0**？如果可以，并且人同意，就在板上给 eth0 配一个临时静态 IP（例如 `ip addr add 192.168.77.2/24 dev eth0 && ip link set eth0 up`），主机网卡配 `192.168.77.1/24`，然后互相 ping 3 个包，再试一次 SSH 登录。这个 IP 在内存里，重启就消失。人不同意或不方便接线，就跳过这一步。**不要动 eth1。**

### E. 整理

15. 更新 `docs/BOARD.md`：新旧镜像对比、U-Boot 信息、CPU 情况。U-Boot 的 `printenv` 里如果有 MAC 地址或序列号，公开日志里打码。
16. 写报告 `handoff/reports/002-new-image-full-boot.md`，在 `handoff/STATUS.md` 里加上 002 这一行，然后发 PR。

## 失败时怎么办

| 现象 | 处理 |
|---|---|
| 下载的文件哈希对不上 | 停下，报告实际的值。不要用这些文件制卡 |
| 新镜像起不来：卡在 U-Boot、内核 panic、停在某处不动 | 保存完整日志。**[需人工]** 请人把 `backup-20261105/` 里的四个文件复制回卡根目录，恢复旧版，确认能再次启动，然后把状态标为 `failed` |
| 新镜像能起来，但 CPU2–7 照样失败 | 照实记录，不要尝试修复。这需要人提供预期核数，并确认硬件配置 |
| 仍然抓不到 U-Boot 输出 | 按第 8 步记录现象，其余步骤照常做完，状态标为 `done`，并在报告里列为未解决问题 |

## 交付物

- `logs/20261105-002-boot-full.log`，以及 `logs/20261105-002-uboot.log`（如果能进 U-Boot）
- `logs/20261105-002-board-info.log`
- `docs/BOARD.md` 更新
- `handoff/reports/002-new-image-full-boot.md`
- `handoff/STATUS.md` 更新

## 需要回答的问题

1. 下载的新版文件，以及写到卡上的文件，哈希是否都和上表一致？
2. 从断电开始的抓取里，能不能看到 OpenSBI 和 U-Boot 的输出？看不到的话，有哪些现象？
3. U-Boot 版本和 `bootcmd` 是什么？是否自动执行了 `boot.scr`？三个 `fatload` 各读到多少字节？
4. 新镜像的内核编译时间是什么，和旧版（2026-05-11）有什么不同？
5. 新镜像下有几个核在线？设备树里列了几个 CPU，各自的 `status` 是什么？
6. `xec` 设备和驱动列表有没有变化？
7. （做了 D 节的话）主机和板子能否 ping 通？能否 SSH？
8. 和旧镜像相比，还有哪些值得注意的差异或新出现的报错？
