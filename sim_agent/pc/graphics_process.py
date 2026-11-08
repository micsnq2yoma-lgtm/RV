"""Separate display/OpenGL process; shared snapshot publication never blocks physics."""
import ctypes
import json
import faulthandler
import os
import queue
import threading
import time
import numpy as np


def set_windows_priority(value):
    if os.name!='nt':return
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.SetPriorityClass.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.SetPriorityClass.restype=wintypes.BOOL
    if not kernel.SetPriorityClass(kernel.GetCurrentProcess(),value):raise ctypes.WinError(ctypes.get_last_error())


def read_snapshot(shared, lock, model):
    with lock:
        values=np.frombuffer(shared,dtype=np.float64).copy()
    return values[:model.nq],values[model.nq:model.nq+model.nv],values[-1]


def graphics_main(board_ip,headless,shared,lock,commands,replies,ready,stop):
    # Only physics receives elevated process priority.
    print(json.dumps({'graphics_stage':'starting'}),flush=True)
    if os.environ.get('RV_DIAG_TRACE'):faulthandler.dump_traceback_later(20)
    set_windows_priority(0x20)
    from sim_server import Simulator,timing
    sim=Simulator(board_ip)
    print(json.dumps({'graphics_stage':'model_ready'}),flush=True)
    sim.shared=(shared,lock);sim.remote_jobs=(commands,replies);sim.render_ready=ready
    viewer=None;worker=None
    try:
        if not headless:
            from mujoco import viewer as mj_viewer
            viewer=mj_viewer.launch_passive(sim.model,sim.data)
        print(json.dumps({'graphics_stage':'viewer_ready'}),flush=True)
        worker=threading.Thread(target=sim.tcp_worker,daemon=True);worker.start()
        # Do not race viewer.sync against creation of the offscreen GLFW context.
        if not ready.wait(45):raise RuntimeError('offscreen renderer startup timed out')
        while not stop.is_set() and (viewer is None or viewer.is_running()):
            q,v,t=read_snapshot(shared,lock,sim.model)
            if viewer:
                with viewer.lock(),sim.lock:
                    sim.data.qpos[:]=q;sim.data.qvel[:]=v;sim.data.time=t
                began=time.perf_counter();viewer.sync();timing('graphics_viewer_sync',began)
            stop.wait(1/30)
    finally:
        sim.stop.set()
        if worker:worker.join(3)
        if viewer:viewer.close()
        stop.set()
