# 任务 001：插卡上电，完成启动、登录，摸清板子情况

- **对应阶段**：docs/PLAN.md 第 0 阶段
- **作者**：Claude
- **日期**：2026-11-05
- **电机是否可能动作**：**否**。本任务不加载 EtherCAT 模块，也不运行任何控制程序。
- **前置条件**：
  - 一张 TF 卡已经按 `docs/BOOT.md` 第 1 节做好：根目录有 `boot.scr`、`uImage.lz4`、`uInitrd.lz4`、`kernel.dtb`，另有一个 `ecat/` 目录。这是 2026-11-05 版的启动文件，大小分别为 719、4223577、14856105、8621 字节。
  - 主机通过 USB 串口线连接开发板的调试串口。如果有网线，也一并接好。

## 目标

让开发板从 TF 卡启动到 Linux shell，把完整的启动日志和板子的基本信息记录下来，并建立一个**可以让 Codex 非交互地向板子发命令、取回输出**的串口通道，供后续任务使用。

## 不要做的事

- 不要 `insmod` 任何 `.ko`，不要运行 `load_ec_*.sh`、`Trajectory_main`、`ec_*example*` 或 `ethercat` 命令。这些属于任务 002 及以后。
- 不要格式化 TF 卡，不要 `dd`，不要修改卡上的任何文件。挂载卡时一律只读挂载（`mount -o ro`）。
- 不要在 U-Boot 里执行 `saveenv`、`env save`，也不要执行任何写 flash 或写 mmc 的命令。
- 不要修改板子的网络配置，也不要启动 DHCP 客户端，除非第 7 步得到了人的同意。

## 步骤

### A. 主机准备

1. 确认主机上可用的串口设备和工具：
   ```sh
   ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
   dmesg | grep -iE "tty(USB|ACM)" | tail
   which picocom minicom screen python3; python3 -c "import serial; print(serial.__version__)"
   ```
   都没有的话，安装 `pyserial`（`pip install pyserial`）。工具优先用 Python，方便后面写成脚本。

2. 写 `scripts/serial_console.py`，后续任务都会用到。要求如下：
   - 参数：`--port`、`--baud`（默认 115200）、`--log`（追加写入日志文件，每行带主机时间戳）。
   - `capture` 模式：持续读取串口并写入日志，直到出现指定的正则（例如 `login:|# $`）或超时。
   - `exec` 模式：发送一条命令，等待 shell 提示符返回，打印这条命令的输出。实现方法是在命令后追加 `; echo __RC=$?__` 作为结束标记，以便拿到返回码。
   - 只用 Python 标准库加 `pyserial`。

### B. 上电启动

3. **[需人工]** 请人确认以下几点后再继续：TF 卡已插好；串口线已接好；**伺服驱动器的动力电已断开，或者电机没有接上**（本任务用不到电机，断开最安全）；开发板目前处于断电状态。

4. 先启动 `capture`：日志写入 `logs/20261105-001-boot.log`，超时设为 180 秒，结束正则为 `login:|# $|=> $`（`=> ` 是 U-Boot 的提示符）。然后 **[需人工]** 请人给开发板上电。

5. 检查启动日志，逐项确认：
   - U-Boot 是否运行了 `boot.scr`：日志里应出现 `Boot images located in .`、`Loading kernel: ./uImage.lz4`、`Starts booting from SD`。
   - 三个 `fatload` 各读到了多少字节，是否分别等于 4223577、14856105、8621。
   - 内核版本行（`Linux version ...`）和启动耗时。
   - 有没有 `Kernel panic`、`Unable to mount`、`mmc.*error`、`timeout` 一类的报错。

6. 如果启动停在 U-Boot 提示符（`=> `），说明没有自动运行 `boot.scr`。这时：
   - 先执行 `printenv bootcmd` 和 `fatls mmc 0`，把输出记下来。这两条都是只读命令。
   - 再按 `docs/BOOT.md` 第 2 节手动输入四条命令启动。
   - **不要改环境变量。** 在报告里说明 `bootcmd` 原来是什么。

### C. 登录后采集信息

7. 登录。登录方式不确定时 **[需人工]** 问人；常见的是 `root`，没有密码。然后用 `serial_console.py exec` 依次执行下面的命令，输出写入 `logs/20261105-001-board-info.log`：
   ```sh
   uname -a
   cat /proc/version
   cat /proc/cpuinfo
   cat /proc/meminfo | head -5
   cat /proc/cmdline
   cat /proc/device-tree/compatible | tr '\0' '\n'
   cat /proc/device-tree/model 2>/dev/null; echo
   df -h; mount
   ls -l /dev/mmcblk* /dev/ttyS* 2>/dev/null
   ip addr; ip route
   lsmod
   ls /sys/bus/platform/drivers/ | grep -iE "xec|eth|mmc"
   ls /sys/bus/platform/devices/ | grep -i xec
   which ssh scp dropbear sshd sftp-server udhcpc ping insmod modinfo dtc tcpdump 2>/dev/null
   busybox 2>&1 | head -3
   date
   dmesg | grep -iE "error|fail|warn" | head -50
   ```
   如果板子上有网线但没有 IP，**[需人工]** 先问人：能不能运行 `udhcpc -i <网卡>`，或者手动配置一个静态 IP。得到同意后再执行。

8. 只读挂载 TF 卡并核对卡上的内容：
   ```sh
   mkdir -p /media && mount -o ro /dev/mmcblk0p1 /media   # 设备名以第 7 步看到的为准
   ls -la /media /media/ecat /media/ecat/ko
   wc -c /media/boot.scr /media/uImage.lz4 /media/uInitrd.lz4 /media/kernel.dtb
   ```
   拿卡上文件的大小和本任务“前置条件”里列的数字比对。

9. 检查内核模块和当前内核是否匹配。只读取信息，**不加载**：
   ```sh
   for k in /media/ecat/ko/*.ko; do echo "== $k"; modinfo "$k" | grep -E "vermagic|depends|name"; done
   uname -r
   ```
   板子上没有 `modinfo` 的话，在主机上对仓库里的 `tf-card/ecat/ko/*.ko` 运行 `strings <ko> | grep vermagic`。如果仓库里还没有镜像文件，就在报告里注明“未能检查”。

10. 判断芯片版本：比较第 7 步里 `compatible`、`model` 和 `/sys/bus/platform/devices/` 的结果，以及 `load_ec_module_master.sh` 用到的 `f8b160000.xec` 设备是否存在，推断该用 `ecat/` 还是 `ecat_newchip/`。依据写进报告。判断不了就写“未确认”。

11. 网络连通性（有网线时）：主机和板子互相 `ping` 3 个包。如果板子有 `dropbear` 或 `sshd`，从主机试一次 SSH 登录，**只连接，不改任何配置**。

12. 卸载 TF 卡（`umount /media`）。

### D. 整理

13. 写 `docs/BOARD.md`，内容包括：串口设备和参数、登录方式、U-Boot 的 `bootcmd`、内核版本、CPU/ISA、内存、`compatible`、TF 卡设备名、网卡列表和 IP、可用工具（ssh、scp、modinfo 等）、芯片版本结论。
    **IP 只写局域网地址，不要写账号密码**：仓库是公开的。
14. 按实际情况改写 `AGENTS.md` 的“环境假设”一节。
15. 按 `handoff/templates/report.md` 写 `handoff/reports/001-tf-card-boot-bringup.md`，更新 `handoff/STATUS.md`，然后发 PR。

## 失败时怎么办

| 现象 | 处理 |
|---|---|
| 串口完全没有输出 | 依次换波特率试：115200、57600、921600、1500000。检查是否接错了 USB 口、TX/RX 是否接反（问人）。都不行就把状态标为 `blocked`，写清楚试过哪些组合 |
| 有输出，但全是乱码 | 波特率不对，按上一行的顺序换着试 |
| U-Boot 报 `fatload` 失败或找不到文件 | 记录 `fatls mmc 0` 和 `mmc info` 的输出，**不要修卡**。标为 `blocked`，请人检查卡是不是 FAT32、文件是不是放在根目录 |
| 内核 panic，或者启动卡住 | 保存完整日志，标为 `failed`。**不要**自行换别的镜像试。换镜像需要 Claude 另出任务单（对照组是 `tf-card/rpmsg/`） |
| 进了 shell，但 `/dev/mmcblk*` 不存在 | 记录 `dmesg | grep -i mmc`，跳过第 8、9 步，在报告里说明 |
| `serial_console.py exec` 拿不到输出或返回码 | 先用 `capture` 手动交互完成采集，保证这次任务的信息拿到手；脚本的问题写进报告 |

## 交付物

- `scripts/serial_console.py`
- `logs/20261105-001-boot.log`
- `logs/20261105-001-board-info.log`
- `docs/BOARD.md`
- `AGENTS.md`：“环境假设”一节更新
- `handoff/reports/001-tf-card-boot-bringup.md`
- `handoff/STATUS.md`：任务 001 状态更新

## 需要回答的问题

1. 板子能否从这张 TF 卡自动启动到 shell？如果不能，卡在哪一步？
2. 串口设备、波特率、登录方式分别是什么？
3. U-Boot 的 `bootcmd` 是什么？会自动运行 `boot.scr` 吗？
4. 内核版本是什么（`uname -r`），和 `.ko` 的 `vermagic` 是否一致？
5. CPU 是 rv32 还是 rv64，ISA 字符串是什么？内存多大？
6. 设备树的 `compatible` 是什么？`f8b160000.xec` 设备是否存在，当前绑定在哪个驱动上？
7. 应该用 `ecat/` 还是 `ecat_newchip/`？依据是什么？
8. 板子上有哪些网卡（eth0、eth1……）？有没有 IP？主机能否 SSH 或 SCP 到板子？
9. 启动日志里有哪些报错或警告值得关注？
10. `serial_console.py exec` 能否稳定使用？已知的限制有哪些？
