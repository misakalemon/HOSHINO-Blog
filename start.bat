@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Hoshino Blog 启动器
echo ============================================
echo  工作目录: %cd%
echo.

if not exist ".env" (
    echo [提示] 未找到 .env 配置文件，将使用默认配置启动
    echo        如需自定义数据库/密钥，请复制 .env.example 为 .env
    echo.
)

echo [1/2] 正在激活 conda 环境 blog_env ...
call conda activate blog_env
if errorlevel 1 (
    echo [错误] conda activate 失败，请检查环境名称
    pause
    exit /b 1
)
echo [OK] 环境激活成功
echo.

echo [2/2] 启动 app.py (Flask + Worker) ...
echo 按 Ctrl+C 停止服务
echo ============================================
python app.py

echo.
echo ============================================
echo  服务已停止（退出码 %errorlevel%）
echo ============================================
pause
