

```
                                               ____                                             
   ________  ____ _  _______  __   _________  / / /__  _____            
  / ___/ _ \/ __ `/ / ___/ / / /  / ___/ __ \/ / / _ \/ ___/                 ❤️ t.me/bummychannel
 / /  /  __/ /_/ / / /  / /_/ /  / /  / /_/ / / /  __/ /                     с любовью к сообществу
/_/   \___/\__, (_)_/   \__,_/  /_/   \____/_/_/\___/_/                      при поддержке kotletker/willixirr
          /____/                                                                              🡔 discord 🡕
```
<div align="center">
  
**ReGRU Roller** — CLI-инструмент для REG.RU CloudVPS: подбор публичного IPv4 под ваши подсети двумя способами — через **API виртуальных машин** или через **плавающие IP (GraphQL + cookie)**.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![PyPI requests](https://img.shields.io/badge/dependency-requests-008080?style=flat)](https://pypi.org/project/requests/)
[![GitHub ip-roller](https://img.shields.io/badge/GitHub-ip--roller-181717?style=flat&logo=github)](https://github.com/bUmmy1337/ip-roller)

Исходники и обсуждения: **[github.com/bUmmy1337/ip-roller](https://github.com/bUmmy1337/ip-roller)**.

</div>

---

## Содержание

1. [Возможности](#возможности)
2. [Требования и установка](#требования-и-установка)
3. [Быстрый старт](#быстрый-старт)
4. [Запуск через Bash и curl](#запуск-через-bash-и-curl)
5. [Интерфейс: хаб и меню](#интерфейс-хаб-и-меню)
6. [Режим VM (Reglet API)](#режим-vm-reglet-api)
7. [Режим Floating IP (cookie + GraphQL)](#режим-floating-ip-cookie--graphql)
8. [Как получить Cookie для Floating IP](#как-получить-cookie-для-floating-ip)
9. [Структура `config.json`](#структура-configjson)
10. [Аргументы командной строки](#аргументы-командной-строки)
11. [Логи и уведомления](#логи-и-уведомления)
12. [Остановка и Ctrl+C](#остановка-и-ctrlc)
13. [Частые проблемы](#частые-проблемы)

---

## Возможности

| Область | Описание |
|--------|----------|
| **Два режима** | **VM** — создание/удаление reglet по Bearer API. **Floating IP** — выпуск и снятие плавающих адресов через панель `cloud.reg.ru` (GraphQL), без поднятия виртуалок. |
| **Хаб** | Одно стартовое меню выбора режима; настройки VM и Floating разведены по разным подменю. |
| **Навигация** | В списках действий — **стрелки ↑↓**, **Enter** — выбор, **Home/End** — к началу/концу списка; рамка и подсказки в терминале. |
| **Подсети** | Общий список `target_subnets` для обоих режимов (CIDR IPv4). |
| **Уведомления** | Telegram и Discord при успехе; для Floating — опциональный **heartbeat** в Telegram/Discord. |
| **Логи** | `roller.log` — VM и общие события; при необходимости смотрите также вывод в консоль. |
| **Конфиг** | Один `config.json`: API, параметры сервера, блок `floating_roll`, уведомления. |

---

## Требования и установка

- **Python** 3.10 или новее  
- Пакет **`requests`**

```bash
pip install requests
```

Клонирование репозитория (или распаковка архива) — перейдите в каталог проекта, где лежат `main.py` и `config.json`.

---

## Быстрый старт

1. Откройте **`config.json`**.  
2. Для режима **VM**: укажите рабочий **`api_token`**, при необходимости поправьте **`api_base_url`** и **`server_payload`**.  
3. Для режима **Floating IP**: заполните **`floating_roll`** (см. [ниже](#режим-floating-ip-cookie--graphql) и [Cookie](#как-получить-cookie-для-floating-ip)).  
4. Проверьте **`target_subnets`** и тайминги.  
5. Запуск:

```bash
# Windows (лаунчер Python)
py main.py

# Linux / macOS / Git Bash
python3 main.py
```

По умолчанию откроется **интерактивный хаб** (ASCII-баннер и выбор режима). Дальше — подменю выбранного режима.

---

## Запуск через Bash и curl

### Вариант A — в один заход (`curl` \| `bash`)

Официальный **raw**-скрипт (ветка `main`; в корне репозитория — [`regru_roller.sh`](https://github.com/bUmmy1337/ip-roller/blob/main/regru_roller.sh)):

```bash
curl -fsSL "https://raw.githubusercontent.com/bUmmy1337/ip-roller/main/regru_roller.sh" | bash -s -- --help
```

При запуске **из pipe** скрипт сам клонирует **[bUmmy1337/ip-roller](https://github.com/bUmmy1337/ip-roller)** в `~/regru_roller`, если рядом нет `main.py`, затем ставит `requests` и вызывает `main.py`.

> **Важно:** `curl | bash` используйте только для доверенного URL. Своё зеркало — подставьте свой raw-адрес.

Примеры с аргументами (пробрасываются в `main.py`):

```bash
# Интерактивный хаб
curl -fsSL "https://raw.githubusercontent.com/bUmmy1337/ip-roller/main/regru_roller.sh" | bash

# Сразу VM-роллер без меню
curl -fsSL "https://raw.githubusercontent.com/bUmmy1337/ip-roller/main/regru_roller.sh" | bash -s -- --no-menu

# Сразу Floating IP без меню
curl -fsSL "https://raw.githubusercontent.com/bUmmy1337/ip-roller/main/regru_roller.sh" | bash -s -- --no-menu --mode floating

# Свой конфиг после клона в ~/regru_roller
curl -fsSL "https://raw.githubusercontent.com/bUmmy1337/ip-roller/main/regru_roller.sh" | bash -s -- --config "$HOME/regru_roller/config.json"
```

Если рядом со скриптом **нет** `main.py`, проект подтягивается через **`REGRU_ROLLER_GIT_URL`** / **`REGRU_ROLLER_ZIP_URL`** (или автоматически при pipe — см. таблицу):

| Переменная | Назначение |
|------------|------------|
| `REGRU_ROLLER_GIT_URL` | URL репозитория для **`git clone --depth 1`** (нужен `git` в PATH). Если не задан и скрипт из **pipe**, по умолчанию используется **`https://github.com/bUmmy1337/ip-roller.git`**. |
| `REGRU_ROLLER_ZIP_URL` | Прямая ссылка на **ZIP** в формате GitHub (*Download ZIP*); нужен `unzip`. |
| `REGRU_ROLLER_HOME` | Куда клонировать / распаковать (по умолчанию **`~/regru_roller`**). |
| `DEFAULT_REGRU_ROLLER_GIT` | Переопределить URL «дефолтного» клона для pipe-запуска (редко нужно). |
| `REGRU_ROLLER_SKIP_PIP=1` | Не вызывать `pip install --user requests` после установки. |

Пример с **явным** указанием репозитория (форк или другая ветка через свой URL):

```bash
export REGRU_ROLLER_GIT_URL='https://github.com/YOU/fork.git'
curl -fsSL "https://raw.githubusercontent.com/bUmmy1337/ip-roller/main/regru_roller.sh" | bash
```

Пример с ZIP-архивом ветки `main`:

```bash
export REGRU_ROLLER_ZIP_URL='https://github.com/bUmmy1337/ip-roller/archive/refs/heads/main.zip'
curl -fsSL "https://raw.githubusercontent.com/bUmmy1337/ip-roller/main/regru_roller.sh" | bash
```

Если каталог `REGRU_ROLLER_HOME` уже содержит **git-клон**, при следующем запуске выполняется **`git pull --ff-only`** (обновление).

### Вариант B — сначала файл, потом запуск

```bash
curl -fsSL "https://raw.githubusercontent.com/bUmmy1337/ip-roller/main/regru_roller.sh" -o regru_roller.sh
chmod +x regru_roller.sh
cd /путь/к/папке/с/main.py   # или: export REGRU_ROLLER_GIT_URL=… и запуск из любой папки
./regru_roller.sh
```

### Локально (без curl)

```bash
chmod +x regru_roller.sh
./regru_roller.sh                 # хаб
./regru_roller.sh --no-menu       # VM
./regru_roller.sh --no-menu --mode floating
```

На **Windows** без Bash можно по-прежнему использовать **`py main.py`** с теми же аргументами.

---

## Интерфейс: хаб и меню

1. После запуска показывается **хаб**: выбор **VM**, **Floating IP** или **Выход**.  
2. Первый показ хаба идёт **под ASCII-баннером**; при возврате из подменю экран **очищается**, чтобы не «наслаивались» старые меню.  
3. Во всех списках пунктов: **↑ / ↓** — перемещение, **Enter** — подтверждение, **Home / End** — к первому/последнему пункту.  
4. В подменю **VM** и **Floating** есть пункт **«Назад в хаб»** и **«Выход из программы»**.

---

## Режим VM (Reglet API)

- Создаёт сервер с параметрами из **`server_payload`** (образ, регион, размер, флаги `floating_ip`, `backups` и т.д.).  
- Ждёт стабилизации и извлекает **публичный IPv4** из ответов API (несколько вариантов структуры JSON).  
- Если IP попадает в **`target_subnets`** — инстанс **оставляется** (до достижения **`max_success`**).  
- Если не попадает — инстанс **удаляется**, пауза **`delete_wait`**.  
- «Зависшие» случаи (нет IP после таймаута проверок) попадают в **отложенные**; перед каждой новой итерацией выполняется быстрый повторный опрос.

Подробнее о поведении отложенных инстансов см. в разделе [логики](#как-работает-vm-роллер) ниже.

---

## Режим Floating IP (cookie + GraphQL)

- Работает через **сессию браузера** `cloud.reg.ru`: в конфиге задаётся полная строка **Cookie** и **`service_id`**.  
- Скрипт обновляет JWT (`login.reg.ru/refresh`), получает краткоживущий **Bearer** (`subscription_tokens`), вызывает **GraphQL** создания/списка/удаления плавающих IP.  
- Новый адрес проверяется на вхождение в **`target_subnets`**; неподходящие IP снимаются; периодически выполняется **очистка** «лишних» плавающих IP на аккаунте (см. тайминги в `floating_roll.timings`).  
- **Telegram / Discord** берутся из общего блока **`notifications`**; для heartbeat используется **`heartbeat_interval_min`** (минуты, `0` — выкл).

Устаревший отдельный файл **`floating_ip_roller.py`** не используйте — вся логика в **`main.py`**.

---

## Как получить Cookie для Floating IP

Нужна **одна строка Cookie**, как в заголовке запроса из браузера (начинается с **`regru_utr=`** и по смыслу содержит сессию; в конце цепочки обычно фигурирует **`jwt_refresh`** — это нормальный признак актуальной связки куков).

### Пошагово (Chrome / Edge; для Firefox шаги аналогичны)

1. Откройте **[https://cloud.reg.ru](https://cloud.reg.ru)** и войдите в аккаунт.  
2. Откройте **DevTools** (**F12**) → вкладка **Network** (Сеть).  
3. Включите запись, при необходимости обновите страницу или перейдите по разделам панели.  
4. В списке запросов найдите запрос с именем вроде **`refresh`** (URL содержит **`login.reg.ru/refresh`** или похожий refresh-эндпоинт авторизации).  
5. Выберите этот запрос → панель **Headers** (Заголовки).  
6. Прокрутите до раздела **Request Headers** → поле **`Cookie`**.  
7. Скопируйте **значение целиком** — длинную строку, которая **начинается с `regru_utr=`** и включает все пары `имя=значение` через **`; `**.  
8. Вставьте строку в **`config.json`** → **`floating_roll`** → **`cookie`** (или через меню Floating → пункт Cookie).

> **Подсказка:** внизу длинной строки Cookie часто видны фрагменты вроде **`jwt_refresh=...`**. Если такого нет, сессия могла быть неполной — повторите вход и снова снимите Cookie с запроса **`refresh`**.

> **Не публикуйте** эту строку в чатах и репозиториях: по ней возможен доступ к вашей учётной записи в облаке.

---

## Структура `config.json`

Минимальный ориентир (значения замените своими):

```json
{
    "api_token": "REG_RU_TOKEN",
    "api_base_url": "https://api.cloudvps.reg.ru/v1/reglets",
    "server_payload": {
        "backups": false,
        "floating_ip": true,
        "image": "ubuntu-18-04-amd64",
        "name": "vm",
        "region_slug": "openstack-msk1",
        "size": "c2-m2-d10-base"
    },
    "target_subnets": [
        "79.174.91.0/24",
        "79.174.92.0/24"
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
        "discord_webhook_url": "",
        "heartbeat_interval_min": 0
    },
    "floating_roll": {
        "cookie": "regru_utr=...; ... jwt_refresh=...",
        "service_id": "",
        "region": "openstack-msk1",
        "timings": {
            "initial_wait": 8,
            "check_interval": 3,
            "max_checks": 20,
            "delete_wait": 5,
            "cleanup_check_interval": 50
        }
    }
}
```

### Поля кратко

| Поле | Назначение |
|------|------------|
| `api_token` / `api_base_url` | Доступ к **CloudVPS API** для режима VM. |
| `server_payload` | Тело запроса создания reglet. |
| `target_subnets` | Целевые **IPv4-подсети** (CIDR) для **обоих** режимов. |
| `max_success` | Сколько «удачных» **VM** остановить (режим Floating — одиночный цикл до первого подходящего IP). |
| `timings` | Ожидания и интервалы для **VM** (`initial_wait`, `check_interval`, `stability_checks`, `delete_wait`). |
| `notifications` | Telegram / Discord; **`heartbeat_interval_min`** — только для Floating (0 = выключено). |
| `floating_roll.cookie` | Полная строка **Cookie** с `cloud.reg.ru`. |
| `floating_roll.service_id` | ID услуги (виден в запросах `subscription_tokens`, числовой идентификатор). |
| `floating_roll.region` | Регион плавающих IP (например `openstack-msk1`). |
| `floating_roll.timings` | Ожидания и лимиты для **Floating** (в т.ч. `cleanup_check_interval`). |

Изменения из меню сохраняются в файл только после пункта **«Сохранить config.json»** (или аналога в подменю Floating).

---

## Как работает VM-роллер

1. Создаётся сервер через API.  
2. Пауза **`initial_wait`**.  
3. Периодические проверки с шагом **`check_interval`**; для «стабильности» нужно **`stability_checks`** успешных подряд.  
4. Если публичный IPv4 есть и подходит по подсетям — сервер остаётся; иначе — удаление и **`delete_wait`**.  
5. Если IP так и не извлечён в лимите проверок — ID уходит в **отложенные**; перед следующей итерацией выполняется повторный опрос отложенных.

**Отложенные:** при появлении подходящего IP засчитывается успех; при неподходящем — удаление; при отсутствии IP — остаются в списке до следующего чека.

---

## Аргументы командной строки

| Аргумент | Описание |
|----------|----------|
| `--config ПУТЬ` | Файл конфигурации (по умолчанию `config.json`). |
| `--no-menu` | Без хаба/меню — сразу запуск роллера. |
| `--mode vm` | С `--no-menu`: режим **VM** (значение по умолчанию). |
| `--mode floating` | С `--no-menu`: режим **Floating IP**. |
| `--max N` | Переопределить **`max_success`** (только для VM). |

Примеры:

```bash
py main.py --no-menu
py main.py --no-menu --mode floating
py main.py --config ./my_config.json --max 2
```

---

## Логи и уведомления

| Файл / канал | Содержимое |
|--------------|------------|
| **`roller.log`** | Создание/удаление VM, ошибки API, итерации, отложенные инстансы, важные сообщения Floating. |
| **Telegram / Discord** | Уведомление при успешном подборе IP (оба режима используют общие поля токена и webhook). |
| **Heartbeat** | Только Floating: периодические «пульсы», если задан `heartbeat_interval_min` > 0 и настроен хотя бы один канал. |

---

## Остановка и Ctrl+C

- **VM:** при **Ctrl+C** скрипт спрашивает, удалять ли **текущий** активный инстанс. Отложенные при этом **не трогаются** автоматически.  
- **Floating IP:** при прерывании можно выбрать удаление **текущего** плавающего IP или оставить его.

---

## Частые проблемы

### `401 Unauthorized` (режим VM)

Проверьте **`api_token`**, срок действия и права доступа к CloudVPS API.

### IP всегда «ещё нет» (VM)

Ответ API может отличаться по схеме; скрипт перебирает варианты. Инстанс уйдёт в **отложенные** и будет перепроверяться. Смотрите **`roller.log`** и отладочные строки в консоли.

### Floating: ошибки GraphQL / «JWT»

Обновите **`floating_roll.cookie`** из браузера (запрос **`refresh`**, полный **`Cookie`** с **`regru_utr=`**). Проверьте **`service_id`** и **`region`**.

### Слишком много инстансов в облаке

Если много серверов попало в отложенные и не удалены — контролируйте лог и панель REG.RU.

---

<div align="center">

**ReGRU Roller** · REG.RU CloudVPS

</div>
