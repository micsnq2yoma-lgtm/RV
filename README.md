# RV

RISC-V 开发板（Nuclei 平台）的 TF 卡启动镜像、EtherCAT 主站和机械臂轨迹控制程序。
文件来自 Dropbox `/Workspace/RV`，其中 `TF卡镜像/` 改名为 `tf-card/`，换成纯 ASCII 路径，方便在板子的 shell 里使用。

后续的开发和调试交给 Codex 在开发板上执行，由 Claude 写任务单、审阅结果。规则见 [`AGENTS.md`](AGENTS.md)，分阶段计划见 [`docs/PLAN.md`](docs/PLAN.md)，双方的交互协议和任务进度见 [`handoff/`](handoff/README.md)。

## 目录结构

| 路径 | 内容 |
|---|---|
| `boot/` | 最新的启动文件（2026-11-05 编译）：`uImage.lz4`、`uInitrd.lz4`、`kernel.dtb`、`boot.scr` |
| `boot.zip` | 和 `boot/` 对应的压缩包 |
| `tf-card/` 根目录 | 当前烧卡用的启动文件，已更新成和 `boot/` 一致 |
| `tf-card/img/`、`tf-card/old/` | 两套更早的启动镜像 |
| `tf-card/rpmsg/` | 带 rpmsg 核间通信的镜像，附 `test_rpmsg` |
| `tf-card/ecat/` | EtherCAT 主站：内核模块 `ko/`、`ethercat` 工具、库、配置、加载脚本，以及各种场景下的 `Trajectory_main` 和 `libecatmain.so` |
| `tf-card/ecat_newchip/`、`tf-card/ecat_newchip.zip` | 新芯片版本的 EtherCAT 主站，比 `ecat/` 多一个 `ko_newchip/` |
| `tf-card/test/`、`tf-card/test_play/` | 参数测试版程序和运行日志 |
| `tf-card/jhkdl/`、`tf-card/jhkdl0911/` | 运动学库 `libjhkdl` 及测试程序（如 `test_ur10`） |
| `MANIFEST.tsv` | 全部 157 个文件的路径和大小，共约 356 MB |
| `scripts/verify_manifest.sh` | 校验文件是否齐全 |
| `docs/BOOT.md` | 制卡、启动、加载 EtherCAT 的步骤 |

## 上传镜像文件（尚未完成）

目前仓库里只有文档和清单，镜像文件还没上传。在一台装有 Dropbox 客户端、同步了 `/Workspace/RV` 的电脑上执行（第二条命令里的路径换成你本机 Dropbox 的实际路径）：

```bash
git clone https://github.com/micsnq2yoma-lgtm/RV.git && cd RV
cp -a ~/Dropbox/Workspace/RV/boot ~/Dropbox/Workspace/RV/boot.zip .
cp -a ~/Dropbox/Workspace/RV/TF卡镜像 tf-card
sh scripts/verify_manifest.sh
git add -A && git commit -m "Add boot images and tf-card contents" && git push
```

## 校验

```bash
sh scripts/verify_manifest.sh
```

## 注意

- 这些都是交叉编译好的二进制文件，仓库里没有源码。
- `tf-card/ecat_newchip.zip` 有 61.7 MB。GitHub 网页上传单个文件最大 25 MB，所以要用 git 命令行推送。
- `robot/6_new/` 里的 `trajectory.txt` 和 `Position-Velocity.txt` 在 Dropbox 原件里就是 0 字节。
