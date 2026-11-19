@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set "DIR=%~dp0"
set "PORT=8765"
set "MODEL=gemini-3.8-flash"
set "EFFORT=high"
set "TIMEOUT=300"
set "MAX_CONCURRENCY=5"
set "PID_FILE=%DIR%.proxy.pid"
set "LOG_FILE=%DIR%proxy.log"

echo ----------------------------------------------------
echo   Antigravity Proxy - Windows 启动脚本
echo ----------------------------------------------------

:: 探测 Python 命令
set "PY_CMD="
where python >nul 2>nul
if %errorlevel% equ 0 (
    set "PY_CMD=python"
) else (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY_CMD=py"
    ) else (
        where python3 >nul 2>nul
        if %errorlevel% equ 0 (
            set "PY_CMD=python3"
        )
    )
)

if "%PY_CMD%"=="" (
    echo [错误] 未检测到 Python 环境！请先安装 Python 3.10+ 并勾选 "Add to PATH"。
    pause
    exit /b 1
)

:: 检查是否已在运行
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    tasklist /fi "PID eq !OLD_PID!" 2>nul | findstr "!OLD_PID!" >nul
    if !errorlevel! equ 0 (
        echo [提示] 代理服务已经在运行中 (PID: !OLD_PID!)
        echo        接口地址: http://127.0.0.1:%PORT%/v1
        echo        若需停止，请运行 stop.bat
        exit /b 0
    )
)

echo [启动中] 正在以端口 %PORT%、模型 %MODEL%、思考级别 %EFFORT%、超时 %TIMEOUT%s、最大并发 %MAX_CONCURRENCY% 启动...
start /b "" %PY_CMD% "%DIR%agy_proxy.py" --port %PORT% --model %MODEL% --effort %EFFORT% --timeout %TIMEOUT% --max-concurrency %MAX_CONCURRENCY% > "%LOG_FILE%" 2>&1

:: 获取刚才启动的进程 PID 并写入 PID 文件
timeout /t 1 /nobreak >nul
for /f "tokens=2" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    set "NEW_PID=%%a"
)

if defined NEW_PID (
    echo !NEW_PID! > "%PID_FILE%"
    echo [成功] Antigravity Proxy 启动成功！
    echo        PID:      !NEW_PID!
    echo        端点:     http://127.0.0.1:%PORT%/v1
    echo        日志:     %LOG_FILE%
) else (
    echo [提示] 服务已在后台拉起，请通过 status.bat 检查健康状态。
)

echo.
echo 可通过 status.bat 查看运行状态，或运行 %PY_CMD% test_client.py 进行连通性验证。
exit /b 0
