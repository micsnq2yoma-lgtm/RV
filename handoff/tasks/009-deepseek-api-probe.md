# 任务 009：DeepSeek API 摸底（S0）

- **对应阶段**：`docs/SIM_AGENT_DESIGN.md` 的 S0
- **作者**：Claude
- **日期**：2026-11-08
- **电机是否可能动作**：**否**
- **前置条件**：任务 008 完成：固定 IP、`board_bootstrap.ps1`、`board_proxy_tunnel.ps1` 都可用。分支 `task-009-deepseek-probe`，基于 `task-008-eth0-network`，再合并上游 `handoff-protocol`。

## 目标

确认 RV 板子能通过代理调用 **DeepSeek-V4.1-Flash-1017**，并弄清楚它支持哪些能力。后面的 Agent 设计要依据这些结果来定。

## 不要做的事

- **API Key 不进仓库、不进日志、不写进脚本**。日志里所有请求头都要打码。
- 每次运行最多发 20 个请求，避免浪费额度。
- 不改 Clash 和防火墙。

## 步骤

1. **[需人工]** 请人提供 DeepSeek API Key。存放方式：电脑上作为环境变量临时使用；板子上存到 eMMC Ubuntu 里的 `/root/.config/rv-agent/deepseek.key`，`chmod 600`，通过 `scp` 传上去，或者由人在 SSH 里手动粘贴。传完立刻删除电脑上的临时文件。
2. 准备环境：开机后执行 `board_bootstrap.ps1`，打开代理隧道，进入 Ubuntu。用代理参数安装：`apt-get install -y python3-httpx python3-pil`。
3. 在仓库里新建 `sim_agent/probe/deepseek_probe.py`：只用标准库加 httpx；从上面的文件读取 Key；代理从环境变量 `HTTPS_PROXY` 读取。逐项测试下面几点，每项记录：HTTP 状态码、耗时、返回的 `usage`、结论：
   - a. `GET https://api.deepseek.com/models`：列出可用模型，确认 `DeepSeek-V4.1-Flash-1017` 是否在里面，以及模型 ID 的准确写法。
   - b. 普通对话：`POST /chat/completions`，问一句简单的话。
   - c. **工具调用**：定义 `pick(color)` 和 `place(target)` 两个工具，给出一句场景描述，要求“把红色方块放进左边托盘”。检查返回里有没有 `tool_calls`，参数是否正确。
   - d. **JSON 输出**：使用 `response_format={"type":"json_object"}`，检查是否支持。
   - e. **图片输入**：用 OpenAI 格式的 `image_url`（base64 data URL）发一张 64×64 的纯红色 PNG，问“这张图是什么颜色”。记录返回的是正确答案、报错，还是忽略了图片。
   - f. 连续 5 次测试 c，统计平均延迟和 p95 延迟。
4. 在板子上（`HTTPS_PROXY=http://127.0.0.1:7897`）运行 `deepseek_probe.py`。如果代理行不通，再在电脑上直接运行一遍作为对照，在报告里注明在哪里跑的。
5. 输出写到 `logs/20261108-009-deepseek-probe.log`（Key 打码）。
6. 写报告 `handoff/reports/009-deepseek-api-probe.md`，更新 `STATUS.md`，发 PR。

## 失败时怎么办

| 现象 | 处理 |
|---|---|
| 401 或 403 | Key 有问题，请人检查。不要重试超过 2 次 |
| 模型 ID 不存在 | 把 `/models` 的列表贴进报告，问人用哪个 |
| 板子通过代理连不上 | 先在板子上 `wget` 一个 HTTP 地址测代理本身。在电脑上跑一遍作为对照，然后汇报 |

## 需要回答的问题

1. 模型 ID 的准确写法是什么？`/models` 返回了哪些模型？
2. 支持工具调用吗？支持 JSON 输出吗？支持图片输入吗？
3. 从板子发请求，工具调用的平均延迟和 p95 延迟各是多少？
4. 每次工具调用大约用多少 token？
