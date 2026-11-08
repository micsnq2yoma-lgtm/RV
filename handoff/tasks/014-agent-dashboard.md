# 任务 014：DeepSeek 智能体闭环 + 多视角监控面板 + 板子资源监控（S4 + S5）

- **对应阶段**：`docs/SIM_AGENT_DESIGN.md` 的 S4、S5
- **作者**：Claude
- **日期**：2026-11-08
- **电机是否可能动作**：**否**（只有仿真）
- **前置条件**：分支 `task-014-agent-dashboard`，基于 `task-012-hang-isolation`（包含 011 的全部代码），再合并上游 `handoff-protocol`。**任务 013 取消**，它的 IK 提速部分并入本任务的 A 节。
- **必须先读**：`handoff/DECISIONS.md`（尤其是“失联问题暂缓”“演示要求”两条）、`docs/SIM_AGENT_DESIGN.md`（3.3–3.5 节、第 4 节）。

## 目标

人在电脑浏览器里打开 RV 板子提供的网页面板，输入一句中文任务，例如“把蓝色方块叠到绿色方块上”。之后：

- 板子上的智能体负责感知、调用 DeepSeek 规划，并驱动仿真里的 Panda 完成任务；
- 面板上同时显示**四个视角**的实时画面（俯视、正面、侧面、腕部），以及智能体每一步的思考、工具调用和结果；
- 面板和板子的终端里**持续打印板子的资源使用情况**。

## 关于失联（人的决定）

偶发的整板失联**暂时不查**。如果遇到：记录时间和当时在做的事，请人按 RESET，然后接着做。这次试验按失败计入，并在报告里单独列出，但**不做任何排查**。运行时的日志和图片仍然写到 `/tmp`，并实时取回电脑。

## 不要做的事

- 不改 Windows 防火墙和 Clash，不碰 eth1，不碰真实电机。
- DeepSeek Key 只从 `/root/.config/rv-agent/deepseek.key` 读取，不进仓库，也不进日志或面板。
- 面板不提供任何执行 shell 命令的入口，只监听 `192.168.50.2`。

## 步骤

### A. IK 提速（S4 的前置条件）

1. 用 `cProfile` 分析 `kin.py` 的 `ik()`，报告最耗时的前 10 个函数。
2. 依次尝试：热启动（用当前 q 作为初值）→ FK 和雅可比一次算完 → 小矩阵改用纯 Python 或 numpy 向量运算 → 调整阻尼和迭代参数 → 还不够就改用 C 实现，编译成 `.so` 用 `ctypes` 调用。精度要求不变：位置 < 1 mm，姿态 < 1°。
3. 验收：30 个目标点全部收敛，板子上**平均耗时 ≤ 50 ms**，同时报告最大耗时。

### B. 仿真端：多视角渲染（协议 v1.2）

4. 场景新增 `front`、`side` 两个固定相机，四个视角都要能看清机械臂、三个方块和两个托盘。
5. 实现 `render_multi`，并把 `render` 的分辨率放宽到 320×240 和 640×480（v1.2 第 2、3 条）。渲染在渲染进程里完成。测一下面板刷新时（四个视角，320×240，每秒 4 次）物理步进是否还能满足 3.4 节的标准。

### C. 板子端：感知（L3）

6. 新建 `sim_agent/board/agent/perception.py`：
   - 请求一张 640×480 的 `top` 图像，在 HSV 空间按颜色阈值分割出红、绿、蓝三个方块和两个托盘，取连通域质心；
   - 用应答里的相机参数（`fovy`、`cam_pos`、`cam_xmat`）把像素反投影成射线，再和桌面（以及方块顶面）求交，得到世界坐标。叠在其他方块上的方块用颜色区分，高度用方块顶面平面估计。被机械臂挡住的物体标为 `occluded`，沿用上一次的位置；
   - 输出场景 JSON：`{"objects":[{"name":"red_cube","xy":[..],"z_est":..,"in":"left_tray|right_tray|table|on:green_cube"}],"gripper":"empty|holding:<名字>"}`。
7. 验收：随机做 20 次 `reset`，和 `objects` 真值比较，xy 误差平均 < 1 cm，最大 < 2 cm。机械臂回到 home 时不能有物体被挡住。

### D. 板子端：智能体（L4）

8. 新建 `sim_agent/board/agent/agent.py`：
   - 模型 `deepseek-flash`，`base_url=https://api.deepseek.com`，走代理 `http://127.0.0.1:7897`（打开 SSH 反向隧道，参照任务 008）；
   - 工具（function calling），参数都用物体名称，**不让模型给坐标**：`pick(object)`、`place_in(tray)`、`stack_on(object)`、`home()`、`finish(success, summary)`。坐标由感知层给出，再由技能层执行；
   - 每一轮：感知 → 把场景 JSON 和上一步的执行结果发给模型 → 模型调用**一个**工具 → 执行 → 下一轮。最多 12 轮。模型调用 `finish`，或者达到上限时结束；
   - 系统提示词：说明桌面布局、工具的含义、每次只调用一个工具、手里拿着东西时不能再 `pick`，以及要根据新的场景确认上一步是否成功。提示词放在 `sim_agent/board/agent/prompts/` 下的文本文件里；
   - 每一步都记录：发给模型的内容（Key 打码）、模型返回的文字和工具调用、执行结果、耗时、token 用量、当时的四张图。记录写到 `/tmp/runs/<时间>/steps.jsonl`，并实时取回电脑。
9. 错误处理：
   - 工具执行失败（IK 不收敛、没抓住）时，把失败原因告诉模型，由模型决定是重试还是换个办法；
   - API 超时或出错时，重试 2 次，仍然失败就结束本次任务，标记为 `api_error`。

### E. 板子端：资源监控

10. 新建 `sim_agent/board/agent/sysmon.py`，每秒采样一次：
    - 每个 CPU 核的占用率（从 `/proc/stat` 计算，分出 user、system、irq、softirq、idle）；
    - 内存：总量、可用、`/tmp` 用了多少；
    - `loadavg`；
    - `/proc/interrupts` 中 eth0、eMMC、TF 卡、串口这几个中断每秒的次数；
    - eth0 的收发速率（来自 `/proc/net/dev`）；
    - 进程级的 CPU 占用：`rt_ctl`、agent、面板服务各自占多少（来自 `/proc/<pid>/stat`），以及它们的调度策略和所在的 CPU；
    - `rt_ctl` 的实时指标：处理时间的平均值和最大值、到达间隔的最大值、丢包。`rt_ctl` 每秒输出的 JSON 可以写到 `/tmp/rt_ctl.stats`，由 sysmon 读取；
    - 温度，如果能读到 `/sys/class/thermal` 的话。
11. 终端里每秒打印**一行**摘要，例如：
    `CPU0 63% CPU1 18% | mem 612/1999M | rt proc 0.18/0.52ms gap 4.1/9.8ms loss 0 | eth0 rx 410k tx 95k | irq eth0 260/s mmc 0/s | agent: step 3 stack_on(green_cube)`
    完整数据同时写一份 CSV 到 `/tmp/runs/<时间>/sysmon.csv`。

### F. 板子端：网页面板（L5）

12. 新建 `sim_agent/board/agent/dashboard.py`（FastAPI + uvicorn，在 Ubuntu 里通过代理装 `python3-fastapi`、`python3-uvicorn`），监听 `192.168.50.2:8080`。只用一个 HTML 页面加原生 JS，不引入前端构建工具。页面分区：
    - **任务区**：输入框加“开始”“停止”按钮。停止会让智能体在当前技能结束后停下，并让机械臂回到 home；
    - **四宫格视频**：top、front、side、wrist，320×240，每秒约 4 帧。板子用 `render_multi` 取图，通过 MJPEG 流或 WebSocket 推给浏览器；
    - **智能体时间线**：每一步的场景摘要、模型的文字、工具调用、执行结果、耗时、token；
    - **资源面板**：E 节的数据，每秒刷新。包括两个 CPU 核占用率的折线（最近 60 秒）、内存、`rt_ctl` 指标、中断和网络；
    - **回放**：可以选择 `/tmp/runs` 里已经完成的任务，逐步查看当时的四张图和决策。
13. 进程和 CPU 分配：`rt_ctl` 固定在 CPU1，FIFO80；agent、dashboard、sysmon 都是普通优先级，绑定 CPU0。如果面板刷新让 CPU0 长时间满负载，就降低帧率或分辨率，并在报告里给出数据。

### G. 验收

14. 在浏览器里，用三条中文任务各跑 5 次，每次开始前用不同的 seed 做 `reset`：
    - T1：“把红色方块放进左边的托盘”；
    - T2：“把蓝色方块叠到绿色方块上面”；
    - T3：“把三个方块都放进右边的托盘”。

    成功与否用 `objects` 真值判定，不能只看模型自己报告的结果。记录每次的成功与否、轮数、总耗时、token 总数、失败原因，以及运行期间两个 CPU 核的平均占用和峰值。
15. 录一段**完整的屏幕视频**：浏览器面板加上 MuJoCo 窗口，内容是 T3 的一次成功运行。另外截几张面板的图，提交到 `sim_agent/docs/img/`。视频太大的话不要提交，在报告里写明文件放在电脑上的什么位置。
16. 新建 `sim_agent/board/agent/README.md`，写清楚一键启动的步骤：bootstrap → 隧道 → 挂载 Ubuntu → 启动 `rt_ctl` → 启动 dashboard（dashboard 负责启动 agent 和 sysmon）→ 电脑上启动 `sim_server.py` → 浏览器打开 `http://192.168.50.2:8080`。最好提供一个 `run_demo.sh`。
17. 写报告 `handoff/reports/014-agent-dashboard.md`，更新 `STATUS.md`，发 PR。

## 验收标准

- IK 平均耗时 ≤ 50 ms。
- 感知 xy 误差：平均 < 1 cm，最大 < 2 cm。
- T1 ≥ 4/5，T2 ≥ 4/5，T3 ≥ 3/5（失联导致的失败单独列出）。
- 面板能同时显示四个视角、智能体时间线和资源数据；运行期间 `rt_ctl` 每包处理时间最大值 < 1 ms。

## 需要回答的问题

1. IK 用的是哪种优化方法？优化前后的平均耗时和最大耗时各是多少？
2. 感知的误差统计，以及遮挡怎么处理。
3. 三条任务各自的成功率、平均轮数、平均耗时、平均 token，以及失败原因。
4. 运行期间两个 CPU 核的占用情况（平均值和峰值）、内存、`rt_ctl` 指标；面板刷新给 CPU0 增加了多少负载。
5. 有没有遇到失联？如果有，发生在什么时间、当时在做什么。
6. 面板截图和视频放在哪里。
