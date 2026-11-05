# 开发与调试计划（交给 Codex 执行）

阶段按顺序执行。每个阶段末尾的“完成标准”都满足后，才进入下一阶段。安全规则见 `AGENTS.md`。

---

## 第 0 阶段：摸清环境和连接

目标：确认 Codex 能稳定地控制开发板，并把板子的基本信息记录下来。

1. 在主机上找到串口设备（`ls /dev/ttyUSB* /dev/ttyACM*`），确认波特率（先试 115200），用 `picocom`、`minicom` 或 `pyserial` 连上。
2. 上电，抓取完整的 U-Boot 和内核启动日志，存到 `logs/YYYYMMDD-boot.log`。
3. 登录后执行下列命令，输出存到 `logs/YYYYMMDD-board-info.log`：
   `uname -a`、`cat /proc/cpuinfo`、`cat /proc/meminfo`、`ip addr`、`ls /dev/mmcblk*`、`lsmod`、`ls /sys/bus/platform/drivers/ | grep -i xec`、`which ssh scp dropbear sftp-server`
4. 判断网络部署是否可行：板子上能不能用 SSH/SCP，主机和板子能否互相 ping 通。
5. 判断芯片版本：老芯片用 `ecat/`，新芯片用 `ecat_newchip/`。依据是启动日志、设备树（`/proc/device-tree/compatible`）。实在判断不了就问人。
6. 写一份 `docs/BOARD.md`：串口参数、登录方式、IP、芯片版本、内核版本、可用工具。再把 `AGENTS.md` 的“环境假设”一节改成实际情况。

**完成标准**：`docs/BOARD.md` 已提交；Codex 能通过脚本非交互地向板子发命令并取回输出。

## 第 1 阶段：建立部署工具

目标：不用每次手动拔插 TF 卡，就能把文件送上板子、执行命令、取回日志。

1. 写 `scripts/board_exec.sh`（或 Python 脚本）：通过 SSH 或串口在板子上执行一条命令并返回输出。
2. 写 `scripts/deploy.sh <本地目录> <板上目录>`：通过 SCP 把文件推上板子。没有 SCP 就退回到 TF 卡方式，并写清楚手动步骤。
3. 写 `scripts/make_tf_card.sh <设备>`：在主机上制作 TF 卡。脚本必须先打印设备信息并要求输入 `yes` 确认，然后按 `docs/BOOT.md` 复制文件。
4. 用这些脚本从头完整走一遍：制卡、启动、部署 `ecat/`。

**完成标准**：三个脚本已提交，并附一次成功运行的日志。

## 第 2 阶段：验证新启动镜像

目标：确认 `tf-card/` 根目录的新镜像（2026-11-05 编译）能正常启动，并和旧镜像比较。

1. 用新镜像启动，记录内核版本和启动时间，检查 `dmesg` 里有没有报错（`dmesg | grep -iE "error|fail|warn"`）。
2. 用同样的方法测一遍 `tf-card/rpmsg/` 镜像，也就是被替换下来的那一版，作为对照。
3. 在 `docs/IMAGES.md` 里记录每套镜像（新、rpmsg、img、old）的内核版本、设备树差异（用 `dtc -I dtb -O dts` 反编译后 diff）和启动结果。

**完成标准**：新镜像能启动并登录，`docs/IMAGES.md` 已提交。新镜像起不来就停下汇报，不要自行改镜像。

## 第 3 阶段：EtherCAT 主站通信（电机不使能）

目标：主站模块加载成功，能扫描到所有从站。

1. 检查模块和内核是否匹配：在板子上对每个 `.ko` 执行 `modinfo`，比较 `vermagic` 和 `uname -r`。
2. 按 `docs/BOOT.md` 第 3 节加载主站：XEC 网口用 `load_ec_module_master.sh`，通用网卡用 `load_ec_modules.sh`。具体选哪个，根据第 0 阶段的结论决定。
3. 执行 `ethercat master`、`ethercat slaves`、`ethercat pdos`，确认链路 up、从站数量正确、所有从站都能进入 PREOP 或 OP 状态。
4. 测试卸载和重新加载（`rmmod`），确认可以重复执行。
5. 输出存到 `logs/`，结论写进 `docs/ETHERCAT.md`：从站列表、型号（200 还是 GSD600）、网口选择。

**完成标准**：`ethercat slaves` 能列出全部从站。从站型号和数量要请人确认。

## 第 4 阶段：搞清楚 `Trajectory_main` 怎么用

目标：在电机不动的前提下，弄清楚程序的参数、输入文件和输出。

1. 在主机上做静态分析：`file`、`readelf -d`（看依赖库）、`strings | less`（找命令行参数、文件名、提示信息），对象是 `Trajectory_main` 和 `libecatmain.so`。
2. 计算所有变体目录下文件的 sha256，在 `docs/VARIANTS.md` 里列出哪些文件完全相同、哪些不同，并根据目录名和字符串推测每个变体的用途（200/GSD600、周期 4/8/12 ms、noenable、6 轴等）。
3. 在板子上运行 `noenable-notrajectory/` 版本，再运行 `noenable/` 版本，记录完整输出、CPU 占用和实际周期抖动（如果程序会打印）。
4. 搞清楚 `maxVelocity.txt`、`trajectory.txt`、`Position-Velocity.txt` 的格式，以及它们是程序的输入还是输出。

**完成标准**：`docs/VARIANTS.md` 和 `docs/TRAJECTORY_MAIN.md` 已提交，两个不使能版本都运行成功。

## 第 5 阶段：带电机运行（每一步都要人工确认）

目标：在人的监督下，从最保守的配置开始让电机动起来。

1. 先单轴、低速：选 `demo/200` 或 `demo/GSD600`（看第 3 阶段确认的型号）。运行前按 `AGENTS.md` 安全规则第 1 条取得同意。
2. 再测参数组：从 `test/0.5` 开始，然后依次测 `1`、`2`、`4`，每一组都单独取得同意。
3. 最后测六轴：`robot/6_4ms`、`robot/6`、`robot/6_run`。`6_4ms` 带 `Trajectory_main_log`，可以用来采集数据。
4. 每次运行都采集日志，对比指令轨迹和实际轨迹（参考 `test_play/trajectory_full_log.csv` 的格式），写进 `docs/RUNS.md`。

**完成标准**：每种配置都有运行记录。出现异常（报警、跟随误差、通信掉线）时立即停止，并汇报给人。

## 第 6 阶段：为后续开发做准备

目标：从“只能跑现成的二进制”走到“能改代码、能重新编译”。

1. 确定交叉编译工具链：用 `file` 看架构（rv32 还是 rv64、ABI），看 `.ko` 的 `vermagic`，推断需要的内核版本。
2. 列出缺少的源码：`Trajectory_main`、`libecatmain`、`libjhkdl`、IgH EtherCAT Master 的 Nuclei XEC 驱动、内核和设备树。**向人索取源码**，不要尝试反编译重写。
3. 用 `ecat/include/ecrt.h` 和 `ecat/lib/libethercat.a` 编一个最小的 EtherCAT 用户程序（例如只读从站状态），验证工具链可用。
4. 测一下 `jhkdl0911/test_operators` 和 `jhkdl/test_ur10`，记录运动学库的接口和用法。

**完成标准**：工具链能编出在板子上运行的程序。源码清单已经交给人。

---

## 需要人提供或确认的信息

- 串口设备和波特率、登录账号
- 芯片版本（老芯片还是新芯片）
- 伺服驱动和电机的型号与数量（200 还是 GSD600）
- 急停装置、机械限位等现场安全条件
- `Trajectory_main` 等程序的源码，以及预期的运动效果
