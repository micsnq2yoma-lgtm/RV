# eth0 经 Windows 共享网络

## 当前结果（任务 008，2026-11-07）

任务 **blocked**，Windows ICS 当前已关闭并恢复原配置。启用共享时板子能 ping 通 `8.8.8.8`，但同一时段主机 HTTPS 检查失败，独立 Chrome 报 `ERR_NETWORK_CHANGED`。不能据此认为已经打通部署通道；SSH、SCP、Ubuntu apt 尚未验证。证据和全部限制见[报告 008](../handoff/reports/008-eth0-internet-via-pc.md)。

## 接线与地址

| 项目 | 实测结果 |
|---|---|
| 板上 eth0 接口 | **J1**；从 RJ1 移到 J1 后 eth0 carrier 从 0 变为 1 |
| RJ1 | 插线时 eth0 carrier 为 0；本任务没有操作 eth1，也没有确认 RJ1 的驱动映射 |
| 电脑上游 | 有默认网关的无线网卡；公开日志别名 `<WAN-WIFI>` |
| 电脑下游 | 直连 J1 的有线网卡；公开日志别名 `<BOARD-ETHERNET>`；本轮链路 100 Mbps |
| ICS 活跃时电脑下游地址 | `192.168.137.1/24` |
| 板子本轮 DHCP 地址 | `192.168.137.178/24`，网关和 DNS 均为 `192.168.137.1` |
| 较早启动的 DHCP 地址 | `192.168.137.26/24`；不能继续当作当前地址 |
| 回滚后电脑下游地址 | `169.254.205.202/16`，DHCP/DNS 原配置恢复 |

板子可能在 ICS 关闭后仍显示旧租约。地址还在不代表网络可用。每次启动重新执行 `ip addr show eth0` 确认，不把本轮地址固定写入脚本。

## Windows ICS 的操作范围

先识别上、下游网卡，备份精确状态，启动独立回滚进程并确认心跳递增，再取得当次授权。保留主机当前代理、TUN、DNS、路由与防火墙。发现已有其他共享时停止，不替换它。

图形界面入口：控制面板 → 网络连接 → 上游无线网卡属性 → 共享 → 允许其他网络用户连接 → 家庭网络连接选择直连开发板的有线网卡。管理员 API 的对应角色是上游 `EnableSharing(0)`、下游 `EnableSharing(1)`。

本轮人在管理员 PowerShell 中启动本地备份/守护程序；核实心跳后才启用上述两项共享。连续三轮主机联网检查失败会自动关闭本轮共享并恢复下游配置。当前故障尚未解决，**不要直接按上述入口再次启用共享**；应由维护者确定后续排查任务。

只读检查命令：

```powershell
Get-NetAdapter
Get-NetIPConfiguration
Get-NetIPAddress -InterfaceAlias '<接板子的有线网卡名称>' -AddressFamily IPv4
```

## Buildroot 中的检查与 DHCP

```sh
ip link show eth0
cat /sys/class/net/eth0/carrier
ip addr show eth0
ip route
cat /etc/resolv.conf
ps | grep -E 'udhcpc|sshd' | grep -v grep
```

本镜像已有 eth0 的后台 `udhcpc` 和 `sshd`。本轮使用自动 DHCP，没有添加静态地址或另起 DHCP 客户端。若后续确认原客户端已经退出，可按任务单使用 `udhcpc -i eth0 -n -q`。

共享活跃的同步测试结果：

| 目标 | 结果 |
|---|---|
| `192.168.137.1` | 3 发 0 收；主机等待 8 秒后中断，板上报告退出码 1 |
| `8.8.8.8` | 3 发 3 收，0% 丢包，平均 55.472 ms |
| `github.com` | 解析到了 `198.18.1.137`，3 发 0 收；等待 8 秒后中断，退出码 1 |

域名返回的是 Fake-IP 范围地址，只能说明本次查询返回了地址，不能证明域名业务连通或 DNS 路径完整。网关不回应 ICMP 的原因未确认；本轮没有关闭防火墙或增加放行规则。

## SSH / SCP 脚本（实机验证待完成）

网络恢复后先在串口读取主机公钥指纹，再核对 SSH 首次连接提示；本轮已通过可信串口读取主机公钥，但没有完成 SSH 登录。不要跳过主机身份核验或关闭验证。

```sh
# 在板子串口中读取，供首次 SSH 提示核对
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

```powershell
# 在仓库根目录执行；替换为当次实际 DHCP 地址
$boardIp = '192.168.137.178'
./scripts/board_ssh.ps1 -BoardIP $boardIp -Command 'uname -a'
$LASTEXITCODE

./scripts/board_scp.ps1 -BoardIP $boardIp -LocalPath ./example.txt -RemotePath /tmp/example.txt
./scripts/board_scp.ps1 -BoardIP $boardIp -LocalPath ./received.txt -RemotePath /tmp/example.txt -Download
```

两个脚本调用 Windows 原生 OpenSSH，交互输入口令，返回原生退出码。可选 `-KnownHostsFile` 必须指向已有的可信 known_hosts 文件，此模式强制核验。SCP 使用 `-O` 兼容旧 SCP 协议；串口已确认板上有 `scp`，SFTP 子系统未验证。脚本仅完成 PowerShell 5.1/7 语法和参数拒绝检查，文件传输及远端退出码传递的实机结果仍未确认。

本轮没有生成或部署客户端认证密钥，也没有修改 sshd 配置。密码、认证交互和主机公钥未写入仓库。

## 校时

本轮两次 `ntpd` 均返回 `command not found`（127），采用任务单允许的电脑 UTC 回退方式：

```powershell
(Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')
```

在板上替换为刚取到的时间：

```sh
date -u -s '<电脑当前 UTC 时间>'
date -u
```

实测从 1970 年设为 `2026-11-08 03:05:29 UTC`，该时刻对应本机 11 月 7 日晚间。没有设置 RTC；重启后是否保时未验证，每次启动都应检查。

## Ubuntu 软件源与 apt（本轮未执行）

当前共享已回滚，板子没有可用的电脑网关；本轮未进入 Ubuntu、未运行 `apt-get update`，也未安装软件。实际软件源内容未确认，不推断为默认源。

后续网络和时间验证通过后，按任务单继续：

```sh
sh /mount_emmc.sh start
# 以下在 Ubuntu chroot 中
date -u
cat /etc/resolv.conf
ping -c 3 ports.ubuntu.com
cat /etc/apt/sources.list.d/*.sources /etc/apt/sources.list 2>/dev/null
apt-get update
# 获得当次安装批准后才执行：apt-get install -y git ca-certificates
# git --version
exit
# 回到 Buildroot
sh /mount_emmc.sh stop
sh /mount_emmc.sh status
```

不执行 apt upgrade，不擅自更换源。Ubuntu chroot 使用正在运行的 Buildroot 内核、网络和时钟；进入 chroot 本身不能修复 ICS 故障。本轮最终检查为 `Ubuntu root is not mounted`，并确认 `/mnt/ubuntu`、`/mnt/emmc_ro` 及其子挂载全部不存在。

## 重启后检查清单

1. 维持伺服动力电断开，接主电后按维护者确认的临时方法短按 RESET；J1 接电脑有线口。
2. 重新枚举串口并登录 Buildroot，检查 eth0 carrier、DHCP 地址、路由和 DNS。
3. 重新核对主机共享状态；本轮收尾时 ICS 关闭，不应假设 Windows 仍在共享。
4. 校验主机与板子联网、SSH 主机身份及板上时钟。本轮没有部署认证公钥；以后若在内存 rootfs 中部署，重启后需重新安装公钥。
5. 使用 Ubuntu 时重新 start；使用结束后 exit、stop，并核对全部卸载。
