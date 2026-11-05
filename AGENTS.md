# AGENTS.md：给 Codex 的工作规则

你（Codex）负责在这块 RISC-V 开发板上做开发和调试。动手前先读 `README.md`、`docs/BOOT.md` 和 `handoff/README.md`。

**你只执行 `handoff/tasks/` 里的任务单**：人会告诉你执行哪一个。执行完按 `handoff/templates/report.md` 写报告。任务单之间的规划由 Claude 负责（总体路线见 `docs/PLAN.md`），不要越过当前任务单自行推进到下一阶段。

## 已核实环境与待确认项（任务 001，2026-11-05）

- Codex 主机是 Windows，使用 PowerShell、Python 3.13.13 和 pyserial 3.5；串口脚本为 `scripts/serial_console.py`。
- 人确认电脑 USB 线直连开发板调试 USB 口。当前识别到 `COM3`（`USB Serial Port (COM3)`）；端口名可能变化，每次操作前重新枚举。
- 人提供的 CPU 型号为 `UX900 RISC-V`，所接 USB 口标注为 `USBC1`，上电后电源指示灯亮。断开板子主电后 COM3 仍可识别。板级型号和 USBC1 到 CPU 控制台的实际连接尚未核实；CPU 信息来自人，尚无板上输出佐证。
- 人已确认 TF 卡插好、串口线接好、伺服驱动器动力电断开或电机未连接，并在采集启动后确认开发板上电。本次确认不能替代未来任务的现场确认。
- 已在 COM3 / 115200 / 8N1、无流控下读到可读的厂商欢迎语和 Linux 登录提示符，串口路径已验证；尚未捕获完整的 U-Boot/内核启动过程。此前两轮 115200 采集超时；57600 上电采集有乱码，暴露的 Windows 输出编码问题已修复。人随后明确指定使用 COM3 / 115200，后续按此设置操作。
- 人提出的免口令登录方式实测被拒绝；等待人手动登录并释放 COM3。不要猜测密码、改口令或绕过认证。登录交互仅存于已忽略的 `.venv`，不得公开提交。真机 `exec` 尚未验证，任务仍为 `blocked`，详见 `docs/BOARD.md` 和任务 001 报告。
- 以太网接线、板子 IP、SSH/SCP、芯片版本和内核信息均未确认；未修改主机或板子的网络配置。
- 按已有启动文档，根文件系统预期是 initramfs（`uInitrd.lz4`），重启后内存内改动会丢失；此项尚未通过板上输出核实。任务 001 不得写 TF 卡，挂载必须只读。
- 当前仓库只有文档和文件清单，没有启动镜像、`.ko` 或控制程序，也没有源码；不能用清单代替文件实测。

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
