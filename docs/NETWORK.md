# 开发板网络：固定 IP 与 SSH 反向代理隧道

## 当前状态

任务 008-r3 已完成。电脑有线口保留 `192.168.50.1/24`（无网关、无 DNS），J1 对应板上 eth0，使用 `192.168.50.2/24`。电脑 HTTPS 检查正常。Buildroot wget、Ubuntu apt 更新和 git 访问 GitHub 均通过 SSH 隧道验证。git 为 2.43.0。结束时隧道已关闭、eMMC 全部卸载。

代理路径：板上程序 → 板上 `127.0.0.1:7897` → SSH → 电脑 `127.0.0.1:7897` → Clash。Ubuntu chroot 与 Buildroot 共享网络。主机 Clash、TUN、DNS、防火墙与 ICS 保持本轮开始时的状态。历史试验见[报告 008](../handoff/reports/008-eth0-internet-via-pc.md)。

## 每次开机后的顺序

1. 接好 J1、调试 USB 和主电，按板卡已确认的启动方法进入 Buildroot。串口登录后断开终端释放端口；重新枚举确认串口名。
2. 在电脑仓库根目录执行（要求电脑固定 IP 仍在）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./scripts/board_bootstrap.ps1 -Port COM3
./scripts/board_ssh.ps1 192.168.50.2 'uname -a; date -u'
```

bootstrap 使用 `.venv/Scripts/python.exe` 和 pyserial，可通过 `-Python` 指定解释器。它要求已有登录 shell，不发送凭据；配置板子 RAM 中的 eth0 地址和电脑当前 UTC。默认日志在忽略目录 `.venv/board-bootstrap.log`。重启后重新执行。仅删除已知失效的 `default via 192.168.137.1 dev eth0`，不改其他路由；旧 DHCP 地址可能仍留在 RAM，应检查 `ip route`。不操作 eth1。

第一次 SSH 连接前，通过可信串口执行 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` 并核对指纹；主机密钥变化时重新核实。脚本支持 `-KnownHostsFile` 指向已核实的专用文件，启用严格校验。

3. 需要外网时，在另一个 PowerShell 终端保持以下命令运行：

```powershell
./scripts/board_proxy_tunnel.ps1 -BoardIP 192.168.50.2 -ProxyPort 7897
# 本轮使用了已通过串口核实的专用文件，可追加：
# -KnownHostsFile ./.venv/008r3/known_hosts
```

密码只在交互提示中输入，不写入脚本或日志。该脚本前台运行，按 Ctrl+C 关闭。端口以当前电脑代理监听为准；本轮为 7897。它显式绑定板上回环地址，转发失败时退出。板上确认：

```sh
netstat -tln | grep 7897
# 应仅见 127.0.0.1:7897 LISTEN
http_proxy=http://127.0.0.1:7897 wget -q -O /tmp/noble-release http://ports.ubuntu.com/ubuntu-ports/dists/noble/Release
# 先确认 wget 返回 0，再查看内容，避免管道掩盖失败
head -5 /tmp/noble-release
```

4. 进入 Ubuntu，按需通过临时参数访问外网：

```sh
sh /mount_emmc.sh start
date -u
P=http://127.0.0.1:7897
apt-get -o Acquire::http::Proxy=$P -o Acquire::https::Proxy=$P update
git --version
git -c http.proxy=$P ls-remote https://github.com/Nuclei-Software/nuclei-linux-sdk HEAD
# 任何后续安装仍需当次授权；本轮已批准安装 git 及依赖、更新 ca-certificates。
```

不把代理写入配置，不更换软件源，不执行 apt upgrade。若时钟错误，先从电脑重新校时：

```powershell
$utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')
./scripts/board_ssh.ps1 192.168.50.2 "date -u -s '$utc'; date -u"
```

5. 使用结束，先在 Ubuntu `exit`，回到 Buildroot 卸载，再关闭电脑隧道：

```sh
exit
sh /mount_emmc.sh stop
sh /mount_emmc.sh status
```

在隧道终端按 Ctrl+C；板上 `netstat -tln` 应不再有 7897。不要在 apt/dpkg 工作中关闭隧道或强制卸载。

## SSH 与 SCP

```powershell
./scripts/board_ssh.ps1 192.168.50.2 'uname -a'
./scripts/board_scp.ps1 192.168.50.2 ./example.txt /tmp/example.txt
./scripts/board_scp.ps1 192.168.50.2 ./received.txt /tmp/example.txt -Download
Get-FileHash ./example.txt, ./received.txt -Algorithm SHA256
```

脚本返回原生退出码；r2 已验证 SSH 0/1 和 SCP 往返哈希。SCP 使用 `-O`，保持严格文件名检查。普通绝对路径已实测，特殊字符路径未实机覆盖。

## 电脑固定 IP 如何撤销

电脑端本轮唯一网络改动是直连网卡的固定 IPv4。撤销也应先核对网卡身份、备份当前精确状态、启动独立回滚守护并获得当次授权，避免误改 WLAN/TUN。原状态为 IPv4 DHCP 开启、DNS 自动；本轮精确备份位于本地忽略目录 `.venv/008r3/run-20261107-203041/`。

核实目标网卡后，管理员可执行以下核心命令，并依据备份恢复原 metric/路由等属性，再检查电脑 HTTPS：

```powershell
# $boardIfIndex 必须取自当次核实的直连网卡，不照抄历史索引
Remove-NetIPAddress -InterfaceIndex $boardIfIndex -IPAddress 192.168.50.1 -Confirm:$false
Set-NetIPInterface -InterfaceIndex $boardIfIndex -AddressFamily IPv4 -Dhcp Enabled
Set-DnsClientServerAddress -InterfaceIndex $boardIfIndex -ResetServerAddresses
```

本轮验证成功，固定 IP 按用户授权保留，未执行撤销。
