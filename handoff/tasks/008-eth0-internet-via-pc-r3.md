# 任务 008-r3：用 SSH 反向隧道借用 Clash 代理（不开 Allow LAN，不碰防火墙）

- **替代**：008-r2 的 A3、A4 两节（Clash 的 Allow LAN 和防火墙规则）。r2 里已经验证通过的部分（固定 IP、`board_bootstrap.ps1`、SSH、`board_ssh.ps1`、`board_scp.ps1`）照常使用。
- **作者**：Claude
- **日期**：2026-11-08
- **电机是否可能动作**：**否**
- **前置条件**：在 `task-008-eth0-network` 分支上继续，先合并上游 `handoff-protocol`，结果推到 PR #5。

## r2 失败的原因（Claude 的判断）

固定 IP 阶段一切正常，电脑上网也没受影响。出问题的是防火墙这一步：r2 **停用了 Clash 自己的三条入站规则**。Clash 的 TUN 模式要靠这些规则接收回程流量，规则一停，电脑的 HTTPS 自然就断了。新加的那条窄规则本身不会造成这个问题。

问题出在我的方案上：Clash 原有的规则允许任意来源访问，所以只要打开 Allow LAN，代理就会对 Wi-Fi 上的其他设备开放，“只放行开发板”在不改动这些规则的前提下做不到。Codex 为了满足这个要求，才去停用旧规则。

## 新方案：SSH 反向隧道

代理继续**只监听电脑的 127.0.0.1**，Clash 和防火墙都不动。电脑通过 SSH 登录开发板时带上 `-R` 参数，把开发板上的 `127.0.0.1:7897` 转发回电脑的 `127.0.0.1:7897`：

```
开发板程序 → 开发板 127.0.0.1:7897 → (SSH 隧道，走 192.168.50.0/24) → 电脑 127.0.0.1:7897 → Clash → 外网
```

- 不需要打开 Allow LAN，不需要新增或停用任何防火墙规则，不需要 ICS。
- 代理只对开发板开放，而且只在 SSH 隧道连着的时候可用。
- eMMC 上 Ubuntu 的 chroot 和 Buildroot 共用同一个网络，所以在 chroot 里也能用 `127.0.0.1:7897`。

## 不要做的事

- **不改 Clash 的任何设置**（包括 Allow LAN、TUN、端口），**不新增、停用或删除任何防火墙规则**，不启用 ICS。
- 电脑上只允许做一项网络改动：给直连开发板的有线网卡配 `192.168.50.1/24`（不设网关和 DNS）。这一项在 r2 里已经验证过不影响电脑上网。
- 不改开发板的 `sshd_config`。不碰 eth1。
- Ubuntu 里只装 `git` 和 `ca-certificates`，并且要人当次同意。不执行 `apt upgrade`，不换软件源，不把代理写进配置文件。

## 步骤

### A. 恢复固定 IP 直连

1. **[需人工]** 请人同意后，按 r2 第 2 步再给有线网卡配一次 `192.168.50.1/24`，包括事前备份、配置后检查电脑上网、失败就回滚。日志写到 `logs/20261108-008r3-host.log`。
2. 确认开发板已经开机、登录，并且已经释放串口，然后执行 `board_bootstrap.ps1 -Port COM3`，完成开发板的 IP 配置和校时。开发板如果重启过，需要先登录。
3. 用 `board_ssh.ps1` 执行 `uname -a; date -u`，确认 SSH 可用。

### B. 建立反向隧道

4. 检查开发板 sshd 是否允许端口转发（只读查看）：
   ```sh
   grep -iE '^\s*(AllowTcpForwarding|GatewayPorts|PermitOpen|DisableForwarding)' /etc/ssh/sshd_config || echo "using defaults"
   ```
   OpenSSH 默认允许 TCP 转发。如果配置里明确写了 `AllowTcpForwarding no`，就停下汇报，**不要改配置**。
5. 在电脑上新开一个 PowerShell 窗口或后台进程，保持连接，执行：
   ```powershell
   ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 `
       -o UserKnownHostsFile=<r2 用的专用 known_hosts> `
       -R 127.0.0.1:7897:127.0.0.1:7897 root@192.168.50.2
   ```
   密码由人输入，或者用 r2 的方式输入，不写进日志。端口以 r2 确认的 mixed-port 为准，当时是 7897。这里**绑定到开发板的 127.0.0.1**，所以开发板上的其他网卡上不会出现这个端口。
6. 在开发板上确认隧道已经建立：
   ```sh
   netstat -tln 2>/dev/null | grep 7897 || ss -tln 2>/dev/null | grep 7897
   ```
   应该看到 `127.0.0.1:7897` 处于监听状态。

### C. 通过隧道访问外网

7. 在开发板的 Buildroot 里：
   ```sh
   export http_proxy=http://127.0.0.1:7897
   wget -q -O - http://ports.ubuntu.com/ubuntu-ports/dists/noble/Release 2>&1 | head -5
   ```
8. 进入 Ubuntu（`sh /mount_emmc.sh start`）：
   ```sh
   date
   cat /etc/apt/sources.list.d/*.sources /etc/apt/sources.list 2>/dev/null | grep -vE '^\s*#' | grep -v '^$'
   P=http://127.0.0.1:7897
   apt-get -o Acquire::http::Proxy=$P -o Acquire::https::Proxy=$P update
   ```
9. **[需人工]** 请人当次同意后，再执行：
   ```sh
   apt-get -o Acquire::http::Proxy=$P -o Acquire::https::Proxy=$P install -y git ca-certificates
   git --version
   git -c http.proxy=$P ls-remote https://github.com/Nuclei-Software/nuclei-linux-sdk HEAD
   ```
10. `exit`，然后执行 `sh /mount_emmc.sh stop`，确认已经全部卸载。

### D. 收尾和工具

11. 关闭隧道：结束第 5 步的 ssh 进程。在开发板上确认 7897 端口已经不再监听。
12. 新增 `scripts/board_proxy_tunnel.ps1`：参数是开发板 IP 和代理端口（默认 7897），作用是建立第 5 步的隧道，并在终端里提示“按 Ctrl+C 关闭”。不能包含密码。
13. 更新 `docs/NETWORK.md`：
    - 删掉 Allow LAN 和防火墙规则的部分，改成 SSH 隧道方案；
    - “每次开机后”的步骤：先执行 `board_bootstrap.ps1`，需要上网时再执行 `board_proxy_tunnel.ps1`；
    - apt 和 git 的代理参数统一写成 `http://127.0.0.1:7897`；
    - 电脑端唯一的改动（有线网卡固定 IP）怎么撤销。
14. 更新报告 008：新增一节“r3 执行记录”，逐条回答下面的问题，`STATUS.md` 改成实际结果，推到 PR #5。固定 IP 这次**保留**，不用回滚，除非电脑上网出了问题。

## 失败时怎么办

| 现象 | 处理 |
|---|---|
| 配固定 IP 后电脑上网异常 | 按 r2 回滚，标为 `blocked`。r2 里这一步是正常的，如果这次出问题，要对比两次的差异 |
| `ssh -R` 报 `remote port forwarding failed` | 记录开发板 `sshd_config` 的相关行和 ssh 的 `-v` 输出（打码），汇报。不要改 sshd 配置 |
| 隧道建立了，但 wget 或 apt 连不上 | 在电脑上执行 `Test-NetConnection 127.0.0.1 -Port 7897`，确认 Clash 正在监听。记录后汇报，不要改 Clash |
| apt 报证书或时间错误 | 用 `board_ssh.ps1` 重新校时，然后再试一次 |

## 需要回答的问题

1. 固定 IP 恢复后，电脑自己的网络是否正常？
2. 反向隧道能否建立？开发板上 `127.0.0.1:7897` 是否在监听？
3. 通过隧道，`wget`、`apt-get update`、`git ls-remote` 的结果分别是什么？
4. git 装上了吗？版本是多少？
5. 以后每次需要开发板上网时，按什么顺序执行哪几条命令？
