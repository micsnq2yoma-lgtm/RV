# 报告 001：板级只读采集完成，TF 卡镜像不符合前置条件

- **执行者**：Codex
- **日期**：2026-11-05（America/Los_Angeles）
- **结果**：blocked
- **分支 / PR**：`task-001-tf-card-boot-bringup` / [草稿 PR #1](https://github.com/micsnq2yoma-lgtm/RV/pull/1)，目标 handoff-protocol

## 一句话结论

真机串口命令通道已验证，完成 35 条只读采集；但 TF 卡根目录实际为 rpmsg 副本而非任务要求的新版，U-Boot 全程与网络验证也未完成，不能标记 done。

## 逐步执行记录

日志均位于 logs/，文件前缀为 20261105-001-。公开文件为注明范围的原始输出摘录；认证和含真实 MAC 等完整记录仅保留本机。

| 步骤 | 结果 | 证据 |
|---|---|---|
| 1 主机准备 | Windows 等价枚举识别 COM3；Python 3.13.13、pyserial 3.5 | host-prep 1–10、25–36 行 |
| 2 串口脚本 | 完成，修复 Windows 输出编码及 CRLF，9 项主机测试通过 | host-prep 104–120 行；scripts/serial_console.py |
| 3 人工确认 | 人确认卡、线与电机断动力条件，按通知断电/上电 | 本次会话；host-prep 67、69、121 行 |
| 4 上电捕获 | 仅取得登录阶段，完整 U-Boot 缺失；此前两次超时、57600 乱码均保留 | boot.log、boot-57600.log、host-prep 37–39、67–72、121–122 行 |
| 5 启动检查 | 恢复内核缓冲区，有内核版本、设备及 /init；没有实际 fatload 输出 | dmesg 日志 |
| 6 U-Boot 回退 | 未执行，未取得提示符；未发送 printenv/fatload/bootm 或保存环境 | boot.scr 只静态读取，board-info 184–202 行 |
| 7 登录后采集 | 本次接入已在 shell，没有再发送或验证凭据。02:02:57–02:05:27，35 条命令均取得状态和提示符 | board-info、network、dmesg；完整记录在忽略目录 |
| 8 TF 卡只读检查 | 挂载明确为 vfat ro；三个文件大小不符，四组根目录/rpmsg 哈希一致 | board-info 121–132、203–212 行 |
| 9 模块元数据 | 无 modinfo，用板上 strings 读九个 .ko，版本一致；未加载 | board-info 145–183 行 |
| 10 版本判断 | ecat_newchip 为静态候选，硬件修订号和运行未验证 | loader-excerpts 2–9 行；board-info 102–107 行 |
| 11 网络 | 两个网口无链路和业务 IP，不能测试 ping/SSH；未改配置或运行 DHCP | network；board-info 108–120 行 |
| 12 卸载卡 | 完成，TF_CARD_UNMOUNTED | board-info 230–232 行 |
| 13–15 整理 | 已更新 BOARD、AGENTS、报告和状态表；本轮新增诊断公开同步已获用户明确同意，提交至现有草稿 PR #1，任务保持 blocked | docs/BOARD.md、handoff/STATUS.md |

## 需要回答的问题

1. **板子能否从这张 TF 卡自动启动到 shell？如果不能，卡在哪一步？** 当前可操作 Linux shell，但完整 U-Boot 未取得，不能确认启动源和 boot.scr 自动执行。卡根目录不满足新版文件前置条件，确认为卡内 rpmsg 文件副本。

2. **串口设备、波特率、登录方式分别是什么？** COM3，115200 / 8N1，无流控；板上 ttyNUC0，终端 /dev/console。本次接入已有 shell，未再次发送或验证用户提供的凭据。认证信息不公开。

3. **U-Boot 的 bootcmd 是什么？会自动运行 boot.scr 吗？** 未确认；未取得 printenv 输出。boot.scr 静态内容含 fatload/bootm，不能当作已执行证据。

4. **内核版本是什么（uname -r），和 .ko 的 vermagic 是否一致？** 内核 6.6.90-rt54+。三个 ko 目录共九个模块均为 `6.6.90-rt54+ SMP preempt mod_unload modversions riscv`。版本字符串一致，符号 ABI、加载结果未验证。

5. **CPU 是 rv32 还是 rv64，ISA 字符串是什么？内存多大？** riscv64，ISA 为 `rv64imafdc_zicbom_zicntr_zicsr_zifencei_zihpm_sscofpmf_sstc_svpbmt`，MMU sv39。物理 2 GiB，MemTotal=2,047,968 kB。possible/present=0-7、online=0-1、offline=2-7，预期核数未知。见 board-info 8–32、213–222 行。

6. **设备树的 compatible 是什么？f8b160000.xec 设备是否存在，当前绑定在哪个驱动上？** compatible/model 均为 nuclei,p0soc。f8b160000.xec 不存在；实际 f9c210000.xec（eth0）、f9cdc0000.xec（eth1）均绑定 nuclei-xec。见 board-info 36–38、59–66、102–107 行。

7. **应该用 ecat/ 还是 ecat_newchip/？依据是什么？** 静态建议以后以 ecat_newchip 为候选，其脚本使用 eth1、f9cdc0000.xec 和 ko_newchip，匹配平台设备；旧脚本指向不存在的 f8b160000.xec。未执行或修改脚本，硬件修订号及驱动运行仍需后续任务验证。见 loader-excerpts。

8. **板子上有哪些网卡（eth0、eth1……）？有没有 IP？主机能否 SSH 或 SCP 到板子？** lo、eth0、eth1、sit0。以太网口均 NO-CARRIER、carrier=0，无业务 IP 和业务路由。未测试 ping/SSH/SCP；存在 ssh/scp/sshd 二进制不代表服务或连通性成立。未运行 DHCP 或修改网络。

9. **启动日志里有哪些报错或警告值得关注？** CPU2–CPU7 failed to come online，最后仅两个 CPU 上线（dmesg 74–80 行），预期核数与原因未确认。已取得内核缓冲区中未见 Kernel panic、Unable to mount、MMC error。约 8.741 秒运行 /init，完整上电耗时未测；板上时钟为 1970 年。

10. **serial_console.py exec 能否稳定使用？已知的限制有哪些？** 本次 35 条真实命令均获取返回码及提示符，无标记超时；31 条退出 0，4 条退出 1 来自缺少可选路径、工具或属性，保留真实结果。9 项主机测试通过。仍依赖已登录 POSIX shell 和正确提示符正则，子 shell 的 cd/环境不跨调用保留；超时不终止远端命令；开串口可能有控制线脉冲。这里只证明本次序列可用，不夸大长期稳定性。

## TF 卡对照

| 文件 | 任务要求（字节） | 实测（字节） |
|---|---:|---:|
| boot.scr | 719 | 719 |
| uImage.lz4 | 4,223,577 | 4,245,866 |
| uInitrd.lz4 | 14,856,105 | 14,224,341 |
| kernel.dtb | 8,621 | 9,238 |

四组根目录/rpmsg SHA-256 全部相同，见 board-info 203–212 行与 BOARD.md。未替换镜像、修卡或写卡。

## 和任务单不一致的地方

- 任务单仅在 origin/handoff-protocol（387c2ad），任务分支及 PR 以其为基线，未修改任务单。
- 主机为 Windows，使用 .NET/CIM/PnP/pyserial；依赖隔离在 .venv，未修改全局 Python。相关硬件与 Git 操作按环境授权运行，未修改网络设置。
- 初始其他波特率仅被动侦听，57600 后补充上电尝试有乱码，暴露的 Windows 输出编码问题已修复。用户明确指定回到 COM3 / 115200，随后获得可读输出。历史失败日志保留。
- 旧的认证阻塞已不适用，本次接入已在 shell；未再发送或验证所提供凭据，不将认证信息写入配置、日志或公开材料。
- U-Boot 全程缺失，另行恢复 dmesg，仍标记 bootcmd、fatload 和自动启动路径未知。
- 无 modinfo，但板上有 strings，因此直接只读读取九个卡上模块的元数据；未运行 EtherCAT 命令。
- 卡镜像不符后，只完成只读取证与卸载，没有修卡或进入任务 002。
- 公开日志为标明范围的输出摘录。真实 MAC、认证、完整目录清单、带 NUL 的 model 原始输出留在本机 .venv，完整原始记录未编辑。network 省略链路层地址行，loader 只包含路径与设备地址。即使日志小于 5 MB，也按公开仓库隐私规则省略这些内容。
- 经用户明确同意，通过个人 fork 提交草稿 PR；私有文档链接及认证信息不写入公开仓库。

## 发现的问题和风险

- 卡根目录不是任务要求的新版；已到 shell 不能当作目标镜像已验证。
- CPU2–CPU7 未上线，预期核数不明；未擅改设备树、固件或 CPU 设置。
- 旧加载脚本的设备地址不匹配；newchip 仅为静态候选，未做驱动运行认证。
- 网口无链路，SSH/SCP 未验证；没有改网络或启动 DHCP。
- 根文件系统在内存，板上时钟未设，取证使用主机时间。
- 卡已卸载、串口已关闭；未加载模块、运行电机程序或改变 TF 卡、U-Boot、主机/板子网络。

## 需要人做的事

1. 请维护者提供任务要求的新版镜像来源，或由规划方修订任务；后续制卡/替换文件按明确任务和授权进行。
2. 确认实际预期核数与 CPU2–CPU7 未上线的原因。
3. 完成需要测试的网线连接；若后续需 DHCP 或静态 IP，再按任务要求授权该项变更。
4. 正确镜像就绪后补齐完整上电过程、U-Boot bootcmd、boot.scr 与 fatload 证据。

## 给 Claude 的建议（可选）

任务 001 保持 blocked，不进入任务 002。串口通道和板级信息已具备，先处理目标镜像与前置条件差异，再补启动和网络验证。
