import time
import random
import requests
import ipaddress
import sys
import os
import json
import copy
import logging
import signal
import threading
import argparse
from datetime import datetime

try:
    import readline as _readline  # noqa: F401 — автодополнение в интерактиве (Unix / Git Bash)
except ImportError:
    _readline = None

# Включаем поддержку ANSI-цветов в консоли Windows
if sys.platform == 'win32':
    os.system('color')

# ==========================================
#         ВИЗУАЛЬНЫЙ СТИЛЬ (ANSI)
# ==========================================
class C:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    CLEAR_LINE = '\033[K'

ASCII_ART = r"""
                                               ____         
   ________  ____ _  _______  __   _________  / / /__  _____
  / ___/ _ \/ __ `/ / ___/ / / /  / ___/ __ \/ / / _ \/ ___/
 / /  /  __/ /_/ / / /  / /_/ /  / /  / /_/ / / /  __/ /    
/_/   \___/\__, (_)_/   \__,_/  /_/   \____/_/_/\___/_/     
          /____/                                            
"""


def _animate_ascii_line(line: str, char_delay: float):
    if not line:
        print()
        return

    for index in range(1, len(line) + 1):
        visible_part = line[:index]
        sys.stdout.write(f"\r{C.CLEAR_LINE}{C.MAGENTA}{C.BOLD}{visible_part}{C.RESET}")
        sys.stdout.flush()
        time.sleep(char_delay)

    sys.stdout.write("\n")
    sys.stdout.flush()


def print_ascii_art(animated=False, char_delay=0.0035, line_delay=0.05):
    if not animated or not sys.stdout.isatty():
        print(f"{C.MAGENTA}{C.BOLD}{ASCII_ART}{C.RESET}")
        return

    for raw_line in ASCII_ART.splitlines():
        _animate_ascii_line(raw_line, char_delay)
        time.sleep(line_delay)


# ==========================================
#     РАНДОМИЗАЦИЯ ИМЁН И ТАЙМИНГОВ
# ==========================================

def generate_random_vm_name(config: dict) -> str:
    """Генерирует случайное имя VM на основе настроек рандомизации."""
    name_cfg = config.get("name_randomization", {})
    if not name_cfg.get("enabled", False):
        return config.get("server_payload", {}).get("name", "vm")

    base_name = config.get("server_payload", {}).get("name", "vm")
    pattern = name_cfg.get("pattern", "{base}-{random}")

    # Формируем случайную часть
    prefixes = name_cfg.get("random_prefixes", ["test", "dev", "stg"])
    chosen_prefix = random.choice(prefixes) if prefixes else ""

    if name_cfg.get("random_numbers", True):
        digits = name_cfg.get("random_number_digits", 2)
        number_part = str(random.randint(0, 10 ** digits - 1)).zfill(digits)
        random_part = f"{chosen_prefix}{number_part}" if chosen_prefix else number_part
    else:
        random_part = chosen_prefix

    # Подставляем в шаблон
    return pattern.format(base=base_name, random=random_part)


def get_random_iteration_delay(config: dict) -> float:
    """Возвращает случайную задержку между итерациями (имитация человека)."""
    timings_rand = config.get("timings_randomization", {})
    if not timings_rand.get("enabled", False):
        return 0

    # Определяем: обычная пауза или долгая
    if random.random() < timings_rand.get("long_pause_probability", 0.15):
        # Долгая пауза 1-2 минуты
        pause_min = timings_rand.get("long_pause_min", 1) * 60
        pause_max = timings_rand.get("long_pause_max", 2) * 60
        delay = random.uniform(pause_min, pause_max)
        pause_type = "долгая"
    else:
        # Обычная пауза 6-12 секунд
        delay = random.uniform(
            timings_rand.get("between_iterations_min", 6),
            timings_rand.get("between_iterations_max", 12),
        )
        pause_type = "обычная"

    log.info(f"Рандомизация: {pause_type} пауза {delay:.1f}с")
    return delay


def print_pause_banner(delay: float):
    """Красиво выводит информацию о паузе."""
    if delay >= 60:
        mins = delay / 60
        print(f"\n{C.DIM}😴 Пауза {mins:.1f} мин...{C.RESET}")
    else:
        print(f"\n{C.DIM}😴 Пауза {delay:.1f}с...{C.RESET}")


def prompt_line_with_completions(label: str, current: str, completions):
    """Ввод строки с Tab-автодополнением (если доступен readline)."""
    display = (current[:50] + "…") if len(current) > 50 else current
    prompt = f"{label} [{display}]: "
    if not _readline:
        raw = input(prompt).strip()
        return raw if raw else current

    def completer(text, state):
        matches = [c for c in completions if c.startswith(text)]
        try:
            return matches[state]
        except IndexError:
            return None

    old_completer = _readline.get_completer()
    old_delims = _readline.get_completer_delims()
    try:
        _readline.set_completer(completer)
        _readline.set_completer_delims(" \t\n`!@#$%^&*()=+[{]}\\|;:'\",<>?")
        _readline.parse_and_bind("tab: complete")
        raw = input(prompt).strip()
    finally:
        _readline.set_completer(old_completer)
        _readline.set_completer_delims(old_delims)
    return raw if raw else current


# ==========================================
#     МЕНЮ СО СТРЕЛКАМИ (↑↓ Enter)
# ==========================================

def _tty_nav_available() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _read_nav_key():
    """
    Одно нажатие: 'up' | 'down' | 'enter' | 'home' | 'end' | 'esc'.
    Кроссплатформенно: Windows (msvcrt), POSIX (termios).
    """
    if sys.platform == "win32":
        import msvcrt

        b = msvcrt.getch()
        if b in (b"\r", b"\n"):
            return "enter"
        if b == b"\x03":
            raise KeyboardInterrupt
        if b in (b"\xe0", b"\x00"):
            b2 = msvcrt.getch()
            if b2 == b"H":
                return "up"
            if b2 == b"P":
                return "down"
            if b2 == b"G":
                return "home"
            if b2 == b"O":
                return "end"
            return None
        if b == b"\x1b":
            seq = bytearray(b"\x1b")
            while msvcrt.kbhit() and len(seq) < 12:
                seq += msvcrt.getch()
            if seq.endswith(b"[A") or seq.endswith(b"OA"):
                return "up"
            if seq.endswith(b"[B") or seq.endswith(b"OB"):
                return "down"
            if seq.endswith(b"[1~") or seq.endswith(b"[H") or seq.endswith(b"OH"):
                return "home"
            if seq.endswith(b"[4~") or seq.endswith(b"[F") or seq.endswith(b"OF"):
                return "end"
            return "esc"
        return None

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
        if ch == "\r" or ch == "\n":
            return "enter"
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "up"
                if ch3 == "B":
                    return "down"
                if ch3 == "H":
                    return "home"
                if ch3 == "F":
                    return "end"
                if ch3 == "1":
                    if sys.stdin.read(1) == "~":
                        return "home"
                if ch3 == "4":
                    if sys.stdin.read(1) == "~":
                        return "end"
                if ch3 == "O":
                    ch4 = sys.stdin.read(1)
                    if ch4 == "H":
                        return "home"
                    if ch4 == "F":
                        return "end"
                while ch3 and ch3 not in "ABCDEFGHZ~":
                    ch3 = sys.stdin.read(1)
            return "esc"
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _strip_ansi(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\033" and i + 1 < len(s) and s[i + 1] == "[":
            j = i + 2
            while j < len(s) and s[j] not in "mH":
                j += 1
            i = j + 1 if j < len(s) else len(s)
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _visible_len(s: str) -> int:
    return len(_strip_ansi(s))


def _rbox_row(inner_cell: str, inner_width: int) -> str:
    """Строка рамки: │ + ячейка ровно inner_width видимых символов + │."""
    if _visible_len(inner_cell) > inner_width:
        inner_cell = _truncate_visible(_strip_ansi(inner_cell), inner_width)
    pad = max(0, inner_width - _visible_len(inner_cell))
    return f"{C.DIM}│{C.RESET}{inner_cell}{' ' * pad}{C.DIM}│{C.RESET}"


def clear_terminal():
    """Полная очистка экрана (курсор в левый верхний угол)."""
    if sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def _truncate_visible(text: str, max_vis: int) -> str:
    plain = _strip_ansi(text)
    if len(plain) <= max_vis:
        return text
    if max_vis <= 0:
        return ""
    if max_vis == 1:
        return "…"
    return plain[: max_vis - 1] + "…"


def arrow_pick_menu(
    title: str,
    option_labels: list,
    *,
    subtitle: str = "",
    dirty_note: str = "",
    clear_before: bool = True,
) -> int:
    """
    Интерактивный список. Возвращает индекс 0..n-1.
    Без TTY или при сбое — запасной ввод номера.
    """
    n = len(option_labels)
    if n == 0:
        return 0
    if not _tty_nav_available():
        print(f"\n{C.BOLD}{title}{C.RESET}")
        for i, lab in enumerate(option_labels, start=1):
            print(f"  {i}. {_strip_ansi(lab)}")
        raw = input("Номер пункта: ").strip()
        try:
            k = int(raw)
            if 1 <= k <= n:
                return k - 1
        except ValueError:
            pass
        return 0

    idx = 0
    first_draw = True
    if _tty_nav_available():
        if clear_before:
            clear_terminal()
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

    def build_block(sel: int) -> str:
        inner_w = 52
        top = f"{C.DIM}╭{'─' * inner_w}╮{C.RESET}"
        bot = f"{C.DIM}╰{'─' * inner_w}╯{C.RESET}"
        dirty = f" {C.YELLOW}{dirty_note}{C.RESET}" if dirty_note else ""
        title_plain = _strip_ansi(title)
        title_vis = (
            f"{C.BOLD}{C.CYAN}{title_plain}{C.RESET}{dirty}"
            if len(title_plain) + _visible_len(dirty) <= inner_w
            else f"{C.BOLD}{C.CYAN}{_truncate_visible(title_plain, max(8, inner_w - _visible_len(dirty) - 1))}{C.RESET}{dirty}"
        )
        lines = [
            "",
            top,
            _rbox_row(title_vis, inner_w),
        ]
        if subtitle:
            sub_plain = _strip_ansi(subtitle)
            sub_cell = f"{C.DIM}{_truncate_visible(sub_plain, inner_w)}{C.RESET}"
            lines.append(_rbox_row(sub_cell, inner_w))
        lines.append(f"{C.DIM}├{'─' * inner_w}┤{C.RESET}")
        prefix_sel_w = 2
        prefix_unsel_w = 3
        for i, raw_lab in enumerate(option_labels):
            lab = _strip_ansi(raw_lab)
            if i == sel:
                cap = inner_w - prefix_sel_w
                lab_cut = lab if len(lab) <= cap else lab[: max(0, cap - 1)] + "…"
                cell = (
                    f"{C.GREEN}{C.BOLD}▶{C.RESET} "
                    f"{C.BOLD}{C.GREEN}{lab_cut}{C.RESET}"
                )
            else:
                cap = inner_w - prefix_unsel_w
                lab_cut = lab if len(lab) <= cap else lab[: max(0, cap - 1)] + "…"
                cell = f"   {C.DIM}{lab_cut}{C.RESET}"
            lines.append(_rbox_row(cell, inner_w))
        lines.append(f"{C.DIM}├{'─' * inner_w}┤{C.RESET}")
        hint_rich = (
            f"{C.DIM}↑↓{C.RESET} навигация {C.DIM}·{C.RESET} "
            f"{C.BOLD}Enter{C.RESET} — выбор {C.DIM}·{C.RESET} {C.DIM}Home/End{C.RESET} — край"
        )
        if _visible_len(hint_rich) > inner_w:
            hint_short = "↑↓ Enter — выбор · Home/End"
            if len(hint_short) > inner_w:
                hint_short = hint_short[: max(0, inner_w - 1)] + "…"
            hint_rich = f"{C.DIM}{hint_short}{C.RESET}"
        lines.append(_rbox_row(hint_rich, inner_w))
        lines.append(_rbox_row("", inner_w))
        lines.append(bot)
        return "\n".join(lines) + "\n"

    try:
        block = build_block(idx)
        line_count = len(block.splitlines())
        sys.stdout.write(block)
        sys.stdout.flush()

        while True:
            if not first_draw:
                sys.stdout.write(f"\033[{line_count}A")
                sys.stdout.write(build_block(idx))
                sys.stdout.flush()
            first_draw = False

            try:
                key = _read_nav_key()
            except (KeyboardInterrupt, EOFError):
                raise

            if key == "up":
                idx = (idx - 1) % n
            elif key == "down":
                idx = (idx + 1) % n
            elif key == "home":
                idx = 0
            elif key == "end":
                idx = n - 1
            elif key == "enter":
                return idx
            elif key == "esc":
                pass
            elif key is None:
                pass
    finally:
        if _tty_nav_available():
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()


# ==========================================
#            КОНФИГУРАЦИЯ И ЛОГИ
# ==========================================

DEFAULT_CONFIG = {
    "api_token": "REG_RU_TOKEN",
    "api_base_url": "https://api.cloudvps.reg.ru/v1/reglets",
    "server_payload": {
        "backups": False,
        "floating_ip": True,
        "image": "ubuntu-18-04-amd64",
        "name": "vm",
        "region_slug": "openstack-msk1",
        "size": "c1-m1-d10-base"
    },
    "target_subnets": [
        "79.174.91.0/24", "79.174.92.0/24", "79.174.93.0/24", "79.174.94.0/24",
        "79.174.95.0/24", "37.140.192.0/24", "89.108.126.0/24", "31.31.197.0/24", "31.31.198.0/24", "213.189.204.0/24"
    ],
    "max_success": 1,
    "timings": {
        "initial_wait": 90,
        "check_interval": 5,
        "stability_checks": 3,
        "delete_wait": 10
    },
    # Рандомизация для имитации человеческого поведения
    "name_randomization": {
        "enabled": True,
        # Шаблон имени: {base} — базовое имя, {random} — случайная часть
        # Варианты: "{base}-{random}", "{base}{random}", "{random}-{base}", "{random}"
        "pattern": "{base}-{random}",
        # Префиксы для случайной части (выбирается один рандомно)
        "random_prefixes": ["test", "dev", "stg", "prod", "app", "web", "db", "api", "srv", "node", "vm", "box"],
        # Использовать ли числа в случайной части
        "random_numbers": True,
        # Длина числовой части (сколько цифр)
        "random_number_digits": 2,
    },
    "timings_randomization": {
        "enabled": True,
        # Базовая пауза между итерациями (секунды): от и до
        "between_iterations_min": 6,
        "between_iterations_max": 12,
        # Вероятность долгой паузы (0.0 — никогда, 1.0 — всегда)
        "long_pause_probability": 0.15,
        # Долгая пауза (минуты): от и до
        "long_pause_min": 1,
        "long_pause_max": 2,
    },
    "notifications": {
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "discord_webhook_url": "",
        "heartbeat_interval_min": 0,
    },
    # Роллинг плавающих IP через cloud.reg.ru (cookie + GraphQL), подсети = target_subnets выше
    "floating_roll": {
        "cookie": "ВСТАВЬ_СЮДА_COOKIE_ИЗ_БРАУЗЕРА",
        "service_id": "",
        "region": "openstack-msk1",
        "timings": {
            "initial_wait": 8,
            "check_interval": 3,
            "max_checks": 20,
            "delete_wait": 5,
            "cleanup_check_interval": 50,
        },
    },
}

GRAPHQL_URL = "https://cloudvps-graphql-server.svc.reg.ru/api"
REFRESH_URL = "https://login.reg.ru/refresh"
SUB_TOKEN_URL = "https://cloudvps-graphql-server.svc.reg.ru/auth/subscription_tokens"

GQL_CREATE_FLOATING = """
mutation createFloatingIp($params: CreateFloatingIPParams!) {
  floatingIP {
    create(params: $params) {
      ... on FloatingIP                 { __typename id address status }
      ... on Unauthorized               { __typename message }
      ... on FloatingIPsLimitExceeded   { __typename message }
      ... on FloatingIPRegionOutOfStock { __typename message }
      ... on InvalidRegion              { __typename message }
      __typename
    }
    __typename
  }
}
"""

GQL_LIST_FLOATING = """
query floatingIPs($region: String, $page: Int!, $pageSize: Int) {
  floatingIPs(region: $region, page: $page, pageSize: $pageSize) {
    ... on FloatingIPs {
      __typename
      floatingIPs { __typename id address status createdAt isLocked region }
    }
    ... on Unauthorized  { message __typename }
    ... on InvalidRegion { message __typename }
    __typename
  }
}
"""

GQL_REMOVE_FLOATING = """
mutation removeFloatingIp($params: RemoveFloatingIPParams!) {
  floatingIP {
    remove(params: $params) {
      ... on FloatingIP                        { __typename id }
      ... on Unauthorized                      { __typename message }
      ... on FloatingIPNotFound                { __typename message }
      ... on FloatingIPIsLocked                { __typename message }
      ... on FloatingIPResourcesCannotBeDeleted { __typename message }
      __typename
    }
    __typename
  }
}
"""

CLOUD_REGION_SUGGESTIONS = (
    "openstack-msk1",
    "openstack-spb1",
    "openstack-nsk1",
    "openstack-ekb1",
    "openstack-kzn1",
)


def _deep_merge_defaults(current, defaults):
    if not isinstance(current, dict):
        return copy.deepcopy(defaults)
    merged = copy.deepcopy(current)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(merged[key], dict):
            merged[key] = _deep_merge_defaults(merged[key], value)
    return merged


class ConfigManager:
    def __init__(self, config_file="config.json"):
        self.config_file = config_file
        self.config = self.load_config()

    def _merge_defaults(self, current, defaults):
        return _deep_merge_defaults(current, defaults)

    def load_config(self):
        default_config = copy.deepcopy(DEFAULT_CONFIG)
        if not os.path.exists(self.config_file):
            print(f"{C.YELLOW}[!] Конфиг {self.config_file} не найден. Создаю дефолтный.{C.RESET}")
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4)
            return default_config
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            return self._merge_defaults(cfg, default_config)
        except Exception as e:
            print(f"{C.RED}[ER] Ошибка чтения конфига: {e}. Используем дефолтный.{C.RESET}")
            return default_config

    def save_config(self, config=None):
        config_to_save = copy.deepcopy(config if config is not None else self.config)
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config_to_save, f, indent=4, ensure_ascii=False)
        self.config = config_to_save


class InteractiveMenu:
    def __init__(self, config_manager: ConfigManager, config: dict):
        self.config_manager = config_manager
        self.config = copy.deepcopy(config)
        self.is_dirty = False

    def _read_choice(self, prompt: str) -> str:
        try:
            return input(prompt).strip()
        except EOFError:
            return "0"

    def _mark_dirty(self):
        self.is_dirty = True

    def _mask_secret(self, value: str) -> str:
        if not value:
            return "(пусто)"
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}...{value[-4:]}"

    def _prompt_int(self, label: str, current: int, min_value: int = 1) -> int:
        while True:
            raw_value = self._read_choice(f"{label} [{current}]: ")
            if not raw_value:
                return current
            try:
                parsed = int(raw_value)
            except ValueError:
                print(f"{C.YELLOW}[!]{C.RESET} Нужно ввести целое число.")
                continue
            if parsed < min_value:
                print(f"{C.YELLOW}[!]{C.RESET} Значение должно быть не меньше {min_value}.")
                continue
            return parsed

    def _prompt_text(self, label: str, current: str) -> str:
        raw_value = self._read_choice(f"{label} [{current}]: ")
        return raw_value if raw_value else current

    def _prompt_bool(self, label: str, current: bool) -> bool:
        current_text = "Y/n" if current else "y/N"
        while True:
            raw_value = self._read_choice(f"{label} [{current_text}]: ").lower()
            if not raw_value:
                return current
            if raw_value in {"y", "yes", "д", "да"}:
                return True
            if raw_value in {"n", "no", "н", "нет"}:
                return False
            print(f"{C.YELLOW}[!]{C.RESET} Ответьте y/yes/да или n/no/нет.")

    def _prompt_subnets(self):
        current_subnets = ", ".join(self.config["target_subnets"])
        print(f"Текущие подсети: {current_subnets}")
        print("Введите список подсетей через запятую. Пустой ввод оставит всё как есть.")
        raw_value = self._read_choice("Новые подсети: ")
        if not raw_value:
            return

        candidates = [item.strip() for item in raw_value.split(",") if item.strip()]
        if not candidates:
            print(f"{C.YELLOW}[!]{C.RESET} Список подсетей не может быть пустым.")
            return

        validated = []
        for subnet in candidates:
            try:
                ipaddress.ip_network(subnet)
            except ValueError:
                print(f"{C.RED}[ER]{C.RESET} Неверная подсеть: {subnet}")
                return
            validated.append(subnet)

        self.config["target_subnets"] = validated
        self._mark_dirty()
        print(f"{C.GREEN}[OK]{C.RESET} Подсети обновлены.")

    def _show_settings(self):
        payload = self.config["server_payload"]
        timings = self.config["timings"]
        notif = self.config.get("notifications", {})
        nr = self.config.get("name_randomization", {})
        tr = self.config.get("timings_randomization", {})
        print(f"\n{C.BOLD}{C.MAGENTA}=== ТЕКУЩИЕ НАСТРОЙКИ ==={C.RESET}")
        print(f"Конфиг                : {self.config_manager.config_file}")
        print(f"Токен API             : {self._mask_secret(self.config.get('api_token', ''))}")
        print(f"API URL               : {self.config.get('api_base_url', '')}")
        print(f"Нужно серверов        : {self.config.get('max_success', 1)}")
        print(f"Подсети               : {', '.join(self.config.get('target_subnets', []))}")
        print(f"Имя сервера (база)    : {payload.get('name', '')}")
        print(f"Регион                : {payload.get('region_slug', '')}")
        print(f"Размер                : {payload.get('size', '')}")
        print(f"Образ                 : {payload.get('image', '')}")
        print(f"Floating IP           : {payload.get('floating_ip', False)}")
        print(f"Backups               : {payload.get('backups', False)}")
        print(f"Начальное ожидание    : {timings.get('initial_wait', 0)} сек")
        print(f"Интервал проверки     : {timings.get('check_interval', 0)} сек")
        print(f"Проверок стабильности : {timings.get('stability_checks', 0)}")
        print(f"Пауза после удаления  : {timings.get('delete_wait', 0)} сек")
        print(f"Рандом. имён          : {'вкл' if nr.get('enabled') else 'выкл'} | шаблон: {nr.get('pattern', '')}")
        print(f"Рандом. таймингов     : {'вкл' if tr.get('enabled') else 'выкл'} | "
              f"{tr.get('between_iterations_min', 6)}-{tr.get('between_iterations_max', 12)}с | "
              f"долгая: {int(tr.get('long_pause_probability', 0.15) * 100)}%")
        print(f"Heartbeat (floating)  : {notif.get('heartbeat_interval_min', 0)} мин")
        print(f"Сохранены в файл      : {'нет' if self.is_dirty else 'да'}")
        print(f"{C.MAGENTA}==========================={C.RESET}\n")

    def _edit_max_success(self):
        current = self.config.get("max_success", 1)
        self.config["max_success"] = self._prompt_int("Сколько серверов нужно найти", current, min_value=1)
        self._mark_dirty()

    def _edit_timings(self):
        timings = self.config["timings"]
        print(f"\n{C.BOLD}Настройка таймингов{C.RESET}")
        timings["initial_wait"] = self._prompt_int("Начальное ожидание, сек", timings.get("initial_wait", 90), min_value=0)
        timings["check_interval"] = self._prompt_int("Интервал проверки, сек", timings.get("check_interval", 5), min_value=1)
        timings["stability_checks"] = self._prompt_int("Сколько успешных чеков подряд считать стабильностью", timings.get("stability_checks", 3), min_value=1)
        timings["delete_wait"] = self._prompt_int("Пауза после удаления, сек", timings.get("delete_wait", 10), min_value=0)
        self._mark_dirty()

    def _edit_server_payload(self):
        payload = self.config["server_payload"]
        print(f"\n{C.BOLD}Настройка параметров сервера{C.RESET}")
        payload["name"] = self._prompt_text("Имя сервера", payload.get("name", "vm"))
        payload["region_slug"] = prompt_line_with_completions(
            "Регион (Tab — автодополнение)",
            payload.get("region_slug", "openstack-msk1"),
            CLOUD_REGION_SUGGESTIONS,
        )
        payload["size"] = self._prompt_text("Тариф/размер", payload.get("size", "c2-m2-d10-base"))
        payload["image"] = self._prompt_text("Образ", payload.get("image", "ubuntu-18-04-amd64"))
        payload["floating_ip"] = self._prompt_bool("Включить floating IP", payload.get("floating_ip", True))
        payload["backups"] = self._prompt_bool("Включить backups", payload.get("backups", False))
        self._mark_dirty()

    def _edit_api_settings(self):
        print(f"\n{C.BOLD}Настройка API{C.RESET}")
        self.config["api_token"] = self._prompt_text("API токен", self.config.get("api_token", ""))
        self.config["api_base_url"] = self._prompt_text("API base URL", self.config.get("api_base_url", ""))
        self._mark_dirty()

    def _edit_name_randomization(self):
        nr = self.config.setdefault("name_randomization", copy.deepcopy(DEFAULT_CONFIG["name_randomization"]))
        print(f"\n{C.BOLD}Рандомизация имён VM{C.RESET}")
        nr["enabled"] = self._prompt_bool("Включить рандомизацию имён", nr.get("enabled", True))
        nr["pattern"] = self._prompt_text(
            "Шаблон ({base}, {random})",
            nr.get("pattern", "{base}-{random}"),
        )
        current_prefixes = ", ".join(nr.get("random_prefixes", []))
        print(f"Текущие префиксы: {current_prefixes}")
        raw = self._read_choice("Новые префиксы через запятую (пустой ввод — оставить): ")
        if raw:
            nr["random_prefixes"] = [p.strip() for p in raw.split(",") if p.strip()]
        nr["random_numbers"] = self._prompt_bool("Добавлять числа к префиксам", nr.get("random_numbers", True))
        nr["random_number_digits"] = self._prompt_int("Количество цифр", nr.get("random_number_digits", 2), min_value=1)
        self._mark_dirty()

    def _edit_timings_randomization(self):
        tr = self.config.setdefault("timings_randomization", copy.deepcopy(DEFAULT_CONFIG["timings_randomization"]))
        print(f"\n{C.BOLD}Рандомизация таймингов (имитация человека){C.RESET}")
        tr["enabled"] = self._prompt_bool("Включить рандомизацию таймингов", tr.get("enabled", True))
        tr["between_iterations_min"] = self._prompt_int(
            "Мин. пауза между итерациями, сек", tr.get("between_iterations_min", 6), min_value=1
        )
        tr["between_iterations_max"] = self._prompt_int(
            "Макс. пауза между итерациями, сек", tr.get("between_iterations_max", 12), min_value=1
        )
        # Вероятность в процентах
        current_prob = int(tr.get("long_pause_probability", 0.15) * 100)
        new_prob = self._prompt_int("Вероятность долгой паузы, %", current_prob, min_value=0)
        tr["long_pause_probability"] = new_prob / 100.0
        tr["long_pause_min"] = self._prompt_int("Мин. долгая пауза, мин", tr.get("long_pause_min", 1), min_value=1)
        tr["long_pause_max"] = self._prompt_int("Макс. долгая пауза, мин", tr.get("long_pause_max", 2), min_value=1)
        self._mark_dirty()

    def _save_config(self):
        try:
            self.config_manager.save_config(self.config)
            self.is_dirty = False
            print(f"{C.GREEN}[OK]{C.RESET} Конфиг сохранен: {self.config_manager.config_file}")
        except Exception as e:
            print(f"{C.RED}[ER]{C.RESET} Не удалось сохранить конфиг: {e}")

    def _confirm_exit(self) -> bool:
        if not self.is_dirty:
            return True

        while True:
            answer = self._read_choice("Есть несохраненные изменения. Сохранить перед выходом? [y/N/c]: ").lower()
            if answer in {"y", "yes", "д", "да"}:
                self._save_config()
                return True
            if answer in {"", "n", "no", "н", "нет"}:
                return True
            if answer in {"c", "cancel", "о", "отмена"}:
                return False
            print(f"{C.YELLOW}[!]{C.RESET} Ответьте y/yes/да, n/no/нет или c/cancel/отмена.")

    def run(self) -> str:
        """'run' — старт роллера, 'hub' — в хаб, 'exit' — завершить программу."""
        labels = [
            "Запустить роллер",
            "Показать текущие настройки",
            "Изменить количество целей",
            "Изменить тайминги",
            "Рандомизация имён VM",
            "Рандомизация таймингов (человек)",
            "Изменить параметры сервера",
            "Изменить API (токен, URL)",
            "Изменить целевые подсети",
            "Сохранить config.json",
            "Назад в хаб режимов",
            "Выход из программы",
        ]
        dirty = "есть несохранённые изменения" if self.is_dirty else ""
        while True:
            choice = arrow_pick_menu(
                "VM / Reglet API",
                labels,
                subtitle=self.config_manager.config_file,
                dirty_note=dirty,
            )
            if choice == 0:
                return "run"
            if choice == 1:
                self._show_settings()
                continue
            if choice == 2:
                self._edit_max_success()
                continue
            if choice == 3:
                self._edit_timings()
                continue
            if choice == 4:
                self._edit_name_randomization()
                continue
            if choice == 5:
                self._edit_timings_randomization()
                continue
            if choice == 6:
                self._edit_server_payload()
                continue
            if choice == 7:
                self._edit_api_settings()
                continue
            if choice == 8:
                self._prompt_subnets()
                continue
            if choice == 9:
                self._save_config()
                continue
            if choice == 10:
                if self._confirm_exit():
                    return "hub"
                continue
            if choice == 11:
                if self._confirm_exit():
                    return "exit"
                continue


class FloatingCookieMenu:
    """Меню настроек режима Floating IP (cookie + GraphQL). Подсети и TG/Discord общие с VM."""

    def __init__(self, config_manager: ConfigManager, config: dict):
        self.config_manager = config_manager
        self.config = copy.deepcopy(config)
        self.is_dirty = False
        self.config.setdefault(
            "floating_roll",
            _deep_merge_defaults({}, copy.deepcopy(DEFAULT_CONFIG.get("floating_roll", {}))),
        )

    def _read(self, prompt: str) -> str:
        try:
            return input(prompt).strip()
        except EOFError:
            return "0"

    def _dirty(self):
        self.is_dirty = True

    def _mask_cookie(self, value: str) -> str:
        if not value or "ВСТАВЬ_СЮДА" in value:
            return f"{C.RED}(не задано){C.RESET}"
        return f"{value[:20]}…{value[-8:]}"

    def _fr(self) -> dict:
        return self.config["floating_roll"]

    def _prompt_int(self, label, current, min_value=0):
        while True:
            raw = self._read(f"{label} [{current}]: ")
            if not raw:
                return current
            try:
                v = int(raw)
                if v < min_value:
                    print(f"{C.YELLOW}[!]{C.RESET} Минимум {min_value}.")
                    continue
                return v
            except ValueError:
                print(f"{C.YELLOW}[!]{C.RESET} Введите целое число.")

    def _prompt_text(self, label, current):
        display = (current[:50] + "…") if len(current) > 50 else current
        raw = self._read(f"{label} [{display}]: ")
        return raw if raw else current

    def _prompt_subnets(self):
        print(f"Текущие (общие с VM): {', '.join(self.config.get('target_subnets', []))}")
        print("Подсети через запятую; пустой ввод — без изменений.")
        raw = self._read("Подсети: ")
        if not raw:
            return
        candidates = [s.strip() for s in raw.split(",") if s.strip()]
        validated = []
        for s in candidates:
            try:
                ipaddress.ip_network(s, strict=False)
                validated.append(s)
            except ValueError:
                print(f"{C.RED}[ER]{C.RESET} Неверная подсеть: {s}")
                return
        self.config["target_subnets"] = validated
        self._dirty()
        print(f"{C.GREEN}[OK]{C.RESET} Подсети обновлены.")

    def _show_settings(self):
        fr = self._fr()
        t = fr.get("timings", {})
        n = self.config.get("notifications", {})
        tg_ok = f"{C.GREEN}задан{C.RESET}" if n.get("telegram_bot_token") else f"{C.RED}нет{C.RESET}"
        print(f"\n{C.BOLD}{C.MAGENTA}══ Floating IP (cookie) ══{C.RESET}")
        print(f"Cookie           : {self._mask_cookie(fr.get('cookie', ''))}")
        print(f"Service ID       : {fr.get('service_id', '')}")
        print(f"Регион           : {fr.get('region', '')}")
        print(f"Подсети (общие)  : {', '.join(self.config.get('target_subnets', []))}")
        print(f"Нач. ожидание    : {t.get('initial_wait')} сек")
        print(f"Интервал проверки: {t.get('check_interval')} сек")
        print(f"Макс. проверок   : {t.get('max_checks')}")
        print(f"Пауза после удал.: {t.get('delete_wait')} сек")
        print(f"Очистка каждые N : {t.get('cleanup_check_interval', 50)}")
        tr = self.config.get("timings_randomization", {})
        print(f"Рандом. таймингов  : {'вкл' if tr.get('enabled') else 'выкл'} | "
              f"{tr.get('between_iterations_min', 6)}-{tr.get('between_iterations_max', 12)}с | "
              f"долгая: {int(tr.get('long_pause_probability', 0.15) * 100)}%")
        print(f"Telegram         : {tg_ok} | heartbeat: {n.get('heartbeat_interval_min', 0)} мин")
        print(f"Несохранено      : {'да' if self.is_dirty else 'нет'}")
        print(f"{C.MAGENTA}══════════════════════════{C.RESET}\n")

    def _edit_cookie(self):
        print(
            f"\n{C.YELLOW}[i]{C.RESET} cloud.reg.ru → F12 → Network → запрос к API → "
            f"Request Headers → {C.BOLD}Cookie{C.RESET}"
        )
        self._fr()["cookie"] = self._prompt_text("Cookie", self._fr().get("cookie", ""))
        self._dirty()

    def _edit_region_service(self):
        self._fr()["region"] = prompt_line_with_completions(
            "Регион (Tab)",
            self._fr().get("region", "openstack-msk1"),
            CLOUD_REGION_SUGGESTIONS,
        )
        self._fr()["service_id"] = self._prompt_text("Service ID", str(self._fr().get("service_id", "")))
        self._dirty()

    def _edit_timings(self):
        t = self._fr().setdefault("timings", {})
        defaults = DEFAULT_CONFIG["floating_roll"]["timings"]
        for key in defaults:
            t.setdefault(key, defaults[key])
        print(f"\n{C.BOLD}Тайминги Floating{C.RESET}")
        t["initial_wait"] = self._prompt_int("Нач. ожидание, сек", t["initial_wait"], 0)
        t["check_interval"] = self._prompt_int("Интервал проверки, сек", t["check_interval"], 1)
        t["max_checks"] = self._prompt_int("Макс. проверок", t["max_checks"], 1)
        t["delete_wait"] = self._prompt_int("Пауза после удаления, сек", t["delete_wait"], 0)
        t["cleanup_check_interval"] = self._prompt_int(
            "Очистка каждые N итераций (0=выкл)", t.get("cleanup_check_interval", 50), 0
        )
        self._dirty()

    def _edit_timings_randomization(self):
        tr = self.config.setdefault("timings_randomization", copy.deepcopy(DEFAULT_CONFIG["timings_randomization"]))
        print(f"\n{C.BOLD}Рандомизация таймингов (имитация человека){C.RESET}")
        tr["enabled"] = self._prompt_bool("Включить рандомизацию таймингов", tr.get("enabled", True))
        tr["between_iterations_min"] = self._prompt_int(
            "Мин. пауза между итерациями, сек", tr.get("between_iterations_min", 6), min_value=1
        )
        tr["between_iterations_max"] = self._prompt_int(
            "Макс. пауза между итерациями, сек", tr.get("between_iterations_max", 12), min_value=1
        )
        current_prob = int(tr.get("long_pause_probability", 0.15) * 100)
        new_prob = self._prompt_int("Вероятность долгой паузы, %", current_prob, min_value=0)
        tr["long_pause_probability"] = new_prob / 100.0
        tr["long_pause_min"] = self._prompt_int("Мин. долгая пауза, мин", tr.get("long_pause_min", 1), min_value=1)
        tr["long_pause_max"] = self._prompt_int("Макс. долгая пауза, мин", tr.get("long_pause_max", 2), min_value=1)
        self._dirty()

    def _edit_notifications(self):
        n = self.config.setdefault("notifications", {})
        print(f"\n{C.BOLD}Уведомления (общие с VM){C.RESET}")
        n["telegram_bot_token"] = self._prompt_text("Telegram Bot Token", n.get("telegram_bot_token", ""))
        n["telegram_chat_id"] = self._prompt_text("Telegram Chat ID", n.get("telegram_chat_id", ""))
        n["discord_webhook_url"] = self._prompt_text("Discord Webhook", n.get("discord_webhook_url", ""))
        n["heartbeat_interval_min"] = self._prompt_int(
            "Heartbeat каждые N мин (0=выкл)", n.get("heartbeat_interval_min", 0), 0
        )
        self._dirty()

    def _save(self):
        try:
            self.config_manager.save_config(self.config)
            self.is_dirty = False
            print(f"{C.GREEN}[OK]{C.RESET} Конфиг сохранён.")
        except Exception as e:
            print(f"{C.RED}[ER]{C.RESET} Ошибка сохранения: {e}")

    def _confirm_exit(self):
        if not self.is_dirty:
            return True
        while True:
            ans = self._read("Несохранённые изменения. Сохранить? [y/N/c]: ").lower()
            if ans in {"y", "yes", "д", "да"}:
                self._save()
                return True
            if ans in {"", "n", "no", "н", "нет"}:
                return True
            if ans in {"c", "cancel"}:
                return False

    def run(self) -> str:
        """Возвращает 'run' | 'hub' | 'exit'."""
        labels = [
            "Запустить роллер",
            "Показать настройки",
            "Cookie (из браузера)",
            "Регион и Service ID",
            "Подсети (общие с VM)",
            "Тайминги Floating",
            "Рандомизация таймингов (человек)",
            "Telegram / Discord / heartbeat",
            "Сохранить config.json",
            "Назад в хаб режимов",
            "Выход из программы",
        ]
        dirty = "есть несохранённые изменения" if self.is_dirty else ""
        while True:
            choice = arrow_pick_menu(
                "Floating IP (cookie + GraphQL)",
                labels,
                subtitle=self.config_manager.config_file,
                dirty_note=dirty,
            )
            if choice == 0:
                return "run"
            if choice == 1:
                self._show_settings()
            elif choice == 2:
                self._edit_cookie()
            elif choice == 3:
                self._edit_region_service()
            elif choice == 4:
                self._prompt_subnets()
            elif choice == 5:
                self._edit_timings()
            elif choice == 6:
                self._edit_timings_randomization()
            elif choice == 7:
                self._edit_notifications()
            elif choice == 8:
                self._save()
            elif choice == 9:
                if self._confirm_exit():
                    return "hub"
            elif choice == 10:
                if self._confirm_exit():
                    return "exit"


def setup_logger():
    logger = logging.getLogger("regru_roller")
    logger.setLevel(logging.DEBUG)
    
    # File handler
    fh = logging.FileHandler("roller.log", encoding="utf-8")
    fh.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    return logger

log = setup_logger()

# ==========================================
#               УВЕДОМЛЕНИЯ
# ==========================================

class Notifier:
    def __init__(self, config):
        self.tg_token = config.get("telegram_bot_token", "")
        self.tg_chat_id = config.get("telegram_chat_id", "")
        self.ds_url = config.get("discord_webhook_url", "")

    def send_success(self, ip, iteration):
        msg = f"✅ УСПЕХ!\nПойман нужный IP: {ip}\nПопытка: {iteration}"
        self._send_tg(msg)
        self._send_discord(msg)

    def _send_tg(self, msg):
        if not self.tg_token or not self.tg_chat_id: return
        tg_url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
        try:
            requests.post(tg_url, json={"chat_id": self.tg_chat_id, "text": msg}, timeout=5)
        except:
            pass

    def _send_discord(self, msg):
        if not self.ds_url: return
        try:
            requests.post(self.ds_url, json={"content": msg}, timeout=5)
        except:
            pass


class FloatingIpNotifier:
    """Уведомления для cookie-Floating режима: heartbeat, JWT, очистка."""

    def __init__(self, config: dict, stats: dict):
        self.tg_token = config.get("telegram_bot_token", "")
        self.tg_chat_id = config.get("telegram_chat_id", "")
        self.ds_url = config.get("discord_webhook_url", "")
        interval_min = config.get("heartbeat_interval_min", 0)
        self.hb_interval = interval_min * 60
        self.stats = stats
        self._hb_stop = threading.Event()
        self._hb_thread = None

    def _tg(self, msg: str) -> bool:
        if not self.tg_token or not self.tg_chat_id:
            return False
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.tg_token}/sendMessage",
                json={"chat_id": self.tg_chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=8,
            )
            data = resp.json()
            if not data.get("ok"):
                log.warning(f"Telegram: {data.get('description')}")
                return False
            return True
        except Exception as e:
            log.warning(f"Telegram send failed: {e}")
            return False

    def _discord(self, msg: str):
        if not self.ds_url:
            return
        plain = (
            msg.replace("<b>", "**").replace("</b>", "**").replace("<code>", "`").replace("</code>", "`")
        )
        try:
            requests.post(self.ds_url, json={"content": plain}, timeout=8)
        except Exception as e:
            log.warning(f"Discord send failed: {e}")

    def _send(self, msg: str):
        self._tg(msg)
        self._discord(msg)

    def send_success(self, ip: str, iteration: int):
        elapsed = get_beautiful_time(time.time() - self.stats["start_time"])
        msg = (
            f"✅ <b>Floating IP — успех</b>\n\n"
            f"🎯 IP: <code>{ip}</code>\n"
            f"🔄 Попытка: {iteration}\n"
            f"⏱ Время: {elapsed}\n"
            f"✨ Создано: {self.stats['created']} | 🗑 Удалено: {self.stats['deleted']}"
        )
        self._send(msg)

    def send_heartbeat(self):
        elapsed = get_beautiful_time(time.time() - self.stats["start_time"])
        now = datetime.now().strftime("%H:%M:%S")
        msg = (
            f"💓 <b>Roller жив</b> [{now}]\n\n"
            f"⏱ {elapsed}\n"
            f"✨ {self.stats['created']} | 🗑 {self.stats['deleted']} | 🔍 {self.stats['found']}"
        )
        ok = self._tg(msg)
        self._discord(msg)
        if ok:
            print(f"\n{C.DIM}[hb]{C.RESET} Heartbeat в Telegram.")
        log.info("Heartbeat floating")

    def send_jwt_expired(self):
        self._send(
            "⛔ <b>Floating IP — JWT</b>\n\nCookie устарела. Обнови в config и перезапусти."
        )

    def send_error(self, text: str):
        self._send(f"❌ <b>Roller</b>\n\n{text}")

    def send_cleanup(self, deleted_count: int, iteration: int):
        elapsed = get_beautiful_time(time.time() - self.stats["start_time"])
        msg = (
            f"🧹 <b>Очистка IP</b>\n\n"
            f"🔄 Итерация: {iteration}\n"
            f"🗑 Удалено: {deleted_count}\n"
            f"⏱ {elapsed}"
        )
        self._send(msg)

    def start_heartbeat(self):
        if self.hb_interval <= 0:
            return
        if not self.tg_token and not self.ds_url:
            return
        self._hb_stop.clear()
        self._hb_thread = threading.Thread(target=self._hb_loop, daemon=True)
        self._hb_thread.start()
        print(f"{C.DIM}[hb]{C.RESET} Heartbeat каждые {self.hb_interval // 60} мин.")

    def stop_heartbeat(self):
        self._hb_stop.set()
        if self._hb_thread:
            self._hb_thread.join(timeout=3)
            self._hb_thread = None

    def _hb_loop(self):
        while not self._hb_stop.wait(timeout=self.hb_interval):
            try:
                self.send_heartbeat()
            except Exception as e:
                log.warning(f"Heartbeat error: {e}")


# ==========================================
#       АНИМАЦИИ И ВСПОМОГАТЕЛЬНЫЕ ТУЛЗЫ
# ==========================================

class Spinner:
    def __init__(self, message="Ожидание...", spinner_chars=None, interval=0.1):
        self.spinner_chars = spinner_chars or ["|", "/", "-", "\\"]
        self.message = message
        self.interval = interval
        self.is_running = False
        self.thread = None
        self._lock = threading.Lock()

    def _spin(self):
        idx = 0
        while self.is_running:
            with self._lock:
                message = self.message
            sys.stdout.write(f"\r{C.CLEAR_LINE}{C.CYAN}{self.spinner_chars[idx]}{C.RESET} {message}")
            sys.stdout.flush()
            idx = (idx + 1) % len(self.spinner_chars)
            time.sleep(self.interval)
        sys.stdout.write(f"\r{C.CLEAR_LINE}")
        sys.stdout.flush()

    def update(self, message):
        with self._lock:
            self.message = message

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def stop(self):
        if not self.is_running and not self.thread:
            return
        self.is_running = False
        if self.thread:
            self.thread.join()
            self.thread = None

def get_beautiful_time(seconds):
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    if hours > 0: return f"{hours}ч {mins}м {secs}с"
    if mins > 0: return f"{mins}м {secs}с"
    return f"{secs}с"


def _parse_cookie_dict(cookie_str: str) -> dict:
    result = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            result[key.strip()] = value.strip()
    return result


def _build_cookie_str(cookie_dict: dict) -> str:
    return "; ".join(f"{key}={value}" for key, value in cookie_dict.items())


def _floating_effective_config(full_config: dict) -> dict:
    """Сборка dict в формате FloatingIpRoller из общего config.json."""
    defaults = copy.deepcopy(DEFAULT_CONFIG.get("floating_roll", {}))
    block = full_config.get("floating_roll") or {}
    merged_block = _deep_merge_defaults(block, defaults)
    timings = _deep_merge_defaults(
        merged_block.get("timings") or {},
        defaults.get("timings") or {},
    )
    return {
        "cookie": merged_block.get("cookie", ""),
        "service_id": str(merged_block.get("service_id", "")),
        "region": merged_block.get("region", "openstack-msk1"),
        "target_subnets": list(full_config.get("target_subnets") or []),
        "timings": timings,
        "notifications": full_config.get("notifications") or {},
    }


class JwtExpiredError(Exception):
    pass


class _CleanupFoundError(Exception):
    def __init__(self, ip_addr: str, ip_id: int):
        self.ip_addr = ip_addr
        self.ip_id = ip_id


class SessionManager:
    """Cookie + refresh JWT + subscription Bearer для GraphQL."""

    def __init__(self, cookie_str: str, service_id: str):
        self.cookie_dict = _parse_cookie_dict(cookie_str)
        self.service_id = service_id
        self._lock = threading.Lock()

    def _csrf(self) -> str:
        return (
            self.cookie_dict.get("csrftoken")
            or self.cookie_dict.get("acc-csrftoken")
            or self.cookie_dict.get("ext_auth_csrf")
            or ""
        )

    def refresh_jwt(self) -> bool:
        with self._lock:
            csrf = self._csrf()
            cookie_str = _build_cookie_str(self.cookie_dict)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://cloud.reg.ru",
            "Referer": "https://cloud.reg.ru/",
            "X-Csrf-Token": csrf,
            "Cookie": cookie_str,
        }
        try:
            resp = requests.post(REFRESH_URL, headers=headers, timeout=10)
            if resp.status_code != 200:
                log.warning(f"JWT refresh HTTP {resp.status_code}: {resp.text[:200]}")
                return False
            data = resp.json()
            if not data.get("success"):
                log.warning(f"JWT refresh: {data}")
                return False
            with self._lock:
                for cookie in resp.cookies:
                    self.cookie_dict[cookie.name] = cookie.value
            log.info("JWT обновлён (login.reg.ru/refresh)")
            return True
        except Exception as e:
            log.error(f"JWT refresh: {e}")
            return False

    def get_subscription_token(self):
        with self._lock:
            cookie_str = _build_cookie_str(self.cookie_dict)
            csrf = self._csrf()
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://cloud.reg.ru",
            "Referer": "https://cloud.reg.ru/",
            "X-Csrf-Token": csrf,
            "Cookie": cookie_str,
        }
        try:
            resp = requests.get(
                SUB_TOKEN_URL, params={"service_id": self.service_id}, headers=headers, timeout=10
            )
            if resp.status_code == 500:
                log.warning("subscription_tokens 500, пауза 5с")
                time.sleep(5)
                resp = requests.get(
                    SUB_TOKEN_URL, params={"service_id": self.service_id}, headers=headers, timeout=10
                )
            if resp.status_code != 200:
                log.warning(f"subscription_tokens HTTP {resp.status_code}: {resp.text[:300]}")
                return None
            return resp.json().get("token")
        except Exception as e:
            log.error(f"subscription_tokens: {e}")
            return None

    def get_cookie_str(self) -> str:
        with self._lock:
            return _build_cookie_str(self.cookie_dict)


class FloatingIpRoller:
    """Роллинг публичных адресов через create/delete Floating IP (GraphQL + cookie)."""

    def __init__(self, config: dict, full_config: dict = None):
        self.region = config["region"]
        self.service_id = config.get("service_id", "")
        self.target_subnets = []
        for net_str in config["target_subnets"]:
            try:
                self.target_subnets.append(ipaddress.ip_network(net_str, strict=False))
            except ValueError:
                print(f"{C.RED}[ER] Неверная подсеть: {net_str}{C.RESET}")

        t = config["timings"]
        self.initial_wait = t["initial_wait"]
        self.check_interval = t["check_interval"]
        self.max_checks = t["max_checks"]
        self.delete_wait = t["delete_wait"]
        self.cleanup_check_interval = t.get("cleanup_check_interval", 50)

        # Полный конфиг для рандомизации
        self.full_config = full_config or config

        self.session_mgr = SessionManager(config["cookie"], self.service_id)
        self.http = requests.Session()
        self.http.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Origin": "https://cloud.reg.ru",
                "Referer": "https://cloud.reg.ru/",
            }
        )

        self.stats = {"created": 0, "deleted": 0, "found": 0, "start_time": time.time()}
        self.notifier = FloatingIpNotifier(config.get("notifications", {}), self.stats)
        self.current_ip_id = None
        self.current_ip_addr = None
        self._sub_token = None
        self._token_lock = threading.Lock()

    def _get_auth_headers(self) -> dict:
        with self._token_lock:
            if not self._sub_token:
                token = self.session_mgr.get_subscription_token()
                if token:
                    self._sub_token = token
        headers = {"Cookie": self.session_mgr.get_cookie_str()}
        if self._sub_token:
            headers["Authorization"] = f"Bearer {self._sub_token}"
        return headers

    def _do_jwt_refresh(self) -> bool:
        print(f"\n{C.YELLOW}[!]{C.RESET} Пробуем обновить сессию (refresh)...")
        log.info("Cookie refresh")
        ok = self.session_mgr.refresh_jwt()
        if ok:
            print(f"{C.GREEN}[OK]{C.RESET} Сессия обновлена.")
            with self._token_lock:
                self._sub_token = None
            return True
        print(f"{C.RED}[ER]{C.RESET} Refresh не удался.")
        return False

    def _gql(self, operation_name: str, query: str, variables: dict, _retry_count: int = 0):
        payload = {"operationName": operation_name, "query": query, "variables": variables}
        try:
            self.http.cookies.clear()
            headers = self._get_auth_headers()
            resp = self.http.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if "errors" in data:
                for err in data["errors"]:
                    msg = err.get("message", "")
                    if "JWT expired" in msg or ("exp" in msg and "expired" in msg.lower()):
                        if _retry_count == 0:
                            with self._token_lock:
                                self._sub_token = None
                            return self._gql(operation_name, query, variables, _retry_count=1)
                        if _retry_count == 1:
                            if self._do_jwt_refresh():
                                return self._gql(operation_name, query, variables, _retry_count=2)
                        raise JwtExpiredError()
                log.warning(f"GraphQL [{operation_name}]: {data['errors']}")
                print(f"{C.YELLOW}[!]{C.RESET} GraphQL: {data['errors']}")
            return data.get("data")
        except JwtExpiredError:
            raise
        except Exception as e:
            print(f"{C.RED}[ER]{C.RESET} {operation_name}: {e}")
            log.error(f"{operation_name}: {e}")
            return None

    def _create_floating_ip(self) -> bool:
        data = self._gql(
            "createFloatingIp",
            GQL_CREATE_FLOATING,
            {"params": {"region": self.region, "description": ""}},
        )
        if not data:
            return False
        result = data.get("floatingIP", {}).get("create", {})
        if result.get("__typename") == "FloatingIP":
            return True
        msg = result.get("message", result.get("__typename"))
        print(f"{C.RED}[ER]{C.RESET} Создание: {msg}")
        log.error(f"createFloatingIp: {msg}")
        return False

    def _list_floating_ips(self) -> list:
        data = self._gql(
            "floatingIPs",
            GQL_LIST_FLOATING,
            {"region": self.region, "page": 1, "pageSize": 50},
        )
        if not data:
            return []
        container = data.get("floatingIPs", {})
        if container.get("__typename") != "FloatingIPs":
            log.warning(f"floatingIPs: {container.get('__typename')} {container.get('message')}")
            return []
        return container.get("floatingIPs", [])

    def _delete_floating_ip(self, ip_id: int) -> bool:
        data = self._gql("removeFloatingIp", GQL_REMOVE_FLOATING, {"params": {"id": ip_id}})
        if not data:
            return False
        result = data.get("floatingIP", {}).get("remove", {})
        if result.get("__typename") == "FloatingIP":
            return True
        msg = result.get("message", result.get("__typename"))
        print(f"{C.YELLOW}[!]{C.RESET} Удаление #{ip_id}: {msg}")
        log.warning(f"removeFloatingIp #{ip_id}: {msg}")
        return False

    def _is_target(self, ip_str: str) -> bool:
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            return any(ip_obj in net for net in self.target_subnets)
        except ValueError:
            return False

    def _wait_for_new_ip(self, known_ids: set):
        sp = Spinner(f"Начальное ожидание {self.initial_wait} сек...")
        sp.start()
        try:
            time.sleep(self.initial_wait)
        finally:
            sp.stop()

        check_sp = Spinner("Ожидание нового IP...", spinner_chars=["◴", "◷", "◶", "◵"], interval=0.12)
        check_sp.start()
        try:
            for i in range(self.max_checks):
                n = i + 1
                ips = self._list_floating_ips()
                for ip_obj in ips:
                    if ip_obj.get("id") in known_ids:
                        continue
                    addr = ip_obj.get("address", "")
                    status = ip_obj.get("status", "")
                    ip_id = ip_obj.get("id")
                    if not addr:
                        continue
                    if status == "ACTIVE":
                        check_sp.stop()
                        print(f"{C.GREEN}[OK]{C.RESET} Новый IP: {C.BOLD}{addr}{C.RESET} (id={ip_id})")
                        log.info(f"Floating IP {addr} id={ip_id}")
                        return {"id": ip_id, "address": addr}
                    check_sp.update(f"Проверка {n:02d}/{self.max_checks} | {addr} | {status}")
                new_any = [ip for ip in ips if ip.get("id") not in known_ids]
                if not new_any:
                    check_sp.update(f"Проверка {n:02d}/{self.max_checks} | ждём IP...")
                time.sleep(self.check_interval)
        finally:
            check_sp.stop()

        print(f"{C.RED}[ER]{C.RESET} IP не активировался вовремя.")
        log.warning("Floating IP timeout")
        return None

    def _safe_delete(self, ip_id: int, ip_addr: str):
        print(f"{C.YELLOW}[NO]{C.RESET} Удаляем {ip_addr} (id={ip_id})")
        log.info(f"Удаление floating {ip_addr} id={ip_id}")
        for attempt in range(1, 4):
            ok = self._delete_floating_ip(ip_id)
            if ok:
                print(f"{C.GREEN}[OK]{C.RESET} Удалён.")
                self.stats["deleted"] += 1
                break
            if attempt < 3:
                print(f"{C.YELLOW}[!]{C.RESET} Повтор через 5с ({attempt + 1}/3)...")
                time.sleep(5)
        else:
            log.error(f"Зомби-IP: {ip_addr} id={ip_id}")
        self.current_ip_id = None
        self.current_ip_addr = None
        sp = Spinner(f"Пауза {self.delete_wait} сек...")
        sp.start()
        try:
            time.sleep(self.delete_wait)
        finally:
            sp.stop()

    def _cleanup_check(self, iteration: int):
        print(f"\n{C.BOLD}{C.MAGENTA}[CLEANUP] Проверка всех IP (итерация {iteration}){C.RESET}")
        log.info(f"Cleanup iteration {iteration}")
        all_ips = self._list_floating_ips()
        if not all_ips:
            print(f"{C.DIM}[CLEANUP]{C.RESET} Список пуст.")
            return
        good = [ip for ip in all_ips if self._is_target(ip.get("address", ""))]
        junk = [ip for ip in all_ips if not self._is_target(ip.get("address", ""))]
        print(
            f"{C.DIM}[CLEANUP]{C.RESET} Всего {len(all_ips)} | "
            f"{C.GREEN}ok: {len(good)}{C.RESET} | {C.YELLOW}мусор: {len(junk)}{C.RESET}"
        )
        if good:
            ip_obj = good[0]
            ip_addr = ip_obj.get("address", "?")
            ip_id = ip_obj.get("id")
            print(f"{C.GREEN}[CLEANUP] Подходящий IP: {ip_addr} (id={ip_id}){C.RESET}")
            self.stats["found"] += 1
            self.notifier.send_success(ip_addr, iteration)
            for bad in junk:
                self._safe_delete(bad["id"], bad.get("address", "?"))
            raise _CleanupFoundError(ip_addr, ip_id)
        print(f"{C.YELLOW}[CLEANUP]{C.RESET} Удаляем {len(junk)} нецелевых...")
        deleted_count = 0
        for bad in junk:
            if self._delete_floating_ip(bad.get("id")):
                self.stats["deleted"] += 1
                deleted_count += 1
                print(f"{C.GREEN}  ✓{C.RESET} {bad.get('address')}")
            time.sleep(1)
        self.notifier.send_cleanup(deleted_count, iteration)
        print(f"{C.GREEN}[CLEANUP]{C.RESET} Удалено {deleted_count}.\n")

    def _print_result_box(self, ip: str, ip_id: int, attempt: int, success: bool):
        status_text = (
            f"{C.GREEN}✔ Подходит{C.RESET}" if success else f"{C.RED}✖ Не та подсеть{C.RESET}"
        )
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{C.DIM}╔═══════════════════════════════════════════════════════╗{C.RESET}")
        print(f"{C.DIM}║{C.RESET}  {C.CYAN}IP{C.RESET}      : {C.BOLD}{ip:<42}{C.RESET}{C.DIM}║{C.RESET}")
        print(f"{C.DIM}║{C.RESET}  {C.CYAN}ID{C.RESET}      : {str(ip_id):<42}{C.DIM}║{C.RESET}")
        print(f"{C.DIM}║{C.RESET}  {C.CYAN}Попытка{C.RESET} : {str(attempt):<42}{C.DIM}║{C.RESET}")
        print(f"{C.DIM}║{C.RESET}  {C.CYAN}Статус{C.RESET}  : {status_text:<51}{C.DIM}║{C.RESET}")
        print(f"{C.DIM}║{C.RESET}  {C.CYAN}Время{C.RESET}   : {now:<42}{C.DIM}║{C.RESET}")
        print(f"{C.DIM}╚═══════════════════════════════════════════════════════╝{C.RESET}\n")

    def _print_dashboard(self):
        elapsed = time.time() - self.stats["start_time"]
        print(f"\n{C.BOLD}{C.MAGENTA}=== Floating IP — итоги ==={C.RESET}")
        print(f"⏱  {C.CYAN}{get_beautiful_time(elapsed)}{C.RESET}")
        print(f"✨ Создано: {C.CYAN}{self.stats['created']}{C.RESET} | 🗑 Удалено: {C.CYAN}{self.stats['deleted']}{C.RESET}")
        print(f"✅ Найдено: {C.GREEN}{self.stats['found']}{C.RESET}")
        print(f"{C.MAGENTA}==========================={C.RESET}\n")
        log.info(
            f"Floating сессия: +{self.stats['created']} -{self.stats['deleted']} ={self.stats['found']}"
        )

    def _handle_interrupt(self):
        print(f"\n{C.YELLOW}[!] Ctrl+C{C.RESET}")
        log.warning("Прерывание floating")
        if self.current_ip_id:
            try:
                ans = input(
                    f"{C.YELLOW}[?]{C.RESET} Удалить {self.current_ip_addr} (id={self.current_ip_id})? [y/N]: "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans in {"y", "yes", "д", "да"}:
                if self._delete_floating_ip(self.current_ip_id):
                    self.stats["deleted"] += 1
                    print(f"{C.GREEN}✔ Удалён.{C.RESET}")
                else:
                    print(f"{C.RED}✖ Не удалось.{C.RESET}")
            else:
                print(f"{C.GREEN}✔ Оставлен.{C.RESET}")
        else:
            print(f"{C.GREEN}✔ Нет текущего IP.{C.RESET}")

    def run(self, show_banner: bool = True):
        if show_banner:
            print_ascii_art(animated=sys.stdout.isatty())
        if "ВСТАВЬ_СЮДА" in self.session_mgr.get_cookie_str():
            print(f"{C.RED}[ER]{C.RESET} Задайте Cookie в меню Floating → пункт 3.")
            return
        if not self.target_subnets:
            print(f"{C.RED}[ER]{C.RESET} Нет валидных target_subnets.")
            return
        print(f"{C.DIM}режим:{C.RESET} {C.BOLD}Floating IP (cookie){C.RESET} | регион {C.CYAN}{self.region}{C.RESET}\n")
        log.info(f"Старт FloatingIpRoller region={self.region}")
        self.notifier.start_heartbeat()
        iteration = 1
        try:
            while True:
                if (
                    iteration > 1
                    and self.cleanup_check_interval > 0
                    and iteration % self.cleanup_check_interval == 0
                ):
                    self._cleanup_check(iteration)
                print(f"{C.BOLD}{C.CYAN}--- Итерация {iteration} ---{C.RESET}")
                log.info(f"Floating iter {iteration}")
                existing_ids = {ip["id"] for ip in self._list_floating_ips()}
                print(f"{C.BLUE}[>>]{C.RESET} Создаём floating IP...")
                if not self._create_floating_ip():
                    print(f"{C.YELLOW}[!]{C.RESET} Не вышло создать IP, пауза.\n")
                    time.sleep(self.delete_wait)
                    iteration += 1
                    continue
                self.stats["created"] += 1
                new_ip = self._wait_for_new_ip(existing_ids)
                if not new_ip:
                    current = self._list_floating_ips()
                    for ip_obj in current:
                        if ip_obj.get("id") not in existing_ids:
                            self._safe_delete(ip_obj["id"], ip_obj.get("address", "?"))
                    iteration += 1
                    continue
                ip_id = new_ip["id"]
                ip_addr = new_ip["address"]
                self.current_ip_id = ip_id
                self.current_ip_addr = ip_addr
                success = self._is_target(ip_addr)
                self._print_result_box(ip_addr, ip_id, iteration, success)
                if success:
                    self.stats["found"] += 1
                    print(f"{C.GREEN}{C.BOLD}[!!!] Бинго: {ip_addr}{C.RESET}\n")
                    log.info(f"Цель {ip_addr} id={ip_id}")
                    self.notifier.send_success(ip_addr, iteration)
                    self.current_ip_id = None
                    self.current_ip_addr = None
                    break
                self._safe_delete(ip_id, ip_addr)

                # Рандомизация паузы между итерациями
                random_delay = get_random_iteration_delay(self.full_config)
                if random_delay > 0:
                    print_pause_banner(random_delay)
                    time.sleep(random_delay)

                iteration += 1
        except KeyboardInterrupt:
            self._handle_interrupt()
        except _CleanupFoundError as e:
            print(f"{C.GREEN}[CLEANUP] Зафиксирован: {e.ip_addr}{C.RESET}\n")
            log.info(f"Победа cleanup: {e.ip_addr}")
        except JwtExpiredError:
            print(f"\n{C.RED}{C.BOLD}JWT / Cookie — обновите Cookie в config{C.RESET}\n")
            log.error("JWT expired floating")
            self.notifier.send_jwt_expired()
            if self.current_ip_id:
                print(f"{C.YELLOW}[!]{C.RESET} Остался IP id={self.current_ip_id}")
        except Exception as e:
            print(f"\n{C.RED}Ошибка: {e}{C.RESET}")
            log.error(f"Floating critical: {e}", exc_info=True)
            self.notifier.send_error(str(e))
            self._handle_interrupt()
        finally:
            self.notifier.stop_heartbeat()
        self._print_dashboard()


# ==========================================
#               ЯДРО (ROLLER)
# ==========================================

class RegruRoller:
    def __init__(self, config):
        self.config = config
        self.api_token = config["api_token"]
        self.api_base_url = config["api_base_url"]
        self.payload = config["server_payload"]
        self.max_success = config["max_success"]
        
        self.target_subnets = []
        for net_str in config["target_subnets"]:
            try:
                self.target_subnets.append(ipaddress.ip_network(net_str))
            except ValueError:
                print(f"{C.RED}[ER] Неверный формат подсети: {net_str}{C.RESET}")

        t = config["timings"]
        self.initial_wait = t["initial_wait"]
        self.check_interval = t["check_interval"]
        self.stability_checks = t["stability_checks"]
        self.delete_wait = t["delete_wait"]

        self.session = requests.Session()
        self.session.headers.update({
            "accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}"
        })

        self.notifier = Notifier(config.get("notifications", {}))
        
        # Статистика сессии
        self.stats = {
            "created": 0,
            "deleted": 0,
            "found": 0,
            "start_time": time.time()
        }

        # Блокировка состояния для безопасного выхода (Ctrl+C)
        self.current_server_id = None
        self.pending_server_ids = []

    def _extract_reglet_object(self, payload):
        if not isinstance(payload, dict):
            return {}

        reglet_keys = {
            "id",
            "status",
            "state",
            "networks",
            "interfaces",
            "network_interfaces",
            "public_ip",
            "public_ipv4",
            "floating_ip",
            "ip_address",
            "ipv4",
            "v4",
            "addresses",
            "ips",
        }

        for key in ("reglet", "server", "instance", "result", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, dict) and reglet_keys.intersection(candidate.keys()):
                return candidate

        if reglet_keys.intersection(payload.keys()):
            return payload

        return {}

    def is_target_ip(self, ip_str: str) -> bool:
        if not ip_str or ip_str == "(еще нет)": return False
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            return any(ip_obj in net for net in self.target_subnets)
        except ValueError:
            return False

    def _normalize_public_ipv4(self, value) -> str:
        if not isinstance(value, str):
            return ""

        candidate = value.strip()
        if not candidate:
            return ""

        if "/" in candidate:
            candidate = candidate.split("/", 1)[0].strip()

        try:
            ip_obj = ipaddress.ip_address(candidate)
        except ValueError:
            return ""

        if ip_obj.version != 4:
            return ""

        if any([
            ip_obj.is_private,
            ip_obj.is_loopback,
            ip_obj.is_link_local,
            ip_obj.is_multicast,
            ip_obj.is_unspecified,
            ip_obj.is_reserved,
        ]):
            return ""

        return candidate

    def _collect_public_ip_candidates(self, node, preferred=False):
        preferred_candidates = []
        fallback_candidates = []

        def walk(value, is_preferred=False):
            if isinstance(value, dict):
                public_markers = {
                    str(value.get("type", "")).lower(),
                    str(value.get("scope", "")).lower(),
                    str(value.get("network_type", "")).lower(),
                    str(value.get("kind", "")).lower(),
                    str(value.get("name", "")).lower(),
                }
                nested_preferred = is_preferred or any(marker in {"public", "floating", "external", "internet"} for marker in public_markers)
                nested_preferred = nested_preferred or value.get("public") is True or value.get("is_public") is True

                for key in (
                    "ip_address",
                    "ip",
                    "address",
                    "public_ip",
                    "public_ipv4",
                    "floating_ip",
                    "floating_ip_address",
                    "main_ip",
                    "ipv4",
                ):
                    ip_value = self._normalize_public_ipv4(value.get(key))
                    if not ip_value:
                        continue
                    if nested_preferred:
                        preferred_candidates.append(ip_value)
                    else:
                        fallback_candidates.append(ip_value)

                for child in value.values():
                    if isinstance(child, (dict, list, tuple)):
                        walk(child, nested_preferred)

            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item, is_preferred)

            else:
                ip_value = self._normalize_public_ipv4(value)
                if not ip_value:
                    return
                if is_preferred:
                    preferred_candidates.append(ip_value)
                else:
                    fallback_candidates.append(ip_value)

        walk(node, preferred)
        return preferred_candidates, fallback_candidates

    def _network_snapshot(self, reglet_data: dict) -> str:
        snapshot = {
            "keys": sorted(reglet_data.keys()) if isinstance(reglet_data, dict) else [],
            "status": reglet_data.get("status"),
            "state": reglet_data.get("state"),
            "networks": reglet_data.get("networks"),
            "interfaces": reglet_data.get("interfaces"),
            "network_interfaces": reglet_data.get("network_interfaces"),
            "public_ip": reglet_data.get("public_ip"),
            "public_ipv4": reglet_data.get("public_ipv4"),
            "floating_ip": reglet_data.get("floating_ip"),
            "floating_ips": reglet_data.get("floating_ips"),
            "ip_address": reglet_data.get("ip_address"),
            "ipv4": reglet_data.get("ipv4"),
            "v4": reglet_data.get("v4"),
            "addresses": reglet_data.get("addresses"),
            "ips": reglet_data.get("ips"),
            "access_ip_v4": reglet_data.get("access_ip_v4"),
        }
        try:
            return json.dumps({k: v for k, v in snapshot.items() if v is not None}, ensure_ascii=False, default=str)[:600]
        except Exception:
            return str(snapshot)[:600]

    def extract_public_ip(self, reglet_data: dict) -> str:
        if not isinstance(reglet_data, dict):
            return ""

        preferred_candidates = []
        fallback_candidates = []

        networks = reglet_data.get("networks")
        if isinstance(networks, dict):
            for key in ("public", "floating", "external", "v4", "ipv4", "v6", "ipv6"):
                if key in networks:
                    preferred, fallback = self._collect_public_ip_candidates(
                        networks[key],
                        preferred=key in {"public", "floating", "external"},
                    )
                    preferred_candidates.extend(preferred)
                    fallback_candidates.extend(fallback)
            preferred, fallback = self._collect_public_ip_candidates(networks)
            preferred_candidates.extend(preferred)
            fallback_candidates.extend(fallback)
        elif networks is not None:
            preferred, fallback = self._collect_public_ip_candidates(networks)
            preferred_candidates.extend(preferred)
            fallback_candidates.extend(fallback)

        for key in ("interfaces", "network_interfaces"):
            if key not in reglet_data:
                continue
            preferred, fallback = self._collect_public_ip_candidates(reglet_data[key])
            preferred_candidates.extend(preferred)
            fallback_candidates.extend(fallback)

        for key in (
            "v4",
            "ipv4",
            "v6",
            "ipv6",
            "ips",
            "ip_addresses",
            "addresses",
            "floating_ips",
            "public_network",
            "public_interface",
            "public_interfaces",
        ):
            if key not in reglet_data:
                continue
            preferred, fallback = self._collect_public_ip_candidates(
                reglet_data[key],
                preferred=key in {"floating_ips", "public_network", "public_interface", "public_interfaces"},
            )
            preferred_candidates.extend(preferred)
            fallback_candidates.extend(fallback)

        for key in (
            "public_ip",
            "public_ipv4",
            "floating_ip",
            "floating_ip_address",
            "main_ip",
            "access_ip_v4",
            "access_ip",
            "ip_address",
            "ipv4",
            "ip",
        ):
            ip_value = self._normalize_public_ipv4(reglet_data.get(key))
            if ip_value:
                return ip_value

        preferred, fallback = self._collect_public_ip_candidates(reglet_data)
        preferred_candidates.extend(preferred)
        fallback_candidates.extend(fallback)

        for ip_value in preferred_candidates + fallback_candidates:
            if ip_value:
                return ip_value

        return ""

    def _format_check_status(self, check_number: int, status: str, ip: str, stability_count: int) -> str:
        return (
            f"Проверка {check_number:02d}/40 | "
            f"статус: {status} | "
            f"IP: {ip} | "
            f"стабильность: {stability_count}/{self.stability_checks}"
        )

    def _format_check_waiting(self, check_number: int) -> str:
        return f"Проверка {check_number:02d}/40 | сервер еще не отвечает или уже удален"

    def _confirm_delete_current_server(self, server_id: int) -> bool:
        prompt = f"{C.YELLOW}[?]{C.RESET} Удалить инстанс {server_id}? [y/N]: "

        while True:
            try:
                answer = input(prompt).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return False

            if answer in ("", "n", "no", "н", "нет"):
                return False

            if answer in ("y", "yes", "д", "да"):
                return True

            print(f"{C.YELLOW}[!]{C.RESET} Ответьте y/yes/да или n/no/нет.")

    def _remove_pending_server(self, server_id: int):
        if server_id in self.pending_server_ids:
            self.pending_server_ids.remove(server_id)

    def _remember_pending_server(self, server_id: int, reason: str, reglet_data=None):
        if not server_id:
            return

        if server_id in self.pending_server_ids:
            print(f"{C.DIM}[~]{C.RESET} Инстанс {server_id} уже есть в отложенных проверках.")
            return

        self.pending_server_ids.append(server_id)
        print(f"{C.YELLOW}[~]{C.RESET} Инстанс {server_id} записан в отложенные проверки: {reason}")
        log.warning(
            f"Инстанс {server_id} записан в отложенные проверки: {reason}. Ответ API: {self._network_snapshot(reglet_data or {})}"
        )

    def _poll_pending_servers(self, upcoming_iteration: int):
        if not self.pending_server_ids:
            return

        print(
            f"{C.CYAN}[..]{C.RESET} Быстрый чек отложенных инстансов перед итерацией {upcoming_iteration} "
            f"({len(self.pending_server_ids)} шт.)"
        )

        for server_id in list(self.pending_server_ids):
            reglet = self.get_server_info(server_id)
            if reglet is None:
                print(f"{C.DIM}[pend {server_id}]{C.RESET} инстанс уже удален или недоступен, убираем из списка")
                log.info(f"Отложенный инстанс {server_id} больше не доступен, убран из списка")
                self._remove_pending_server(server_id)
                if self.current_server_id == server_id:
                    self.current_server_id = None
                continue

            status = reglet.get('status') or reglet.get('state') or reglet.get('power_state') or 'unknown'
            ip = self.extract_public_ip(reglet) or "(еще нет)"
            print(f"{C.DIM}[pend {server_id}]{C.RESET} статус: {C.YELLOW}{status:<7}{C.RESET} | IP: {C.BOLD}{ip}{C.RESET}")

            if status == 'archive':
                print(f"{C.DIM}[pend {server_id}]{C.RESET} инстанс уже в архиве, убираем из списка")
                log.info(f"Отложенный инстанс {server_id} в архиве, убран из списка")
                self._remove_pending_server(server_id)
                if self.current_server_id == server_id:
                    self.current_server_id = None
                continue

            if status != 'active' or ip == "(еще нет)":
                continue

            self._remove_pending_server(server_id)
            success = self.is_target_ip(ip)

            if success:
                self.stats["found"] += 1
                print(
                    f"{C.GREEN}{C.BOLD}[!!!] БИНГО из отложенных! Оставляем сервер {server_id} "
                    f"({self.stats['found']}/{self.max_success}){C.RESET}\n"
                )
                log.info(f"Отложенный инстанс {server_id} подошел по IP {ip}")
                self.notifier.send_success(ip, f"отложенный {server_id}")
                if self.current_server_id == server_id:
                    self.current_server_id = None
                if self.stats["found"] >= self.max_success:
                    return
                continue

            print(f"{C.YELLOW}[NO]{C.RESET} Отложенный инстанс {server_id} получил неподходящий IP, удаляем.")
            log.info(f"Отложенный инстанс {server_id} получил неподходящий IP {ip}, запускаем удаление")
            self.safe_delete(server_id)

    def get_server_info(self, server_id: int):
        url = f"{self.api_base_url}/{server_id}"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 404: return None
            resp.raise_for_status()
            return self._extract_reglet_object(resp.json())
        except requests.exceptions.RequestException as e:
            log.warning(f"Ошибка запроса информации о сервере {server_id}: {e}")
            return {}
        except ValueError as e:
            log.warning(f"Не удалось распарсить JSON сервера {server_id}: {e}")
            return {}

    def print_result_box(self, ip: str, attempt: int, is_success: bool):
        status_text = f"{C.GREEN}✔ Идеально подходит!{C.RESET}" if is_success else f"{C.RED}✖ Не тот регион/IP{C.RESET}"
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(f"\n{C.DIM}╔════════════════════════════════════════════════════╗{C.RESET}")
        print(f"{C.DIM}║{C.RESET}  {C.CYAN}💡 Текущий IP{C.RESET} : {C.BOLD}{ip:<31}{C.RESET}{C.DIM}║{C.RESET}")
        print(f"{C.DIM}║{C.RESET}  {C.CYAN}🔄 Попытка   {C.RESET} : {attempt:<31}{C.DIM}║{C.RESET}")
        print(f"{C.DIM}║{C.RESET}  {C.CYAN}📊 Статус    {C.RESET} : {status_text:<40}{C.DIM}║{C.RESET}")
        print(f"{C.DIM}║{C.RESET}  {C.CYAN}🕒 Время     {C.RESET} : {current_time:<31}{C.DIM}║{C.RESET}")
        print(f"{C.DIM}╚════════════════════════════════════════════════════╝{C.RESET}\n")

    def create_and_wait(self) -> dict:
        print(f"\n{C.BLUE}[>>]{C.RESET} Создание сервера...")
        log.info("Отправка запроса на создание сервера.")

        # Рандомизация имени сервера
        payload_to_send = copy.deepcopy(self.payload)
        random_name = generate_random_vm_name(self.config)
        if random_name != self.payload.get("name", "vm"):
            payload_to_send["name"] = random_name
            log.info(f"Случайное имя сервера: {random_name}")
            print(f"{C.DIM}[name]{C.RESET} Имя: {C.CYAN}{random_name}{C.RESET}")

        try:
            resp = self.session.post(self.api_base_url, json=payload_to_send, timeout=15)
            resp.raise_for_status()
            created_reglet = self._extract_reglet_object(resp.json())
            server_id = created_reglet.get('id')
            self.current_server_id = server_id
            self.stats["created"] += 1
            log.info(f"Сервер создан, ID: {server_id}")
        except Exception as e:
            self.current_server_id = None
            print(f"{C.RED}[ER]{C.RESET} Ошибка при создании: {e}")
            log.error(f"Ошибка создания сервера: {e}")
            return {}

        if not server_id: return {}

        spinner = Spinner(f"Начальное ожидание ({self.initial_wait} сек)... ")
        spinner.start()
        try:
            time.sleep(self.initial_wait)
        finally:
            spinner.stop()

        print(f"{C.GREEN}[OK]{C.RESET} Запуск проверки стабильности сервера (ID: {server_id})")

        stability_count = 0
        final_reglet = {}
        missing_ip_logged = False
        check_spinner = Spinner(
            "Запуск проверки состояния сервера...",
            spinner_chars=["◴", "◷", "◶", "◵"],
            interval=0.12,
        )
        check_spinner.start()

        try:
            for i in range(40):
                check_number = i + 1
                reglet = self.get_server_info(server_id)
                if not reglet:
                    check_spinner.update(self._format_check_waiting(check_number))
                    time.sleep(self.check_interval)
                    continue

                status = reglet.get('status') or reglet.get('state') or reglet.get('power_state') or 'unknown'
                ip = self.extract_public_ip(reglet) or "(еще нет)"
                next_stability_count = stability_count + 1 if status == 'active' and ip != "(еще нет)" else 0
                check_spinner.update(self._format_check_status(check_number, status, ip, next_stability_count))

                if status == 'active' and ip == "(еще нет)" and not missing_ip_logged:
                    check_spinner.stop()
                    print(f"{C.YELLOW}[dbg]{C.RESET} Ответ API по сети: {self._network_snapshot(reglet)}")
                    log.warning(
                        f"Сервер {server_id} active, но публичный IP не извлечен. Ответ API: {self._network_snapshot(reglet)}"
                    )
                    missing_ip_logged = True
                    check_spinner.start()
                    check_spinner.update(self._format_check_status(check_number, status, ip, next_stability_count))

                if status == 'active' and ip != "(еще нет)":
                    stability_count = next_stability_count
                    final_reglet = reglet
                    if stability_count >= self.stability_checks:
                        check_spinner.stop()
                        print(f"{C.GREEN}[OK]{C.RESET} Сервер стабилен! IP получен: {C.BOLD}{ip}{C.RESET}")
                        log.info(f"Сервер {server_id} стабилен на IP {ip}")
                        return final_reglet
                else:
                    stability_count = 0

                time.sleep(self.check_interval)
        finally:
            check_spinner.stop()

        print(f"{C.RED}[ER]{C.RESET} Сервер не стабилизировался за отведенное время.")
        log.warning(f"Сервер {server_id} не стабилизировался.")
        if not final_reglet and server_id:
            return {"id": server_id}
        return final_reglet

    def safe_delete(self, server_id: int):
        print(f"{C.YELLOW}[NO]{C.RESET} IP не подходит -> Запуск удаления.")
        print(f"{C.RED}[XX]{C.RESET} Удаление инстанса {server_id}...")
        log.info(f"Удаление сервера {server_id}")

        url = f"{self.api_base_url}/{server_id}"
        try:
            self.session.delete(url, timeout=10)
        except Exception as e:
            print(f"{C.RED}[ER]{C.RESET} Запрос на удаление не прошел: {e}")
            log.error(f"Ошибка запроса удаления {server_id}: {e}")

        spinner = Spinner("Ожидание полного удаления... ")
        spinner.start()

        deleted = False
        try:
            for i in range(30):
                reglet = self.get_server_info(server_id)
                if reglet is None:
                    deleted = True
                    break
                status = reglet.get('status', 'unknown')
                locked = reglet.get('locked', False)
                if status == 'archive' and not locked:
                    deleted = True
                    break
                time.sleep(self.check_interval)
        finally:
            spinner.stop()

        if deleted:
            print(f"{C.GREEN}[OK]{C.RESET} Сервер успешно удален!")
            self.stats["deleted"] += 1
            log.info(f"Сервер {server_id} удален.")
        else:
            print(f"{C.YELLOW}[!]{C.RESET} Сервер завис в удалении, продолжаем.")
            log.warning(f"Завис при удалении {server_id}")

        self.current_server_id = None

        print(f"{C.DIM}[sleep]{C.RESET} Отдыхаем {self.delete_wait} сек...")
        time.sleep(self.delete_wait)

    def print_dashboard(self):
        elapsed = time.time() - self.stats["start_time"]
        hr_time = get_beautiful_time(elapsed)
        print(f"\n{C.BOLD}{C.MAGENTA}=== ИТОГИ СЕССИИ ==={C.RESET}")
        print(f"⏱  Время в работе   : {C.CYAN}{hr_time}{C.RESET}")
        print(f"📦 Создано серверов : {C.CYAN}{self.stats['created']}{C.RESET}")
        print(f"🗑  Удалено серверов : {C.CYAN}{self.stats['deleted']}{C.RESET}")
        print(f"✅ Найдено целей    : {C.GREEN}{self.stats['found']}{C.RESET} / {self.max_success}")
        print(f"{C.MAGENTA}===================={C.RESET}\n")
        log.info(f"Сессия завершена. Создано: {self.stats['created']}, Удалено: {self.stats['deleted']}, Найдено: {self.stats['found']}")

    def run(self, show_banner: bool = True):
        if show_banner:
            print_ascii_art(animated=sys.stdout.isatty())
        print(f"{C.DIM}режим:{C.RESET} {C.BOLD}VM / Reglet API{C.RESET} | цель: {C.CYAN}{self.max_success}{C.RESET} сервер(ов)\n")
        log.info("Запуск цикла Roller'a")

        iteration = 1
        try:
            while self.stats["found"] < self.max_success:
                self._poll_pending_servers(iteration)
                if self.stats["found"] >= self.max_success:
                    break

                print(f"{C.BOLD}{C.CYAN}--- Итерация {iteration} ---{C.RESET}")
                log.info(f"Начало итерации {iteration}")

                reglet = self.create_and_wait()
                server_id = reglet.get('id')
                ip_address = self.extract_public_ip(reglet)

                if not server_id:
                    print(f"{C.YELLOW}[!] Сбой получения данных. Даем паузу и продолжаем.{C.RESET}\n")
                    iteration += 1
                    time.sleep(self.delete_wait)
                    continue

                if not ip_address:
                    print(
                        f"{C.YELLOW}[!]{C.RESET} Публичный IP не удалось определить. "
                        f"Записываем сервер и продолжаем создавать новые.\n"
                    )
                    self._remember_pending_server(
                        server_id,
                        "сервер не стабилизировался и не выдал публичный IP",
                        reglet,
                    )
                    iteration += 1
                    continue

                success = self.is_target_ip(ip_address)
                self.print_result_box(ip_address, iteration, success)

                if success:
                    self.stats["found"] += 1
                    print(f"{C.GREEN}{C.BOLD}[!!!] БИНГО! Оставляем сервер ({self.stats['found']}/{self.max_success}){C.RESET}\n")
                    log.info(f"Цель достигнута. IP {ip_address}")
                    self.notifier.send_success(ip_address, iteration)
                    self.current_server_id = None
                else:
                    self.safe_delete(server_id)

                # Рандомизация паузы между итерациями
                random_delay = get_random_iteration_delay(self.config)
                if random_delay > 0:
                    print_pause_banner(random_delay)
                    time.sleep(random_delay)

                iteration += 1

        except KeyboardInterrupt:
            self._handle_interrupt(confirm_before_delete=True)

        except Exception as e:
            print(f"\n{C.RED}Критическая ошибка: {e}{C.RESET}")
            log.error(f"Критическая ошибка: {e}")
            self._handle_interrupt(confirm_before_delete=False)

        self.print_dashboard()

    def _handle_interrupt(self, confirm_before_delete=False):
        print(f"\n\n{C.YELLOW}[!] ПОЛУЧЕН СИГНАЛ ПРЕРЫВАНИЯ (Ctrl+C)!{C.RESET}")
        log.warning("Получен сигнал прерывания (Ctrl+C).")
        if self.current_server_id:
            should_delete = True
            if confirm_before_delete:
                should_delete = self._confirm_delete_current_server(self.current_server_id)

            if should_delete:
                print(f"{C.RED}[!] Удаляем инстанс {self.current_server_id}...{C.RESET}")
                try:
                    self.session.delete(f"{self.api_base_url}/{self.current_server_id}", timeout=10)
                    print(f"{C.GREEN}✔ Инстанс отправлен в корзину.{C.RESET}")
                    log.info(f"Удален инстанс {self.current_server_id} после остановки")
                    self.stats["deleted"] += 1
                    self._remove_pending_server(self.current_server_id)
                    self.current_server_id = None
                except Exception as e:
                    print(f"{C.RED}✖ Не удалось удалить: {e}{C.RESET}")
            else:
                print(f"{C.GREEN}✔ Оставляем инстанс {self.current_server_id} без удаления.{C.RESET}")
                log.info(f"Инстанс {self.current_server_id} оставлен после остановки пользователем")
        else:
            if self.pending_server_ids:
                pending_ids = ", ".join(str(server_id) for server_id in self.pending_server_ids)
                print(f"{C.GREEN}✔ Активный инстанс не выбран. Отложенные инстансы оставлены без изменений: {pending_ids}{C.RESET}")
            else:
                print(f"{C.GREEN}✔ Нет зависших инстансов.{C.RESET}")

# ==========================================
#                   ЗАПУСК
# ==========================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Reg.Ru Roller: VM (API) или Floating IP (cookie + GraphQL)"
    )
    parser.add_argument("--config", type=str, default="config.json", help="Путь к config.json")
    parser.add_argument("--max", type=int, help="Переопределить max_success (только VM)")
    parser.add_argument(
        "--mode",
        choices=("vm", "floating"),
        default="vm",
        help="С --no-menu: какой роллер запустить (по умолчанию vm)",
    )
    parser.add_argument("--no-menu", action="store_true", help="Без меню — сразу роллер (--mode)")
    return parser.parse_args()


def run_mode_hub_loop(cfg_manager: ConfigManager, config: dict) -> None:
    """Двухрежимный хаб: VM и Floating IP не смешивают пункты меню."""
    hub_labels = [
        "VM — создание и удаление reglet (API Bearer)",
        "Floating IP — cookie и GraphQL (без виртуалок)",
        "Выход",
    ]
    clear_before_hub = False
    while True:
        try:
            idx = arrow_pick_menu(
                "Reg.Ru Roller · хаб",
                hub_labels,
                subtitle=cfg_manager.config_file,
                clear_before=clear_before_hub,
            )
        except EOFError:
            print(f"\n{C.YELLOW}[i]{C.RESET} EOF — выход.")
            return

        if idx == 2:
            print(f"\n{C.DIM}Пока.{C.RESET}")
            return
        if idx == 0:
            menu = InteractiveMenu(cfg_manager, config)
            action = menu.run()
            config = menu.config
            cfg_manager.config = config
            if action == "run":
                RegruRoller(config).run(show_banner=False)
            elif action == "exit":
                return
            clear_before_hub = True
            continue
        if idx == 1:
            fmenu = FloatingCookieMenu(cfg_manager, config)
            action = fmenu.run()
            config = fmenu.config
            cfg_manager.config = config
            if action == "run":
                FloatingIpRoller(_floating_effective_config(config), full_config=config).run(show_banner=False)
            elif action == "exit":
                return
            clear_before_hub = True
            continue


def main():
    args = parse_args()
    cfg_manager = ConfigManager(args.config)
    config = copy.deepcopy(cfg_manager.config)

    if args.max is not None:
        config["max_success"] = args.max

    tty = sys.stdin.isatty() and sys.stdout.isatty()
    use_hub = not args.no_menu and sys.stdin.isatty()

    print_ascii_art(animated=tty)

    if use_hub:
        run_mode_hub_loop(cfg_manager, config)
        return

    if args.mode == "floating":
        FloatingIpRoller(_floating_effective_config(config), full_config=config).run(show_banner=False)
    else:
        RegruRoller(config).run(show_banner=False)


if __name__ == "__main__":
    main()
