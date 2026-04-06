import logging

logger = logging.getLogger(__name__)


def persist_session(token: str) -> None:
    logger.info("persisting bearer=%s", token)
