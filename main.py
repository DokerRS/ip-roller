import time
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
        "size": "c2-m2-d10-base"
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
    "notifications": {
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "discord_webhook_url": ""
    }
}

class ConfigManager:
    def __init__(self, config_file="config.json"):
        self.config_file = config_file
        self.config = self.load_config()

    def _merge_defaults(self, current, defaults):
        if not isinstance(current, dict):
            return copy.deepcopy(defaults)

        merged = copy.deepcopy(current)
        for key, value in defaults.items():
            if key not in merged:
                merged[key] = copy.deepcopy(value)
            elif isinstance(value, dict) and isinstance(merged[key], dict):
                merged[key] = self._merge_defaults(merged[key], value)

        return merged

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
        print(f"\n{C.BOLD}{C.MAGENTA}=== ТЕКУЩИЕ НАСТРОЙКИ ==={C.RESET}")
        print(f"Конфиг                : {self.config_manager.config_file}")
        print(f"Токен API             : {self._mask_secret(self.config.get('api_token', ''))}")
        print(f"API URL               : {self.config.get('api_base_url', '')}")
        print(f"Нужно серверов        : {self.config.get('max_success', 1)}")
        print(f"Подсети               : {', '.join(self.config.get('target_subnets', []))}")
        print(f"Имя сервера           : {payload.get('name', '')}")
        print(f"Регион                : {payload.get('region_slug', '')}")
        print(f"Размер                : {payload.get('size', '')}")
        print(f"Образ                 : {payload.get('image', '')}")
        print(f"Floating IP           : {payload.get('floating_ip', False)}")
        print(f"Backups               : {payload.get('backups', False)}")
        print(f"Начальное ожидание    : {timings.get('initial_wait', 0)} сек")
        print(f"Интервал проверки     : {timings.get('check_interval', 0)} сек")
        print(f"Проверок стабильности : {timings.get('stability_checks', 0)}")
        print(f"Пауза после удаления  : {timings.get('delete_wait', 0)} сек")
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
        payload["region_slug"] = self._prompt_text("Регион", payload.get("region_slug", "openstack-msk1"))
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

    def _print_menu(self):
        dirty_marker = f" {C.YELLOW}*есть несохраненные изменения*{C.RESET}" if self.is_dirty else ""
        print(f"\n{C.BOLD}{C.CYAN}=== ГЛАВНОЕ МЕНЮ ==={C.RESET}{dirty_marker}")
        print("1. Запустить роллер")
        print("2. Показать текущие настройки")
        print("3. Изменить количество целей")
        print("4. Изменить тайминги")
        print("5. Изменить параметры сервера")
        print("6. Изменить API настройки")
        print("7. Изменить подсети")
        print("8. Сохранить config.json")
        print("0. Выход")

    def run(self) -> bool:
        while True:
            self._print_menu()
            choice = self._read_choice("Выберите действие: ")

            if choice == "1":
                return True
            if choice == "2":
                self._show_settings()
                continue
            if choice == "3":
                self._edit_max_success()
                continue
            if choice == "4":
                self._edit_timings()
                continue
            if choice == "5":
                self._edit_server_payload()
                continue
            if choice == "6":
                self._edit_api_settings()
                continue
            if choice == "7":
                self._prompt_subnets()
                continue
            if choice == "8":
                self._save_config()
                continue
            if choice == "0":
                if self._confirm_exit():
                    return False
                continue

            print(f"{C.YELLOW}[!]{C.RESET} Неизвестный пункт меню.")

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
        self.thread = threading.Thread(target=self._spin)
        self.thread.daemon = True
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
        
        try:
            resp = self.session.post(self.api_base_url, json=self.payload, timeout=15)
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

    def run(self):
        print_ascii_art(animated=True)
        print(f"Цель: {self.max_success} серверов.\n")
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
    parser = argparse.ArgumentParser(description="Автоматический парсинг/рероллинг серверов reg.ru")
    parser.add_argument('--config', type=str, default='config.json', help='Путь к конфигурационному файлу')
    parser.add_argument('--max', type=int, help='Переопределить количество нужных серверов (max_success)')
    parser.add_argument('--no-menu', action='store_true', help='Запустить сразу, без интерактивного меню')
    return parser.parse_args()

def main():
    print_ascii_art(animated=True)
    
    args = parse_args()
    cfg_manager = ConfigManager(args.config)
    config = copy.deepcopy(cfg_manager.config)
    
    if args.max is not None:
        config["max_success"] = args.max

    use_menu = not args.no_menu and sys.stdin.isatty()
    if use_menu:
        menu = InteractiveMenu(cfg_manager, config)
        should_start = menu.run()
        if not should_start:
            print(f"{C.YELLOW}[i]{C.RESET} Выход без запуска.")
            return
        config = menu.config

    roller = RegruRoller(config)
    roller.run()

if __name__ == "__main__":
    main()