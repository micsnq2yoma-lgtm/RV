# 任务状态

| 编号 | 任务 | 对应阶段 | 状态 | 任务单 | 报告 | PR |
|---|---|---|---|---|---|---|
| 001 | 插卡上电：启动、登录、摸清板子 | 第 0 阶段 | blocked | [tasks/001-tf-card-boot-bringup.md](tasks/001-tf-card-boot-bringup.md) | [reports/001-tf-card-boot-bringup.md](reports/001-tf-card-boot-bringup.md) | [草稿 #1](https://github.com/micsnq2yoma-lgtm/RV/pull/1) |
| 002 | 换新版启动文件、完整抓取上电过程 | 第 0 阶段收尾 / 第 2 阶段 | done | [任务](tasks/002-new-image-full-boot.md)、[补充 1](tasks/002-addendum-1-card-in-reader.md) | [报告](reports/002-new-image-full-boot.md) | [草稿 #2](https://github.com/micsnq2yoma-lgtm/RV/pull/2) |
| 003 | 新卡制卡并恢复任务 002 上板验证 | 第 1 / 2 阶段 | done | [任务](tasks/003-make-new-boot-card.md)、[补充 1](tasks/003-addendum-1-convert-mbr.md) | [报告](reports/003-make-new-boot-card.md) | [沿用草稿 #2](https://github.com/micsnq2yoma-lgtm/RV/pull/2) |
| 004 | 启动卡更新为 boot_1106 | 第 2 阶段 | done（冷启动故障与镜像无关，见 005） | [任务](tasks/004-update-to-boot-1106.md) | [报告](reports/004-update-to-boot-1106.md) | [草稿 #3](https://github.com/micsnq2yoma-lgtm/RV/pull/3) |
| 005 | 重上 boot_1106 并统计冷启动 | 第 2 阶段收尾 | done | [任务](tasks/005-reapply-boot-1106-coldboot-stats.md) | [报告](reports/005-reapply-boot-1106-coldboot-stats.md) | [沿用草稿 #3](https://github.com/micsnq2yoma-lgtm/RV/pull/3) |
| 007 | 检查 eMMC Ubuntu 并进入 chroot | 使用 eMMC 系统 | done | [任务](tasks/007-emmc-ubuntu-check.md) | [报告](reports/007-emmc-ubuntu-check.md) | [PR #4](https://github.com/micsnq2yoma-lgtm/RV/pull/4) |
| 008 | eth0 经 Windows ICS 上网与 SSH/SCP | 第 1 阶段 | blocked | [任务](tasks/008-eth0-internet-via-pc.md) | [报告](reports/008-eth0-internet-via-pc.md) | 待创建草稿 PR |

001 当前阻塞：串口和只读板级采集已完成，但卡根目录实际为 rpmsg 文件副本，不符合目标新版前置条件；U-Boot 全程与网络验证尚未完成。未写卡或推进任务 002。

002 已完成新版冷启动采集、U-Boot 检查与板上四文件 SHA-256 回读。CPU2–7 上线失败仍可复现。用户选择跳过 D 节可选网络验证。

003 已完成制卡。补充 1 经第二次确认后使用 Set-Disk 转为 MBR，单个 FAT32 卷 RVBOOT。回读校验通过后已安全弹出。

004 的原始失败与回退记录保留。依据任务 005 的维护者判断，状态改为 done。当前卡已重新换上 boot_1106，详情见 005。

005 已完成重上卡、5 轮冷启动和 2 轮 RESET 对照及板上复核。五轮冷启动均 120 秒零字节，未捕获 invalid state，逐轮追加 RESET 均恢复到登录。两次持续供电 RESET 对照也成功。当前保留 boot_1106，冷启动已知问题和临时方法见 BOARD 与报告。

007 已确认 eMMC 单个 ext4 分区内为 Ubuntu 24.04.3 LTS。维护者 start 可进入 chroot，Python 3.12.3、GCC 13.3.0 已确认，PATH 可找到 make、apt，git 未找到，/lib/modules 缺失。正常 exit、stop 后已确认全部卸载，详见 EMMC.md 与报告。

008 已确认 J1=eth0，ICS 自动分配 192.168.137.178，板子 ping 8.8.8.8 为 3/3。共享期间主机 HTTPS 同步失败，独立守护已关闭本轮共享、恢复原下游配置；主机联网恢复。板子已用 PC UTC 校时，eMMC 全部未挂载。SSH/SCP 实机检查和 Ubuntu apt 尚未完成，详见 NETWORK.md 与报告。
