import ctypes
import os
import sys
import time
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32

class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD),
        ('lpReserved', wintypes.LPWSTR),
        ('lpDesktop', wintypes.LPWSTR),
        ('lpTitle', wintypes.LPWSTR),
        ('dwX', wintypes.DWORD),
        ('dwY', wintypes.DWORD),
        ('dwXSize', wintypes.DWORD),
        ('dwYSize', wintypes.DWORD),
        ('dwXCountChars', wintypes.DWORD),
        ('dwYCountChars', wintypes.DWORD),
        ('dwFillAttribute', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('wShowWindow', wintypes.WORD),
        ('cbReserved2', wintypes.WORD),
        ('lpReserved2', ctypes.c_char_p),
        ('hStdInput', wintypes.HANDLE),
        ('hStdOutput', wintypes.HANDLE),
        ('hStdError', wintypes.HANDLE),
    ]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('hProcess', wintypes.HANDLE),
        ('hThread', wintypes.HANDLE),
        ('dwProcessId', wintypes.DWORD),
        ('dwThreadId', wintypes.DWORD),
    ]

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
backend_script = os.path.join(root_dir, "backend", "desktop_app.py")
pythonw_exe = r"C:\Python314\pythonw.exe"
if not os.path.exists(pythonw_exe):
    pythonw_exe = sys.executable

si = STARTUPINFOW()
si.cb = ctypes.sizeof(STARTUPINFOW)
si.lpDesktop = "WinSta0\\Default"
pi = PROCESS_INFORMATION()

cmd = f'"{pythonw_exe}" -X utf8 "{backend_script}"'
cwd = os.path.join(root_dir, "backend")

# CREATE_NEW_PROCESS_GROUP
flags = 0x00000200

success = kernel32.CreateProcessW(
    None,
    cmd,
    None,
    None,
    False,
    flags,
    None,
    cwd,
    ctypes.byref(si),
    ctypes.byref(pi),
)

if not success:
    print(f"Failed to launch on WinSta0\\Default: error {kernel32.GetLastError()}")
    sys.exit(1)

print(f"Buzzcaf Studio launched successfully on WinSta0\\Default with PID {pi.dwProcessId}")
kernel32.CloseHandle(pi.hThread)

# Wait for process exit so the daemon task stays alive and monitors it
kernel32.WaitForSingleObject(pi.hProcess, 0xFFFFFFFF) # INFINITE
exit_code = wintypes.DWORD()
kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(exit_code))
print(f"Process PID {pi.dwProcessId} exited with code {exit_code.value}")
kernel32.CloseHandle(pi.hProcess)
