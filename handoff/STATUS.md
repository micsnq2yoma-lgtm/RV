# 任务状态

| 编号 | 任务 | 对应阶段 | 状态 | 任务单 | 报告 | PR |
|---|---|---|---|---|---|---|
| 001 | 插卡上电：启动、登录、摸清板子 | 第 0 阶段 | blocked | [tasks/001-tf-card-boot-bringup.md](tasks/001-tf-card-boot-bringup.md) | [reports/001-tf-card-boot-bringup.md](reports/001-tf-card-boot-bringup.md) | [草稿 #1](https://github.com/micsnq2yoma-lgtm/RV/pull/1) |
| 002 | 换新版启动文件、完整抓取上电过程 | 第 0 阶段收尾 / 第 2 阶段 | blocked | [任务](tasks/002-new-image-full-boot.md)、[补充 1](tasks/002-addendum-1-card-in-reader.md) | [报告](reports/002-new-image-full-boot.md) | [草稿 #2](https://github.com/micsnq2yoma-lgtm/RV/pull/2) |
| 003 | 新卡制卡并恢复任务 002 上板验证 | 第 1 / 2 阶段 | failed | [任务](tasks/003-make-new-boot-card.md) | [报告](reports/003-make-new-boot-card.md) | [沿用草稿 #2](https://github.com/micsnq2yoma-lgtm/RV/pull/2) |

001 当前阻塞：串口和只读板级采集已完成，但卡根目录实际为 rpmsg 文件副本，不符合目标新版前置条件；U-Boot 全程与网络验证尚未完成。未写卡或推进任务 002。

002 当前阻塞：四个新版源文件已通过大小与 content_hash 校验，但任务 003 制卡失败，尚未复制或回读卡上文件，B–E 未执行。

003 失败：当场获准操作磁盘 2 并由人批准 UAC。Clear-Disk 后两分区已消失，但 Initialize-Disk -PartitionStyle MBR 返回 “The disk has already been initialized.”。复核为 GPT、无分区；按任务失败规则停止，未创建 FAT32 卷、复制文件或上板，原约 7.5 GB 卡未操作。
