from datetime import datetime, timezone, timedelta

# Indian Standard Time: UTC + 5:30
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def now_ist() -> datetime:
    """Return the current datetime in Indian Standard Time (IST)."""
    return datetime.now(IST)


def now_ist_str(format_str: str = "%Y-%m-%d %H:%M:%S IST") -> str:
    """Return formatted current time string in Indian Standard Time (IST)."""
    return now_ist().strftime(format_str)


def now_ist_iso() -> str:
    """Return ISO-8601 formatted string with +05:30 offset."""
    return now_ist().isoformat()
