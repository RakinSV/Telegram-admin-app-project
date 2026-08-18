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

Write-Host "=== Пересоздаю контейнеры ===" -ForegroundColor Cyan
docker compose up -d --force-recreate tg_repost guardian engage

Write-Host "=== Проверяю, что админка отвечает ===" -ForegroundColor Cyan
$ok = $false
foreach ($i in 1..12) {
    Start-Sleep -Seconds 10
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8001/health" -TimeoutSec 10
        if ($r.StatusCode -eq 200) {
            Write-Host $r.Content
            $ok = $true
            break
        }
    } catch {
        Write-Host ("ещё не отвечает (" + $i + "/12)")
    }
}

docker compose ps --format "table {{.Service}}`t{{.Status}}"

if (-not $ok) {
    Write-Host "АДМИНКА НЕ ОТВЕТИЛА — смотри логи: docker compose logs tg_repost --tail 50" -ForegroundColor Red
    exit 1
}
Write-Host "Готово." -ForegroundColor Green
