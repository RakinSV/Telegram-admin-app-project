<div align="center">

```
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║   ████████╗ ██████╗     ██████╗ ███████╗██████╗  ██████╗ ███████╗║
║   ╚══██╔══╝██╔════╝     ██╔══██╗██╔════╝██╔══██╗██╔═══██╗██╔════╝║
║      ██║   ██║  ███╗    ██████╔╝█████╗  ██████╔╝██║   ██║███████╗║
║      ██║   ██║   ██║    ██╔══██╗██╔══╝  ██╔═══╝ ██║   ██║╚════██║║
║      ██║   ╚██████╔╝    ██║  ██║███████╗██║     ╚██████╔╝███████║║
║      ╚═╝    ╚═════╝     ╚═╝  ╚═╝╚══════╝╚═╝      ╚═════╝ ╚══════╝║
║                                                                  ║
║   + G U A R D I A N  · moderation   + E N G A G E · gamification ║
╚══════════════════════════════════════════════════════════════════╝
```

# Self-Hosted Telegram Automation — Repost Bot + Guardian Moderation + Engage Gamification

**An automated Telegram repost bot with a two-agent AI editorial desk: scrape → rewrite & fact-check → moderate → publish — plus an AI group moderator (Guardian) and an audience-engagement bot (Engage).**
Three independent bots, one web admin panel, all self-hosted.

🇬🇧 **English** &nbsp;|&nbsp; 🇷🇺 [Русский](README.ru.md) &nbsp;|&nbsp; 📖 [Wiki (full docs, FAQ, troubleshooting)](../../wiki)

[![CI](https://img.shields.io/github/actions/workflow/status/RakinSV/Telegram-admin-app-project/ci.yml?branch=main&label=CI&style=flat-square)](https://github.com/RakinSV/Telegram-admin-app-project/actions/workflows/ci.yml)
[![Stars](https://img.shields.io/github/stars/RakinSV/Telegram-admin-app-project?style=flat-square)](https://github.com/RakinSV/Telegram-admin-app-project/stargazers)
[![Tests](https://img.shields.io/badge/tests-1253%20passing-brightgreen?style=flat-square)](tests/)
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
path from source post to publication — but the interesting part isn't the
automation, it's the **editorial quality**: a journalist agent writes the
draft, an editor agent fact-checks it against the sources, disputed claims
get verified against the open web, and the journalist rewrites. You watch
that argument happen live in a Telegram chat.

Around that pipeline sit two more bots. **Guardian** protects the group from
spam, bots, and raids, so the audience the first bot grows doesn't drown.
**Engage** turns readers into participants — quizzes generated from the posts
themselves, a referral programme with real anti-fraud, and verifiable
contest draws.

All three are production-ready: Alembic migrations from day one, 1253 tests,
CI running lint/type-check/security-scan on every push, Docker packaging for
VPS/Proxmox deployment, and a single web admin panel instead of poking at
`.env` files and a database by hand.

This README is the overview and quick start.

- **New to Docker, or just want it running?** Start with the
  **[Wiki](../../wiki)** — a beginner-friendly, step-by-step walkthrough with
  FAQ and troubleshooting.
- **Contributing or exploring the code?** See [CLAUDE.md](CLAUDE.md)
  (architecture decisions), [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) (system
  passport), [FEATURES.md](FEATURES.md) (feature backlog),
  [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) (phased plan), and
  Guardian's own [GUARDIAN.md](guardian/GUARDIAN.md) /
  [GUARDIAN_FEATURES.md](guardian/GUARDIAN_FEATURES.md) — note: these are
  written in Russian.

---

## Contents

- [What's inside](#whats-inside)
- [The editorial desk — two AI agents](#the-editorial-desk--two-ai-agents-draft--fact-check)
- [Repost bot — features](#repost-bot--features)
- [Guardian — AI group moderator](#guardian--ai-group-moderator-captcha-spam-filter-anti-raid)
- [Engage — turning readers into participants](#engage--turning-readers-into-participants-quizzes-referrals-contests)
- [Web admin panel](#web-admin-panel)
- [Proxies](#proxies-mtproto--socks5--http)
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
│  ╭─ editorial desk ──────────────────────────────────────────────╮       │
│  │ journalist writes draft → editor fact-checks against sources  │       │
│  │      ▲                              │                          │       │
│  │      └── rewrite ◀── web-verify disputed claims ◀─────────────┘       │
│  ╰───────────────────────────────────────────────────────────────╯       │
│         │  (the whole argument is streamed to a Telegram chat)           │
│         ▼                                                                 │
│  + source enrichment (Brave) + RU/EN version comparison                  │
│  + auto cover image (Unsplash / ComfyUI / OpenAI-compatible)             │
│         │                                                                 │
│         ▼                                                                 │
│  manual moderation via DM (✅/❌/✏️) OR scheduled auto-posting             │
│         │                                                                 │
│         ▼                                                                 │
│  publish to N groups → collect stats → auto-digest / native ads /         │
│  smart scheduling / growth tracker / join attribution                    │
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

┌───────────────────────────────── Engage ───────────────────────────────────┐
│                                                                             │
│  Post published → LLM writes a quiz about it → published as a native       │
│                   Telegram quiz-poll after a reading delay → points,       │
│                   streaks, levels, leaderboard                             │
│                                                                             │
│  Personal invite link → invitee joins + writes + survives N days →         │
│                          only then the referral counts (anti-fraud)        │
│                                                                             │
│  Contest → seed published up front → verifiable draw → protocol posted     │
│  Keyword triggers → auto-replies · DM onboarding · reader submissions      │
└─────────────────────────────────────────────────────────────────────────┘
```

All three processes live in one repository but are **independent bots** —
their own tokens, their own restart cycles. The repost bot and Engage share
one database (`tg_repost.db`) because quizzes are derived from posts and
referrals resolve against the same members; Guardian keeps its own
(`guardian.db`) with a separate Alembic chain. One crashing or being
redeployed doesn't touch the others, and all three are managed from a single
web panel.

---

## The editorial desk — two AI agents (draft + fact-check)

Most "AI rewrite" tools are synonym shufflers: one model call, one output,
nobody checks it. This one runs an actual editorial process, because the
failure mode that matters isn't clumsy phrasing — it's **confidently
publishing something false**.

```
① journalist  → writes the draft (a copywriter persona with 20 years of experience,
                 one of 5 style profiles)
② editor      → fact-checks the draft against the ORIGINAL source text,
                 returns a verdict (OK / NEEDS WORK) plus a list of claims
                 it could not confirm
③ web check   → those specific claims are searched on the open web
④ journalist  → rewrites, addressing each note
```

- **The editor is not the same voice as the journalist.** It runs on its own
  prompt at temperature 0.2 — deterministic on purpose. A creative
  fact-checker is a contradiction.
- **It writes notes like a human editor would**: *"this is wrong, check
  against this link"* — attached to the specific claim, not a vague score.
- **Configurable rounds** (`editorial_max_rounds`) — one round is the
  default. Each round costs LLM calls, so this is one of the two most
  expensive knobs in the system (the other is variant count).
- **The notes are saved** on the post variant and shown in the moderation UI,
  so you can see *why* the final text differs from the draft.
- **Costs are visible, not hidden**: minimum config is 1 LLM call per post,
  typical (editorial on) is 3, everything enabled is ~10. Multiply by
  variants × languages before you turn it all on.

### Watch the argument live

Both agents can stream their exchange to a Telegram chat of your choosing —
you see the draft, the editor's objections, the web-verification result, and
the final text, as it happens. Three verbosity modes:

| Mode | What lands in the chat |
|---|---|
| `all` | Every step — full transparency, noisy |
| `problems` | Only threads where the editor actually objected |
| `summary` | One line per post: verdict and round count |

Messages are threaded per post and sent silently (`disable_notification`), so
the newsroom never buzzes your phone at 3am.

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
- **Join attribution — which ad actually paid off.** Every invite link can
  carry a label and a cost. Telegram tells you which link each member came
  through, so the panel shows joins, leaves, 7/30-day retention and **cost
  per member who is still here** — not cost per click. An ad that brings 100
  people who all leave in a week is correctly reported as a failure.
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
- **Unified proxy support (MTProto / SOCKS5 / HTTP)** — one section, enable a
  type and tick what to route through it (Telegram, rewrite AI, image AI);
  see [Proxies](#proxies-mtproto--socks5--http) below — **and read the Wiki's Proxy Guide before
  you configure this — there's an important limitation.**

---

## Guardian — AI group moderator (CAPTCHA, spam filter, anti-raid)

A separate bot on `aiogram`. Its job isn't to review content — it's to
**protect the real people in your group** from spam, bots, and toxicity
while your audience grows.

### New-member verification
- Muted immediately on join → CAPTCHA (math / "I'm not a robot" button /
  channel-topic question) → restrictions lifted on a correct answer.
- No answer within N minutes → auto-kick.
- The "who answered first" race and "who is actually the new member vs. who
  invited them" confusion are both resolved by explicit `user_id` addressing
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
- **Service-message hygiene** — auto-deletes the "X joined the group" /
  "Y pinned a message" clutter, keeps a night mode that silences the bot's
  own replies during quiet hours, and posts a periodic rules reminder.
- **Keyword auto-replies** — rule-based answers to recurring questions
  ("when's the stream?", "where are the rules?"), matched on word
  boundaries so "cat" never fires on "category", with a per-rule cooldown
  so the bot can't be turned into a flood machine.
- **Log channel** — every moderation action, manual or automatic, is
  written to a private channel with inline buttons for a quick admin
  response.
- **SOCKS5/HTTP proxy support for the Bot API** — see [Proxies](#proxies-mtproto--socks5--http) below.
- **21 admin commands** — `/warn /mute /unmute /ban /unban /kick /check
  /addword /delword /listwords /trust /untrust /addomain /deldomain
  /listdomains /setmode /setcaptcha /setwarn /setmutime /mode /stats
  /growth` — the entire config changes on the fly, no bot restart needed.

---

## Engage — turning readers into participants (quizzes, referrals, contests)

The third bot, also on `aiogram`. Guardian keeps bad actors *out*; Engage
gives the good ones a reason to *stay*. Every mechanic here was built around
one rule: **rewards must be hard to farm**, or the leaderboard becomes a
list of whoever ran the most fake accounts.

### Quizzes generated from your own posts

After a post is published, the LLM writes a multiple-choice question about
it. The question goes out as a **native Telegram quiz-poll** after a reading
delay — Telegram checks the answer itself, shows the correct option with an
explanation, and won't let anyone re-vote.

- **No LLM call to grade answers**, and no arguing about "that's what I
  meant" — the platform is the referee.
- The question is built from **already fact-checked material** (the article
  text was extracted, the editor verified it), so the quiz can't invent
  something the post never said.
- Points: **10** per correct answer, plus a daily-streak bonus of **5**
  (capped at **25**) — streaks count by *calendar date*, so you can't farm
  them by answering twice in one evening.
- `/me` shows your points, accuracy and streak; `/top` shows the leaderboard.

### Referral programme with real anti-fraud

Each member gets a personal invite link (`/invite`). The referral counts only
when the invited person has **joined, written at least one message, and
stayed N days**.

- **Self-referral is rejected**, and once someone is credited to an inviter,
  nobody can steal them — first inviter wins, so there's no "poach the
  referral" race.
- The "wrote a message" condition is the one that matters: throwaway accounts
  will join for a reward, but they won't talk.
- **50 points** per confirmed referral — deliberately worth more than a quiz
  answer, because bringing a live human is worth more than answering one
  question.

### Contests you can prove weren't rigged

The problem with channel giveaways is that nobody can verify the winner
wasn't the owner's friend. So the draw is **reproducible**:

1. A random seed is generated **when the contest is created** — before a
   single participant exists — and published up front.
2. Participants are sorted by user ID (a stable order nobody controls).
3. The winners are drawn from that seed, and a protocol with the seed,
   the algorithm and the full participant list is posted afterwards.

Anyone can re-run the draw and get the same winners. The unpredictability
comes from the seed being generated with `secrets`; the *draw itself* is
deliberately deterministic, because a cryptographically random draw would be
unverifiable — which defeats the entire point.

### Plus the small stuff that keeps a group alive

- **DM onboarding** — a new member gets a private welcome walking them
  through the rules and what the channel is for, instead of a wall-of-text
  pinned post nobody reads.
- **Reader submissions (UGC)** — `/suggest` lets members send you posts;
  they land in the same moderation queue as everything else, with `/cancel`
  to back out mid-submission.
- Everything is **off by default** (`QUIZ_ENABLED`, `REFERRALS_ENABLED`,
  `CONTESTS_ENABLED`, `SUGGESTIONS_ENABLED`, `ONBOARDING_ENABLED`) — turn on
  only the mechanics you actually want.

---

## Web admin panel

A single FastAPI panel for all three bots, embedded in the same process as
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

## Proxies (MTProto / SOCKS5 / HTTP)

One unified proxy section on `/settings` → **Proxy**. You enable one or more
**types**, fill in each one's address (and optional credentials), then tick
what to route through it. There are three types and three usage toggles:

- **Types:** **MTProto** (Telegram-specific fake-TLS proxy, Telethon only,
  uses a *secret* instead of login/password), **SOCKS5**, and **HTTP(S)**
  (both plain tunnels — usable for Telethon, the Bot API, and the AI calls).
- **Usage toggles:** *Telegram* (Telethon reading + every bot's Bot API),
  *rewrite AI*, *image AI*.

| Setting | Secret? | Notes |
|---|---|---|
| Address (`host:port`), login | plain, editable on `/settings` | never hidden — useless without the password/secret anyway |
| Password / MTProto secret | write-only secret | masked; **one-click "show"** reveals it (you're already logged in) |
| Usage toggles | plain checkboxes | pick per-traffic: Telegram / rewrite AI / image AI |

Precedence when several types are enabled: for **Telegram**, SOCKS5 → HTTP →
MTProto; for **AI traffic**, HTTP → SOCKS5 (MTProto is Telegram-only). Leave
every type disabled for a direct connection (the default).

Guardian's Bot API proxy is **separate** (`.env` only,
`GUARDIAN_BOT_API_PROXY_URL`) — Guardian is a different process built once at
start, so changing it needs `docker compose restart guardian`.

> ⚠️ **Read this before setting up an MTProto proxy.** Telethon's built-in
> MTProto proxy support does **not** implement fake-TLS mode (secrets
> starting with `ee`) — a known limitation of the library itself, not
> something this project can patch around. Most modern public MTProto proxies
> default to fake-TLS. If your proxy secret starts with `ee`, Telethon will
> hang or fail with a garbled decryption error. **The simplest fix is to use a
> SOCKS5 or HTTP(S) proxy instead** — plain tunnels have no fake-TLS
> limitation. Alternatively, get a classic (plain hex / `dd`-prefixed) secret
> from the same proxy. **Full details, real error messages, and a decision
> tree in the [Wiki's Proxy Guide](../../wiki/Proxy-Guide).**

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
| Telethon login hangs or fails with a garbled error | MTProto proxy in fake-TLS mode — unsupported, see [Proxies](#proxies-mtproto--socks5--http) above | Read the [Wiki's Proxy Guide](../../wiki/Proxy-Guide) |

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

**Engage** (any member, in the group or in DM):
```
/me        — your points, accuracy and current streak
/top       — leaderboard
/invite    — your personal referral link
/suggest   — send the channel a post idea  (/cancel to abort)
```

---

## Tests and code quality

```bash
pytest                                            # 1253 tests
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
  webui/                 # web admin panel for all three bots (FastAPI + Jinja2)
  telegram/               # Telethon listener, publisher, moderation bot, newsroom
  rewriter/                # LLM client: editorial desk, styles, quizzes, embeddings
  dedup/                    # hash + semantic dedup check
  enrichment/                # Brave Search enrichment + article extraction
  covers/                     # Unsplash / ComfyUI / OpenAI-compatible covers
  ads/                         # native advertising
  scheduler/                    # APScheduler jobs: posting, stats, digest, growth
  db/                            # ORM + Alembic migrations (27)
  tools/                          # gen_session, check_telethon, backup

guardian/                # AI group moderator (separate bot, own database)
  handlers/                # join (CAPTCHA), messages, admin, hygiene, autoreply
  filters/                   # keyword / ai / heuristics / link / flood
  services/                   # warn_system, captcha, raid_detector, profile_analyzer
  db/                           # own ORM + Alembic chain

engage/                  # audience engagement bot (shares tg_repost's database)
  handlers/                # quiz, referral, contest, suggest, start (deep links)

tests/                   # 1253 tests — pytest + pytest-asyncio
.github/workflows/       # CI: ruff, mypy, pytest, bandit, pip-audit
```

Engage deliberately has **no database of its own**: quizzes are derived from
posts, referral links are the same invite links the repost bot creates, and
referred members land in the same attribution table. A separate database
would mean syncing all three across process boundaries.

---

## Implementation status

**46 of 50 planned features are implemented.** The remaining 4 are deferred
on purpose, not unfinished — see the bottom of this section.

- ✅ **Repost bot** — collection, rewriting, dedup, moderation, publishing,
  stats, style profiles, source enrichment, article extraction, auto covers,
  smart scheduling, digest, native ads, growth tracker, session rotation,
  join attribution, web admin panel (full CRUD + audit log + live logs),
  Docker packaging.
- ✅ **Editorial desk (two agents)** — journalist → editor fact-check → web
  verification of disputed claims → revision, with notes saved per variant
  and the whole exchange optionally streamed to a Telegram chat.
- ✅ **Guardian** — CAPTCHA, welcome, three spam-filter modes, warns,
  anti-flood, anti-raid, profile analysis, quiet hours, auto-trust, service
  hygiene, keyword auto-replies, stats, per-group configuration.
- ✅ **Engage** — quizzes from published posts, points/streaks/leaderboard,
  referrals with anti-fraud, verifiable contest draws, DM onboarding, reader
  submissions.
- ✅ **CI/CD** — GitHub Actions on every push/PR, fully clean
  mypy/ruff/bandit/pip-audit across all three packages.
- ✅ **Auto-backup** — `.env` + both databases + logs in one script.
- ✅ **Unified proxy support (MTProto / SOCKS5 / HTTP)** — one section, per-type
  enable + per-traffic usage toggles (Telegram / rewrite AI / image AI),
  configured on `/settings` (see [Proxies](#proxies-mtproto--socks5--http) — and read the fake-TLS
  caveat).
- ✅ **Production deployment proven** — an LXC on Proxmox (Docker inside an
  unprivileged container with nesting enabled), a full `docker compose up`
  run end to end.
- ⬜ **Real production tokens** — purely an operational step: create the
  Guardian and Engage bots with @BotFather, add them to `/settings`, and add
  Guardian to the group as an administrator. Until then those two processes
  won't start (by design — they refuse rather than run half-configured).
- 💭 **Deferred by choice** — multi-tenant SaaS (a separate product, not a
  feature); cross-posting to VK/Instagram (out of scope); paid access via
  Telegram Stars (recorded as an idea, needs a payment flow); role-based
  admin accounts for the panel (skipped — there is one user).

---

## Support the project

This project is written and maintained in spare time, with no grant and no
company behind it — three bots, 1253 tests and 50 documented features, built
nights and weekends. If it's been useful to you, a coffee helps keep the
feature work going:

**Bitcoin (BTC)** — native SegWit (bech32), Bitcoin mainnet only:

```
bc1qwnkyez3nv86dry54dqfjjtav29qqq72h69pevw
```

[**Open this address on mempool.space →**](https://mempool.space/address/bc1qwnkyez3nv86dry54dqfjjtav29qqq72h69pevw)
— check it against the block explorer before sending anything. Never trust an
address pasted into a chat, including by me.

**⭐ Starring the repo costs nothing but helps other people find it** — and
telling me what you built with it is worth more than the coffee.

---

<div align="center">

*Keywords: telegram bot · telegram repost bot · telegram auto-posting ·
telegram channel automation · rewrite bot AI · openai rewriter · AI
fact-checking · multi-agent LLM pipeline · content repost automation ·
telegram moderation bot · anti-spam telegram bot · telegram chat moderator ·
captcha verification bot · anti-raid telegram · telegram gamification bot ·
telegram quiz bot · telegram referral bot · telegram giveaway bot ·
telethon userbot · aiogram bot · python telegram automation · self-hosted
telegram bot · fastapi admin panel · telegram channel growth · AI content
pipeline*

</div>
