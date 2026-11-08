# 开发板硬件概要（依据原理图 2026-09-03 版）

原理图由人提供（PDF，19 页），**不放进公开仓库**。本文只摘录和开发有关的接口信息。

| 模块 | 器件 / 信号 | 说明 |
|---|---|---|
| SoC | P0_TESTCHIP（FCLP484 封装），芯来 UX900，Linux 下可用 2 核 | 见 `handoff/DECISIONS.md` |
| 内存 | LPDDR4（H9HCNNNBKUMLXR） | Linux 识别为 2 GiB |
| 启动存储 | 2 片 W25Q128JV SPI Flash（XIP0、XIP2），APS12808L 128 Mb PSRAM（XIP1） | 闪存里是 Nuclei SDK 引导程序和 OpenSBI |
| eMMC | KLMCG4JEUD-B04P | Linux 下是 `mmcblk1`，59.6 GiB，装有 Ubuntu 24.04（任务 007） |
| TF 卡 | CARD1（SDIO0） | Linux 下是 `mmcblk0`，U-Boot 只从这里启动 |
| 以太网 1 | **J1**：RTL8201FI（百兆，MII） | Linux 下是 **eth0**（`f9c210000.xec`）；直连电脑，`192.168.50.2` |
| 以太网 2 | **RJ1**：RTL8211EG（千兆，GMII） | Linux 下是 **eth1**（`f9cdc0000.xec`）；**留给 EtherCAT** |
| CAN FD | 2 路，TJA1051T，引到 CN9 | Linux 驱动未验证 |
| RS485 | 4 路，SP3485（USART5/6/7/10），引到 CN9 | Linux 驱动未验证 |
| USB 2.0 | USB_TOP0（片上 PHY，USB1/USB5 口，带 ID 脚）；XUC0（ULPI，外接 USB3315C PHY，USB2/USB3/USB4/USB6 口，带 ID 脚） | 硬件支持 OTG；**当前 Linux 内核没有 USB 驱动**，暂不可用 |
| 调试 | USBC1：FT2232HL（A 通道 JTAG，B 通道 USART0 控制台） | 电脑上是 COM3，115200 |
| 扩展 | CN1 LGPIO 排针（GPIO、USART11、QSPI3/4、USART8 等），H4 排针 | 另有 RGB 屏（DISP）和摄像头（DCMI）复用引脚 |
| 无线 | **无 Wi-Fi，无蓝牙** | |
| 电源 | DC 输入经 TPS54332 降压到 5 V，AXP15060 PMIC；USBC1 也能供电（SW6 选择） | |
| 按键 | NRST（SW1） | 冷启动后需要按一次（报告 005） |
