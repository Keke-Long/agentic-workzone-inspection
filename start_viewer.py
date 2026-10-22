"""Launch the three read-only BEV/report pages using only Python standard library.
Open http://127.0.0.1:8768/workzone1/bev on the same machine.
For a remote workstation use SSH local port forwarding.
"""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parent / "experiments/agentic_inspection/scripts/case18_bev_readonly_server.py"), run_name="__main__")
