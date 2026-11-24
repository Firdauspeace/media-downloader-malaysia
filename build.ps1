$ErrorActionPreference = 'Stop'
$appName = 'Media Downloader Malaysia'
$icon = Join-Path $PSScriptRoot 'icon.ico'
$bundledTools = foreach ($command in 'yt-dlp.exe', 'ffmpeg.exe', 'ffprobe.exe', 'node.exe') {
    $executable = (Get-Command $command -CommandType Application | Select-Object -First 1).Source
    '--add-data'
    "${executable}:tools"
}

python -m PyInstaller --noconfirm --onefile --windowed --noupx --exclude-module numpy `
    --name $appName --icon $icon --add-data "${icon}:." @bundledTools `
    --add-data ((Join-Path $PSScriptRoot 'FFmpeg-LICENSE.txt') + ':tools') `
    --workpath (Join-Path $PSScriptRoot 'build') --distpath (Join-Path $PSScriptRoot 'dist') `
    --specpath $PSScriptRoot (Join-Path $PSScriptRoot 'media_downloader.py')

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller exited with code $LASTEXITCODE."
}
