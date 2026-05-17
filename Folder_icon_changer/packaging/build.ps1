$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$distRoot = "..\\dist\\app"
$binDir = "..\\dist\\app\\bin"
$icoDir = "..\\dist\\app\\ico"
$specDir = "."

if (Test-Path $distRoot) {
  Remove-Item -Recurse -Force $distRoot
}

New-Item -ItemType Directory -Force -Path $binDir | Out-Null

Copy-Item -Recurse -Force "..\\ico" $icoDir

python -m PyInstaller `
  --noconfirm --clean --onefile --noconsole `
  --distpath $binDir `
  --workpath "..\\build\\pyinstaller\\folder_icon_changer" `
  --specpath $specDir `
  --icon "..\\ico\\folder11.ico" `
  "..\\folder_icon_changer.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m PyInstaller `
  --noconfirm --clean --onefile --noconsole `
  --distpath $binDir `
  --workpath "..\\build\\pyinstaller\\icon_creator" `
  --specpath $specDir `
  --hidden-import "PyQt6.QtSvg" `
  --icon "..\\ico\\folder11.ico" `
  "..\\icon_creator.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m PyInstaller `
  --noconfirm --clean --onefile --noconsole `
  --distpath $binDir `
  --workpath "..\\build\\pyinstaller\\icon_downloader" `
  --specpath $specDir `
  --icon "..\\ico\\folder11.ico" `
  "..\\icon_downloader.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
