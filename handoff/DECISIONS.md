# 维护者确认的事实与决定

这里记录人（维护者）明确回答过的问题。Codex 每次执行任务前都要读一遍。这里的内容优先于任务单里的“未确认”或“待确认”。

| 日期 | 事项 | 结论 | 影响 |
|---|---|---|---|
| 2026-11-07 | 预期 CPU 核数 | **这块板子只有 2 个核** | CPU0–1 在线是正常的。CPU2–7 报 `failed to come online` 不是故障，而是设备树和 OpenSBI 按 8 核配置造成的，与硬件不符。以后报告里这一项只需记录“与预期一致（2 核）” |
| 2026-11-07 | 冷启动 | 临时办法：接通主电后按一次 RESET | 见报告 005。根因属于固件或硬件，交给维护者处理 |
| 2026-11-07 | 系统镜像 | 使用 boot_1106 | 见报告 004、005 |
| 2026-11-07 | 联网方式 | eth0（J1 口）用网线直连 Windows 电脑；eth1 留给 EtherCAT | 见任务 008 |
| 2026-11-08 | 联网方式（修订） | **不用 ICS**：它和电脑上 Clash 的 TUN 模式冲突（报告 008）。用固定 IP（电脑 `192.168.50.1`，开发板 `192.168.50.2`）跑 SSH/SCP。外网访问**通过 SSH 反向隧道**借用电脑 Clash 的 `127.0.0.1:7897` 代理；**不开 Allow LAN，不碰 Clash 的设置和防火墙规则**（r2 停用 Clash 自带的规则后，电脑断网） | 见任务 008-r3 |
| 2026-11-07 | 参考资料 | 芯来官方 Linux SDK：https://github.com/Nuclei-Software/nuclei-linux-sdk | 本板的 Buildroot、OpenSBI、U-Boot 都基于它，遇到问题先查它的 README 和 FAQ |
| 2026-11-08 | 新方向：仿真机器人 Agent Demo | 大模型用 **DeepSeek-V4.1-Flash-1017** API，机械臂用 **Franka Panda**（MuJoCo Menagerie）。电脑跑仿真，RV 板子跑感知、Agent、运动学和实时控制 | 见 `docs/SIM_AGENT_DESIGN.md`、任务 009、010 |
| 2026-11-08 | DeepSeek 模型 ID | 人选定 **`deepseek-flash`**（API 里没有 `DeepSeek-V4.1-Flash-1017`）。不依赖它的图片理解，见报告 009 | 见 `docs/SIM_AGENT_DESIGN.md` |
| 2026-11-08 | 整板失联（未解决） | 三次失联都发生在 eMMC 上的 Ubuntu 处于活动状态时；E1–E6 都没能复现（报告 012）。在找到原因之前，运行时的日志和图片写到 `/tmp`，并实时取回电脑；`rt_ctl` 继续用 FIFO80、绑定 CPU1，Python 绑定 CPU0 | 见 `docs/STABILITY.md`、任务 013 |
| 2026-11-08 | 供电方式 | **DC 电源插座供电**（人确认）。任务 013 的 A 节第 1 项不用再问，只需请人补充适配器规格；“USB-C 供电不足”这个可能已排除 | 任务 013 |

## 由此带来的待办（尚未安排成任务）

- 设备树（`kernel.dtb`）里 `cpu@2`–`cpu@7` 的 `status` 都是 `okay`，OpenSBI 也报告 `Platform HART Count: 8`。内核每等一个不存在的核就要超时约 1 秒，启动因此多花约 6 秒。冷启动时 OpenSBI 报的 `hart is in invalid state`，也**可能**和它按 8 核配置有关，目前只是推测，未验证。
- 修复办法：维护者在固件（OpenSBI）和设备树源文件里改成 2 核；或者由我们在卡上的 `kernel.dtb` 里把 `cpu@2`–`cpu@7` 改成 `disabled`，作为临时验证（可回退，不碰闪存固件）。是否这样做，等维护者决定。
