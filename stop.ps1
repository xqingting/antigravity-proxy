# Antigravity Proxy - PowerShell 停止脚本
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Port = 8765
$PidFile = Join-Path $ScriptDir ".proxy.pid"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Antigravity Proxy - Windows PowerShell 停止脚本" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

$Stopped = $false

if (Test-Path $PidFile) {
    $PidVal = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($PidVal) {
        $Proc = Get-Process -Id $PidVal -ErrorAction SilentlyContinue
        if ($Proc) {
            Stop-Process -Id $PidVal -Force -ErrorAction SilentlyContinue
            Write-Host "[成功] 已终止代理进程 (PID: $PidVal)" -ForegroundColor Green
            $Stopped = $true
        }
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

# 端口清理兜底
$NetConn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($NetConn) {
    foreach ($conn in $NetConn) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Host "[成功] 释放端口 $Port 占用进程 (PID: $($conn.OwningProcess))" -ForegroundColor Green
        $Stopped = $true
    }
}

if ($Stopped) {
    Write-Host "[完成] 服务已停止。" -ForegroundColor Green
} else {
    Write-Host "[提示] 未检测到正在运行的代理服务。" -ForegroundColor Yellow
}
