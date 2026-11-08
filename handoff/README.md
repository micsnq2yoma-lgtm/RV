# Claude ↔ Codex 交互协议

这个目录是 Claude（出计划、审结果）和 Codex（在开发板上执行）之间唯一的沟通渠道。双方不直接对话，都通过这个仓库里的文件交接，由人在两边之间传话和把关。

## 角色

| 角色 | 职责 |
|---|---|
| **Claude** | 写任务单 `tasks/NNN-*.md`；审阅 Codex 的报告；决定下一步；维护 `docs/PLAN.md` |
| **Codex** | 按任务单在主机和开发板上执行；保存原始日志；写报告 `reports/NNN-*.md`；发 PR |
| **人** | 接线、上电、插拔卡、守急停；回答双方的问题；批准电机使能；合并 PR；在两边之间传话 |

## 一轮交互的流程

1. **Claude** 写任务单 `handoff/tasks/NNN-简述.md`，在 `STATUS.md` 里登记为 `ready`，推送到 `main`。
2. **人**告诉 Codex：“执行 `handoff/tasks/NNN-简述.md`”。
3. **Codex** 新建分支 `task-NNN-简述`，把 `STATUS.md` 里的状态改成 `in-progress`，然后按任务单执行：
   - 遇到任务单里标了 **[需人工]** 的步骤，或者遇到 `AGENTS.md` 安全规则要求停下的情况，就停下来问人，等人回答后再继续。
   - 原始输出存到 `logs/`，结论写进任务单要求的 `docs/` 文件。
4. **Codex** 按 `templates/report.md` 写报告 `handoff/reports/NNN-简述.md`，把状态改成 `done`、`blocked` 或 `failed`，然后发 PR。
5. **人**告诉 Claude：“看一下任务 NNN 的报告”（附上 PR 链接）。
6. **Claude** 读报告、日志和 PR 改动，在 PR 下评审或回复。之后有两种走向：需要返工就写 `NNN-简述-r2.md`；可以推进就写下一个任务单。
7. **人**合并 PR，回到第 1 步。

## 文件约定

- **编号**：三位数字，按顺序递增，例如 `001`、`002`。返工版本加后缀 `-r2`、`-r3`。
- **任务单**：一旦发布就不改。执行中遇到需要调整的情况，Claude 写补充文件 `NNN-addendum-K-简述.md`，Codex 执行时把原任务单和所有补充一起读；需要整体重做时写新版本 `-r2`。
- **报告**：必须逐条回答任务单里的“需要回答的问题”。不知道的写“未确认”并说明原因，**不要猜**。
- **日志**：`logs/YYYYMMDD-NNN-主题.log`，保存原始输出，不要编辑。太大（超过 5 MB）的话，只提交关键片段，并在报告里说明删减了什么。
- **状态**：`STATUS.md` 是总览表，可选状态有 `ready`、`in-progress`、`blocked`（等人或等信息）、`done`、`failed`。

## 人在中间传话的模板

**给 Codex：**
> 读 `AGENTS.md`、`handoff/README.md` 和 `handoff/DECISIONS.md`，然后执行 `handoff/tasks/NNN-xxx.md`。

**给 Claude：**
> Codex 完成了任务 NNN，报告在 `handoff/reports/NNN-xxx.md`，PR：<链接>。请审阅并给出下一个任务。

## 目录

```
handoff/
├── README.md        本协议
├── STATUS.md        任务状态总览
├── DECISIONS.md     维护者确认的事实与决定（每次执行前必读）
├── CLAUDE_ONBOARDING.md  新 Claude 会话的交接说明
├── templates/       任务单和报告的模板
├── tasks/           Claude 写的任务单
└── reports/         Codex 写的报告
```
