<div align="center">

```
╔══════════════════════════════════════════════════════════════════╗
║                                                                    ║
║   ████████╗ ██████╗     ██████╗ ███████╗██████╗  ██████╗ ███████╗║
║   ╚══██╔══╝██╔════╝     ██╔══██╗██╔════╝██╔══██╗██╔═══██╗██╔════╝║
║      ██║   ██║  ███╗    ██████╔╝█████╗  ██████╔╝██║   ██║███████╗║
║      ██║   ██║   ██║    ██╔══██╗██╔══╝  ██╔═══╝ ██║   ██║╚════██║║
║      ██║   ╚██████╔╝    ██║  ██║███████╗██║     ╚██████╔╝███████║║
║      ╚═╝    ╚═════╝     ╚═╝  ╚═╝╚══════╝╚═╝      ╚═════╝ ╚══════╝║
║                                                                    ║
║        + G U A R D I A N  ·  AI group-chat moderation             ║
╚══════════════════════════════════════════════════════════════════╝
```

**An automated Telegram content pipeline: scrape → LLM rewrite → moderate → publish — plus a standalone AI moderator bot for your group chat.**
Two independent bots, one web admin panel, all self-hosted.

🇬🇧 **English** &nbsp;|&nbsp; 🇷🇺 [Русский](README.ru.md) &nbsp;|&nbsp; 📖 [Wiki (full docs, FAQ, troubleshooting)](../../wiki)

[![CI](https://img.shields.io/github/actions/workflow/status/RakinSV/Telegram-admin-app-project/ci.yml?branch=main&label=CI&style=flat-square)](https://github.com/RakinSV/Telegram-admin-app-project/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-537%20passing-brightgreen?style=flat-square)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square)](https://www.python.org/)
[![Ruff](https://img.shields.io/badge/lint-ruff-red?style=flat-square)](https://github.com/astral-sh/ruff)
[![mypy](https://img.shields.io/badge/type--checked-mypy-blue?style=flat-square)](https://mypy-lang.org/)
[![Bandit](https://img.shields.io/badge/security-bandit-yellow?style=flat-square)](https://bandit.readthedocs.io/)
[![Docker](https://img.shields.io/badge/deploy-docker--compose-2496ED?style=flat-square&logo=docker&logoColor=white)](docker-compose.yml)

</div>

---

## Why this exists

A Telegram channel owner usually picks between two bad options: manually
rewrite other people's posts every day, or just forward them and risk
plagiarism complaints and audience loss. This project automates the whole
path from source post to publication — LLM rewriting, duplicate detection,
pre-publish moderation, and stats on what actually resonates with your
audience. A separate **Guardian** bot protects the group at the same time,
so the audience the first bot grows doesn't get drowned by spam, bots, and
raids.

Both bots are production-ready: Alembic migrations from day one, 537 tests,
CI running lint/type-check/security-scan on every push, Docker packaging for
VPS/Proxmox deployment, and a single web admin panel instead of poking at
`.env` files and a database by hand.

This README is the overview and quick start. For a **beginner-friendly,
step-by-step deployment walkthrough with FAQ and troubleshooting**, see the
**[Wiki](../../wiki)** — if you've never run a Docker container before,
start there, not here. For deep implementation-level context and
architecture decisions (written for contributors/maintainers, not end
users), see [CLAUDE.md](CLAUDE.md), the repost bot's feature backlog in
[FEATURES.md](FEATURES.md), the phased implementation plan in
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), and Guardian's own docs in
[guardian/GUARDIAN.md](guardian/GUARDIAN.md) and
[guardian/GUARDIAN_FEATURES.md](guardian/GUARDIAN_FEATURES.md) (these four
are in Russian).

---

## Contents

- [What's inside](#whats-inside)
- [Repost bot — features](#repost-bot--features)
- [Guardian — AI group moderator](#guardian--ai-group-moderator)
- [Web admin panel](#web-admin-panel)
- [Proxies](#proxies)
- [Stack](#stack)
- [Quick start (no Docker)](#quick-start-no-docker)
- [Docker deployment](#docker-deployment)
- [CLI commands](#cli-commands)
- [Bot commands in Telegram](#bot-commands-in-telegram)
- [Tests and code quality](#tests-and-code-quality)
- [Backup](#backup)
- [Project structure](#project-structure)
- [Implementation status](#implementation-status)
- [Support the project](#support-the-project)

---

## What's inside

```
┌─────────────────────────────── Repost bot ────────────────────────────────┐
│                                                                             │
│  N Telegram channels                                                      │
│         │  Telethon (user session, reads without Bot API limits)          │
│         ▼                                                                 │
│  keyword filter → hash dedup → semantic dedup check (embeddings)          │
│         │                                                                 │
│         ▼                                                                 │
│  LLM rewrite (style profile per post type) + source enrichment (Brave)    │
│  + RU/EN version comparison + auto cover image (Unsplash/ComfyUI)         │
│         │                                                                 │
│         ▼                                                                 │
│  manual moderation via DM (✅/❌/✏️) OR scheduled auto-posting             │
│         │                                                                 │
│         ▼                                                                 │
│  publish to N groups → collect stats → auto-digest / native ads /         │
│  smart scheduling / growth tracker                                        │
└─────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────── Guardian ──────────────────────────────────┐
│                                                                             │
│  New member → CAPTCHA (math/button/question) → muted until answered →     │
│               welcome message with rules / auto-kick on timeout            │
│                                                                             │
│  Every message → anti-flood → link whitelist → stop words →               │
│                   suspicion heuristics → AI classifier                     │
│                   (only for the suspicious ~20% — saves tokens)            │
│                                                                             │
│  Violations → escalating warns (mute → kick → ban) → log channel          │
│  Join spike → anti-raid (chat lockdown) → auto-unlock                     │
│  30 clean days → auto-trust (bypasses filters)                            │
└─────────────────────────────────────────────────────────────────────────┘
```

Both processes live in one repository but are **independent bots** — their
own tokens, their own databases (`tg_repost.db` / `guardian.db`), their own
Alembic migration chains. One crashing or being redeployed doesn't touch the
other. Both are managed from a single web panel.

---

## Repost bot — features

### Content collection and quality
- **Reads without Bot API limits** — Telethon on a user session sees any
  public/accessible channel, not just ones where the bot is an admin.
- **Keyword filtering** — global or per-channel stop-/required-words,
  applied before a post ever enters the queue.
- **Two-layer deduplication** — fast exact-match hashing plus optional
  semantic dedup via embeddings (catches paraphrased copies from other
  channels).
- **Rewrite style profiles** — news / opinion / instruction / humor, each
  with its own prompt template, per-source or auto-selected by the LLM.
- **Source enrichment** — Brave Search finds 2-3 relevant links (RU + EN) on
  the post's topic, the LLM picks the best ones, a "📚 Sources" block is
  appended — builds audience trust and guards against misinformation
  accusations.
- **Version comparison** — if Russian and English sources disagree on the
  story, the post is honestly flagged "⚠️ conflicting accounts".
- **Auto cover images** — if a post has no media, generate one via the
  Unsplash API (fast, free) or a local ComfyUI instance (unique AI
  generation).

### Publishing and growth
- **Flexible moderation** — manual approval via DM buttons / full autopilot
  / drip-posting on time slots, any combination.
- **Multi-channel publishing** — per-source target overrides
  (`Source.target_chat_ids`), not a blanket "everything to every group".
- **Smart scheduling** — analyzes view history to find your audience's peak
  hours and recommends (or auto-applies) a shift in posting slots.
- **Auto-digest** — once a week the LLM compiles a summary of the best
  posts.
- **Native ads** — every Nth post organically weaves in an ad brief in the
  channel's own voice, rotating through briefs.
- **Growth tracker** — subscriber-count snapshots plus per-style post
  counts, so you can see what's actually growing the channel.
- **Negative-reaction auto-response** — counts 👎/💩/😡 reactions, notifies
  the owner and optionally deletes the post past a threshold (with
  brigading protection — a cap on auto-deletes per hour).

### Reliability and scale
- **Anti-ban mechanics** — jitter between requests, hourly read limits —
  reduce the risk of the Telethon user session getting restricted.
- **Multiple Telethon session rotation** — balances source reading across
  accounts as the channel count grows, with a separate rate limiter per
  session.
- **Post status machine** — explicit transitions `new → filtered_out |
  duplicate → rewriting → rewritten → pending_approval → approved |
  rejected → posted | failed`, every transition logged.
- **Retry with exponential backoff** on every network call (Telegram, LLM,
  search).
- **MTProto/SOCKS5 proxy support** — Telethon (user session) goes through
  an MTProto proxy, the Bot API (posting/moderation) through SOCKS5; see
  [Proxies](#proxies) below — **and read the Wiki's Proxy Guide before you
  configure this, there's an important limitation.**

---

## Guardian — AI group moderator

A separate bot on `aiogram`. Its job isn't to review content — it's to
**protect the real people in your group** from spam, bots, and toxicity
while your audience grows.

### New-member verification
- Muted immediately on join → CAPTCHA (math / "I'm not a robot" button /
  channel-topic question) → restrictions lifted on a correct answer.
- No answer within N minutes → auto-kick.
- The "who answered first" race and "who is actually the new member vs. who
  invited them" confusion are closed via explicit `user_id` addressing
  rather than aiogram FSM context (a real security bug found and fixed —
  see commit history).
- **Profile analysis** — no username/photo, suspicious bio, brand-new
  account → a stronger CAPTCHA for risky profiles (never an auto-ban based
  on profile alone — that would be too aggressive).

### Spam filter — three modes to choose from
| Mode | How it works | When to use it |
|---|---|---|
| `keywords` | Stop-word list with anti-evasion normalization (homoglyphs, zero-width characters, separators) | Zero cost, for small/quiet groups |
| `ai` | Every message is classified via an OpenAI-compatible API, JSON response with a confidence score | Best quality, but spends tokens on every message |
| `hybrid` | Heuristics (prices, "DM me", zero-width chars, forwards, brand-new accounts) select ~20% as suspicious → only those go to the AI | **Recommended** — AI-level quality at keyword-filter cost |

The AI classifier is **fail-open**: any error, timeout, or invalid JSON is
treated as "let it through", never as "delete" — when unsure, the bot never
cuts a legitimate message.

### Moderation and protection
- **Link whitelist filter**, including links hidden behind text
  (`text_link` entities).
- **Anti-flood** — message-rate limit per window plus repeated-duplicate
  detection.
- **Warn system** with escalation to the highest threshold reached (mute →
  kick → ban), scheduled TTL auto-reset of warns.
- **Anti-raid** — a join spike locks down the whole chat's permissions
  (restoring the *previous* permissions, not defaults, on unlock), with
  manual/auto unlock buttons once things calm down.
- **Quiet hours** — scheduled auto-switch between strict (warn on any
  violation) and soft (log only, no deletion) modes.
- **Auto-trust** — members with no violations for N days automatically
  bypass filters, cutting AI load on an active, already-vetted audience.
- **Log channel** — every moderation action, manual or automatic, is
  written to a private channel with inline buttons for a quick admin
  response.
- **SOCKS5 proxy support for the Bot API** — see [Proxies](#proxies) below.
- **21 admin commands** — `/warn /mute /unmute /ban /unban /kick /check
  /addword /delword /listwords /trust /untrust /addomain /deldomain
  /listdomains /setmode /setcaptcha /setwarn /setmutime /mode /stats
  /growth` — the entire config changes on the fly, no bot restart needed.

---

## Web admin panel

A single FastAPI panel for both bots, embedded in the same process as
`main.py` (not a separate service) — settings apply live, logs stream to
the browser without any inter-process syncing.

- **`/setup`** — first-run wizard: admin password + Telegram login right in
  the browser (phone → code → 2FA), no terminal fiddling.
- **`/`** dashboard — post funnel by status, today's rewrite token usage,
  24h error rate, component status (listener/bot/scheduler).
- **`/sources` `/targets` `/moderation` `/ads` `/stats`** — full CRUD,
  mirrors the CLI and the Telegram bot against the same business logic (not
  two code paths that can drift apart).
- **`/settings`** — ~25 settings grouped by feature, applied live; fields
  marked `resync` automatically rebuild the relevant scheduler jobs.
- **`/secrets`** — write-only form: the value is encrypted (`Fernet`) and
  never sent back to the browser, only a `••••a1b2` mask.
- **`/components`** — live restart of the Telethon listener/bot without
  restarting the process, after changing a token or session.
- **`/guardian*`** — manage Guardian from the same panel: spam-filter mode,
  warn thresholds, stop words, link whitelist, trusted users — no Telegram
  command needed.
- **`/audit`** — log of every action taken from the admin panel (who, what,
  when).
- **`/logs`** — live process logs via Server-Sent Events, no WebSocket
  infrastructure required.

Access is **localhost/VPN-only by design** (no mandatory TLS), sessions
have idle and absolute timeouts, `/login` is rate-limited, passwords use
Argon2id.

---

## Proxies

Telethon (the user session) talks to Telegram directly over **MTProto** — a
regular SOCKS5/HTTP proxy won't work there, it needs an actual
**MTProto proxy**. The Bot API (posting/moderation for both bots), on the
other hand, runs over plain HTTPS — MTProto is useless there, it needs
**SOCKS5**. Many providers selling proxies "for Telegram automation" offer
both endpoints on the same server.

| What's proxied | Type | Where to configure |
|---|---|---|
| Telethon (main session + all of the F26 rotation) | MTProto | `/settings` (host/port) + `/secrets` (secret) — one shared proxy for every Telethon client |
| Repost bot's Bot API | SOCKS5 | `/secrets` (`Bot API Proxy URL`, the whole thing including credentials) |
| Guardian's Bot API | SOCKS5 | **`.env` only** (`GUARDIAN_BOT_API_PROXY_URL`) — unlike the repost bot, Guardian has no live component restart; `Bot()` is built once at process start, same as `GUARDIAN_BOT_TOKEN`; changing it needs `docker compose restart guardian` |

Leave everything blank for a direct connection (the default, nothing to
configure if you don't need a proxy).

> ⚠️ **Read this before setting up an MTProto proxy.** Telethon's built-in
> MTProto proxy support does **not** implement fake-TLS mode (secrets
> starting with `ee`) — this is a known limitation of the library itself,
> not something this project can patch around. Most modern public MTProto
> proxies default to fake-TLS. If your proxy secret starts with `ee`,
> Telethon will hang or fail with a garbled decryption error no matter what
> you configure here. You need a classic secret (plain hex, or `dd`-prefixed)
> from the same proxy, or a different proxy entirely. **Full details, real
> error messages, and a decision tree in the [Wiki's Proxy
> Guide](../../wiki/Proxy-Guide).**

---

## Stack

| Layer | Technology | Why |
|---|---|---|
| Channel reading | **Telethon** (user session) | Bot API can't read someone else's channel without admin rights there |
| Publishing/moderation | **python-telegram-bot** (repost) · **aiogram 3.x** (Guardian) | aiogram gives FSM out of the box for the multi-step CAPTCHA |
| Rewriting/classification | **OpenAI SDK**, any compatible `base_url` | GPT-4o-mini, Claude via a proxy, local llama.cpp/Ollama — no code changes needed |
| Database | **SQLite + SQLAlchemy + Alembic** | Simple, one file, easy to back up; a path to Postgres is open from day one |
| Scheduler | **APScheduler** | Cron-like jobs inside the process, no Celery/Redis for a single operator |
| Web admin panel | **FastAPI + Jinja2 + Starlette Sessions** | Embedded in the shared event loop, settings live-reload with no frontend build step |
| Secrets | **Fernet (cryptography)** + Argon2id | Symmetric encryption at rest, write-only UI |
| CI | **GitHub Actions**: ruff · mypy · pytest · bandit · pip-audit | Every push is checked by a linter, a type checker, and two security scanners |
| Deployment | **Docker + docker-compose** | Two services on one image, different entrypoints, isolated volumes |

---

## Quick start (no Docker)

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# bash/zsh:
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # fill in secrets, or leave blank and use /setup later

alembic upgrade head                            # repost bot schema
alembic -c alembic_guardian.ini upgrade head     # Guardian schema (if you're running it too)

python -m tg_repost.main
```

Open `http://127.0.0.1:8000/setup` — the web wizard comes up even with
every `.env` value blank. Everything else is configured from the browser
from there.

Telethon needs a session string:
```bash
python -m tg_repost.tools.gen_session
```
(Or skip this entirely and use the **"Log in via Telegram"** button in the
web wizard instead — it does the phone/code/2FA flow right in the browser.)

Guardian runs as a separate process:
```bash
python -m guardian.bot
```
The bot must be added to the group it protects **as an administrator**,
with these permissions: delete messages, ban/kick members, restrict members
(mute), manage invite links (needed for anti-raid).

---

## Docker deployment

This is the recommended way to run this project. If you've never used
Docker before, follow along — but for a truly beginner-proof, click-by-click
walkthrough with screenshots of common errors, use the
**[Wiki's Installation Guide](../../wiki/Installation)** instead of this
condensed version.

### 1. Install Docker

**Debian/Ubuntu:**
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in (or run `newgrp docker`) — group membership doesn't
# apply to your current shell session until you do.
```

Verify:
```bash
docker compose version
```
If that fails with something like `unknown command "compose"`, you have the
old standalone `docker-compose` (or nothing) rather than the Compose V2
plugin this project's commands assume. Install it:
```bash
sudo apt update && sudo apt install docker-compose-plugin
```

**Windows/macOS:** install [Docker Desktop](https://www.docker.com/products/docker-desktop/) — Compose V2 is bundled.

### 2. Clone the repository

```bash
git clone https://github.com/RakinSV/Telegram-admin-app-project.git
cd Telegram-admin-app-project
```

### 3. Create `.env` — **before** the first `docker compose up`

```bash
cp .env.example .env
```

This step is not optional and the order matters: if `.env` doesn't exist
yet, Docker's bind mount (`./.env:/app/.env` in `docker-compose.yml`)
creates a **directory** named `.env` instead of mounting a file, and the
container fails to start with a confusing error. You don't need to fill
anything in by hand — leave every secret blank and set them later through
the `/setup` web wizard. The only thing worth doing now is opening `.env`
and skimming the comments so you know what exists.

### 4. Start it

```bash
docker compose up -d --build
```

First build takes a couple of minutes (pulling dependencies). Two services
come up on the same image — `tg_repost` (web admin panel + repost pipeline,
published on `127.0.0.1:8000`) and `guardian` (group moderation) — each
with its own entrypoint, independent restart policy (`unless-stopped`), a
shared `.env`, and separate volumes for the database/logs/media.

Check it's healthy:
```bash
docker compose ps
docker compose logs -f tg_repost
```

### 5. Open the admin panel

The port is published as `127.0.0.1:8000` — **loopback of the Docker host
only**, by design, matching the same localhost/VPN-only security perimeter
you'd have running without Docker. If you're on the same machine, open
`http://127.0.0.1:8000/setup` in a browser. If you're deploying on a
**remote server**, you have two options — both covered in detail, with
exact commands, in the **[Wiki](../../wiki/Installation#step-6--open-the-admin-panel)**:
- SSH tunnel from your laptop (`ssh -L 8000:127.0.0.1:8000 user@server`), or
- a `docker-compose.override.yml` that publishes on a VPN/LAN interface
  instead of `127.0.0.1` (never publish this panel directly on a public IP
  without a reverse proxy and TLS in front of it).

First run prints a one-time setup token to the logs — grab it with:
```bash
docker compose logs tg_repost | grep -i token
```

From there: create an admin password, then use the **"Log in via
Telegram"** button on the `/secrets` page to connect your Telethon account
(phone → code → 2FA, right in the browser — no terminal needed).

### 6. Updating

```bash
git pull
docker compose up -d --build
```
Your `.env` and both databases (in `./data/`) are untouched — they live
outside the image, in bind-mounted volumes.

### Common problems

| Symptom | Cause | Fix |
|---|---|---|
| `unknown command "compose"` | Compose V2 plugin not installed | `sudo apt install docker-compose-plugin` |
| `permission denied ... docker.sock` | Group membership from `usermod -aG docker` not applied yet | Log out/in, or `newgrp docker` |
| `.env` created as a directory | `docker compose up` ran before `.env` existed | `docker compose down`, `rmdir .env` (it's empty), `cp .env.example .env`, retry |
| `/guardian*` pages 500 with "no such table" | `GUARDIAN_DATABASE_URL` mismatch between services, or a stale image before a fix landed | `docker compose up -d --build` to rebuild both services from the current `docker-compose.yml` |
| Telethon login hangs or fails with a garbled error | MTProto proxy in fake-TLS mode — unsupported, see [Proxies](#proxies) above | Read the [Wiki's Proxy Guide](../../wiki/Proxy-Guide) |

More scenarios, with real error text, live in the **[Wiki
FAQ](../../wiki/FAQ)**.

---

## CLI commands

```bash
# Sources and targets (F01, F12)
python -m tg_repost.cli add-source @some_channel
python -m tg_repost.cli list-sources
python -m tg_repost.cli remove-source @some_channel
python -m tg_repost.cli add-target -1001234567890 --title "My channel"
python -m tg_repost.cli set-source-targets @some_channel -- -1001111,-1002222
python -m tg_repost.cli set-source-style @some_channel news
python -m tg_repost.cli set-source-enrich @some_channel on

# Native ads (F21)
python -m tg_repost.cli add-ad-brief "20% off at our partner" --max-uses 5
python -m tg_repost.cli list-ad-briefs

# Telethon session rotation (F26)
python -m tg_repost.cli add-telethon-session "Second account"   # prompts for the session string via getpass
python -m tg_repost.cli list-telethon-sessions

# Backup
python -m tg_repost.tools.backup --keep 14
```

## Bot commands in Telegram

**Repost bot** (DM to the owner): `/start` `/stats` `/best_times` `/growth`

**Guardian** (in the group, admins only):
```
/warn /mute /unmute /ban /unban /kick /check      — member moderation
/addword /delword /listwords                      — stop words
/addomain /deldomain /listdomains                  — link whitelist
/trust /untrust                                    — trusted users
/setmode /setcaptcha /setwarn /setmutime /mode      — live config
/stats /growth                                      — moderation stats
```

---

## Tests and code quality

```bash
pytest                                            # 537 tests
ruff check tg_repost guardian                     # linter
mypy tg_repost guardian                           # static typing — 0 errors
bandit -r tg_repost guardian -c pyproject.toml     # security scanner, documented baseline
pip-audit -r requirements.txt                      # dependency CVEs
```

All of this runs automatically in CI on every push/PR
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)). Every feature in
this repository went through at least one review cycle with code-reviewer
and security-auditor agents — real findings (from path traversal to a race
condition in the CAPTCHA flow to an auth bypass in anti-raid) were fixed and
locked in with regression tests, not just written up in an issue.

---

## Backup

```bash
python -m tg_repost.tools.backup            # keeps the last 14 backups
0 3 * * * cd /path/to/repo && python -m tg_repost.tools.backup   # cron
```
Archives `.env` plus both SQLite databases plus `logs/` into one zip —
without `.env`, encrypted secrets in the database are unrecoverable, so
they're backed up together. The archive file is chmod'd `0600`; don't sync
`backups/` to the cloud without separate encryption (`age`/GPG).

---

## Project structure

```
tg_repost/              # repost bot
  webui/                 # web admin panel for both bots (FastAPI + Jinja2)
  telegram/               # Telethon listener, publisher, moderation bot
  rewriter/                # LLM client: rewriting, styles, embeddings
  dedup/                    # hash + semantic dedup check
  enrichment/                # Brave Search source enrichment
  covers/                     # Unsplash / ComfyUI auto covers
  ads/                         # native advertising
  scheduler/                    # APScheduler jobs: posting, stats, digest, growth
  db/                            # ORM + Alembic migrations
  tools/                          # gen_session, check_telethon, backup

guardian/                # AI group moderator (separate bot, own database)
  handlers/                # join (CAPTCHA), messages (spam filter), admin, stats
  filters/                   # keyword / ai / heuristics / link / flood
  services/                   # warn_system, captcha, raid_detector, profile_analyzer
  db/                           # own ORM + Alembic chain

tests/                   # 537 tests — pytest + pytest-asyncio
.github/workflows/       # CI: ruff, mypy, pytest, bandit, pip-audit
```

---

## Implementation status

- ✅ **Repost bot** — Phases 0–6 complete: collection, rewriting, dedup,
  moderation, publishing, stats, style profiles, source enrichment, auto
  covers, smart scheduling, digest, native ads, growth tracker, session
  rotation, web admin panel (full CRUD + audit log + live logs), Docker
  packaging.
- ✅ **Guardian** — all phases G0–G17: CAPTCHA, welcome, three spam-filter
  modes, warns, anti-flood, anti-raid, profile analysis, quiet hours,
  auto-trust, stats, config via commands and the web panel.
- ✅ **CI/CD** — GitHub Actions on every push/PR, fully clean
  mypy/ruff/bandit/pip-audit across both packages.
- ✅ **Auto-backup** — `.env` + both databases + logs in one script.
- ✅ **MTProto/SOCKS5 proxy support** — Telethon via MTProto, both bots'
  Bot API via SOCKS5, configured through `/settings`+`/secrets` (see
  [Proxies](#proxies) — and read the fake-TLS caveat).
- ✅ **Production deployment proven** — an LXC on Proxmox (Docker inside an
  unprivileged container with nesting enabled), a full `docker compose up`
  run end to end.
- ⬜ **Real production tokens** — purely an operational step at this point:
  fill in real `TG_*`/`GUARDIAN_BOT_TOKEN`/`GUARDIAN_GROUP_ID` values and
  add Guardian to a group as an administrator.
- 💭 **Deliberately out of scope for now** — a multi-tenant SaaS version
  for other channel owners; a dedicated web panel for Guardian rather than
  a section inside the shared admin panel; live restart for Guardian
  without a full process restart (currently only the repost bot has this,
  see `/components`).

---

## Support the project

This project is written and maintained in spare time, with no grant and no
company behind it. If it's been useful to you, a coffee helps keep the
feature work going:

**Bitcoin:**
```
bc1qwnkyez3nv86dry54dqfjjtav29qqq72h69pevw
```

A star on the repository costs nothing but helps other people find the
project.

---

<div align="center">

*Keywords: telegram bot · telegram repost bot · telegram auto-posting ·
telegram channel automation · rewrite bot AI · openai rewriter · content
repost automation · telegram moderation bot · anti-spam telegram bot ·
telegram chat moderator · captcha verification bot · anti-raid telegram ·
telethon userbot · aiogram bot · python telegram automation · self-hosted
telegram bot · fastapi admin panel · telegram channel growth · AI content
pipeline*

</div>
