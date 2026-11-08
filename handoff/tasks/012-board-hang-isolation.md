# 任务 012：整板失联排查（稳定性优先于 S4）

- **对应阶段**：S3 收尾。这个问题不解决，不进入 S4
- **作者**：Claude
- **日期**：2026-11-08
- **电机是否可能动作**：**否**
- **前置条件**：分支 `task-012-hang-isolation`，基于 `task-011-pick-place`，再合并上游 `handoff-protocol`。

## 背景（报告 010、011）

| 运行 | `rt_ctl` 在哪运行 | 其他负载 | eMMC | 结果 |
|---|---|---|---|---|
| 010 正式测试 600 s | Buildroot `/tmp`，FIFO80，CPU1 | 只有很少的 TCP 请求 | Ubuntu 挂着，但写入很少 | **稳定** |
| 011 抓放 | **Ubuntu chroot**，FIFO80，CPU1 | Python 跑 IK（CPU0，单次约 1.6 s 满负载）、numpy；往 eMMC 写日志和图片 | 读写挂载，写入较多 | 跑到第 8 个种子时**整板失联** |
| 011 复测 | 同上 | 每 5 s 一个轨迹段，加一次渲染 | 同上 | 跑约 10 s 再次**整板失联** |

“整板失联”指：串口没有回显，SSH 和 ARP 都不通，必须按 RESET 才能恢复。重启后 eMMC 要做 journal 恢复，补拍的图片变成了 0 字节。目前**没有抓到任何内核信息**。

几个怀疑方向，都没有验证：
- 实时优先级的配置：`rt_ctl` 是 FIFO80，而 PREEMPT_RT 内核里网卡和 eMMC 的中断线程默认是 FIFO50，比它低；
- eMMC 驱动用的是 PIO 方式（启动日志里写着 `batched PIO`），在写入较多时可能出问题；
- 网卡驱动在持续负载下出问题；
- 硬件问题，比如供电或温度。

## 不要做的事

- 不改内核、设备树和闪存固件，不改 Windows 防火墙和 Clash。
- **测试期间不往 eMMC 写大文件**。日志写到板子的 `/tmp`（内存里），测完用 scp 取回。只有 A 节第 4 项故意测 eMMC 写入。
- 每次失联后，**先取证再按 RESET**，具体见 A 节。

## 步骤

### A. 先做好“死机取证”的准备（每次开机后都要做）

1. 开机，执行 `board_bootstrap.ps1`。然后在串口上执行下面的命令，输出存到 `logs/20261108-012-baseline.log`：
   ```sh
   dmesg -n 8                                    # 内核所有级别的消息都打到串口
   echo 1 > /proc/sys/kernel/sysrq 2>/dev/null; cat /proc/sys/kernel/sysrq
   cat /proc/sys/kernel/sched_rt_runtime_us /proc/sys/kernel/sched_rt_period_us
   ls /proc/sys/kernel/ | grep -iE "watchdog|lockup|hung|panic"
   for f in /proc/sys/kernel/{watchdog,softlockup_panic,hung_task_timeout_secs,panic}; do [ -f $f ] && echo "$f=$(cat $f)"; done
   cat /proc/interrupts
   ps -o pid,comm 2>/dev/null | head -80     # BusyBox 版本
   ```
   在 Ubuntu chroot 里另外执行：`ps -eLo pid,tid,cls,rtprio,psr,comm --sort=-rtprio | head -60`。这条命令列出所有实时线程（中断线程、ksoftirqd、rcu 等）的优先级，以及它们跑在哪个 CPU 上。
2. 在电脑上**全程持续抓串口日志**，从开机一直抓到测试结束，写到 `logs/20261108-012-serial-<实验名>.log`。
3. **失联时的取证流程**：
   - a. 先等 30 秒，看串口上有没有自动打出内核信息（softlockup、RCU stall、hung task、oops）。
   - b. 通过串口发 **SysRq**。用 pyserial 的 `send_break()` 发送 break，然后在 5 秒内发一个字母：先发 `w`（处于阻塞状态的任务），再发 `l`（每个 CPU 正在执行什么），最后发 `t`（所有任务，输出很长）。每个字母之间等 5 秒。每一步都要抓串口输出。
   - c. 如果 SysRq 完全没有反应，记录“SysRq 无响应”。这本身就是很重要的线索，说明内核基本停住了。
   - d. 记录板子上的指示灯状态，以及板子摸起来是否明显发热。**[需人工]** 请人观察。
   - e. 然后再请人按 RESET。重启后执行 `dmesg | head -50`，并检查 eMMC 挂载时的 journal 恢复信息。

### B. 隔离实验

每个实验跑 **10 分钟**，或者跑到失联为止。每次只改变一个因素。实验顺序如下；**一旦有实验复现了失联，就先按 A.3 取证，再做后面的实验**。

| 编号 | 配置 | 要验证什么 |
|---|---|---|
| E1 | 重复 010：`rt_ctl --sine` 在 Buildroot `/tmp` 里运行，FIFO80，CPU1；Ubuntu **不挂载** | 基线是否仍然稳定 |
| E2 | E1 的配置，同时在 Ubuntu chroot 里跑一个**纯计算负载**：不停地算 IK，**不写文件**，绑定 CPU0 | CPU 满负载 + 实时控制环 |
| E3 | E1 的配置，同时往 eMMC 持续写入：在 chroot 里循环执行 `dd if=/dev/zero of=/mnt/ubuntu/tmp/stress bs=1M count=50 conv=fsync`，每轮结束后删除文件 | eMMC 写入压力 |
| E4 | 复现 011 的完整配置（`rt_ctl` 在 chroot 里，加 IK 和技能循环），但**日志只写到 `/tmp`** | 能否复现 011 的失联 |
| E5 | E4 的配置，但 `rt_ctl` 用 **FIFO 40**（比中断线程的 50 低） | 优先级倒置的假设 |
| E6 | E4 的配置，但 `rt_ctl` 用 **SCHED_OTHER**（普通优先级） | 是否和实时调度有关 |

另外，在 E1 到 E3 运行期间，电脑上持续 `ping -t 192.168.50.2`，用来记录失联的准确时间。

每个实验结束后（没有失联的情况下），记录：
- `rt_ctl` 的统计；
- `cat /proc/interrupts` 和实验开始时相比的增量；
- `dmesg | tail -30`；
- 如果有 `/sys/class/thermal/thermal_zone*/temp`，记录温度。

### C. 仿真端 10 分钟验收（顺带完成 011 遗留的部分）

4. 在第一个连续稳定运行 10 分钟的“完整配置”实验里（E4、E5 或 E6），同时统计仿真端的指标：看门狗误触发次数、状态包到达间隔的最大值。这样就补上了 011 没完成的 10 分钟验收（标准见设计文档 3.4 节）。

### D. 整理

5. 根据实验结果，给出结论和建议。可能的结论有：
   - 只有 eMMC 写入会触发 → eMMC 驱动的问题，建议交给维护者；我们这边绕开：运行时不写 eMMC，或者改写 TF 卡、`/tmp`；
   - 只有 FIFO80 会触发，FIFO40 或 SCHED_OTHER 不会 → 调整我们的优先级方案，并写进设计文档；
   - 都不触发 → 写明条件，并记录对 011 和本次差异的分析；
   - 抓到了内核栈 → 附上栈，指出出问题的驱动或子系统。
6. 新建 `docs/STABILITY.md`，记录取证方法和实验结论。写报告 `handoff/reports/012-board-hang-isolation.md`，更新 `STATUS.md`，发 PR。

## 需要回答的问题

1. 中断线程（网卡、eMMC、串口）的实时优先级各是多少，分别绑在哪个 CPU 上？RT throttling 参数是多少？内核有没有开 softlockup 和 hung task 检测？
2. E1 到 E6 各自的结果：失联还是稳定，运行了多长时间。
3. 如果失联了，SysRq 有没有响应？抓到了什么内核信息？
4. 仿真端 10 分钟的指标：看门狗误触发次数、状态包到达间隔最大值。
5. 结论和建议：以后的 Agent 运行时，`rt_ctl` 用什么优先级，跑在哪里；日志和文件写到哪里。
