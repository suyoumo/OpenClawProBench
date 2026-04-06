import logging
from models import User

logger = logging.getLogger(__name__)

def create_user(name, age):
    user = User(name, age)
    logger.info(f'Created user {name}')
    return user

def delete_user(user):
    logger.warning(f'Deleting {user.name}')
    return True

def list_users():
    return []

def update_user(user, **kwargs):
    for k, v in kwargs.items():
        setattr(user, k, v)
    return user
