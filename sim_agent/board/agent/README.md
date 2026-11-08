# Panda 智能体与监控面板

仅用于 MuJoCo 仿真。板子负责视觉、DeepSeek 规划、IK 与控制；Windows 只负责物理和渲染。
默认使用 FIFO80/CPU1 控制器，Python 普通调度/CPU0。日志与图片全部在 RAM，必须边运行边同步回电脑。

## 首次准备

使用 boot_1106，按维护者约定主电接通后按 RESET。主机有线 IP 为 `192.168.50.1/24`，
板子 J1/eth0 为 `192.168.50.2/24`。伺服动力电保持断开。登录后关闭串口终端，再运行：

```powershell
./scripts/board_bootstrap.ps1 -Port COM3
./scripts/board_proxy_tunnel.ps1 -BoardIP 192.168.50.2 -KnownHostsFile <本次启动已核验的known_hosts>
```

隧道窗口保持打开；它仅把板上 `127.0.0.1:7897` 转发到电脑 Clash 回环代理。
不启用 ICS/Allow LAN，不改防火墙。主机密钥发生变化时先通过物理串口核验，不能关闭密钥检查。

在另一个 SSH 会话的 Buildroot shell 中挂载 Ubuntu，退出它自动打开的 shell，然后绑定 RAM：

```sh
sh /mount_emmc.sh start
exit
mount --bind /tmp /mnt/ubuntu/tmp
chroot /mnt/ubuntu
export http_proxy=http://127.0.0.1:7897 https_proxy=http://127.0.0.1:7897
apt-get update
apt-get install --no-install-recommends python3-numpy python3-pil python3-httpx python3-fastapi python3-uvicorn gcc
```

安装仅首次需要。API Key 由用户安全写入 Ubuntu 的 `/root/.config/rv-agent/deepseek.key`，权限600。
不要把 Key 放环境命令、聊天、截图或日志。程序只读取这个文件，不显示它，也不提供修改密钥的网页入口。

将仓库 `sim_agent/board/agent`、`sim_agent/board/rt_ctl`、`sim_agent/board/tools` 上传到
Buildroot 的 `/tmp/rv014/`，并将 `scripts/run_demo.sh` 上传为 `/tmp/rv014/run_demo.sh`。
可用已核验主机密钥的 SCP；每次重启后 RAM 文件都需重新上传。

## 启动

在 Ubuntu 中编译（产物仍在绑定的 RAM 目录）：

```sh
gcc -O2 -Wall -Wextra -std=c11 -shared -fPIC /tmp/rv014/agent/kin_native.c -o /tmp/rv014/agent/libkin_native.so -lm
gcc -O2 -Wall -Wextra -std=c11 -shared -fPIC /tmp/rv014/agent/vision_native.c -o /tmp/rv014/agent/libvision_native.so
gcc -O2 -Wall -Wextra -std=c11 /tmp/rv014/rt_ctl/rt_ctl.c -o /tmp/rv014/rt_ctl/rt_ctl -lm -pthread
sh /tmp/rv014/run_demo.sh
```

启动脚本先启动控制器，再启动面板；面板负责启动 agent 子进程和 sysmon。
控制器数据在 `/tmp/rt_ctl.stats`；终端每秒打印 CPU、内存、IRQ、网络与实时指标。
`kin.py` 自动使用同目录的 `.so`；`RV_IK_BACKEND=python` 仅用于对照，不会自动编译。
原始模型链来自 `kinematics` 应答，不手抄 DH 参数。C 返回成功后使用相同的1mm/1°判定。

随后在 Windows 仓库根目录运行，保持窗口可见：

```powershell
.venv/010/py/Scripts/python.exe sim_agent/pc/sim_server.py --seconds 7200
python sim_agent/pc/archive_dashboard.py --out .venv/014/demo-archive
```

浏览器打开 `http://192.168.50.2:8080`。输入任务和不同 seed，点击“开始任务”。
页面显示四个视角、简短行动说明、工具结果、token和资源。帧率可选4/2/1 fps。
停止会等待当前技能结束，再回到 home。一次只允许运行一个任务。
API 每次最多重试2次，最多12轮，每轮只执行一个经过名称/参数校验的工具。

任务示例：

- 把红色方块放进左边的托盘
- 把蓝色方块叠到绿色方块上面
- 把三个方块都放进右边的托盘

这三条完整文本有独立真值验收规则。任意其他文本可运行，但不会套用模糊的成功判定。
模型只获得颜色感知结果；`objects` 真值只在运行结束后的独立验收中使用。
视觉遮挡时保留旧坐标并标记 `occluded`，不把旧位置当新观测。叠放高度采用已知方块尺寸和最近放置平面估计。

## 记录与退出

每次运行保存在 `/tmp/runs/<时间>/`：`request.json`、`steps.jsonl`、四视角逐步图片、
`sysmon.csv`、`status.json`、`evaluation.json` 与 `agent.log`。面板回放只访问这个固定目录。
主机归档器每秒同步文件与资源数据；断线会记录异常并继续尝试，不删除已取得证据。
完整记录较大，公开提交前排除认证交互与设备标识。API请求日志不包含 Authorization 头。

点击停止并等待任务结束。退出面板启动脚本、仿真和归档器，确认本次进程退出，再从 Buildroot：

```sh
exit                       # 离开Ubuntu shell
umount /mnt/ubuntu/tmp
sh /mount_emmc.sh stop
sh /mount_emmc.sh status
```

所有 Ubuntu 子挂载应消失；不要强制卸载。最后关闭 SSH 隧道。
若板子失联，按任务014仅记录时间和当前活动，请人RESET，计入失败后继续；不在本任务排查根因。

实现参考：[DeepSeek工具调用](https://api-docs.deepseek.com/guides/tool_calls/)、
[FastAPI WebSocket](https://fastapi.tiangolo.com/advanced/websockets/)、
[MuJoCo Python接口](https://mujoco.readthedocs.io/en/stable/python.html)。
