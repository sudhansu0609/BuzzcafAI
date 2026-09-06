' Buzzcaf Studio - one-click launcher with no console window.
'
' Runs backend\desktop_app.py under pythonw so nothing but the Studio window
' appears. Preflight runs inside desktop_app.py and reports failures in a
' dialog. For a console with hot reload, use start_buzzcafai.bat instead.
'
' Interpreter: BUZZCAF_PYTHON (a pythonw.exe path) -> .venv\Scripts\pythonw.exe
' -> pythonw.exe on PATH.
Option Explicit
Dim sh, fso, env, root, py
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
Set env = sh.Environment("PROCESS")

root = fso.GetParentFolderName(WScript.ScriptFullName)

py = env("BUZZCAF_PYTHON")
If py = "" Or Not fso.FileExists(py) Then py = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(py) Then py = "pythonw.exe"

sh.CurrentDirectory = root & "\backend"
' 0 = hidden window, False = do not wait.
sh.Run """" & py & """ -X utf8 """ & root & "\backend\desktop_app.py""", 0, False
