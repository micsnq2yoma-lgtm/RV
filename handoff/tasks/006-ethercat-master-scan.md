# 任务 006：加载 EtherCAT 主站，扫描从站（电机不使能）

- **对应阶段**：docs/PLAN.md 第 3 阶段
- **作者**：Claude
- **日期**：2026-11-07
- **电机是否可能动作**：**否**。本任务只加载主站模块，读取从站信息。主站没有应用程序时，从站最多进入 PREOP 状态，不会进入 OP，也不会使能电机。即便如此，仍要求**伺服主电（动力电）断开**，只接控制电。
- **前置条件**：PR #3 的成果可用：卡上是 boot_1106；冷启动的临时办法是“接通主电后按一次 RESET”。新建分支 `task-006-ethercat-scan`，基于 `task-004-boot-1106`，再合并上游 `handoff-protocol`。PR 的目标分支是上游的 `handoff-protocol`。

## 背景

- 卡上的 `ecat_newchip/load_ec_module_master.sh` 内容如下（来自 Dropbox，361 字节）：
  ```sh
  MAC_ADDR=$(ip link show eth1 | awk '/link\/ether/ {print $2}')
  MAC_ADDR=00:11:22:33:44:55
  cd /media/ecat_newchip/ko_newchip
  insmod ec_master.ko main_devices=$MAC_ADDR
  echo "f9cdc0000.xec" > /sys/bus/platform/drivers/nuclei-xec/unbind
  insmod ec_nuclei_xec.ko
  echo "f9cdc0000.xec" > /sys/bus/platform/drivers/nuclei-xec-ecat/bind
  ```
  也就是说：主站用 **eth1**（`f9cdc0000.xec`），先把它从普通网卡驱动解绑，再绑到 EtherCAT 专用驱动。主站匹配的 MAC 地址写死为 `00:11:22:33:44:55`。
- 本任务**不运行这个脚本**，而是按它的顺序手动一条一条执行，每一步都检查结果。

## 不要做的事

- 不运行任何 `Trajectory_main`、`ec_dc_user_example_*`、`ec_user_example`、`ecat_sl.sh`。
- `ethercat` 命令行工具**只用只读子命令**：`master`、`slaves`（含 `-v`）、`pdos`、`domains`、`config`、`version`。**禁止**用 `states`、`download`、`sii_write`、`reg_write`、`foe_write`、`soe_write`、`alias`、`rescan` 以外的写操作；`rescan` 也只在 D 节说明的情况下用一次。
- 不用 `insmod -f` 强行加载，不改内核模块文件，不改卡上任何文件，TF 卡只读挂载。
- 不动 eth0。

## 步骤

### A. 现场确认

1. **[需人工]** 向人确认以下几点，答案写进报告：
   - EtherCAT 从站（伺服驱动器）是不是用网线接在开发板的 **eth1** 口上？开发板上哪个物理网口对应 eth1？不确定的话，请人说明网线插在哪个口（看丝印）。
   - 一共几台从站？型号分别是什么（`200` 还是 `GSD600`，或者其他）？
   - 从站的**控制电**已经接通（扫描需要），**主电或动力电已经断开**；急停已按下，或者电机已经拆下。

### B. 启动、登录、检查

2. 按任务 005 的方法启动：先接调试 USB，开始 `capture`，然后请人接主电；如果 120 秒内没有输出，请人按一次 RESET，抓到 `login:` 为止。日志存为 `logs/20261107-006-boot.log`。**[需人工]** 请人登录。
3. 只读挂载 TF 卡，执行以下命令，输出存到 `logs/20261107-006-precheck.log`。TF 卡设备名按任务 005 的方法判断：
   ```sh
   mount -o ro /dev/mmcblk0p1 /media
   ls -l /media/ecat_newchip /media/ecat_newchip/ko_newchip /media/ecat_newchip/ko /media/ecat_newchip/bin
   sha256sum /media/ecat_newchip/ko_newchip/*.ko /media/ecat_newchip/ko/*.ko
   cat /media/ecat_newchip/load_ec_module_master.sh
   ip link show eth1; cat /sys/class/net/eth1/carrier
   ls -l /sys/bus/platform/drivers/nuclei-xec/ /sys/bus/platform/drivers/ | head -60
   grep -i ethercat /proc/devices; ls -l /dev/EtherCAT* 2>&1
   uname -r; lsmod
   ```
   - 记下 eth1 当前的 MAC 地址（公开日志里打码），以及 `carrier` 是 0 还是 1。从站接好并上电时，应该是 1。
   - 如果 `carrier` 是 0：**[需人工]** 请人检查网线和从站的控制电，再查一次。还是 0 的话，照样继续 C 节（加载模块本身也是要验证的内容），但要在报告里写明。

### C. 加载主站（按脚本顺序，逐条执行）

每执行一条，都先 `dmesg | tail -20`，再继续下一条。全部输出存到 `logs/20261107-006-load.log`。

4. `cd /media/ecat_newchip/ko_newchip && insmod ec_master.ko main_devices=00:11:22:33:44:55`
   - 期望 dmesg 出现类似 `EtherCAT: Master driver ...`、`Master 0 ... waiting for device`。
5. `echo f9cdc0000.xec > /sys/bus/platform/drivers/nuclei-xec/unbind`，然后 `ip link show eth1`（eth1 应该消失）。
6. `insmod ec_nuclei_xec.ko`，然后 `ls /sys/bus/platform/drivers/ | grep -i xec`（应该出现 `nuclei-xec-ecat`）。
7. `echo f9cdc0000.xec > /sys/bus/platform/drivers/nuclei-xec-ecat/bind`
   - 期望 dmesg 里出现主站拿到网卡、链路 up、开始扫描的信息，例如 `Master 0: ... attached`、`Link state of ecm0 changed to UP`、`Starting EtherCAT-IDLE thread`、`Scanning bus`、`Bus scanning completed`、`N slave(s) responding`。
8. 设备节点：`ls -l /dev/EtherCAT0`。如果不存在，从 `/proc/devices` 里查出 `EtherCAT` 的主设备号 M，执行 `mknod /dev/EtherCAT0 c M 0`。这只是在内存里建节点，重启就没了。

### D. 只读查询

9. 设 `E=/media/ecat_newchip/bin/ethercat`。如果它提示找不到库，就加上 `LD_LIBRARY_PATH=/media/ecat_newchip/lib`。依次执行，输出存到 `logs/20261107-006-scan.log`：
   ```sh
   $E version
   $E master
   $E slaves
   $E slaves -v
   $E pdos
   $E domains
   $E config
   ```
10. 30 秒后再执行一次 `$E master` 和 `$E slaves`，对比帧计数和丢帧数（`Lost frames` 等），看链路是否稳定。
11. 如果 `slaves` 是空的，但 `carrier` 是 1，并且 dmesg 里没有扫描完成的记录：可以执行**一次** `$E rescan`，等 5 秒后再查。还是空的就停在这里，进入 E 节卸载。

### E. 卸载，并确认可以重复加载

12. 卸载，输出追加到 `logs/20261107-006-load.log`：
    ```sh
    echo f9cdc0000.xec > /sys/bus/platform/drivers/nuclei-xec-ecat/unbind
    rmmod ec_nuclei_xec
    rmmod ec_master
    echo f9cdc0000.xec > /sys/bus/platform/drivers/nuclei-xec/bind
    ip link show eth1; lsmod; dmesg | tail -30
    ```
    eth1 应该恢复成普通网卡。
13. 再按 C 节加载一次，执行 `$E master` 和 `$E slaves`，确认结果和第一次一致，然后再按第 12 步卸载。如果第一次卸载就出了问题（`rmmod` 报错、dmesg 出现 oops），**跳过**第 13 步。
14. 最后：`umount /media`。板子保持开机，停在登录状态。

### F. 整理

15. 新建 `docs/ETHERCAT.md`，记录：网口和接线；主站加载步骤和实测的 dmesg 关键行；从站列表（位置、厂商 ID、产品码、名称、状态）；`pdos` 摘要；链路稳定性；卸载和重新加载的结果。
16. 写报告 `handoff/reports/006-ethercat-master-scan.md`，在 `STATUS.md` 里加上 006，然后发 PR。

## 失败时怎么办

| 现象 | 处理 |
|---|---|
| `insmod` 报 `Invalid module format`、`Unknown symbol` 或 `disagrees about version` | 记录 dmesg，停止加载，**不要**用 `-f`。如果是在第 6 步失败，先把 eth1 重新绑回 `nuclei-xec`，再执行 `rmmod ec_master` |
| 第 7 步之后 dmesg 一直是 `waiting for device`，主站没拿到网卡 | 说明 `00:11:22:33:44:55` 和网卡实际的 MAC 对不上。卸载后，把第 4 步的 `main_devices` 换成第 3 步记下的 eth1 真实 MAC，**只重试一次**，结果写进报告 |
| 内核 oops 或 panic，系统无响应 | 保存串口日志。**[需人工]** 请人按 RESET 重启，确认能回到登录状态，然后停止任务并汇报 |
| 从站数量和人说的对不上，或者有从站停在 INIT、处于 ERROR 状态 | 照实记录 `slaves -v` 的输出，不要尝试改状态 |

## 需要回答的问题

1. 从站接在哪个网口上？共几台，什么型号？控制电和动力电的状态如何？
2. 四条加载命令各自的结果如何？主站有没有拿到网卡（用的是默认 MAC 还是真实 MAC）？
3. `ethercat slaves` 列出了几个从站？每个从站的厂商 ID、产品码、名称和当前状态是什么？
4. `pdos` 里有哪些 PDO 映射（只要摘要）？
5. 30 秒内链路稳定吗？有没有丢帧？
6. 卸载和重新加载能否正常完成，eth1 能否恢复？
7. dmesg 里有没有异常（oops、警告、超时）？
