"""Выкладка сайта «Интерактивная сказка» на хостинг Рег.ру по SFTP.

Сравнивает файлы Результат/Сайт/ с файлами на сервере и выкладывает новые и
изменённые. На сервере ничего не удаляет.

Запуск (из любой папки):
    python deploy_site.py --check        проверить подключение и папку сайта
    python deploy_site.py                только показать, что будет выложено (по умолчанию)
    python deploy_site.py --upload       показать список и выложить после ввода «да»
    python deploy_site.py --upload --yes выложить без вопроса (когда подтверждение уже дано в чате)

Доступы — в файле .env рядом со скриптом (образец: .env.example). .env в git не попадает.
"""

import argparse
import csv
import datetime as dt
import os
import posixpath
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent.parent
SITE_DIR = PROJECT_DIR / "Результат" / "Сайт"
ENV_FILE = SCRIPT_DIR / ".env"
KNOWN_HOSTS = SCRIPT_DIR / "known_hosts"
LOG_FILE = SCRIPT_DIR / "журнал_выкладки.csv"

# Служебные файлы, которые на сайт не нужны
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
EXCLUDE_SUFFIXES = {".md", ".tmp", ".bak"}

REQUIRED_KEYS = ["SFTP_HOST", "SFTP_USER", "SFTP_PASSWORD", "SFTP_REMOTE_DIR"]


def load_env(path):
    """Простой разбор .env: строки КЛЮЧ=значение, # — комментарий."""
    if not path.exists():
        sys.exit(f"Нет файла {path}. Скопируйте .env.example в .env и заполните доступы.")
    env = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    # Если вписан адрес панели (https://serverXX.hosting.reg.ru:1500/) — берём только имя сервера
    host = env.get("SFTP_HOST", "")
    if "://" in host or "/" in host:
        host = urlsplit(host if "://" in host else "//" + host).hostname or ""
        env["SFTP_HOST"] = host
    missing = [k for k in REQUIRED_KEYS if not env.get(k)]
    if missing:
        sys.exit(f"В .env не заполнено: {', '.join(missing)}")
    return env


def connect(env, trust_new_host):
    try:
        import paramiko
    except ImportError:
        sys.exit("Нет библиотеки paramiko. Установите: pip install paramiko")

    client = paramiko.SSHClient()
    if KNOWN_HOSTS.exists():
        client.load_host_keys(str(KNOWN_HOSTS))

    class AskPolicy(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            fp = key.fingerprint if hasattr(key, "fingerprint") else key.get_base64()[:32]
            if not trust_new_host:
                raise SystemExit(
                    f"Сервер {hostname} ещё не известен. Отпечаток ключа: {key.get_name()} {fp}\n"
                    "Сверьте его (в панели хостинга или у поддержки) и запустите ещё раз с --trust-new-host."
                )
            client.get_host_keys().add(hostname, key.get_name(), key)
            client.save_host_keys(str(KNOWN_HOSTS))
            print(f"Ключ сервера сохранён в {KNOWN_HOSTS.name}: {key.get_name()} {fp}")

    client.set_missing_host_key_policy(AskPolicy())
    client.connect(
        hostname=env["SFTP_HOST"],
        port=int(env.get("SFTP_PORT") or 22),
        username=env["SFTP_USER"],
        password=env["SFTP_PASSWORD"],
        look_for_keys=False,
        allow_agent=False,
        timeout=20,
    )
    return client, client.open_sftp()


def local_files():
    if not SITE_DIR.exists():
        sys.exit(f"Нет папки сайта: {SITE_DIR}")
    for path in sorted(SITE_DIR.rglob("*")):
        if not path.is_file():
            continue
        if path.name in EXCLUDE_NAMES or path.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        yield path, path.relative_to(SITE_DIR).as_posix()


def remote_stat(sftp, remote_path):
    try:
        return sftp.stat(remote_path)
    except FileNotFoundError:
        return None


def plan_changes(sftp, remote_root):
    """Список (статус, локальный путь, относительный путь): новый / изменён."""
    changes, same = [], 0
    for path, rel in local_files():
        st = path.stat()
        rst = remote_stat(sftp, posixpath.join(remote_root, rel))
        if rst is None:
            changes.append(("новый", path, rel))
        elif rst.st_size != st.st_size or int(st.st_mtime) > int(rst.st_mtime or 0):
            changes.append(("изменён", path, rel))
        else:
            same += 1
    return changes, same


def ensure_remote_dir(sftp, remote_dir, made):
    if remote_dir in made or remote_dir in ("", "/"):
        return
    try:
        if stat.S_ISDIR(sftp.stat(remote_dir).st_mode):
            made.add(remote_dir)
            return
    except FileNotFoundError:
        pass
    ensure_remote_dir(sftp, posixpath.dirname(remote_dir), made)
    sftp.mkdir(remote_dir)
    made.add(remote_dir)


def upload(sftp, remote_root, changes):
    made, done = set(), []
    for status, path, rel in changes:
        remote_path = posixpath.join(remote_root, rel)
        ensure_remote_dir(sftp, posixpath.dirname(remote_path), made)
        sftp.put(str(path), remote_path)
        st = path.stat()
        # Ставим серверу дату локального файла — чтобы следующее сравнение было точным
        sftp.utime(remote_path, (st.st_atime, st.st_mtime))
        print(f"  ✓ {rel}")
        done.append((status, rel, st.st_size))
    return done


def write_log(env, done):
    new_file = not LOG_FILE.exists()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if new_file:
            w.writerow(["дата_время", "сервер", "папка", "статус", "файл", "размер_байт"])
        for status, rel, size in done:
            w.writerow([now, env["SFTP_HOST"], env["SFTP_REMOTE_DIR"], status, rel, size])


def main():
    # При запуске из агента (вывод в канал, не в консоль) — UTF-8, чтобы не было «кракозябр»
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    p =argparse.ArgumentParser(description="Выкладка сайта на хостинг по SFTP")
    p.add_argument("--check", action="store_true", help="только проверить подключение и папку сайта")
    p.add_argument("--upload", action="store_true", help="выложить новые и изменённые файлы")
    p.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
    p.add_argument("--trust-new-host", action="store_true", help="запомнить ключ сервера при первом подключении")
    args = p.parse_args()

    env = load_env(ENV_FILE)
    remote_root = env["SFTP_REMOTE_DIR"].rstrip("/")
    client, sftp = connect(env, args.trust_new_host)
    try:
        print(f"Подключено: {env['SFTP_USER']}@{env['SFTP_HOST']}")
        rst = remote_stat(sftp, remote_root)
        if rst is None or not stat.S_ISDIR(rst.st_mode):
            sys.exit(f"На сервере нет папки {remote_root}. Проверьте SFTP_REMOTE_DIR в .env.")

        if args.check:
            names = sorted(sftp.listdir(remote_root))
            print(f"Папка сайта {remote_root}: {len(names)} объектов")
            for n in names[:30]:
                print(f"  {n}")
            return

        changes, same = plan_changes(sftp, remote_root)
        print(f"Локально: {SITE_DIR}\nНа сервере: {remote_root}")
        print(f"Без изменений: {same}. К выкладке: {len(changes)}.")
        for status, path, rel in changes:
            print(f"  [{status}] {rel} ({path.stat().st_size} байт)")
        if site_url := env.get("SITE_URL"):
            print(f"Сайт: {site_url}")

        if not changes:
            print("Выкладывать нечего.")
            return
        if not args.upload:
            print("\nЭто просмотр. Чтобы выложить: python deploy_site.py --upload")
            return
        if not args.yes:
            answer = input("\nВыложить эти файлы? Введите «да»: ").strip().lower()
            if answer not in ("да", "yes", "y", "д"):
                print("Отменено.")
                return

        print("Выкладка:")
        done = upload(sftp, remote_root, changes)
        write_log(env, done)
        print(f"Готово: выложено {len(done)} файлов. Журнал: {LOG_FILE.name}")
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
