Option Explicit
Dim shell, fso, folder, proc, pythonExe, pythonwExe, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
On Error Resume Next
Set proc = shell.Exec("py -3 -c ""import sys; print(sys.executable)""")
If Err.Number <> 0 Then
  Err.Clear
  Set proc = shell.Exec("python -c ""import sys; print(sys.executable)""")
End If
If Err.Number <> 0 Then
  MsgBox "Install Python 3.10+ untuk Windows dulu. Lihat MULAI_DI_SINI.html.", 48, "YouTube Title Loop"
  WScript.Quit 1
End If
On Error GoTo 0
Do While proc.Status = 0
  WScript.Sleep 100
Loop
If proc.ExitCode <> 0 Then
  MsgBox "Python tidak bisa dijalankan. Coba START.bat untuk melihat error.", 48, "YouTube Title Loop"
  WScript.Quit 1
End If
pythonExe = Trim(proc.StdOut.ReadAll)
pythonwExe = fso.BuildPath(fso.GetParentFolderName(pythonExe), "pythonw.exe")
If Not fso.FileExists(pythonwExe) Then
  MsgBox "pythonw.exe tidak ditemukan. Install Python resmi untuk Windows.", 48, "YouTube Title Loop"
  WScript.Quit 1
End If
command = """" & pythonwExe & """ """ & fso.BuildPath(folder, "server.py") & """"
shell.Run command, 0, False
