@echo off
REM ============================================
REM  HOSHINO Blog 本地质量校验（等价 CI 的 lint + test）
REM  用法：在 cmd 中运行 check.bat
REM  说明：SQLite 后端跑全量测试，无需 MySQL
REM ============================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set TEST_DB_BACKEND=sqlite
set SECRET_KEY=local-check-secret
set WORKER_PROCESS=1

echo ============================================
echo  [1/2] 语法与未定义名检查
echo ============================================
python -m ruff check --select E9,F63,F7,F82 .
if errorlevel 1 (
    echo [FAIL] ruff 检查未通过
    pause
    exit /b 1
)

echo.
echo ============================================
echo  [2/2] 测试（SQLite 后端，无需 MySQL）
echo ============================================
python -m pytest
if errorlevel 1 (
    echo [FAIL] 测试未通过
    pause
    exit /b 1
)

echo.
echo [OK] 全部检查通过
pause
