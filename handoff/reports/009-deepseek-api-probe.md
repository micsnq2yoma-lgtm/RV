# 报告 009：探测工具完成，待 Key 和板上环境

- **执行者**：Codex
- **日期**：2026-11-07（America/Los_Angeles；任务日志名使用 20261108）
- **结果**：blocked
- **分支 / PR**：`task-009-deepseek-probe` / [草稿 PR #7](https://github.com/micsnq2yoma-lgtm/RV/pull/7)

## 一句话结论

已实现安全、有限请求的 DeepSeek 探测器并通过四项离线测试；未收到 Key 存放状态及本轮开发板现场确认，实际 API 请求数为 0，不能声称模型能力已验证。

## 逐步执行记录

| 步骤 | 结果 | 证据 |
|---|---|---|
| 前置 | 完成 | 基于 task-008-eth0-network 创建指定分支，合并上游 bea7027；已读 DECISIONS 与 SIM_AGENT_DESIGN |
| 1 | 等人 | 已询问指定 key 文件是否就绪，未索取聊天明文 Key；提供人工交互 store_key.py，隐藏输入、文件600、父目录700、拒绝覆盖，不经电脑临时文件 |
| 2 | 尚未执行 | 等待本轮现场确认；未登录、挂载、安装板上包或启动隧道，不沿用历史接线确认 |
| 3 | 实现并离线测试 | [probe README](../../sim_agent/probe/README.md)；标准库+httpx，PNG用标准库生成；十请求常规流程、硬上限20、无自动重试 |
| 4 | 尚未执行 | 板子未探测，不存在代理失败证据，未擅自做付费PC对照 |
| 5 | 记录当前状态 | [日志](../../logs/20261108-009-deepseek-probe.log)仅记录未运行与MockTransport测试，不含模拟API输出或真实Key |
| 6 | 草稿交付 | 报告与STATUS明确blocked，待补真实输出再更新同一PR |

## 需要回答的问题

1. **模型 ID 与 /models 列表？** 未确认；尚未调用 API。请求模型名为任务指定的 `DeepSeek-V4.1-Flash-1017`。脚本会先输出真实列表，若找不到完全一致的 ID 即停止，交给人决定，不自动替换。
2. **工具调用、JSON、图片支持？** 均未确认。脚本实现普通对话、pick/place工具、JSON对象与64×64红色PNG测试；工具调用只检查返回参数，不执行动作。图片单次答红色仅是有限样本，不代表完整视觉能力。
3. **板上工具调用均值和p95？** 未测。实现连续5次成功且参数正确的工具调用统计，用nearest-rank计算p95；同时记录有效样本数，不能将失败样本混成成功延迟。
4. **每次工具调用 token？** 未确认。实际调用时逐项记录usage，当前没有真实token消费数据。

## 和任务单不一致的地方

未执行依赖人工前置的步骤，先完成无凭据实现和测试。提供板上手动隐藏输入工具，不需从聊天传Key，也不产生电脑临时Key文件；这属于任务允许的SSH手动输入方式。未修改Clash、防火墙、板上系统或源。

## 发现的问题和风险

离线测试只验证十请求预算、401立即停止与Key脱敏、模型缺失不替换、错误工具参数拒绝。不能从MockTransport或API文档推断指定模型实际可用。脚本默认不跟随重定向，不输出请求头，不自动重试。Key只允许指定Ubuntu文件或PC对照的临时进程环境；仓库没有认证信息。

官方接口参考：[models](https://api-docs.deepseek.com/api/list-models/)、[chat completions](https://api-docs.deepseek.com/api/create-chat-completion/)。具体模型能力以待执行的实测为准。

## 需要人做的事

回复 Key 是否已在 `/root/.config/rv-agent/deepseek.key`（600），或选择需要安全输入方式；不要把值发到聊天。确认本轮开发板主电、USB、J1就绪，伺服动力电断开或电机未连接，以及是否重启。之后准备网络/chroot，安装任务要求的python3-httpx、python3-pil，执行真实探测并安全退出、卸载和关闭隧道。
