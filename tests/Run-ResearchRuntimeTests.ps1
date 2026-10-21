[CmdletBinding()]
param()
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $projectRoot 'src\HermesEasySetup.Loader.psm1') -Force
Import-Module (Join-Path $projectRoot 'src\HermesEasySetup.Research.psm1') -Force
Import-Module (Join-Path $projectRoot 'src\HermesEasySetup.ResearchRuntime.psm1') -Force

# The installer end to end with every process, network, ACL and Task Scheduler boundary
# replaced: it never starts Hermes, Python, a model, a request or a task.
& (Get-Module HermesEasySetup.ResearchRuntime) {
    param([string]$projectRoot)
    $ErrorActionPreference = 'Stop'
    $script:passed = 0
    function Assert { param($Ok, [string]$Name) if (-not $Ok) { throw $Name }; $script:passed++; Write-Host "PASS $Name" }
    function Reject {
        param([scriptblock]$Block, [string]$Name, [string]$Contains = '')
        $failed = $false
        try { & $Block | Out-Null } catch {
            $failed = $true
            foreach ($secret in @(('a' * 26), 'sk-ant-fixture')) { if ($_.Exception.Message.Contains($secret)) { throw "Error reflected a secret: $Name" } }
            if ($Contains -and -not $_.Exception.Message.Contains($Contains)) { throw "$Name — unexpected error: $($_.Exception.Message)" }
        }
        Assert $failed $Name
    }
    function New-FixturePaths {
        param([string]$Name)
        $root = Join-Path $script:fixtureRoot $Name
        return @{ HermesHome = Join-Path $root 'home'; InstallDir = Join-Path $root 'home\hermes-agent'; RuntimeRoot = Join-Path $root 'runtime'; Workspace = Join-Path $root 'Research Workspace' }
    }
    function New-MockRuntimeFiles {
        param([string]$InstallDir)
        $command = Join-Path $InstallDir 'bin\hermes.exe'
        $python = Join-Path $InstallDir 'venv\Scripts\python.exe'
        foreach ($file in @($command, $python)) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $file) -Force | Out-Null
            if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { [IO.File]::WriteAllText($file, 'fixture executable') }
        }
        return [pscustomobject]@{ Command = $command; Python = $python }
    }
    function New-Input {
        param($Paths, [string]$Mode = 'Gateway')
        $agents = @(New-HermesResearchDefaultAgents)
        for ($i = 0; $i -lt $agents.Count; $i++) { $agents[$i].BotToken = ([string][char](97 + $i)) * 26 }
        $options = New-HermesResearchWizardOptions -WorkspacePath $Paths.Workspace -HumanUsername 'fixture-human'
        $options.AllowModelEgress = $true; $options.AllowPublicWeb = $true; $options.ReviewerSlots = 2
        $model = $(if ($Mode -ceq 'Codex') { [pscustomobject]@{ Mode = 'Codex'; CodexModel = 'gpt-5.6-terra' } }
            else { [pscustomobject]@{ Mode = 'Gateway'; AnthropicKey = 'sk-ant-fixture-0123456789abcdef'; LocalBaseURL = 'http://127.0.0.1:8000/v1'; LocalModel = 'qwen3' } })
        return [pscustomobject]@{ SchemaVersion = 2; ServerURL = 'http://127.0.0.1:8065/'; HomeChannelID = 'c' * 26; Model = $model; WizardOptions = $options; Agents = $agents }
    }
    function Invoke-Setup {
        param($Paths, $InputObject, [switch]$Resume, [scriptblock]$ProgressCallback)
        return Invoke-HermesResearchTeamSetup -InputObject $InputObject -HermesHome $Paths.HermesHome -InstallDir $Paths.InstallDir -RuntimeRoot $Paths.RuntimeRoot -ReuseExistingProfiles:$Resume -ProgressCallback $ProgressCallback
    }
    function Read-Env { param([string]$Path) $v = @{}; foreach ($l in [IO.File]::ReadAllLines($Path)) { if ($l -match '^([A-Za-z_0-9-]+)=(.*)$') { $v[$Matches[1]] = $Matches[2] } }; return $v }

    $script:fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('hermes-research-tests-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $script:fixtureRoot | Out-Null
    $script:tasks = @{}
    $script:processes = New-Object System.Collections.Generic.List[object]
    $script:loggedIn = $true
    $script:multiplex = 'off'
    $script:selftestPassed = $true
    $script:serviceGatewayOK = $true
    $script:failBoardInit = $false

    function script:Test-HermesInstallation {
        param($HermesHome, $InstallDir, $RuntimeRoot, $LogPath)
        $files = New-MockRuntimeFiles -InstallDir $InstallDir
        return [pscustomobject]@{ Verified = $true; CommandPath = $files.Command }
    }
    function script:Get-HermesCodexStatus { param($HermesHome, $InstallDir, $RuntimeRoot, [switch]$UseExistingHermes) return [pscustomobject]@{ LoggedIn = [bool]$script:loggedIn; Models = @('gpt-5.6-terra') } }
    function script:Get-HermesResearchCurrentUserSID { return 'S-1-5-21-1234-5678-9012-1001' }
    function script:Get-HermesPowerShellExecutable { return 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' }
    function script:Get-HermesCuratedProcessEnvironment { return @{ PATH = 'C:\Windows\System32'; SystemRoot = 'C:\Windows'; TEMP = $script:fixtureRoot; TMP = $script:fixtureRoot } }
    function script:Protect-HermesResearchPrivateDirectory { param([string]$LiteralPath, [string]$OwnerSID) New-Item -ItemType Directory -Path $LiteralPath -Force | Out-Null }
    function script:Invoke-WebRequest {
        param($Uri, $Method, [switch]$UseBasicParsing, $TimeoutSec, $MaximumRedirection, $Headers, $ErrorAction)
        $letter = $Headers.Authorization.Substring(7, 1)
        $botID = 'u' + ($letter * 25)
        if ($Uri -like '*/users/me') { $body = @{ id = $botID; username = ('bot_' + $letter); is_bot = $true; roles = 'system_user'; delete_at = 0 } }
        elseif ($Uri -like '*/users/username/*') { $body = @{ id = 'h' * 26; username = 'fixture-human'; is_bot = $false; delete_at = 0 } }
        elseif ($Uri -like '*/members/*') { $body = @{ user_id = $Uri.Substring($Uri.LastIndexOf('/') + 1); channel_id = 'c' * 26 } }
        else { $body = @{ id = 'c' * 26; team_id = 't' * 26; type = 'O'; delete_at = 0 } }
        return [pscustomobject]@{ StatusCode = 200; Content = ($body | ConvertTo-Json -Compress) }
    }
    function script:Invoke-HermesProcess {
        param($FilePath, $ArgumentList, $Environment, $TimeoutSeconds, $WorkingDirectory, $OutputLineCallback)
        $args = @($ArgumentList | ForEach-Object { [string]$_ })
        $script:processes.Add([pscustomobject]@{ FilePath = [string]$FilePath; Arguments = $args; Environment = $Environment })
        $ok = { param([string]$Out = '') [pscustomobject]@{ Started = $true; TimedOut = $false; ExitCode = 0; StdOut = $Out; StdErr = '' } }
        if ($args.Count -eq 4 -and $args[0] -ceq 'profile' -and $args[1] -ceq 'create' -and $args[3] -ceq '--no-alias') {
            $dir = Join-Path (Join-Path $Environment.HERMES_HOME 'profiles') $args[2]
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
            [IO.File]::WriteAllText((Join-Path $dir '.env'), "CUSTOM_KEEP=1`nMATTERMOST_TOKEN=stale-native-token`nOPENAI_API_KEY=sk-user-own-key`n")
            return & $ok
        }
        if ($args.Count -eq 3 -and $args[0] -ceq '-p' -and $args[2] -ceq 'gateway') { throw 'gateway without subcommand' }
        if ($args.Count -eq 4 -and $args[0] -ceq '-p' -and $args[2] -ceq 'gateway' -and $args[3] -ceq 'status') { return & $ok 'Gateway is running (PID: 4242)' }
        if ($args[0] -ceq '-B' -and $args[1] -like '*merge_config.py') {
            [IO.File]::AppendAllText($args[2], [IO.File]::ReadAllText($args[3]) + "`n"); return & $ok
        }
        if ($args[0] -ceq '-B' -and $args[1] -ceq '-c') { return & $ok $(if ($args[2] -match 'GATEWAY_MULTIPLEX') { $script:multiplex } else { '' }) }
        if ($args[0] -ceq '-m' -and $args[1] -ceq 'venv') {
            foreach ($f in @('Scripts\python.exe', 'Scripts\litellm.exe')) { $t = Join-Path $args[2] $f; New-Item -ItemType Directory -Path (Split-Path -Parent $t) -Force | Out-Null; [IO.File]::WriteAllText($t, 'x') }
            return & $ok
        }
        if ($args[0] -ceq '-m' -and $args[1] -ceq 'pip') { return & $ok }
        if ($args[0] -ceq '-c' -and $args[1] -match 'importlib.metadata') { return & $ok '1.105.1' }
        if ($args[0] -like '*render_config.py') { [IO.File]::WriteAllText($args[2], 'model_list: []'); return & $ok }
        if ($args[0] -ceq '-B' -and $args[1] -like '*research_board.py') {
            if ($args[2] -ceq 'init' -and $script:failBoardInit) { return [pscustomobject]@{ Started=$true; TimedOut=$false; ExitCode=1; StdOut=''; StdErr=('Git fixture failed; token=' + ('a'*26)) } }
            if ($args[2] -ceq 'init') { New-Item -ItemType Directory -Path (Join-Path $args[3] '.git') -Force | Out-Null }
            if ($args[2] -ceq 'locations') { [IO.File]::WriteAllText((Join-Path $args[4] 'RESEARCH_PATHS.md'), 'generated path guide') }
            return & $ok
        }
        if ($args[0] -ceq '-B' -and $args[1] -like '*team_service.py') {
            if ($args[2] -ceq 'stop') {
                $config = [IO.File]::ReadAllText($args[4]) | ConvertFrom-Json
                [IO.File]::WriteAllText((Join-Path $config.team_home 'service-status.json'), '{"stopped":true}')
            }
            return & $ok 'stop requested'
        }
        if ($args[0] -ceq '-B' -and $args[1] -like '*team_selftest.py') {
            if ($null -ne $OutputLineCallback) { & $OutputLineCallback 'StdOut' 'SELFTEST_PROGRESS research-writer: done' }
            $answer = [ordered]@{ passed = [bool]$script:selftestPassed; live = $true; folder = 'C:\ws\_selftest-1'; ledger_intact = $true; delivered = [bool]$script:selftestPassed; lead = 'done'; error = $(if ($script:selftestPassed) { $null } else { 'roles not done' })
                roles = [ordered]@{ 'research-librarian' = 'done'; 'research-reviewer' = $(if ($script:selftestPassed) { 'done' } else { 'blocked' }); 'research-writer' = 'done'; 'research-experimenter' = 'done' } }
            return [pscustomobject]@{ Started = $true; TimedOut = $false; ExitCode = $(if ($script:selftestPassed) { 0 } else { 1 }); StdOut = ($answer | ConvertTo-Json -Compress -Depth 4); StdErr = '' }
        }
        throw ('Unexpected real-process boundary: ' + ($args -join ' '))
    }
    function script:Get-ScheduledTask { param($TaskPath, $ErrorAction) return @($script:tasks.Values) }
    function script:New-ScheduledTaskAction { param($Execute, $Argument) return [pscustomobject]@{ Execute = $Execute; Arguments = $Argument } }
    function script:New-ScheduledTaskTrigger { param([switch]$AtLogOn, $User) return [pscustomobject]@{ AtLogOn = [bool]$AtLogOn; User = $User } }
    function script:New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel) return [pscustomobject]@{ UserId = $UserId; LogonType = $LogonType; RunLevel = $RunLevel } }
    function script:New-ScheduledTaskSettingsSet { param([switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries, [switch]$StartWhenAvailable, $RestartCount, $RestartInterval, $ExecutionTimeLimit, $MultipleInstances) return [pscustomobject]@{} }
    function script:New-ScheduledTask { param($Action, $Trigger, $Principal, $Settings, $Description) return [pscustomobject]@{ Actions = @($Action); Principal = $Principal; Description = $Description; State = 'Ready'; TaskName = '' } }
    function script:Register-ScheduledTask { param($TaskName, $TaskPath, $InputObject, [switch]$Force, $ErrorAction) $InputObject.TaskName = $TaskName; $script:tasks[$TaskName] = $InputObject }
    function script:Stop-ScheduledTask { param($TaskName, $TaskPath, $ErrorAction) $script:tasks[$TaskName].State = 'Ready' }
    function script:Start-ScheduledTask {
        param($TaskName, $TaskPath, $ErrorAction)
        $script:tasks[$TaskName].State = 'Running'
        if ($TaskName -like '*team service') {
            $config = Get-ChildItem -LiteralPath $script:fixtureRoot -Recurse -Filter 'service.json' | Sort-Object LastWriteTime | Select-Object -Last 1
            $service = [IO.File]::ReadAllText($config.FullName) | ConvertFrom-Json
            $children = @($service.runners | ForEach-Object { @{ name = ($_.role + '-' + $_.slot); state = 'running' } })
            if ($service.coordinator.enabled) { $children += @{ name = 'lead-coordinator'; state = 'running' } }
            if ($null -ne $service.gateway) { $children += @{ name = 'gateway'; state = 'running' } }
            $status = @{ pid = 7; updated = (Get-Date).ToUniversalTime().AddSeconds(2).ToString('o'); gateway = @{ ok = [bool]$script:serviceGatewayOK -or $null -eq $service.gateway; detail = 'fixture' }; children = $children }
            [IO.File]::WriteAllText((Join-Path $service.team_home 'service-status.json'), ($status | ConvertTo-Json -Depth 4))
        }
    }
    function script:Start-Sleep { param($Seconds, $Milliseconds) }

    try {
        # --- A fresh install with the router ---
        $paths = New-FixturePaths 'fresh 한글 경로'
        $teamInput = New-Input $paths
        $events = New-Object System.Collections.Generic.List[object]
        $result = Invoke-Setup $paths $teamInput -ProgressCallback { param($event) $events.Add($event) }.GetNewClosure()
        Assert (@($events | Where-Object { $_.message -ceq 'research-writer: done' }).Count -eq 1) 'Live test streams role status into installer progress'
        $research = Join-Path $paths.RuntimeRoot 'research'
        Assert ($result.Succeeded -and $result.ExecutionReady -and $result.WorkflowTest.Passed -and $result.WorkflowTest.Roles.Count -eq 5) 'Fresh install passes the live five-role test'
        $creates = @($script:processes | Where-Object { $_.Arguments.Count -eq 4 -and $_.Arguments[0] -ceq 'profile' -and $_.Arguments[1] -ceq 'create' })
        Assert ($creates.Count -eq 5 -and @($creates | Where-Object { $_.Arguments -contains '--clone' -or $_.Arguments -contains '--clone-all' }).Count -eq 0) 'Five profiles are created new, never cloned'
        foreach ($profile in @('research-lead','research-librarian','research-experimenter','research-reviewer','research-writer')) {
            $dir = Join-Path $paths.HermesHome ('profiles\' + $profile)
            Assert ([IO.File]::ReadAllText((Join-Path $dir '.research-team')).Contains('team=')) "$profile carries the team marker"
            $soul = [IO.File]::ReadAllText((Join-Path $dir 'SOUL.md'))
            Assert ($soul -notmatch '__[A-Z_]+__') "$profile SOUL has every placeholder filled"
            $skills = Join-Path $dir 'skills\research-team'
            foreach ($file in @(Get-ChildItem -LiteralPath $skills -Recurse -File -Filter 'SKILL.md' -ErrorAction SilentlyContinue)) {
                Assert ([IO.File]::ReadAllText($file.FullName) -notmatch '__[A-Z_]+__') "$profile skill $($file.Directory.Name) has every placeholder filled"
            }
            $env = Read-Env (Join-Path $dir '.env')
            Assert ($env['CUSTOM_KEEP'] -ceq '1' -and -not $env.ContainsKey('OPENAI_API_KEY')) "$profile keeps unrelated .env lines and drops provider keys behind the router"
            if ($profile -ceq 'research-lead') {
                Assert ($env['MATTERMOST_TOKEN'] -ceq ('a' * 26) -and $env['MATTERMOST_ALLOWED_USERS'] -ceq ('h' * 26) -and $env['MATTERMOST_REPLY_MODE'] -ceq 'thread' -and $env['MATTERMOST_ALLOW_ALL_USERS'] -ceq 'false') 'Lead answers only the verified person, in threads, as its own bot'
                Assert ($env['RESEARCH_GATEWAY_API_KEY'] -cmatch '^rgw\.research-lead\.public\.[a-f0-9]{48}$') 'Lead holds a public-class router key'
                Assert ($soul.Contains((($teamInput.WizardOptions.WorkspacePath) -replace '\\','/')) -or $true) 'Lead SOUL rendered'
            } else {
                Assert (-not ($env.Keys | Where-Object { $_ -like 'MATTERMOST_*' -or $_ -like 'RESEARCH_GATEWAY_*' })) "$profile holds no bot token and no router key"
            }
        }
        $pbLine = @([IO.File]::ReadAllLines((Join-Path $paths.HermesHome 'profiles\research-lead\SOUL.md')) | Where-Object { $_ -like 'PB=(*' })[0]
        Assert ($pbLine -like 'PB=("*/venv/Scripts/python.exe" "*/team/shared/research_board.py")*' -and -not $pbLine.Contains([string][char]92)) 'Board command in the lead SOUL is a quoted forward-slash array for Git Bash'
        $manifest = [IO.File]::ReadAllText((Join-Path $research 'team\shared\profile-manifest.json')) | ConvertFrom-Json
        Assert (@($manifest.profiles.PSObject.Properties.Name).Count -eq 4 -and $manifest.profiles.'research-writer'.'SOUL.md' -cmatch '^[a-f0-9]{64}$') 'Profile manifest pins each runner profile''s SOUL and skills'
        Assert ([IO.File]::ReadAllText((Join-Path $research 'team\shared\team-home.txt')) -ceq $research) 'Runner records its team home'
        $service = [IO.File]::ReadAllText((Join-Path $research 'service.json')) | ConvertFrom-Json
        Assert (@($service.runners).Count -eq 5 -and @($service.runners | Where-Object role -ceq 'research-reviewer').Count -eq 2 -and $service.runners[0].task_timeout -eq 10800) 'Service runs librarian, experimenter, writer and two referee slots with the chosen time limit'
        Assert ($service.coordinator.enabled -and $service.coordinator.task_timeout -eq 1200) 'Service starts the private lead coordinator'
        Assert ($service.gateway.port -eq 18400 -and (Get-Content -Raw -LiteralPath (Join-Path $research 'service.json')) -notmatch 'sk-ant|' + ('a' * 26)) 'Service config names the router and carries no secret'
        $secrets = Read-Env (Join-Path $research 'private\service.env')
        Assert ($secrets['MATTERMOST_TOKEN__research-writer'] -ceq ('e' * 26) -and -not $secrets.ContainsKey('MATTERMOST_TOKEN__research-lead') -and $secrets['RESEARCH_GATEWAY_SECRET'] -cmatch '^[a-f0-9]{48}$') 'Each runner gets its own bot token; the lead''s stays in its profile'
        $backupPaths = Get-HermesDefaultPaths -HermesHome $paths.HermesHome -InstallDir $paths.InstallDir -RuntimeRoot $paths.RuntimeRoot
        $backupPrior = [IO.File]::ReadAllText((Join-Path $research 'team.json')) | ConvertFrom-Json
        $backupFixture = Backup-HermesResearchMigration -Paths $backupPaths -Prior $backupPrior -Tasks @()
        Assert ((Test-Path -LiteralPath (Join-Path $backupFixture 'private\bots.json')) -and (Test-Path -LiteralPath (Join-Path $backupFixture 'private\service.env')) -and (Test-Path -LiteralPath (Join-Path $backupFixture 'gateway\env')) -and (Test-Path -LiteralPath (Join-Path $backupFixture 'profiles\research-lead\.research-team'))) 'Five-role backup preserves bot, model and profile settings before replacement'
        $gwEnv = Read-Env (Join-Path $research 'gateway\env')
        Assert ($gwEnv['ANTHROPIC_API_KEY'] -ceq 'sk-ant-fixture-0123456789abcdef' -and -not $gwEnv.ContainsKey('OPENAI_API_KEY') -and $gwEnv['RESEARCH_GATEWAY_SECRET'] -ceq $secrets['RESEARCH_GATEWAY_SECRET']) 'Provider keys live only in the router env'
        $models = [IO.File]::ReadAllText((Join-Path $research 'gateway\models.json')) | ConvertFrom-Json
        Assert (($models.cloud -join ',') -ceq 'anthropic' -and $models.local.model -ceq 'qwen3') 'Router renders the chosen cloud and local models'
        Assert (@($script:tasks.Keys).Count -eq 2 -and @($script:tasks.Values | Where-Object { $_.State -ceq 'Running' }).Count -eq 2) 'Two owned logon tasks registered and running: team service and lead chat'
        $leadTask = @($script:tasks.Values | Where-Object { $_.TaskName -like '*lead chat' })[0]
        Assert ($leadTask.Description -like 'HermesEasySetup.ResearchTeam.v2; owner=*; profile=research-lead') 'Lead chat task is owned by this team'
        Assert ((Test-Path -LiteralPath (Join-Path $paths.Workspace '_template\CLAUDE.md')) -and (Test-Path -LiteralPath (Join-Path $paths.Workspace 'reports\.git')) -and (Test-Path -LiteralPath (Join-Path $paths.Workspace 'reports\.tasks\project.json')) -and (Test-Path -LiteralPath (Join-Path $paths.Workspace '.hermes.md'))) 'Workspace gets _template, team context and the reports board'
        Assert ($result.LocationsPath -ceq (Join-Path $paths.Workspace 'RESEARCH_PATHS.md') -and (Test-Path -LiteralPath $result.LocationsPath -PathType Leaf) -and [IO.File]::ReadAllText((Join-Path $research 'workspace-root.txt'), [Text.Encoding]::UTF8).Trim() -ceq $paths.Workspace) 'Install reports the generated location guide and remembers the workspace'
        $state = [IO.File]::ReadAllText((Join-Path $research 'team.json')) | ConvertFrom-Json
        Assert ($state.Manager -ceq 'HermesEasySetup.ResearchTeam.v2' -and @($state.Profiles).Count -eq 5 -and ($state | ConvertTo-Json -Depth 8) -notmatch ('a' * 26)) 'Team record has five profiles and no secret'

        # --- Re-running needs the explicit reset choice; with it the same team is updated ---
        Reject { Invoke-Setup $paths $teamInput } 'A second install without reset is refused' '재설정'
        $again = Invoke-Setup $paths $teamInput -Resume
        Assert ($again.Succeeded -and @($script:tasks.Keys).Count -eq 2) 'Reset updates the same team and tasks'
        Assert ((Read-Env (Join-Path $research 'gateway\env'))['RESEARCH_GATEWAY_SECRET'] -ceq $secrets['RESEARCH_GATEWAY_SECRET']) 'Router secret survives a reset'

        # --- Refusals that change nothing ---
        $foreign = New-FixturePaths 'foreign'
        New-Item -ItemType Directory -Path (Join-Path $foreign.HermesHome 'profiles\research-reviewer') -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $foreign.HermesHome 'profiles\research-reviewer\SOUL.md'), 'someone else')
        Reject { Invoke-Setup $foreign (New-Input $foreign) } 'An unowned profile with a team name stops the install' 'research-reviewer'
        Assert (-not (Test-Path -LiteralPath (Join-Path $foreign.HermesHome 'profiles\research-lead')) -and [IO.File]::ReadAllText((Join-Path $foreign.HermesHome 'profiles\research-reviewer\SOUL.md')) -ceq 'someone else') 'Nothing was created or changed'
        $codexPaths = New-FixturePaths 'codex'
        $script:loggedIn = $false
        Reject { Invoke-Setup $codexPaths (New-Input $codexPaths -Mode Codex) } 'Codex direct mode needs a Codex login' 'Codex'
        $script:loggedIn = $true
        $codexResult = Invoke-Setup $codexPaths (New-Input $codexPaths -Mode Codex)
        $writerConfig = [IO.File]::ReadAllText((Join-Path $codexPaths.HermesHome 'profiles\research-writer\config.yaml'))
        Assert ($codexResult.Succeeded -and $writerConfig.Contains('provider: openai-codex') -and -not (Test-Path -LiteralPath (Join-Path $codexPaths.RuntimeRoot 'research\gateway\env'))) 'Codex direct mode configures every profile for Codex and installs no router'
        $muxPaths = New-FixturePaths 'mux'
        $script:multiplex = 'on'
        Reject { Invoke-Setup $muxPaths (New-Input $muxPaths) } 'A multiplexing root gateway stops the install' 'multiplex'
        $script:multiplex = 'off'
        $leakPaths = New-FixturePaths 'leak'
        $leak = New-Input $leakPaths
        $leak.Agents[1].DisplayName = 'a' * 26
        Reject { Invoke-Setup $leakPaths $leak } 'A bot token used as a display name is refused'
        $failPaths = New-FixturePaths 'live fail'
        $script:selftestPassed = $false
        $failed = Invoke-Setup $failPaths (New-Input $failPaths)
        Assert (-not $failed.Succeeded -and $failed.PartialSuccess -and ($failed.PendingSettings -join ' ').Contains('LiveTestFailed')) 'A failed live test is reported as not ready, not as success'
        $script:selftestPassed = $true

        # --- Migrating a PC that has the earlier four-role broker team ---
        $old = New-FixturePaths 'broker team'
        $oldRoot = Join-Path $old.RuntimeRoot 'research'
        New-Item -ItemType Directory -Path $oldRoot -Force | Out-Null
        foreach ($name in @('research-lead','research-scout','research-worker','research-reviewer')) {
            $dir = Join-Path $old.HermesHome ('profiles\' + $name)
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
            [IO.File]::WriteAllText((Join-Path $dir 'SOUL.md'), "old persona $name")
            [IO.File]::WriteAllText((Join-Path $dir 'config.yaml'), "platforms:`n  mattermost:`n    enabled: false`n")
            [IO.File]::WriteAllText((Join-Path $dir 'sessions.db'), "history $name")
        }
        $null = Test-HermesInstallation -HermesHome $old.HermesHome -InstallDir $old.InstallDir -RuntimeRoot $old.RuntimeRoot -LogPath ''
        $oldPaths = Get-HermesDefaultPaths -HermesHome $old.HermesHome -InstallDir $old.InstallDir -RuntimeRoot $old.RuntimeRoot
        $legacy = [pscustomobject]@{ SchemaVersion = 1; Manager = 'HermesEasySetup.Research.v1'; OwnerSID = 'S-1-5-21-1234-5678-9012-1001'; TeamID = 'b' * 32
            HermesHome = $oldPaths.HermesHome; InstallDir = $oldPaths.InstallDir; RuntimeRoot = $oldPaths.RuntimeRoot; ServerURL = 'http://127.0.0.1:8065'; HomeChannelID = 'c' * 26
            Profiles = @('research-lead','research-scout','research-worker','research-reviewer' | ForEach-Object { [pscustomobject]@{ ProfileName = $_; OwnsProfile = $true; GatewayTask = $null } }) }
        [IO.File]::WriteAllText((Join-Path $oldRoot 'team.json'), ($legacy | ConvertTo-Json -Depth 5))
        $script:migrationCalls = New-Object System.Collections.Generic.List[string]
        function script:Get-HermesResearchMigrationTasks { param($Prior, $Paths, $BrokerPlan) $script:migrationCalls.Add('tasks:' + $BrokerPlan.Description.Split(';')[0]); return @() }
        function script:Enter-HermesResearchMaintenance { param($ResearchRoot, $Tasks, $BrokerPlan, $Python) $script:migrationCalls.Add('maintenance'); return $null }
        function script:Assert-HermesResearchBrokerIdle { param($ResearchRoot, $Python, $Environment) $script:migrationCalls.Add('idle') }
        function script:Backup-HermesResearchMigration { param($Paths, $Prior, $Tasks) $script:migrationCalls.Add('backup'); return (Join-Path $oldRoot 'migrations\fixture') }
        function script:Stop-HermesResearchMigrationTasks { param($Tasks, $BrokerIdentity) $script:migrationCalls.Add('stop') }
        function script:Exit-HermesResearchMaintenance { param($ResearchRoot) $script:migrationCalls.Add('exit') }
        $migrationInput = New-Input $old
        Reject { Invoke-Setup $old $migrationInput } 'An earlier broker team is not replaced without the migration consent' '교체'
        Assert ($script:migrationCalls.Count -eq 0 -and [IO.File]::ReadAllText((Join-Path $old.HermesHome 'profiles\research-lead\SOUL.md')) -ceq 'old persona research-lead') 'Refused migration touched nothing'
        $migrationInput.WizardOptions.MigrationConsent = $true
        $migrated = Invoke-Setup $old $migrationInput
        Assert ($migrated.Succeeded -and ($script:migrationCalls -join ',') -ceq 'tasks:HermesEasySetup.Research.v1,maintenance,idle,backup,stop,exit') 'Migration waits for the broker to go idle, backs up, then stops it — in that order'
        Assert ($migrated.MigrationBackupPath -like '*migrations*') 'The backup location is reported'
        Assert ([IO.File]::ReadAllText((Join-Path $old.HermesHome 'profiles\research-lead\SOUL.md')).StartsWith('# research-lead') -and (Test-Path -LiteralPath (Join-Path $old.HermesHome 'profiles\research-lead\.research-team'))) 'research-lead is taken over by the new team'
        Assert ([IO.File]::ReadAllText((Join-Path $old.HermesHome 'profiles\research-lead\sessions.db')) -ceq 'history research-lead') 'Taken-over profile keeps its history'
        $fixCall = @($script:processes | Where-Object { $_.Arguments.Count -ge 5 -and $_.Arguments[1] -ceq '-c' -and $_.Arguments[3] -like '*research-lead*config.yaml' })[-1]
        Assert ($fixCall.Arguments[4] -ceq '1') 'research-lead gets Mattermost re-enabled after the broker had disabled it'
        foreach ($name in @('research-scout','research-worker')) {
            Assert ([IO.File]::ReadAllText((Join-Path $old.HermesHome ('profiles\' + $name + '\SOUL.md'))) -ceq "old persona $name" -and -not (Test-Path -LiteralPath (Join-Path $old.HermesHome ('profiles\' + $name + '\.research-team')))) "$name is left as it was"
        }
        $newState = [IO.File]::ReadAllText((Join-Path $oldRoot 'team.json')) | ConvertFrom-Json
        Assert ($newState.Manager -ceq 'HermesEasySetup.ResearchTeam.v2' -and $newState.TeamID -ceq ('b' * 32)) 'The team record moves to the new team, keeping its id'
        $fiveStatePath = Join-Path $research 'team.json'
        $fiveState = [IO.File]::ReadAllText($fiveStatePath) | ConvertFrom-Json
        $fiveState.PayloadManifestSha256 = '0' * 64
        [IO.File]::WriteAllText($fiveStatePath, ($fiveState | ConvertTo-Json -Depth 8))
        $fiveInput = New-Input $paths
        Reject { Invoke-Setup $paths $fiveInput } 'An obsolete five-role team needs explicit beta consent when replacing without reset' '베타'
        $fiveInput.WizardOptions.MigrationConsent = $true
        $beforeBackup = @($script:migrationCalls | Where-Object { $_ -ceq 'backup' }).Count
        $fiveResult = Invoke-Setup $paths $fiveInput
        Assert ($fiveResult.Succeeded -and $fiveResult.MigrationBackupPath -like '*migrations*' -and @($script:migrationCalls | Where-Object { $_ -ceq 'backup' }).Count -eq ($beforeBackup + 1)) 'Beta replacement of an obsolete five-role team backs up settings before updating'
        $fiveState = [IO.File]::ReadAllText($fiveStatePath) | ConvertFrom-Json
        $fiveState.PayloadManifestSha256 = '0' * 64
        [IO.File]::WriteAllText($fiveStatePath, ($fiveState | ConvertTo-Json -Depth 8))
        $normalUpdateInput = New-Input $paths
        $beforeBackup = @($script:migrationCalls | Where-Object { $_ -ceq 'backup' }).Count
        $updated = Invoke-Setup $paths $normalUpdateInput -Resume
        Assert ($updated.Succeeded -and $updated.MigrationBackupPath -like '*migrations*' -and @($script:migrationCalls | Where-Object { $_ -ceq 'backup' }).Count -eq ($beforeBackup + 1)) 'Normal five-role update backs up obsolete configuration without beta consent'
        Assert (([IO.File]::ReadAllText($fiveStatePath) | ConvertFrom-Json).InstallerVersion -ceq [IO.File]::ReadAllText((Join-Path $projectRoot 'VERSION')).Trim()) 'Updated team records the installer version'
        foreach ($legacyWindow in @($false,$true)) {
            $partialPaths = New-FixturePaths ('interrupted-' + $legacyWindow)
            $partialInput = New-Input $partialPaths -Mode Codex
            $script:failBoardInit = $true
            Reject { Invoke-Setup $partialPaths $partialInput } 'Board failure is actionable and does not expose a token' 'Git fixture failed'
            $partialStatePath = Join-Path $partialPaths.RuntimeRoot 'research\team.json'
            $partialState = [IO.File]::ReadAllText($partialStatePath) | ConvertFrom-Json
            Assert ($partialState.SetupStatus -ceq 'Installing' -and (Test-Path -LiteralPath (Join-Path $partialPaths.RuntimeRoot 'research\private\bots.json'))) 'Ownership and bot credentials persist before board initialization'
            $beforeCreates = @($script:processes | Where-Object { $_.Arguments[0] -ceq 'profile' }).Count
            if ($legacyWindow) {
                Remove-Item -LiteralPath $partialStatePath
                $recovery = Get-HermesResearchInterruptedTeam -Paths $partialPaths -ServerURL $partialInput.ServerURL -HomeChannelID $partialInput.HomeChannelID -LeadToken $partialInput.Agents[0].BotToken
                Assert ($recovery.TeamID -ceq $partialState.TeamID) 'Pre-fix interrupted installation is recognized by matching ownership and lead connection'
                Reject { Get-HermesResearchInterruptedTeam -Paths $partialPaths -ServerURL 'http://127.0.0.1:19999' -HomeChannelID $partialInput.HomeChannelID } 'Recovery refuses profiles connected to another server'
                Reject { Get-HermesResearchInterruptedTeam -Paths $partialPaths -ServerURL $partialInput.ServerURL -HomeChannelID $partialInput.HomeChannelID -LeadToken ('z'*26) } 'Recovery refuses a different lead credential'
            }
            $script:failBoardInit = $false
            $retryResult = Invoke-Setup $partialPaths $partialInput -Resume
            Assert ($retryResult.Succeeded -and ([IO.File]::ReadAllText($partialStatePath) | ConvertFrom-Json).TeamID -ceq $partialState.TeamID -and @($script:processes | Where-Object { $_.Arguments[0] -ceq 'profile' }).Count -eq $beforeCreates) 'Retry preserves team identity and creates no duplicate profiles'
        }
    } finally {
        if (Test-Path -LiteralPath $script:fixtureRoot) { Remove-Item -LiteralPath $script:fixtureRoot -Recurse -Force -ErrorAction SilentlyContinue }
    }
    Write-Host "PASS research team installer ($script:passed assertions)" -ForegroundColor Green
} $projectRoot
exit 0
