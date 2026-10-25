"""Local wall-clock helpers (patched in tests to simulate timeouts/midnight)."""
from datetime import datetime

TS_FORMAT = '%Y-%m-%d %H:%M:%S'


def now():
    return datetime.now().replace(microsecond=0)


def ts(value=None):
    return (value or now()).strftime(TS_FORMAT)


def parse_ts(value):
    return datetime.strptime(value, TS_FORMAT) if value else None
