<#
Daily Quartr calendar sweep for Roz, driven by Windows Task Scheduler.

TEMPORARY. This runs the scan on the laptop until AWS is live; at that point the
scanning module moves there and this task must be REMOVED rather than left
running alongside it -- two schedulers publishing into the same inbox would race
on the same <TICKER>-<PERIOD>.event.json filenames.

Exit code is propagated so Task Scheduler's "Last Run Result" is meaningful.
Output is appended to a month-stamped log under host_quartr/logs (gitignored),
so a missed or failing run is auditable after the fact rather than invisible.
#>

# Deliberately NOT 'Stop'. Python's logging writes INFO to stderr, and with
# ErrorActionPreference='Stop' PowerShell promotes a native command's stderr to a
# TERMINATING error -- so a perfectly healthy sweep exited 1 and every scheduled
# run would have reported failure. Success is judged by $LASTEXITCODE instead.
$ErrorActionPreference = 'Continue'

$repo = 'C:\Users\BobbyWhittaker\OneDrive - Cassius Capital\Desktop\Earnings Call Summarizer'
$python = Join-Path $repo '.venv\Scripts\python.exe'

$logDir = Join-Path $repo 'host_quartr\logs'
New-Item -ItemType Directory -Force -Path $logDir -ErrorAction Stop | Out-Null
$log = Join-Path $logDir ('sweep-{0}.log' -f (Get-Date -Format 'yyyy-MM'))

Set-Location $repo
$stamp = (Get-Date).ToString('u')
Add-Content $log "=== $stamp sweep start ==="

$code = 0
try {
    & $python -m services.earnings_monitor.host_automation calendar `
        --source mcp --horizon-days 100 --verify-within-days 7 2>&1 |
        Add-Content $log
    $code = $LASTEXITCODE
}
catch {
    Add-Content $log "ERROR: $_"
    $code = 1
}

Add-Content $log "=== $stamp sweep end (exit $code) ==="
exit $code
