﻿param([switch]$WebOnly)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Client = Join-Path $Root 'novel_agent\client'

$env:NO_PROXY = '*'
$env:HTTP_PROXY = ''
$env:HTTPS_PROXY = ''
$env:ALL_PROXY = ''

$ChildProcesses = [System.Collections.Generic.List[int]]::new()

function Register-Tree {
    param([int]$ParentId)
    try {
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentId" -ErrorAction SilentlyContinue
        foreach ($c in $children) {
            if ($ChildProcesses -notcontains $c.ProcessId) {
                $ChildProcesses.Add($c.ProcessId) | Out-Null
                Register-Tree -ParentId $c.ProcessId
            }
        }
    } catch { }
}

function Stop-Tree {
    param([int]$RootId)
    Register-Tree -ParentId $RootId
    if ($ChildProcesses -notcontains $RootId) {
        $ChildProcesses.Add($RootId) | Out-Null
    }
    $ChildProcesses.Sort()
    $ChildProcesses.Reverse()
    foreach ($id in $ChildProcesses) {
        try {
            $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
            if ($proc -and -not $proc.HasExited) {
                Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
                Write-Host "已终止进程 $id ($($proc.ProcessName))" -ForegroundColor DarkGray
            }
        } catch { }
    }
    $ChildProcesses.Clear()
}

try {
    Write-Host '启动后端 (python -m novel_agent) ...' -ForegroundColor Yellow
    $be = Start-Process python -ArgumentList '-m','novel_agent' -WorkingDirectory $Root -WindowStyle Normal -PassThru

    Write-Host '启动前端 ...' -ForegroundColor Yellow
    Set-Location $Client
    if ($WebOnly) { npm run dev } else { npm run tauri dev }
}
finally {
    Set-Location $Root
    Write-Host '正在清理所有服务进程...' -ForegroundColor Yellow
    if ($be -and -not $be.HasExited) {
        Stop-Tree -RootId $be.Id
    }
    $ChildProcesses.Clear()
    $myPid = $PID
    try {
        $stale = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='uvicorn.exe' OR Name='node.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.ProcessId -ne $myPid -and $_.ParentProcessId -ne $myPid }
        foreach ($p in $stale) {
            $cmd = $p.CommandLine
            if ($cmd -and ($cmd -match 'novel_agent' -or $cmd -match 'tauri' -or $cmd -match 'vite')) {
                try {
                    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                    Write-Host "已清理残留进程 $($p.ProcessId)" -ForegroundColor DarkGray
                } catch { }
            }
        }
    } catch { }
    Write-Host '所有服务已退出' -ForegroundColor Green
}
