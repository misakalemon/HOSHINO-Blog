@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Hoshino Blog 停止器
echo ============================================
echo  目标目录: %cd%
echo.

rem ── 1. 定位并终止本项目（目录内 app.py / worker.py）进程 ──
rem 注意：用 -like 通配符匹配而非正则，避免路径中的反斜杠
rem 被 .NET 正则当作转义符解析（如 \p、\h 等）导致匹配失败/报错。
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root = '%~dp0'.TrimEnd('\');" ^
  "try { $procs = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.CommandLine -and $_.CommandLine -like ('*' + $root + '*') -and ($_.CommandLine -like '*app.py*' -or $_.CommandLine -like '*worker.py*') }) }" ^
  "catch { Write-Host '[提示] 无法枚举进程（权限受限），请打开任务管理器手动结束 python 进程'; $procs = @() };" ^
  "if ($procs.Count -gt 0) {" ^
  "  $procs | ForEach-Object { Write-Host ('  终止: PID=' + $_.ProcessId + '  ' + $_.CommandLine); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue };" ^
  "  Start-Sleep -Milliseconds 800;" ^
  "  Write-Host ('已停止 ' + $procs.Count + ' 个进程')" ^
  "} else { Write-Host '未找到运行中的 hoshino-blog 进程' }"

echo.

rem ── 2. 端口释放检查（默认 5000，可用系统环境变量 PORT 覆盖）──
set "APP_PORT=5000"
if defined PORT set "APP_PORT=%PORT%"
powershell -NoProfile -Command ^
  "try { $p = Get-NetTCPConnection -LocalPort %APP_PORT% -State Listen -ErrorAction SilentlyContinue; } catch { $p = $null };" ^
  "if ($p) { Write-Host ('[提示] 端口 ' + %APP_PORT% + ' 仍被占用（PID=' + ($p | Select-Object -First 1).OwningProcess + '），可能不是本项目的服务') }" ^
  "else { Write-Host ('[OK] 端口 ' + %APP_PORT% + ' 已释放') }"

echo.
pause
