@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set "DIR=%~dp0"
set "PORT=8765"
set "PID_FILE=%DIR%.proxy.pid"

echo ----------------------------------------------------
echo   Antigravity Proxy - Windows 停止脚本
echo ----------------------------------------------------

set "FOUND=0"

:: 优先根据 PID 文件杀死
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    if defined OLD_PID (
        taskkill /f /pid !OLD_PID! >nul 2>&1
        if !errorlevel! equ 0 (
            echo [成功] 已安全终止 PID 为 !OLD_PID! 的代理进程。
            set "FOUND=1"
        )
    )
    del /f /q "%PID_FILE%" >nul 2>&1
)

:: 兜底通过端口清理
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
    if !errorlevel! equ 0 (
        echo [成功] 释放端口 %PORT% 上的残留进程 (PID: %%a)。
        set "FOUND=1"
    )
)

if "!FOUND!"=="1" (
    echo [完成] Antigravity Proxy 代理服务已停止。
) else (
    echo [提示] 未发现正在运行的代理服务。
)

exit /b 0
