import os
import sys
import threading
import traceback


# ============================================================
# 0) En erken log altyapisi - modul import edilirken bile yazsin
# ============================================================
def _startup_log(message):
    """Servis baslangicindaki kritik hatalari diske yaz."""
    try:
        log_dir = "C:\\SaggioRobotAgent\\logs"
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "service_startup.log"), "a", encoding="utf-8") as fp:
            fp.write(message + "\n")
    except Exception:
        pass


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
_startup_log(f"[module-load] script_dir={_SCRIPT_DIR} python={sys.executable}")

# ============================================================
# 1) pywin32 importlari - hatayi yakala ve logla
# ============================================================
try:
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil
    _startup_log("[module-load] pywin32 imports ok")
except Exception as ex:
    _startup_log(f"[module-load-error] pywin32 import failed: {ex}\n{traceback.format_exc()}")
    raise

# NOT: agent_runtime importu BILEREK lazy yapildi (SvcDoRun icinde).
# Bu sayede 'requests' gibi bir bagimliik eksikse servis startup'i 1053
# yerine event log + dosya log uretir.


class SaggioRobotAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "SaggioRobotAgent"
    _svc_display_name_ = "Saggio Robot Agent"
    _svc_description_ = "Saggio merkezi sunucusundan iş alıp robot bilgisayarda çalıştırır."

    def __init__(self, args):
        super().__init__(args)
        self.h_wait_stop = win32event.CreateEvent(None, 0, 0, None)
        self.stop_event = threading.Event()
        self.worker = None
        self.worker_error = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop_event.set()
        win32event.SetEvent(self.h_wait_stop)

    def _worker_main(self, run_loop, config_path):
        try:
            run_loop(self.stop_event, config_path)
        except Exception as ex:
            self.worker_error = ex
            tb = traceback.format_exc()
            _startup_log(f"[worker-crash] {ex}\n{tb}")
            try:
                servicemanager.LogErrorMsg(f"SaggioRobotAgent worker crashed: {ex}\n{tb}")
            except Exception:
                pass
            win32event.SetEvent(self.h_wait_stop)

    def SvcDoRun(self):
        _startup_log("[svcdorun] entered")
        try:
            # 1) SCM'ye HEMEN RUNNING raporla
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            _startup_log("[svcdorun] reported SERVICE_RUNNING")
            servicemanager.LogInfoMsg("SaggioRobotAgent service started")

            # 2) Lazy import - hata burada yakalanir
            try:
                from agent_runtime import DEFAULT_CONFIG_PATH, run_loop
                _startup_log("[svcdorun] agent_runtime import ok")
            except Exception as ex:
                tb = traceback.format_exc()
                _startup_log(f"[svcdorun] agent_runtime import FAILED: {ex}\n{tb}")
                servicemanager.LogErrorMsg(f"agent_runtime import failed: {ex}\n{tb}")
                return

            # 3) Config yolu cozumle
            config_path = (
                os.environ.get("SAGGIO_AGENT_CONFIG")
                or "C:\\SaggioRobotAgent\\config.json"
            )
            if not os.path.exists(config_path):
                config_path = DEFAULT_CONFIG_PATH
            _startup_log(f"[svcdorun] config_path={config_path} exists={os.path.exists(config_path)}")

            if not os.path.exists(config_path):
                msg = f"config.json bulunamadi: {config_path}"
                _startup_log(f"[svcdorun-error] {msg}")
                servicemanager.LogErrorMsg(msg)
                return

            # 4) Worker thread
            self.worker = threading.Thread(
                target=self._worker_main, args=(run_loop, config_path), daemon=True
            )
            self.worker.start()
            _startup_log("[svcdorun] worker thread started")

            # 5) Stop sinyali bekle
            win32event.WaitForSingleObject(self.h_wait_stop, win32event.INFINITE)
            self.stop_event.set()
            if self.worker and self.worker.is_alive():
                self.worker.join(timeout=15)

            _startup_log("[svcdorun] stopped cleanly")
            servicemanager.LogInfoMsg("SaggioRobotAgent service stopped")
        except Exception as ex:
            tb = traceback.format_exc()
            _startup_log(f"[svcdorun-fatal] {ex}\n{tb}")
            try:
                servicemanager.LogErrorMsg(f"SaggioRobotAgent fatal: {ex}\n{tb}")
            except Exception:
                pass
            raise


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(SaggioRobotAgentService)


