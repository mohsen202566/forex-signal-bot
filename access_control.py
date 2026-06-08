# -*- coding: utf-8 -*-
"""
Access control for Forex Signal Bot.

This file is ASCII-safe in code and UTF-8-safe for Persian messages.
It stores allowed Telegram user IDs in data/allowed_users.json.
"""

import json
import os
from typing import Set

from config import DATA_DIR, USERS_FILE, OWNER_ID, ALLOWED_USER_IDS


def _to_int(value, default=None):
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(str(value).strip())
    except Exception:
        return default


def _base_allowed_users() -> Set[int]:
    users = set()

    for user_id in ALLOWED_USER_IDS:
        parsed = _to_int(user_id)
        if parsed is not None:
            users.add(parsed)

    owner_id = _to_int(OWNER_ID)
    if owner_id is not None and owner_id > 0:
        users.add(owner_id)

    return users


def _ensure_file() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(USERS_FILE):
        save_allowed_users(_base_allowed_users())


def load_allowed_users() -> Set[int]:
    _ensure_file()
    users = set()

    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data.get("allowed", []):
            parsed = _to_int(item)
            if parsed is not None:
                users.add(parsed)
    except Exception:
        users = set()

    users |= _base_allowed_users()
    return users


def save_allowed_users(users) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    clean_users = sorted({int(u) for u in users if _to_int(u) is not None})

    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump({"allowed": clean_users}, f, ensure_ascii=False, indent=2)


def is_owner(user_id: int) -> bool:
    owner_id = _to_int(OWNER_ID)
    current_user_id = _to_int(user_id)
    return owner_id is not None and owner_id > 0 and current_user_id == owner_id


def is_allowed(user_id: int) -> bool:
    current_user_id = _to_int(user_id)
    if current_user_id is None:
        return False

    owner_id = _to_int(OWNER_ID)
    if owner_id is None or owner_id <= 0:
        return False

    return current_user_id in load_allowed_users()


def add_user(user_id: int) -> bool:
    parsed = _to_int(user_id)
    if parsed is None or parsed <= 0:
        return False

    users = load_allowed_users()
    users.add(parsed)
    save_allowed_users(users)
    return True


def remove_user(user_id: int) -> bool:
    parsed = _to_int(user_id)
    owner_id = _to_int(OWNER_ID)

    if parsed is None or parsed <= 0:
        return False

    # Owner must never be removed from access list.
    if owner_id is not None and parsed == owner_id:
        save_allowed_users(load_allowed_users())
        return False

    users = load_allowed_users()
    existed = parsed in users
    users.discard(parsed)
    save_allowed_users(users)
    return existed


def list_users_text() -> str:
    users = load_allowed_users()
    if not users:
        return "هیچ کاربری مجاز نیست."

    owner_id = _to_int(OWNER_ID)
    lines = ["کاربران مجاز:"]

    for user_id in sorted(users):
        suffix = " (مالک)" if owner_id is not None and user_id == owner_id else ""
        lines.append(f"• {user_id}{suffix}")

    return "\n".join(lines)
