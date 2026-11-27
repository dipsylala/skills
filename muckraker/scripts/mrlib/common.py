"""Shared plumbing: HTTP fetching (with the SEC contact rules), body decoding, record output, text helpers."""

import http.client
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib


#!/usr/bin/env python3
"""Deterministic fetchers for muckraker source agents.

Each command fetches one kind of public record and prints JSON lines, one
record per fact, each with the source URL and, where there is one, the exact
text from the document (`quote`) so the coordinator can confirm it.

sec.gov asks automated clients to identify themselves. Pass the name and email
the user gave with --user-agent "Name email" or the MUCKRAKER_SEC_UA
environment variable, such as "Jane Smith jane@example.com"; commands that
reach sec.gov refuse to run without one, or with a value not in that form.

Standard library only; Python 3.9 or later.
"""

import argparse
import http.client
import datetime as dt
import html
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
import zlib

SEC_MIN_INTERVAL = 0.15  # seconds between sec.gov requests (under 10 a second)
MAX_BODY = 100 * 1024 * 1024  # largest body, raw or decompressed; big BDC 10-Qs run to ~35 MB
_CHUNK = 64 * 1024
_last_sec_request = 0.0


class FetchError(Exception):
    pass


def read_body(stream, gzipped, limit=MAX_BODY, sink=None):
    """Read a response body in chunks, never holding more than `limit` bytes of
    raw or decompressed data, so an oversized page or a gzip bomb fails cleanly.
    With `sink`, each decompressed chunk goes to it instead and nothing is kept."""
    out, size = [], 0
    raw_total = 0
    d = zlib.decompressobj(16 + zlib.MAX_WBITS) if gzipped else None
    while True:
        chunk = stream.read(_CHUNK)
        if not chunk:
            break
        raw_total += len(chunk)
        if raw_total > limit:
            raise FetchError(f"response larger than {limit} bytes")
        if d is None:
            data = chunk
        else:
            data = d.decompress(chunk, limit - size + 1)
            if d.unconsumed_tail:
                raise FetchError(f"decompressed response larger than {limit} bytes")
        size += len(data)
        if size > limit:
            raise FetchError(f"decompressed response larger than {limit} bytes")
        sink(data) if sink else out.append(data)
    if d is not None:
        tail = d.flush(limit - size + 1)
        size += len(tail)
        if size > limit or d.unconsumed_tail:
            raise FetchError(f"decompressed response larger than {limit} bytes")
        sink(tail) if sink else out.append(tail)
    return b"".join(out)


def fetch(url, user_agent, retries=2, auth=None, accept=None):
    """Return the decoded body of `url`."""
    return decode_body(fetch_bytes(url, user_agent, retries, auth, accept))


_CHARSET_RE = re.compile(rb"""charset\s*=\s*["']?([A-Za-z0-9_.:-]+)""", re.I)


def decode_body(raw):
    """UTF-8 when the body is valid UTF-8; otherwise the charset the page declares
    in its first 4 KB (a Latin-1 register page such as w2.brreg.no), else cp1252.
    Decoding a Latin-1 page as UTF-8 turns every å or ø into U+FFFD, so quotes
    with those letters are never found."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    m = _CHARSET_RE.search(raw[:4096])
    if m:
        try:
            return raw.decode(m.group(1).decode("ascii"), errors="replace")
        except LookupError:
            pass
    return raw.decode("cp1252", errors="replace")


SEC_CONTACT = re.compile(r"\S.*\s[^\s@]+@[^\s@]+\.[^\s@]+")
SEC_COMMANDS = {"edgar-filings", "edgar-facts", "edgar-search", "marks", "formd"}


def clean_sec_contact(user_agent):
    """The contact without surrounding spaces or quotes, which a .env file loaded by
    PowerShell (or a pasted value) keeps as part of the value."""
    return (user_agent or "").strip().strip("\"'").strip()


def sec_contact_problem(user_agent):
    """Why `user_agent` cannot go to sec.gov, or None. SEC asks automated clients
    to declare a name and a contact email, so the value must be "Name email",
    such as "Jane Smith jane@example.com". The message never repeats the value."""
    if not clean_sec_contact(user_agent):
        return "sec.gov needs --user-agent or MUCKRAKER_SEC_UA"
    if not SEC_CONTACT.fullmatch(clean_sec_contact(user_agent)):
        return ('sec.gov needs --user-agent or MUCKRAKER_SEC_UA as "Name email", such as '
                '"Jane Smith jane@example.com": a name, a space, then an email address')
    return None


def fetch_bytes(url, user_agent, retries=2, auth=None, accept=None, limit=MAX_BODY, sink=None):
    """Return the raw body of `url`. `auth` is sent as an Authorization header
    on this request only, never on a redirect (Companies House documents redirect
    to signed storage URLs that reject it). `user_agent` is the user's SEC contact,
    so it goes to sec.gov only; every other host gets a generic one."""
    global _last_sec_request
    host = urllib.parse.urlparse(url).hostname or ""
    is_sec = host == "sec.gov" or host.endswith(".sec.gov")
    problem = sec_contact_problem(user_agent) if is_sec else None
    if problem:
        raise FetchError(problem)
    if is_sec:
        user_agent = clean_sec_contact(user_agent)
    headers = {"Accept-Encoding": "gzip"}
    if not is_sec:
        # Never set beside the SEC contact: urllib merges ordinary headers over unredirected
        # ones on Python 3.15+ (earlier versions did the reverse), so a generic User-Agent
        # here would replace the contact, and sec.gov answers it with HTTP 403.
        headers["User-Agent"] = "muckraker"
    if accept:
        headers["Accept"] = accept
    for attempt in range(retries + 1):
        if is_sec:
            wait = SEC_MIN_INTERVAL - (time.monotonic() - _last_sec_request)
            if wait > 0:
                time.sleep(wait)
            _last_sec_request = time.monotonic()
        request = urllib.request.Request(url, headers=headers)
        if is_sec:  # unredirected, so a redirect to another host does not carry the contact
            request.add_unredirected_header("User-Agent", user_agent)
        if auth:
            request.add_unredirected_header("Authorization", auth)
        try:
            with urllib.request.urlopen(request, timeout=60) as r:
                return read_body(r, r.headers.get("Content-Encoding") == "gzip", limit, sink)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise FetchError(f"HTTP {e.code} for {url}") from e
        except urllib.error.URLError as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise FetchError(f"{e.reason} for {url}") from e
        except (TimeoutError, ConnectionError, http.client.HTTPException) as e:  # read timeout, reset, cut-off body
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise FetchError(f"{type(e).__name__} for {url}") from e


def emit(record):
    print(json.dumps(record, ensure_ascii=False))


def cik10(cik):
    m = re.fullmatch(r"\s*(?:CIK)?\s*(\d{1,10})\s*", str(cik), re.I)
    if not m:
        raise FetchError(f'not a CIK: {cik}. Find the company\'s CIK with: mr.py edgar-search "{cik}", '
                         f"or https://www.sec.gov/cgi-bin/browse-edgar?company={urllib.parse.quote(str(cik))}")
    return m.group(1).zfill(10)


_INVISIBLE_RE = re.compile("[­​‌‍⁠﻿]")  # soft hyphens, zero-width characters


def text_of(fragment):
    """Visible text of an HTML/XML fragment, whitespace collapsed and invisible
    characters (soft hyphens such as &shy;, zero-width spaces) removed."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", _INVISIBLE_RE.sub("", text)).strip()
