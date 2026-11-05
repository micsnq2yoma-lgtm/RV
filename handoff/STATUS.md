# 任务状态

| 编号 | 任务 | 对应阶段 | 状态 | 任务单 | 报告 | PR |
|---|---|---|---|---|---|---|
| 001 | 插卡上电：启动、登录、摸清板子 | 第 0 阶段 | blocked | [tasks/001-tf-card-boot-bringup.md](tasks/001-tf-card-boot-bringup.md) | [reports/001-tf-card-boot-bringup.md](reports/001-tf-card-boot-bringup.md) | [草稿 #1](https://github.com/micsnq2yoma-lgtm/RV/pull/1) |
| 002 | 换新版启动文件、完整抓取上电过程 | 第 0 阶段收尾 / 第 2 阶段 | blocked | [任务](tasks/002-new-image-full-boot.md)、[补充 1](tasks/002-addendum-1-card-in-reader.md) | [报告](reports/002-new-image-full-boot.md) | [草稿 #2](https://github.com/micsnq2yoma-lgtm/RV/pull/2) |

001 当前阻塞：串口和只读板级采集已完成，但卡根目录实际为 rpmsg 文件副本，不符合目标新版前置条件；U-Boot 全程与网络验证尚未完成。未写卡或推进任务 002。

002 当前阻塞：第 0 步完成；人已确认约 32 GB 的 GPT SDHC 卡是准备使用的新卡，按补充 C 分支等待另行制卡任务，未写卡或格式化。用户提供的 Dropbox Workspace/RV/boot 四个新版源文件大小及 content_hash 已全部通过校验，卡上文件尚未写入或验证。
