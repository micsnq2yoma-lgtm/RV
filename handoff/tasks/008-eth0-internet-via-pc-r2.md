# 任务 008-r2：eth0 直连电脑（固定 IP），通过 Clash 代理上网

- **替代**：`008-eth0-internet-via-pc.md` 中的 ICS 方案（A3 节）。原任务单里已经完成的部分（J1=eth0 的确认、`board_ssh.ps1`、`board_scp.ps1`、`docs/NETWORK.md`）在本任务里接着用。
- **作者**：Claude
- **日期**：2026-11-08
- **电机是否可能动作**：**否**
- **前置条件**：在 PR #5 的分支 `task-008-eth0-network` 上继续工作，先合并上游 `handoff-protocol`。结果推到 PR #5。

## 为什么改方案

报告 008 显示，电脑开着 Clash，用的是 TUN 模式和 Fake-IP（`github.com` 被解析成 `198.18.1.137`）。开启 Windows ICS 后，电脑自己的 HTTPS 访问失败了，Codex 回滚后才恢复。ICS 和 Clash 的 TUN 模式经常冲突。

**人的决定（2026-11-08）**：不再使用 ICS。改为下面的方式：
- 电脑的有线网卡和开发板 eth0 各配一个**固定 IP**，组成一个只有两台机器的小网段，用来跑 SSH 和 SCP；
- 开发板要访问外网时（apt、git），走**电脑上 Clash 的 HTTP 代理**。为此人需要在 Clash 里打开“允许局域网连接”（Allow LAN），并在防火墙里**只对开发板的 IP** 放行代理端口。

## 地址规划

| 设备 | 接口 | 地址 |
|---|---|---|
| 电脑 | 直连开发板的有线网卡 | `192.168.50.1/24`，**不设网关，不设 DNS** |
| 开发板 | eth0（J1 口） | `192.168.50.2/24` |

这个网段不能和电脑现有的任何网段重叠。第 1 步核对时如果发现 `192.168.50.0/24` 已经有人在用，就换成 `192.168.77.0/24`，并在报告里说明。

## 不要做的事

- 不再启用 ICS。
- 不改电脑上网的那块网卡（无线），不改 Clash 的 TUN、DNS、规则和订阅，不关防火墙。Clash 里**只**由人打开 Allow LAN 这一项。
- 防火墙只加一条入站规则：只允许来自 `192.168.50.2` 的连接访问 Clash 代理端口。不开放其他端口，也不开放给其他地址。
- 不碰 eth1，不加载 EtherCAT 模块。
- Ubuntu 里只装 `git` 和 `ca-certificates`，而且要人当次同意；不执行 `apt upgrade`，不换软件源。

## 步骤

### A. 电脑端

1. 只读核对，输出追加到 `logs/20261108-008r2-host.log`。日志里打码 MAC、无线网卡名和外网地址：
   ```powershell
   Get-NetAdapter | Format-Table -AutoSize Name, InterfaceDescription, Status
   Get-NetIPAddress -AddressFamily IPv4 | Format-Table -AutoSize InterfaceAlias, IPAddress, PrefixLength, PrefixOrigin
   Get-NetRoute -AddressFamily IPv4 | Where-Object DestinationPrefix -like '192.168.*' | Format-Table -AutoSize
   ```
   确认 ICS 仍然是关闭的，直连开发板的有线网卡处于 `Up`。
2. **[需人工]** 请人同意后，以管理员身份给这块有线网卡配置固定 IP（需要人批准 UAC）：
   ```powershell
   $if = '<直连开发板的有线网卡名>'
   Set-NetIPInterface -InterfaceAlias $if -Dhcp Disabled
   New-NetIPAddress -InterfaceAlias $if -IPAddress 192.168.50.1 -PrefixLength 24
   Get-NetIPAddress -InterfaceAlias $if -AddressFamily IPv4
   ```
   配完立刻检查电脑自己能不能正常上网（用报告 008 里的方法，打开两三个 HTTPS 网站）。一旦失败，马上回滚：
   ```powershell
   Remove-NetIPAddress -InterfaceAlias $if -IPAddress 192.168.50.1 -Confirm:$false
   Set-NetIPInterface -InterfaceAlias $if -Dhcp Enabled
   ```
   回滚后标为 `blocked` 并汇报。
3. **[需人工]** 请人在 Clash 里：
   - 打开“允许局域网连接”（Allow LAN）；
   - 告诉 Codex 代理端口号：一般叫 mixed-port 或 HTTP 端口，常见的是 7890，Clash Verge 默认是 7897。
   - 如果 Windows 弹出防火墙提示，请人**不要**点“允许所有网络”，直接关掉提示，由下一步的规则来放行。
4. **[需人工]** 请人同意后，以管理员身份添加一条只放行开发板的防火墙规则：
   ```powershell
   New-NetFirewallRule -DisplayName 'RV board to Clash proxy' -Direction Inbound -Action Allow `
     -Protocol TCP -LocalPort <端口> -RemoteAddress 192.168.50.2 -LocalAddress 192.168.50.1
   ```
   在报告里记下规则名，以后要删时执行：`Remove-NetFirewallRule -DisplayName 'RV board to Clash proxy'`。
   然后再检查一遍电脑自己上网是否正常。

### B. 开发板端

5. 启动并登录（上电后按一次 RESET），或者直接用已经开着的板子。在串口上执行，输出写到 `logs/20261108-008r2-board.log`：
   ```sh
   cat /sys/class/net/eth0/carrier
   ip addr add 192.168.50.2/24 dev eth0
   ip link set eth0 up
   ip addr show eth0; ip route
   ping -c 3 192.168.50.1
   ```
   板子上可能还留着上次 ICS 分到的 `192.168.137.178` 地址，以及指向 `192.168.137.1` 的默认路由，那个网关已经不存在了。用 `ip route del default` 删掉这条默认路由，避免干扰；这个旧地址留着也没关系。以上设置都在内存里，重启就没了。
   > 如果电脑 ping 不通开发板，或者开发板 ping 不通电脑：Windows 防火墙默认会挡住 ICMP，这不影响 SSH。直接进入第 6 步试 SSH。

### C. SSH 和 SCP

6. 在电脑上执行：`ssh root@192.168.50.2 "uname -a"`。**[需人工]** 由人输入密码，或者人同意后由 Codex 输入，密码不写进日志。第一次连接时的主机指纹，要和串口上 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` 的输出核对一致（如果这个文件存在）。
7. 用 `scripts/board_ssh.ps1` 执行 `uname -a`，确认能拿到输出和退出码；再执行一条会失败的命令（例如 `false`），确认退出码能正确传回 1。
8. 用 `scripts/board_scp.ps1` 往板子的 `/tmp/` 传一个测试文件，再传回来，比较前后的 SHA-256。

### D. 校时

9. 开发板没有 ntpd，所以用电脑的时间：先在电脑上取 `(Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')`，再在开发板上执行 `date -u -s "<这个时间>"`，读回确认。最好写成一条命令，用 `board_ssh.ps1` 一步完成。

### E. 通过代理访问外网

10. 在开发板的 Buildroot 里先测一下 HTTP 代理：
    ```sh
    export http_proxy=http://192.168.50.1:<端口>
    wget -q -O - http://ports.ubuntu.com/ubuntu-ports/dists/noble/Release 2>&1 | head -5
    ```
    能看到 `Origin: Ubuntu` 之类的内容，就说明代理能用。BusyBox 的 wget 可能不支持 HTTPS 代理，这一步只测 HTTP。
11. 进入 Ubuntu：`sh /mount_emmc.sh start`，然后执行：
    ```sh
    date
    cat /etc/apt/sources.list.d/*.sources /etc/apt/sources.list 2>/dev/null | grep -vE '^\s*#' | grep -v '^$'
    P=http://192.168.50.1:<端口>
    apt-get -o Acquire::http::Proxy=$P -o Acquire::https::Proxy=$P update
    ```
    **不要**把代理写进 Ubuntu 的配置文件，每次都通过 `-o` 参数传入。
12. **[需人工]** 请人当次同意后，再执行：
    ```sh
    apt-get -o Acquire::http::Proxy=$P -o Acquire::https::Proxy=$P install -y git ca-certificates
    git --version
    git -c http.proxy=$P ls-remote https://github.com/Nuclei-Software/nuclei-linux-sdk HEAD
    ```
    最后一条用来验证 git 能通过代理访问 GitHub。
13. `exit` 退出 Ubuntu，然后执行 `sh /mount_emmc.sh stop`，确认已经全部卸载。

### F. 整理

14. 更新 `docs/NETWORK.md`：去掉 ICS 方案，改成“固定 IP + Clash 代理”方案。写清楚：
    - 电脑端一次性设置：固定 IP、Clash 的 Allow LAN、防火墙规则，以及三项各自怎么撤销；
    - 开发板**每次开机后**要执行的命令：配 IP、校时、需要时设置代理；
    - SSH、SCP 和两个脚本的用法；
    - apt 和 git 怎么带代理参数。
15. 新增 `scripts/board_net_up.sh`（POSIX sh，在开发板上运行）：配置 `192.168.50.2/24`，删除失效的默认路由，打印 `ip addr`；可以接受一个参数作为 UTC 时间，用来设置日期。新增 `scripts/board_bootstrap.ps1`（在电脑上运行）：通过串口调用 `board_net_up.sh` 里的同样步骤，并把电脑当前的 UTC 时间传过去。这样每次开机后，电脑执行一条命令就能让开发板网络就绪。
16. 更新报告 008：保留原来的 ICS 记录，新增一节“r2 执行记录”，逐条回答下面的问题。`STATUS.md` 里 008 的状态改成实际结果，推到 PR #5。

## 失败时怎么办

| 现象 | 处理 |
|---|---|
| 配固定 IP 或加防火墙规则后，电脑自己上不了网 | 立刻按第 2 步回滚，删掉防火墙规则，标为 `blocked` |
| SSH 连不上 | 在串口上检查 `ps | grep sshd`，以及 `netstat -tln 2>/dev/null | grep :22`，记录下来。不要改 sshd 的配置 |
| 代理不通（连接被拒绝或超时） | 确认人已经打开 Allow LAN、端口号没错、防火墙规则的端口和地址正确。还是不通就停下汇报，**不要**放宽防火墙规则 |
| apt 报证书或时间错误 | 重新校时后再试一次 |

## 需要回答的问题

1. 电脑有线网卡和开发板分别用了什么 IP？配置之后，电脑自己的网络是否正常？
2. Clash 的代理端口是多少？防火墙规则叫什么名字？
3. SSH、`board_ssh.ps1`（包括退出码）、`board_scp.ps1`（包括哈希比较）是否都正常？
4. 通过代理，`wget`、`apt-get update`、`git ls-remote` 的结果分别是什么？
5. git 装上了吗？版本是多少？
6. 每次开机后，执行哪一条命令能让开发板网络就绪？
