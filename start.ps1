# Antigravity Proxy - PowerShell 启动脚本
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Port = 8765
$Model = "gemini-3.8-flash"
$Effort = "medium"
$Timeout = 300
$MaxConcurrency = 5
$PidFile = Join-Path $ScriptDir ".proxy.pid"
$LogFile = Join-Path $ScriptDir "proxy.log"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Antigravity Proxy - Windows PowerShell 启动脚本" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 检测 Python
$PyCmd = $null
if (Get-Command "python" -ErrorAction SilentlyContinue) {
    $PyCmd = "python"
} elseif (Get-Command "py" -ErrorAction SilentlyContinue) {
    $PyCmd = "py"
} elseif (Get-Command "python3" -ErrorAction SilentlyContinue) {
    $PyCmd = "python3"
}

if (-not $PyCmd) {
    Write-Host "[错误] 未检测到 Python 环境！请先安装 Python 3.10+。" -ForegroundColor Red
    exit 1
}

# 检查是否已运行
if (Test-Path $PidFile) {
    $OldPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($OldPid) {
        $Proc = Get-Process -Id $OldPid -ErrorAction SilentlyContinue
        if ($Proc) {
            Write-Host "[提示] 代理服务已经在运行中 (PID: $OldPid)" -ForegroundColor Yellow
            Write-Host "       接口端点: http://127.0.0.1:$Port/v1"
            Write-Host "       停止命令: .\stop.ps1"
            exit 0
        }
    }
}

Write-Host "[启动中] 正在以端口 $Port、模型 $Model、并发数 $MaxConcurrency 启动..." -ForegroundColor Green

$Args = @(
    (Join-Path $ScriptDir "agy_proxy.py"),
    "--port", $Port,
    "--model", $Model,
    "--effort", $Effort,
    "--timeout", $Timeout,
    "--max-concurrency", $MaxConcurrency
)

$Process = Start-Process -FilePath $PyCmd -ArgumentList $Args -RedirectStandardOutput $LogFile -RedirectStandardError $LogFile -NoNewWindow -PassThru

if ($Process) {
    $Process.Id | Out-File -FilePath $PidFile -Encoding utf8
    Start-Sleep -Seconds 1
    Write-Host "[成功] Antigravity Proxy 启动成功！" -ForegroundColor Green
    Write-Host "       PID:      $($Process.Id)"
    Write-Host "       API 端点: http://127.0.0.1:$Port/v1"
    Write-Host "       日志文件: $LogFile"
} else {
    Write-Host "[错误] 启动进程失败，请检查 Python 及依赖！" -ForegroundColor Red
}
