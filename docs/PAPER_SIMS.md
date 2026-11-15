# 论文仿真环境的复现与上板：AGP 与 RAX

- **作者**：Claude（维护者要求：读两篇论文和开源代码，找出能在本地和 RV 板上复现的仿真环境，先本地测试再上板）
- **日期**：2026-11-15
- **论文**：
  - *Agent as Policy for Robotic Manipulation*（AGP，arXiv 2609.12541），代码：github.com/agent-as-policy-2026/agent-as-policy
  - *Scaling Online Exploration for Robot Agents*（RAX，arXiv 2610.22496），代码：github.com/robot-agent-exploration/rax（代码按分支组织）

两篇论文都让一个通用 agent 通过 API 直接驱动机器人：AGP 用 Codex 或 Claude Code，配一个“观察 / 动作”命令行接口；RAX 用 Codex、Claude Code、DeepSeek Harness 或 Kimi Code，配 MCP 工具。

## 1. 仿真环境调研结论

本机：Windows 11、RTX 3060 Laptop（6 GB 显存）、16 GB 内存。

| 环境 | 来源 | 内容 | 后端 | 本机结果 | 上 RV 板 |
|---|---|---|---|---|---|
| **LIBERO / LIBERO-PRO** | RAX `libero-pro/*` | Franka Panda；厨房、客厅等带纹理的真实感场景，共 4 套 130 个任务 | robosuite 1.4 + MuJoCo 3.2.3 | **能跑**：Windows 原生，带两路相机时每秒 32–35 步（任务按 20 Hz 控制） | **已完成**（见第 3 节） |
| **DexJoCo** | RAX `dexjoco/*` | Franka 加 Allegro 灵巧手；11 个任务（浇花、点鼠标、敲钉子、双臂汉诺塔等） | MuJoCo 3.4.0 | **能跑**：Windows 原生，30 Hz 实时，最多 4 个 640×640 相机 | 能接；灵巧手要先设计好抓握动作，下一步再做 |
| RoboDojo | AGP `robodojo/`、RAX | ARX X5 双臂 | 要求 Ubuntu 22.04、Vulkan、带 RT 核心的 GPU、16 GB 内存 | 没装 | 本机条件不够 |
| BEHAVIOR-1K、HumanoidArena | RAX | 家庭大场景；Unitree G1 | Isaac Sim 5.1 / 6.1 | 不可行：6 GB 显存不够 | 不可行 |

RAX 的官方 harness 要求 Linux、bubblewrap 沙箱和 Node.js 24 的 coding-agent CLI，搬不到 riscv64 的板子上。所以我们只借用它的**仿真环境和任务定义**，工具接口也参照它的设计（观察、7 维末端增量动作、像素到三维坐标）；agent 用我们自己的轻量 Python 循环，和 Panda、导航两个 demo 一样跑在板子上。

### 在 Windows 上原生运行 LIBERO 要做的修改（只改本机的 conda 环境）

- conda 环境 Python 3.8.13；`mujoco==3.2.3`（≥ 3.4 会破坏 LIBERO 的初始状态）、`robosuite==1.4.0`、`bddl==1.0.1`，以及 CPU 版的 `torch==1.11.0`（读取初始状态要用）；
- 用 `conda run` 激活环境再执行 pip（否则 SSL 依赖的 DLL 找不到），并使用官方 PyPI；
- 把 mujoco 包里的 `mujoco.dll` 复制到 `robosuite/utils/`；
- 把 `robosuite/macros.py` 里的 `MUJOCO_GPU_RENDERING` 改为 False（Windows 没有 EGL，改走 GLFW / WGL 渲染）；
- 新建 `C:\tmp`（robosuite 的日志路径写死为 `/tmp`）；预先写好 `~/.libero/config.yaml`，避免首次导入时交互式询问数据路径。

DexJoCo：conda 环境 Python 3.11，`mujoco==3.4.0`、`gymnasium==1.0.0`，然后 `pip install -e dexjoco/dexjoco`。注意脚本不要放在含有 `dexjoco` 同名目录的地方运行，否则会被当成同名包挡住真正的安装。

## 2. LIBERO demo 的结构

```
电脑（LIBERO conda 环境）                            RV 板（Ubuntu chroot）
sim_agent/pc/libero_server.py  ──TCP 15004，电脑主动连板子──▶  sim_agent/board/libero/
  官方 BDDL 任务和初始状态                                    libero_perception：深度图加实例分割 → 物体中心、顶面高度、尺寸
  observe：RGB / 深度 / 实例分割 / 相机内外参 / 本体状态       libero_skills：闭环末端控制（pick / place_on / place_in）
  step：官方 7 维操作空间动作                                  libero_agent：DeepSeek（thinking），update_plan / pick / place_on / place_in / finish
  truth：LIBERO 自己的成功谓词（只用于评估）                   libero_dashboard：工作台 v2（SSE 事件、回放、主板数据）
  MJPEG 127.0.0.1:8093 → 浏览器
```

- **感知**：实例分割图来自仿真器，代替真实系统里的视觉检测模型；物体位置和尺寸由板子从深度图计算，和仿真真值相比误差 1–3 cm。机器人底座和桌、墙等背景会被过滤掉。
- **技能**：夹爪沿世界 y 方向张合。比 7 cm 宽的物体（碗、盘）夹 y 向的边沿，其余夹中心；抓取深度不超过物体高度的一半。抓起后重新观察，确认被抬起的是目标物体，不是就放回原处。放置时考虑抓取点相对物体中心的偏移，让物体中心对准目标；放进容器时从容器口下方松手。
- **模型看到的只有文字**：英文指令、物体坐标、手里拿着什么、上一步结果。“盘子和烤盅之间的那只碗”这类空间描述，由模型根据坐标推断。

## 3. 结果

成功与否都由 LIBERO 官方的 BDDL 谓词判定。原始记录：`logs/20261115-libero-local-trials.log`、`logs/20261115-libero-board-trials.log`。

| 运行位置 | 代码版本 | libero_spatial | libero_object | libero_goal（6 个抓放类任务） | libero_10（5 个多步任务） |
|---|---|---|---|---|---|
| 电脑（第 1 批） | 初版 | 9/10 | 8/10 | — | — |
| 电脑（第 2 批） | 修正扁平物体、抓错物体、放进容器 | 重跑抽屉任务：失败 | 重跑 2 个失败任务：1/2 | 5/6 | 2/5 |
| **RV 板** | 同第 2 批 | **9/10** | **8/10**（1 次因空 `tool_calls` 中断，已修复） | **4/6** | — |
| RV 板（工作台录像） | 加上扁平物体放宽和空 `tool_calls` 修复 | — | — | — | libero_10 任务 0：**成功**（9 轮，216 s） |

板上成功的任务一般 3 轮完成，每个约 25–47 s，比电脑上慢约 30%。多出来的时间主要花在板上解码深度图、计算点云，以及每步动作的网络往返。

**还没解决的问题**（都在技能层，模型推理是对的）：

- 物体在抽屉里时，从正上方下降会被柜体挡住；
- 扁平物体（奶油奶酪、黄油）的抓取，已放宽到位判定，但还没在批次里复测；
- 形状不规则或较高的物体（摩卡壶、马克杯、酒瓶）抓取点不对；
- 开抽屉、拧开关、推东西这类关节操作还没有对应的工具，libero_goal 的任务 0、3、5、7 和 libero_10 的部分任务暂时做不了。

演示录像（只录工作台页面）保存在电脑本地 `.venv/015/video/libero-l10-0.mp4`，没有提交到仓库。

## 4. 运行

板子：`sh /tmp/rv014/run_libero.sh`（工作台）或 `python3 run_board.py <输出目录> libero_spatial:0 ...`（批量）。电脑：

```powershell
conda run -p <LIBERO 环境> python sim_agent/pc/libero_server.py --agent-ip 192.168.50.2 --mjpeg 127.0.0.1:8093
```

本地测试（不用板子）：电脑上运行 `run_local.py <输出目录> libero_spatial:0 ...`，Key 只通过进程的环境变量 `DEEPSEEK_API_KEY` 传入；`libero_server.py` 不加 `--agent-ip`，默认连接 127.0.0.1。
