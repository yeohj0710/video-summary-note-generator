$ErrorActionPreference = "Stop"

$DevRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProgramFilesDir = Split-Path -Parent $DevRoot
$RepoRoot = Split-Path -Parent $ProgramFilesDir
$ProgramDirName = -join ([char[]](0xD504, 0xB85C, 0xADF8, 0xB7A8, 0x20, 0xAD6C, 0xC131, 0x20, 0xD30C, 0xC77C))
$NotesDirName = -join ([char[]](0xC0DD, 0xC131, 0xB41C, 0x20, 0xB178, 0xD2B8))
$GuideFileName = (-join ([char[]](0xC0AC, 0xC6A9, 0xC124, 0xBA85, 0xC11C))) + ".html"
$ApiGuideFileName = "openai_api_key_guide.html"
$SourceGuideFileName = "media_source_guide.html"
$ExeBaseName = -join ([char[]](0xC601, 0xC0C1, 0x00B7, 0xC74C, 0xC131, 0x20, 0xC694, 0xC57D, 0x20, 0xB178, 0xD2B8, 0x20, 0xC0DD, 0xC131, 0xAE30))
$ExeFileName = $ExeBaseName + ".exe"
Set-Location $DevRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt pytest
& ".\.venv\Scripts\python.exe" -m pytest

if (Test-Path "build") {
    Remove-Item -LiteralPath "build" -Recurse -Force
}
if (Test-Path "dist") {
    Remove-Item -LiteralPath "dist" -Recurse -Force
}

& ".\.venv\Scripts\python.exe" -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name $ExeBaseName `
    --icon "assets\clipnote.ico" `
    --contents-directory $ProgramDirName `
    --add-data "assets\clipnote.ico;assets" `
    --collect-all customtkinter `
    --collect-all docx `
    --collect-all reportlab `
    --collect-binaries imageio_ffmpeg `
    --hidden-import yt_dlp `
    "src\clipnote_ai\__main__.py"

$BuiltAppDir = Join-Path $DevRoot ("dist\" + $ExeBaseName)
$BuiltExe = Join-Path $BuiltAppDir $ExeFileName
$BuiltRuntimeDir = Join-Path $BuiltAppDir $ProgramDirName

if (-not (Test-Path $BuiltExe)) {
    throw "Built exe was not found: $BuiltExe"
}
if (-not (Test-Path $BuiltRuntimeDir)) {
    throw "Built runtime folder was not found: $BuiltRuntimeDir"
}

$OldExeNames = @(
    "ClipNoteAI.exe",
    ((-join ([char[]](0xB3D9, 0xC601, 0xC0C1, 0x20, 0xC694, 0xC57D, 0x20, 0xB178, 0xD2B8, 0x20, 0xC0DD, 0xC131, 0xAE30))) + ".exe")
)
foreach ($OldExeName in $OldExeNames) {
    $OldExe = Join-Path $RepoRoot $OldExeName
    if (Test-Path $OldExe) {
        Remove-Item -LiteralPath $OldExe -Force
    }
}
Copy-Item $BuiltExe (Join-Path $RepoRoot $ExeFileName) -Force

New-Item -ItemType Directory -Force -Path $ProgramFilesDir | Out-Null
$DevRootResolved = (Resolve-Path $DevRoot).Path
$PreservedProgramFiles = @(
    (Join-Path $ProgramFilesDir "github-download-zip.png")
)
Get-ChildItem $ProgramFilesDir -Force | ForEach-Object {
    $ItemPath = (Resolve-Path $_.FullName).Path
    if ($ItemPath -ne $DevRootResolved -and $ItemPath -notin $PreservedProgramFiles) {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
    }
}
Copy-Item (Join-Path $BuiltRuntimeDir "*") $ProgramFilesDir -Recurse -Force
Copy-Item (Join-Path $DevRoot $ApiGuideFileName) (Join-Path $ProgramFilesDir $ApiGuideFileName) -Force
Copy-Item (Join-Path $DevRoot $SourceGuideFileName) (Join-Path $ProgramFilesDir $SourceGuideFileName) -Force

$NotesDir = Join-Path $RepoRoot $NotesDirName
New-Item -ItemType Directory -Force -Path $NotesDir | Out-Null

$Guide = Join-Path $RepoRoot $GuideFileName
if (-not (Test-Path $Guide)) {
    throw "HTML guide file was not found: $Guide"
}

Write-Host ""
Write-Host "Done:"
Write-Host ("  " + $ExeFileName)
Write-Host ("  " + $GuideFileName)
Write-Host ("  " + $NotesDirName + "\")
Write-Host ("  " + $ProgramDirName + "\")
