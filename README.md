# startup-hunter

Ежедневный публичный дайджест зарубежных бизнес-сигналов с разбором применимости
в России: https://herclogon.github.io/startup-hunter/latest/

## Как устроено

- Облачный агент Claude по расписанию (05:00 МСК) выполняет [PROMPT.md](PROMPT.md):
  ищет сигналы по фокусу дня, сверяется с архивом, пишет `digests/YYYY-MM-DD.md`,
  дописывает `data/signals.jsonl`, проверяет выпуск и делает push.
- GitHub Actions на каждый push проверяет изменённые выпуски, собирает сайт и
  публикует его на GitHub Pages.

| Путь | Что это |
|---|---|
| `PROMPT.md` | инструкция агента: профиль, ротация источников, правила фактов, формат |
| `digests/` | выпуски в markdown |
| `data/signals.jsonl` | архив сигналов с цитатами, по нему отсеиваются повторы |
| `scripts/verify.py` | проверка ссылок и цитат в выпуске |
| `scripts/build.py` | сборка сайта в `_site/` |
| `content/about.md` | страница «О проекте» |
| `docs/original-brief.md` | исходное ТЗ, из которого вырос проект |

## Локально

```bash
pip install -r requirements.txt
python3 scripts/verify.py digests/2026-10-12.md
python3 scripts/build.py && python3 -m http.server -d _site
```
