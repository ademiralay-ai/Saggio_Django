"""NSSM/Task Scheduler altinda servis olarak calistirilacak basit launcher.

Kullanim:
    python.exe agent_launcher.py

NSSM ile kayit:
    nssm install SaggioRobotAgent ^
        C:\\SaggioRobotAgent\\.venv\\Scripts\\python.exe ^
        C:\\SaggioRobotAgent\\agent_launcher.py
    nssm set SaggioRobotAgent AppDirectory C:\\SaggioRobotAgent
    nssm set SaggioRobotAgent AppStdout    C:\\SaggioRobotAgent\\logs\\stdout.log
    nssm set SaggioRobotAgent AppStderr    C:\\SaggioRobotAgent\\logs\\stderr.log
    nssm set SaggioRobotAgent Start        SERVICE_AUTO_START
    nssm start SaggioRobotAgent
"""
import os
import signal
import sys
import threading
import traceback


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

# Stdout buffering kapat - log'lar aninda yazilsin
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass


def _log(msg):
    try:
        log_dir = "C:\\SaggioRobotAgent\\logs"
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "launcher.log"), "a", encoding="utf-8") as fp:
            fp.write(msg + "\n")
    except Exception:
        pass
    try:
        print(msg, flush=True)
    except Exception:
        pass


def main():
    _log(f"[launcher] starting | python={sys.executable} | dir={_SCRIPT_DIR}")

    try:
        from agent_runtime import DEFAULT_CONFIG_PATH, run_loop
    except Exception as ex:
        _log(f"[launcher] agent_runtime import FAILED: {ex}\n{traceback.format_exc()}")
        sys.exit(2)

    config_path = (
        os.environ.get("SAGGIO_AGENT_CONFIG")
        or "C:\\SaggioRobotAgent\\config.json"
    )
    if not os.path.exists(config_path):
        config_path = DEFAULT_CONFIG_PATH

    if not os.path.exists(config_path):
        _log(f"[launcher] config not found: {config_path}")
        sys.exit(3)

    _log(f"[launcher] config_path={config_path}")

    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        _log(f"[launcher] received signal {signum}, stopping...")
        stop_event.set()

    # NSSM stop emri SIGINT/SIGTERM gonderir, Ctrl+C de SIGINT
    try:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _handle_signal)
    except Exception:
        pass

    try:
        run_loop(stop_event, config_path)
        _log("[launcher] run_loop returned cleanly")
    except KeyboardInterrupt:
        _log("[launcher] keyboard interrupt")
    except Exception as ex:
        _log(f"[launcher] run_loop crashed: {ex}\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
