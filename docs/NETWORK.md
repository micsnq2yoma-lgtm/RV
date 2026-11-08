# 开发板网络：固定 IP 与 Clash HTTP 代理

## 当前状态

任务 008-r2 **blocked**。固定 IP、原生 SSH、SSH 脚本退出码和 SCP 往返哈希已验证；之后收紧现有 Clash 防火墙放行范围时，主机 HTTPS 检查失败，已按任务要求回滚。当前电脑有线口恢复 DHCP/APIPA，三条原规则恢复，新规则删除，代理仍只监听 `127.0.0.1:7897`。Allow LAN 未打开，wget、apt、git 外网测试未执行。

下面记录 r2 的目标方案和核心指令。**当前电脑没有 192.168.50.1，需维护者处理防火墙兼容性问题后才能恢复部署通道。** 原 ICS 试验完整保留在[报告 008](../handoff/reports/008-eth0-internet-via-pc.md)中，不再采用。

## 接线与目标地址

| 位置 | 接口 / 地址 |
|---|---|
| 板上网口 | J1 已确认为 eth0；eth1 留给 EtherCAT |
| 电脑网口 | 有线网卡直连 J1；目标 `192.168.50.1/24`，无网关、无 DNS |
| 板上 eth0 | `192.168.50.2/24` |
| HTTP/mixed 代理 | 目标 `http://192.168.50.1:7897` |

本轮核查 192.168.50.0/24 与主机已有地址和直连路由不重叠。旧 ICS 地址 192.168.137.178 仍留在板子 RAM 中，指向 192.168.137.1 的旧默认路由已删除。

## 电脑端设置及撤销

每次涉及主机网络变更，都先备份精确状态并启动独立回滚守护，确认心跳递增，获得当次授权后操作。无线网卡、TUN、DNS、规则、订阅和防火墙总体开关保持原状。

1. **固定 IP**：管理员在直连板子的网卡关闭 IPv4 DHCP，添加 `192.168.50.1/24`，不设网关和 DNS。配置后立即检查主机多个 HTTPS 站点。本轮这一阶段正常，随后已因防火墙阶段失败而撤销。撤销时删除本次静态地址，并恢复原 DHCP/DNS、路由及 metric 配置；本机原状态为 DHCP 开启。
2. **Allow LAN**：只有人在 Clash 界面打开并确认代理端口。撤销时由人关闭。本轮没有打开，监听仍为 127.0.0.1:7897。若弹出防火墙提示，不选择向所有网络开放。
3. **防火墙**：目标规则显示名为 `RV board to Clash proxy`，内部 Name 为 `RV-Board-Clash-Proxy-008r2`，仅允许 TCP 7897、远端 192.168.50.2、本地 192.168.50.1。撤销新规则可用：

```powershell
Remove-NetFirewallRule -Name RV-Board-Clash-Proxy-008r2
```

本机原有三条覆盖 Clash 核心的宽放行规则。新增窄规则不能抵消旧规则的宽权限。人在确认无其他设备使用后，额外批准停用这三条旧规则；但该组合变更后主机 HTTPS 超时，已恢复旧规则并删除新规则。具体哪条旧规则与主机联网有关未隔离确认，后续不得直接照抄这一失败组合。

## 每次开机后的板上操作

接主电后按维护者确认的方法短按 RESET；先通过串口登录 Buildroot，退出终端程序释放 COM3。若电脑端已按后续批准的方案就绪，在仓库根目录运行一条命令：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./scripts/board_bootstrap.ps1 -Port COM3
```

脚本默认使用仓库 `.venv/Scripts/python.exe`（需 pyserial），可用 `-Python` 指定解释器。它读取同目录 `board_net_up.sh`，通过串口执行同一份 POSIX sh 代码，并传入电脑 UTC。默认日志在忽略目录 `.venv/board-bootstrap.log`，可用 `-LogPath` 指定。脚本要求已有登录 shell，不自动发送凭据；串口名每次重新枚举。

本轮实际返回码为 0，eth0 地址、carrier=1、旧默认路由移除和 UTC 均已核实。脚本只配置板子内存状态，不能替代电脑端 IP 或代理设置。

也可以将脚本传到板上后执行：

```sh
sh /tmp/board_net_up.sh '2026-11-08 03:36:41'
# 时间参数仅为格式示例，须换成电脑当前 UTC；也可不传时间
ip addr show eth0
ip route
date -u
```

脚本仅删除已知失效的 `default via 192.168.137.1 dev eth0`，不删除其他接口或其他网关的路由。配置不依赖重启保留；本轮旧 DHCP 客户端仍在运行，后续也应重新核对路由。

## SSH 与 SCP

第一次连接前，通过可信串口读取并核对指纹：

```sh
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

电脑端示例（仅在电脑固定地址已恢复后使用）：

```powershell
ssh root@192.168.50.2 "uname -a"
./scripts/board_ssh.ps1 192.168.50.2 'uname -a'
./scripts/board_ssh.ps1 192.168.50.2 'false'
$LASTEXITCODE
./scripts/board_scp.ps1 192.168.50.2 ./example.txt /tmp/example.txt
./scripts/board_scp.ps1 192.168.50.2 ./received.txt /tmp/example.txt -Download
Get-FileHash ./example.txt, ./received.txt -Algorithm SHA256
```

两个脚本不包含密码，使用原生 OpenSSH 交互认证，返回原生退出码。可选 `-KnownHostsFile` 指向预先通过可信渠道核实的 known_hosts 文件，强制主机核验。没有生成或部署客户端认证密钥。

本轮原生 SSH 成功；脚本 `uname -a` 返回 0、`false` 返回 1。SCP 使用 `-O` 兼容板上旧协议；修复下载路径整体引号导致的 `filename does not match request` 后，59 字节测试文件往返 SHA-256 一致。保持严格文件名检查，没有使用 `-T`。当前已测试普通绝对远端路径，包含特殊字符的路径未实机覆盖。

## 校时

镜像没有 ntpd。串口 bootstrap 会传入电脑 UTC；已有 SSH 时也可：

```powershell
$utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')
./scripts/board_ssh.ps1 192.168.50.2 "date -u -s '$utc'; date -u"
```

本轮串口和 SSH 两种路径均成功。若交互输入密码等待较久，传入时间会产生相应延迟；不要把这当作精密时钟同步。未设置 RTC，重启后重新检查。

## 代理、Ubuntu apt 与 git（待验证）

防火墙问题解决且由人开启 Allow LAN 后，先在 Buildroot 检查 HTTP 代理：

```sh
export http_proxy=http://192.168.50.1:7897
wget -q -O - http://ports.ubuntu.com/ubuntu-ports/dists/noble/Release 2>&1 | head -5
unset http_proxy
```

通过后进入 Ubuntu，再逐项执行：

```sh
sh /mount_emmc.sh start
date -u
cat /etc/apt/sources.list.d/*.sources /etc/apt/sources.list 2>/dev/null
P=http://192.168.50.1:7897
apt-get -o Acquire::http::Proxy=$P -o Acquire::https::Proxy=$P update
# 以下安装必须先获得当次明确批准：
# apt-get -o Acquire::http::Proxy=$P -o Acquire::https::Proxy=$P install -y git ca-certificates
# git --version
# git -c http.proxy=$P ls-remote https://github.com/Nuclei-Software/nuclei-linux-sdk HEAD
exit
sh /mount_emmc.sh stop
sh /mount_emmc.sh status
```

代理只作为命令参数使用，不写进 Ubuntu 配置；不执行 apt upgrade、不更换源。本轮未进入 Ubuntu、未安装包，软件源和 git 版本未重新确认。最终确认 eMMC 全部未挂载。
