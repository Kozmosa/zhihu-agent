param(
    [string]$Python = 'python',
    [string]$WorkRoot = (Join-Path $PSScriptRoot '.backend-work'),
    [switch]$LiveDeepSeek
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$evidenceRoot = Join-Path $WorkRoot ('checks-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $evidenceRoot | Out-Null
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$checks = [System.Collections.Generic.List[object]]::new()

function Invoke-BackendCheck {
    param([string]$Name, [string[]]$Arguments)
    $savedPreference = $ErrorActionPreference
    try {
        # Windows PowerShell wraps native stderr warnings as non-terminating errors.
        $ErrorActionPreference = 'Continue'
        & $Python @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $evidenceRoot ($Name + '.log'))
        $checkExitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $savedPreference }
    $checks.Add([pscustomobject]@{ name = $Name; exit_code = $checkExitCode; passed = ($checkExitCode -eq 0) })
}

Push-Location -LiteralPath $projectRoot
try {
    Invoke-BackendCheck -Name 'pytest' -Arguments @(
        '-m', 'pytest', 'tests', '-q', '-p', 'no:cacheprovider',
        '--basetemp', (Join-Path $evidenceRoot 'pytest-tmp'),
        '--junitxml', (Join-Path $evidenceRoot 'pytest.xml')
    )
    Invoke-BackendCheck -Name 'ruff' -Arguments @('-m', 'ruff', 'check', '--no-cache', 'src\zhijing', 'tests', 'scripts', 'src\verify_model.py', 'src\verify_http.py')
    Invoke-BackendCheck -Name 'format' -Arguments @('-m', 'ruff', 'format', '--check', '--output-format', 'concise', '--no-cache', 'src\zhijing', 'tests', 'scripts', 'src\verify_model.py', 'src\verify_http.py')
    Invoke-BackendCheck -Name 'entry' -Arguments @('main.py', '--check')
    Invoke-BackendCheck -Name 'http' -Arguments @(
        (Join-Path $PSScriptRoot 'verify_http.py'), '--work-root', (Join-Path $evidenceRoot 'formal-http')
    )
    foreach ($provider in @('extractive', 'ollama', 'openai')) {
        Invoke-BackendCheck -Name ('smoke-' + $provider) -Arguments @(
            (Join-Path $PSScriptRoot 'verify_model.py'), '--provider', $provider, '--mock', '--workflow',
            '--work-root', (Join-Path $evidenceRoot ('smoke-' + $provider)),
            '--report', (Join-Path $evidenceRoot ($provider + '.json'))
        )
    }
    if ($LiveDeepSeek) {
        # getpass reads the key interactively; never put it in command arguments or a log.
        & $Python (Join-Path $PSScriptRoot 'verify_model.py') --provider openai --live --workflow `
            --url 'https://api.deepseek.com' --model 'deepseek-v4-flash' --thinking disabled `
            --prompt-key --work-root (Join-Path $evidenceRoot 'deepseek-live') `
            --report (Join-Path $evidenceRoot 'deepseek-live.json')
        $checks.Add([pscustomobject]@{ name = 'deepseek-live'; exit_code = $LASTEXITCODE; passed = ($LASTEXITCODE -eq 0) })
    }
    $passed = @($checks | Where-Object { -not $_.passed }).Count -eq 0
    [pscustomobject]@{
        checked_at = (Get-Date).ToUniversalTime().ToString('o')
        passed = $passed
        checks = $checks.ToArray()
        live_requested = [bool]$LiveDeepSeek
        evidence = $evidenceRoot
    } | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $evidenceRoot 'summary.json')
    Write-Output ('Evidence: ' + $evidenceRoot)
    if (-not $passed) { exit 1 }
}
finally {
    Pop-Location
}
