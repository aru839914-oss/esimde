param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'status', 'setup')]
    [string]$Action = 'start',
    [switch]$NoTunnel,
    [int]$Port = 5000,
    [switch]$InstallCloudflared,
    [switch]$Follow
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

$AppDir     = Split-Path -Parent $PSScriptRoot
$RootDir    = Split-Path -Parent $AppDir
$RunDir     = Join-Path $AppDir '.run'
$StateFile  = Join-Path $RunDir 'state.json'
$ServerLog  = Join-Path $RunDir 'server.log'
$ServerErr  = Join-Path $RunDir 'server.err.log'
$TunnelLog  = Join-Path $RunDir 'cloudflared.log'
$UrlFile    = Join-Path $RunDir 'public_url.txt'
$VenvPython = Join-Path $AppDir '.venv\Scripts\python.exe'
$LocalUrl   = "http://127.0.0.1:$Port"
$CloudflaredUrl = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'

function Say([string]$Text, [string]$Color = 'Gray') { Write-Host $Text -ForegroundColor $Color }
function Ok([string]$Text)   { Write-Host "  [OK] $Text" -ForegroundColor Green }
function Warn([string]$Text) { Write-Host "  [!]  $Text" -ForegroundColor Yellow }
function Fail([string]$Text, [int]$Code = 1) {
    Write-Host ""
    Write-Host "ОШИБКА: $Text" -ForegroundColor Red
    exit $Code
}

function Get-EsimdeServerProcesses {
    Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.ToLowerInvariant().Contains($AppDir.ToLowerInvariant()) -and
                       ($_.CommandLine -match 'serve\.py|app\.py') }
}

function Get-EsimdeTunnelProcesses {
    Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "--url\s+http://(127\.0\.0\.1|localhost):$Port(\s|$)" }
}

function Get-LegacyServerWindows {
    Get-CimInstance Win32_Process -Filter "Name = 'cmd.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'Esimde server' -and $_.CommandLine -match 'serve\.py' }
}

function Test-Health([string]$BaseUrl, [int]$Timeout = 3) {
    try {
        $r = Invoke-WebRequest -Uri "$BaseUrl/healthz" -UseBasicParsing -TimeoutSec $Timeout
        return ($r.StatusCode -eq 200 -and $r.Content -match '"ok"')
    } catch { return $false }
}

function Get-PortOwners {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
}

function Read-State {
    if (Test-Path $StateFile) {
        try { return Get-Content $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
    }
    return $null
}

function Write-State($State) {
    New-Item -ItemType Directory -Force $RunDir | Out-Null
    $State | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8
}

function Get-TunnelUrlFromLog {
    if (-not (Test-Path $TunnelLog)) { return $null }
    $m = Select-String -Path $TunnelLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Matches } | ForEach-Object { $_.Value } |
        Where-Object { $_ -notmatch '^https://api\.' } | Select-Object -Last 1
    return $m
}

function Find-Cloudflared {
    $candidates = @(
        (Join-Path $AppDir 'tools\cloudflared.exe'),
        (Join-Path $RootDir 'tools\cloudflared.exe'),
        (Join-Path $env:ProgramFiles 'cloudflared\cloudflared.exe')
    )
    if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} 'cloudflared\cloudflared.exe') }
    foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return $c } }
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Install-Cloudflared {
    $toolsDir = Join-Path $AppDir 'tools'
    New-Item -ItemType Directory -Force $toolsDir | Out-Null
    $target = Join-Path $toolsDir 'cloudflared.exe'
    $tmp = "$target.download"
    Say "  Скачиваю cloudflared с официального GitHub Cloudflare..." 'Cyan'
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $CloudflaredUrl -OutFile $tmp -UseBasicParsing
    } catch {
        Fail "не удалось скачать cloudflared: $($_.Exception.Message)"
    }
    $sig = Get-AuthenticodeSignature $tmp
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Cloudflare, Inc\.') {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
        Fail "подпись скачанного файла не принадлежит Cloudflare, Inc. Файл удалён."
    }
    Move-Item $tmp $target -Force
    Ok "cloudflared установлен: $target (подпись Cloudflare, Inc. проверена)"
    return $target
}

function Show-CloudflaredHelp {
    Say ""
    Say "cloudflared не найден. Установите его одним из официальных способов:" 'Yellow'
    Say "  1) Автоматически (скачать с GitHub Cloudflare и проверить подпись):"
    Say "     powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" start -InstallCloudflared" 'White'
    Say "  2) Через winget:"
    Say "     winget install --id Cloudflare.cloudflared" 'White'
    Say "  3) Вручную: скачайте $CloudflaredUrl"
    Say "     и сохраните как $(Join-Path $AppDir 'tools\cloudflared.exe')"
}

function Stop-Tree([int]$ProcessId, [string]$What) {
    $p = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $p) { return }
    & taskkill.exe /PID $ProcessId /T /F *> $null
    Start-Sleep -Milliseconds 300
    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) { Warn "не удалось остановить $What (PID $ProcessId)" }
    else { Ok "остановлен: $What (PID $ProcessId)" }
}

function Show-Summary([string]$PublicUrl) {
    Say ""
    Say "==================================================================" 'Cyan'
    Say "  Esimde работает" 'Green'
    Say "  Локально:        $LocalUrl" 'White'
    if ($PublicUrl) {
        Say "  Публичная ссылка: $PublicUrl" 'Green'
        Say "  (ссылка скопирована в буфер обмена и сохранена в .run\public_url.txt)" 'DarkGray'
        Say "  Ссылка временная: при каждом новом запуске туннеля она другая." 'DarkGray'
    }
    Say "  Журналы:          $RunDir" 'DarkGray'
    Say "  Остановить:       Esimde_stop.bat  или задача VS Code «Esimde: остановить»" 'White'
    Say "==================================================================" 'Cyan'
}

function Invoke-Setup {
    Say "Esimde: подготовка окружения" 'Cyan'
    if (-not (Test-Path $VenvPython)) {
        $py = Get-Command py -ErrorAction SilentlyContinue
        $pyArgs = @('-3')
        if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue; $pyArgs = @() }
        if (-not $py) { Fail "Python не найден. Установите Python 3.10+ с https://www.python.org/downloads/ (галочка «Add python.exe to PATH»)." }
        $ver = & $py.Source @pyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])"
        if ([version]$ver -lt [version]'3.10') { Fail "нужен Python 3.10 или новее, найден $ver." }
        Say "  Создаю виртуальное окружение (.venv) на Python $ver..."
        & $py.Source @pyArgs -m venv (Join-Path $AppDir '.venv')
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) { Fail "не удалось создать .venv." }
        Ok "создано .venv"
    } else { Ok "виртуальное окружение уже есть (.venv)" }
    Say "  Устанавливаю зависимости из requirements.txt..."
    & $VenvPython -m pip install --disable-pip-version-check -q -r (Join-Path $AppDir 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { Fail "pip install завершился с ошибкой." }
    Ok "зависимости установлены"
    $envFile = Join-Path $AppDir '.env'
    if (-not (Test-Path $envFile)) {
        Copy-Item (Join-Path $AppDir '.env.example') $envFile
        Warn ".env создан из шаблона. Впишите TELEGRAM_BOT_TOKEN, если нужен Telegram-бот."
    } else { Ok ".env уже существует (не изменён)" }
    Say ""
    Say "Готово. Запуск: Esimde_start.bat или задача VS Code «Esimde: запустить + публичная ссылка»." 'Green'
}

function Invoke-Status {
    Say "Esimde: состояние" 'Cyan'
    $servers = @(Get-EsimdeServerProcesses)
    $tunnels = @(Get-EsimdeTunnelProcesses)
    if ($servers.Count) { Ok "сервер: процессы $(($servers | ForEach-Object { $_.ProcessId }) -join ', ')" } else { Warn "сервер не запущен" }
    if (Test-Health $LocalUrl) { Ok "локальный адрес отвечает: $LocalUrl" } else { Warn "локальный адрес не отвечает: $LocalUrl" }
    if ($tunnels.Count) { Ok "туннель: процессы $(($tunnels | ForEach-Object { $_.ProcessId }) -join ', ')" } else { Warn "туннель не запущен" }
    $url = Get-TunnelUrlFromLog
    if ($tunnels.Count -and $url) {
        if (Test-Health $url 10) { Ok "публичная ссылка отвечает: $url" }
        else { Warn "публичная ссылка пока не отвечает: $url" }
    }
}

function Invoke-Stop {
    Say "Esimde: остановка" 'Cyan'
    $found = $false
    $state = Read-State
    $ids = New-Object System.Collections.Generic.List[int]
    if ($state) {
        foreach ($key in @('tunnel_pid', 'server_pid')) {
            $id = [int]$state.$key
            if ($id -gt 0) {
                $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $id" -ErrorAction SilentlyContinue
                $startKey = $key -replace 'pid', 'start'
                if ($proc -and $proc.CreationDate.ToString('o') -eq $state.$startKey) { $ids.Add($id) }
            }
        }
    }
    foreach ($p in @(Get-EsimdeTunnelProcesses) + @(Get-LegacyServerWindows) + @(Get-EsimdeServerProcesses)) {
        if ($p -and -not $ids.Contains([int]$p.ProcessId)) { $ids.Add([int]$p.ProcessId) }
    }
    foreach ($id in $ids) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $id" -ErrorAction SilentlyContinue
        if ($proc) {
            $found = $true
            $what = 'сервер Esimde'
            if ($proc.Name -eq 'cloudflared.exe') { $what = 'туннель cloudflared' }
            elseif ($proc.Name -eq 'cmd.exe') { $what = 'окно старого запуска' }
            Stop-Tree $id $what
        }
    }
    Remove-Item $StateFile -Force -ErrorAction SilentlyContinue
    Remove-Item $UrlFile -Force -ErrorAction SilentlyContinue
    if (-not $found) { Ok "процессы Esimde не найдены - уже остановлено" }
    Start-Sleep -Milliseconds 500
    if (Test-Health $LocalUrl 2) { Warn "на $LocalUrl всё ещё что-то отвечает - проверьте другие окна." }
    else { Ok "порт $Port свободен" }
}

function Invoke-Start {
    Say "Esimde: запуск" 'Cyan'
    Say "  Каталог проекта: $AppDir" 'DarkGray'

    if (-not (Test-Path (Join-Path $AppDir 'serve.py'))) { Fail "не найден serve.py рядом со скриптом. Скрипт должен лежать в important_events\scripts." }

    if (-not (Test-Path $VenvPython)) {
        Say ""
        Say "Виртуальное окружение не найдено (.venv)." 'Yellow'
        Say "Выполните один раз:  Esimde_setup.bat   или задачу VS Code «Esimde: установка (venv + зависимости)»" 'White'
        Fail "нет .venv"
    }
    Ok "Python: $VenvPython"

    & $VenvPython -c "import flask, flask_wtf, apscheduler, waitress, pywebpush, tzdata" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Say "Не все зависимости установлены. Выполните: Esimde_setup.bat" 'Yellow'
        Fail "нет нужных библиотек Python"
    }
    Ok "зависимости Python на месте"

    $envFile = Join-Path $AppDir '.env'
    $hasToken = $false
    if (Test-Path $envFile) {
        $hasToken = [bool](Get-Content $envFile -Encoding UTF8 | Where-Object { $_ -match '^\s*TELEGRAM_BOT_TOKEN\s*=\s*\S+' })
    }
    if ($hasToken -or $env:TELEGRAM_BOT_TOKEN) { Ok "Telegram: токен найден (значение не показывается)" }
    else { Warn "Telegram: токен не задан - бот выключен (укажите TELEGRAM_BOT_TOKEN в .env)" }

    $servers = @(Get-EsimdeServerProcesses)
    $serverState = $null
    if ($servers.Count -gt 0) {
        $ready = $false
        for ($i = 0; $i -lt 15 -and -not $ready; $i++) { $ready = Test-Health $LocalUrl; if (-not $ready) { Start-Sleep 1 } }
        if (-not $ready) {
            Fail "найден уже запущенный процесс Esimde (PID $(($servers | ForEach-Object { $_.ProcessId }) -join ', ')), но он не отвечает на $LocalUrl. Выполните Esimde_stop.bat и запустите снова."
        }
        Ok "сервер Esimde уже запущен - второй экземпляр (и второй Telegram-бот) не запускаю"
        $state = Read-State
        if ($state) { $serverState = @{ pid = $state.server_pid; start = $state.server_start } }
    } else {
        $owners = @(Get-PortOwners)
        if ($owners.Count -gt 0) {
            $names = ($owners | ForEach-Object { $p = Get-Process -Id $_ -ErrorAction SilentlyContinue; if ($p) { "$($p.ProcessName) (PID $_)" } else { "PID $_" } }) -join ', '
            Fail "порт $Port занят другой программой: $names. Закройте её или запустите с другим портом: -Port 5001"
        }
        New-Item -ItemType Directory -Force $RunDir | Out-Null
        $env:PORT = "$Port"
        $env:HOST = '127.0.0.1'
        if ($NoTunnel) { $env:BEHIND_PROXY = '0' } else { $env:BEHIND_PROXY = '1' }
        $env:PYTHONIOENCODING = 'utf-8'
        $env:PYTHONUNBUFFERED = '1'
        $proc = Start-Process -FilePath $VenvPython -ArgumentList 'serve.py' -WorkingDirectory $AppDir `
            -WindowStyle Hidden -RedirectStandardOutput $ServerLog -RedirectStandardError $ServerErr -PassThru
        Say "  Сервер запускается (PID $($proc.Id)), жду готовности..."
        $ready = $false
        for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
            Start-Sleep -Milliseconds 500
            if ($proc.HasExited) { break }
            $ready = Test-Health $LocalUrl
        }
        if (-not $ready) {
            Say ""
            Say "Последние строки журнала сервера:" 'Yellow'
            if (Test-Path $ServerErr) { Get-Content $ServerErr -Tail 20 -Encoding UTF8 | ForEach-Object { Say "    $_" 'DarkYellow' } }
            Stop-Tree $proc.Id 'сервер Esimde'
            Fail "сервер не ответил на $LocalUrl/healthz."
        }
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.Id)"
        $serverState = @{ pid = $proc.Id; start = $cim.CreationDate.ToString('o') }
        Ok "сервер готов: $LocalUrl (слушает только 127.0.0.1)"
    }

    $publicUrl = $null
    $tunnelState = @{ pid = 0; start = '' }
    if (-not $NoTunnel) {
        $tunnels = @(Get-EsimdeTunnelProcesses)
        if ($tunnels.Count -gt 0) {
            $publicUrl = Get-TunnelUrlFromLog
            Ok "туннель уже запущен (PID $(($tunnels | ForEach-Object { $_.ProcessId }) -join ', '))"
            $tunnelState = @{ pid = $tunnels[0].ProcessId; start = $tunnels[0].CreationDate.ToString('o') }
        } else {
            $cf = Find-Cloudflared
            if (-not $cf -and $InstallCloudflared) { $cf = Install-Cloudflared }
            if (-not $cf) {
                Show-CloudflaredHelp
                Write-State @{ server_pid = $serverState.pid; server_start = $serverState.start; tunnel_pid = 0; tunnel_start = ''; url = ''; port = $Port }
                Show-Summary $null
                exit 2
            }
            Ok "cloudflared: $cf"
            Remove-Item $TunnelLog -Force -ErrorAction SilentlyContinue
            $cfArgs = "tunnel --no-autoupdate --logfile `"$TunnelLog`" --url $LocalUrl"
            $cfProc = Start-Process -FilePath $cf -ArgumentList $cfArgs -WindowStyle Hidden -PassThru
            Say "  Туннель запускается (PID $($cfProc.Id)), жду публичную ссылку..."
            for ($i = 0; $i -lt 90 -and -not $publicUrl; $i++) {
                Start-Sleep -Milliseconds 500
                if ($cfProc.HasExited) { break }
                $publicUrl = Get-TunnelUrlFromLog
            }
            if (-not $publicUrl) {
                Say ""
                Say "Последние строки журнала cloudflared:" 'Yellow'
                if (Test-Path $TunnelLog) { Get-Content $TunnelLog -Tail 15 -Encoding UTF8 | ForEach-Object { Say "    $_" 'DarkYellow' } }
                Stop-Tree $cfProc.Id 'туннель cloudflared'
                Fail "Cloudflare не выдал ссылку. Проверьте интернет и что брандмауэр не блокирует cloudflared. Локально сайт работает: $LocalUrl"
            }
            $cfCim = Get-CimInstance Win32_Process -Filter "ProcessId = $($cfProc.Id)"
            $tunnelState = @{ pid = $cfProc.Id; start = $cfCim.CreationDate.ToString('o') }
            Ok "Cloudflare выдал ссылку: $publicUrl"
            Say "  Жду подключения туннеля к Cloudflare..."
            $registered = $false
            for ($i = 0; $i -lt 60 -and -not $registered; $i++) {
                Start-Sleep -Milliseconds 500
                $registered = [bool](Select-String -Path $TunnelLog -Pattern 'Registered tunnel connection' -Quiet -ErrorAction SilentlyContinue)
            }
            if ($registered) { Ok "туннель подключён" } else { Warn "туннель ещё не подтвердил подключение" }
            Start-Sleep -Seconds 5
            Say "  Проверяю, что ссылка открывает Esimde (DNS может обновляться до минуты)..."
            $reachable = $false
            for ($i = 0; $i -lt 12 -and -not $reachable; $i++) { $reachable = Test-Health $publicUrl 10; if (-not $reachable) { Start-Sleep 5 } }
            if ($reachable) { Ok "публичная ссылка отвечает (/healthz = ok)" }
            else { Warn "ссылка пока не отвечает - подождите 1-2 минуты и откройте её снова (или выполните status)." }
        }
        if ($publicUrl) {
            Set-Content -Path $UrlFile -Value $publicUrl -Encoding UTF8
            try { Set-Clipboard -Value $publicUrl } catch { }
        }
    }

    Write-State @{ server_pid = $serverState.pid; server_start = $serverState.start;
                   tunnel_pid = $tunnelState.pid; tunnel_start = $tunnelState.start;
                   url = "$publicUrl"; port = $Port; started_at = (Get-Date).ToString('o') }
    Show-Summary $publicUrl

    if ($Follow) {
        Say ""
        Say "Журнал сервера (Ctrl+C - выйти из просмотра; сервер продолжит работу):" 'DarkGray'
        Get-Content $ServerErr -Wait -Tail 20 -Encoding UTF8
    }
}

switch ($Action) {
    'start'  { Invoke-Start }
    'stop'   { Invoke-Stop }
    'status' { Invoke-Status }
    'setup'  { Invoke-Setup }
}
