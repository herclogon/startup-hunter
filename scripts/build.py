#!/usr/bin/env python3
"""Сборка статического сайта из digests/*.md в _site/.

Страницы: / (список выпусков), /latest/ (последний выпуск, постоянная ссылка),
/YYYY-MM-DD/ (каждый выпуск), /about/, /feed.xml (RSS).
Использование: python3 scripts/build.py [--out _site]
"""

import argparse
import html
import os
import re
import shutil
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SITE_URL = os.environ.get("SITE_URL", "https://herclogon.github.io/startup-hunter/").rstrip("/") + "/"
SITE_TITLE = "Радар возможностей"
FEED_SIZE = 30

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1c1a;--muted:#6b675f;--line:#e4e0d7;--accent:#1f5fbf;
--quote:#f1eee6;--warn-bg:#fff2d6;--warn-fg:#7a4b00;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151514;--fg:#e9e6df;
--muted:#9b968c;--line:#2e2d2a;--accent:#7fb0ff;--quote:#1f1e1c;--warn-bg:#3a2c0f;--warn-fg:#ffd27a;}}
:root[data-theme="dark"]{--bg:#151514;--fg:#e9e6df;--muted:#9b968c;--line:#2e2d2a;--accent:#7fb0ff;
--quote:#1f1e1c;--warn-bg:#3a2c0f;--warn-fg:#ffd27a;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main,header,footer{max-width:44rem;margin:0 auto;padding:0 16px}
header{display:flex;gap:1.2rem;align-items:baseline;flex-wrap:wrap;padding-top:1.2rem;padding-bottom:.6rem;border-bottom:1px solid var(--line)}
header .brand{font-weight:700;color:var(--fg);text-decoration:none;margin-right:auto}
header a{color:var(--muted);text-decoration:none}header a:hover{color:var(--accent)}
a{color:var(--accent);overflow-wrap:anywhere}
h1{font-size:1.6rem;line-height:1.25;margin:1.6rem 0 .4rem}
h2{font-size:1.25rem;margin:2.4rem 0 .6rem;padding-bottom:.3rem;border-bottom:1px solid var(--line)}
h3{font-size:1.08rem;margin:2rem 0 .3rem;line-height:1.35}
h3+p{color:var(--muted);font-size:.88rem;margin-top:0}
blockquote{margin:.6rem 0;padding:.5rem .9rem;background:var(--quote);border-left:3px solid var(--line);font-size:.93rem}
blockquote p{margin:0}
ul{padding-left:1.2rem}
table{border-collapse:collapse;display:block;overflow-x:auto}td,th{border:1px solid var(--line);padding:.3rem .6rem}
.stale{background:var(--warn-bg);color:var(--warn-fg);padding:.6rem .9rem;border-radius:6px;margin-top:1rem;display:none}
.issues{list-style:none;padding:0}.issues li{padding:.45rem 0;border-bottom:1px solid var(--line)}
.issues .meta{color:var(--muted);font-size:.88rem}
.pager{display:flex;justify-content:space-between;margin:3rem 0 1rem;gap:1rem}
footer{color:var(--muted);font-size:.85rem;padding-top:1rem;padding-bottom:2rem;border-top:1px solid var(--line);margin-top:3rem}
"""

# Выпуск готовится в 05:00 МСК (02:00 UTC); старше 36 часов после этого — устарел.
STALE_JS = """
<script>
(function(){var m=document.querySelector('main[data-date]');if(!m)return;
var t=Date.parse(m.dataset.date+'T02:00:00Z');if(Date.now()-t>36*3600e3){
var b=document.getElementById('stale');b.style.display='block';}})();
</script>
"""


def page(title: str, body: str, depth: int, date: str = "", extra_head: str = "") -> str:
    up = "../" * depth or "./"
    stale = ""
    if date:
        stale = (
            f'<div id="stale" class="stale">Выпуск от {date} устарел: новый не вышел. '
            f'Возможно, генерация сломалась.</div>'
        )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="alternate" type="application/rss+xml" title="{SITE_TITLE}" href="{up}feed.xml">
{extra_head}<style>{CSS}</style></head>
<body>
<header><a class="brand" href="{up}">{SITE_TITLE}</a>
<a href="{up}latest/">Последний</a><a href="{up}about/">О проекте</a><a href="{up}feed.xml">RSS</a></header>
<main{f' data-date="{date}"' if date else ''}>{stale}
{body}
</main>
<footer>Сигналы собирает и проверяет AI-агент. Цифры подкреплены цитатами из источников;
«Оценка» и «Почему интересно» — мнение модели, не факт.</footer>
{STALE_JS if date else ''}</body></html>
"""


def render(md_text: str) -> str:
    # Python-Markdown строже GitHub: нужен пустой абзац перед списком
    # и отступ в 4 пробела у вложенных блоков. Приводим вывод агента к этому.
    lines = []
    for line in md_text.splitlines():
        if re.match(r" {2,3}\S", line):
            line = "    " + line.lstrip()
        prev = lines[-1] if lines else ""
        is_item = re.match(r"\s*([-*]|\d+\.)\s", line)
        if is_item and prev.strip() and not re.match(r"\s*([-*]|\d+\.)\s", prev):
            lines.append("")
        elif re.match(r"\s+>", line) and prev.strip() and not prev.lstrip().startswith(">"):
            lines.append("")
        lines.append(line)
    return markdown.markdown("\n".join(lines), extensions=["extra", "sane_lists"])


def first_h1(md_text: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", md_text, re.M)
    return m.group(1).strip() if m else fallback


def count_signals(md_text: str) -> int:
    m = re.search(r"^## Новые сигналы\s*$(.*?)(?=^## |\Z)", md_text, re.M | re.S)
    return len(re.findall(r"^### ", m.group(1), re.M)) if m else 0


def plural(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} сигнал"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} сигнала"
    return f"{n} сигналов"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "_site"))
    out = Path(ap.parse_args().out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / ".nojekyll").write_text("")

    issues = []
    for p in sorted((ROOT / "digests").glob("*.md"), reverse=True):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem):
            continue
        text = p.read_text(encoding="utf-8")
        issues.append({"date": p.stem, "md": text, "title": first_h1(text, p.stem), "html": render(text)})

    for i, it in enumerate(issues):
        newer = issues[i - 1]["date"] if i > 0 else None
        older = issues[i + 1]["date"] if i + 1 < len(issues) else None
        pager = '<nav class="pager">'
        pager += f'<a href="../{older}/">← {older}</a>' if older else "<span></span>"
        pager += f'<a href="../{newer}/">{newer} →</a>' if newer else "<span></span>"
        pager += "</nav>"
        d = out / it["date"]
        d.mkdir()
        (d / "index.html").write_text(page(it["title"], it["html"] + pager, 1), encoding="utf-8")

    latest = out / "latest"
    latest.mkdir()
    if issues:
        it = issues[0]
        canon = f'<link rel="canonical" href="{SITE_URL}{it["date"]}/">\n'
        body = it["html"] + f'<nav class="pager"><span></span><a href="../{it["date"]}/">Постоянная ссылка на выпуск</a></nav>'
        (latest / "index.html").write_text(page(it["title"], body, 1, it["date"], canon), encoding="utf-8")
    else:
        (latest / "index.html").write_text(page(SITE_TITLE, "<p>Выпусков пока нет.</p>", 1), encoding="utf-8")

    rows = "".join(
        f'<li><a href="{it["date"]}/">{html.escape(it["title"])}</a> '
        f'<span class="meta">· {plural(count_signals(it["md"]))}</span></li>'
        for it in issues
    )
    intro = (
        "<h1>Радар возможностей</h1><p>Ежедневная подборка свежих зарубежных бизнес-сигналов "
        "с коротким разбором применимости в России. "
        '<a href="about/">Как это устроено</a>.</p>'
    )
    (out / "index.html").write_text(
        page(SITE_TITLE, intro + f'<ul class="issues">{rows or "<li>Выпусков пока нет.</li>"}</ul>', 0),
        encoding="utf-8",
    )

    about_md = (ROOT / "content" / "about.md").read_text(encoding="utf-8")
    (out / "about").mkdir()
    (out / "about" / "index.html").write_text(
        page(f"О проекте — {SITE_TITLE}", render(about_md), 1), encoding="utf-8"
    )

    items = []
    for it in issues[:FEED_SIZE]:
        dt = datetime.fromisoformat(it["date"]).replace(hour=2, tzinfo=timezone.utc)
        link = f"{SITE_URL}{it['date']}/"
        items.append(
            f"<item><title>{html.escape(it['title'])}</title><link>{link}</link>"
            f"<guid>{link}</guid><pubDate>{format_datetime(dt)}</pubDate>"
            f"<description>{html.escape(it['html'])}</description></item>"
        )
    (out / "feed.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<rss version="2.0"><channel>'
        f"<title>{SITE_TITLE}</title><link>{SITE_URL}</link>"
        "<description>Ежедневные зарубежные бизнес-сигналы с разбором применимости в России</description>"
        f"<language>ru</language>{''.join(items)}</channel></rss>\n",
        encoding="utf-8",
    )
    print(f"Собрано {len(issues)} выпусков → {out}")


if __name__ == "__main__":
    main()
