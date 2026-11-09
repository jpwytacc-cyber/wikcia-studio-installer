# Resolve both a distributable folder and the maintained source-package layout.
# This script does not change execution policy, install prerequisites or use a system Python.
$ErrorActionPreference = 'Stop'
try {
    $base = $PSScriptRoot
    $candidates = @($base, (Join-Path $base 'bundle\Wikcia-Windows11'))
    if (Test-Path -LiteralPath (Join-Path $base 'bundle') -PathType Container) {
        $candidates += @(Get-ChildItem -LiteralPath (Join-Path $base 'bundle') -Directory |
            Where-Object { $_.Name -notmatch '\.(before|building|failed)' } |
            ForEach-Object { $_.FullName })
    }
    $valid = @($candidates | Select-Object -Unique | Where-Object {
        (Test-Path -LiteralPath (Join-Path $_ 'manifest.json') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $_ 'bootstrap\python\python.exe') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $_ 'installer.py') -PathType Leaf)
    })
    # Prefer an adjacent complete distributable; otherwise require one nested bundle.
    if ($valid -contains $base) { $bundle = $base }
    elseif ($valid.Count -eq 1) { $bundle = $valid[0] }
    elseif ($valid.Count -gt 1) { throw 'Multiple bundles found. Run INSTALL-WIKCIA.cmd inside the intended bundle folder.' }
    else {
        throw ('No complete installer payload was found beside this launcher or in bundle\Wikcia-Windows11. Checked: ' + ($candidates -join '; ') + '. This is a missing-payload error, not proof that the archive is still zipped. Obtain the complete Wikcia installer package.')
    }
    # Source-package launchers use the repaired outer engine; distributables use their own.
    $engine = Join-Path $base 'installer.py'
    if (-not (Test-Path -LiteralPath $engine -PathType Leaf)) { $engine = Join-Path $bundle 'installer.py' }
    Write-Host ('Installer payload: ' + $bundle)
    & (Join-Path $bundle 'bootstrap\python\python.exe') -s -u $engine --bundle $bundle @args
    exit $LASTEXITCODE
}
catch {
    [Console]::Error.WriteLine('SETUP FAILED: ' + $_.Exception.Message)
    exit 1
}
