$ErrorActionPreference = 'Stop'
$projectRoot = Join-Path $PSScriptRoot 'para_github'
$pythonCandidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs/Python/Python312/python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs/Python/Python313/python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs/Python/Python314/python.exe')
)
$projectPython = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $projectPython) { throw 'Falta Python 3.12–3.14. Instala Python 3.12 para tu usuario.' }
& $projectPython (Join-Path $projectRoot 'tools/automatizar.py') @args
exit $LASTEXITCODE
