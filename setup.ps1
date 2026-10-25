# Smart Attendance - cài đặt một lần (Windows PowerShell 5.1+)
#   Chạy:  powershell -ExecutionPolicy Bypass -File setup.ps1
# Script KHÔNG xoá môi trường hay dữ liệu sẵn có (database, dataset, models).
param(
    [switch]$SkipFrontend
)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$Root = $PSScriptRoot
$Core = Join-Path $Root 'attendance_system'
$Venv = Join-Path $Core '.venv'
$Py = Join-Path $Venv 'Scripts\python.exe'
$NodeVersion = 'v24.22.1'
$ToolsNode = Join-Path $Root 'tools\node'

function Step($t) { Write-Host ''; Write-Host "==> $t" -ForegroundColor Green }
function Fail($t) { Write-Host ''; Write-Host "[LOI] $t" -ForegroundColor Red; exit 1 }
function Warn($t) { Write-Host "[CANH BAO] $t" -ForegroundColor Yellow }

# ------------------------------------------------------------------ Python
Step 'Kiểm tra Python'
if (-not (Test-Path $Py)) {
    $base = $null
    foreach ($v in @('3.11', '3.12')) {
        try { $out = & py "-$v" -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0 -and $out) { $base = $out.Trim(); break } } catch {}
    }
    if (-not $base) {
        Fail "Không tìm thấy Python 3.11 (khuyến nghị) hoặc 3.12. Cài tại https://www.python.org/downloads/release/python-3119/ (tick 'Add python.exe to PATH'), rồi chạy lại setup.ps1."
    }
    Write-Host "Tạo môi trường ảo tại $Venv bằng $base"
    & $base -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail 'Không tạo được môi trường ảo Python.' }
} else {
    Write-Host "Dùng môi trường có sẵn: $Venv"
}
$pyver = & $Py -c "import sys; print('%d.%d.%d' % sys.version_info[:3])"
Write-Host "Python $pyver"
if (-not ($pyver -like '3.11.*' -or $pyver -like '3.12.*')) { Warn "Đã kiểm thử với Python 3.11.9. Phiên bản $pyver có thể thiếu wheel cho insightface/onnxruntime." }

Step 'Cài thư viện Python (backend + nhận diện)'
& $Py -m pip install --disable-pip-version-check -r (Join-Path $Core 'requirements.txt') -r (Join-Path $Root 'requirements-web.txt')
if ($LASTEXITCODE -ne 0) { Fail 'pip install thất bại. Kiểm tra kết nối mạng; với insightface trên Windows có thể cần "Microsoft C++ Build Tools".' }

# ------------------------------------------------------------------ Models
Step 'Kiểm tra model nhận diện'
$detDir = Join-Path $Core 'models\insightface\models\buffalo_sc'
$missingDet = @('det_500m.onnx') | Where-Object { -not (Test-Path (Join-Path $detDir $_)) }
if ($missingDet) {
    Warn "Thiếu detector SCRFD: $($missingDet -join ', ') trong $detDir"
    Write-Host 'Thử tải tự động detector buffalo_sc...'
    & $Py -c "import sys; sys.path.insert(0, r'$Core'); from functions.face_detector import FaceDetector; FaceDetector(); print('OK')"
} else { Write-Host "Đủ detector SCRFD: $detDir" }

$adaDir = Join-Path $Core 'models\cvlface_adaface_ir101_webface12m'
$adaModel = Join-Path $adaDir 'pretrained_model\model.pt'
if (-not (Test-Path $adaModel)) {
    Warn "Thiếu model AdaFace IR101 WebFace12M tại $adaDir"
    Write-Host "Tải checkpoint chính thức minchul/cvlface_adaface_ir101_webface12m từ HuggingFace..."
    & $Py -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='minchul/cvlface_adaface_ir101_webface12m', local_dir=r'$adaDir'); print('AdaFace download OK')"
} else { Write-Host "Đủ model AdaFace IR101 WebFace12M: $adaModel" }

if (-not (Test-Path (Join-Path $Core 'models\anti_spoof_minifas.onnx'))) {
    Write-Host 'Không có anti_spoof_minifas.onnx: chống giả mạo giữ chế độ TẮT (mặc định). Xem README nếu muốn bật.'
}

# ------------------------------------------------------------------ Node + frontend
if (-not $SkipFrontend) {
    Step 'Kiểm tra Node.js'
    $node = $null
    $sys = Get-Command node -ErrorAction SilentlyContinue
    if ($sys) {
        $v = (& node --version).Trim()
        if ([int]($v.TrimStart('v').Split('.')[0]) -ge 20) { $node = Split-Path $sys.Source }
        else { Warn "Node $v quá cũ (cần >= 20); dùng bản portable." }
    }
    if (-not $node -and (Test-Path (Join-Path $ToolsNode 'node.exe'))) { $node = $ToolsNode }
    if (-not $node) {
        Write-Host "Tải Node.js $NodeVersion portable vào tools\node (không cài vào hệ thống)..."
        $zip = Join-Path $env:TEMP "node-$NodeVersion-win-x64.zip"
        $base = "https://nodejs.org/dist/$NodeVersion"
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest "$base/node-$NodeVersion-win-x64.zip" -OutFile $zip -UseBasicParsing
            $sums = (Invoke-WebRequest "$base/SHASUMS256.txt" -UseBasicParsing).Content
        } catch { Fail "Không tải được Node.js ($($_.Exception.Message)). Cài Node.js LTS từ https://nodejs.org rồi chạy lại." }
        $expected = ($sums -split "`n" | Where-Object { $_ -match "node-$NodeVersion-win-x64.zip" }) -split '\s+' | Select-Object -First 1
        $actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
        if ($expected -ne $actual) { Remove-Item $zip; Fail 'Checksum Node.js không khớp, đã huỷ.' }
        $tmp = Join-Path $Root 'tools\_node_tmp'
        Expand-Archive $zip -DestinationPath $tmp -Force
        Move-Item (Join-Path $tmp "node-$NodeVersion-win-x64") $ToolsNode
        Remove-Item $tmp -Recurse -Force; Remove-Item $zip
        $node = $ToolsNode
    }
    $env:Path = "$node;$env:Path"
    Write-Host "Node $(& node --version) / npm $(& npm.cmd --version)"

    Step 'Cài thư viện giao diện (npm)'
    Push-Location (Join-Path $Root 'frontend')
    try {
        if (Test-Path 'package-lock.json') { & npm.cmd ci --no-audit --no-fund } else { & npm.cmd install --no-audit --no-fund }
        if ($LASTEXITCODE -ne 0) { Fail 'npm install thất bại.' }
        Step 'Build giao diện'
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { Fail 'Build giao diện thất bại.' }
    } finally { Pop-Location }
}

Step 'Kiểm tra nhanh backend'
& $Py -c "import sys; sys.path.insert(0, r'$Root'); import onnxruntime, backend.app; print('Backend OK')"
if ($LASTEXITCODE -ne 0) { Fail 'Import backend thất bại (xem lỗi phía trên).' }

Write-Host ''
Write-Host 'HOÀN TẤT. Chạy ứng dụng bằng:  Chay-SmartAttendance.cmd   (hoặc: powershell -ExecutionPolicy Bypass -File run.ps1)' -ForegroundColor Green
