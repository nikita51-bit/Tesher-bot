from __future__ import annotations

import asyncio
import json
import os
import random
import re
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from dotenv import load_dotenv
from vkbottle import Bot, Callback, GroupEventType, Keyboard
from vkbottle.bot import Message, MessageEvent

from database import Database

ENV_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".env"
)

load_dotenv(ENV_FILE, override=True)

TOKEN = os.getenv("VK_GROUP_TOKEN", "").strip()

if not TOKEN or TOKEN == "PASTE_YOUR_COMMUNITY_TOKEN_HERE":
    raise RuntimeError(
        f"Не найден токен VK_GROUP_TOKEN. Проверь файл: {ENV_FILE}\n"
        "Убедись, что файл называется .env, а не .env.txt, "
        "и в нём указан настоящий токен сообщества."
    )

API_VERSION = os.getenv("VK_API_VERSION", "5.199")
API_BASE_URL = os.getenv("VK_API_BASE_URL", "https://api.vk.ru/method").strip().rstrip("/")
LEGACY_API_BASE_URL = "https://api.vk.com/method"
DB = Database(os.getenv("DB_PATH", "bot.db"))
bot = Bot(TOKEN)

LEVEL_NAMES = {
    0: "Пользователь",
    1: "Модератор",
    2: "Ст. Модератор",
    3: "Гл. Модератор",
    4: "Создатель",
}

# Commands may be remapped separately in each conference with /arangrules.
# A command absent from this map is unassigned until the creator assigns it.
DEFAULT_RULES: dict[str, int] = {
    "q": 0,
    "help": 0,
    "time": 1,
    "mute": 1,
    "unmute": 1,
    "pin": 1,
    "unpin": 1,
    "warns": 1,
    "warnlist": 1,
    "warn": 2,
    "unwarn": 2,
    "kick": 2,
    "admins": 2,
    "get": 2,
    "domain": 2,
    "domaindelete": 2,
    "searchdomain": 2,
    "ban": 3,
    "unban": 3,
    "banlist": 3,
    "comment": 3,
    "comments": 3,
    "arang": 3,
    "amode": 4,
    "arangrules": 4,
    "localcreate": 4,
    "localdelete": 4,
    "localjoin": 4,
    "localleave": 4,
    "nt": 2,
    "pm": 2,
    "execute": 4,
    "gc": 2,
    "localclear": 4,
    "lkick": 3,
    "lban": 3,
    "unlban": 3,
    "raspnew": 3,
    "rasppublic": 3,
    "raspedit": 3,
    "raspedittime": 3,
    "raspdelete": 3,
    "raspinfo": 3,
    "raspcycle": 3,
    "ls": 4,
    "restart": 4,
    "cmdplus": 4,
    "cmdminus": 4,
}

COMMAND_DESCRIPTIONS = {
    "q": "Добровольный выход из беседы с подтверждением и сбросом уровня.",
    "help": "Справка по уникальным командам выбранного уровня: /help 0–4.",
    "time": "Показывает текущее время Москвы.",
    "mute": "Запрещает отправку сообщений на заданное число минут; сообщения удаляются ботом.",
    "unmute": "Снимает мут с пользователя.",
    "pin": "Закрепляет сообщение, на которое ответили командой.",
    "unpin": "Открепляет закреплённое сообщение.",
    "warns": "Показывает активные предупреждения пользователя или список пользователей с предупреждениями.",
    "warnlist": "Показывает историю предупреждений постранично: /warnlist @пользователь [страница].",
    "warn": "Выдаёт устное предупреждение; каждые два устных конвертируются в одно основное.",
    "unwarn": "Снимает указанное число основных предупреждений; историю не удаляет.",
    "kick": "Исключает пользователя из этой беседы и сбрасывает его уровень.",
    "admins": "Показывает администраторов текущей беседы.",
    "get": "Показывает доступную статистику пользователя в боте и беседе.",
    "domain": "Добавляет один домен/тег пользователя.",
    "domaindelete": "Удаляет указанный домен/тег пользователя.",
    "searchdomain": "Ищет пользователей по сохранённому домену/тегу.",
    "ban": "Блокирует пользователя в текущей беседе; -1 означает перманентно.",
    "unban": "Снимает блокировку пользователя в текущей беседе.",
    "banlist": "Показывает историю блокировок постранично; доступна Главному модератору (3 уровень).",
    "comment": "Оставляет комментарий о пользователе внутри текущей локализации.",
    "comments": "Показывает комментарии о пользователе внутри текущей локализации постранично.",
    "arang": "Назначает уровень 0–3; суффикс -l применяет уровень во всех беседах локализации.",
    "nt": "/nt 0 текст — отправляет вызов участникам текущей конференции в ЛС; /nt 1 текст — участникам всей локализации в ЛС.",
    "pm": "Показывает локальные конференции и их ID; также отправляет сообщение по ID.",
    "execute": "Последовательно выполняет несколько команд; доступна Создателю (4 уровень).",
    "gc": "Показывает время работы бота, пинг VK API, базу данных и информацию о локализации.",
    "localclear": "Удаляет все локализации, связи бесед и локальные блокировки.",
    "amode": "Включает/выключает режим, в котором бот удаляет сообщения не-администраторов.",
    "arangrules": "Настраивает уровень доступа к командам в текущей беседе.",
    "localcreate": "Создаёт локализацию; текущая беседа становится главной.",
    "localdelete": "Удаляет локализацию; выполнить можно только в её главной беседе.",
    "localjoin": "Подключает текущую беседу к локализации.",
    "localleave": "Отключает текущую не-главную беседу от локализации.",
    "lkick": "Исключает пользователя из всех бесед текущей локализации.",
    "lban": "Блокирует пользователя во всех беседах текущей локализации.",
    "unlban": "Снимает локальную блокировку пользователя.",
    "raspnew": "Создаёт объявление. Формат: /raspnew Название | Описание (или /raspnew \"Название\" Описание).",
    "rasppublic": "Назначает публикацию: /rasppublic ID_конференции ID_объявления ДеньНедели ЧЧ:ММ [-c]. Суффикс -c включает еженедельный цикл.",
    "raspedit": "Изменяет описание объявления: /raspedit ID_объявления Новый текст объявления.",
    "raspedittime": "Изменяет расписание: /raspedittime ID_объявления ID_конференции ДеньНедели ЧЧ:ММ [-c].",
    "raspdelete": "Удаляет объявление и связанные с ним расписания: /raspdelete ID_объявления.",
    "raspinfo": "Показывает название, ID, описание и расписания объявления: /raspinfo ID_объявления.",
    "raspcycle": "Включает или выключает еженедельный цикл: /raspcycle ID_объявления ON/OFF.",
    "ls": "Отправляет личное сообщение упомянутому пользователю, только если текущая беседа подключена к локализации и адресат состоит хотя бы в одной её конференции: /ls @пользователь текст.",
    "restart": "Перезапускает бота.",
    "cmdplus": "Разрешает пользователю вызывать выбранную команду без обычного уровня доступа: /cmdplus @пользователь /команда.",
    "cmdminus": "Отзывает персональный доступ к команде: /cmdminus @пользователь /команда.",
}

DURATION_RE = re.compile(r"^(-1|\d+)([smhdсмчд]?)$", re.IGNORECASE)
MENTION_PATTERNS = [
    re.compile(r"\[id(\d+)\|[^\]]*\]", re.IGNORECASE),
    re.compile(r"@id(\d+)(?:\s*\([^)]*\))?", re.IGNORECASE),
    re.compile(r"(?<![\w])id(\d+)(?!\w)", re.IGNORECASE),
]
USERNAME_MENTION_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_.]{1,40})")
FLOOD_WINDOW = 10
FLOOD_LIMIT = 20
AUTO_MUTE_SECONDS = 15 * 60
OWNER_CACHE_SECONDS = 60
STARTED_AT = time.monotonic()
MOSCOW_TZ = timezone(timedelta(hours=3))
WEEKDAYS = {
    "понедельник": 0, "пн": 0, "monday": 0, "mon": 0,
    "вторник": 1, "вт": 1, "tuesday": 1, "tue": 1,
    "среда": 2, "ср": 2, "среду": 2, "wednesday": 2, "wed": 2,
    "четверг": 3, "чт": 3, "thursday": 3, "thu": 3,
    "пятница": 4, "пт": 4, "friday": 4, "fri": 4,
    "суббота": 5, "сб": 5, "saturday": 5, "sat": 5,
    "воскресенье": 6, "вс": 6, "sunday": 6, "sun": 6,
}
# Commands which must never be delegated to regular users; otherwise a chain of
# grants could become a privilege-escalation path.
NON_DELEGABLE_COMMANDS = {
    "cmdplus", "cmdminus", "restart", "execute", "arangrules", "arang",
    "amode", "localclear", "localcreate", "localdelete", "localjoin",
    "localleave", "ls",
}
FIXED_LEVEL_4_COMMANDS = {"ls", "restart", "cmdplus", "cmdminus", "arangrules"}


class VKAPIError(RuntimeError):
    def __init__(self, code: int | None, message: str) -> None:
        self.code = code
        super().__init__(f"VK API {code}: {message}" if code is not None else message)


class VKAPI:
    def __init__(self, token: str) -> None:
        self.token = token
        self.session: aiohttp.ClientSession | None = None
        self.base_url = API_BASE_URL

    async def start(self) -> None:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=18))

    async def close(self) -> None:
        if self.session is not None and not self.session.closed:
            await self.session.close()

    async def call(self, method: str, **params: Any) -> Any:
        if self.session is None or self.session.closed:
            await self.start()
        data = {key: value for key, value in params.items() if value is not None}
        data["access_token"] = self.token
        data["v"] = API_VERSION
        assert self.session is not None
        try:
            async with self.session.post(f"{self.base_url}/{method}", data=data) as response:
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            # VK announced the api.vk.ru migration. Keep a best-effort fallback
            # for networks where DNS/routing to that host is temporarily broken.
            if self.base_url == "https://api.vk.ru/method" and API_BASE_URL == self.base_url:
                try:
                    async with self.session.post(f"{LEGACY_API_BASE_URL}/{method}", data=data) as response:
                        payload = await response.json(content_type=None)
                    self.base_url = LEGACY_API_BASE_URL
                    print("[WARN] API api.vk.ru недоступен, временно используется совместимый api.vk.com")
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                    raise exc
            else:
                raise
        if "error" in payload:
            err = payload["error"]
            raise VKAPIError(err.get("error_code"), err.get("error_msg", "неизвестная ошибка"))
        return payload.get("response")


vk = VKAPI(TOKEN)
owner_cache: dict[int, tuple[float, int | None]] = {}
flood_windows: dict[tuple[int, int], deque[float]] = defaultdict(deque)
auto_mute_notice_at: dict[tuple[int, int], float] = {}


def now_ts() -> int:
    return int(time.time())


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{days} дн. {hours} ч. {minutes} мин. {seconds} сек."


def format_months(seconds: int) -> str:
    """Format an elapsed duration as full 30-day months plus remaining days."""
    days = max(0, int(seconds)) // 86400
    months, remainder_days = divmod(days, 30)

    def plural(value: int, one: str, few: str, many: str) -> str:
        value_abs = abs(value) % 100
        last = value_abs % 10
        if 11 <= value_abs <= 14:
            word = many
        elif last == 1:
            word = one
        elif 2 <= last <= 4:
            word = few
        else:
            word = many
        return f"{value} {word}"

    return f"{plural(months, 'месяц', 'месяца', 'месяцев')} {plural(remainder_days, 'день', 'дня', 'дней')}"


def parse_duration(value: str) -> int | None:
    value = value.strip().lower()
    match = DURATION_RE.fullmatch(value)
    if not match:
        return None
    number = int(match.group(1))
    if number == -1:
        return -1
    unit = match.group(2).lower()
    multiplier = {
        "": 60,
        "s": 1,
        "с": 1,
        "m": 60,
        "м": 60,
        "h": 3600,
        "ч": 3600,
        "d": 86400,
        "д": 86400,
    }.get(unit, 60)
    return number * multiplier


def get_field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def action_dict(message: Message) -> dict[str, Any] | None:
    action = get_field(message, "action")
    if action is None:
        return None
    if isinstance(action, dict):
        return action
    if hasattr(action, "model_dump"):
        return action.model_dump()
    if hasattr(action, "dict"):
        return action.dict()
    return {"type": get_field(action, "type"), "member_id": get_field(action, "member_id")}


def peer_to_chat_id(peer_id: int) -> int:
    if peer_id < 2_000_000_000:
        raise ValueError("Команда доступна только внутри групповой беседы VK.")
    return peer_id - 2_000_000_000


def level_of(peer_id: int, user_id: int) -> int:
    row = DB.fetchone("SELECT level FROM admins WHERE peer_id=? AND user_id=?", (peer_id, user_id))
    return int(row["level"]) if row else 0


def required_level(peer_id: int, command: str) -> int | None:
    # While linked, the main conference's explicit rule is authoritative.
    loc = localization_for_peer(peer_id)
    if loc and int(loc["main_peer_id"]) != peer_id:
        inherited = DB.fetchone(
            "SELECT level FROM command_rules WHERE peer_id=? AND command=?",
            (int(loc["main_peer_id"]), command),
        )
        if inherited:
            return None if int(inherited["level"]) == -1 else int(inherited["level"])
    row = DB.fetchone("SELECT level FROM command_rules WHERE peer_id=? AND command=?", (peer_id, command))
    if row:
        return None if int(row["level"]) == -1 else int(row["level"])
    return DEFAULT_RULES.get(command)


def set_admin_level(peer_id: int, user_id: int, level: int, granted_by: int | None) -> None:
    if level == 0:
        DB.execute(
            "INSERT INTO admins(peer_id,user_id,level,granted_by,granted_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(peer_id,user_id) DO UPDATE SET level=0,granted_by=excluded.granted_by,granted_at=excluded.granted_at",
            (peer_id, user_id, 0, granted_by, now_ts()),
        )
    else:
        DB.execute(
            "INSERT INTO admins(peer_id,user_id,level,granted_by,granted_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(peer_id,user_id) DO UPDATE SET level=excluded.level,granted_by=excluded.granted_by,granted_at=excluded.granted_at",
            (peer_id, user_id, level, granted_by, now_ts()),
        )


async def send(peer_id: int, text: str, keyboard: str | None = None) -> None:
    params: dict[str, Any] = {"peer_id": peer_id, "message": text[:3900], "random_id": random.randint(1, 2_000_000_000)}
    if keyboard:
        params["keyboard"] = keyboard
    await vk.call("messages.send", **params)


async def safe_send(peer_id: int, text: str, keyboard: str | None = None) -> None:
    try:
        await send(peer_id, text, keyboard)
    except Exception as exc:
        print(f"[WARN] Не удалось отправить сообщение в {peer_id}: {exc}")


async def send_private_message(user_id: int, text: str) -> None:
    """Send a direct message through the community token, propagating VK errors."""
    if user_id <= 0:
        raise ValueError("Для личного сообщения нужен положительный VK ID пользователя.")
    await vk.call(
        "messages.send",
        user_id=user_id,
        message=text[:3900],
        random_id=random.randint(1, 2_000_000_000),
    )


def first_free_local_public_id(conn: Any | None = None) -> int:
    """Return the smallest unused positive local conference ID."""
    connection = conn if conn is not None else DB.conn
    candidate = 1
    for row in connection.execute(
        "SELECT public_id FROM localization_chats WHERE public_id IS NOT NULL ORDER BY public_id"
    ).fetchall():
        public_id = int(row[0])
        if public_id == candidate:
            candidate += 1
        elif public_id > candidate:
            break
    return candidate


def parse_weekday(value: str) -> int | None:
    normalized = value.strip().casefold().rstrip(".")
    if normalized.isdigit():
        number = int(normalized)
        return number - 1 if 1 <= number <= 7 else None
    return WEEKDAYS.get(normalized)


def valid_hhmm(value: str) -> bool:
    return bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value.strip()))


async def kick_user(peer_id: int, user_id: int) -> None:
    chat_id = peer_to_chat_id(peer_id)
    try:
        await vk.call("messages.removeChatUser", chat_id=chat_id, member_id=user_id)
    except VKAPIError as first_error:
        # Older API wrappers/versions used user_id instead of member_id.
        try:
            await vk.call("messages.removeChatUser", chat_id=chat_id, user_id=user_id)
        except VKAPIError:
            raise first_error


def reset_member_role(peer_id: int, user_id: int, pending_return: bool = False) -> None:
    set_admin_level(peer_id, user_id, 0, None)
    row = DB.fetchone("SELECT * FROM memberships WHERE peer_id=? AND user_id=?", (peer_id, user_id))
    now = now_ts()
    if row:
        completed = int(row["completed_seconds"] or 0)
        start = row["session_start"]
        if start and row["active"]:
            completed += max(0, now - int(start))
        DB.execute(
            "UPDATE memberships SET active=0,session_start=NULL,completed_seconds=?,return_pending=? WHERE peer_id=? AND user_id=?",
            (completed, 1 if pending_return else 0, peer_id, user_id),
        )
    else:
        DB.execute(
            "INSERT INTO memberships(peer_id,user_id,first_join,last_join,session_start,completed_seconds,active,return_pending) "
            "VALUES(?,?,?,?,NULL,0,0,?)",
            (peer_id, user_id, now, now, 1 if pending_return else 0),
        )


def ensure_user(user_id: int) -> None:
    DB.execute("INSERT OR IGNORE INTO users(user_id,first_seen,message_count) VALUES(?,?,0)", (user_id, now_ts()))


def count_message(peer_id: int, user_id: int) -> None:
    ensure_user(user_id)
    DB.execute("UPDATE users SET message_count=message_count+1 WHERE user_id=?", (user_id,))
    now = now_ts()
    row = DB.fetchone("SELECT * FROM memberships WHERE peer_id=? AND user_id=?", (peer_id, user_id))
    if not row:
        DB.execute(
            "INSERT INTO memberships(peer_id,user_id,first_join,last_join,session_start,completed_seconds,invited_by,active) VALUES(?,?,?,?,?,0,NULL,1)",
            (peer_id, user_id, now, now, now),
        )
    elif not row["active"]:
        DB.execute(
            "UPDATE memberships SET last_join=?,session_start=?,active=1,first_join=COALESCE(first_join,?) WHERE peer_id=? AND user_id=?",
            (now, now, now, peer_id, user_id),
        )


async def get_members(peer_id: int) -> list[dict[str, Any]]:
    result = await vk.call("messages.getConversationMembers", peer_id=peer_id, extended=1, count=1000)
    if isinstance(result, dict):
        items = result.get("items", [])
        # Some clients expose conversation members in a nested response.
        return [dict(item) for item in items if isinstance(item, dict)]
    if isinstance(result, list):
        return [dict(item) for item in result if isinstance(item, dict)]
    return []


async def sync_owner(peer_id: int, force: bool = False) -> int | None:
    cached = owner_cache.get(peer_id)
    if not force and cached and time.time() - cached[0] < OWNER_CACHE_SECONDS:
        return cached[1]
    try:
        members = await get_members(peer_id)
    except Exception as exc:
        print(f"[WARN] Не удалось обновить состав беседы {peer_id}: {exc}")
        return DB.fetchone("SELECT owner_id FROM chat_state WHERE peer_id=?", (peer_id,))["owner_id"] if DB.fetchone("SELECT owner_id FROM chat_state WHERE peer_id=?", (peer_id,)) else None

    owner_id: int | None = None
    now = now_ts()
    for item in members:
        uid = int(item.get("member_id") or item.get("id") or 0)
        if uid <= 0:
            continue
        ensure_user(uid)
        join_date = int(item.get("join_date") or now)
        invited_by = item.get("invited_by")
        DB.execute(
            "INSERT INTO memberships(peer_id,user_id,first_join,last_join,session_start,completed_seconds,invited_by,active) "
            "VALUES(?,?,?,?,?,0,?,1) "
            "ON CONFLICT(peer_id,user_id) DO UPDATE SET first_join=COALESCE(memberships.first_join,excluded.first_join), "
            "last_join=COALESCE(memberships.last_join,excluded.last_join), "
            "session_start=CASE WHEN memberships.active=0 THEN COALESCE(memberships.session_start,excluded.session_start) ELSE memberships.session_start END, "
            "invited_by=COALESCE(memberships.invited_by,excluded.invited_by), active=1",
            (peer_id, uid, join_date, join_date, join_date, invited_by),
        )
        if bool(item.get("is_owner")):
            owner_id = uid
    # On some API responses the owner is provided separately.
    if owner_id is None:
        try:
            chat_data = await vk.call("messages.getConversationsById", peer_ids=peer_id, extended=1)
            if isinstance(chat_data, dict):
                for item in chat_data.get("items", []):
                    chat = item.get("chat_settings") or {}
                    candidate = chat.get("owner_id")
                    if candidate:
                        owner_id = int(candidate)
        except Exception:
            pass

    existing = DB.fetchone("SELECT owner_id FROM chat_state WHERE peer_id=?", (peer_id,))
    old_owner = int(existing["owner_id"]) if existing and existing["owner_id"] else None
    DB.execute("INSERT OR IGNORE INTO chat_state(peer_id,owner_id,amode,updated_at) VALUES(?,?,0,?)", (peer_id, owner_id, now))
    if owner_id is not None and owner_id != old_owner:
        with DB.transaction() as conn:
            if old_owner and old_owner != owner_id:
                conn.execute("DELETE FROM admins WHERE peer_id=? AND user_id=?", (peer_id, old_owner))
            conn.execute(
                "INSERT INTO admins(peer_id,user_id,level,granted_by,granted_at) VALUES(?,?,4,?,?) "
                "ON CONFLICT(peer_id,user_id) DO UPDATE SET level=4,granted_by=excluded.granted_by,granted_at=excluded.granted_at",
                (peer_id, owner_id, owner_id, now),
            )
            conn.execute("UPDATE chat_state SET owner_id=?,updated_at=? WHERE peer_id=?", (owner_id, now, peer_id))
    elif owner_id is not None:
        # Keep the owner at level 4 even after manual DB edits.
        set_admin_level(peer_id, owner_id, 4, owner_id)
    owner_cache[peer_id] = (time.time(), owner_id if owner_id is not None else old_owner)
    return owner_id if owner_id is not None else old_owner


async def profile_name(user_id: int) -> str:
    try:
        result = await vk.call("users.get", user_ids=user_id, fields="domain")
        if result and isinstance(result, list):
            user = result[0]
            return f"[id{user_id}|{user.get('first_name','')} {user.get('last_name','')}]".strip()
    except Exception:
        pass
    return f"[id{user_id}|Пользователь {user_id}]"


async def resolve_target(message: Message, text: str) -> tuple[int | None, str]:
    rest = text.strip()
    for pattern in MENTION_PATTERNS:
        match = pattern.search(rest)
        if match:
            target_id = int(match.group(1))
            rest = (rest[:match.start()] + " " + rest[match.end():]).strip()
            rest = re.sub(r"\s+", " ", rest)
            return target_id, rest
    reply = get_field(message, "reply_message")
    if reply is not None:
        target_id = int(get_field(reply, "from_id", 0) or 0)
        if target_id > 0:
            return target_id, rest
    username = USERNAME_MENTION_RE.search(rest)
    if username:
        try:
            result = await vk.call("users.get", user_ids=username.group(1))
            if result and isinstance(result, list):
                target_id = int(result[0]["id"])
                rest = (rest[:username.start()] + " " + rest[username.end():]).strip()
                return target_id, re.sub(r"\s+", " ", rest)
        except Exception:
            pass
    return None, rest


async def delete_message(message: Message) -> bool:
    peer_id = int(get_field(message, "peer_id", 0) or 0)
    cmid = get_field(message, "conversation_message_id")
    if not cmid:
        return False
    try:
        await vk.call("messages.delete", peer_id=peer_id, cmids=str(cmid), delete_for_all=1)
        return True
    except Exception as exc:
        print(f"[WARN] Не удалось удалить сообщение {peer_id}/{cmid}: {exc}")
        return False


def active_ban(peer_id: int, user_id: int) -> Any | None:
    row = DB.fetchone("SELECT * FROM bans WHERE peer_id=? AND user_id=?", (peer_id, user_id))
    if row and not row["permanent"] and row["until_ts"] and int(row["until_ts"]) <= now_ts():
        DB.execute("DELETE FROM bans WHERE peer_id=? AND user_id=?", (peer_id, user_id))
        return None
    return row


def active_mute(peer_id: int, user_id: int) -> Any | None:
    row = DB.fetchone("SELECT * FROM mutes WHERE peer_id=? AND user_id=?", (peer_id, user_id))
    if row and int(row["until_ts"]) <= now_ts():
        DB.execute("DELETE FROM mutes WHERE peer_id=? AND user_id=?", (peer_id, user_id))
        return None
    return row


def localization_for_peer(peer_id: int) -> Any | None:
    return DB.fetchone(
        "SELECT l.*,lc.is_main FROM localization_chats lc JOIN localizations l ON l.id=lc.localization_id WHERE lc.peer_id=?",
        (peer_id,),
    )


async def conference_public_id(peer_id: int) -> int | None:
    row = DB.fetchone("SELECT public_id FROM localization_chats WHERE peer_id=?", (peer_id,))
    return int(row["public_id"]) if row and row["public_id"] is not None else None


async def conference_titles(peer_ids: list[int]) -> dict[int, str]:
    """Fetch VK conference titles in batches, falling back to stable identifiers."""
    titles: dict[int, str] = {}
    unique_ids = sorted(set(int(pid) for pid in peer_ids))
    for offset in range(0, len(unique_ids), 50):
        batch = unique_ids[offset:offset + 50]
        if not batch:
            continue
        try:
            response = await vk.call("messages.getConversationsById", peer_ids=",".join(map(str, batch)), extended=1)
            items = response.get("items", []) if isinstance(response, dict) else []
            for item in items:
                peer = item.get("peer") or {}
                pid = int(peer.get("id") or item.get("peer_id") or 0)
                settings = item.get("chat_settings") or {}
                title = str(settings.get("title") or "").strip()
                if pid and title:
                    titles[pid] = title
        except Exception as exc:
            print(f"[INFO] Не удалось получить названия бесед {batch}: {exc}")
    for pid in unique_ids:
        if pid not in titles:
            titles[pid] = f"Конференция VK {pid}"
    return titles


def active_local_ban(localization_id: int, user_id: int) -> Any | None:
    return DB.fetchone("SELECT * FROM local_bans WHERE localization_id=? AND user_id=?", (localization_id, user_id))


def record_ban_history(
    peer_id: int,
    user_id: int,
    actor_id: int,
    action: str,
    duration_text: str,
    reason: str,
    *,
    localization_id: int | None = None,
    until_ts: int | None = None,
    permanent: bool = False,
) -> None:
    DB.execute(
        "INSERT INTO ban_history(peer_id,localization_id,user_id,actor_id,action,duration_text,reason,created_at,until_ts,permanent) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (peer_id, localization_id, user_id, actor_id, action, duration_text, reason, now_ts(), until_ts, int(permanent)),
    )


async def handle_join_or_leave(message: Message, peer_id: int, action: dict[str, Any]) -> bool:
    """Handle VK service messages, including member removal and invitation events."""
    action_type = str(action.get("type") or "")
    member_id = int(action.get("member_id") or 0)
    actor_id = int(get_field(message, "from_id", 0) or 0)
    if not action_type:
        return False
    if action_type == "chat_kick_user" and member_id > 0:
        voluntary = member_id == actor_id
        existing_membership = DB.fetchone(
            "SELECT return_pending FROM memberships WHERE peer_id=? AND user_id=?",
            (peer_id, member_id),
        )
        # Preserve the return guard after /q: VK reports the resulting removal as
        # a bot/admin kick, even though the user explicitly confirmed leaving.
        pending_return = voluntary or bool(existing_membership and existing_membership["return_pending"])
        reset_member_role(peer_id, member_id, pending_return=pending_return)
        await close_membership(peer_id, member_id, pending_return=pending_return)
        return True
    if action_type in {"chat_invite_user", "chat_invite_user_by_link"} and member_id > 0:
        ensure_user(member_id)
        await sync_owner(peer_id)
        mem = DB.fetchone("SELECT return_pending FROM memberships WHERE peer_id=? AND user_id=?", (peer_id, member_id))
        if mem and mem["return_pending"]:
            # A real invitation by another member is the requested permission to return.
            if actor_id == member_id:
                reset_member_role(peer_id, member_id, pending_return=True)
                try:
                    await kick_user(peer_id, member_id)
                except Exception as exc:
                    print(f"[WARN] Не удалось удалить самостоятельно вернувшегося пользователя: {exc}")
                await safe_send(peer_id, f"{await profile_name(member_id)}: для возвращения требуется повторное приглашение другим участником.")
                return True
            DB.execute("UPDATE memberships SET return_pending=0 WHERE peer_id=? AND user_id=?", (peer_id, member_id))
        ban = active_ban(peer_id, member_id)
        loc = localization_for_peer(peer_id)
        loc_ban = active_local_ban(int(loc["id"]), member_id) if loc else None
        if ban or loc_ban:
            try:
                await kick_user(peer_id, member_id)
            except Exception as exc:
                print(f"[WARN] Не удалось удалить заблокированного участника: {exc}")
            reset_member_role(peer_id, member_id)
            reason = ban["reason"] if ban else loc_ban["reason"]
            await safe_send(peer_id, f"{await profile_name(member_id)} заблокирован(а) в этой беседе/локализации. Причина: {reason}")
            return True
        now = now_ts()
        DB.execute(
            "INSERT INTO memberships(peer_id,user_id,first_join,last_join,session_start,completed_seconds,invited_by,active,return_pending) "
            "VALUES(?,?,?,?,?,0,?,1,0) ON CONFLICT(peer_id,user_id) DO UPDATE SET last_join=excluded.last_join,session_start=excluded.session_start,invited_by=excluded.invited_by,active=1,return_pending=0",
            (peer_id, member_id, now, now, now, actor_id),
        )
        return True
    return False


async def close_membership(peer_id: int, user_id: int, pending_return: bool = False) -> None:
    row = DB.fetchone("SELECT * FROM memberships WHERE peer_id=? AND user_id=?", (peer_id, user_id))
    now = now_ts()
    if not row:
        DB.execute(
            "INSERT INTO memberships(peer_id,user_id,first_join,last_join,session_start,completed_seconds,active,return_pending) VALUES(?,?,?,?,NULL,0,0,?)",
            (peer_id, user_id, now, now, 1 if pending_return else 0),
        )
        return
    completed = int(row["completed_seconds"] or 0)
    if row["active"] and row["session_start"]:
        completed += max(0, now - int(row["session_start"]))
    DB.execute(
        "UPDATE memberships SET completed_seconds=?,active=0,session_start=NULL,return_pending=? WHERE peer_id=? AND user_id=?",
        (completed, 1 if pending_return else 0, peer_id, user_id),
    )


def is_amode(peer_id: int) -> bool:
    row = DB.fetchone("SELECT amode FROM chat_state WHERE peer_id=?", (peer_id,))
    return bool(row["amode"]) if row else False


async def check_localization_ban(peer_id: int, user_id: int) -> tuple[bool, str]:
    loc = localization_for_peer(peer_id)
    if not loc:
        return False, ""
    row = active_local_ban(int(loc["id"]), user_id)
    return (True, str(row["reason"])) if row else (False, "")


async def on_ordinary_message(message: Message) -> None:
    peer_id = int(get_field(message, "peer_id", 0) or 0)
    user_id = int(get_field(message, "from_id", 0) or 0)
    if peer_id < 2_000_000_000 or user_id <= 0:
        return

    # Keep owner/creator rights synchronized from VK membership data.
    await sync_owner(peer_id)
    count_message(peer_id, user_id)

    ban = active_ban(peer_id, user_id)
    loc_banned, loc_reason = await check_localization_ban(peer_id, user_id)
    if ban or loc_banned:
        await delete_message(message)
        try:
            await kick_user(peer_id, user_id)
        except Exception as exc:
            print(f"[WARN] Пользователь {user_id} заблокирован, но удаление не удалось: {exc}")
        reset_member_role(peer_id, user_id)
        return

    mute = active_mute(peer_id, user_id)
    if mute:
        await delete_message(message)
        return

    # Antiflood: 20 messages in any rolling 10-second window -> 15 minute mute.
    flood_key = (peer_id, user_id)
    q = flood_windows[flood_key]
    current = time.monotonic()
    q.append(current)
    while q and current - q[0] > FLOOD_WINDOW:
        q.popleft()
    if len(q) >= FLOOD_LIMIT:
        expiry = now_ts() + AUTO_MUTE_SECONDS
        DB.execute(
            "INSERT INTO mutes(peer_id,user_id,until_ts,reason,by_user,created_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(peer_id,user_id) DO UPDATE SET until_ts=excluded.until_ts,reason=excluded.reason,by_user=excluded.by_user,created_at=excluded.created_at",
            (peer_id, user_id, expiry, "Автоматический мут за флуд (20 сообщений за 10 секунд)", 0, now_ts()),
        )
        await delete_message(message)
        q.clear()
        if current - auto_mute_notice_at.get(flood_key, 0) > 30:
            auto_mute_notice_at[flood_key] = current
            await safe_send(peer_id, f"{await profile_name(user_id)} получил(а) автоматический мут на 15 минут за флуд (20 сообщений за 10 секунд).")
        return

    # Admin mode is enforced by deleting non-admin messages. An admin whose level
    # was revoked is immediately treated as a regular user on their next message.
    if is_amode(peer_id) and level_of(peer_id, user_id) == 0:
        await delete_message(message)
        return

    text = str(get_field(message, "text", "") or "").strip()
    if not text.startswith(("/", "!")):
        return
    match = re.match(r"^[/!]([a-zA-Z][a-zA-Z0-9_]*)(?:@[A-Za-z0-9_]+)?(?:\s+(.*))?$", text, re.DOTALL)
    if not match:
        return
    command = match.group(1).lower()
    args = (match.group(2) or "").strip()
    await dispatch_command(message, peer_id, user_id, command, args)


async def dispatch_command(message: Message, peer_id: int, user_id: int, command: str, args: str) -> None:
    global DB
    # Hidden compatibility alias: deliberately not listed in /help.
    if command == "domen":
        command = "domain"
    current_level = level_of(peer_id, user_id)
    if command == "arangrules" and current_level < 4:
        await safe_send(peer_id, "Команда /arangrules доступна только Создателю (4 уровень).")
        return
    required = 4 if command in FIXED_LEVEL_4_COMMANDS else required_level(peer_id, command)
    if command not in COMMAND_DESCRIPTIONS:
        return
    personal_grant = DB.fetchone(
        "SELECT 1 FROM user_command_grants WHERE peer_id=? AND user_id=? AND command=?",
        (peer_id, user_id, command),
    )
    if required is None and not personal_grant:
        await safe_send(peer_id, f"Команда /{command} сейчас не привязана ни к одному уровню. Создатель может назначить её через /arangrules add [уровень] /{command}.")
        return
    if required is not None and current_level < required and not personal_grant:
        await safe_send(peer_id, f"Недостаточно прав. Команда /{command} требует уровень {required} ({LEVEL_NAMES[required]}). Ваш уровень: {current_level}.")
        return

    try:
        if command == "q":
            keyboard = (
                Keyboard(inline=True)
                .add(Callback("✅ Подтвердить выход", payload={"action": "q_confirm", "peer_id": peer_id, "user_id": user_id}))
                .row()
                .add(Callback("Отмена", payload={"action": "q_cancel", "peer_id": peer_id, "user_id": user_id}))
                .get_json()
            )
            await safe_send(peer_id, "Подтвердите добровольный выход. После подтверждения бот исключит вас и сбросит ваш уровень админки.", keyboard)
        elif command == "execute":
            if current_level < 4:
                await safe_send(peer_id, "⛔ /execute доступна только Создателю (4 уровень).")
                return
            commands = [x.strip() for x in args.splitlines() if x.strip()]
            if not commands:
                await safe_send(peer_id, "Формат: /execute\n/time\n/admins")
                return
            for line in commands[:30]:
                line = line.strip()
                if not line.startswith(("/", "!")):
                    line = "/" + line
                m = re.match(r"^[/!]([a-zA-Z][a-zA-Z0-9_]*)(?:\s+(.*))?$", line, re.DOTALL)
                if m:
                    await dispatch_command(message, peer_id, user_id, m.group(1).lower(), (m.group(2) or "").strip())
        elif command == "nt":
            parts = args.split(maxsplit=1)
            if len(parts) != 2 or parts[0] not in {"0", "1"} or not parts[1].strip():
                await safe_send(peer_id, "Использование: \n/nt 0 текст — Вызов участников текущей конференции. \n/nt 1 текст — Вызов участников всей локализации.")
                return
            mode, body = int(parts[0]), parts[1].strip()
            if len(body) > 3400:
                await safe_send(peer_id, "Текст слишком длинный. Максимальная длина текста для /nt — 3400 символов, чтобы добавить заголовок вызова.")
                return
            loc = localization_for_peer(peer_id)
            if mode == 1 and not loc:
                await safe_send(peer_id, "Режим /nt 1 доступен только внутри подключённой локализации. Используйте /localcreate или /localjoin.")
                return
            source_title = (await conference_titles([peer_id])).get(peer_id, f"Конференция VK {peer_id}")
            source_public_id = await conference_public_id(peer_id)
            if mode == 0:
                target_peers = [peer_id]
                scope_text = "вызов участников одной конференции"
            else:
                target_peers = [int(row["peer_id"]) for row in DB.fetchall(
                    "SELECT peer_id FROM localization_chats WHERE localization_id=? ORDER BY is_main DESC, joined_at ASC",
                    (int(loc["id"]),),
                )]
                scope_text = f"вызов участников локализации «{loc['name']}»"
            users: set[int] = set()
            for target_peer in target_peers:
                try:
                    members = await get_members(target_peer)
                    for item in members:
                        member_id = int(item.get("member_id") or item.get("id") or 0)
                        if member_id > 0 and member_id != user_id:
                            users.add(member_id)
                except Exception as exc:
                    print(f"[WARN] /nt: не удалось получить участников беседы {target_peer}: {exc}")
            users_sorted = sorted(users)
            sender = await profile_name(user_id)
            source_id_line = f"Локальный ID конференции: {source_public_id}\n" if source_public_id is not None else ""
            location_line = f"Локализация: «{loc['name']}»\n" if loc else "Локализация: не подключена\n"
            dm_text = (
                "📣 ВЫЗОВ УЧАСТНИКОВ\n"
                f"{location_line}"
                f"Конференция-источник: «{source_title}»\n"
                f"VK ID конференции: {peer_id}\n"
                f"{source_id_line}"
                f"Отправитель: {sender}\n"
                f"Тип вызова: {scope_text}\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"{body}"
            )
            sent = 0
            failed = 0
            failure_reasons: dict[str, int] = defaultdict(int)
            for member in users_sorted:
                try:
                    await send_private_message(member, dm_text)
                    sent += 1
                except Exception as exc:
                    failed += 1
                    reason = str(exc).replace("\n", " ").strip() or type(exc).__name__
                    if len(reason) > 120:
                        reason = reason[:117] + "..."
                    failure_reasons[reason] += 1
                    print(f"[WARN] /nt не доставил ЛС пользователю {member}: {exc}")
            reasons_text = ""
            if failure_reasons:
                common_reasons = sorted(failure_reasons.items(), key=lambda item: item[1], reverse=True)[:3]
                reasons_text = "\nПричины недоставки: " + "; ".join(
                    f"{reason} ({amount})" for reason, amount in common_reasons
                )
            if not users_sorted:
                reasons_text = "\nVK API не вернул участников для отправки. Проверьте, что бот видит состав беседы."
            await safe_send(
                peer_id,
                f"📨 Вызов отправлен: {sent} из {len(users_sorted)} пользователей ({scope_text}). "
                f"Не доставлено: {failed}. Пользователям, которые запретили сообщения от сообщества, VK может не разрешить доставку."
                f"{reasons_text}",
            )
        elif command == "ls":
            loc = localization_for_peer(peer_id)
            if not loc:
                await safe_send(peer_id, "⛔ /ls работает только в конференции, подключённой к локализации.")
                return
            target, body = await resolve_target(message, args)
            if not target or not body.strip():
                await safe_send(peer_id, "Использование: /ls @пользователь текст сообщения")
                return
            if len(body) > 3400:
                await safe_send(peer_id, "Текст слишком длинный: максимум 3400 символов.")
                return
            linked_peers = [int(row["peer_id"]) for row in DB.fetchall(
                "SELECT peer_id FROM localization_chats WHERE localization_id=? ORDER BY is_main DESC, joined_at ASC",
                (int(loc["id"]),),
            )]
            found_in: list[int] = []
            for linked_peer in linked_peers:
                try:
                    members = await get_members(linked_peer)
                    if any(int(item.get("member_id") or item.get("id") or 0) == target for item in members):
                        found_in.append(linked_peer)
                except Exception as exc:
                    print(f"[WARN] /ls: не удалось проверить участников беседы {linked_peer}: {exc}")
            if not found_in:
                await safe_send(peer_id, "⛔ Сообщение не отправлено: пользователь не найден среди участников конференций этой локализации либо VK API не дал проверить состав.")
                return
            source_title = (await conference_titles([peer_id])).get(peer_id, f"Конференция VK {peer_id}")
            source_public_id = await conference_public_id(peer_id)
            sender = await profile_name(user_id)
            dm_text = (
                "✉️ ЛИЧНОЕ СООБЩЕНИЕ ИЗ ЛОКАЛИЗАЦИИ\n"
                f"🏘 Локализация: «{loc['name']}»\n"
                f"💬 Конференция: «{source_title}»\n"
                f"🆔 Локальный ID конференции: {source_public_id if source_public_id is not None else 'не назначен'}\n"
                f"👤 Отправитель: {sender}\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"{body.strip()}"
            )
            try:
                await send_private_message(target, dm_text)
            except Exception as exc:
                print(f"[WARN] /ls не доставил ЛС пользователю {target}: {exc}")
                await safe_send(peer_id, f"❌ VK не доставил сообщение {await profile_name(target)}: {exc}. Проверьте разрешение на сообщения от сообщества.")
                return
            await safe_send(peer_id, f"✅ Личное сообщение отправлено пользователю {await profile_name(target)}.")
        elif command in {"cmdplus", "cmdminus"}:
            await cmd_user_command_grant(message, peer_id, user_id, command, args)
        elif command.startswith("rasp"):
            await cmd_announcement(peer_id, user_id, command, args)
        elif command == "restart":
            await safe_send(peer_id, "♻️ Перезапускаю бота. Данные SQLite сохраняются.")
            # Let VK finish sending the acknowledgement before replacing the process.
            await asyncio.sleep(0.8)
            try:
                await vk.close()
                DB.conn.commit()
                DB.close()
                script = os.path.abspath(sys.argv[0])
                os.execv(sys.executable, [sys.executable, script, *sys.argv[1:]])
            except Exception as exc:
                # If the OS refuses exec, restore the DB/session so the bot isn't
                # left running against a closed SQLite connection.
                DB = Database(os.getenv("DB_PATH", "bot.db"))
                await vk.start()
                await safe_send(peer_id, f"❌ Не удалось перезапустить процесс: {exc}. Бот продолжает работу.")
        elif command == "pm":
            loc = localization_for_peer(peer_id)
            if not loc:
                await safe_send(peer_id, "Эта беседа не подключена к локализации. Сначала используйте /localcreate или /localjoin.")
                return

            if not args or args.casefold() in {"list", "список"}:
                chats = DB.fetchall(
                    "SELECT peer_id, public_id, is_main FROM localization_chats "
                    "WHERE localization_id=? ORDER BY is_main DESC, joined_at ASC, peer_id ASC",
                    (int(loc["id"]),),
                )
                titles = await conference_titles([int(chat["peer_id"]) for chat in chats])
                lines = [f"🏘 ЛОКАЛИЗАЦИЯ «{loc['name']}»", "Список конференций:"]
                for chat in chats:
                    role = "главная" if int(chat["is_main"]) else "подключённая"
                    current = " — текущая" if int(chat["peer_id"]) == peer_id else ""
                    public_id = chat["public_id"] if chat["public_id"] is not None else "не назначен"
                    vk_peer_id = int(chat["peer_id"])
                    lines.append(f"\n• {titles.get(vk_peer_id, f'Конференция VK {vk_peer_id}')}{current}")
                    lines.append(f"  Локальный ID: {public_id} · VK ID: {vk_peer_id}")
                    lines.append(f"  Тип: {role}")
                lines.append("\n✉️ Отправка в другую конференцию: /pm ID текст сообщения")
                await safe_send(peer_id, "\n".join(lines))
                return

            parts = args.split(maxsplit=1)
            if len(parts) < 2 or not parts[0].isdigit() or not parts[1].strip():
                await safe_send(peer_id, "Формат: /pm ID_беседы текст сообщения. Чтобы посмотреть локальные конференции и ID, введите /pm")
                return
            target_id, body = int(parts[0]), parts[1].strip()
            target_row = DB.fetchone(
                "SELECT peer_id FROM localization_chats WHERE localization_id=? AND public_id=?",
                (int(loc["id"]), target_id),
            )
            if not target_row:
                await safe_send(peer_id, "Конференция с таким ID не найдена в текущей локализации. Введите /pm, чтобы посмотреть список ID.")
                return
            source_id = await conference_public_id(peer_id)
            await safe_send(
                int(target_row["peer_id"]),
                f"✉️ Сообщение из локальной конференции ID {source_id}:\n{body}",
            )
            await safe_send(peer_id, f"Сообщение отправлено в конференцию ID {target_id}.")
        elif command == "help":
            await cmd_help(peer_id, user_id, args)
        elif command == "gc":
            loc = localization_for_peer(peer_id)
            db_size = os.path.getsize(DB.filename) if os.path.exists(DB.filename) else 0
            try:
                member_count = len(await get_members(peer_id))
            except Exception:
                member_count = 0
            started_ping = time.perf_counter()
            try:
                await vk.call("messages.getConversationsById", peer_ids=peer_id, extended=1)
                ping_text = f"{(time.perf_counter() - started_ping) * 1000:.0f} мс"
            except Exception as exc:
                ping_text = f"недоступен ({type(exc).__name__})"
            uptime = format_duration(int(time.monotonic() - STARTED_AT))
            current_title = (await conference_titles([peer_id])).get(peer_id, f"Конференция VK {peer_id}")
            conference_public = await conference_public_id(peer_id)
            info = [
                "🛠 Статус BOT",
                f"• Время работы: {uptime}",
                f"• Пинг VK API: {ping_text}",
                f"• Версия VK API: {API_VERSION}",
                f"• База данных: SQLite ({db_size:,} байт)",
                "",
                "🏘 Информация о конференции",
                f"• Название: {current_title}",
                f"• VK ID: {peer_id}",
                f"• Локальный ID: {conference_public if conference_public is not None else 'не назначен'}",
                f"• Участников: {member_count}",
                f"• Локализация: {loc['name'] if loc else 'не подключена'}",
            ]
            if loc:
                local_chats = DB.fetchall(
                    "SELECT peer_id,public_id,is_main FROM localization_chats WHERE localization_id=? ORDER BY is_main DESC,joined_at ASC",
                    (int(loc["id"]),),
                )
                titles = await conference_titles([int(row["peer_id"]) for row in local_chats])
                info.append(f"• ID локализации: {int(loc['id'])}")
                info.append(f"• Конференций в локализации: {len(local_chats)}")
                for chat in local_chats:
                    cp = int(chat["peer_id"])
                    role = "главная" if int(chat["is_main"]) else "подключённая"
                    info.append(f"  — {titles.get(cp, f'Конференция VK {cp}')}: локальный ID {chat['public_id']}, VK ID {cp} ({role})")
            await safe_send(peer_id, "\n".join(info))
        elif command == "time":
            # Moscow uses fixed UTC+3; avoid ZoneInfo/tzdata dependency on Windows.
            msk = datetime.now(timezone(timedelta(hours=3)))
            await safe_send(
                peer_id,
                "🕒 Текущее время Москвы (МСК, UTC+3)\n"
                f"📅 Дата: {msk.strftime('%d.%m.%Y')}\n"
                f"⏰ Время: {msk.strftime('%H:%M:%S')}",
            )
        elif command in {"mute", "ban"}:
            await cmd_mute_or_ban(message, peer_id, user_id, command, args)
        elif command == "banlist":
            await cmd_banlist(message, peer_id, args)
        elif command == "warns":
            await cmd_active_warns(message, peer_id, args)
        elif command == "warnlist":
            await cmd_warning_history(message, peer_id, args)
        elif command == "comment":
            await cmd_add_comment(message, peer_id, user_id, args)
        elif command == "comments":
            await cmd_comments(message, peer_id, args)
        elif command in {"unmute", "unban", "kick", "warn", "unwarn", "get", "domain", "domaindelete", "arang"}:
            await cmd_target_command(message, peer_id, user_id, command, args)
        elif command == "admins":
            rows = DB.fetchall("SELECT user_id,level FROM admins WHERE peer_id=? AND level>0 ORDER BY level DESC,user_id", (peer_id,))
            if not rows:
                await safe_send(peer_id, "Администраторы не найдены. Владельца беседы бот определит при следующей синхронизации, если API вернёт это поле.")
            else:
                lines = [f"• {await profile_name(int(row['user_id']))} — {row['level']} уровень ({LEVEL_NAMES[int(row['level'])]})" for row in rows]
                await safe_send(peer_id, "Администраторы беседы:\n" + "\n".join(lines))
        elif command == "searchdomain":
            await cmd_search_domain(peer_id, args)
        elif command == "pin":
            reply = get_field(message, "reply_message")
            cmid = get_field(reply, "conversation_message_id") if reply else None
            if not cmid:
                await safe_send(peer_id, "Ответьте командой /pin на сообщение, которое нужно закрепить.")
            else:
                await vk.call("messages.pin", peer_id=peer_id, conversation_message_id=int(cmid))
                await safe_send(peer_id, "Сообщение закреплено.")
        elif command == "unpin":
            await vk.call("messages.unpin", peer_id=peer_id)
            await safe_send(peer_id, "Закреплённое сообщение откреплено.")
        elif command == "amode":
            value = 0 if is_amode(peer_id) else 1
            DB.execute("INSERT INTO chat_state(peer_id,owner_id,amode,updated_at) VALUES(?,NULL,?,?) ON CONFLICT(peer_id) DO UPDATE SET amode=excluded.amode,updated_at=excluded.updated_at", (peer_id, value, now_ts()))
            await safe_send(peer_id, "Режим администратора включён: сообщения пользователей без уровня будут удаляться." if value else "Режим администратора выключен.")
        elif command == "arangrules":
            await cmd_arangrules(peer_id, user_id, args)
        elif command == "localclear":
            with DB.transaction() as conn:
                conn.execute("DELETE FROM local_bans")
                conn.execute("DELETE FROM localization_chats")
                conn.execute("DELETE FROM localizations")
            await safe_send(peer_id, "🧹 Все локализации, связи конференций и локальные блокировки удалены.")
        elif command in {"localcreate", "localdelete", "localjoin", "localleave"}:
            await cmd_localization(peer_id, user_id, command, args)
        elif command in {"lkick", "lban", "unlban"}:
            await cmd_local_moderation(message, peer_id, user_id, command, args)
    except VKAPIError as exc:
        await safe_send(peer_id, f"VK API не выполнил действие: {exc}. Проверьте права бота в беседе и доступность метода.")
    except Exception as exc:
        print(f"[ERROR] /{command} в {peer_id}: {exc}")
        await safe_send(peer_id, f"Не удалось выполнить /{command}: {exc}")


async def cmd_help(peer_id: int, user_id: int, args: str) -> None:
    own_level = level_of(peer_id, user_id)
    if args:
        try:
            requested = int(args.split()[0])
        except ValueError:
            await safe_send(peer_id, "Использование: /help [0–4]")
            return
    else:
        requested = own_level
    if requested not in range(5):
        await safe_send(peer_id, "Использование: /help [0–4]")
        return
    if own_level < requested:
        await safe_send(peer_id, "⛔ Нельзя просматривать справку уровня выше вашего.")
        return
    lines = [f"📚 СПРАВКА • УРОВЕНЬ {requested}",
             f"Ваш уровень: {own_level} — {LEVEL_NAMES[own_level]}",
             "━━━━━━━━━━━━━━━━━━"]
    commands = []
    for cmd in sorted(COMMAND_DESCRIPTIONS):
        req = 4 if cmd in FIXED_LEVEL_4_COMMANDS else required_level(peer_id, cmd)
        if req == requested:
            commands.append(cmd)
            lines.append(f"🔹 /{cmd} — {COMMAND_DESCRIPTIONS[cmd]}")
    if requested == own_level:
        personal = DB.fetchall(
            "SELECT command FROM user_command_grants WHERE peer_id=? AND user_id=? ORDER BY command",
            (peer_id, user_id),
        )
        if personal:
            lines.extend(["", "🔓 ПЕРСОНАЛЬНО ДОСТУПНЫЕ КОМАНДЫ"])
            for row in personal:
                granted_command = str(row["command"])
                if granted_command in COMMAND_DESCRIPTIONS:
                    lines.append(f"🔹 /{granted_command} — {COMMAND_DESCRIPTIONS[granted_command]}")
    if not commands:
        if not any("ПЕРСОНАЛЬНО ДОСТУПНЫЕ КОМАНДЫ" in line for line in lines):
            lines.append("На этом уровне уникальных команд нет.")
    await safe_send(peer_id, "\n".join(lines))


def extract_page(rest: str) -> tuple[str, int]:
    """Take a trailing positive page number from a command's remaining arguments."""
    tokens = rest.strip().split()
    if tokens and tokens[-1].isdigit():
        page = max(1, int(tokens.pop()))
        return " ".join(tokens).strip(), page
    return rest.strip(), 1


def history_keyboard(kind: str, peer_id: int, page: int, pages: int, target_id: int | None = None) -> str | None:
    """Create inline paging controls for moderation history messages."""
    buttons: list[tuple[str, int]] = []
    if page > 1:
        buttons.append(("⬅️ Назад", page - 1))
    if page < pages:
        buttons.append(("Вперёд ➡️", page + 1))
    if not buttons:
        return None
    keyboard = Keyboard(inline=True)
    payload_target = int(target_id or 0)
    for index, (label, target_page) in enumerate(buttons):
        if index:
            keyboard.row()
        keyboard.add(Callback(label, payload={
            "action": "history_page",
            "kind": kind,
            "peer_id": peer_id,
            "target_id": payload_target,
            "page": target_page,
        }))
    return keyboard.get_json()


async def cmd_user_command_grant(message: Message, peer_id: int, actor_id: int, command: str, args: str) -> None:
    target, rest = await resolve_target(message, args)
    if not target or not rest.strip():
        await safe_send(peer_id, f"Использование: /{command} @пользователь /команда")
        return
    token = rest.strip().split()[0]
    granted_command = token.lstrip("/!").split("@", maxsplit=1)[0].casefold()
    if granted_command not in COMMAND_DESCRIPTIONS:
        await safe_send(peer_id, f"Неизвестная команда: {token}. Выберите команду из /help.")
        return
    if granted_command in NON_DELEGABLE_COMMANDS:
        await safe_send(peer_id, f"Команду /{granted_command} нельзя передать через /cmdplus.")
        return
    if command == "cmdplus":
        DB.execute(
            "INSERT INTO user_command_grants(peer_id,user_id,command,granted_by,granted_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(peer_id,user_id,command) DO UPDATE SET granted_by=excluded.granted_by,granted_at=excluded.granted_at",
            (peer_id, target, granted_command, actor_id, now_ts()),
        )
        await safe_send(peer_id, f"✅ Пользователю {await profile_name(target)} выдан персональный доступ к /{granted_command} в этой конференции.")
    else:
        cur = DB.execute(
            "DELETE FROM user_command_grants WHERE peer_id=? AND user_id=? AND command=?",
            (peer_id, target, granted_command),
        )
        if cur.rowcount:
            await safe_send(peer_id, f"✅ Персональный доступ пользователя {await profile_name(target)} к /{granted_command} отозван.")
        else:
            await safe_send(peer_id, f"У пользователя {await profile_name(target)} не было персонального доступа к /{granted_command} в этой конференции.")


def parse_announcement_title_description(args: str) -> tuple[str, str] | None:
    value = args.strip()
    if not value:
        return None
    # A pipe is the unambiguous separator for multiword titles and descriptions.
    if "|" in value:
        title, description = value.split("|", maxsplit=1)
        title, description = title.strip().strip("\"'"), description.strip()
    else:
        quoted = re.match(r"^(['\"])(.+?)\1\s+(.+)$", value, re.DOTALL)
        if quoted:
            title, description = quoted.group(2).strip(), quoted.group(3).strip()
        else:
            parts = value.split(maxsplit=1)
            if len(parts) != 2:
                return None
            title, description = parts[0].strip(), parts[1].strip()
    if not title or not description:
        return None
    return title, description


def parse_schedule_arguments(args: str, editing_time: bool = False) -> tuple[int, int, int, str, bool] | None:
    parts = args.split()
    if parts and parts[-1].casefold() == "-c":
        cycle = True
        parts.pop()
    else:
        cycle = False
    if len(parts) != 4 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    if editing_time:
        announcement_id, conference_id = int(parts[0]), int(parts[1])
    else:
        conference_id, announcement_id = int(parts[0]), int(parts[1])
    weekday = parse_weekday(parts[2])
    if weekday is None or not valid_hhmm(parts[3]):
        return None
    return announcement_id, conference_id, weekday, parts[3], cycle


async def cmd_announcement(peer_id: int, actor_id: int, command: str, args: str) -> None:
    loc = localization_for_peer(peer_id)
    if not loc:
        await safe_send(peer_id, f"/{command} работает только в конференции, подключённой к локализации.")
        return
    localization_id = int(loc["id"])

    if command == "raspnew":
        parsed = parse_announcement_title_description(args)
        if not parsed:
            await safe_send(peer_id, "Использование: /raspnew Название объявления | Описание объявления\nМожно также: /raspnew \"Название объявления\" Описание объявления")
            return
        title, description = parsed
        if len(title) > 180 or len(description) > 3000:
            await safe_send(peer_id, "Название ограничено 180 символами, описание — 3000 символами.")
            return
        now = now_ts()
        cur = DB.execute(
            "INSERT INTO announcements(localization_id,title,description,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (localization_id, title, description, actor_id, now, now),
        )
        await safe_send(peer_id, f"✅ Объявление создано.\n🆔 ID: {cur.lastrowid}\n📌 Название: {title}\nНазначьте публикацию командой /rasppublic.")
        return

    # Announcement IDs are scoped to the localization where they were created.
    if command in {"rasppublic", "raspedittime"}:
        parsed = parse_schedule_arguments(args, editing_time=(command == "raspedittime"))
        if not parsed:
            if command == "rasppublic":
                usage = "/rasppublic ID_конференции ID_объявления ДеньНедели ЧЧ:ММ [-c]"
            else:
                usage = "/raspedittime ID_объявления ID_конференции ДеньНедели ЧЧ:ММ [-c]"
            await safe_send(peer_id, f"Использование: {usage}\nДни: понедельник–воскресенье (или пн, вт, ср, чт, пт, сб, вс). Время: 18:30.")
            return
        announcement_id, conference_id, weekday, publish_time, cycle_requested = parsed
        announcement = DB.fetchone(
            "SELECT id,title FROM announcements WHERE id=? AND localization_id=?",
            (announcement_id, localization_id),
        )
        if not announcement:
            await safe_send(peer_id, f"Объявление ID {announcement_id} не найдено в локализации «{loc['name']}».")
            return
        target_chat = DB.fetchone(
            "SELECT peer_id,public_id FROM localization_chats WHERE localization_id=? AND public_id=?",
            (localization_id, conference_id),
        )
        # Also accept the raw VK peer ID as a convenience, but only for a chat
        # that is already linked to this localization.
        if not target_chat and conference_id >= 2_000_000_000:
            target_chat = DB.fetchone(
                "SELECT peer_id,public_id FROM localization_chats WHERE localization_id=? AND peer_id=?",
                (localization_id, conference_id),
            )
        if not target_chat:
            await safe_send(peer_id, f"ID конференции {conference_id} не найден в локализации. Введите /pm, чтобы посмотреть локальные ID.")
            return
        target_peer = int(target_chat["peer_id"])
        existing = DB.fetchone(
            "SELECT id,cycle_enabled FROM announcement_schedules WHERE announcement_id=? AND peer_id=?",
            (announcement_id, target_peer),
        )
        cycle = cycle_requested if (command == "rasppublic" or cycle_requested) else (bool(existing["cycle_enabled"]) if existing else False)
        now = now_ts()
        DB.execute(
            "INSERT INTO announcement_schedules(announcement_id,localization_id,peer_id,weekday,publish_time,cycle_enabled,enabled,last_sent_date,last_attempt_at,created_by,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,1,NULL,0,?,?,?) "
            "ON CONFLICT(announcement_id,peer_id) DO UPDATE SET weekday=excluded.weekday,publish_time=excluded.publish_time,"
            "cycle_enabled=excluded.cycle_enabled,enabled=1,last_sent_date=NULL,last_attempt_at=0,updated_at=excluded.updated_at",
            (announcement_id, localization_id, target_peer, weekday, publish_time, 1 if cycle else 0, actor_id, now, now),
        )
        weekday_name = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][weekday]
        action_word = "Обновлено расписание" if existing else "Публикация назначена"
        cycle_text = "еженедельно" if cycle else "один раз"
        await safe_send(peer_id, f"✅ {action_word}.\nОбъявление #{announcement_id}: «{announcement['title']}»\nКонференция: локальный ID {target_chat['public_id']}\nВремя: {weekday_name}, {publish_time} МСК\nРежим: {cycle_text}.")
        return

    if command == "raspedit":
        parts = args.split(maxsplit=1)
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].strip():
            await safe_send(peer_id, "Использование: /raspedit ID_объявления Новый текст объявления")
            return
        announcement_id, description = int(parts[0]), parts[1].strip()
        if len(description) > 3000:
            await safe_send(peer_id, "Описание слишком длинное: максимум 3000 символов.")
            return
        cur = DB.execute(
            "UPDATE announcements SET description=?,updated_at=? WHERE id=? AND localization_id=?",
            (description, now_ts(), announcement_id, localization_id),
        )
        if cur.rowcount:
            await safe_send(peer_id, f"✅ Описание объявления #{announcement_id} обновлено.")
        else:
            await safe_send(peer_id, f"Объявление #{announcement_id} не найдено в этой локализации.")
        return

    if command == "raspdelete":
        if not args.strip().isdigit():
            await safe_send(peer_id, "Использование: /raspdelete ID_объявления")
            return
        announcement_id = int(args.strip())
        cur = DB.execute("DELETE FROM announcements WHERE id=? AND localization_id=?", (announcement_id, localization_id))
        await safe_send(peer_id, f"🗑 Объявление #{announcement_id} и его расписания удалены." if cur.rowcount else f"Объявление #{announcement_id} не найдено в этой локализации.")
        return

    if command == "raspinfo":
        if not args.strip().isdigit():
            await safe_send(peer_id, "Использование: /raspinfo ID_объявления")
            return
        announcement_id = int(args.strip())
        announcement = DB.fetchone(
            "SELECT id,title,description,created_by,created_at,updated_at FROM announcements WHERE id=? AND localization_id=?",
            (announcement_id, localization_id),
        )
        if not announcement:
            await safe_send(peer_id, f"Объявление #{announcement_id} не найдено в этой локализации.")
            return
        schedules = DB.fetchall(
            "SELECT s.peer_id,s.weekday,s.publish_time,s.cycle_enabled,s.enabled,lc.public_id "
            "FROM announcement_schedules s JOIN localization_chats lc ON lc.peer_id=s.peer_id "
            "WHERE s.announcement_id=? ORDER BY lc.public_id",
            (announcement_id,),
        )
        lines = [f"📢 ОБЪЯВЛЕНИЕ #{announcement_id}", f"Название: {announcement['title']}", f"Описание: {announcement['description']}", "", "📅 Расписание:"]
        if not schedules:
            lines.append("Публикации не назначены.")
        weekday_names = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        for schedule in schedules:
            status = "отключено" if not int(schedule["enabled"]) else ("еженедельно" if int(schedule["cycle_enabled"]) else "однократно")
            lines.append(f"• Конференция ID {schedule['public_id']}: {weekday_names[int(schedule['weekday'])]}, {schedule['publish_time']} МСК — {status}")
        await safe_send(peer_id, "\n".join(lines))
        return

    if command == "raspcycle":
        parts = args.split()
        if len(parts) != 2 or not parts[0].isdigit() or parts[1].upper() not in {"ON", "OFF"}:
            await safe_send(peer_id, "Использование: /raspcycle ID_объявления ON/OFF")
            return
        announcement_id, mode = int(parts[0]), parts[1].upper()
        announcement = DB.fetchone(
            "SELECT id FROM announcements WHERE id=? AND localization_id=?",
            (announcement_id, localization_id),
        )
        if not announcement:
            await safe_send(peer_id, f"Объявление #{announcement_id} не найдено в этой локализации.")
            return
        cur = DB.execute(
            "UPDATE announcement_schedules SET cycle_enabled=?,"
            "enabled=CASE WHEN ?=0 AND last_sent_date IS NOT NULL THEN 0 ELSE 1 END,"
            "last_attempt_at=0,updated_at=? WHERE announcement_id=? AND localization_id=?",
            (1 if mode == "ON" else 0, 1 if mode == "ON" else 0, now_ts(), announcement_id, localization_id),
        )
        if not cur.rowcount:
            await safe_send(peer_id, f"У объявления #{announcement_id} ещё нет расписания. Сначала используйте /rasppublic.")
        elif mode == "ON":
            await safe_send(peer_id, f"🔁 Еженедельный цикл включён для объявления #{announcement_id} во всех назначенных конференциях.")
        else:
            await safe_send(peer_id, f"⏹ Еженедельный цикл выключен для объявления #{announcement_id}. Уже опубликованные циклы больше не повторятся; если объявление ещё не отправлялось, первая публикация состоится один раз в назначенное время.")


async def cmd_active_warns(message: Message, peer_id: int, args: str) -> None:
    target, rest = await resolve_target(message, args)
    rest, page = extract_page(rest)
    if target:
        row = DB.fetchone(
            "SELECT strikes,oral_pending FROM warnings WHERE peer_id=? AND user_id=?",
            (peer_id, target),
        )
        strikes = int(row["strikes"]) if row else 0
        oral = int(row["oral_pending"]) if row else 0
        await safe_send(
            peer_id,
            f"⚠️ АКТИВНЫЕ ПРЕДУПРЕЖДЕНИЯ\nПользователь: {await profile_name(target)}\n"
            f"Основные: {strikes}/3\nУстные до конвертации: {oral}/2",
        )
        return

    where = "peer_id=? AND (strikes>0 OR oral_pending>0)"
    params: tuple[Any, ...] = (peer_id,)
    total_row = DB.fetchone(f"SELECT COUNT(*) AS amount FROM warnings WHERE {where}", params)
    total = int(total_row["amount"]) if total_row else 0
    per_page = 10
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    rows = DB.fetchall(
        f"SELECT user_id,strikes,oral_pending FROM warnings WHERE {where} "
        "ORDER BY strikes DESC,oral_pending DESC,user_id ASC LIMIT ? OFFSET ?",
        params + (per_page, (page - 1) * per_page),
    )
    lines = [f"⚠️ АКТИВНЫЕ ПРЕДУПРЕЖДЕНИЯ · Страница {page}/{pages}", f"Пользователей с предупреждениями: {total}"]
    if not rows:
        lines.append("Активных предупреждений нет.")
    for row in rows:
        lines.append(
            f"• {await profile_name(int(row['user_id']))} — основные {int(row['strikes'])}/3, "
            f"устные {int(row['oral_pending'])}/2"
        )
    if total > per_page:
        lines.append("Следующая страница: /warns " + str(page + 1) if page < pages else "Вы достигли последней страницы.")
    await safe_send(peer_id, "\n".join(lines), history_keyboard("warns", peer_id, page, pages, target))


async def cmd_warning_history(message: Message, peer_id: int, args: str) -> None:
    target, rest = await resolve_target(message, args)
    rest, page = extract_page(rest)
    where = "peer_id=?"
    params: tuple[Any, ...] = (peer_id,)
    if target:
        where += " AND user_id=?"
        params += (target,)
    count_row = DB.fetchone(f"SELECT COUNT(*) AS amount FROM warning_history WHERE {where}", params)
    total = int(count_row["amount"]) if count_row else 0
    per_page = 10
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    rows = DB.fetchall(
        f"SELECT id,user_id,actor_id,action,reason,created_at FROM warning_history WHERE {where} "
        "ORDER BY id DESC LIMIT ? OFFSET ?",
        params + (per_page, (page - 1) * per_page),
    )
    who = f" · {await profile_name(target)}" if target else " · все пользователи"
    lines = [f"📜 ИСТОРИЯ ПРЕДУПРЕЖДЕНИЙ{who}", f"Страница {page}/{pages} · записей: {total}"]
    if not rows:
        lines.append("История предупреждений пуста.")
    for row in rows:
        dt = datetime.fromtimestamp(int(row["created_at"])).strftime("%d.%m.%Y %H:%M")
        reason = str(row["reason"] or "Причина не указана")
        if len(reason) > 160:
            reason = reason[:157] + "..."
        lines.append(
            f"\n#{int(row['id'])} · {dt}\n"
            f"Пользователь: {await profile_name(int(row['user_id']))}\n"
            f"Действие: {row['action']}\n"
            f"Модератор: {await profile_name(int(row['actor_id']))}\n"
            f"Причина: {reason}"
        )
    if total > per_page:
        lines.append(f"\nДля следующей страницы: /warnlist {f'@id{target} ' if target else ''}{page + 1}" if page < pages else "\nВы достигли последней страницы.")
    await safe_send(peer_id, "\n".join(lines), history_keyboard("warnlist", peer_id, page, pages, target))


async def cmd_banlist(message: Message, peer_id: int, args: str) -> None:
    target, rest = await resolve_target(message, args)
    rest, page = extract_page(rest)
    loc = localization_for_peer(peer_id)
    if loc:
        where = "(peer_id=? OR localization_id=?)"
        params: tuple[Any, ...] = (peer_id, int(loc["id"]))
        scope_label = f"локализация «{loc['name']}»"
    else:
        where = "peer_id=?"
        params = (peer_id,)
        scope_label = "текущая конференция"
    if target:
        where += " AND user_id=?"
        params += (target,)
    count_row = DB.fetchone(f"SELECT COUNT(*) AS amount FROM ban_history WHERE {where}", params)
    total = int(count_row["amount"]) if count_row else 0
    per_page = 10
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    rows = DB.fetchall(
        f"SELECT id,user_id,actor_id,action,duration_text,reason,created_at,until_ts,permanent "
        f"FROM ban_history WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + (per_page, (page - 1) * per_page),
    )
    target_label = f" · {await profile_name(target)}" if target else ""
    lines = [f"🚫 ИСТОРИЯ БЛОКИРОВОК · {scope_label}{target_label}", f"Страница {page}/{pages} · записей: {total}"]
    if not rows:
        lines.append("Записей о блокировках пока нет.")
    for row in rows:
        dt = datetime.fromtimestamp(int(row["created_at"])).strftime("%d.%m.%Y %H:%M")
        duration = f"Срок: {row['duration_text']}\n" if row["duration_text"] else ""
        reason = str(row["reason"] or "Причина не указана")
        if len(reason) > 160:
            reason = reason[:157] + "..."
        lines.append(
            f"\n#{int(row['id'])} · {dt}\n"
            f"Пользователь: {await profile_name(int(row['user_id']))}\n"
            f"Действие: {row['action']}\n"
            f"{duration}"
            f"Модератор: {await profile_name(int(row['actor_id']))}\n"
            f"Причина: {reason}"
        )
    if total > per_page:
        next_command = f"/banlist {f'@id{target} ' if target else ''}{page + 1}"
        lines.append(f"\nСледующая страница: {next_command}" if page < pages else "\nВы достигли последней страницы.")
    await safe_send(peer_id, "\n".join(lines), history_keyboard("banlist", peer_id, page, pages, target))


async def cmd_add_comment(message: Message, peer_id: int, actor_id: int, args: str) -> None:
    loc = localization_for_peer(peer_id)
    if not loc:
        await safe_send(peer_id, "/comment работает только в конференции, подключённой к локализации.")
        return
    target, comment = await resolve_target(message, args)
    comment = comment.strip()
    if not target or not comment:
        await safe_send(peer_id, "Использование: /comment [@Пользователь] текст комментария. Можно также ответить на сообщение пользователя.")
        return
    if len(comment) > 800:
        await safe_send(peer_id, "Комментарий слишком длинный: максимум 800 символов.")
        return
    DB.execute(
        "INSERT INTO user_comments(localization_id,peer_id,user_id,actor_id,comment,created_at) VALUES(?,?,?,?,?,?)",
        (int(loc["id"]), peer_id, target, actor_id, comment, now_ts()),
    )
    await safe_send(peer_id, f"📝 Комментарий сохранён о пользователе {await profile_name(target)} в локализации «{loc['name']}».")


async def cmd_comments(message: Message, peer_id: int, args: str) -> None:
    loc = localization_for_peer(peer_id)
    if not loc:
        await safe_send(peer_id, "/comments работает только в конференции, подключённой к локализации.")
        return
    target, rest = await resolve_target(message, args)
    rest, page = extract_page(rest)
    if not target:
        await safe_send(peer_id, "Использование: /comments @пользователь [страница]. Можно также ответить на сообщение пользователя.")
        return
    params = (int(loc["id"]), target)
    count_row = DB.fetchone("SELECT COUNT(*) AS amount FROM user_comments WHERE localization_id=? AND user_id=?", params)
    total = int(count_row["amount"]) if count_row else 0
    per_page = 3
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    rows = DB.fetchall(
        "SELECT id,peer_id,actor_id,comment,created_at FROM user_comments "
        "WHERE localization_id=? AND user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
        params + (per_page, (page - 1) * per_page),
    )
    lines = [f"📝 КОММЕНТАРИИ О ПОЛЬЗОВАТЕЛЕ", f"Пользователь: {await profile_name(target)}", f"Локализация: «{loc['name']}»", f"Страница {page}/{pages} · комментариев: {total}"]
    if not rows:
        lines.append("Комментариев пока нет.")
    titles = await conference_titles([int(row["peer_id"]) for row in rows]) if rows else {}
    for row in rows:
        dt = datetime.fromtimestamp(int(row["created_at"])).strftime("%d.%m.%Y %H:%M")
        author = await profile_name(int(row["actor_id"]))
        chat_title = titles.get(int(row["peer_id"]), f"Конференция VK {row['peer_id']}")
        lines.append(f"\n#{int(row['id'])} · {dt}\nАвтор: {author}\nКонференция: {chat_title}\nКомментарий: {row['comment']}")
    if total > per_page:
        lines.append(f"\nСледующая страница: /comments @id{target} {page + 1}" if page < pages else "\nВы достигли последней страницы.")
    await safe_send(peer_id, "\n".join(lines), history_keyboard("comments", peer_id, page, pages, target))


async def cmd_mute_or_ban(message: Message, peer_id: int, actor_id: int, command: str, args: str) -> None:
    target, rest = await resolve_target(message, args)
    if not target:
        await safe_send(peer_id, f"Использование: /{command} [@пользователь] [Длительность] [Причина]" if command == "mute" else "Использование: /ban [@Пользователь] [Длительность] [Причина] \nПримечание: (-1 = навсегда)")
        return
    parts = rest.split(maxsplit=1)
    if len(parts) < 1:
        await safe_send(peer_id, "Укажите длительность и причину.")
        return
    reason = parts[1].strip() if len(parts) > 1 else "Причина не указана"
    if command == "mute":
        # Mute duration is intentionally minute-only: use /mute @user 15 reason.
        if not re.fullmatch(r"\d+", parts[0]):
            await safe_send(peer_id, "Длительность мута указывается только целым числом минут. Пример: /mute @id123 15 флуд")
            return
        duration_minutes = int(parts[0])
        if duration_minutes <= 0:
            await safe_send(peer_id, "Длительность мута должна быть не менее 1 минуты.")
            return
        duration = duration_minutes * 60
        expiry = now_ts() + duration
        DB.execute(
            "INSERT INTO mutes(peer_id,user_id,until_ts,reason,by_user,created_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(peer_id,user_id) DO UPDATE SET until_ts=excluded.until_ts,reason=excluded.reason,by_user=excluded.by_user,created_at=excluded.created_at",
            (peer_id, target, expiry, reason, actor_id, now_ts()),
        )
        await safe_send(peer_id, f"🔇 {await profile_name(target)} получил(а) мут на {duration_minutes} минут.\nОграничение действует до: {datetime.fromtimestamp(expiry).strftime('%d.%m.%Y %H:%M:%S')}\nПричина: {reason}. Сообщения будут удаляться, если у бота есть право модерации.")
    else:
        duration = parse_duration(parts[0])
        if duration is None:
            await safe_send(peer_id, "Неверная длительность бана. Примеры: 15м, 2ч, 3д, 120s; -1 означает навсегда.")
            return
        if duration == -1:
            until_ts = None
            permanent = 1
            duration_text = "перманентно"
        elif duration <= 0:
            await safe_send(peer_id, "Для бана укажите положительное время или -1 для перманентной блокировки.")
            return
        else:
            until_ts = now_ts() + duration
            permanent = 0
            duration_text = f"до {datetime.fromtimestamp(until_ts).strftime('%d.%m.%Y %H:%M:%S')}"
        DB.execute(
            "INSERT INTO bans(peer_id,user_id,until_ts,permanent,reason,by_user,created_at) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(peer_id,user_id) DO UPDATE SET until_ts=excluded.until_ts,permanent=excluded.permanent,reason=excluded.reason,by_user=excluded.by_user,created_at=excluded.created_at",
            (peer_id, target, until_ts, permanent, reason, actor_id, now_ts()),
        )
        loc = localization_for_peer(peer_id)
        record_ban_history(
            peer_id, target, actor_id, "Блокировка", duration_text, reason,
            localization_id=int(loc["id"]) if loc else None,
            until_ts=until_ts, permanent=bool(permanent),
        )
        reset_member_role(peer_id, target)
        try:
            await kick_user(peer_id, target)
        except Exception as exc:
            await safe_send(peer_id, f"Блокировка сохранена, но исключить пользователя не удалось: {exc}")
            return
        await safe_send(peer_id, f"{await profile_name(target)} заблокирован(а) {duration_text}. Причина: {reason}. Уровень админки сброшен.")


async def cmd_target_command(message: Message, peer_id: int, actor_id: int, command: str, args: str) -> None:
    months_mode = False
    if command == "get":
        months_mode = bool(re.search(r"(?:^|\s)-y(?=\s|$)", args, re.IGNORECASE))
        args = re.sub(r"(?:^|\s)-y(?=\s|$)", " ", args, flags=re.IGNORECASE).strip()
    target, rest = await resolve_target(message, args)
    if command == "get" and not target:
        target = actor_id
    if not target:
        await safe_send(peer_id, f"Команда: /{command} [@Пользователь] [Причина] \nПримечание: Ответьте на сообщение пользователя")
        return
    if command == "unmute":
        DB.execute("DELETE FROM mutes WHERE peer_id=? AND user_id=?", (peer_id, target))
        await safe_send(peer_id, f"Мут с {await profile_name(target)} снят. {('Причина: ' + rest) if rest else ''}".strip())
    elif command == "unban":
        existing_ban = DB.fetchone("SELECT * FROM bans WHERE peer_id=? AND user_id=?", (peer_id, target))
        DB.execute("DELETE FROM bans WHERE peer_id=? AND user_id=?", (peer_id, target))
        if existing_ban:
            loc = localization_for_peer(peer_id)
            record_ban_history(
                peer_id, target, actor_id, "Снятие блокировки", "", "Команда /unban",
                localization_id=int(loc["id"]) if loc else None,
            )
        await safe_send(peer_id, f"Блокировка с {await profile_name(target)} снята. Теперь он может быть приглашён в беседу.")
    elif command == "kick":
        reason = rest or "Причина не указана"
        reset_member_role(peer_id, target)
        await kick_user(peer_id, target)
        await safe_send(peer_id, f"🚪 {await profile_name(target)} исключён(а) из беседы. Уровень администратора сброшен.\nПричина: {reason}")
    elif command == "warn":
        parts = rest.split(maxsplit=1)
        count = 1
        reason = rest or "Причина не указана"
        if parts and re.fullmatch(r"\d+", parts[0]):
            count = int(parts[0])
            reason = parts[1] if len(parts) > 1 else "Причина не указана"
        if count < 1 or count > 1_000_000:
            await safe_send(peer_id, "Количество должно быть от 1 до 1 000 000 за одну команду.")
            return
        row = DB.fetchone("SELECT strikes,oral_pending FROM warnings WHERE peer_id=? AND user_id=?", (peer_id, target))
        strikes = int(row["strikes"]) if row else 0
        oral = int(row["oral_pending"]) if row else 0
        total_oral = oral + count
        strikes += total_oral // 2
        oral = total_oral % 2
        DB.execute(
            "INSERT INTO warnings(peer_id,user_id,strikes,oral_pending) VALUES(?,?,?,?) "
            "ON CONFLICT(peer_id,user_id) DO UPDATE SET strikes=excluded.strikes,oral_pending=excluded.oral_pending",
            (peer_id, target, strikes, oral),
        )
        DB.execute("INSERT INTO warning_history(peer_id,user_id,actor_id,action,reason,created_at) VALUES(?,?,?,?,?,?)",
                   (peer_id, target, actor_id, f"Выдано устных предупреждений: {count}", reason, now_ts()))
        if strikes >= 3:
            expiry = now_ts() + 15 * 86400
            DB.execute(
                "INSERT INTO bans(peer_id,user_id,until_ts,permanent,reason,by_user,created_at) VALUES(?,?,?,0,?,?,?) "
                "ON CONFLICT(peer_id,user_id) DO UPDATE SET until_ts=excluded.until_ts,permanent=0,reason=excluded.reason,by_user=excluded.by_user,created_at=excluded.created_at",
                (peer_id, target, expiry, "Автоматическая блокировка после 3 основных предупреждений", 0, now_ts()),
            )
            loc = localization_for_peer(peer_id)
            record_ban_history(
                peer_id, target, actor_id, "Автоматическая блокировка", "15 дней",
                "Накоплено 3 основных предупреждения", localization_id=int(loc["id"]) if loc else None,
                until_ts=expiry, permanent=False,
            )
            DB.execute("UPDATE warnings SET strikes=0,oral_pending=0 WHERE peer_id=? AND user_id=?", (peer_id, target))
            reset_member_role(peer_id, target)
            try:
                await kick_user(peer_id, target)
            except Exception as exc:
                await safe_send(peer_id, f"Автобан сохранён, но исключить пользователя не удалось: {exc}")
                return
            DB.execute("INSERT INTO warning_history(peer_id,user_id,actor_id,action,reason,created_at) VALUES(?,?,?,?,?,?)",
                       (peer_id, target, actor_id, "Автобан на 15 дней", "Накоплено 3 основных предупреждения; счётчик сброшен", now_ts()))
            await safe_send(peer_id, f"{await profile_name(target)} получил(а) предупреждения и заблокирован(а) на 15 дней.")
        else:
            await safe_send(peer_id, f"⚠️ {await profile_name(target)}: выдано устных предупреждений — {count}. \nПредупреждений: {strikes}/3 {oral}/2\nПричина: {reason}")
    elif command == "unwarn":
        parts = rest.split()
        oral_mode = bool(parts and parts[0].lower() in {"oral", "устные", "устных"})
        if oral_mode:
            parts = parts[1:]
        try:
            count = int(parts[0])
        except (ValueError, IndexError):
            await safe_send(peer_id, "Использование: /unwarn @пользователь количество или /unwarn @пользователь oral количество")
            return
        if count < 1:
            await safe_send(peer_id, "Количество должно быть положительным числом.")
            return
        row = DB.fetchone("SELECT strikes,oral_pending FROM warnings WHERE peer_id=? AND user_id=?", (peer_id, target))
        strikes = int(row["strikes"]) if row else 0
        oral = int(row["oral_pending"]) if row else 0
        if oral_mode:
            removed = min(count, oral)
            DB.execute("INSERT OR IGNORE INTO warnings(peer_id,user_id,strikes,oral_pending) VALUES(?,?,0,0)", (peer_id, target))
            DB.execute("UPDATE warnings SET oral_pending=? WHERE peer_id=? AND user_id=?", (oral-removed, peer_id, target))
            remain = oral-removed
            label = "устных"
        else:
            removed = min(count, strikes)
            DB.execute("INSERT OR IGNORE INTO warnings(peer_id,user_id,strikes,oral_pending) VALUES(?,?,0,0)", (peer_id, target))
            DB.execute("UPDATE warnings SET strikes=? WHERE peer_id=? AND user_id=?", (strikes-removed, peer_id, target))
            remain = strikes-removed
            label = "основных"
        DB.execute("INSERT INTO warning_history(peer_id,user_id,actor_id,action,reason,created_at) VALUES(?,?,?,?,?,?)",
                   (peer_id, target, actor_id, f"Снято {label} предупреждений: {removed}", "Команда /unwarn", now_ts()))
        await safe_send(peer_id, f"Снято {label} предупреждений: {removed}. Осталось: {remain}.")
    elif command == "get":
        await cmd_get(peer_id, target, months_mode=months_mode)
    elif command == "domain":
        domain = rest.strip().lstrip("@").strip()
        if not domain:
            await safe_send(peer_id, "Использование: /domain @пользователь название_домена")
            return
        DB.execute("INSERT OR IGNORE INTO domains(user_id,domain,added_by,added_at) VALUES(?,?,?,?)", (target, domain, actor_id, now_ts()))
        await safe_send(peer_id, f"Домен «{domain}» добавлен пользователю {await profile_name(target)}. За одну команду можно добавить только один домен.")
    elif command == "domaindelete":
        domain = rest.strip().lstrip("@").strip()
        if not domain:
            await safe_send(peer_id, "Использование: /domaindelete @пользователь название_домена")
            return
        cur = DB.execute("DELETE FROM domains WHERE user_id=? AND domain=? COLLATE NOCASE", (target, domain))
        await safe_send(peer_id, f"Домен «{domain}» {'удалён' if cur.rowcount else 'не найден'} у пользователя {await profile_name(target)}.")
    elif command == "arang":
        try:
            new_level = int(rest.split()[0])
        except (ValueError, IndexError):
            await safe_send(peer_id, "Использование: /arang @пользователь 0-2")
            return
        if new_level not in (0, 1, 2, 3):
            await safe_send(peer_id, "Можно выдать уровень 0, 1, 2 или 3. Уровень 4 синхронизируется только для владельца.")
            return
        state = DB.fetchone("SELECT owner_id FROM chat_state WHERE peer_id=?", (peer_id,))
        if state and state["owner_id"] and int(state["owner_id"]) == target:
            await safe_send(peer_id, "Нельзя изменить уровень владельца беседы командой /arang.")
            return
        local_all = bool(re.search(r"(?:^|\s)-l\s*$", rest))
        if local_all:
            rest = re.sub(r"(?:^|\s)-l\s*$", "", rest).strip()
        peers = [peer_id]
        if local_all:
            loc = localization_for_peer(peer_id)
            if not loc:
                await safe_send(peer_id, "Суффикс -l доступен только в подключённой локализации.")
                return
            peers = [int(r["peer_id"]) for r in DB.fetchall(
                "SELECT peer_id FROM localization_chats WHERE localization_id=?", (int(loc["id"]),))]
        for target_peer in peers:
            state = DB.fetchone("SELECT owner_id FROM chat_state WHERE peer_id=?", (target_peer,))
            if state and state["owner_id"] and int(state["owner_id"]) == target:
                continue
            set_admin_level(target_peer, target, new_level, actor_id)
        scope = "во всех беседах локализации" if local_all else "в этой беседе"
        await safe_send(peer_id, f"Для {await profile_name(target)} установлен уровень {new_level} ({LEVEL_NAMES[new_level]}) {scope}.")


async def cmd_get(peer_id: int, user_id: int, months_mode: bool = False) -> None:
    ensure_user(user_id)
    user = DB.fetchone("SELECT first_seen,message_count FROM users WHERE user_id=?", (user_id,))
    member = DB.fetchone("SELECT * FROM memberships WHERE peer_id=? AND user_id=?", (peer_id, user_id))
    domains = DB.fetchall("SELECT domain FROM domains WHERE user_id=? ORDER BY domain COLLATE NOCASE", (user_id,))
    level = level_of(peer_id, user_id)
    total_seconds = int(member["completed_seconds"] or 0) if member else 0
    current_session = 0
    if member and member["active"] and member["session_start"]:
        current_session = max(0, now_ts() - int(member["session_start"]))
        total_seconds += current_session
    first_seen = datetime.fromtimestamp(int(user["first_seen"])).strftime("%d.%m.%Y %H:%M:%S") if user else "неизвестно"
    join_date = datetime.fromtimestamp(int(member["first_join"])).strftime("%d.%m.%Y %H:%M:%S") if member and member["first_join"] else "неизвестно"
    inviter = await profile_name(int(member["invited_by"])) if member and member["invited_by"] else "неизвестно"
    domain_list = ", ".join(row["domain"] for row in domains) or "нет"
    current_duration = format_months(current_session) if months_mode else format_duration(current_session)
    total_duration = format_months(total_seconds) if months_mode else format_duration(total_seconds)
    text = (
        f"Информация о {await profile_name(user_id)}\n"
        f"--------------------------------------------------------\n"
        f"VK ID: {user_id}\n"
        f"Регистрация VK: Нет доступа (403 Forbidden)\n"
        f"--------------------------------------------------------\n"
        f"Впервые замечен ботом: {first_seen}\n"
        f"Сообщений с момента наблюдения ботом: {int(user['message_count']) if user else 0}\n"
        f"Уровень в этой беседе: {level} ({LEVEL_NAMES[level]})\n"
        f"Домены: {domain_list}\n"
        f"--------------------------------------------------------\n"
        f"Кто пригласил: {inviter}\n"
        f"--------------------------------------------------------\n"
        f"Время текущего нахождения: {current_duration}\n"
        f"Время нахождения за всё время: {total_duration}"
    )
    await safe_send(peer_id, text)


async def cmd_search_domain(peer_id: int, args: str) -> None:
    domain = args.strip().lstrip("@").strip()
    if not domain:
        await safe_send(peer_id, "Использование: /searchdomain название_домена")
        return
    rows = DB.fetchall("SELECT user_id,added_at FROM domains WHERE domain=? COLLATE NOCASE ORDER BY user_id", (domain,))
    if not rows:
        await safe_send(peer_id, f"Пользователи с доменом «{domain}» не найдены.")
        return
    lines = [f"Найдено по домену «{domain}»: {len(rows)}"]
    for row in rows[:30]:
        lines.append(f"• {await profile_name(int(row['user_id']))}; добавлен {datetime.fromtimestamp(int(row['added_at'])).strftime('%d.%m.%Y')}")
    await safe_send(peer_id, "\n".join(lines))


async def cmd_arangrules(peer_id: int, actor_id: int, args: str) -> None:
    parts = args.split()
    if not parts:
        await safe_send(peer_id, "Команды: /arangrules add [уровень] [команда]; /arangrules remove [уровень] [команда]; /arangrules info [команда]")
        return
    operation = parts[0].lower()
    if operation == "add" and len(parts) >= 3:
        try:
            level = int(parts[1])
        except ValueError:
            await safe_send(peer_id, "Уровень должен быть числом от 0 до 4.")
            return
        command = parts[2].lower().lstrip("/")
        if level not in range(5) or command not in COMMAND_DESCRIPTIONS:
            await safe_send(peer_id, "Укажите уровень 0-4 и существующую команду, например /arangrules add 1 /mute.")
            return
        if command == "arangrules":
            await safe_send(peer_id, "/arangrules всегда остаётся доступной только Создателю, это системное ограничение.")
            return
        DB.execute(
            "INSERT INTO command_rules(peer_id,command,level,updated_by,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(peer_id,command) DO UPDATE SET level=excluded.level,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
            (peer_id, command, level, actor_id, now_ts()),
        )
        await safe_send(peer_id, f"Команда /{command} назначена уровню {level} ({LEVEL_NAMES[level]}) в этой беседе.")
    elif operation == "remove" and len(parts) >= 3:
        try:
            level = int(parts[1])
        except ValueError:
            await safe_send(peer_id, "Уровень должен быть числом от 0 до 4.")
            return
        command = parts[2].lower().lstrip("/")
        if level not in range(5) or command not in COMMAND_DESCRIPTIONS or command == "arangrules":
            await safe_send(peer_id, "Укажите уровень 0-4 и команду (кроме /arangrules).")
            return
        # Store -1 explicitly, so removing a default command disables it instead of restoring its default.
        DB.execute(
            "INSERT INTO command_rules(peer_id,command,level,updated_by,updated_at) VALUES(?,?, -1,?,?) "
            "ON CONFLICT(peer_id,command) DO UPDATE SET level=-1,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
            (peer_id, command, actor_id, now_ts()),
        )
        await safe_send(peer_id, f"Команда /{command} удалена из прав уровня {level}; сейчас она не назначена ни одному уровню.")
    elif operation == "info" and len(parts) >= 2:
        command = parts[1].lower().lstrip("/")
        if command not in COMMAND_DESCRIPTIONS:
            await safe_send(peer_id, "Неизвестная команда.")
            return
        req = required_level(peer_id, command)
        level_text = "не назначена" if req is None else f"{req} ({LEVEL_NAMES[req]})"
        await safe_send(peer_id, f"/{command}\nОписание: {COMMAND_DESCRIPTIONS[command]}\nТребуемый уровень в этой беседе: {level_text}.")
    else:
        await safe_send(peer_id, "Использование: /arangrules add [уровень] [команда] | remove [уровень] [команда] | info [команда]")


async def cmd_localization(peer_id: int, actor_id: int, command: str, args: str) -> None:
    name = args.strip()
    if not name:
        await safe_send(peer_id, f"Укажите название локализации: /{command} Название")
        return
    if command == "localcreate":
        try:
            with DB.transaction() as conn:
                cur = conn.execute("INSERT INTO localizations(name,main_peer_id,created_by,created_at) VALUES(?,?,?,?)", (name, peer_id, actor_id, now_ts()))
                local_id = int(cur.lastrowid)
                public_id = first_free_local_public_id(conn)
                conn.execute("INSERT INTO localization_chats(localization_id,peer_id,is_main,joined_at,public_id) VALUES(?,?,1,?,?)", (local_id, peer_id, now_ts(), public_id))
            await safe_send(peer_id, f"✅ Локализация «{name}» создана. ID этой беседы: {await conference_public_id(peer_id)}. Эта беседа назначена главной.")
        except Exception:
            await safe_send(peer_id, "Не удалось создать локализацию: название уже занято или эта беседа уже подключена к другой локализации.")
    elif command == "localdelete":
        loc = DB.fetchone("SELECT * FROM localizations WHERE name=? COLLATE NOCASE", (name,))
        if not loc:
            await safe_send(peer_id, "Локализация не найдена.")
            return
        if int(loc["main_peer_id"]) != peer_id:
            await safe_send(peer_id, "Удалить локализацию можно только в главной беседе, где она была создана.")
            return
        DB.execute("DELETE FROM localizations WHERE id=?", (int(loc["id"]),))
        await safe_send(peer_id, f"Локализация «{name}» удалена вместе со связями и локальными блокировками.")
    elif command == "localjoin":
        loc = DB.fetchone("SELECT * FROM localizations WHERE name=? COLLATE NOCASE", (name,))
        if not loc:
            await safe_send(peer_id, "Локализация не найдена.")
            return
        already = DB.fetchone("SELECT localization_id FROM localization_chats WHERE peer_id=?", (peer_id,))
        if already:
            await safe_send(peer_id, "Эта беседа уже подключена к локализации. Сначала выполните /localleave в текущей локализации.")
            return
        with DB.transaction() as conn:
            conn.execute("DELETE FROM command_rules WHERE peer_id=?", (peer_id,))
            public_id = first_free_local_public_id(conn)
            conn.execute("INSERT INTO localization_chats(localization_id,peer_id,is_main,joined_at,public_id) VALUES(?,?,0,?,?)", (int(loc["id"]), peer_id, now_ts(), public_id))
        await safe_send(peer_id, f"🔗 Беседа подключена к локализации «{loc['name']}».\nИндивидуальный ID беседы: {public_id}. Используйте /pm {public_id} текст для отправки сообщения.")
    elif command == "localleave":
        loc = DB.fetchone("SELECT l.*,lc.is_main FROM localization_chats lc JOIN localizations l ON l.id=lc.localization_id WHERE lc.peer_id=? AND l.name=? COLLATE NOCASE", (peer_id, name))
        if not loc:
            await safe_send(peer_id, "Эта беседа не подключена к указанной локализации.")
            return
        if int(loc["is_main"]) or int(loc["main_peer_id"]) == peer_id:
            await safe_send(peer_id, "Главная беседа не может покинуть свою локализацию. Для удаления используйте /localdelete Название.")
            return
        with DB.transaction() as conn:
            conn.execute("DELETE FROM localization_chats WHERE peer_id=? AND localization_id=?", (peer_id, int(loc["id"])))
            conn.execute("DELETE FROM announcement_schedules WHERE peer_id=? AND localization_id=?", (peer_id, int(loc["id"])))
            conn.execute("DELETE FROM command_rules WHERE peer_id=?", (peer_id,))
        await safe_send(peer_id, f"Беседа отключена от локализации «{loc['name']}».")


async def cmd_local_moderation(message: Message, peer_id: int, actor_id: int, command: str, args: str) -> None:
    loc = localization_for_peer(peer_id)
    if not loc:
        await safe_send(peer_id, f"/{command} работает только в беседе, подключённой к локализации.")
        return
    target, reason = await resolve_target(message, args)
    if not target:
        await safe_send(peer_id, f"Использование: /{command} @пользователь [причина]")
        return
    localization_id = int(loc["id"])
    peers = [int(row["peer_id"]) for row in DB.fetchall("SELECT peer_id FROM localization_chats WHERE localization_id=?", (localization_id,))]
    if command == "unlban":
        existing_local_ban = DB.fetchone("SELECT * FROM local_bans WHERE localization_id=? AND user_id=?", (localization_id, target))
        DB.execute("DELETE FROM local_bans WHERE localization_id=? AND user_id=?", (localization_id, target))
        if existing_local_ban:
            record_ban_history(
                peer_id, target, actor_id, "Снятие локальной блокировки", "", "Команда /unlban",
                localization_id=localization_id,
            )
        await safe_send(peer_id, f"Локальная блокировка пользователя {await profile_name(target)} снята в локализации «{loc['name']}».")
        return
    if command == "lban":
        DB.execute("INSERT INTO local_bans(localization_id,user_id,reason,by_user,created_at) VALUES(?,?,?,?,?) ON CONFLICT(localization_id,user_id) DO UPDATE SET reason=excluded.reason,by_user=excluded.by_user,created_at=excluded.created_at", (localization_id, target, reason or "Причина не указана", actor_id, now_ts()))
        record_ban_history(
            peer_id, target, actor_id, "Локальная блокировка", "во всех конференциях локализации",
            reason or "Причина не указана", localization_id=localization_id, permanent=True,
        )
    successful = 0
    for linked_peer in peers:
        reset_member_role(linked_peer, target)
        try:
            await kick_user(linked_peer, target)
            successful += 1
        except Exception as exc:
            # A user absent from a linked chat is normal; don't abort the rest.
            print(f"[INFO] Не удалось исключить id{target} из {linked_peer}: {exc}")
    if command == "lban":
        await safe_send(peer_id, f"{await profile_name(target)} заблокирован(а) во всей локализации «{loc['name']}». Исключения выполнены в {successful} беседах. Причина: {reason or 'Причина не указана'}.")
    else:
        await safe_send(peer_id, f"{await profile_name(target)} исключён(а) из бесед локализации «{loc['name']}» (успешных исключений: {successful}). Уровни админки сброшены в подключённых беседах.")


@bot.on.chat_message()
async def chat_handler(message: Message) -> None:
    peer_id = int(get_field(message, "peer_id", 0) or 0)
    if peer_id < 2_000_000_000:
        return
    action = action_dict(message)
    if action:
        try:
            await handle_join_or_leave(message, peer_id, action)
        except Exception as exc:
            print(f"[WARN] Ошибка обработки сервисного события {peer_id}: {exc}")
        return
    await on_ordinary_message(message)



async def edited_message_handler(message: Message) -> None:
    """Process edited messages as commands without repeating moderation side effects."""
    peer_id = int(get_field(message, "peer_id", 0) or 0)
    user_id = int(get_field(message, "from_id", 0) or 0)
    if peer_id < 2_000_000_000 or user_id <= 0:
        return
    text = str(get_field(message, "text", "") or "").strip()
    if not text.startswith(("/", "!")):
        return
    match = re.match(r"^[/!]([a-zA-Z][a-zA-Z0-9_]*)(?:@[A-Za-z0-9_]+)?(?:\s+(.*))?$", text, re.DOTALL)
    if match:
        await dispatch_command(message, peer_id, user_id, match.group(1).lower(), (match.group(2) or "").strip())


# Register only when this vkbottle version exposes the message-edit event.
_message_edit_event = getattr(GroupEventType, "MESSAGE_EDIT", None)
if _message_edit_event is not None:
    bot.on.raw_event(_message_edit_event, Message)(edited_message_handler)


@bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent)
async def callback_handler(event: MessageEvent) -> None:
    payload = get_field(event, "payload", {}) or {}
    action = payload.get("action") if isinstance(payload, dict) else None
    user_id = int(get_field(event, "user_id", 0) or 0)
    peer_id = int(get_field(event, "peer_id", 0) or 0)
    if action == "history_page":
        if peer_id != int(payload.get("peer_id", -1)):
            try:
                await event.show_snackbar("Эта кнопка предназначена другой конференции.")
            except Exception:
                pass
            return
        kind = str(payload.get("kind", ""))
        page = max(1, int(payload.get("page", 1)))
        target_id = int(payload.get("target_id", 0) or 0)
        command_map = {
            "warns": ("warns", cmd_active_warns),
            "warnlist": ("warnlist", cmd_warning_history),
            "banlist": ("banlist", cmd_banlist),
            "comments": ("comments", cmd_comments),
        }
        if kind not in command_map:
            return
        command_name, handler = command_map[kind]
        req = required_level(peer_id, command_name)
        grant = DB.fetchone(
            "SELECT 1 FROM user_command_grants WHERE peer_id=? AND user_id=? AND command=?",
            (peer_id, user_id, command_name),
        )
        if (req is None and not grant) or (req is not None and level_of(peer_id, user_id) < req and not grant):
            try:
                await event.show_snackbar("Недостаточно прав для просмотра этой истории.")
            except Exception:
                pass
            return
        if kind == "comments" and target_id <= 0:
            return
        args = f"@id{target_id} {page}" if target_id > 0 else str(page)
        await handler(event, peer_id, args)
        try:
            await event.show_snackbar(f"Страница {page}")
        except Exception:
            pass
        return
    if action not in {"q_confirm", "q_cancel"}:
        return
    if user_id != int(payload.get("user_id", -1)) or peer_id != int(payload.get("peer_id", -1)):
        try:
            await event.show_snackbar("Эта кнопка предназначена другому пользователю или беседе.")
        except Exception:
            pass
        return
    if action == "q_cancel":
        await safe_send(peer_id, f"✅ {await profile_name(user_id)}, выход отменён. Вы остаетесь в беседе, ваш уровень сохранён.")
        try:
            await event.show_snackbar("Выход отменён.")
        except Exception:
            pass
        return
    reset_member_role(peer_id, user_id, pending_return=True)
    try:
        await kick_user(peer_id, user_id)
        try:
            await event.show_snackbar("Вы исключены из беседы. Уровень админки сброшен.")
        except Exception:
            pass
    except Exception as exc:
        await safe_send(peer_id, f"Не удалось исключить вас. Проверьте, есть ли у бота права исключать участников: {exc}")


async def announcement_scheduler() -> None:
    """Persistent weekly announcement delivery loop (all schedule times are Moscow time)."""
    while True:
        try:
            now = datetime.now(MOSCOW_TZ)
            today = now.date().isoformat()
            current_time = now.strftime("%H:%M")
            schedules = DB.fetchall(
                "SELECT s.id,s.announcement_id,s.localization_id,s.peer_id,s.weekday,s.publish_time,"
                "s.cycle_enabled,s.last_sent_date,s.last_attempt_at,a.title,a.description,l.name AS localization_name "
                "FROM announcement_schedules s "
                "JOIN announcements a ON a.id=s.announcement_id "
                "JOIN localizations l ON l.id=s.localization_id "
                "WHERE s.enabled=1 ORDER BY s.id"
            )
            for schedule in schedules:
                schedule_id = int(schedule["id"])
                attempt_at = int(schedule["last_attempt_at"] or 0)
                sent_date = str(schedule["last_sent_date"] or "")
                cycle = bool(schedule["cycle_enabled"])

                # Failed one-off announcements are not silently repeated a week later.
                if not cycle and attempt_at:
                    attempted_day = datetime.fromtimestamp(attempt_at, MOSCOW_TZ).date().isoformat()
                    if attempted_day < today and not sent_date:
                        DB.execute("UPDATE announcement_schedules SET enabled=0,updated_at=? WHERE id=?", (now_ts(), schedule_id))
                        continue

                if int(schedule["weekday"]) != now.weekday() or str(schedule["publish_time"]) > current_time:
                    continue
                if sent_date == today:
                    continue
                if attempt_at and now_ts() - attempt_at < 300:
                    continue

                DB.execute(
                    "UPDATE announcement_schedules SET last_attempt_at=?,updated_at=? WHERE id=?",
                    (now_ts(), now_ts(), schedule_id),
                )
                announcement_text = (
                    "📢 ОБЪЯВЛЕНИЕ\n"
                    f"🏘 Локализация: «{schedule['localization_name']}»\n"
                    f"🆔 Объявление: #{int(schedule['announcement_id'])}\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"📌 {schedule['title']}\n\n{schedule['description']}"
                )
                try:
                    await send(int(schedule["peer_id"]), announcement_text)
                except Exception as exc:
                    print(f"[WARN] Не удалось опубликовать объявление #{schedule['announcement_id']} в {schedule['peer_id']}: {exc}")
                    continue

                DB.execute(
                    "UPDATE announcement_schedules SET last_sent_date=?,enabled=?,updated_at=? WHERE id=?",
                    (today, 1 if cycle else 0, now_ts(), schedule_id),
                )
                print(f"[INFO] Объявление #{schedule['announcement_id']} опубликовано в беседе {schedule['peer_id']} ({today} {current_time} МСК)")
        except Exception as exc:
            print(f"[ERROR] Ошибка планировщика объявлений: {exc}")
        await asyncio.sleep(15)


async def main() -> None:
    await vk.start()
    print("VK Conference Bot started. SQLite database:", DB.filename)
    scheduler_task = asyncio.create_task(announcement_scheduler(), name="announcement-scheduler")
    try:
        await bot.run_polling()
    finally:
        scheduler_task.cancel()
        await asyncio.gather(scheduler_task, return_exceptions=True)
        await vk.close()
        DB.close()


if __name__ == "__main__":
    asyncio.run(main())
