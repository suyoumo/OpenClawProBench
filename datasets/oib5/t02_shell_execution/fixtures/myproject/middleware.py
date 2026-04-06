import time
import logging

logger = logging.getLogger(__name__)

def timing_middleware(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        logger.debug(f'{func.__name__} took {elapsed:.3f}s')
        return result
    return wrapper
