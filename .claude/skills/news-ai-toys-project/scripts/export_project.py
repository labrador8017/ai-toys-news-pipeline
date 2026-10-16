"""Выгрузка конвейера новостей в отдельный чистый комплект — для коллег или публикации.

Собирает только то, что нужно для работы конвейера (агенты, скиллы, скрипты,
данные, сайт, документация), без секретов, служебных файлов и личных
документов. Исходный репозиторий не меняет.

Запуск:
    python export_project.py                         в <проект>/tmp/export/…, пути D:\\myai оставить
    python export_project.py --root "C:\\work\\news"  заменить D:\\myai в инструкциях агентов на новый корень
    python export_project.py --out "D:\\share"        куда положить комплект
    python export_project.py --with-business-docs    добавить анализ рынка, PRD, подбор сказок
    python export_project.py --zip                   дополнительно упаковать в .zip
"""

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ROOT = SKILL_DIR.parent.parent.parent
PROJECT_NAME = "Разработка_Игрушка-джойстик"
PROJECT = ROOT / PROJECT_NAME
OLD_ROOT = "D:\\myai"

# Что берём из проекта (пути от папки проекта)
PROJECT_ITEMS = [
    "README.md",
    "INDEX.md",
    "Документы/Конвейер-новостей_инструкция-тестирования_2026-10-17.md",
    "Документы/Новости",
    "Документы/Скрипты",
    "Документы/Демо",
    "Результат/Конвейер-новостей_описание-проекта_2026-10-17.md",
    "Результат/Пульт-конвейера.html",
    "Результат/Посты",
    "Результат/Сайт",
    "Результат/Сайт_инструкция_размещение-рег-ру_2026-10-16.md",
]
BUSINESS_DOCS = [
    "Результат/Игрушка-джойстик_анализ-рынка_2026-09-24.md",
    "Результат/Игрушка-джойстик_подбор-сказок_2026-10-08.md",
    "Результат/Интерактивная-сказка_PRD_2026-10-08.md",
]
CLAUDE_ITEMS = [
    ".claude/agents/news-ai-toys-search.md",
    ".claude/agents/news-ai-toys-validator.md",
    ".claude/agents/news-ai-toys-content-writer.md",
    ".claude/skills/news-ai-toys-post",
    ".claude/skills/news-ai-toys-site",
    ".claude/skills/news-ai-toys-pipeline",
    ".claude/skills/news-ai-toys-project",
]
# Никогда не выгружаем
SKIP_NAMES = {".env", ".env.txt", "known_hosts", "__pycache__", ".DS_Store", "Thumbs.db", "desktop.ini"}
SKIP_SUFFIXES = {".pyc", ".tmp", ".bak"}
TEXT_FOR_PATHS = {".md", ".py", ".example"}

GITIGNORE = """# Секреты: доступы к хостингу, ключи API (образец — .env.example)
.env
.env.txt
known_hosts

# Служебное
__pycache__/
tmp/
*/tmp/
.playwright-mcp/
.claude/settings.local.json
"""

START_HERE = """
---

## Развернуть у себя

Комплект собран {date} из рабочего репозитория проекта «Интерактивная сказка».

### Что внутри
- `{project}/` — проект: README (начните с него), скрипты, справки, посты, сайт, пульт.
- `.claude/agents/` — субагенты: поиск, проверка, посты.
- `.claude/skills/` — скиллы: оркестратор `news-ai-toys-pipeline`, сайт, посты и `news-ai-toys-project` — скилл работы с этим репозиторием.

### Как развернуть
1. Склонируйте репозиторий или скопируйте папку целиком.
2. Откройте в ней Claude Code и скажите: **«разверни проект по скиллу news-ai-toys-project»** — Claude проверит Python, поставит зависимости, поможет заполнить `.env` и прогонит проверку.
3. Вручную то же самое — раздел «Подготовка» в `{project}/README.md`.

{paths_note}

### Чего здесь нет (специально)
- `.env` с доступами и ключами — у каждого свои (образец: `{project}/Документы/Скрипты/.env.example`).
- Личные и рабочие документы владельца проекта, ТЗ и исходные иллюстрации.
"""


def skip(path):
    return path.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES


def copy_item(src, dst, stats):
    if src.is_dir():
        for p in sorted(src.rglob("*")):
            if any(part in SKIP_NAMES for part in p.relative_to(src).parts) or skip(p) or p.is_dir():
                continue
            target = dst / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            stats["files"] += 1
            stats["bytes"] += p.stat().st_size
    elif src.exists() and not skip(src):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        stats["files"] += 1
        stats["bytes"] += src.stat().st_size
    else:
        stats["missing"].append(str(src))


def replace_root(out, new_root):
    changed = 0
    for p in out.rglob("*"):
        if p.is_file() and p.suffix.lower() in TEXT_FOR_PATHS:
            s = p.read_text(encoding="utf-8")
            if OLD_ROOT in s:
                p.write_text(s.replace(OLD_ROOT, new_root.rstrip("\\/")), encoding="utf-8")
                changed += 1
    return changed


def write_root_readme(out, deploy_section):
    """README.md в корне комплекта = README проекта (ссылки от корня) + раздел «Развернуть у себя».

    GitHub показывает на главной странице только корневой README."""
    src = out / PROJECT_NAME / "README.md"
    text = src.read_text(encoding="utf-8") if src.exists() else "# Конвейер новостей об ИИ-игрушках\n"

    def fix(m):
        link = m.group(2)
        if re.match(r"^(https?:|mailto:|#|/)", link):
            return m.group(0)
        return f"{m.group(1)}({PROJECT_NAME}/{link})"

    text = re.sub(r"(\[[^\]]*\])\(([^)]+)\)", fix, text)
    text = re.sub(r'(<img[^>]*\bsrc=")(?!https?:|/)([^"]+)"', lambda m: f'{m.group(1)}{PROJECT_NAME}/{m.group(2)}"', text)
    note = (f"> Код и данные проекта — в папке [`{PROJECT_NAME}/`]({PROJECT_NAME}/), агенты и скиллы Claude Code — в `.claude/`. "
            "Пути в командах ниже даны от папки проекта.\n\n")
    first_break = text.find("\n\n")
    text = text[:first_break + 2] + note + text[first_break + 2:] if first_break != -1 else note + text
    (out / "README.md").write_text(text.rstrip() + "\n" + deploy_section, encoding="utf-8")


def note_index(out):
    """INDEX.md описывает весь рабочий проект — помечаем, что в комплект вошёл только конвейер."""
    index = out / PROJECT_NAME / "INDEX.md"
    if index.exists():
        s = index.read_text(encoding="utf-8")
        head, _, rest = s.partition("\n")
        index.write_text(head + "\n\n> В этот комплект вошёл только конвейер новостей. Разделы «ТЗ», «Примеры», план развития "
                         "и бизнес-документы ниже описывают рабочий проект и здесь отсутствуют.\n" + rest, encoding="utf-8")


def main():
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Выгрузка конвейера новостей для коллег")
    ap.add_argument("--out", help="папка, в которой создать комплект (по умолчанию <проект>/tmp/export)")
    ap.add_argument("--root", help=f"новый корень вместо {OLD_ROOT} в инструкциях агентов и скиллов")
    ap.add_argument("--with-business-docs", action="store_true", help="добавить анализ рынка, PRD, подбор сказок")
    ap.add_argument("--zip", action="store_true", help="упаковать комплект в .zip")
    ap.add_argument("--name", help="имя папки комплекта (по умолчанию news-ai-toys_<дата>)")
    args = ap.parse_args()

    date = dt.date.today().isoformat()
    base = Path(args.out) if args.out else PROJECT / "tmp" / "export"
    out = base / (args.name or f"news-ai-toys_{date}")
    if out.exists():
        sys.exit(f"Папка уже есть: {out}\nУдалите её вручную или укажите другую через --out — перезаписывать не буду.")

    stats = {"files": 0, "bytes": 0, "missing": []}
    items = PROJECT_ITEMS + (BUSINESS_DOCS if args.with_business_docs else [])
    for item in items:
        copy_item(PROJECT / item, out / PROJECT_NAME / item, stats)
    for item in CLAUDE_ITEMS:
        copy_item(ROOT / item, out / item, stats)
    (out / ".gitignore").write_text(GITIGNORE, encoding="utf-8")

    if args.root:
        n = replace_root(out, args.root)
        paths_note = f"Пути `{OLD_ROOT}` в инструкциях заменены на `{args.root}` ({n} файлов) — положите комплект туда."
    else:
        paths_note = (f"⚠ Инструкции агентов и скиллов ссылаются на `{OLD_ROOT}`. Либо положите комплект в `{OLD_ROOT}`, "
                      "либо попросите Claude: «замени D:\\myai на путь к этой папке во всех файлах .claude и README» "
                      "(или пересоберите комплект с --root).")
    write_root_readme(out, START_HERE.format(date=date, project=PROJECT_NAME, paths_note=paths_note))
    note_index(out)

    print(f"Комплект: {out}")
    print(f"Файлов: {stats['files']}, размер: {stats['bytes'] / 1024 / 1024:.1f} МБ")
    for m in stats["missing"]:
        print(f"  ! не найдено: {m}")
    print("Не выгружено: .env, known_hosts, __pycache__, tmp, ТЗ и исходные иллюстрации, личный план развития"
          + ("" if args.with_business_docs else ", бизнес-документы (добавить: --with-business-docs)"))
    print("⚠ Сайт: иллюстрации в Результат/Сайт/assets/img/ (кроме news/) — временные заглушки, часть с действующими "
          "правами (см. PRD, раздел о правах). Для публичного показа заменить.")
    if args.zip:
        archive = shutil.make_archive(str(out), "zip", root_dir=out.parent, base_dir=out.name)
        print(f"Архив: {archive}")


if __name__ == "__main__":
    main()
