# 板级稳定性与失联取证（任务 012）

E1–E6及一轮补充E4均完成600秒，窗口内未失联；但实验外准备阶段再次整板失联。
根因未确认，任务结果为 failed，不进入 S4。任务基于 `task-011-pick-place`，
合并上游 `handoff-protocol` 的 02a54d9。完整证据见
[报告012](../handoff/reports/012-board-hang-isolation.md)。

## 当前基线

独立 RESET 启动后，串口、eth0/J1 和 SSH 正常。串口、eth0/eth1、两路 MMC
中断线程均为 FIFO50，`Cpus_allowed_list=0`，有效 IRQ affinity 为 CPU0。
RT throttling 为 runtime=950000 us、period=1000000 us；没有修改它们。

`/proc/sys/kernel/sysrq`、`/proc/sysrq-trigger`、`/proc/config.gz` 均不存在。
没有找到 watchdog、softlockup 或 hung-task 对应 sysctl，panic=0。
因此无法保证该镜像的 SysRq 及锁死检测可用；不能把 SysRq 无响应单独当作
内核完全锁死的证据。没有修改内核、设备树或固件来补这些能力。

[Linux 官方 SysRq 文档](https://docs.kernel.org/admin-guide/sysrq.html)说明该功能
需要内核配置支持，串口触发还依赖端口支持 BREAK。维护者 SDK 参考为
[Nuclei Linux SDK](https://github.com/Nuclei-Software/nuclei-linux-sdk)；本机未暴露
内核配置，不能用 SDK 默认配置替代实测。

## 取证与文件位置

每次启动执行 `scripts/stability_baseline.sh`，开启 printk 全级别输出，并记录
中断计数、优先级、affinity、RT 限流和可用的温度读数。
Windows 的 `scripts/stability_serial.py` 持续保存串口原始输出；认证交互单独处理，
不放入公开日志。疑似失联后先观察30秒，再依次发送 BREAK+w、BREAK+l、BREAK+t，
相隔5秒。观察并记录指示灯和温度后，才由人复位。

控制器和负载输出写入 Buildroot `/tmp/rv012/logs`，同时经 SSH 流式保存到电脑，
以免复位丢失内存证据。正常结束后再次读取板上完整日志。
E2、E4–E6 将 Buildroot `/tmp` 绑定到 `/mnt/ubuntu/tmp`；源码、Python缓存、
日志和图片均使用内存，退出时先卸载这个绑定，再调用维护者的 stop 脚本。

E3 保留 Ubuntu 自己的 eMMC `/tmp`，使用唯一临时文件，每轮写50MiB并fsync后删除。
任务单中的 `/mnt/ubuntu/tmp/stress` 若在 chroot 内执行会重复根路径；实际使用
chroot 内 `/tmp/rv012-stress.*`，对应 Buildroot 的 `/mnt/ubuntu/tmp/rv012-stress.*`。
该实验是唯一故意施加 eMMC 写入负载的实验。

## 实验设计

全部使用任务011的控制器代码，新增可选 `--fifo-priority 40` 与 `--sched-other`，
默认仍为 FIFO80。Buildroot 无gcc，使用 Ubuntu gcc 编译到绑定的内存目录，
随后卸载 Ubuntu，在 Buildroot `/tmp` 执行 E1。
E1 重复010的运行环境和正弦负载，但程序含011新增接口；不声称二进制与010相同。

E1为卸载Ubuntu的正弦基线，E2加CPU0纯IK，E3加eMMC写入；E4为Ubuntu内完整技能循环，
E5仅改FIFO40，E6仅改普通调度。E4-verified是增加跨reset峰值后重跑的FIFO80对照。

| 实验 | PC计时秒 | 失联 | 看门狗次数 | 到包最大ms | 处理最大µs | 测量范围 |
|---|---:|---|---:|---:|---:|---|
| E1 | 600.000553 | 窗口内未失联 | 1 | 100.139929 | 512.598 | 单一统计周期 |
| E2 | 600.000305 | 窗口内未失联 | 0 | 23.210105 | 515.335 | 单一统计周期 |
| E3 | 600.001472 | 窗口内未失联 | 0 | 30.684985 | 578.786 | 单一统计周期 |
| E4 | 600.002242 | 窗口内未失联 | 0 | 83.010643 | 543.442 | 周期日志观测峰值，可能遗漏reset前尾段 |
| E4-verified | 600.001832 | 窗口内未失联 | 0 | 21.449352 | 556.191 | 跨reset生命周期计数 |
| E5 | 600.000529 | 窗口内未失联 | 0 | 20.673442 | 568.485 | 跨reset生命周期计数 |
| E6 | 600.001021 | 窗口内未失联 | 0 | 20.710649 | 4577.402 | 跨reset生命周期计数 |

E1看门狗1次时，PC同时出现97.5967ms物理步间隙和99.5803ms发送间隙；
程序的board_silence标签不足以将原因归于板子。原E4观测83.010643ms超标，
同时PC发送间隙82.5039ms。保留这些失败，不用后续达标样本替换。

原E4普通计数随场景reset清零，可能遗漏两个打印点之间的峰值；补充的lifetime
计数跨reset保持，正式E4-verified、E5、E6使用相同二进制与负载源码。
E4-verified和E5达到600秒、零看门狗、到包最大<50ms、处理最大<1ms；
E6普通调度的处理峰值超过1ms，不能作为实时指标达标样本。
PC最后一行的RTT和包数仍属于最后一个reset周期，不是全窗口汇总。

E2完成325次IK。E3完成89轮50MiB写入，至少4450MiB，eMMC IRQ16增量38070；
末轮中止后清理临时文件。E1两路MMC中断增量为0。没有读到温度传感器数值。

## E4 结束后准备阶段失联

首次 E4 正常退出，Ubuntu 于 2026-11-08 01:09:14（America/Los_Angeles）卸载。
随后为补充跨reset峰值计数，准备命令重新挂载Ubuntu、绑定内存/tmp并编译C程序。
串口最后确认01:09:39挂载成功，之后命令未返回，SSH读取超时、ping连续失败，ARP为Incomplete。
命令链中没有运行rt_ctl；具体停在挂载后的哪一个子步骤尚未确认，不能直接归因于gcc。

01:11:14开始追加30秒被动观察，随后依次发送BREAK+w/l/t，没有收到诊断输出。
普通串口存活标记与uptime也在10秒内收到0字节。主机网口保持Up/100Mbps，未改网络。
由于缺少SysRq接口，不能将SysRq无响应单独解读成内核完全锁死。
现场确认电源灯亮、无明显发热、接线未变后人工复位。恢复挂载有EXT4 journal recovery；
dpkg审计无输出，numpy1.26.4可用。同一编译流程加即时阶段记录后成功，随后完成剩余实验。
初始编译工具超时丢失了缓冲的部分stdout，因此不能定位挂载后的具体失败子命令。

这次失联位于测试窗口之外；不能改写前四个窗口的结果，也不能把整体系统说成已经稳定。

## 配置建议与安全收尾

中断线程有效CPU0、控制主线程CPU1，不是简单的80>50就可认定同核抢占。
无控制器运行时也发生失联，现有结果不足以确认优先级是根因。保留默认FIFO80；
FIFO40与SCHED_OTHER仅作为诊断选项，不宣称已修复。维护者应审阅准备阶段的失联，
提供具备SysRq/lockup取证能力且确认串口BREAK支持的诊断镜像，再决定下一任务。
未改内核、设备树、闪存固件、Clash、防火墙或eth1。

后续试验继续将控制器绑定CPU1、Python绑定CPU0，日志和图片写RAM并流式取回电脑。
无明显发热不能替代温度或电源测量。单次十分钟稳定也不代表长期可靠。

诊断选项示例（仅在任务要求的仿真环境准备完成后运行）：

```sh
/tmp/rv012/rt_ctl-buildroot --cpu 1 --sine
chroot /mnt/ubuntu /tmp/rv012/src/rt_ctl --cpu 1 --fifo-priority 40
chroot /mnt/ubuntu /tmp/rv012/src/rt_ctl --cpu 1 --sched-other
```

正常退出时先结束本次Python负载和控制器，确认进程退出，取回RAM日志，然后：

```sh
umount /mnt/ubuntu/tmp       # 仅本次确有该RAM绑定时
sh /mount_emmc.sh stop
sh /mount_emmc.sh status
```

不得强制卸载。失联时先完成取证与人工观察，再请人RESET。本轮最终确认所有实验进程退出、
Ubuntu及子挂载消失、控制Unix socket消失；未建立代理隧道，主机联网及原网络设置正常。
