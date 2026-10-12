# SayMyName one-line installer for Windows. Paste this into PowerShell:
#
#   irm https://raw.githubusercontent.com/YellowElonMusk/Startup-name-finder/main/install.ps1 | iex
#
# Downloads SayMyName into %LOCALAPPDATA%\SayMyName, adds a "SayMyName" shortcut
# to the Desktop and Start menu, and starts it. Running it again updates the app.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$repo = 'https://github.com/YellowElonMusk/Startup-name-finder/archive/refs/heads/main.zip'
$dest = Join-Path $env:LOCALAPPDATA 'SayMyName'
$tmp = Join-Path $env:TEMP ('saymyname-' + [guid]::NewGuid())

Write-Host 'Downloading SayMyName...'
New-Item -ItemType Directory -Force $tmp | Out-Null
Invoke-WebRequest -UseBasicParsing -Uri $repo -OutFile "$tmp\app.zip"
Expand-Archive "$tmp\app.zip" -DestinationPath $tmp -Force
$src = Get-ChildItem $tmp -Directory | Select-Object -First 1

# Copy over any previous install; its .venv is kept so updates start fast.
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item -Path "$($src.FullName)\*" -Destination $dest -Recurse -Force
Remove-Item $tmp -Recurse -Force

$launcher = Join-Path $dest 'start_namestack.bat'
$shell = New-Object -ComObject WScript.Shell
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'SayMyName.lnk'
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'SayMyName.lnk'
foreach ($path in @($desktop, $startMenu)) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $launcher
    $lnk.WorkingDirectory = $dest
    $lnk.Description = 'Find a startup name and check if the domain is free'
    $lnk.Save()
}

Write-Host "Installed in $dest"
Write-Host 'Next time, double-click "SayMyName" on your Desktop.'
Write-Host 'Starting SayMyName...'
Start-Process -FilePath $launcher -WorkingDirectory $dest
