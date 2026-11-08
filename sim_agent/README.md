# Panda simulation — task 010 (simulation only)

Protocol: [design v1](../docs/SIM_AGENT_DESIGN.md). No EtherCAT access. J1 is eth0;
Windows initiates both connections. Do not change Windows firewall or Clash.
Real-board timing acceptance is separate from the localhost fixture.

## PC setup (PowerShell, repository root)

```powershell
python -m venv .venv/010/py
.venv/010/py/Scripts/python.exe -m pip install -r sim_agent/pc/requirements.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File sim_agent/pc/fetch_assets.ps1
```

Dependencies are pinned to MuJoCo 4.0.0, numpy 2.5.4, Pillow 13.0.0 (JPEG encoder).
Assets: [Google DeepMind MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie),
commit `98a70c569c4c1b6da467a20012f766ee1f8dc521`,
`franka_emika_panda`, Apache-2.0. The downloader retains upstream LICENSE/README.
No meshes or original model XML are committed. Our scene includes the original
`panda.xml`; original actuators remain unchanged. A wrist camera is attached to
the original `hand` with MjSpec at load time. Table surface is world z=0 m.

## Local fixture before board testing

Run in two terminals in the same host/network context:

```powershell
.venv/010/py/Scripts/python.exe sim_agent/pc/fake_board.py --seconds 30
.venv/010/py/Scripts/python.exe sim_agent/pc/sim_server.py --board-ip 127.0.0.1 --seconds 18
```

The fixture replies with sine targets, requests both images and reset, deliberately
withholds commands from t=6 to 6.5 seconds, then resumes. Use `--no-pause` for
an uninterrupted fixture run. Images default to ignored `sim_agent/runs/local-images`.
Local timing and intentional dropped replies are **not** real-board acceptance.
`--headless` closes only the viewer; the rendering thread still serves images.

## Board preparation and launch

Confirm current wiring and servo power disconnected, then follow
[NETWORK.md](../docs/NETWORK.md) to log into Buildroot, release COM3, and run:

```powershell
./scripts/board_bootstrap.ps1 -Port COM3
```

Copy `sim_agent/board/rt_ctl/{rt_ctl.c,protocol.h,Makefile}` and
`sim_agent/board/tools/proto_client.py` to the board. Use the existing board_scp
wrapper or verified SSH/SCP; never embed passwords. Enter eMMC Ubuntu via
`sh /mount_emmc.sh start`, then compile in the uploaded directory:

```sh
make CFLAGS='-O2 -Wall -Wextra -std=c11'
./rt_ctl --sine --cpu 1
```

The process exits on failed mlockall, affinity or SCHED_FIFO=80. It does not
silently downgrade scheduling. Prefer copying the executable to Buildroot RAM
and running there if its dynamic loader/libs are compatible; otherwise use
chroot and record that fact. Do not claim either path works until tested.
In a separate board shell:

```sh
python3 proto_client.py --out /tmp/rv010-images
```

Then on the PC (viewer opens, 600 seconds by default):

```powershell
.venv/010/py/Scripts/python.exe sim_agent/pc/sim_server.py --board-ip 192.168.50.2 --seconds 600
```

The TCP client requests hello, objects, top and wrist JPEGs (640x480 quality 80),
reset seed=1, then objects. It reports metadata and bytes rather than dumping
base64. The returned objects are ground truth for testing, not Agent perception.

## Timing and shutdown

- RVS1=144 bytes, RVC1=80 bytes, explicitly little-endian. UDP 15001/TCP 15002.
- Physics uses 2ms deadlines, skips catch-up when late; state every second step.
  OpenGL/JPEG run on a dedicated thread with a brief locked state copy.
- A separate UDP reader timestamps actual arrival; RTT uses echoed ack and
  monotonic send/arrival timestamps, not time when physics applies the command.
- Joint targets are range-clamped and slewed by at most 0.004 rad/physics step
  (2 rad/s). Mode 0 and timeout hold measured position. Timeout is checked at
  98ms (one-step margin); OS scheduling can still exceed 100ms and must be reported.
- Loss counts unanswered states older than 100ms, excludes live in-flight and
  reset-discarded states. Stats separately expose those counts; intended interruption
  periods must not be mixed into the uninterrupted ten-minute benchmark.
- C reports cumulative receive/loss, processing mean/max, interval mean/max/std
  every second from a non-RT reporter. No terminal I/O on the normal RT packet path.
- Ctrl+C on rt_ctl keeps responding mode=0 for 0.5s, then exits. Test shutdown
  and restart explicitly. Ctrl+C on the PC stops its threads and closes the viewer.
  After all board processes finish, exit chroot and `sh /mount_emmc.sh stop`;
  verify unmounted before ending the session. No forced unmount.

## Measured results (2026-11-07 local / 2026-11-08 UTC)

`python -m unittest discover -s sim_agent/pc -v` tests exact offsets, lengths,
invalid magic/mode/NaN/Inf. The real-board executable compiled without warnings
in eMMC Ubuntu and ran from Buildroot `/tmp/rv010-rt_ctl --sine --cpu 1`, with
`SCHED_FIFO=80 mlockall=ok`. The Python TCP client ran in Ubuntu.

The 600.002-second run had 0% sequence loss, RTT p50 0.916 ms / p99 1.169 ms /
max 4.833 ms, but board processing max **490.236 us** exceeded the 200 us limit.
PC watchdog activation also exceeded 100 ms during four stalls. Acceptance
therefore **failed**. An independent stop/restart test reached the watchdog at
99.305 ms after the last command (already holding after SIGINT mode=0).
Both returned images show all three cubes and both trays. Actual logs, images,
timing limits and cleanup: [task 010 report](../handoff/reports/010-mujoco-panda-loopback.md).
