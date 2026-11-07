# 维护者确认的事实与决定

这里记录人（维护者）明确回答过的问题。Codex 每次执行任务前都要读一遍。这里的内容优先于任务单里的“未确认”或“待确认”。

| 日期 | 事项 | 结论 | 影响 |
|---|---|---|---|
| 2026-11-07 | 预期 CPU 核数 | **这块板子只有 2 个核** | CPU0–1 在线是正常的。CPU2–7 报 `failed to come online` 不是故障，而是设备树和 OpenSBI 按 8 核配置造成的，与硬件不符。以后报告里这一项只需记录“与预期一致（2 核）” |
| 2026-11-07 | 冷启动 | 临时办法：接通主电后按一次 RESET | 见报告 005。根因属于固件或硬件，交给维护者处理 |
| 2026-11-07 | 系统镜像 | 使用 boot_1106 | 见报告 004、005 |
| 2026-11-07 | 联网方式 | **eth0 用网线直连 Windows 电脑，由电脑共享网络（ICS）上网**；eth1 留给 EtherCAT | 见任务 008 |
| 2026-11-07 | 参考资料 | 芯来官方 Linux SDK：https://github.com/Nuclei-Software/nuclei-linux-sdk | 本板的 Buildroot、OpenSBI、U-Boot 都基于它，遇到问题先查它的 README 和 FAQ |

## 由此带来的待办（尚未安排成任务）

- 设备树（`kernel.dtb`）里 `cpu@2`–`cpu@7` 的 `status` 都是 `okay`，OpenSBI 也报告 `Platform HART Count: 8`。内核每等一个不存在的核就要超时约 1 秒，启动因此多花约 6 秒。冷启动时 OpenSBI 报的 `hart is in invalid state`，也**可能**和它按 8 核配置有关，目前只是推测，未验证。
- 修复办法：维护者在固件（OpenSBI）和设备树源文件里改成 2 核；或者由我们在卡上的 `kernel.dtb` 里把 `cpu@2`–`cpu@7` 改成 `disabled`，作为临时验证（可回退，不碰闪存固件）。是否这样做，等维护者决定。
