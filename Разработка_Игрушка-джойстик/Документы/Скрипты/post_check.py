"""Проверка JSON поста (схема ai-toys-post/v1) перед картинкой и сайтом.

Точно считает длины постов (агент-писатель считает вручную), проверяет лимиты
и хэштеги, ищет метки [уточнить]. Ничего не меняет.

Запуск:
    python post_check.py <путь к JSON поста>

Код выхода: 0 — всё в норме, 1 — есть ошибки (пост надо вернуть на доработку).
"""

import json
import sys
from pathlib import Path

# (минимум, максимум) длины content + хэштеги через пробел; (мин, макс) число хэштегов
LIMITS = {
    "telegram": ((800, 950), (0, 3)),
    "max": ((600, 1200), (0, 3)),
    "vk": ((700, 1500), (3, 5)),
}
REQUIRED = ["schema_version", "source", "summary", "unverified", "image", "platforms"]


def full_text(post):
    tags = " ".join(post.get("hashtags") or [])
    return post.get("content", "") + ("\n\n" + tags if tags else "")


def main():
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        sys.exit("Запуск: python post_check.py <путь к JSON поста>")
    path = Path(sys.argv[1])
    data = json.loads(path.read_text(encoding="utf-8-sig"))

    errors, notes = [], []
    if data.get("schema_version") != "ai-toys-post/v1":
        errors.append(f"schema_version = {data.get('schema_version')!r}, нужно 'ai-toys-post/v1'")
    for key in REQUIRED:
        if key not in data:
            errors.append(f"нет поля {key}")
    if not (data.get("image") or {}).get("prompt"):
        errors.append("нет image.prompt — картинку не сгенерировать")

    print(f"Пост: {path.name}")
    for name, ((lo, hi), (tlo, thi)) in LIMITS.items():
        post = (data.get("platforms") or {}).get(name)
        if not post:
            errors.append(f"нет platforms.{name}")
            continue
        text = full_text(post)
        n, tags = len(text), len(post.get("hashtags") or [])
        mark = "ок"
        if n > hi:
            mark = f"ДЛИННЕЕ на {n - hi}"
            errors.append(f"{name}: {n} символов, максимум {hi} — сократить на {n - hi}+")
        elif n < lo:
            mark = f"короче нормы на {lo - n}"
            notes.append(f"{name}: {n} символов, норма от {lo}")
        if not tlo <= tags <= thi:
            errors.append(f"{name}: хэштегов {tags}, нужно {tlo}–{thi}")
        if "[уточнить]" in text:
            errors.append(f"{name}: в тексте осталась метка [уточнить]")
        print(f"  {name:9} {n:5} симв. (норма {lo}–{hi}), хэштегов {tags} — {mark}")

    for n in notes:
        print(f"Замечание: {n}")
    if errors:
        print("ОШИБКИ:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print("Всё в норме.")


if __name__ == "__main__":
    main()
