"""Polite, resumable raw HTML downloader backed by SQLite fetch_log and .html.gz files."""
import gzip
import os
import time

from ganyan.db import fetched_ok, log_fetch
from ganyan.tjk import get


def _read_raw_text(path):
    """Read gzipped (or plain) HTML file and return UTF-8 text."""
    with open(path, "rb") as f:
        data = f.read()
    if not data:
        return None
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")


def fetch(
    conn,
    source,
    target,
    url,
    raw_path,
    headers=None,
    delay=1.0,
    getter=None,
    sleep_fn=time.sleep,
):
    """Return HTML text from local .html.gz cache if fetched_ok, else download via tjk.get.

    On HTTP 200 with non-empty body: writes gzipped bytes to ``raw_path``, records
    ``status='ok'`` in ``fetch_log``, sleeps ``delay`` seconds, and returns decoded text.
    On error or empty body: records ``status='error'`` so the next run retries, sleeps
    ``delay`` seconds, and returns ``None``.
    """
    path_str = str(raw_path)
    if conn is not None and fetched_ok(conn, source, target) and os.path.exists(path_str):
        try:
            if os.path.getsize(path_str) > 0:
                cached = _read_raw_text(path_str)
                if cached:
                    return cached
        except OSError:
            pass

    dl = getter or get
    try:
        http_status, body = dl(url, extra_headers=headers)
    except Exception:
        http_status, body = None, b""

    if isinstance(body, str):
        body = body.encode("utf-8")
    body = body or b""

    if http_status == 200 and body.strip():
        parent = os.path.dirname(path_str)
        if parent:
            os.makedirs(parent, exist_ok=True)
        gz_bytes = gzip.compress(body)
        tmp_path = path_str + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(gz_bytes)
        os.replace(tmp_path, path_str)
        if conn is not None:
            log_fetch(conn, source, target, "ok", http=http_status, nbytes=len(body))
        if delay and delay > 0:
            sleep_fn(delay)
        return body.decode("utf-8", errors="replace")

    if conn is not None:
        log_fetch(conn, source, target, "error", http=http_status, nbytes=len(body))
    if delay and delay > 0:
        sleep_fn(delay)
    return None
