# Smart Attendance - khởi động web app tại http://127.0.0.1:8000
#   Chạy:  powershell -ExecutionPolicy Bypass -File run.ps1 [-Port 8000] [-NoBrowser]
param(
    [int]$Port = 8000,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$Root = $PSScriptRoot
$Py = Join-Path $Root 'attendance_system\.venv\Scripts\python.exe'

if (-not (Test-Path $Py)) {
    Write-Host '[LOI] Chưa có môi trường Python. Hãy chạy setup.ps1 trước.' -ForegroundColor Red
    Read-Host 'Nhấn Enter để đóng'
    exit 1
}
if (-not (Test-Path (Join-Path $Root 'frontend\dist\index.html'))) {
    Write-Host '[CANH BAO] Chưa build giao diện (frontend\dist). Hãy chạy setup.ps1.' -ForegroundColor Yellow
}
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "[LOI] Cổng $Port đang được dùng (có thể ứng dụng đã chạy). Mở http://127.0.0.1:$Port hoặc chạy: run.ps1 -Port 8010" -ForegroundColor Red
    Read-Host 'Nhấn Enter để đóng'
    exit 1
}

$url = "http://127.0.0.1:$Port"
if (-not $NoBrowser) {
    # Open the browser once the server answers (model loading continues in the background).
    Start-Job -ArgumentList $url -ScriptBlock {
        param($u)
        for ($i = 0; $i -lt 60; $i++) {
            try { Invoke-WebRequest "$u/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process $u; break } catch { Start-Sleep -Milliseconds 500 }
        }
    } | Out-Null
}

Set-Location $Root
& $Py -m backend --host 127.0.0.1 --port $Port
