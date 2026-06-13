"""
Sovereign Nexus Orchestrator (SNO) CLI Tool — v2.0
Exposes console scripts to run server, UI, or both.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# Configure UTF-8 encoding safely to prevent UnicodeEncodeError on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


def start_server() -> None:
    """Start SNO MCP Server."""
    print("[SNO] Starting Sovereign Nexus Orchestrator MCP Server...")
    from src.main import main
    main()


def start_ui() -> None:
    """Start SNO Streamlit Ops Console."""
    print("[UI] Starting SNO Ops Console (Streamlit)...")
    cmd = [sys.executable, "-m", "streamlit", "run", "src/ui/app.py"]
    try:
        subprocess.run(cmd)
    except Exception as e:
        print(f"Error starting Streamlit UI: {e}")
        print("Please ensure streamlit is installed (pip install streamlit)")


def start_all() -> None:
    """Run both backend server and UI concurrently."""
    print("[SNO] Bootstrapping SNO Services Concurrently...")
    import time
    
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()

    # Start server as a subprocess
    server_process = subprocess.Popen(
        [sys.executable, "-c", "from src.main import main; main()"],
        env=env,
    )
    time.sleep(1.5)  # Wait for MCP port binding

    # Start UI as a subprocess
    ui_process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "src/ui/app.py"],
        env=env,
    )

    try:
        server_process.wait()
        ui_process.wait()
    except KeyboardInterrupt:
        print("\n[SNO] Shutting down SNO services...")
        server_process.terminate()
        ui_process.terminate()
        server_process.wait()
        ui_process.wait()
        print("Shutdown complete.")



def main() -> None:
    parser = argparse.ArgumentParser(description="Sovereign Nexus Orchestrator (SNO) CLI Tool")
    parser.add_argument(
        "command",
        choices=["start", "ui", "run"],
        help="Command to execute: 'start' (MCP Server), 'ui' (Streamlit Ops Console), or 'run' (Both concurrently)",
    )
    args = parser.parse_args()

    # Insert current working directory to PYTHONPATH
    sys.path.insert(0, os.getcwd())

    if args.command == "start":
        start_server()
    elif args.command == "ui":
        start_ui()
    elif args.command == "run":
        start_all()


if __name__ == "__main__":
    main()
