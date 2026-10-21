[CmdletBinding()]
param([string]$PythonPath = (Get-Command python -CommandType Application -ErrorAction Stop).Source)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $repo 'src\HermesEasySetup.Loader.psm1') -Force
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('hermes-board-env-' + [guid]::NewGuid().ToString('N'))
try {
    $paths = Get-HermesDefaultPaths -HermesHome (Join-Path $fixture 'home') -RuntimeRoot (Join-Path $fixture 'runtime')
    $environment = & (Get-Module HermesEasySetup.Existing) {
        param($p) New-HermesExistingRuntimeEnvironment -Paths $p -VenvScripts (Join-Path $p.InstallDir 'venv\Scripts')
    } $paths
    # Use real local Python and Git, with the same restricted environment as
    # existing-Hermes setup. No Mattermost, model or installed profile is touched.
    & (Get-Module HermesEasySetup.ResearchRuntime) { param($e) Add-HermesResearchToolPaths -Environment $e } $environment
    $environment['RESEARCH_TEAM_HOME'] = Join-Path $fixture 'team'
    # The board's push is ONLY to its new local bare repo beneath this fixture.
    # Disable network protocols, global/system rewrites, credentials and hooks.
    $environment['GIT_ALLOW_PROTOCOL'] = 'file'
    $environment['GIT_CONFIG_NOSYSTEM'] = '1'
    $environment['GIT_CONFIG_GLOBAL'] = Join-Path $fixture 'empty.gitconfig'
    $environment['GIT_TERMINAL_PROMPT'] = '0'
    $environment['GIT_TEMPLATE_DIR'] = Join-Path $fixture 'empty-template'
    New-Item -ItemType Directory -Path $environment['GIT_TEMPLATE_DIR'] -Force | Out-Null
    [IO.File]::WriteAllText($environment['GIT_CONFIG_GLOBAL'],'')
    $workspace = Join-Path $fixture 'workspace'
    $teamRoot = Join-Path $repo 'team'
    foreach ($attempt in 1..2) {
        $null = & (Get-Module HermesEasySetup.ResearchRuntime) {
            param($ws,$team,$python,$e)
            Install-HermesResearchWorkspace -WorkspacePath $ws -TeamRoot $team -Python $python -Environment $e -ChannelID ('c'*26) -Mention '@fixture'
        } $workspace $teamRoot $PythonPath $environment
        if (-not (Test-Path -LiteralPath (Join-Path $workspace 'reports\.git')) -or
            -not (Test-Path -LiteralPath (Join-Path $workspace 'reports\.tasks\board.conf'))) { throw 'Board initialization did not finish' }
    }
    $check = Invoke-HermesProcess -FilePath $PythonPath -ArgumentList @('-B','-c','import subprocess,sys; r=subprocess.run(["git","-C",sys.argv[1],"status","--porcelain"],check=True,capture_output=True,text=True); assert not r.stdout.strip(), r.stdout', (Join-Path $workspace 'reports')) -Environment $environment -TimeoutSeconds 30
    if (-not $check.Started -or $check.ExitCode -ne 0) { throw 'Board retry left uncommitted changes' }
    Write-Host 'PASS real Git board initialization and retry under the existing-Hermes restricted environment'
} finally {
    $resolved = [IO.Path]::GetFullPath($fixture)
    $prefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\hermes-board-env-'
    if (-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe fixture cleanup' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
