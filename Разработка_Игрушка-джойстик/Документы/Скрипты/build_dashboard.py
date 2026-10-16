"""Пульт конвейера новостей — одна HTML-страница со сводкой по всем новостям.

Читает справки (Документы/Новости), посты (Результат/Посты), реестр кандидатов,
страницу сайта (Результат/Сайт/news.html) и журналы скриптов и собирает
Результат/Пульт-конвейера.html. Ничего, кроме этой страницы, не меняет.

Запуск:
    python build_dashboard.py            собрать пульт
    python build_dashboard.py --open     собрать и открыть в браузере
"""

import csv
import datetime as dt
import html
import json
import re
import sys
import webbrowser
from pathlib import Path

from post_check import LIMITS, full_text

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT = SCRIPT_DIR.parent.parent
NEWS_DIR = PROJECT / "Документы" / "Новости"
POSTS_DIR = PROJECT / "Результат" / "Посты"
SITE_HTML = PROJECT / "Результат" / "Сайт" / "news.html"
REGISTRY = NEWS_DIR / "ИИ-игрушки_кандидаты_реестр.md"
OUT = PROJECT / "Результат" / "Пульт-конвейера.html"
LOGS = {"Картинки": SCRIPT_DIR / "журнал_картинок.csv", "Выкладка на хостинг": SCRIPT_DIR / "журнал_выкладки.csv"}
PLATFORMS = {"telegram": "Telegram", "max": "MAX", "vk": "ВКонтакте"}
FRESH_DAYS = 14

e = html.escape


def read_briefs():
    """Справки: заголовок, URL первоисточника, дата публикации, вердикт проверки."""
    briefs = []
    for path in sorted(NEWS_DIR.glob("ИИ-игрушки_новость_*.md")):
        text = path.read_text(encoding="utf-8-sig")
        title = re.search(r"^# (.+)$", text, re.M)
        # Первая ссылка в разделе «Первоисточник» (URL бывает и в строке «- URL:», и списком ниже)
        section = re.search(r"^## Первоисточник(.*?)(?=^## )", text, re.M | re.S)
        url = re.search(r"https?://[^\s)>\]]+", section.group(1)) if section else None
        pub = re.search(r"^- Дата публикации:\s*(\d{4}-\d{2}-\d{2})", text, re.M)
        check = re.search(r"^- Проверка:\s*(.+)$", text, re.M)
        if check is None:
            verdict = "старый формат"
        elif "не проведена" in check.group(1):
            verdict = "не проверена"
        else:
            m = re.search(r"годится|доработать|отказ", check.group(1))
            verdict = m.group(0) if m else check.group(1)
        briefs.append({
            "file": path.name,
            "title": title.group(1).strip() if title else path.stem,
            "url": url.group(0).strip() if url else "",
            "published": pub.group(1) if pub else "",
            "verdict": verdict,
        })
    return briefs


def site_cards():
    """URL источника → id карточки на странице «Новости»."""
    if not SITE_HTML.exists():
        return {}
    s = SITE_HTML.read_text(encoding="utf-8")
    cards = {}
    for m in re.finditer(r'<article class="[^"]*" id="([^"]+)">(.*?)</article>', s, re.S):
        src = re.search(r'class="post__src" href="([^"]+)"', m.group(2))
        if src:
            cards[html.unescape(src.group(1))] = m.group(1)
    return cards


def read_posts(cards):
    posts = []
    for path in sorted(POSTS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        image = next((p for p in (path.with_suffix(x) for x in (".jpg", ".jpeg", ".png")) if p.exists()), None)
        lengths = {}
        for key, ((lo, hi), _) in LIMITS.items():
            post = (data.get("platforms") or {}).get(key) or {}
            lengths[key] = (len(full_text(post)), hi, full_text(post))
        src = data.get("source") or {}
        posts.append({
            "file": path.name,
            "summary": data.get("summary", ""),
            "source_title": src.get("title", ""),
            "url": src.get("url", ""),
            "published": src.get("published_at", ""),
            "image": image,
            "lengths": lengths,
            "unverified": data.get("unverified") or [],
            "card": cards.get(src.get("url", "")),
        })
    posts.sort(key=lambda p: p["published"], reverse=True)
    return posts


def read_reserve(today):
    """Кандидаты со статусом «резерв», которым ещё ≤14 дней."""
    if not REGISTRY.exists():
        return []
    rows = []
    for line in REGISTRY.read_text(encoding="utf-8-sig").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7 or not cells[5].startswith("резерв"):
            continue
        m = re.match(r"\d{4}-\d{2}-\d{2}", cells[2])
        age = (today - dt.date.fromisoformat(m.group(0))).days if m else None
        if age is not None and age <= FRESH_DAYS:
            rows.append({"title": cells[1], "published": cells[2], "age": age, "url": cells[4], "note": cells[5]})
    return rows


def read_log(path, limit=5):
    if not path.exists():
        return [], []
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    return (rows[0], rows[1:][-limit:][::-1]) if rows else ([], [])


def rel(path):
    return path.relative_to(OUT.parent).as_posix()


def pill(text, kind):
    return f'<span class="pill pill--{kind}">{e(text)}</span>'


VERDICT_KIND = {"годится": "ok", "старый формат": "muted", "не проверена": "warn", "доработать": "warn", "отказ": "bad"}


def render_post(p, brief):
    pills = []
    if brief:
        pills.append(pill(f"проверка: {brief['verdict']}", VERDICT_KIND.get(brief["verdict"], "muted")))
    pills.append(pill("на сайте", "ok") if p["card"] else pill("не на сайте", "warn"))
    pills.append(pill("картинка", "ok") if p["image"] else pill("без картинки", "warn"))
    if p["unverified"]:
        pills.append(pill(f"не подтверждено: {len(p['unverified'])}", "muted"))

    tabs = []
    for key, name in PLATFORMS.items():
        n, hi, text = p["lengths"][key]
        state = "ok" if n <= hi else "bad"
        tabs.append(
            f'<div class="platform"><div class="platform__head"><b>{name}</b>'
            f'{pill(f"{n} / {hi}", state)}'
            f'<button class="copy" type="button" data-copy>Копировать</button></div>'
            f'<pre class="platform__text">{e(text)}</pre></div>'
        )
    img = (f'<a href="{e(rel(p["image"]))}" target="_blank"><img class="thumb" src="{e(rel(p["image"]))}" alt=""></a>'
           if p["image"] else '<div class="thumb thumb--empty">нет картинки</div>')
    site = (f'<a href="Сайт/news.html#{e(p["card"])}" target="_blank">Открыть на сайте ↗</a>' if p["card"] else "")
    return f"""
    <article class="news">
      {img}
      <div class="news__body">
        <div class="news__meta">{e(p['published'])} · {''.join(pills)}</div>
        <h3>{e(p['summary'])}</h3>
        <div class="news__links"><a href="{e(p['url'])}" target="_blank" rel="noopener">Первоисточник ↗</a>{site}
          <span class="file">{e(p['file'])}</span></div>
        <details><summary>Тексты постов</summary>{''.join(tabs)}</details>
      </div>
    </article>"""


def build():
    today = dt.date.today()
    briefs = read_briefs()
    by_url = {b["url"]: b for b in briefs if b["url"]}
    cards = site_cards()
    posts = read_posts(cards)
    post_urls = {p["url"] for p in posts}
    waiting = [b for b in briefs if b["url"] not in post_urls]
    reserve = read_reserve(today)

    stats = [
        ("На сайте", len(cards)),
        ("Постов", len(posts)),
        ("Справок без постов", len(waiting)),
        ("Свежих в резерве", len(reserve)),
    ]
    stats_html = "".join(f'<div class="stat"><b>{n}</b><span>{e(t)}</span></div>' for t, n in stats)

    commands = [
        ("Новость целиком", "сделай новость про ИИ-игрушки"),
        ("На тему", "сделай новость про ИИ-игрушки: <тема или ссылка>"),
        ("С готовой справки", "запусти конвейер по справке <путь>"),
        ("Выложить сайт", "выложи сайт"),
    ]
    cmd_html = "".join(
        f'<div class="cmd"><span>{e(t)}</span><code>{e(c)}</code><button class="copy" type="button" data-copy-text="{e(c)}">Копировать</button></div>'
        for t, c in commands)

    waiting_html = "".join(
        f'<li>{pill(b["verdict"], VERDICT_KIND.get(b["verdict"], "muted"))} <b>{e(b["title"])}</b>'
        f' <span class="file">{e(b["file"])}</span><br><small>Дальше: '
        f'{"посты — «напиши посты по справке …»" if b["verdict"] in ("годится", "старый формат") else "проверка — «проверь справку …»" if b["verdict"] == "не проверена" else "решение Ивана (см. заключение проверки)"}'
        f'</small></li>' for b in waiting) or "<li>Нет — по всем справкам есть посты.</li>"

    reserve_html = "".join(
        f'<li><b>{e(r["title"])}</b> — {e(r["published"])} ({r["age"]} дн.) '
        f'<a href="{e(r["url"])}" target="_blank" rel="noopener">↗</a><br><small>{e(r["note"])}</small></li>'
        for r in reserve) or "<li>Свежих резервных кандидатов нет.</li>"

    logs_html = ""
    for name, path in LOGS.items():
        head, rows = read_log(path)
        if not rows:
            logs_html += f"<h3>{e(name)}</h3><p class='muted'>Записей пока нет.</p>"
            continue
        cols = [i for i, h in enumerate(head) if h != "промпт"]
        logs_html += (f"<h3>{e(name)}</h3><div class='table'><table><tr>"
                      + "".join(f"<th>{e(head[i])}</th>" for i in cols) + "</tr>"
                      + "".join("<tr>" + "".join(f"<td>{e(r[i]) if i < len(r) else ''}</td>" for i in cols) + "</tr>" for r in rows)
                      + "</table></div>")

    news_html = "".join(render_post(p, by_url.get(p["url"])) for p in posts)
    built = dt.datetime.now().strftime("%d.%m.%Y %H:%M")

    page = TEMPLATE.format(built=e(built), stats=stats_html, commands=cmd_html, news=news_html,
                           waiting=waiting_html, reserve=reserve_html, logs=logs_html)
    OUT.write_text(page, encoding="utf-8")
    return OUT


TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Пульт конвейера новостей</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;600&family=Unbounded:wght@600&display=swap" rel="stylesheet">
<style>
:root {{
  --ink: #1E1B2E; --ink-soft: #5A5570; --paper: #FFFFFF; --mist: #F5F3FA; --line: #E4DEF5;
  --violet: #7B5CFF; --lav: #EDE6FF;
  --ok: #1F8A4C; --ok-bg: #E3F5EA; --warn: #9A5B00; --warn-bg: #FFF1D6; --bad: #B42318; --bad-bg: #FDE7E5;
  --muted-bg: #EEEDF3;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --ink: #ECE9F6; --ink-soft: #ABA5C2; --paper: #16141F; --mist: #1F1C2B; --line: #322E44;
    --violet: #A894FF; --lav: #2A2442;
    --ok: #6FD39A; --ok-bg: #173325; --warn: #F2C26B; --warn-bg: #3A2C12; --bad: #FF8A80; --bad-bg: #3D1A18; --muted-bg: #2A2737;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--mist); color: var(--ink); font: 400 15px/1.5 "Golos Text", "Segoe UI", sans-serif; }}
.wrap {{ max-width: 1080px; margin: 0 auto; padding: 24px 16px 48px; }}
header h1 {{ font: 600 26px/1.2 "Unbounded", "Arial Black", sans-serif; margin: 0 0 4px; }}
.muted, small, .file {{ color: var(--ink-soft); }}
.file {{ font-size: 12px; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 20px 0; }}
.stat {{ background: var(--paper); border: 1px solid var(--line); border-radius: 16px; padding: 14px 16px; }}
.stat b {{ display: block; font: 600 28px/1.1 "Unbounded", sans-serif; color: var(--violet); }}
section {{ background: var(--paper); border: 1px solid var(--line); border-radius: 20px; padding: 18px 20px; margin: 16px 0; }}
section > h2 {{ font: 600 17px/1.3 "Unbounded", sans-serif; margin: 0 0 12px; }}
.cmd {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 8px 0; border-top: 1px solid var(--line); }}
.cmd:first-of-type {{ border-top: 0; }}
.cmd span {{ min-width: 140px; color: var(--ink-soft); }}
code {{ background: var(--lav); padding: 3px 8px; border-radius: 8px; font-size: 14px; overflow-wrap: anywhere; }}
.news {{ display: grid; grid-template-columns: 140px 1fr; gap: 16px; padding: 16px 0; border-top: 1px solid var(--line); }}
.news:first-of-type {{ border-top: 0; padding-top: 0; }}
.thumb {{ width: 140px; height: 140px; object-fit: cover; border-radius: 14px; display: block; }}
.thumb--empty {{ display: grid; place-items: center; background: var(--muted-bg); color: var(--ink-soft); font-size: 13px; }}
.news h3 {{ margin: 6px 0; font-size: 16px; line-height: 1.4; }}
.news__meta {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 13px; color: var(--ink-soft); }}
.news__links {{ display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 14px; }}
a {{ color: var(--violet); }}
.pill {{ display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 12px; font-weight: 600; white-space: nowrap; }}
.pill--ok {{ background: var(--ok-bg); color: var(--ok); }}
.pill--warn {{ background: var(--warn-bg); color: var(--warn); }}
.pill--bad {{ background: var(--bad-bg); color: var(--bad); }}
.pill--muted {{ background: var(--muted-bg); color: var(--ink-soft); }}
details {{ margin-top: 10px; }}
summary {{ cursor: pointer; color: var(--violet); font-weight: 600; }}
.platform {{ margin-top: 10px; border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }}
.platform__head {{ display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--mist); }}
.platform__head .copy {{ margin-left: auto; }}
.platform__text {{ margin: 0; padding: 12px; white-space: pre-wrap; font: inherit; font-size: 14px; max-height: 320px; overflow: auto; }}
.copy {{ font: inherit; font-size: 13px; padding: 4px 12px; border-radius: 999px; border: 1px solid var(--violet); background: transparent; color: var(--violet); cursor: pointer; }}
.copy:hover {{ background: var(--lav); }}
.copy.done {{ background: var(--violet); color: var(--paper); }}
ul.list {{ margin: 0; padding-left: 18px; }} ul.list li {{ margin: 8px 0; }}
.cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.cols section {{ margin: 0; }}
.table {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }}
th {{ color: var(--ink-soft); font-weight: 600; }}
h3 {{ font-size: 15px; }}
@media (max-width: 720px) {{
  .news {{ grid-template-columns: 1fr; }}
  .thumb {{ width: 100%; height: 200px; }}
  .cols {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Пульт конвейера новостей</h1>
    <div class="muted">Проект «Интерактивная сказка» · собрано {built} · обновить: <code>python Документы/Скрипты/build_dashboard.py</code></div>
  </header>
  <div class="stats">{stats}</div>

  <section>
    <h2>Запуск в Claude Code</h2>
    {commands}
  </section>

  <section>
    <h2>Новости и посты</h2>
    {news}
  </section>

  <div class="cols">
    <section><h2>Справки без постов</h2><ul class="list">{waiting}</ul></section>
    <section><h2>Резерв кандидатов (≤14 дней)</h2><ul class="list">{reserve}</ul></section>
  </div>

  <section>
    <h2>Журналы</h2>
    {logs}
  </section>
</div>
<script>
function copyText(text, btn) {{
  const done = () => {{ const t = btn.textContent; btn.textContent = "Скопировано"; btn.classList.add("done");
    setTimeout(() => {{ btn.textContent = t; btn.classList.remove("done"); }}, 1500); }};
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(done, () => fallback(text) && done());
  }} else if (fallback(text)) {{ done(); }}
}}
function fallback(text) {{
  const ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  let ok = false; try {{ ok = document.execCommand("copy"); }} catch (e) {{}}
  ta.remove(); return ok;
}}
document.addEventListener("click", (ev) => {{
  const btn = ev.target.closest(".copy"); if (!btn) return;
  const text = btn.dataset.copyText ?? btn.closest(".platform").querySelector(".platform__text").textContent;
  copyText(text, btn);
}});
</script>
</body>
</html>
"""


def main():
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    out = build()
    print(f"Пульт собран: {out}")
    if "--open" in sys.argv:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
