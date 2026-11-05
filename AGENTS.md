# AGENTS.md：给 Codex 的工作规则

你（Codex）负责在这块 RISC-V 开发板上做开发和调试。动手前先读 `README.md`、`docs/BOOT.md` 和 `handoff/README.md`。

**你只执行 `handoff/tasks/` 里的任务单**：人会告诉你执行哪一个。执行完按 `handoff/templates/report.md` 写报告。任务单之间的规划由 Claude 负责（总体路线见 `docs/PLAN.md`），不要越过当前任务单自行推进到下一阶段。

## 已核实环境与待确认项（任务 001，2026-11-05）

- Codex 主机是 Windows，使用 PowerShell、Python 3.13.13 和 pyserial 3.5；串口脚本为 `scripts/serial_console.py`。
- 人确认电脑 USB 线直连开发板调试 USB 口。当前识别到 `COM3`（`USB Serial Port (COM3)`）；端口名可能变化，每次操作前重新枚举。
- 人提供 CPU 型号 `UX900 RISC-V`、USB 口标注 `USBC1`。板上实测 riscv64、marchid=0x900、MMU sv39、compatible/model=nuclei,p0soc；控制台为 ttyNUC0。板子主电断开时 COM3 仍可识别；芯片硬件修订号未确认。
- 人已确认 TF 卡插好、串口线接好、伺服驱动器动力电断开或电机未连接，并在采集启动后确认开发板上电。本次确认不能替代未来任务的现场确认。
- COM3 / 115200 / 8N1、无流控已验证可读输出及真机 exec；本次 35 条命令取得返回码和提示符。此前超时和乱码见历史日志，Windows 输出编码问题已修复。已恢复 dmesg，完整 U-Boot 启动过程、bootcmd 和实际 fatload 仍未知。
- 旧的登录阻塞已解除：本次接入时已有 shell，没有再次发送或验证所提供凭据。认证信息不得写入飞书、仓库或公开日志；完整认证/串口记录只留在忽略目录 `.venv`。不猜测、修改口令或绕过认证。
- 内核为 `6.6.90-rt54+`、SMP PREEMPT_RT；物理内存 2 GiB，MemTotal=2047968 kB。CPU0–1 在线、CPU2–7 离线，内核报告后六核上线失败；预期核数未知。
- eth0=f9c210000.xec、eth1=f9cdc0000.xec，均绑定 nuclei-xec，无链路和业务 IP，SSH/SCP 未验证。未改网络或启动 DHCP。ecat_newchip 脚本地址匹配 eth1，仅为后续静态候选，未加载模块。
- 实测根文件系统为内存 rootfs，dmesg 确认 initramfs；重启不能依赖内存改动保留。TF 卡 /dev/mmcblk0p1 已只读检查并卸载。任务 001 不得写卡。
- 卡根目录四个启动文件 SHA-256 与卡内 rpmsg/ 对应文件逐一相同；三个大小不符合任务要求的新版。任务仍为 blocked，须由维护者提供正确镜像或调整任务，不自行换镜像或进入任务 002。
- 仓库仍没有镜像、模块二进制或源码；卡上三个 ko 目录共九个模块版本字符串与当前内核一致，仅完成静态读取，不保证 ABI 或加载成功。

## 安全规则（必须遵守）

1. **电机使能需要人工确认**。凡是可能让电机上电或运动的程序，包括 `demo/`、`robot/`、`test/`、`test_play/` 下的 `Trajectory_main` 和 `ec_dc_user_example_*`，运行前必须停下来，向人说明要跑什么、预期会怎么动、怎么停止，**拿到当次明确同意后**才能执行。之前的同意不能沿用到下一次。
2. 程序默认优先跑 `noenable-notrajectory` 版本，其次是 `noenable` 版本。
3. 每次运行控制程序都要准备好停止手段：知道进程号，`kill -INT`、`kill -9` 都能用；确认现场有人守着急停。
4. 改 TF 卡上的启动文件（`boot.scr`、`uImage.lz4`、`uInitrd.lz4`、`kernel.dtb`）之前，先备份到卡上的 `backup-YYYYMMDD/` 目录。
5. 不要 `dd` 写整张卡，也不要格式化，除非人明确要求，并且确认了目标设备名。
6. 不要把密码、密钥、IP 以外的内网信息提交到仓库。**这个仓库是公开的。**

## 工作方式

- 每个任务在独立分支上做（`task-NNN-简述`），完成后发 PR。PR 描述里链接报告，并写清楚做了什么、板子上的实际输出、哪些没做成。
- 板子上的原始输出（串口日志、`dmesg`、`ethercat` 命令输出）保存到 `logs/YYYYMMDD-NNN-主题.log` 并提交。结论写进 `docs/`。
- 结果如实汇报。命令失败就贴出错误输出，不要猜测或编造板子的输出。
- 遇到无法从板子或仓库中确定的问题（硬件接线、电机型号、`Trajectory_main` 的预期行为等），停下来问人。
- 新增的脚本放在 `scripts/`，用 POSIX `sh` 编写，板子上可能没有 bash。

## 常用命令

```sh
sh scripts/verify_manifest.sh          # 校验镜像文件齐全
ethercat master                        # 主站状态（加载模块之后）
ethercat slaves                        # 从站列表
dmesg | tail -50                       # 内核日志
```
