"""Проверка проекта «Конвейер новостей об ИИ-игрушках» перед коммитом и публикацией.

Ничего не меняет — только читает файлы и git. Запуск из любой папки:
    python project_check.py
Код выхода: 0 — ошибок нет (предупреждения допустимы), 1 — есть ошибки.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ROOT = SKILL_DIR.parent.parent.parent                    # корень репозитория (myai)
PROJECT = ROOT / "Разработка_Игрушка-джойстик"
CLAUDE = ROOT / ".claude"
SCRIPTS = PROJECT / "Документы" / "Скрипты"
POSTS = PROJECT / "Результат" / "Посты"
SITE = PROJECT / "Результат" / "Сайт"
NEWS = PROJECT / "Документы" / "Новости"

REQUIRED = [
    PROJECT / "README.md",
    PROJECT / "INDEX.md",
    PROJECT / "Результат" / "Конвейер-новостей_описание-проекта_2026-10-17.md",
    PROJECT / "Документы" / "Конвейер-новостей_инструкция-тестирования_2026-10-17.md",
    SCRIPTS / "post_check.py",
    SCRIPTS / "gigachat_img.py",
    SCRIPTS / "deploy_site.py",
    SCRIPTS / "build_dashboard.py",
    SCRIPTS / ".env.example",
    SCRIPTS / "certs" / "russian_trusted_root_ca.pem",
    SITE / "news.html",
    SITE / "index.html",
    NEWS / "ИИ-игрушки_кандидаты_реестр.md",
    CLAUDE / "agents" / "news-ai-toys-search.md",
    CLAUDE / "agents" / "news-ai-toys-validator.md",
    CLAUDE / "agents" / "news-ai-toys-content-writer.md",
    CLAUDE / "skills" / "news-ai-toys-post" / "SKILL.md",
    CLAUDE / "skills" / "news-ai-toys-site" / "SKILL.md",
    CLAUDE / "skills" / "news-ai-toys-pipeline" / "SKILL.md",
    CLAUDE / "skills" / "news-ai-toys-project" / "SKILL.md",
]
NEVER_TRACKED = [r"(^|/)\.env$", r"\.env\.txt$", r"(^|/)known_hosts$", r"__pycache__/"]
SECRET_PATTERNS = [
    (r"(SFTP_PASSWORD|GIGACHAT_AUTH_KEY|FUSIONBRAIN_(API|SECRET)_KEY)\s*=\s*\S{4,}", "заполненный ключ/пароль"),
    (r"Basic\s+[A-Za-z0-9+/]{30,}={0,2}", "ключ авторизации Basic"),
    (r"-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----", "приватный ключ"),
]
TEXT_EXT = {".md", ".py", ".html", ".css", ".js", ".json", ".csv", ".txt", ".example", ".yml"}

errors, warnings, infos = [], [], []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def rel(p):
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def git_files():
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "-c", "core.quotepath=off", "ls-files", "-z"],
                             capture_output=True, check=True).stdout.decode("utf-8")
        return [f for f in out.split("\0") if f]
    except (OSError, subprocess.CalledProcessError):
        warn("git недоступен — проверки репозитория пропущены")
        return None


def check_required():
    for p in REQUIRED:
        if not p.exists():
            err(f"нет обязательного файла: {rel(p)}")


def check_frontmatter():
    """Агенты и скиллы: есть name/description; ': ' в описании без кавычек ломает YAML."""
    files = list((CLAUDE / "agents").glob("news-ai-toys-*.md")) + list((CLAUDE / "skills").glob("news-ai-toys-*/SKILL.md"))
    for p in files:
        s = p.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        m = re.match(r"---\n(.*?)\n---\n", s, re.S)
        if not m:
            err(f"{rel(p)}: нет блока frontmatter (--- … ---)")
            continue
        fields = dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)
        for key in ("name", "description"):
            if key not in fields:
                err(f"{rel(p)}: во frontmatter нет поля {key}")
        desc = fields.get("description", "")
        if ": " in desc and not desc.startswith(('"', "'")):
            err(f"{rel(p)}: в description есть «: » без кавычек — YAML не разберётся, описание скилла пропадёт")
        expected = p.parent.name if p.name == "SKILL.md" else p.stem
        if fields.get("name", "").strip() != expected:
            err(f"{rel(p)}: name «{fields.get('name')}» не совпадает с именем файла/папки «{expected}»")


def check_control_chars(tracked):
    """Управляющие символы (например \\b вместо обратного слэша) — частый след неудачной правки."""
    candidates = [ROOT / f for f in tracked] if tracked is not None else list(PROJECT.rglob("*"))
    for p in candidates:
        if p.suffix.lower() not in TEXT_EXT or not p.is_file():
            continue
        if not (str(p).startswith(str(PROJECT)) or str(p).startswith(str(CLAUDE))):
            continue
        text = p.read_text(encoding="utf-8-sig", errors="replace")
        bad = re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text)
        if bad:
            err(f"{rel(p)}: управляющие символы ({len(bad)} шт.) — вероятно, испорченный путь с обратным слэшем")


def check_python():
    for p in list(SCRIPTS.glob("*.py")) + list((SKILL_DIR / "scripts").glob("*.py")):
        try:
            compile(p.read_text(encoding="utf-8-sig"), str(p), "exec")
        except SyntaxError as e:
            err(f"{rel(p)}: синтаксическая ошибка, строка {e.lineno}: {e.msg}")


def check_git(tracked):
    if tracked is None:
        return
    for f in tracked:
        for pat in NEVER_TRACKED:
            if re.search(pat, f):
                err(f"в git попал файл, которого там быть не должно: {f}")
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
    for rule in (".env", "__pycache__/"):
        if rule not in gi:
            err(f".gitignore: нет правила {rule}")
    # секреты в отслеживаемых текстовых файлах
    for f in tracked:
        p = ROOT / f
        if p.suffix.lower() not in TEXT_EXT or not p.is_file() or "Разработка_Игрушка-джойстик" not in f and not f.startswith(".claude/"):
            continue
        text = p.read_text(encoding="utf-8-sig", errors="replace")
        for pat, what in SECRET_PATTERNS:
            if re.search(pat, text):
                err(f"{f}: похоже на секрет — {what}")
    # неотслеживаемые файлы проекта
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "-c", "core.quotepath=off", "status", "--porcelain", "--", str(PROJECT), str(CLAUDE)],
                             capture_output=True, check=True).stdout.decode("utf-8")
        untracked = [l[3:] for l in out.splitlines() if l.startswith("??")]
        changed = [l[3:] for l in out.splitlines() if not l.startswith("??")]
        if untracked:
            warn("неотслеживаемые файлы (добавить в коммит или в .gitignore): " + ", ".join(untracked))
        if changed:
            infos.append(f"незакоммиченных изменений: {len(changed)}")
    except (OSError, subprocess.CalledProcessError):
        pass


def check_posts():
    sys.path.insert(0, str(SCRIPTS))
    try:
        from post_check import LIMITS, full_text
    except Exception as e:  # noqa: BLE001
        err(f"post_check.py не импортируется: {e}")
        return
    for p in sorted(POSTS.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            err(f"{rel(p)}: битый JSON ({e})")
            continue
        if data.get("schema_version") != "ai-toys-post/v1":
            err(f"{rel(p)}: schema_version не ai-toys-post/v1")
        for key, ((_, hi), _) in LIMITS.items():
            n = len(full_text((data.get("platforms") or {}).get(key) or {}))
            if n > hi:
                warn(f"{p.name}: {key} {n} симв. > {hi}")
        if not any(p.with_suffix(x).exists() for x in (".jpg", ".jpeg", ".png")):
            warn(f"{p.name}: нет картинки рядом с JSON")


def check_site():
    html = (SITE / "news.html").read_text(encoding="utf-8") if (SITE / "news.html").exists() else ""
    for page in SITE.glob("*.html"):
        s = page.read_text(encoding="utf-8")
        for ref in re.findall(r'(?:src|href)="([^"#:]+)"', s):
            if ref.startswith(("http", "mailto", "tel", "//")) or not ref.strip():
                continue
            ref = ref.split("?")[0]
            if not (SITE / ref).exists():
                err(f"{rel(page)}: ссылка на несуществующий файл {ref}")
    ids = re.findall(r'<article class="[^"]*" id="([^"]+)"', html)
    if len(ids) != len(set(ids)):
        err("news.html: повторяющиеся id карточек")
    srcs = re.findall(r'class="post__src" href="([^"]+)"', html)
    if len(srcs) != len(set(srcs)):
        err("news.html: одна новость (источник) на странице дважды")
    dates = re.findall(r'<time datetime="([\d-]+)"', html)
    if dates != sorted(dates, reverse=True):
        err("news.html: нарушен порядок карточек по дате (новые сверху)")
    if "[уточнить]" in html:
        err("news.html: на сайт попала метка [уточнить]")
    infos.append(f"новостей на сайте: {len(ids)}")


def check_briefs():
    pending = []
    for p in NEWS.glob("ИИ-игрушки_новость_*.md"):
        s = p.read_text(encoding="utf-8-sig")
        if re.search(r"^- Проверка:\s*не проведена", s, re.M):
            pending.append(p.name)
    if pending:
        infos.append("справки ждут проверки: " + ", ".join(pending))


def check_docs():
    for doc in (PROJECT / "README.md", PROJECT / "INDEX.md"):
        if not doc.exists():
            continue
        s = doc.read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)#]+)\)", s):
            if link.startswith("http"):
                continue
            if not (doc.parent / link).exists():
                err(f"{rel(doc)}: битая ссылка {link}")
    index = (PROJECT / "INDEX.md").read_text(encoding="utf-8") if (PROJECT / "INDEX.md").exists() else ""
    for p in list(POSTS.glob("*.json")) + list(SCRIPTS.glob("*.py")) + list(NEWS.glob("*.md")):
        if p.name not in index:
            warn(f"INDEX.md: не упомянут {rel(p)}")
    dash = PROJECT / "Результат" / "Пульт-конвейера.html"
    newest = max((p.stat().st_mtime for p in list(POSTS.glob("*.json")) + [SITE / "news.html"] if p.exists()), default=0)
    if dash.exists() and dash.stat().st_mtime < newest:
        warn("Пульт-конвейера.html старее постов/сайта — пересобрать build_dashboard.py")


def main():
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    tracked = git_files()
    check_required()
    check_frontmatter()
    check_control_chars(tracked)
    check_python()
    check_git(tracked)
    check_posts()
    check_site()
    check_briefs()
    check_docs()

    print(f"Проверка проекта: {rel(PROJECT)}")
    for title, items, mark in (("ОШИБКИ", errors, "✗"), ("Предупреждения", warnings, "!"), ("Сведения", infos, "·")):
        if items:
            print(f"\n{title} ({len(items)}):")
            for i in items:
                print(f"  {mark} {i}")
    print("\nИтог:", "есть ошибки — исправить до коммита/публикации" if errors else "ошибок нет")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
