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
If Not fso.FileExists(py) Then
    Dim candidates, c
    candidates = Array("C:\Python314\pythonw.exe", "C:\Program Files\Python311\pythonw.exe", "C:\Program Files\Python313\pythonw.exe", "C:\Program Files\Python312\pythonw.exe", "C:\Python311\pythonw.exe", "C:\Python312\pythonw.exe", "C:\Python313\pythonw.exe")
    For Each c In candidates
        If fso.FileExists(c) Then
            py = c
            Exit For
        End If
    Next
End If
If Not fso.FileExists(py) Then
    On Error Resume Next
    Dim ex
    Set ex = sh.Exec("where.exe pythonw.exe")
    If Err.Number = 0 And Not ex Is Nothing Then
        Dim line
        line = Trim(ex.StdOut.ReadLine())
        If fso.FileExists(line) Then py = line
    End If
    On Error GoTo 0
End If
If Not fso.FileExists(py) Then py = "pythonw.exe"

sh.CurrentDirectory = root & "\backend"
' 1 = normal window (pythonw has no console, so only the Studio window shows), False = do not wait.
sh.Run """" & py & """ -X utf8 """ & root & "\backend\desktop_app.py""", 1, False

