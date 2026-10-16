"""Картинка к посту про ИИ-игрушки через GigaChat API (рисует встроенный Kandinsky).

Берёт поле image (prompt, negative_prompt) из JSON поста в Результат/Посты/ и
сохраняет картинку рядом с JSON под тем же именем (.jpg). Существующую картинку
не перезаписывает. На сайт картинку переносит скилл news-ai-toys-site.

Запуск:
    python gigachat_img.py --check                 проверить ключ: токен и список моделей (квоту не тратит)
    python gigachat_img.py <путь к JSON поста>      сгенерировать картинку

Ключ авторизации (из кабинета developers.sber.ru) ищется по порядку:
    1) переменная окружения GIGACHAT_AUTH_KEY;
    2) .env рядом со скриптом: GIGACHAT_AUTH_KEY= или Authorization_key=;
    3) переменная пользователя Windows GIGACHAT_AUTH_KEY (реестр HKCU\\Environment) —
       на случай, если консоль открыта до того, как переменную записали.
Scope: GIGACHAT_SCOPE (по умолчанию GIGACHAT_API_PERS — для физлица).
Сертификат НУЦ Минцифры: certs/russian_trusted_root_ca.pem (проверку SSL не отключаем).
"""

import argparse
import csv
import datetime as dt
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / ".env"
CA_FILE = SCRIPT_DIR / "certs" / "russian_trusted_root_ca.pem"
LOG_FILE = SCRIPT_DIR / "журнал_картинок.csv"

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
DEFAULT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1"
DEFAULT_MODEL = "GigaChat"

SYSTEM_PROMPT = (
    "Ты — художник-иллюстратор. Рисуй по описанию пользователя одну картинку, "
    "без текста и надписей на изображении."
)


def read_env_file(path):
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0]
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def windows_user_env(name):
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def load_settings():
    file_env = read_env_file(ENV_FILE)
    key = (
        os.environ.get("GIGACHAT_AUTH_KEY")
        or file_env.get("GIGACHAT_AUTH_KEY")
        or file_env.get("Authorization_key")
        or windows_user_env("GIGACHAT_AUTH_KEY")
    )
    if not key:
        sys.exit("Не найден ключ авторизации GigaChat (GIGACHAT_AUTH_KEY). См. описание в начале скрипта.")
    scope = os.environ.get("GIGACHAT_SCOPE") or file_env.get("GIGACHAT_SCOPE") or "GIGACHAT_API_PERS"
    api_url = (os.environ.get("GIGACHAT_API_URL") or file_env.get("GIGACHAT_API_URL") or DEFAULT_API_URL).rstrip("/")
    model = os.environ.get("GIGACHAT_MODEL") or file_env.get("GIGACHAT_MODEL") or DEFAULT_MODEL
    return key.strip(), scope, api_url, model


def ssl_context():
    if not CA_FILE.exists():
        sys.exit(f"Нет сертификата {CA_FILE}. Скачайте Russian Trusted Root CA (gosuslugi.ru/crt).")
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=str(CA_FILE))
    return ctx


def http(ctx, method, url, headers, body=None, timeout=120):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        sys.exit(f"Ошибка {e.code} от {urllib.parse.urlsplit(url).netloc}: {detail}")
    except urllib.error.URLError as e:
        sys.exit(f"Нет связи с {urllib.parse.urlsplit(url).netloc}: {e.reason}")


def get_token(ctx, key, scope):
    raw = http(
        ctx, "POST", OAUTH_URL,
        {
            "Authorization": f"Basic {key}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        urllib.parse.urlencode({"scope": scope}).encode(),
        timeout=30,
    )
    data = json.loads(raw)
    expires = dt.datetime.fromtimestamp(data["expires_at"] / 1000).strftime("%H:%M")
    return data["access_token"], expires


def api_json(ctx, token, method, url, payload=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return json.loads(http(ctx, method, url, headers, body))


def check(ctx, key, scope, api_url):
    token, expires = get_token(ctx, key, scope)
    print(f"Токен получен (scope {scope}), действует до {expires}.")
    models = api_json(ctx, token, "GET", f"{api_url}/models")
    names = [m.get("id") for m in models.get("data", [])]
    print(f"Доступные модели ({len(names)}): {', '.join(names)}")


def build_prompt(image):
    text = f"Нарисуй: {image['prompt'].strip()}"
    if image.get("aspect_ratio") and image["aspect_ratio"] != "1:1":
        text += f". Формат кадра {image['aspect_ratio']}"
    if image.get("negative_prompt"):
        text += f". На картинке не должно быть: {image['negative_prompt'].strip()}"
    return text


def generate(ctx, key, scope, api_url, model, post_path):
    post_path = Path(post_path).resolve()
    data = json.loads(post_path.read_text(encoding="utf-8"))
    image = data.get("image") or {}
    if not image.get("prompt"):
        sys.exit(f"В {post_path.name} нет поля image.prompt.")

    existing = [p for p in post_path.parent.glob(post_path.stem + ".*")
                if p.suffix.lower() in (".jpg", ".jpeg", ".jfif", ".png")]
    if existing:
        sys.exit(f"Картинка уже есть: {existing[0].name}. Не перезаписываю.")
    out_path = post_path.with_suffix(".jpg")

    prompt = build_prompt(image)
    token, _ = get_token(ctx, key, scope)
    print(f"Модель {model}. Запрос на рисование отправлен, ждём ответ (обычно до минуты)…")
    resp = api_json(ctx, token, "POST", f"{api_url}/chat/completions", {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "function_call": "auto",
    })
    content = resp["choices"][0]["message"].get("content", "")
    m = re.search(r'<img\s+src="([^"]+)"', content)
    if not m:
        sys.exit(f"GigaChat не нарисовал картинку. Ответ модели: {content[:500]}")
    file_id = m.group(1)

    raw = http(ctx, "GET", f"{api_url}/files/{file_id}/content",
               {"Authorization": f"Bearer {token}", "Accept": "application/jpg"})
    out_path.write_bytes(raw)
    print(f"Сохранено: {out_path} ({len(raw)} байт)")

    usage = resp.get("usage", {})
    write_log(post_path.name, out_path.name, model, file_id, usage.get("total_tokens"), prompt)


def write_log(post_name, image_name, model, file_id, tokens, prompt):
    new_file = not LOG_FILE.exists()
    with LOG_FILE.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if new_file:
            w.writerow(["дата_время", "пост", "картинка", "модель", "id_файла", "токенов", "промпт"])
        w.writerow([dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    post_name, image_name, model, file_id, tokens, prompt])


def main():
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Картинка к посту через GigaChat API")
    p.add_argument("post", nargs="?", help="путь к JSON поста (Результат/Посты/*.json)")
    p.add_argument("--check", action="store_true", help="только проверить ключ: токен и модели")
    args = p.parse_args()

    key, scope, api_url, model = load_settings()
    ctx = ssl_context()
    if args.check:
        check(ctx, key, scope, api_url)
    elif args.post:
        generate(ctx, key, scope, api_url, model, args.post)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
