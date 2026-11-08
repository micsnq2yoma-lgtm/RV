# eMMC Ubuntu 使用记录

2026-11-07 任务 007 实测。板子先从 TF 卡 boot_1106 启动 Buildroot，使用维护者 /mount_emmc.sh 进入 eMMC 上的 Ubuntu chroot。进入与退出已验证，最终挂载已清理。

## 存储与系统

| 项目 | 实测值 |
|---|---|
| eMMC | /dev/mmcblk1，MMC，CJUD4R |
| 普通用户区容量 | 124,993,536 个 512 字节扇区，63,996,690,432 字节，59.6015625 GiB |
| 分区 | 单个 /dev/mmcblk1p1，62,496,760 KiB，63,996,682,240 字节 |
| 文件系统 | ext4 |
| Ubuntu | 24.04.3 LTS，Noble Numbat，riscv64 |
| 空间 | BusyBox 只读 df 显示 58.4G、已用 1.1G、可用 54.3G、2%。Ubuntu df 显示 59G、已用 1.2G、可用 55G、3% |
| /usr | du 显示 757.0M |
| 共享内核 | 6.6.90-rt54+ #6 SMP PREEMPT_RT，来自 TF 启动 |
| CPU | 2 核上线，与维护者确认的硬件预期一致 |

只读检查使用 ext4 ro,noload，挂载选项显示 ro,norecovery。内核输出过 orphan cleanup on readonly fs，维护者脚本第一次以 rw 挂载时输出 recovery complete，随后均正常卸载，原始信息见任务日志。

## 工具与系统文件

| 工具或文件 | 结果 |
|---|---|
| apt | /bin/apt |
| Python | /bin/python3，Python 3.12.3 |
| GCC | /bin/gcc，13.3.0，Ubuntu 13.3.0-6ubuntu2~24.04.1 |
| make | /bin/make |
| git | 未在 PATH 中找到，组合 which 查询返回 1 |
| bash | /bin/bash 可执行 |
| systemd | /lib/systemd/systemd 可执行，88,480 字节 |
| init | /sbin/init 链接到 ../lib/systemd/systemd |
| 内核模块 | /lib/modules 目录缺失，因而 /lib/modules/6.6.90-rt54+ 也缺失 |

## 进入和退出

先接通主电并按一次 RESET，登录 Buildroot。维护者脚本挂载 /dev/mmcblk1p1 为 rw，再挂 proc、sys、dev、dev/pts、run，复制 DNS 配置并进入交互式 bash。

```sh
sh /mount_emmc.sh status
HISTFILE=/dev/null sh /mount_emmc.sh start
```

进入 Ubuntu 后，本次会话关闭历史记录，然后执行查看命令。

```sh
HISTFILE=/dev/null
set +o history
cat /etc/os-release
uname -a
id
which apt python3 gcc make git
python3 --version
gcc --version | head -1
df -h /
exit
```

exit 返回 Buildroot 后，先查看保留的挂载，再执行 stop 和最终检查。

```sh
sh /mount_emmc.sh status
sh /mount_emmc.sh stop
sh /mount_emmc.sh status
awk '$2=="/mnt/ubuntu" || index($2,"/mnt/ubuntu/")==1 {print}' /proc/mounts
```

成功结束时 status 显示 Ubuntu root is not mounted，最后的 awk 没有输出。实测 stop 两次均返回 0。当前 eMMC 已卸载，板子处于 Buildroot shell。

## 已验证范围

本次检查了文件系统、系统文件和工具版本，验证 start、交互命令、exit、stop 的完整流程。首次主机提示符识别超时已正常退出并卸载，修正后重试成功。维护者脚本 SHA-256 为 `d31e23ca801f024d30f1b9210651017f224dc7b5298b328661b53e69379cfcad`，与 boot_1106 一致。

当前 U-Boot 只从 TF 卡启动的限制来自任务 007 的前置记录。直接从 eMMC 启动尚未验证，目标模块目录缺失已记录。

[任务报告](../handoff/reports/007-emmc-ubuntu-check.md)、[启动日志](../logs/20261107-007-boot.log)、[eMMC 与 chroot 日志](../logs/20261107-007-emmc.log)。公开日志对标识符脱敏，原始记录留在本机忽略目录。
