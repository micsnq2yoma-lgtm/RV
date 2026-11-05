# 制卡与启动

以下内容依据 `tf-card/boot.scr`、`tf-card/ecat/load_ec_modules.sh` 和 `tf-card/ecat/load_ec_module_master.sh` 整理。

## 1. 制作 TF 卡

1. TF 卡格式化成一个 **FAT32** 分区（MBR 分区表）。U-Boot 用 `fatload mmc 0` 读文件。
2. 把 `tf-card/` 根目录下的 `boot.scr`、`uImage.lz4`、`uInitrd.lz4`、`kernel.dtb` 放到卡的**根目录**。`boot.scr` 默认 `bootloc=.`。
3. 把 `tf-card/ecat/`（新芯片用 `tf-card/ecat_newchip/`）复制到卡上，命名为 `ecat/`。`load_ec_module_master.sh` 写死了 `/media/ecat/ko`。

## 2. 启动

U-Boot 默认会执行 `boot.scr`。如果没有执行，在 U-Boot 提示符下手动输入：

```
fatload mmc 0 0x3000000 uImage.lz4
fatload mmc 0 0x8300000 uInitrd.lz4
fatload mmc 0 0x8000000 kernel.dtb
bootm 0x3000000 0x8300000 0x8000000
```

根文件系统是 `uInitrd.lz4`，一个跑在内存里的 initramfs，**重启后改动不保留**。要保留的东西放在 TF 卡上。

## 3. 加载 EtherCAT 主站

```sh
mount /dev/mmcblk0p1 /media        # 设备名以 ls /dev/mmcblk* 为准
cd /media/ecat
```

下面两种方式选一种：

- **板载 Nuclei XEC 网口作主站**：`sh load_ec_module_master.sh`
  这个脚本把 MAC 写死成 `00:11:22:33:44:55`，会把 `f8b160000.xec` 从 `nuclei-xec` 驱动解绑，再绑到 `nuclei-xec-ecat` 上。
- **eth1 加通用驱动**：`sh load_ec_modules.sh`
  这个脚本读取 eth1 的 MAC，加载 `ec_master.ko` 和 `ec_generic.ko`。

## 4. 运行控制程序

```sh
cd /media/ecat/robot/6_run
export LD_LIBRARY_PATH=.
./Trajectory_main
```

`Trajectory_main` 的命令行参数目前不清楚。第一次上真机请先跑 `noenable` 或 `noenable-notrajectory` 版本，确认通信正常后，再跑会使能电机的版本。
