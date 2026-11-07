# 任务 004：启动卡更新为 boot_1106 版本

- **对应阶段**：docs/PLAN.md 第 2 阶段（验证启动镜像）
- **作者**：Claude
- **日期**：2026-11-07
- **电机是否可能动作**：**否**。不加载 EtherCAT 模块，不运行控制程序。
- **前置条件**：任务 002、003 的成果（PR #2）可用：32 GB 的 `RVBOOT` 卡已做好，能启动；`scripts/serial_console.py`、`scripts/dropbox_content_hash.py` 可用。新建分支 `task-004-boot-1106`，基于 PR #2 的分支 `task-002-new-image-full-boot`，再合并上游 `handoff-protocol`（里面有本任务单和 `scripts/initrd_diff.py`）。PR 的目标分支是上游的 `handoff-protocol`。

## 背景

人要求把系统镜像更新成 `boot_1106` 版本。Dropbox 里有两份内容相同的拷贝：`/Workspace/RV/boot_1106.zip` 和解压好的文件夹 `/Workspace/RV/boot_1106/`。和现在卡上的版本（任务 002 验证过的 11-05 版）相比：

| 文件 | 大小（字节） | Dropbox content_hash | 和卡上现有版本相比 |
|---|---:|---|---|
| boot.scr | 719 | `4e6d99cfe01c1c2b4f3f4bdee2d8acf90c00854ad915478ad5b366cf6c7f24da` | 相同 |
| uImage.lz4 | 4,223,577 | `8ba0c95464d0507cb92ff57e8f949d10f0803d34b2f99855c0fe0fa145e59fdf` | 相同（内核不变） |
| kernel.dtb | 8,621 | `8abd45134a73698081794bf7b69b12833f6b9710955f6035ac67f5f14b93b502` | 相同（设备树不变） |
| **uInitrd.lz4** | **14,857,818** | `432868888c5f4a1e38b9f781f3c5bd52d62c50d97618d4cab61add7f21468ab9` | **不同**（原来是 14,856,105 字节） |
| boot_1106.zip | 16,864,742 | `8bcc0a0c200eea3b2a931c025815ec6ad678fe758001cfe3ff7325fecad237a3` | 压缩包 |

也就是说，这次**只有根文件系统（initramfs）变了**，内核和设备树都没变。所以除了换卡上的文件，本任务还要弄清楚 initramfs 里具体改了什么。

## 不要做的事

- 不加载 `.ko`，不运行 `load_ec_*.sh`、`ethercat`、`Trajectory_main`、`ec_*example*`。
- U-Boot 里不执行 `saveenv`、`setenv` 或任何写入命令。本任务不需要进 U-Boot。
- 卡上只动根目录的四个启动文件和新建的备份目录，其他内容不动。不格式化，不重新分区。
- 不动 eth1。
- 不把 initramfs 里的密码哈希、私钥写进日志或仓库（`initrd_diff.py` 默认不打印这些内容）。

## 步骤

### A. 准备源文件（Windows 主机）

1. 源文件优先用本机 Dropbox 同步目录里的 `Workspace\RV\boot_1106\`，即报告 002、003 用过的那个 `Workspace\RV`。确认四个文件都已下载到本地，不是“仅在线”的占位文件。
2. 校验：`python scripts/dropbox_content_hash.py <boot_1106 目录>\boot.scr <…>\uImage.lz4 <…>\uInitrd.lz4 <…>\kernel.dtb <Workspace\RV>\boot_1106.zip`，五项的大小和 content_hash 必须和上表全部一致。
3. 把 `boot_1106.zip` 解压到一个**仓库之外**的临时目录，确认里面四个文件的 SHA-256 和 `boot_1106\` 文件夹里的相同；同时确认三个不变文件的 SHA-256 和报告 002 记录的一致（`boot.scr` 是 `06203ccf…`，`uImage.lz4` 是 `b3f0662b…`，`kernel.dtb` 是 `3b84109e…`）。zip 里的目录结构或文件名不一样的话，照实记录，以文件夹里的版本为准。
4. 输出存到 `logs/20261107-004-source.log`。

### B. initramfs 对比（只在主机上做，不碰板子）

5. 旧版就用 Dropbox `Workspace\RV\boot\uInitrd.lz4`，也就是 11-05 版，content_hash 是 `66c8ab49…`，和卡上现有的相同：
   ```powershell
   python scripts/initrd_diff.py <Workspace\RV>\boot\uInitrd.lz4 <boot_1106 目录>\uInitrd.lz4 > logs\20261107-004-initrd-diff.log
   ```
6. 对每个**有变化的文本文件**（`etc/` 下的配置、`init`、`etc/init.d/*` 一类的脚本），运行 `--show <路径>` 查看具体差异，追加到同一个日志。被标为 `secret` 的文件只记录“有变化”，**不要**想办法查看内容。
7. 用一两句话总结这次改了什么，比如：新增了 `/lib/modules`、改了启动脚本、换了某个程序。写进报告。脚本解不开镜像（不是 LZ4 或 cpio 格式）的话，记录报错，跳过 B 节继续。

### C. 换卡上的文件

8. **[需人工]** 请人：给开发板断电，取出 `RVBOOT` 卡，插到主机的读卡器上。
9. 找到卷标是 `RVBOOT`、文件系统是 FAT32、大小约 29.7 GiB 的卷，记下盘符 `X:`。如果找到的卷不止一个，或者一个都对不上，就停下来问人。先列一下根目录，确认四个启动文件都在。
10. 备份：建 `X:\backup-20261107\`，把根目录现有的四个启动文件复制进去（目录已经存在就停下来问人）。用 `dropbox_content_hash.py` 确认备份和报告 002 里的 SHA-256 表一致。
11. 把 `boot_1106\` 里的四个文件复制到 `X:\` 根目录覆盖旧文件，然后回读卡上四个文件：大小和 content_hash 要和上表一致，记下 SHA-256。
12. 弹出卡，确认盘符消失。第 9–12 步的输出存到 `logs/20261107-004-card-update.log`。

### D. 冷启动验证

13. **[需人工]** 请人把卡插回**断电状态**的开发板。确认 COM3 存在，开始 `capture`：115200，超时 300 秒，结束正则 `login:`，开启自动重连（任务 002 用过的方式），日志写到 `logs/20261107-004-boot.log`。然后请人上电。
14. 检查启动日志：
    - `fatload` 读到的 ramdisk 字节数应该是 **14,857,818**，另外两个仍是 4,223,577 和 8,621；
    - 内核版本行应该和任务 002 一样（`#6 SMP PREEMPT_RT Thu Nov 5 09:57:02 CST 2026`）；
    - 任务 002 里出现过的 `modprobe: can't change directory to '/lib/modules'` 这次还有没有；
    - 有没有新出现的报错或启动卡住。
15. **[需人工]** 登录。凭据由人输入，不要记进日志。如果登录方式变了（例如密码不同），照实记录，向人要新的凭据，**不要猜测**。
16. 执行下面的命令，输出存到 `logs/20261107-004-board-info.log`：
    ```sh
    cat /proc/version
    cat /etc/os-release 2>/dev/null; cat /etc/*-release 2>/dev/null | head -20
    cat /sys/devices/system/cpu/online
    ls -la /lib/modules 2>&1 | head
    ps
    ls /etc/init.d/
    ip link show
    mount -o ro /dev/mmcblk0p1 /media && sha256sum /media/boot.scr /media/uImage.lz4 /media/uInitrd.lz4 /media/kernel.dtb; umount /media
    dmesg | grep -iE "error|fail|warn" | head -50
    ```
    TF 卡设备名以 `ls /dev/mmcblk*` 为准，用任务 002 的方法区分 TF 卡和 eMMC。卡上四个文件的 SHA-256 必须和第 11 步记下的一致。
17. 根据 B 节的对比结果，挑两三处变化在板子上核实一下。比如新增了某个文件，就确认它在板上存在；改了某个启动脚本，就看启动日志里有没有对应的效果。

### E. 整理

18. 更新 `docs/BOARD.md`：当前镜像版本为 boot_1106，四个文件的哈希，以及 initramfs 的变化摘要。
19. 写报告 `handoff/reports/004-update-to-boot-1106.md`，在 `handoff/STATUS.md` 里加上 004 这一行，然后发 PR。

## 失败时怎么办

| 现象 | 处理 |
|---|---|
| 源文件哈希对不上，或者 zip 和文件夹不一致 | 停下，报告实际的值，不要换卡上的文件 |
| 找不到 `RVBOOT` 卷，或者找到不止一个 | 停下问人 |
| 新版起不来，或者卡在某处 | 保存日志。**[需人工]** 请人把卡插回主机，把 `backup-20261107\` 里的四个文件复制回根目录（只有 `uInitrd.lz4` 不同，所以恢复这一个也可以），确认能恢复启动，状态标为 `failed` |
| 能启动，但登录方式变了 | 记录现象，向人要凭据。拿不到就把状态标为 `blocked`，已采集到的启动日志照常提交 |

## 需要回答的问题

1. 五个源文件（四个启动文件和 zip）的哈希是否全部一致？zip 和文件夹的内容是否相同？
2. initramfs 改了什么？列出新增、删除、修改的条目数，以及关键文本文件的变化摘要。
3. 卡上备份和换上的新文件，哈希是否都正确？
4. 新版能否冷启动到登录？ramdisk 读到了多少字节？
5. `/lib/modules` 的报错还在不在？登录方式有没有变？
6. 在板子上核实了 B 节里的哪几处变化，结果如何？
7. 有没有新出现的报错？CPU2–7 的情况有没有变化？
