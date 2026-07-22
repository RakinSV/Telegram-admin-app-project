"""Готовые наборы RSS-лент, добавляемые в источники одной кнопкой.

Каждый адрес ПРОВЕРЕН запросом на момент добавления: отвечает 200 и парсится
как RSS/Atom с непустым списком записей. Ленты, которые отдавали 403/404 или
пустоту (CISA, NVD, GitHub Advisories, openSUSE), в набор не включены — лучше
короткий рабочий список, чем длинный с мёртвыми адресами, потому что мёртвая
лента молча не приносит ничего и заметить это трудно.

Наборы — только стартовая точка: любую ленту можно добавить руками на
странице «Источники», и любую из этих удалить.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeedPreset:
    title: str
    url: str


# Уязвимости, эксплойты, бюллетени вендоров — «сырьё», а не публицистика.
SECURITY_VULNERABILITIES: tuple[FeedPreset, ...] = (
    FeedPreset("Zero Day Initiative — уязвимости", "https://www.zerodayinitiative.com/rss/published/"),
    FeedPreset("Exploit-DB — новые эксплойты", "https://www.exploit-db.com/rss.xml"),
    FeedPreset("CERT/CC — бюллетени", "https://www.kb.cert.org/vulfeed/"),
    FeedPreset("Microsoft MSRC — Update Guide", "https://api.msrc.microsoft.com/update-guide/rss"),
    FeedPreset("Ubuntu Security Notices", "https://ubuntu.com/security/notices/rss.xml"),
    FeedPreset("Debian Security Advisories", "https://www.debian.org/security/dsa"),
    FeedPreset("Red Hat — безопасность", "https://www.redhat.com/en/rss/blog/channel/security"),
    FeedPreset("SANS Internet Storm Center", "https://isc.sans.edu/rssfeed.xml"),
    FeedPreset("Google Project Zero", "https://googleprojectzero.blogspot.com/feeds/posts/default"),
    FeedPreset("Tenable — исследования", "https://www.tenable.com/security/research/feed"),
    FeedPreset("Qualys — блог", "https://blog.qualys.com/feed"),
    FeedPreset("Rapid7 — блог", "https://blog.rapid7.com/rss/"),
)

# Новости и разбор инцидентов на английском.
SECURITY_NEWS_EN: tuple[FeedPreset, ...] = (
    FeedPreset("The Hacker News", "https://feeds.feedburner.com/TheHackersNews"),
    FeedPreset("BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
    FeedPreset("Krebs on Security", "https://krebsonsecurity.com/feed/"),
    FeedPreset("SecurityWeek", "https://www.securityweek.com/feed/"),
    FeedPreset("Dark Reading", "https://www.darkreading.com/rss.xml"),
    FeedPreset("Schneier on Security", "https://www.schneier.com/feed/"),
    FeedPreset("Cisco Talos", "https://blog.talosintelligence.com/rss/"),
    FeedPreset("Palo Alto Unit 42", "https://unit42.paloaltonetworks.com/feed/"),
    FeedPreset("Malwarebytes Labs", "https://www.malwarebytes.com/blog/feed/index.xml"),
    FeedPreset("WeLiveSecurity (ESET)", "https://www.welivesecurity.com/en/rss/feed/"),
    FeedPreset("Have I Been Pwned — утечки", "https://feeds.feedburner.com/HaveIBeenPwnedLatestBreaches"),
)

# Русскоязычные источники.
SECURITY_NEWS_RU: tuple[FeedPreset, ...] = (
    FeedPreset("Хабр — Информационная безопасность", "https://habr.com/ru/rss/hub/infosecurity/?fl=ru"),
    FeedPreset("SecurityLab", "https://www.securitylab.ru/_services/export/rss/news/"),
    FeedPreset("Kaspersky Securelist", "https://securelist.ru/feed/"),
    FeedPreset("Anti-Malware", "https://www.anti-malware.ru/rss.xml"),
    FeedPreset("Xakep", "https://xakep.ru/feed/"),
)

PRESET_GROUPS: dict[str, tuple[FeedPreset, ...]] = {
    "security_vulns": SECURITY_VULNERABILITIES,
    "security_news_en": SECURITY_NEWS_EN,
    "security_news_ru": SECURITY_NEWS_RU,
}


def all_presets() -> tuple[FeedPreset, ...]:
    return tuple(feed for group in PRESET_GROUPS.values() for feed in group)
