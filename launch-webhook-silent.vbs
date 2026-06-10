Set WShell = CreateObject("WScript.Shell")
WShell.Run "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File ""C:\Scripts\birthday-bot\birthday-discord.ps1""", 0, False
