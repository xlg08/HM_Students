"""JSON application logging; request context also follows service mutations."""
import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

request_id = ContextVar('request_id', default='system')


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = dict(at=datetime.now(timezone.utc).isoformat(), level=record.levelname,
                       message=record.getMessage(), request_id=request_id.get())
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure():
    directory = Path(__file__).resolve().parent.parent / 'logs'
    directory.mkdir(exist_ok=True)
    logger = logging.getLogger('aicrawl')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        output = RotatingFileHandler(directory / 'application.jsonl', maxBytes=2_000_000,
                                     backupCount=3, encoding='utf-8')
        output.setFormatter(JsonFormatter())
        logger.addHandler(output)
    return logger
