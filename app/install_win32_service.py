import os, subprocess, win32event, win32service, win32serviceutil

"""
Install and manage FastAPI application as a Windows service.

Requirements:
    pip install pywin32

Usage:
    python install_win32_service.py install
    python install_win32_service.py start
    python install_win32_service.py stop
    python install_win32_service.py remove

"""


class FastAPIService(win32serviceutil.ServiceFramework):
    _svc_name_ = "A10_Survey_Manager"
    _svc_display_name_ = "A10 Survey Manager Service"

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)

    def SvcDoRun(self):
        os.chdir("C:\\a10_app\\app")
        self.proc = subprocess.Popen([
            "C:\\a10_app\\.venv\\Scripts\\python.exe",
            "-m", "uvicorn", "main:app",
            "--host", "0.0.0.0", "--port", "8000"
        ])
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        self.proc.terminate()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(FastAPIService)
