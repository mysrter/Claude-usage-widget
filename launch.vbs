Option Explicit
Dim sh, fso, pyw, scriptDir, script
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

pyw = "C:\Python314\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw"

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(scriptDir, "widget.pyw")

sh.Run """" & pyw & """ """ & script & """", 0, False
