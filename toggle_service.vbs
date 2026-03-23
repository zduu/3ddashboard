Option Explicit

Dim fso, shell
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

Dim repo, runPy, logsDir, logFile
repo = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = repo
runPy = fso.BuildPath(repo, "run.py")

If Not fso.FileExists(runPy) Then
  WScript.Quit 1
End If

' Detect running service processes (python/pythonw/py/pyw with our run.py)
Dim svc, procs, proc, found, cmd
found = False
Set svc = GetObject("winmgmts:\\.\root\cimv2")
Set procs = svc.ExecQuery("SELECT * FROM Win32_Process WHERE Name='python.exe' OR Name='pythonw.exe' OR Name='py.exe' OR Name='pyw.exe'")
For Each proc In procs
  On Error Resume Next
  cmd = ""
  If Not IsNull(proc.CommandLine) Then cmd = LCase(proc.CommandLine)
  On Error GoTo 0
  If cmd <> "" Then
    If InStr(cmd, "run.py") > 0 And InStr(cmd, LCase(repo)) > 0 Then
      proc.Terminate 0
      found = True
    End If
  End If
Next

If found Then
  ' toggled OFF
  WScript.Quit 0
End If

' Ensure logs directory
logsDir = fso.BuildPath(repo, "logs")
If Not fso.FolderExists(logsDir) Then On Error Resume Next: fso.CreateFolder(logsDir): On Error GoTo 0
logFile = fso.BuildPath(logsDir, "service.log")

' Require existing login state; otherwise, do nothing (login must be done via BAT)
Dim stateFile
stateFile = fso.BuildPath(repo, "state\auth_state.json")
If Not fso.FileExists(stateFile) Then
  WScript.Quit 2
End If

' Resolve Python command for headless run
Dim base, pyPathFile, ts, line
base = ""

pyPathFile = fso.BuildPath(repo, "PY_PATH.txt")
If fso.FileExists(pyPathFile) Then
  Set ts = fso.OpenTextFile(pyPathFile, 1)
  If Not ts.AtEndOfStream Then
    line = Trim(ts.ReadLine)
    If InStr(LCase(line), "python.exe") > 0 Then
      line = Replace(line, "python.exe", "pythonw.exe")
    End If
    base = line
  End If
  ts.Close
End If

If base = "" Then
  ' Prefer the Windows launcher without console
  Dim ret
  On Error Resume Next
  ret = shell.Run("cmd /c ""where pyw""", 0, True)
  If Err.Number = 0 And ret = 0 Then
    base = "pyw -3"
  End If
  Err.Clear
  On Error GoTo 0
End If

If base = "" Then
  base = "pythonw"
End If

' If base looks like a path with spaces and no quotes, quote it.
If InStr(base, " ") > 0 And Left(base,1) <> Chr(34) Then
  If LCase(Left(base,3)) <> "pyw" And LCase(Left(base,6)) <> "python" Then
    base = Chr(34) & base & Chr(34)
  End If
End If

' Launch hidden via cmd to support log redirection
Dim cmdline
cmdline = "cmd /c " & base & " """ & runPy & """ >> """ & logFile & """ 2>&1"
shell.Run cmdline, 0, False

WScript.Quit 0
