@echo off
rem The one command, from cmd.exe. Everything is in dojo.ps1 -- read that one.
rem This only starts it with the execution policy bypassed for this process,
rem which changes nothing on your machine. PowerShell 7 (pwsh) when it is
rem installed, else Windows PowerShell 5.1, which every Windows has.
setlocal
set "PS=powershell"
where pwsh >nul 2>nul && set "PS=pwsh"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0dojo.ps1" %*
exit /b %ERRORLEVEL%
