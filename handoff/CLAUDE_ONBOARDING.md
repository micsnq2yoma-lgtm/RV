# 给新 Claude 会话的交接说明

你接手的角色是**规划者和审阅者**：写任务单、审阅 Codex 的 PR、维护设计文档。Codex 负责在维护者的 Windows 电脑和 RV 开发板上执行。维护者（人）在你们之间传话、操作硬件、做决定。

## 必读（按顺序）

1. `handoff/README.md`：交互协议（任务单 → Codex 执行 → 报告 + PR → Claude 审阅）
2. `handoff/DECISIONS.md`：维护者已经确认的事实和决定，**优先级最高**
3. `handoff/STATUS.md`：任务状态（可能落后，以 PR 为准）
4. `AGENTS.md`：Codex 的规则，包括电机安全规则
5. `docs/SIM_AGENT_DESIGN.md`：仿真智能体的设计和通信协议（v1 → v1.3）
6. `docs/WORKBENCH_DESIGN.md` 和 `sim_agent/design/workbench_mockup.html`：工作台 v2 的设计规范和样稿
7. `docs/architecture.html`：软硬件架构图
8. 最新的几份报告：`handoff/reports/`（在 Codex 的 PR 分支上）

## 仓库和分支

- 上游仓库：`micsnq2yoma-lgtm/RV`（公开仓库：**不要提交密码、Key、MAC 地址、原理图 PDF**）
- Claude 的工作分支：**`handoff-protocol`**。任务单、设计文档、DECISIONS 都推到这个分支。不要直接改 `main`。
- Codex 从自己的 fork（`yizhidianlu/RV`）向 `handoff-protocol` 发 PR，每个任务一个分支 `task-NNN-*`，后一个任务的分支基于前一个。
- PR #1–#10 都已经审阅过，**还没合并**。合并由维护者决定。
- 克隆后执行 `git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'`，然后 `git fetch origin '+refs/pull/N/head:refs/remotes/origin/pr-N'` 读取 PR 的内容。

## 工作习惯

- 任务单、报告、评审都用中文，按 `handoff/templates/` 的格式写。任务单里需要人动手的步骤标 **[需人工]**；每个任务单都要写“不要做的事”“失败时怎么办”“需要回答的问题”。
- 审阅 PR 时，先读报告和关键日志，再用 `gh api repos/micsnq2yoma-lgtm/RV/issues/<PR号>/comments -F body=@文件` 发评审意见。评审里要给出结论、指出问题，并附上下一个任务单的链接。
- 任务单发布后不再修改：要补充就写 `NNN-addendum-K-*.md`，要整体返工就写 `NNN-*-r2.md`。
- 维护者新的决定，记进 `DECISIONS.md`。
- 给维护者的回复里，最后附上可以直接转发给 Codex 的一段话。

## 当前状态（2026-11-08）

- **硬件**：芯来 UX900，2 核（维护者确认），2 GB，DC 供电。从 TF 卡启动 boot_1106（Linux 6.6.90-rt54）。冷启动后要按一次 RESET。eMMC 上装有 Ubuntu 24.04，用 `/mount_emmc.sh` 进入 chroot。
- **网络**：电脑 `192.168.50.1` 和板子 `192.168.50.2` 用网线直连（J1/eth0）。板子通过 SSH 反向隧道使用电脑上 Clash 的代理（`127.0.0.1:7897`）。**不要用 ICS，不要改电脑的防火墙和 Clash**。
- **整板偶发失联**：根因不明，怀疑和 eMMC 读取有关；内核没有 SysRq，查不到原因。维护者决定**暂缓排查**，遇到时记录下来、按 RESET、继续。需要的话，可以请维护者提供调试版内核。
- **仿真智能体**：电脑跑 MuJoCo Panda；板子负责感知、DeepSeek 规划（模型 `deepseek-flash`，**看图不可靠，看图由板子做**）、IK（C 实现，约 18 ms）和 `rt_ctl`（FIFO80，CPU1）。任务 014 中：T1 5/5，T2 4/5，T3 没做完；运行时 CPU0 满载。
- **进行中**：**任务 015**（工作台 v2 + 按图叠放 G1–G4 + 基线对比 + 补完 014 剩下的验收）已经发给 Codex，等它的 PR。
- **暂停**：任务 006（真实 EtherCAT 扫描，要等维护者接好驱动器），以及任务 013 的复现实验部分（已取消）。

## 环境

- 这个会话需要挂载仓库 `micsnq2yoma-lgtm/RV`，有推送权限。
- 云端环境“RV board”额外放行了 `robot-agent-exploration.com`（工作台设计的参考站点）。
- Dropbox 连接器可以读维护者的 `/Workspace/RV`（镜像文件），但这个环境下载不了 Dropbox 的文件（`*.dl.dropboxusercontent.com` 被网络策略拦截）。
