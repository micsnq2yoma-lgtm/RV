# AGENTS.md：给 Codex 的工作规则

你（Codex）负责在这块 RISC-V 开发板上做开发和调试。动手前先读 `README.md`、`docs/BOOT.md` 和 `handoff/README.md`。

**你只执行 `handoff/tasks/` 里的任务单**：人会告诉你执行哪一个。执行完按 `handoff/templates/report.md` 写报告。任务单之间的规划由 Claude 负责（总体路线见 `docs/PLAN.md`），不要越过当前任务单自行推进到下一阶段。

## 环境假设（第 0 阶段核实后改写本节）

- Codex 运行在一台**主机**上，主机通过 **USB 串口**（U-Boot 和内核控制台）和**以太网**（SSH/SCP，如果板子支持）连接开发板。
- 板子的根文件系统是 initramfs（`uInitrd.lz4`），**重启后所有改动丢失**。要保留的文件放在 TF 卡（`/media`）或这个仓库里。
- 仓库里只有交叉编译好的二进制文件，没有源码。

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
