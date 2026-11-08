# Panda simulation and S3 skills (tasks 010–011)

This is simulation only. Keep servo power disconnected. J1 is eth0; Windows
initiates UDP 15001 and TCP 15002. No EtherCAT, eth1, DeepSeek, firewall or Clash
changes are used by S3. Wire formats remain RVS1=144 and RVC1=80 bytes; see
[protocol v1.1](../docs/SIM_AGENT_DESIGN.md#33-协议-v11-补充2026-11-08根据报告-010).

Task 011 remains **failed**: FK and IK checks passed, tray placement was 9/10,
and stacking was 10/10, but two whole-board hangs prevented the ten-minute
stability acceptance. The root cause is unresolved. See the report before
repeating board tests; the short final timing window is not acceptance evidence.

## PC setup

From the repository root in PowerShell:

```powershell
python -m venv .venv/010/py
.venv/010/py/Scripts/python.exe -m pip install -r sim_agent/pc/requirements.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File sim_agent/pc/fetch_assets.ps1
```

Dependencies: MuJoCo 4.0.0, numpy 2.5.4, Pillow 13.0.0. The downloader pins
[MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie) commit
`98a70c569c4c1b6da467a20012f766ee1f8dc521` and retains the Panda Apache-2.0 license.
Original XML and meshes are ignored. We preserve the original eight actuators.
The table surface is z=0 m; cube edges are 4 cm, mass 0.05 kg, friction
`1 0.01 0.001`. Tray interiors are 0.20 x 0.16 m, floor height 0.008 m.

## Board setup

Follow [NETWORK.md](../docs/NETWORK.md) for current wiring, bootstrap, verified
SSH and the temporary proxy tunnel. Mount Ubuntu with `sh /mount_emmc.sh start`.
Install numpy **before** timing tests, in Ubuntu:

```sh
P=http://127.0.0.1:7897
apt-get -o Acquire::http::Proxy=$P -o Acquire::https::Proxy=$P install -y python3-numpy
```

Upload `sim_agent/board/rt_ctl/` source files and `sim_agent/board/agent/*.py` to
Ubuntu `/root/rv011/rt_ctl/` and `/root/rv011/agent/` respectively. Exclude binaries
and `__pycache__`; use the existing SSH/SCP procedure and never embed credentials.
For timing workloads also upload `board/tools/timing_client.py` to
Ubuntu `/root/rv011/tools/timing_client.py`.
Compile inside Ubuntu:

```sh
cd /root/rv011/rt_ctl
make CFLAGS='-O2 -Wall -Wextra -std=c11'
```

## Start S3

In two separate Buildroot SSH shells, with Ubuntu already mounted:

```sh
# Terminal 1: compiled C controller, no sine mode for skills
chroot /mnt/ubuntu /root/rv011/rt_ctl/rt_ctl --cpu 1

# Terminal 2: two tasks, each with seeds 0..9, fixed before testing
chroot /mnt/ubuntu python3 /root/rv011/agent/demo_s3.py --count 10 --out /root/rv011-images
```

Then start the PC (a longer ceiling permits both task suites):

```powershell
.venv/010/py/Scripts/python.exe sim_agent/pc/sim_server.py --seconds 900
```

The client waits for the PC's outbound connection. C runs FIFO80 with mlockall on
CPU1; it exits on setup failure. Python skills set their own affinity to CPU0.
For task 011 both run in Ubuntu, so `/tmp/rt_ctl.sock` resolves to the same path.
`--socket PATH` can override the C endpoint; the Python RTClient also accepts a
path. Do not replace an existing socket until its owner has been inspected.

For a continuous ten-minute timing run, replace the demo client with the command
below and run the PC with `--seconds 600`. It sends a four-second trajectory and
requests a top image every five seconds. `render 35` and `ping 35` are the
three-minute comparison workloads, paired with C `--sine`.

```sh
chroot /mnt/ubuntu python3 /root/rv011/tools/timing_client.py trajectory 118
```

`--validate` runs 50 random joint poses and 30 IK targets. Joint transitions also
respect the velocity limit, and FK is checked after one additional settling
second. FK uses the measured `ee_pose.q`, comparing to the independently returned
MuJoCo TCP pose. The log separately records command tracking error: random
joint-limit poses may collide with the table or robot and need not reach their
command. This is a kinematic model check, not collision-free planning.

## Trajectory interface

Linux Unix datagrams, little-endian, at `/tmp/rt_ctl.sock`. Clients bind an abstract
Unix address for replies. `transport.py` is the reference requester.

| Message | Python struct | Fields |
|---|---|---|
| Request, 80 bytes | `<4sI9d` | magic `RVT1`; op uint32; q_goal[7]; gripper_goal; duration_s |
| Reply, 144 bytes | `<4sIII16d` | magic `RVR1`; status; active; generation; measured q[7]; q_des[7]; measured gripper; gripper_des |

Ops: 1=replace segment, 2=query, 3=cancel/hold. Query/cancel still use an 80-byte
request, with unused doubles zeroed. Status: 0=accepted, 1=invalid, 2=no state yet.
Generation increments on new segments/cancel. `active=0` means interpolation is
complete, not proof that the physical joint has settled. Invalid lengths, magic,
ops, nonfinite targets, limit violations and durations outside [0.5,120] s are
rejected. No trajectory means mode=0; a finished trajectory keeps mode=1 at its
endpoint until replaced or cancelled.

A new segment starts at the **current interpolated target**, even during another
segment. Joints use `10u^3-15u^4+6u^5`, gripper width varies linearly. Python sets
`duration=max(0.5, max(abs(q_goal-q_des))/0.5)` seconds, bounding average joint
speed to 0.5 rad/s (quintic peak is 1.875 times the average). The PC retains its
joint limits and 2 rad/s target slew limit. SIGINT sends mode=0 for 0.5 s then exits.

## Model export and skills

`kinematics` exports compiled `mjModel` body poses, hinge anchors/axes/ranges and
qpos0 along link0→hand, plus the TCP site's hand-relative transform. No DH table
is copied. The site is created in our MjSpec, at the pad tip minus 1 cm: hand-local
`[0,0,0.1014]` m for this pinned asset. `ee_pose` returns TCP world pos/quaternion,
measured q and total finger width. All quaternions are w,x,y,z.

`kin.py` composes exported transforms and a geometric Jacobian. IK uses damped
least squares, joint limits and a weak null-space home bias; it accepts only
position <1 mm and orientation <1 degree within 200 iterations, otherwise raises.
`skills.py` provides home, move_to(x,y,z,yaw), pick(x,y,yaw), and place(x,y,z).
The TCP z axis points down. Pick uses TCP z=0.023 m and a 0.10 m lift; a measured
width in [0.03,0.05] m is required before and after lifting. Place z means the
**cube center height**, so TCP is 3 mm higher. Ground truth is deliberately used
in S3; no camera perception or language model is involved.

Evaluation: the red cube must fit entirely inside the left tray's xy interior
(center margins 0.08/0.06 m) with center z in (0.02,0.05) m. Stacking requires
blue-green xy distance <0.02 m and height difference 0.04±0.01 m after settling.
Every failure and elapsed time is retained; trials are not retried or replaced.

## Scheduling and diagnostics

The default PC runs physics/UDP in a Windows HIGH priority process (never REALTIME)
and viewer/OpenGL/TCP in a separate NORMAL priority process. Shared qpos/qvel/time
snapshots are published with a **nonblocking** lock; missed snapshots are counted.
Renderer startup completes before the benchmark clock. Viewer.sync is at most
30 Hz; display perturbations are not fed back into the physics process.

`--headless` hides the viewer, while rendering remains available. `--in-process`
retains the older architecture for diagnostics only. Events above 20 ms identify
physics starts, mj_step, viewer sync, TCP operations and UDP gaps. The 98 ms
watchdog runs every physics step; logs distinguish a simultaneous >=98 ms physics
stall from silence while physics was being scheduled. This is attribution from
observed timings, not a claim about the OS/driver's underlying cause.

A smaller peer sequence starts a fresh statistics epoch without counting a gap
as loss. Reset returns sim_time and state sequence to zero, sets flags bit1 and
resets packet statistics. Physics-step/wall counters remain cumulative. Mode=0
captures a hold target when entering hold, preventing repeated recapture from
following gravity-driven drift. `--stop-on-stdin` is an optional supervisor exit:
STOP/newline or EOF stops cleanly; its reader starts after process spawning.

The GLFW/model APIs follow the official [Python bindings](https://mujoco.readthedocs.io/en/stable/python.html)
and [mjModel data definitions](https://mujoco.readthedocs.io/en/stable/APIreference/APItypes.html).

## Verification and safe exit

```powershell
.venv/010/py/Scripts/python.exe -m unittest discover -s sim_agent/pc -v
```

The tests compare FK to independent MuJoCo poses, check converged/unreachable IK,
and verify packet offsets, invalid data and JSON error recovery. The original localhost fake_board
fixture is still available; its metrics are not board acceptance evidence.

Finish the Python client, Ctrl+C the C controller and PC server, then confirm the
owned processes have exited. Exit any chroot shells and run from Buildroot:

```sh
sh /mount_emmc.sh stop
sh /mount_emmc.sh status
```

Verify all Ubuntu mounts are gone before closing the SSH proxy tunnel. Never
force unmount. Measured results and remaining limits belong in the
[task 011 report](../handoff/reports/011-panda-kinematics-pick-place.md);
[task 010's original failures](../handoff/reports/010-mujoco-panda-loopback.md) remain historical evidence.

## Task 012 diagnostic controls

The controller accepts `--fifo-priority 1..99` (default 80) or `--sched-other`.
Keep `--cpu 1`; the isolation Python load pins itself to CPU0. These are diagnostic
choices, not a demonstrated fix for the board hang. JSON fields
`lifetime_processing_us_max` and `lifetime_interval_ms_max` survive scene resets;
ordinary packet and timing statistics still reset with the protocol epoch.

`scripts/stability_baseline.sh` records the available kernel diagnostics.
The Windows `scripts/stability_serial.py` collector uses pyserial and a control
file: writing `sysrq` requests 30 seconds of passive capture followed by BREAK
and w/l/t, five seconds apart; writing `stop` closes capture. It never resets the
board. Keep authentication out of the captured/public stream.

`pc/stability_runner.py E1` through `E6` is the task-specific Windows/Paramiko
supervisor, run from the repository root after board preparation. It expects a
verified `.venv/012/known_hosts`, transient `RV_BOARD_PASSWORD`, the prepared
board RAM tree `/tmp/rv012`, and the existing `.venv/010/py` MuJoCo environment.
Use `--label` for a new evidence directory; existing evidence is never overwritten.
The RAM tree must contain the compiled controller, agent modules, load tool and
eMMC load script. This runner does not bootstrap, authenticate over serial, upload
sources or request a hardware reset. Follow the task's evidence and human reset
procedure on failure; inspect processes and mounts before any manual cleanup.

See [stability findings](../docs/STABILITY.md) for experiment scope and limitations.
