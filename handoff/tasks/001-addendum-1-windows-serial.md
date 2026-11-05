# 任务 001 补充 1：Windows 主机上找不到串口

- **补充的任务**：`001-tf-card-boot-bringup.md`
- **作者**：Claude
- **日期**：2026-11-05
- **起因**：Codex 汇报，Windows 主机上没有发现 COM 口。人补充的信息是：开发板用的是芯来（Nuclei）**UX900** 处理器核。

## 对任务 001 的修改

1. **主机是 Windows**，不是 Linux。任务 001 第 1 步里的 `ls /dev/ttyUSB*`、`dmesg` 换成下面 A 节的 PowerShell 命令。`scripts/serial_console.py` 的 `--port` 参数用 `COM3` 这样的写法。其他步骤里在**板子上**执行的命令保持不变。
2. 第 3 步之前，先完成 B 节，找到可用的 COM 口。找不到就把状态标为 `blocked`，并把 A 节的输出写进报告。
3. 默认波特率仍然是 **115200**。芯来的 SDK 和 Linux 默认都用这个值；如果实际不是，按任务 001 的“失败时怎么办”里的顺序换着试。

## A. 先把 USB 设备情况查清楚（只读）

在 PowerShell 里执行，输出存到 `logs/20261105-001-host-usb.log`：

```powershell
# 1) 系统认出的串口
[System.IO.Ports.SerialPort]::GetPortNames()
python -m serial.tools.list_ports -v

# 2) 所有 USB 设备，包括没装驱动、绑到 WinUSB 上的
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match '^(USB|FTDIBUS)\\' } |
  Sort-Object Class | Format-Table -AutoSize Status, Class, FriendlyName, InstanceId

# 3) 拔掉开发板的 USB 线再插上，前后各执行一次，对比多出来的设备
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match '^USB\\VID_' } |
  Select-Object FriendlyName, InstanceId
```

用 `InstanceId` 里的 `VID_xxxx&PID_yyyy` 判断串口芯片：

| VID:PID | 芯片 | 说明 |
|---|---|---|
| 0403:6010 | FTDI FT2232 | 芯来调试器、Digilent 等常用这个芯片。一个 USB 口分出两路：`MI_00` 一般是 JTAG，`MI_01` 一般是 UART |
| 0403:6011 / 6014 / 6001 | FTDI FT4232 / FT232H / FT232R | 装 FTDI VCP 驱动后出现 COM 口 |
| 1A86:7523、1A86:55D4 | WCH CH340、CH9102/CH343 | 需要装 WCH 的驱动 |
| 10C4:EA60 | Silicon Labs CP210x | 需要装 CP210x 的驱动 |
| 067B:2303 | Prolific PL2303 | 需要装 Prolific 的驱动 |

## B. 根据 A 节的结果处理

| A 节看到的情况 | 原因 | 处理 |
|---|---|---|
| 设备出现在“其他设备”里，带黄色感叹号，或者 `Status` 是 `Error`/`Unknown` | 没装驱动 | **[需人工]** 请人按上表安装对应厂商的官方驱动，装完重新执行 A 节 |
| 有 `VID_0403&PID_6010`，但出现在“通用串行总线设备”下、`Class` 是 `USBDevice`，或者显示为 WinUSB/libusb | 以前为了让 OpenOCD 调试用 Zadig 换了驱动，UART 那一路也被换成了 WinUSB | **[需人工]** 请人在设备管理器里**只把 Interface 1（`MI_01`）**换回 FTDI 驱动，Interface 0 保持 WinUSB，不影响 JTAG 调试。如果设备显示为 “USB Serial Converter B”，在属性→高级里勾上 “Load VCP” |
| 有 FTDI 设备、驱动正常，但没有 COM 口 | FTDI 驱动没启用 VCP | **[需人工]** 同上，勾上 “Load VCP”，然后重新插拔 |
| 插拔前后一个新设备都没有 | 线只能充电不能传数据；插在了板子的供电口或 OTG 口而不是调试口；调试器没上电 | **[需人工]** 请人换一根确定能传数据的线，确认插的是板子上标着 DEBUG、UART、JTAG 或 USB-UART 的口，并确认板子已上电（有的调试器靠板子供电） |
| 板子上没有 USB 调试口，只有 TX/RX/GND 排针 | 需要外接 USB 转 TTL 模块 | **[需人工]** 请人接一个 **3.3 V** 电平的 USB 转 TTL 模块：模块 TX 接板子 RX，模块 RX 接板子 TX，GND 接 GND，**模块的 VCC 不要接**。之后按上表装驱动 |

Codex 不要自行安装、替换或卸载驱动，也不要运行 Zadig。所有驱动操作都由人来做，Codex 只负责告诉人看到了什么、建议怎么做。

## C. 需要人补充的信息（Codex 请转达）

UX900 只是芯来的处理器核，用这个核的开发板和 SoC 有好几种，光凭核的名字确定不了串口怎么接。请人提供以下任意一项：

1. 开发板的型号或丝印（板子正面最大的那行字），或者 SoC 芯片上的型号；
2. 板子上所有 USB 口和排针旁边的标注，例如 DEBUG、UART、JTAG、OTG、PWR；
3. 板子的照片（正面，能看清接口），放进仓库 `docs/img/`。照片里不要有不想公开的信息。

## 报告要求

在 `handoff/reports/001-tf-card-boot-bringup.md` 里增加一节“主机串口排查”，写明：A 节的输出摘要、最终用的 COM 口和芯片、人做了哪些驱动操作。如果最终仍然没有串口，就写到这一步为止，状态标为 `blocked`。
