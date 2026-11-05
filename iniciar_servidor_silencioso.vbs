' ==============================================================================
'  VmPOS - Iniciador Silencioso del Servidor Windows (Sin consola negra)
' ==============================================================================
Set WshShell = CreateObject("WScript.Shell")
strPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strPath
WshShell.Run Chr(34) & strPath & "\iniciar_servidor_segundo_plano.bat" & Chr(34), 0, False
Set WshShell = Nothing
