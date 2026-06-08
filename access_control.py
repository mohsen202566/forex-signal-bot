# -*- coding: utf-8 -*-
import json
import os
from config import DATA_DIR, USERS_FILE, OWNER_ID, ALLOWED_USER_IDS

def _ensure_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump({"allowed": sorted(list(ALLOWED_USER_IDS))}, f, ensure_ascii=False, indent=2)

def load_allowed_users():
    _ensure_file()
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        allowed = set(int(x) for x in data.get("allowed", []) if str(x).isdigit())
    except Exception:
        allowed = set()
    allowed |= set(ALLOWED_USER_IDS)
    if OWNER_ID:
        allowed.add(OWNER_ID)
    return allowed

def save_allowed_users(users):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump({"allowed": sorted(list(users))}, f, ensure_ascii=False, indent=2)

def is_owner(user_id: int):
    return OWNER_ID and int(user_id) == int(OWNER_ID)

def is_allowed(user_id: int):
    if not OWNER_ID:
        return False
    return int(user_id) in load_allowed_users()

def add_user(user_id: int):
    users = load_allowed_users()
    users.add(int(user_id))
    save_allowed_users(users)

def remove_user(user_id: int):
    users = load_allowed_users()
    if int(user_id) != int(OWNER_ID):
        users.discard(int(user_id))
    save_allowed_users(users)

def list_users_text():
    users = load_allowed_users()
    if not users:
        return "هیچ کاربری مجاز نیست."
    lines = ["کاربران مجاز:"]
    for u in sorted(users):
        suffix = " (مالک)" if OWNER_ID and u == OWNER_ID else ""
        lines.append(f"• {u}{suffix}")
    return "\n".join(lines)
