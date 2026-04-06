"""用户管理模块"""

import json
from pathlib import Path

DATA_FILE = "users.json"


def load_users():
    path = Path(DATA_FILE)
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    return data


def save_users(users):
    with open(DATA_FILE, "w") as f:
        json.dump(users, f, indent=2)


def find_user(users, user_id):
    for u in users:
        if u["id"] == user_id:
            return u
    return None


def validate_email(email):
    return "@" in email and "." in email.split("@")[1]
