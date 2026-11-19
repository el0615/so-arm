$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDir
& (Join-Path $projectDir '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'guided_test.py')
