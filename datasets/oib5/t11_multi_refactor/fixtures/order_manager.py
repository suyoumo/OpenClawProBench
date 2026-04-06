"""订单管理模块"""

import json
from pathlib import Path

ORDER_FILE = "orders.json"


def load_orders():
    path = Path(ORDER_FILE)
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    return data


def save_orders(orders):
    with open(ORDER_FILE, "w") as f:
        json.dump(orders, f, indent=2)


def find_order(orders, order_id):
    for o in orders:
        if o["id"] == order_id:
            return o
    return None


def validate_amount(amount):
    return isinstance(amount, (int, float)) and amount > 0
