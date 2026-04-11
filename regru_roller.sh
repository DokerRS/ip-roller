#!/usr/bin/env bash
# ReGRU Roller — установка (при необходимости) и запуск main.py
#
# Локально (уже клонировали репозиторий):
#   chmod +x regru_roller.sh && ./regru_roller.sh
#
# Одной командой (скрипт из pipe → клон в ~/regru_roller, см. DEFAULT ниже):
#   curl -fsSL 'https://raw.githubusercontent.com/bUmmy1337/ip-roller/main/regru_roller.sh' | bash
#
# Свой репозиторий / форк:
#   export REGRU_ROLLER_GIT_URL='https://github.com/USER/fork.git'
#   curl -fsSL 'https://…/regru_roller.sh' | bash
#
# Каталог установки (по умолчанию ~/regru_roller):
#   export REGRU_ROLLER_HOME="$HOME/regru_roller"
#
# Вместо git — ZIP с GitHub («Code → Download ZIP»):
#   export REGRU_ROLLER_ZIP_URL='https://github.com/bUmmy1337/ip-roller/archive/refs/heads/main.zip'
#   curl -fsSL 'https://raw.githubusercontent.com/bUmmy1337/ip-roller/main/regru_roller.sh' | bash
#
# Примеры аргументов для main.py:
#   ./regru_roller.sh --no-menu
#   ./regru_roller.sh --no-menu --mode floating
#
set -euo pipefail

REGRU_ROLLER_HOME="${REGRU_ROLLER_HOME:-${HOME}/regru_roller}"
REGRU_ROLLER_GIT_URL="${REGRU_ROLLER_GIT_URL:-}"
REGRU_ROLLER_ZIP_URL="${REGRU_ROLLER_ZIP_URL:-}"
REGRU_ROLLER_SKIP_PIP="${REGRU_ROLLER_SKIP_PIP:-0}"
# Репозиторий по умолчанию, если скрипт запущен из pipe (curl | bash) и main.py ещё нет
DEFAULT_REGRU_ROLLER_GIT="${DEFAULT_REGRU_ROLLER_GIT:-https://github.com/bUmmy1337/ip-roller.git}"

_script_path() {
  # При «curl | bash» часто $0 = «bash», а BASH_SOURCE указывает на /dev/fd/N
  if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
    printf '%s' "${BASH_SOURCE[0]}"
  else
    printf '%s' "${0:-}"
  fi
}

_script_dir() {
  local p
  p="$(_script_path)"
  if [[ "$p" == "-" ]] || [[ "$p" == /dev/fd/* ]] || [[ "$p" == /proc/self/fd/* ]]; then
    printf '%s' ""
    return 0
  fi
  cd "$(dirname "$p")" && pwd
}

_is_streamed_script() {
  local p
  p="$(_script_path)"
  [[ "$p" == "-" ]] || [[ "$p" == /dev/fd/* ]] || [[ "$p" == /proc/self/fd/* ]]
}

_have_main_py() {
  [[ -n "${1:-}" && -f "${1}/main.py" ]]
}

_run_pip_requests() {
  [[ "$REGRU_ROLLER_SKIP_PIP" == "1" ]] && return 0
  if command -v python3 >/dev/null 2>&1; then
    python3 -m pip install --user -q requests 2>/dev/null || true
  elif command -v python >/dev/null 2>&1; then
    python -m pip install --user -q requests 2>/dev/null || true
  fi
}

_install_from_git() {
  local url="$1" dest="$2"
  if ! command -v git >/dev/null 2>&1; then
    echo "regru_roller: нужен git (apt install git / brew install git)." >&2
    return 1
  fi
  if [[ -d "${dest}/.git" ]]; then
    echo "regru_roller: обновляю репозиторий в ${dest} …"
    git -C "$dest" pull --ff-only --depth 1 2>/dev/null || git -C "$dest" pull --ff-only || true
    return 0
  fi
  if [[ -e "$dest" ]]; then
    echo "regru_roller: каталог ${dest} уже существует, но это не git-клон (нет .git). Удалите его или задайте другой REGRU_ROLLER_HOME." >&2
    return 1
  fi
  echo "regru_roller: клонирую ${url} → ${dest} …"
  git clone --depth 1 "$url" "$dest"
}

_install_from_zip() {
  local url="$1" dest="$2"
  local tmp inner
  if ! command -v unzip >/dev/null 2>&1; then
    echo "regru_roller: для ZIP нужен unzip (apt install unzip)." >&2
    return 1
  fi
  tmp="$(mktemp -d)" || return 1
  echo "regru_roller: скачиваю архив …"
  if ! curl -fsSL "$url" -o "${tmp}/src.zip"; then
    rm -rf "$tmp"
    return 1
  fi
  if ! unzip -q "${tmp}/src.zip" -d "${tmp}/extract"; then
    rm -rf "$tmp"
    return 1
  fi
  inner="$(find "${tmp}/extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
  if [[ -z "$inner" || ! -f "${inner}/main.py" ]]; then
    echo "regru_roller: в архиве не найден каталог с main.py (ожидается структура как у GitHub ZIP)." >&2
    rm -rf "$tmp"
    return 1
  fi
  if [[ -e "$dest" ]]; then
    echo "regru_roller: каталог ${dest} уже существует. Удалите его или задайте другой REGRU_ROLLER_HOME." >&2
    rm -rf "$tmp"
    return 1
  fi
  mv "$inner" "$dest"
  rm -rf "$tmp"
  echo "regru_roller: проект распакован в ${dest}"
}

resolve_project_root() {
  local sd candidate
  sd="$(_script_dir)"
  if [[ -n "$sd" ]] && _have_main_py "$sd"; then
    printf '%s' "$sd"
    return 0
  fi
  if _have_main_py "$REGRU_ROLLER_HOME"; then
    printf '%s' "$REGRU_ROLLER_HOME"
    return 0
  fi
  candidate="$(pwd)"
  if _have_main_py "$candidate"; then
    printf '%s' "$candidate"
    return 0
  fi
  printf '%s' ""
  return 1
}

if [[ -z "$REGRU_ROLLER_GIT_URL" && -z "$REGRU_ROLLER_ZIP_URL" ]] && _is_streamed_script; then
  REGRU_ROLLER_GIT_URL="$DEFAULT_REGRU_ROLLER_GIT"
fi

ROOT="$(resolve_project_root || true)"

if ! _have_main_py "$ROOT"; then
  if [[ -n "$REGRU_ROLLER_GIT_URL" ]]; then
    _install_from_git "$REGRU_ROLLER_GIT_URL" "$REGRU_ROLLER_HOME"
    ROOT="$REGRU_ROLLER_HOME"
  elif [[ -n "$REGRU_ROLLER_ZIP_URL" ]]; then
    _install_from_zip "$REGRU_ROLLER_ZIP_URL" "$REGRU_ROLLER_HOME"
    ROOT="$REGRU_ROLLER_HOME"
  else
    echo "" >&2
    echo "regru_roller: не найден main.py рядом со скриптом и не задана установка." >&2
    echo "  Вариант 1 — клонировать репозиторий и повторить запуск:" >&2
    echo "    export REGRU_ROLLER_GIT_URL='https://github.com/bUmmy1337/ip-roller.git'" >&2
    echo "    curl -fsSL 'https://raw.githubusercontent.com/bUmmy1337/ip-roller/main/regru_roller.sh' | bash" >&2
    echo "  Вариант 2 — скачать ZIP (как «Download ZIP» на GitHub):" >&2
    echo "    export REGRU_ROLLER_ZIP_URL='https://github.com/bUmmy1337/ip-roller/archive/refs/heads/main.zip'" >&2
    echo "    curl -fsSL 'https://raw.githubusercontent.com/bUmmy1337/ip-roller/main/regru_roller.sh' | bash" >&2
    echo "  Каталог установки по умолчанию: ${REGRU_ROLLER_HOME} (переопределите REGRU_ROLLER_HOME при необходимости)." >&2
    echo "  Пропуск pip: REGRU_ROLLER_SKIP_PIP=1" >&2
    echo "" >&2
    exit 1
  fi
fi

if ! _have_main_py "$ROOT"; then
  echo "regru_roller: после установки не найден ${ROOT}/main.py" >&2
  exit 1
fi

cd "$ROOT"
_run_pip_requests

if command -v python3 >/dev/null 2>&1; then
  exec python3 main.py "$@"
fi
if command -v python >/dev/null 2>&1; then
  exec python main.py "$@"
fi
echo "regru_roller: не найден python3/python в PATH" >&2
exit 1
