"""Mask secret tokens in access logs.

Invitation, password-reset and share links carry their token in the URL path. The database keeps
only hashes, so the access log must not keep the token either: whoever reads the container logs
would get a working link (an unused invitation creates an account).
"""

import logging
import re

_TOKEN = re.compile(r"(/(?:invite|reset|shared|accept)/)[A-Za-z0-9_-]+")


def mask(text: str) -> str:
    return _TOKEN.sub(r"\1***", text)


class MaskTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(mask(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.msg, str):
            record.msg = mask(record.msg)
        return True


def install() -> None:
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, MaskTokens) for f in logger.filters):
            logger.addFilter(MaskTokens())
