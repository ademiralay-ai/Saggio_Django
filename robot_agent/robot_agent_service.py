import os
import threading

import servicemanager
import win32event
import win32service
import win32serviceutil

from agent_runtime import DEFAULT_CONFIG_PATH, run_loop


class SaggioRobotAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "SaggioRobotAgent"
    _svc_display_name_ = "Saggio Robot Agent"
    _svc_description_ = "Saggio merkezi sunucusundan iş alıp robot bilgisayarda çalıştırır."

    def __init__(self, args):
        super().__init__(args)
        self.h_wait_stop = win32event.CreateEvent(None, 0, 0, None)
        self.stop_event = threading.Event()
        self.worker = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop_event.set()
        win32event.SetEvent(self.h_wait_stop)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg("SaggioRobotAgent service started")
        config_path = os.environ.get("SAGGIO_AGENT_CONFIG", DEFAULT_CONFIG_PATH)

        self.worker = threading.Thread(target=run_loop, args=(self.stop_event, config_path), daemon=True)
        self.worker.start()

        win32event.WaitForSingleObject(self.h_wait_stop, win32event.INFINITE)
        self.stop_event.set()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=15)

        servicemanager.LogInfoMsg("SaggioRobotAgent service stopped")


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(SaggioRobotAgentService)
