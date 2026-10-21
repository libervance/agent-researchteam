[CmdletBinding()]
param([string]$PythonPath = (Get-Command python -CommandType Application -ErrorAction Stop).Source)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $repo 'src\HermesEasySetup.Loader.psm1') -Force
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('hermes-selftest-process-' + [guid]::NewGuid().ToString('N'))
$passed = 0
function Assert { param($Condition,[string]$Name) if (-not $Condition) { throw $Name }; $script:passed++; Write-Host "PASS $Name" }
try {
    $workspace = Join-Path $fixture 'workspace'
    [IO.Directory]::CreateDirectory($workspace) | Out-Null
    $paths = Get-HermesDefaultPaths -HermesHome (Join-Path $fixture 'home') -RuntimeRoot (Join-Path $fixture 'runtime')
    $environment = & (Get-Module HermesEasySetup.Existing) {
        param($p) New-HermesExistingRuntimeEnvironment -Paths $p -VenvScripts (Join-Path $p.InstallDir 'venv\Scripts')
    } $paths
    $environment['RESEARCH_TEAM_HOME'] = Join-Path $fixture 'team'
    Assert ($environment.PYTHONSAFEPATH -ceq '1') 'Uses the installer restricted Python environment'
    # A workspace file with the same name must never replace the shipped helper.
    [IO.File]::WriteAllText((Join-Path $workspace 'research_board.py'), 'raise RuntimeError("WORKSPACE MODULE WAS IMPORTED")')
    $help = Invoke-HermesProcess -FilePath $PythonPath -ArgumentList @('-B', (Join-Path $repo 'team\shared\team_selftest.py'), '--help') -WorkingDirectory $workspace -Environment $environment -TimeoutSeconds 30
    Assert ($help.Started -and $help.ExitCode -eq 0 -and $help.StdOut.Contains('--workspace')) 'Real self-test starts with safe path enabled, without workspace imports or model calls'

    # Only the child program is a fixture. Use the real process launcher, streaming callback,
    # result parser and atomic evidence writer, including Windows PowerShell 5.1.
    $root = Join-Path $fixture 'research'
    $scriptPath = Join-Path $root 'team\shared\team_selftest.py'
    [IO.Directory]::CreateDirectory((Split-Path -Parent $scriptPath)) | Out-Null
    $child = @'
import json, os, sys
mode = os.environ['SELFTEST_FIXTURE_MODE']
if mode == 'crash':
    print("ModuleNotFoundError: No module named 'research_board'", file=sys.stderr)
    print(os.environ['MATTERMOST_TOKEN'], file=sys.stderr)
    sys.exit(3)
if mode == 'empty':
    sys.exit(0)
if mode == 'null':
    print('null'); sys.exit(0)
if mode == 'schema':
    print('{"passed":true}'); sys.exit(0)
if mode == 'malformed':
    print('not JSON'); sys.exit(0)
print('SELFTEST_PROGRESS research-writer: done', flush=True)
result = dict(passed=mode == 'success', live=True, folder=os.getcwd(),
              roles={role: 'done' for role in ['research-librarian', 'research-reviewer', 'research-writer', 'research-experimenter']},
              lead='done', delivered=True, ledger_intact=True, error=None)
if mode == 'failed':
    result['roles']['research-writer'] = 'failed'
    result['error'] = 'worker failed'
print(json.dumps(result))
sys.exit(0 if mode == 'success' else 1)
'@
    [IO.File]::WriteAllText($scriptPath, $child, (New-Object Text.UTF8Encoding($false)))
    $environment['MATTERMOST_TOKEN'] = 'fixture-private-bot-credential'
    $environment['SELFTEST_FIXTURE_MODE'] = 'success'
    $events = New-Object System.Collections.Generic.List[object]
    $callback = { param($event) [void]$events.Add($event) }.GetNewClosure()
    function Run-Fixture {
        & (Get-Module HermesEasySetup.ResearchRuntime) {
            param($r,$p,$e,$w,$callback)
            Invoke-HermesResearchSelfTest -ResearchRoot $r -Python $p -Environment $e -WorkspacePath $w -ChannelID ('c'*26) -CommandPath 'unused-fixture-hermes' -Mention '' -TimeoutSeconds 5 -ProgressCallback $callback
        } $root $PythonPath $environment $workspace $callback
    }
    $result = Run-Fixture
    Assert ($result.Passed -and $result.Roles.Count -eq 5) 'Real streamed child JSON passes the five-role evidence gate'
    Assert (@($events | Where-Object { $_.message -ceq 'research-writer: done' }).Count -eq 1) 'Real process progress reaches the installer callback'
    $evidence = Join-Path $root 'live-test.json'
    $goodEvidence = [IO.File]::ReadAllText($evidence)
    foreach ($mode in @('empty','null','schema','malformed','crash')) {
        $environment['SELFTEST_FIXTURE_MODE'] = $mode
        $result = Run-Fixture
        $expected = $(if ($mode -ceq 'crash') { 'LiveTestProcessFailed' } else { 'LiveTestEvidenceRejected' })
        Assert (-not $result.Passed -and $result.ErrorCode -ceq $expected -and $result.Detail.Length -gt 0) "Actionable error for $mode child result"
        Assert ([IO.File]::ReadAllText($evidence) -ceq $goodEvidence) "Preserves prior evidence after $mode child result"
        if ($mode -ceq 'crash') {
            Assert ($result.Detail.Contains('ModuleNotFoundError') -and $result.Detail.Contains('exit 3') -and -not $result.Detail.Contains($environment.MATTERMOST_TOKEN)) 'Child crash reports cause and exit code with credentials redacted'
        }
    }
    $environment['SELFTEST_FIXTURE_MODE'] = 'failed'
    $result = Run-Fixture
    Assert (-not $result.Passed -and $result.ErrorCode -ceq 'LiveTestFailed' -and $result.Detail -ceq 'worker failed') 'Valid failed-test evidence is distinguished from a child startup failure'
    Assert (([IO.File]::ReadAllText($evidence) | ConvertFrom-Json).roles.'research-writer' -ceq 'failed') 'Valid failed-test evidence replaces the prior result'
    Write-Host "PASS research self-test process integration ($passed assertions)"
} finally {
    $resolved = [IO.Path]::GetFullPath($fixture)
    $prefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\hermes-selftest-process-'
    if (-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe fixture cleanup' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
