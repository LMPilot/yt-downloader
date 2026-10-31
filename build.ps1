# Збирає dist\yt-downloader.exe (один файл, без консолі).
#
# Використання (PowerShell, у папці репозиторію):
#   powershell -ExecutionPolicy Bypass -File build.ps1
#   powershell -ExecutionPolicy Bypass -File build.ps1 -SkipTests
#
# Якщо ffmpeg.exe знайдено в PATH, його копія кладеться поруч у dist\,
# щоб папку dist можна було просто перенести на інший компʼютер.

param(
    [switch]$SkipTests,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Команда завершилась з помилкою ($LASTEXITCODE): $File $($Arguments -join ' ')"
    }
}

if (-not $SkipInstall) {
    Write-Host "==> Встановлення залежностей" -ForegroundColor Cyan
    Invoke-Checked python @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Checked python @("-m", "pip", "install", "-r", "requirements-dev.txt", "pyinstaller")
}

if (-not $SkipTests) {
    Write-Host "==> Тести" -ForegroundColor Cyan
    Invoke-Checked python @("-m", "pytest", "-q")
}

$version = (& python -c "from version import __version__; print(__version__)").Trim()
if ($LASTEXITCODE -ne 0) { throw "Не вдалося прочитати версію з version.py" }
$versionFile = Join-Path ([IO.Path]::GetTempPath()) "yt-downloader-version-info.txt"
Invoke-Checked python @("version_info.py", $versionFile)

Write-Host "==> Збірка yt-downloader.exe $version" -ForegroundColor Cyan
Invoke-Checked python @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean",
    "--onefile", "--windowed",
    "--name", "yt-downloader",
    "--version-file", $versionFile,
    "--icon", "assets\icon.ico",
    "--add-data", "assets\icon.ico;assets",
    "--add-data", "assets\icon.png;assets",
    "--collect-data", "customtkinter",
    "--collect-submodules", "yt_dlp",
    "--collect-all", "yt_dlp_ejs",
    "--hidden-import", "Cryptodome",
    "--hidden-import", "websockets",
    "--hidden-import", "brotli",
    "--hidden-import", "mutagen",
    "--hidden-import", "certifi",
    "app.py"
)

$exe = Join-Path $PSScriptRoot "dist\yt-downloader.exe"
if (-not (Test-Path $exe)) {
    throw "Не знайдено $exe"
}

$ffmpeg = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
if ($ffmpeg) {
    $source = $ffmpeg.Source
    # Chocolatey кладе в PATH лише «прокладку» (shim), яку не можна копіювати —
    # шукаємо справжній ffmpeg.exe у папці пакета.
    if ($source -like "*\chocolatey\bin\*") {
        $chocoLib = Join-Path (Split-Path (Split-Path $source)) "lib"
        $real = Get-ChildItem -Path $chocoLib -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notlike "*\shims\*" } | Select-Object -First 1
        $source = if ($real) { $real.FullName } else { $null }
    }
    if ($source) {
        Copy-Item $source (Join-Path $PSScriptRoot "dist\ffmpeg.exe") -Force
        Write-Host "ffmpeg.exe скопійовано в dist\ ($source)" -ForegroundColor Green
    }
}

# Контрольна сума для автооновлення (формат sha256sum: «<hash>  <файл>»).
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$exe.sha256", "$hash  yt-downloader.exe`n", [Text.Encoding]::ASCII)

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "Готово: $exe, версія $version ($size МБ)" -ForegroundColor Green
Write-Host "SHA256: $hash"
