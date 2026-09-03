@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set "DIR=%~dp0"
set "PORT=8765"
set "PID_FILE=%DIR%.proxy.pid"

echo ----------------------------------------------------
echo   Antigravity Proxy - Windows 状态检查
echo ----------------------------------------------------

if exist "%PID_FILE%" (
    set /p CUR_PID=<"%PID_FILE%"
    echo [PID] 记录 PID: !CUR_PID!
)

curl -s -m 3 http://127.0.0.1:%PORT%/health >nul 2>&1
if %errorlevel% equ 0 (
    echo [状态] 代理服务正在正常运行 (端口: %PORT%)
    echo.
    echo --- 服务健康详细信息 ---
    curl -s http://127.0.0.1:%PORT%/health
    echo.
    echo.
    echo --- 统计概览 ---
    curl -s http://127.0.0.1:%PORT%/v1/stats
    echo.
) else (
    echo [状态] 代理服务未运行或无法连接 (http://127.0.0.1:%PORT%)
)

echo.
exit /b 0
