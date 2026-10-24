#!/usr/bin/env python3
"""Проверка выпуска перед публикацией.

Для каждого переданного digests/YYYY-MM-DD.md:
  - записи архива data/signals.jsonl за эту дату валидны;
  - каждая цитата из выпуска есть в архиве;
  - каждая цитата из архива дословно встречается на своей странице;
  - каждая ссылка в выпуске открывается (HTTP < 400).

Выход 1 и список проблем по карточкам, если что-то не прошло. Сетевой сбой
(таймаут, обрыв) после повторов — только предупреждение «!»: он не доказывает,
что ссылка мёртвая. Несуществующий домен, HTTP 4xx/5xx и цитата, которой нет на
загруженной странице, — провал.

С --soft-network ответы сайтов (HTTP 4xx/5xx, нет домена, нет цитаты на странице) —
тоже предупреждения. Так запускает CI: антибот-защита (Cloudflare, Akamai) режет
IP раннеров GitHub ложными 403/404, а ссылки уже проверил агент перед push.
Использование: python3 scripts/verify.py [--soft-network] digests/2026-10-12.md [...]
"""

import html
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "data" / "signals.jsonl"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
REQUIRED = [
    "id", "digest_date", "section", "event_date", "title", "company", "country",
    "industry", "kind", "customer", "problem", "model", "pain", "rf_verdict",
    "sources", "quotes",
]
LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
QUOTE_RE = re.compile(r"^\s*>\s*«(.+?)»", re.M)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_cache: dict[str, tuple[int, str]] = {}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(text))
    text = text.replace("­", "")
    for chars, repl in (("‘’‚‛`´", "'"), ("“”„‟«»″", '"'), ("‐‑‒–—―−", "-")):
        text = re.sub(f"[{re.escape(chars)}]", repl, text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _get(url: str, timeout: int) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en,ru;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read(8_000_000)
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001
        # Несуществующий домен — провал (-1); таймаут или обрыв — сбой сети (0).
        dead = re.search(r"Name or service not known|nodename nor servname|getaddrinfo failed|No address associated", str(e))
        return (-1 if dead else 0), str(e)
    if "pdf" in ctype:
        return status, ""
    body = raw.decode("utf-8", "replace")
    # Текст внутри <script> тоже оставляем: многие сайты кладут контент в JSON.
    body = body.replace("\\u2019", "'").replace("\\u201c", '"').replace("\\u201d", '"')
    body = body.replace('\\"', '"').replace("\\n", " ")
    return status, norm(re.sub(r"<[^>]+>", " ", body))


def _github_fallback(url: str) -> tuple[int, str] | None:
    """github.com и его API отдают 403 облачным IP: репозиторий и текст проверяем по README."""
    m = re.match(r"https://github\.com/([\w.-]+)/([\w.-]+)/?$", url)
    if not m:
        return None
    owner, repo = m.groups()
    status, readme = _get(f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md", 25)
    if status != 200:
        return None
    # Markdown-выделение (**…**, `…`) на странице GitHub не видно — убираем и тут.
    return 200, re.sub(r"\s+", " ", re.sub(r"[*_`]", "", readme))


def _ted_fallback(url: str) -> tuple[int, str] | None:
    """Страницы извещений TED отдают роботам 202 без текста: берём поля через API."""
    m = re.search(r"ted\.europa\.eu/.*?(\d{1,6}-\d{4})", url)
    if not m:
        return None
    body = json.dumps({
        "query": f"publication-number={m.group(1)}",
        "fields": ["publication-number", "notice-title", "buyer-name", "buyer-country",
                   "publication-date", "total-value", "total-value-cur", "description-lot",
                   "deadline-receipt-tender-date-lot", "notice-type"],
        "limit": 1,
    }).encode()
    req = urllib.request.Request(
        "https://api.ted.europa.eu/v3/notices/search", data=body,
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            notices = json.loads(resp.read()).get("notices", [])
    except Exception:  # noqa: BLE001
        return None
    if not notices:
        return None

    def flat(v):
        if isinstance(v, dict):
            return " ".join(flat(x) for x in v.values())
        if isinstance(v, list):
            return " ".join(flat(x) for x in v)
        return str(v)

    n = notices[0]
    n.pop("links", None)
    return 200, norm(flat(n))


def fetch(url: str) -> tuple[int, str]:
    """(статус, нормализованный текст страницы); статус 0 — сетевая ошибка."""
    if url in _cache:
        return _cache[url]
    result = _get(url, 25)
    for timeout in (45, 60):
        # Российские сайты из зарубежного облака отвечают нестабильно — повторяем.
        if result[0] != 0 and result[0] not in (429, 502, 503, 504):
            break
        result = _get(url, timeout)
    if result[0] in (403, 429):
        result = _github_fallback(url) or result
    if "ted.europa.eu" in url:
        # Текст извещения на странице рисуется скриптом, поэтому всегда добавляем поля из API.
        api = _ted_fallback(url)
        if api:
            result = (200, api[1] + " " + result[1])
    _cache[url] = result
    return result


def card_of(text: str, pos: int) -> str:
    """Заголовок карточки (### ...), в которой находится позиция pos."""
    head = text.rfind("\n### ", 0, pos)
    if head < 0:
        return "(вне карточек)"
    return text[head + 5 : text.find("\n", head + 5)].strip()


def verify(path: Path, archive: list[dict], soft: bool = False) -> tuple[list[str], list[str]]:
    """(проблемы — сигнал удаляется, предупреждения — сбой сети, проверить не удалось)."""
    problems, warnings = [], []
    date = path.stem
    text = path.read_text(encoding="utf-8")
    records = [r for r in archive if r.get("digest_date") == date]

    for r in records:
        missing = [k for k in REQUIRED if k not in r]
        if missing:
            problems.append(f"архив {r.get('id')}: нет полей {', '.join(missing)}")
        for k in ("event_date", "digest_date"):
            if k in r and not DATE_RE.match(str(r[k])):
                problems.append(f"архив {r.get('id')}: {k} не в формате YYYY-MM-DD")

    archived = {norm(q["text"]) for r in records for q in r.get("quotes", [])}
    for m in QUOTE_RE.finditer(text):
        if norm(m.group(1)) not in archived:
            problems.append(f"{card_of(text, m.start())}: цитата не записана в архив: «{m.group(1)[:60]}…»")

    quotes = [(r["id"], q) for r in records for q in r.get("quotes", [])]
    links = {m.group(1): m.start() for m in LINK_RE.finditer(text)}
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(fetch, set(links) | {q["url"] for _, q in quotes}))

    remote = warnings if soft else problems
    for rid, q in quotes:
        status, page = fetch(q["url"])
        if status == 0:
            warnings.append(f"архив {rid}: сбой сети, цитату проверить не удалось: {q['url']}")
        elif status < 0 or status >= 400:
            remote.append(f"архив {rid}: страница недоступна (HTTP {status}): {q['url']}")
        elif norm(q["text"]) not in page:
            remote.append(f"архив {rid}: цитата не найдена на странице: {q['url']}")

    for url, pos in links.items():
        status, _ = fetch(url)
        if status == 0:
            warnings.append(f"{card_of(text, pos)}: сбой сети, ссылку проверить не удалось: {url}")
        elif status < 0 or status >= 400:
            remote.append(f"{card_of(text, pos)}: ссылка не открывается (HTTP {status}): {url}")
    return problems, warnings


def main() -> int:
    args = sys.argv[1:]
    soft = "--soft-network" in args
    paths = [Path(p) for p in args if p != "--soft-network"]
    if not paths:
        print(__doc__)
        return 2
    archive = []
    for n, line in enumerate(ARCHIVE.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                archive.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"data/signals.jsonl:{n}: невалидный JSON: {e}")
                return 1
    ids = [r.get("id") for r in archive]
    dupes = {i for i in ids if ids.count(i) > 1}

    failed = bool(dupes)
    if dupes:
        print(f"архив: повторяющиеся id: {', '.join(sorted(dupes))}")
    for path in paths:
        problems, warnings = verify(path, archive, soft)
        if problems:
            failed = True
            print(f"✗ {path}")
            for p in problems:
                print(f"  - {p}")
        else:
            print(f"✓ {path}")
        for w in warnings:
            print(f"  ! {w}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
