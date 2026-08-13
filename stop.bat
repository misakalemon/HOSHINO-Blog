@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 正在查找 hoshino-blog 相关进程 ...
set "FOUND=0"

:: 通过 PowerShell 精确定位并终止本项目目录下的 app.py 和 worker.py 进程
powershell -NoProfile -Command ^
  "$p = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '%~dp0' -and ($_.CommandLine -match 'app\.py' -or $_.CommandLine -match 'worker\.py') };" ^
  "if ($p) { $p | ForEach-Object { Write-Host ('  终止: PID=' + $_.ProcessId + '  ' + $_.CommandLine); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Write-Host '已停止所有 hoshino-blog 进程' }" ^
  "else { Write-Host '未找到运行中的 hoshino-blog 进程' }"

echo.
pause
