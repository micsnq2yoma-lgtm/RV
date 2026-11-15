"""Run DexJoCo agent episodes on the RV board. usage: run_board.py LIB.json OUT_DIR task:seed ...
The DeepSeek key is read from the board's key file by agent.Model (mode 600, never printed); API traffic goes through the
SSH reverse-tunnel proxy. The PC runs dexjoco_server.py --agent-ip 192.168.50.2 and connects in on TCP 15005.
"""
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
if hasattr(os,'sched_setaffinity'):os.sched_setaffinity(0,{0})
import run_local
if __name__=='__main__':run_local.main(board=True)
