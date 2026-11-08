# 任务 010：MuJoCo Panda 仿真端 + 板子实时控制环联调（S1 + S2）

- **对应阶段**：`docs/SIM_AGENT_DESIGN.md` 的 S1、S2
- **作者**：Claude
- **日期**：2026-11-08
- **电机是否可能动作**：**否**。只有仿真，不碰 EtherCAT 和真实电机。
- **前置条件**：任务 008 完成。分支 `task-010-mujoco-loopback`，基于 `task-008-eth0-network`，再合并上游 `handoff-protocol`。本任务和任务 009 互不依赖，可以先做任何一个。
- **必须先读**：`docs/SIM_AGENT_DESIGN.md`，尤其是第 3 节“通信协议 v1”。两端都**严格**按这个协议实现，字段、长度、端口一个都不能改。如果发现协议有问题，在报告里提出来，由 Claude 修订协议。

## 目标

1. 电脑上：MuJoCo 里的 Panda 场景和 `sim_server.py`。
2. 板子上：C 语言实时控制环 `rt_ctl`，以及一个 Python 测试客户端。
3. 两边连起来：板子让 Panda 按正弦轨迹运动，并取到俯视图，还要测出延迟和抖动。

## 不要做的事

- 不改 Windows 防火墙。连接方向是**电脑主动连板子**，见设计文档 2.1。
- 不改 Clash。不碰 eth1。
- 不提交 MuJoCo Menagerie 的模型文件，只提交一个下载脚本，并注明来源和许可证。

## 目录结构

```
sim_agent/
├── pc/                       # 电脑端（Windows，Python）
│   ├── fetch_assets.ps1      # 下载 mujoco_menagerie 的 franka_emika_panda（固定 commit）
│   ├── scene_tabletop.xml    # include panda.xml + 桌子 + 方块 + 托盘 + top/wrist 相机
│   ├── sim_server.py         # 协议 v1 的电脑端
│   └── requirements.txt      # mujoco、numpy（固定版本）
├── board/
│   ├── rt_ctl/               # C：rt_ctl.c、protocol.h、Makefile
│   └── tools/proto_client.py # Python 测试客户端（render、objects、reset，以及发送正弦轨迹）
└── README.md                 # 两端怎么启动
```

## 步骤

### A. 电脑端（S1）

1. 创建 Python 虚拟环境，安装 `mujoco`、`numpy`（版本写进 `requirements.txt`）。运行 `fetch_assets.ps1`，把 Menagerie 下载到被 `.gitignore` 忽略的 `sim_agent/pc/assets/` 目录。
2. `scene_tabletop.xml`：
   - Panda 用 Menagerie 原版的 `panda.xml`，执行器保持原样：7 个关节位置执行器，加 1 个夹爪执行器，`ctrl` 范围 0–255，对应开口 0–0.08 m。
   - 桌子的桌面高度固定，例如 `table_z = 0.0`，Panda 底座放在桌边。
   - 红、绿、蓝三个 4 cm 方块，加左右两个托盘，都放在 Panda 能够得着的范围内。
   - 相机：`top`（俯视，固定位置，能看到整个工作区）、`wrist`（装在手上）。
3. `sim_server.py`：
   - 物理步长 0.002 s，按实时速度运行（落后时不追帧，记录落后次数）。
   - 每 2 步（4 ms）给 `192.168.50.2:15001` 发一个 `RVS1` 状态包。用同一个 socket 接收 `RVC1`：`mode=1` 时把 `q_des` 写进关节执行器，夹爪宽度按比例换算到 0–255；超过 100 ms 收不到指令就保持当前位置，并置 flags bit0。
   - 连接 `192.168.50.2:15002` 的 TCP 服务通道，实现 `hello`、`render`（640×480 JPEG，质量 80）、`objects`、`reset`、`ping`。断开后每 2 秒重连一次。
   - 渲染在单独的线程里做，**不能拖慢物理步进**。
   - 打开 MuJoCo 的可视化窗口（`mujoco.viewer.launch_passive`），也可以加 `--headless` 参数关掉窗口。
   - 每 5 秒在终端打印一次：发出的包数、收到的指令数、超时次数、落后次数。
4. 先在电脑本机自测：写一个 `pc/fake_board.py`，在 127.0.0.1 上模拟板子的两个端口，确认协议能跑通（`sim_server.py` 加 `--board-ip 127.0.0.1` 参数）。

### B. 板子端（S2）

5. `board/rt_ctl/`：
   - `protocol.h`：用 `__attribute__((packed))` 定义两个结构体，并用 `_Static_assert` 检查长度分别是 144 和 80。
   - `rt_ctl.c`：绑定 UDP `0.0.0.0:15001`；`mlockall`；`SCHED_FIFO` 优先级 80（没有权限就报错退出）；可以用参数绑定到某个 CPU。每收到一个 `RVS1`，就立即回一个 `RVC1`。
   - 测试模式 `--sine`：前 2 秒 `mode=0`；之后以收到的第一个 q 为中心，关节 1 和关节 4 做幅度 0.3 rad、周期 4 s 的正弦运动，夹爪每 4 s 开合一次。关节目标要按 Menagerie `panda.xml` 里的关节范围限位。
   - 每秒打印一行统计：收包数、从收到状态包到发出回包的处理时间（平均和最大值）、相邻两个状态包的到达间隔（平均、最大值、标准差）、丢包数（按 seq 计算）。
   - 收到 SIGINT 后，连续发 0.5 秒 `mode=0` 再退出。
   - 在 eMMC Ubuntu 里用 gcc 编译（`-O2 -Wall`），可执行文件拷到 Buildroot 能访问的位置运行。如果 chroot 里编出来的程序因为 glibc 版本在 Buildroot 里跑不了，就直接在 chroot 里运行（网络是共享的），并在报告里说明。
6. `board/tools/proto_client.py`：监听 TCP `0.0.0.0:15002`，等电脑连上来后，依次发送 `hello`、`objects`、`render top`、`render wrist`、`reset seed=1`、`objects`，把两张图存成文件，打印收到的应答，并计算图像传输耗时。

### C. 联调

7. 板子上执行 `board_bootstrap.ps1` 之后，先启动 `rt_ctl --sine`，再启动 `proto_client.py`。电脑上启动 `sim_server.py`，可视化窗口里应该能看到 Panda 摆动、夹爪开合。
8. 连续运行 **10 分钟**，记录两端的统计。计算往返延迟：电脑端用状态包的发送时间和对应 `ack` 指令包的到达时间算出 p50、p99、最大值；同时统计丢包率。
9. 把两张图（`top`、`wrist`）提交到 `sim_agent/docs/img/`，作为场景布置的证据。
10. 再做一次中断测试：在板子上 Ctrl+C 停掉 `rt_ctl`，确认电脑端在 100 ms 内进入保持状态；重新启动 `rt_ctl` 后，机械臂能接着运动。
11. 日志：`logs/20261108-010-pc.log`、`logs/20261108-010-board.log`。写报告 `handoff/reports/010-mujoco-panda-loopback.md`，更新 `STATUS.md`，发 PR。

## 验收标准

- 10 分钟内丢包率 < 0.1%，往返延迟 p99 < 2 ms，板子端处理时间最大值 < 200 µs。
- 停掉 `rt_ctl` 后，电脑端 100 ms 内进入保持状态。
- 两种相机图像都能正确传回，场景里能看清三个方块和两个托盘。

达不到标准也要如实报告实测数据，并分析瓶颈在哪一边，不要放宽标准后报“通过”。

## 需要回答的问题

1. 用的 MuJoCo 和 Menagerie 是哪个版本（commit）？
2. 电脑端物理步进能否保持实时？落后次数是多少？
3. 10 分钟的丢包率、往返延迟（p50、p99、最大值）、板子端处理时间、到达间隔抖动各是多少？
4. `rt_ctl` 最后是在 Buildroot 里跑的，还是在 chroot 里跑的？SCHED_FIFO 设置成功了吗？
5. 两张相机图像各多大、传一张要多久？
6. 中断测试的结果如何？
7. 协议 v1 有没有需要修改的地方？
