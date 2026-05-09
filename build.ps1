$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt pytest
& ".\.venv\Scripts\python.exe" -m pytest

if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}
if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}
if (Test-Path "release") {
    Remove-Item -Recurse -Force "release"
}

& ".\.venv\Scripts\python.exe" -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "ClipNoteAI" `
    --collect-all customtkinter `
    --collect-binaries imageio_ffmpeg `
    --hidden-import yt_dlp `
    "src\clipnote_ai\__main__.py"

New-Item -ItemType Directory -Force -Path "release\ClipNoteAI\outputs" | Out-Null
New-Item -ItemType File -Force -Path "release\ClipNoteAI\outputs\.keep" | Out-Null
Copy-Item "dist\ClipNoteAI.exe" "release\ClipNoteAI\ClipNoteAI.exe"
$Guide = Get-ChildItem -Path "." -Filter "*.html" | Select-Object -First 1
if ($null -eq $Guide) {
    throw "HTML guide file was not found."
}
Copy-Item $Guide.FullName (Join-Path "release\ClipNoteAI" $Guide.Name)
Compress-Archive -Path "release\ClipNoteAI\*" -DestinationPath "release\ClipNoteAI.zip" -Force

Write-Host ""
Write-Host "완료:"
Write-Host "  release\ClipNoteAI\ClipNoteAI.exe"
Write-Host ("  release\ClipNoteAI\" + $Guide.Name)
Write-Host "  release\ClipNoteAI.zip"
