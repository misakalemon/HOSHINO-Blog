@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo   Hoshino Blog 启动器
echo ============================================
echo  工作目录: %cd%
echo.

rem ── 0. 参数解析：start.bat --debug 以调试模式启动 ──
set "DEBUG_FLAG="
for %%a in (%*) do if /i "%%~a"=="--debug" set "DEBUG_FLAG=1"

rem ── 1. .env 配置检查 ──
if not exist ".env" (
    echo [提示] 未找到 .env 配置文件，将使用默认配置启动
    echo        如需自定义数据库/密钥，请复制 .env.example 为 .env
    echo.
)

rem ── 2. 端口占用检查（默认 5000，可用系统环境变量 PORT 覆盖）──
set "APP_PORT=5000"
if defined PORT set "APP_PORT=%PORT%"
powershell -NoProfile -Command ^
  "$p = Get-NetTCPConnection -LocalPort %APP_PORT% -State Listen -ErrorAction SilentlyContinue;" ^
  "if ($p) { $pid0 = ($p | Select-Object -First 1).OwningProcess; Write-Host ('[警告] 端口 ' + %APP_PORT% + ' 已被进程 PID=' + $pid0 + ' 占用，如为旧服务请先运行 stop.bat') }" ^
  "else { Write-Host ('[OK] 端口 ' + %APP_PORT% + ' 可用') }"
echo.

rem ── 3. conda 环境定位（环境名可用 HOSHINO_CONDA_ENV 覆盖）──
set "CONDA_ENV=blog_env"
if defined HOSHINO_CONDA_ENV set "CONDA_ENV=%HOSHINO_CONDA_ENV%"
set "CONDA_BAT="
where conda >nul 2>&1
if not errorlevel 1 (
    set "CONDA_BAT=conda"
) else (
    rem PATH 中无 conda：探测常见安装位置
    for %%p in ("D:\anaconda\condabin\conda.bat" "%USERPROFILE%\anaconda3\condabin\conda.bat" "%USERPROFILE%\miniconda3\condabin\conda.bat" "C:\ProgramData\Anaconda3\condabin\conda.bat" "C:\ProgramData\miniconda3\condabin\conda.bat") do (
        if exist "%%~p" set "CONDA_BAT=%%~p"
    )
)
if not defined CONDA_BAT (
    echo [错误] 未找到 conda。请安装 Anaconda/Miniconda，
    echo        或手动激活 %CONDA_ENV% 环境后直接运行：python app.py
    pause
    exit /b 1
)

echo [1/2] 激活 conda 环境 %CONDA_ENV% ...
if "%CONDA_BAT%"=="conda" (
    call conda activate %CONDA_ENV%
) else (
    call "%CONDA_BAT%" activate %CONDA_ENV%
)
if errorlevel 1 (
    echo [错误] conda activate 失败，请检查环境名是否正确
    echo        可通过环境变量 HOSHINO_CONDA_ENV 指定其他环境
    pause
    exit /b 1
)
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 环境激活后 python 仍不可用，请检查 conda 安装
    pause
    exit /b 1
)
echo [OK] 环境激活成功
echo.

rem ── 4. 启动 Flask + Worker ──
echo [2/2] 启动 app.py (Flask + Worker) ...
if defined DEBUG_FLAG (
    set "DEBUG=true"
    echo [调试模式] DEBUG=true（端口默认绑定 127.0.0.1）
)
echo 按 Ctrl+C 停止服务
echo ============================================
python app.py
set "EXIT_CODE=%errorlevel%"

echo.
echo ============================================
if "%EXIT_CODE%"=="0" (
    echo  服务已正常退出
) else (
    echo  服务异常退出（退出码 %EXIT_CODE%）
    echo  请查看上方日志或 blog/logs/error.log 排查
)
echo ============================================
pause
exit /b %EXIT_CODE%
