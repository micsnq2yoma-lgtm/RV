# 任务 008：eth0 直连 Windows 电脑，借电脑上网，打通 SSH

- **对应阶段**：docs/PLAN.md 第 1 阶段（部署通道）
- **作者**：Claude
- **日期**：2026-11-07
- **电机是否可能动作**：**否**
- **前置条件**：卡上是 boot_1106。分支 `task-008-eth0-network`，基于 `task-007-emmc-ubuntu`，再合并上游 `handoff-protocol`。
- **参考**：芯来官方 Linux SDK https://github.com/Nuclei-Software/nuclei-linux-sdk （本板的 Buildroot、OpenSBI、U-Boot 都基于它）

## 目标

人要求：开发板的 **eth0** 用网线直连 Windows 电脑，由电脑共享自己的网络给开发板上网。完成后：

1. 电脑能用 SSH/SCP 登录开发板（以后部署文件不用再拔卡）；
2. 开发板能访问互联网，eMMC 上的 Ubuntu 能用 `apt`。

## 已知情况

- 报告 002：boot_1106 启动时会自动运行 `udhcpc`，并启动 `sshd`；`sshd_config` 里设了 `PermitRootLogin yes`（报告 004）。
- 板子的时钟停在 1970 年（报告 001）。**时钟不对的话，apt 和 HTTPS 都会因为证书或签名“尚未生效”而失败**，所以联网后要先校时。
- eth1 留给 EtherCAT，本任务不碰。

## 不要做的事

- 不碰 eth1，不加载 EtherCAT 模块。
- 电脑上：只启用“Internet 连接共享”（ICS），并且只在人同意之后。不关闭防火墙，不改电脑上网用的那块网卡的其他设置。
- 不把 IP 以外的网络信息写进公开仓库：MAC、电脑名、外网 IP、Wi-Fi 名称都要打码。密码不写。
- 在 Ubuntu 里只装本任务允许的软件（第 12 步）。不执行 `apt upgrade`。

## 步骤

### A. 电脑端准备（Windows）

1. 列出电脑的网卡，输出存到 `logs/20261107-008-host-net.log`（MAC 打码）：
   ```powershell
   Get-NetAdapter | Format-Table -AutoSize Name, InterfaceDescription, Status, LinkSpeed
   Get-NetIPConfiguration | Format-List InterfaceAlias, IPv4Address, IPv4DefaultGateway, DNSServer
   ```
   找出两块网卡：**上网的那块**（Wi-Fi 或有线，有默认网关），以及**接开发板的那块**（有线网卡）。
2. **[需人工]** 请人用网线把开发板的 **eth0** 口接到电脑的有线网口。开发板上哪个口是 eth0、哪个是 eth1，如果不确定，就先问人。然后再执行一次 `Get-NetAdapter`，确认接开发板的那块网卡变成了 `Up`。
3. **[需人工]** 请人同意在电脑上启用 ICS。同意后，由人或者 Codex 操作，两种方式选一种：
   - **图形界面**（推荐由人操作）：控制面板 → 网络连接 → 右键“上网的那块网卡” → 属性 → 共享 → 勾选“允许其他网络用户通过此计算机的 Internet 连接来连接”，在“家庭网络连接”里选“接开发板的那块网卡” → 确定。
   - **PowerShell**（管理员权限，需要人批准 UAC）：
     ```powershell
     $m = New-Object -ComObject HNetCfg.HNetShare
     $all = @($m.EnumEveryConnection) | ForEach-Object { [pscustomobject]@{ Conn=$_; Props=$m.NetConnectionProps($_) } }
     $all | ForEach-Object { $_.Props.Name }   # 先列出名字，和第 1 步对照
     $pub  = ($all | Where-Object { $_.Props.Name -eq '<上网网卡名>' }).Conn
     $priv = ($all | Where-Object { $_.Props.Name -eq '<接开发板的网卡名>' }).Conn
     $m.INetSharingConfigurationForINetConnection($pub).EnableSharing(0)
     $m.INetSharingConfigurationForINetConnection($priv).EnableSharing(1)
     ```
   启用后，接开发板的那块网卡会变成 `192.168.137.1/24`，Windows 会在这个网段上提供 DHCP 和 DNS。用 `Get-NetIPAddress -InterfaceAlias '<接开发板的网卡名>'` 确认。

### B. 开发板拿到地址

4. 启动并登录开发板（上电后按一次 RESET）。如果板子已经开着，就直接用。以下输出存到 `logs/20261107-008-board-net.log`：
   ```sh
   ip link show eth0; cat /sys/class/net/eth0/carrier
   ip addr show eth0; ip route
   cat /etc/resolv.conf
   ps | grep -E "udhcpc|sshd" | grep -v grep
   ```
5. 如果 eth0 还没有 `192.168.137.x` 的地址（例如插网线前 udhcpc 已经放弃了），就手动请求一次：
   ```sh
   udhcpc -i eth0 -n -q
   ip addr show eth0; ip route; cat /etc/resolv.conf
   ```
   还是拿不到地址的话，可以先配一个临时静态地址：`ip addr add 192.168.137.50/24 dev eth0; ip link set eth0 up; ip route add default via 192.168.137.1; echo nameserver 192.168.137.1 > /etc/resolv.conf`。这些设置都在内存里，重启就没了。

### C. 连通性和 SSH

6. 在板子上执行：`ping -c 3 192.168.137.1`、`ping -c 3 8.8.8.8`、`ping -c 3 github.com`，分别检查到电脑、到外网 IP、到域名（DNS）是否通。
7. 在电脑上执行：`ping <板子 IP>`；然后 `ssh root@<板子 IP>` 试登录，**[需人工]** 由人输入密码，或者人同意后由 Codex 输入（密码不写进日志）。登录成功后执行一次 `uname -a; exit`。
8. 写 `scripts/board_ssh.ps1`：参数是板子 IP 和要执行的命令，用 `ssh` 在板子上执行，返回输出和退出码。再写 `scripts/board_scp.ps1`，用来传文件。**不要**把密码写进脚本。如果人同意，可以改用 SSH 密钥：在电脑上生成一对密钥，把公钥追加到板子的 `/root/.ssh/authorized_keys`。注意：板子的根文件系统在内存里，**重启后公钥就没了**，所以要在报告里说明，并给出以后重新部署公钥的办法（例如放在 TF 卡上，登录后执行一条命令装回去）。

### D. 校时

9. 在板子上：
   ```sh
   date
   ntpd -n -q -p pool.ntp.org 2>&1 || ntpd -n -q -p ntp.aliyun.com 2>&1
   date
   ```
   如果 ntpd 不可用，或者 NTP 被挡住了，就用电脑的时间手动设置：先在电脑上取 UTC 时间（`(Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')`），再在板子上执行 `date -u -s "<这个时间>"`。确认 `date` 显示的是当前时间。

### E. Ubuntu 联网

10. 进入 eMMC 上的 Ubuntu：`sh /mount_emmc.sh start`。脚本会把板子的 `/etc/resolv.conf` 复制进去，所以 DNS 应该直接可用。
11. 在 Ubuntu 里：
    ```sh
    date
    cat /etc/resolv.conf
    ping -c 3 ports.ubuntu.com
    apt-get update
    ```
    `apt-get update` 成功后，记录用的是哪个软件源（`cat /etc/apt/sources.list.d/*.sources /etc/apt/sources.list 2>/dev/null`）。
12. **[需人工]** 请人同意后，只安装这两个包：
    ```sh
    apt-get install -y git ca-certificates
    git --version
    ```
    这一步会往 eMMC 写入数据，所以必须先征得人同意。
13. `exit` 退出 Ubuntu，然后执行 `sh /mount_emmc.sh stop`，确认已经卸载干净。

### F. 整理

14. 新建 `docs/NETWORK.md`，内容包括：接线（哪个口是 eth0）、ICS 怎么开、板子拿到的 IP、SSH 和 SCP 的用法、校时方法、Ubuntu 的软件源和 apt 用法，以及“重启后需要重新做哪些事”的清单。
15. 写报告 `handoff/reports/008-eth0-internet-via-pc.md`，更新 `STATUS.md`，发 PR。

## 失败时怎么办

| 现象 | 处理 |
|---|---|
| eth0 的 `carrier` 一直是 0 | **[需人工]** 请人检查网线、确认插的是不是 eth0 口，或者换一根线。都不行就标为 `blocked` |
| ICS 启用失败（例如提示网卡已经在共享） | 停下，把错误告诉人。**不要**取消电脑上已有的其他共享设置 |
| 拿到了 IP，但 `ping 8.8.8.8` 不通 | 检查 ICS 是否勾选在了正确的网卡上，检查电脑本身能不能上网。都正常还是不通，记录后标为 `blocked` |
| SSH 被拒绝 | 记录错误信息。不要修改板子的 sshd 配置，汇报 |
| `apt-get update` 报证书或时间错误 | 回到 D 节重新校时，然后再试一次 |
| apt 下载太慢、超时 | 记录下来。**不要**擅自更换软件源，汇报后由人决定是否换成国内镜像 |

## 需要回答的问题

1. 电脑上哪块网卡用来上网，哪块接开发板？ICS 是怎么启用的？
2. 板子的 eth0 拿到了什么 IP？是 DHCP 自动分配的还是手动配的？
3. 板子到电脑、到外网 IP、到域名，三项 ping 的结果分别是什么？
4. 电脑能否 SSH 和 SCP 到板子？`board_ssh.ps1` 能不能用？
5. 校时用的是什么方法？
6. Ubuntu 的 `apt-get update` 能否成功？git 装上了吗？
7. 板子重启之后，哪些设置需要重新做？
