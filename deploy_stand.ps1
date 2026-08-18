# ФАЙЛ СОХРАНЁН С BOM НАМЕРЕННО. Windows PowerShell 5.1 читает .ps1 без
# BOM как ANSI: кириллица в комментариях превращается в мусор, и скрипт
# падает на разборе, а не на логике. Проверено на стенде — первый запуск
# упал с MissingEndCurlyBrace именно поэтому.
# Обновление стенда одной командой. Запускается НА СТЕНДЕ:
#   powershell -ExecutionPolicy Bypass -File C:\deploy\tg-app\deploy_stand.ps1
#
# ЗАЧЕМ СКРИПТ, А НЕ ТРИ КОМАНДЫ РУКАМИ. Обе беды прошлых деплоев — из-за
# неполной последовательности, выполненной по памяти:
#   * пересобирали только `tg_repost`, и Guardian оставался на старом образе,
#     падая на миграции, которой не знал (2026-08-18);
#   * код доставлялся zip-архивом поверх каталога: не видно развёрнутой
#     версии, нет отката, удалённые файлы остаются лежать.
#
# Здесь всё это зафиксировано: код из git (значит, версия видна и откат — это
# `git reset --hard <коммит>`), пересобираются ВСЕ сервисы, а в конце
# проверяется, что админка действительно отвечает.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== Текущая версия ===" -ForegroundColor Cyan
git log --oneline -1

Write-Host "=== Забираю обновления ===" -ForegroundColor Cyan
git fetch --depth 50 origin main
# reset --hard, а не pull: рабочая копия на стенде правиться не должна, и
# случайная локальная правка не должна превращать обновление в конфликт.
# `.env` и `data/` не отслеживаются git и потому не трогаются.
git reset --hard origin/main
git log --oneline -1

Write-Host "=== Резервная копия базы перед обновлением ===" -ForegroundColor Cyan
# Копия ДО, а не после: если обновление окажется неудачным, откатывать надо
# будет и код, и данные — миграции применяются при старте контейнера.
$stamp = Get-Date -Format "yyyyMMdd_HHmm"
$dest = Join-Path $PSScriptRoot "data\backups\pre_deploy_$stamp"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item "data\db\*.db" $dest -Force
Get-ChildItem $dest | Select-Object Name, Length | Format-Table -AutoSize

Write-Host "=== Пересобираю образы (все три сервиса) ===" -ForegroundColor Cyan
docker compose build tg_repost guardian engage
# PowerShell НЕ останавливается на ненулевом коде внешней команды, поэтому
# проверяем явно. Иначе неудачная сборка проходит незамеченной, а следующий
# шаг поднимает контейнеры из СТАРОГО образа — и деплой рапортует «готово»,
# ничего не развернув (поймано 2026-08-18: контейнер работал на прежнем коде,
# а скрипт этого не видел).
if ($LASTEXITCODE -ne 0) {
    Write-Host "СБОРКА НЕ УДАЛАСЬ — деплой прерван" -ForegroundColor Red
    exit 1
}
$built = docker image inspect tg-app-tg_repost:latest --format "{{.Id}}"

Write-Host "=== Пересоздаю контейнеры ===" -ForegroundColor Cyan
docker compose up -d --force-recreate tg_repost guardian engage
if ($LASTEXITCODE -ne 0) {
    Write-Host "КОНТЕЙНЕРЫ НЕ ПЕРЕСОЗДАНЫ — деплой прерван" -ForegroundColor Red
    exit 1
}

Write-Host "=== Сверяю: работает ли ТОТ образ, который собрали ===" -ForegroundColor Cyan
# Проверка по факту, а не по последовательности шагов. Совпадение команд не
# доказывает, что контейнер поднялся из новой сборки, — а расхождение здесь
# ровно то, из-за чего стенд однажды сутки работал на прежнем коде.
$running = docker inspect tg-app-tg_repost-1 --format "{{.Image}}"
if ($running -ne $built) {
    Write-Host "РАЗВЁРНУТ НЕ ТОТ ОБРАЗ:" -ForegroundColor Red
    Write-Host ("  собран:  " + $built)
    Write-Host ("  работает: " + $running)
    Write-Host "Повтори: docker compose up -d --force-recreate tg_repost guardian engage"
    exit 1
}
Write-Host "образ совпал" -ForegroundColor Green

Write-Host "=== Проверяю, что админка отвечает ===" -ForegroundColor Cyan
$ok = $false
foreach ($i in 1..24) {
    Start-Sleep -Seconds 10
    # Ждём до четырёх минут: миграции на базе в 8+ МБ идут заметно дольше
    # двух, и прежний предел давал ложную тревогу на успешном деплое.
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8001/health" -TimeoutSec 10
        if ($r.StatusCode -eq 200) {
            Write-Host $r.Content
            $ok = $true
            break
        }
    } catch {
        Write-Host ("ещё не отвечает (" + $i + "/24)")
    }
}

docker compose ps --format "table {{.Service}}`t{{.Status}}"

if (-not $ok) {
    Write-Host "АДМИНКА НЕ ОТВЕТИЛА — смотри логи: docker compose logs tg_repost --tail 50" -ForegroundColor Red
    exit 1
}
Write-Host "Готово." -ForegroundColor Green
