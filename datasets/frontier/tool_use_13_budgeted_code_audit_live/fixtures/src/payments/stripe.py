import os


def stripe_secret() -> str:
    return os.getenv("STRIPE_SECRET", "")
