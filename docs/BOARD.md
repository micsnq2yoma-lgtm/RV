# 开发板实测记录（任务 001）

日期：2026-11-05，主机时区 America/Los_Angeles。状态：`blocked`。串口和只读命令通道已验证；TF 卡镜像不满足前置条件，U-Boot 全程和网络验证未完成。

## 主机与板级信息

| 项目 | 实测结果 |
|---|---|
| 主机 | Windows、PowerShell、Python 3.13.13、pyserial 3.5 |
| 接线 | 人报告 UX900 CPU、USBC1 USB 口；板子主电断开时 COM3 仍存在 |
| 串口 | COM3，115200 / 8N1，无流控；板上 ttyNUC0，当前终端 /dev/console |
| 登录 | 本次接入时已有 shell，没有再次发送或验证凭据；认证信息不公开 |
| 内核 | 6.6.90-rt54+，SMP PREEMPT_RT，riscv64；编译时间 2026-05-11 |
| CPU / MMU | mvendorid=0x536、marchid=0x900、mimpid=0x40000；sv39 |
| ISA | rv64imafdc_zicbom_zicntr_zicsr_zifencei_zihpm_sscofpmf_sstc_svpbmt |
| 在线 CPU | possible/present=0-7，online=0-1，offline=2-7 |
| 内存 | dmesg 识别物理 2 GiB；MemTotal=2,047,968 kB |
| compatible / model | 均为 nuclei,p0soc；原始 model 末尾 NUL 保留在私有记录 |
| 内核参数 | earlycon=sbi console=ttyNUC0 |
| 根文件系统 | 内存 rootfs，dmesg 确认解包 initramfs |
| TF 卡 | /dev/mmcblk0p1，vfat，曾只读挂载 /media，现已卸载 |
| 板上时间 | 1970-01-01，未校时；日志采用带时区的主机时间 |

证据：`logs/20261105-001-board-info.log` 与 `logs/20261105-001-dmesg.log`。

## TF 卡不符合任务前置条件

| 文件 | 任务要求（字节） | 实测（字节） | 结果 |
|---|---:|---:|---|
| boot.scr | 719 | 719 | 大小相同 |
| uImage.lz4 | 4,223,577 | 4,245,866 | 不符 |
| uInitrd.lz4 | 14,856,105 | 14,224,341 | 不符 |
| kernel.dtb | 8,621 | 9,238 | 不符 |

四个根目录文件与卡内 rpmsg/ 对应文件的 SHA-256 逐一相同（board-info 203–212 行），所以根目录实际为 rpmsg 文件副本。未修卡、更换或写入镜像。任务要求的 2026-11-05 新版尚未验证；文件一致性不能证明 U-Boot 本次实际从哪里加载。

| 文件 | 每对文件共享的 SHA-256 |
|---|---|
| boot.scr | `13bb8fa510a4d8517f2c830b809d976ae40de0700e62013602e6bee61d690ca0` |
| uImage.lz4 | `ac207eca3af4edf66db39be5efd369f52629bcab5c9c90441c5b118ca99a9fe9` |
| uInitrd.lz4 | `d64412c9d979d4455f457f0fc88777cbba049672589a5dd701747a3f14724ba8` |
| kernel.dtb | `41e37ed12024407aca57e758ce3def47f373d019d0253b7483c27fce44ab8525` |

## 网络与模块

| 网卡 | 平台设备 | 当前驱动 | 链路与地址 |
|---|---|---|---|
| eth0 | f9c210000.xec | nuclei-xec | NO-CARRIER，carrier=0，无业务 IP |
| eth1 | f9cdc0000.xec | nuclei-xec | NO-CARRIER，carrier=0，无业务 IP |

另有 lo、sit0，没有业务路由。未启动 DHCP、改网络或进行 ping/SSH/SCP 验证。

静态判断：ecat_newchip/ 更适合作为后续候选，其脚本指向 eth1、f9cdc0000.xec 和 ko_newchip/；旧 ecat 脚本写死的 f8b160000.xec 不存在。证据见 loader-excerpts 日志。芯片硬件修订号及驱动运行尚未验证，未执行加载脚本。

无 modinfo，改用板上 strings 读取 ecat/ko、ecat_newchip/ko、ecat_newchip/ko_newchip 共九个 .ko，均含：

```text
vermagic=6.6.90-rt54+ SMP preempt mod_unload modversions riscv
```

内核版本字符串一致，不代表符号 ABI 或加载成功。lsmod 为空，本次未加载任何模块。

存在 ssh、scp、sshd、udhcpc、ping、insmod、strings、base64、sha256sum、BusyBox 1.36.1；未找到 modinfo、dtc、tcpdump、dropbear、sftp-server、fw_printenv。存在二进制不等于服务已监听或连接成功。

## 警告与尚未确认项

CPU2–CPU7 均 failed to come online，最后仅上线两个 CPU（dmesg 74–80 行）。预期核数和原因未确认，未修改设备树、固件或 CPU 设置。已取到的内核缓冲区中未见 Kernel panic、Unable to mount 或 MMC error。

内核时间约 8.741 秒运行 /init，完整上电到 shell 耗时未测。U-Boot bootcmd、boot.scr 是否实际执行和三个 fatload 字节数均未确认。boot.scr 静态内容不能代替启动取证。

## 串口工具和日志范围

scripts/serial_console.py 只依赖标准库和 pyserial，连接参数置于模式名前：

```powershell
./.venv/Scripts/python.exe scripts/serial_console.py --port COM3 --baud 115200 --log logs/20261105-001-boot.log --timeout 180 capture --until 'login:|# $|=> $'
./.venv/Scripts/python.exe scripts/serial_console.py --port COM3 --baud 115200 --log .venv/serial-private.log exec 'uname -a'
```

capture 不发送字符。exec 用唯一整行标记隔离回显和旧数据，取得返回码后继续等待 shell 提示符；可通过 exec --prompt 改正则。命令在子 shell 中执行，cd 和环境变量不跨调用保留。超时不会停止板上命令；打开串口可能产生驱动控制线脉冲。

日志追加主机时间戳，UTF-8 分包合并解码，无效字节反斜杠转义；CLI 输出为 UTF-8，不转换 CRLF。正常返回远端退出码，本地超时 124，串口/日志错误 125，中断 130。

9 项主机测试通过（host-prep 104–120 行）。本次 35 条真机命令均取得返回码及提示符，无标记超时；31 条退出 0，4 条退出 1，来自缺少可选路径、工具或属性，不代表命令通道故障。

boot.log 仅含登录阶段；dmesg 日志是恢复的内核缓冲区，均非完整 U-Boot 日志。公开 board-info、network、loader 日志是标注范围的原始输出摘录，省略认证交换、真实 MAC、完整目录清单和带 NUL 的 model 输出；完整原始串口与命令记录未编辑，保留在本机忽略目录 .venv。公开日志不含口令。

TF 卡已卸载，串口已关闭。需要维护者提供目标镜像或调整任务，确认预期核数，补齐 U-Boot 全程和网络链路验证；不进入任务 002。

## 任务 002：Windows 读卡器识别（2026-11-05）

已收到任务 002 授权。按补充说明第 0 步，从上游 handoff-protocol（3ead0e6）建立 task-002-new-image-full-boot，并合并任务 001 分支（合并提交 1998ae5）。

只读识别结果见 logs/20261105-002-card-identify.log：Windows 磁盘 2，USB SDHC Card，Get-Disk 大小 31,914,983,424 字节，GPT，IsSystem/IsBoot 均为 False，Online/Healthy。两个分区分别为 1 GiB 和约 28.39 GiB，均显示 Unknown、无盘符；Get-Volume 没有可移动卷，该磁盘也没有可映射的 Windows 卷。

人已确认这张卡是准备使用的新卡，需要另行制卡任务。按补充 C 分支停止卡操作，没有分配盘符、初始化、挂载、格式化、创建备份或写入文件。因无盘符，未能读取卡根目录或验证卡上镜像，也没有把分区类型当作实际文件系统证据。本次板上信息未重新采集，以上任务 001 的板级数据仍是历史结果。

用户提供了本机 Dropbox Workspace/RV 目录。只读检查其 boot/，四个新版源文件的大小及 Dropbox content_hash 全部与任务 002 一致（card-identify 日志 18–31 行）。没有将源文件复制进仓库，也没有写入卡；C 节仍须对将来实际写到卡上的副本再次验证。

| 文件 | 源文件大小（字节） | 普通 SHA-256（供后续板上核对） |
|---|---:|---|
| boot.scr | 719 | `06203ccf2ed48380c99efbd9d449a9d2792805556105c57677cdc8ed09ce30f9` |
| uImage.lz4 | 4,223,577 | `b3f0662be615a73fa1d821b1c3aa1b3c068eaf6668c009982795626fa5437d92` |
| uInitrd.lz4 | 14,856,105 | `e4cf190f117d84ed7f8fe613ed5334165c267e5410b8f5c3228b613c502358b7` |
| kernel.dtb | 8,621 | `3b84109ee3c19c9aa546602bb1ee33f925d7cec7dee1cd14868adaeaaaa60edd` |

## 任务 003：新卡制卡与回读（2026-11-05）

本轮重新核对并经人当场确认的目标是磁盘 2（USB / SDHC Card，31,914,983,424 字节，非系统或启动盘），不是约 7.5 GiB 的原板卡。人手动批准了 UAC；管理员脚本再次确认目标及原 GPT 两分区布局后执行 Clear-Disk。旧分区已消失，但 Initialize-Disk -PartitionStyle MBR 报 `The disk has already been initialized.`。只读复核显示磁盘 2 仍为 GPT、无分区及盘符。

按任务 003 失败规则停止；未执行 New-Partition、Format-Volume、16 GiB 方案、复制、弹出或上板。源目录清单检查通过（checked=152、missing=0、size_mismatch=0），这不是卡上校验结果。原约 7.5 GiB 卡未操作；未获取新镜像的运行信息。详见 `logs/20261105-003-make-card.log` 与 `handoff/reports/003-make-new-boot-card.md`。

补充 1 经人工再次确认磁盘 2 后使用 Set-Disk 转为 MBR。最终为单个 31,913,410,560 字节分区，FAT32 卷 RVBOOT，弹出前盘符 F:。复制后回读四个启动文件的哈希全部匹配，清单 checked=152、missing=0、size_mismatch=0。Windows 已确认安全弹出，用户随后断电换卡。

## 任务 002：新版镜像实测（2026-11-05）

| 项目 | 旧版（任务 001） | 新版（任务 002） |
|---|---|---|
| 内核 | 6.6.90-rt54+，#1，2026-05-11 19:34:25 PDT | 6.6.90-rt54+，#6，2026-11-05 09:57:02 CST |
| CPU | 0–1 在线，CPU2–7 上线失败 | 0–1 在线，CPU2–7 上线失败。设备树 8 个 CPU 均为 okay |
| XEC | eth0 f9c210000.xec，eth1 f9cdc0000.xec，nuclei-xec | 地址和驱动相同。两个接口 carrier 均为 0 |
| 存储 | 7.50 GiB SD，mmcblk0 | 29.7 GiB SD，mmcblk0。另枚举 59.6 GiB eMMC，mmcblk1 |

COM3 / 115200 第二轮采集覆盖 OpenSBI v1.3（8 hart，启动 hart 1）、U-Boot 2024.01-00012-gc0a14d778e 和 Linux。U-Boot 的 bootcmd 为 `run distro_bootcmd`，扫描 mmc 0:1 并执行 boot.scr。三个 fatload 读入 4,223,577、14,856,105、8,621 字节。第三轮截停并记录五条只读命令，随后执行 boot。

Linux 从 /dev/mmcblk0p1 只读回读四个 SHA-256，全部与 Windows 回读匹配，随后确认卸载。新版启动日志显示 init 自动运行 udhcpc、启动 sshd，并记录 /lib/modules 目录缺失的 modprobe 提示。完整记录见 002 报告及 boot-full、uboot、board-info 三份日志。

用户选择跳过 D 节可选网络验证。连通性未测。
