"""Web footprint: domain registration, Wayback history, GitHub, LinkedIn captures, job boards."""

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from . import common, uk


# ------------------------------------------------------------- footprint ----

RDAP_BOOTSTRAP = "https://data.iana.org/rdap/dns.json"


def whois_query(server, query):
    """One port-43 WHOIS query, for domains whose registry has no RDAP service (.io, .ai)."""
    import socket
    out = b""
    with socket.create_connection((server, 43), timeout=20) as conn:
        conn.sendall((query + "\r\n").encode())
        while len(out) < 1024 * 1024:
            chunk = conn.recv(65536)
            if not chunk:
                break
            out += chunk
    return out.decode("utf-8", "replace")


def whois_domain(domain, query=None):
    """Registration dates and registrar from the registry's WHOIS server, which whois.iana.org names."""
    query = query or whois_query
    tld = domain.rsplit(".", 1)[-1]
    server = next((l.split(":", 1)[1].strip() for l in query("whois.iana.org", tld).splitlines()
                   if l.lower().startswith("whois:")), None)
    if not server:
        return None
    text = query(server, domain)
    field = lambda *keys: next((l.split(":", 1)[1].strip()[:10] for l in text.splitlines()
                                if l.split(":", 1)[0].strip().lower() in keys and ":" in l), None)
    return {"registered": field("creation date", "created", "registered on"),
            "expires": field("registry expiry date", "expiry date", "expires"),
            "last_changed": field("updated date", "changed", "last updated"),
            "registrar": next((l.split(":", 1)[1].strip() for l in text.splitlines()
                               if l.strip().lower().startswith("registrar:") and l.split(":", 1)[1].strip()), None),
            "url": f"whois://{server}/{domain}"}


def _domain_of(text):
    host = urllib.parse.urlparse(text if "//" in text else "//" + text).hostname or text
    return host.lower().removeprefix("www.")


LINKEDIN_CAPTURES = 24  # newest monthly captures read; the archive refuses connections after a burst


def _linkedin_slug(text):
    m = re.search(r"linkedin\.com/company/([^/?#\s]+)", text) or re.fullmatch(r"([A-Za-z0-9_.%-]+)", text.strip())
    return urllib.parse.unquote(m.group(1)).lower() if m else None


def linkedin_page_fields(html_text):
    """The fields LinkedIn's logged-out company page shows, or None for a login wall or an empty capture."""
    text = common.text_of(html_text)
    # the page's structured data carries the count in every version; the visible "View all N employees"
    # line is missing from some
    employees = (re.search(r'"numberOfEmployees":\{"value":(\d+)', html_text)
                 or re.search(r"View all ([\d,]+) employees", text))
    size = re.search(r"Company size ([\d,]+(?:-[\d,]+|\+) employees)", text)
    if not (employees or size):
        return None
    hq = re.search(r"Headquarters (.+?) (?:Type|Founded|Specialties|Locations|Products)\b", text)
    founded = re.search(r"Founded (\d{4})", text)
    followers = re.search(r"([\d,]+) followers", text)
    num = lambda m: int(m.group(1).replace(",", "")) if m else None
    return {"employees": num(employees), "followers": num(followers), "size_band": size.group(1) if size else None,
            "headquarters": hq.group(1) if hq else None, "founded": int(founded.group(1)) if founded else None,
            "quote": (employees or size).group(0)}


def wayback_day(ts):
    """A Wayback timestamp (20261126013741) as a date (2026-11-26)."""
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"


def wayback_closest(url, get, today):
    """The capture of `url` closest to today from the Wayback Availability API, as (timestamp, original), or
    None. It sees a new capture at once, while the CDX index takes hours to list it and is sometimes offline."""
    api = "https://archive.org/wayback/available?" + urllib.parse.urlencode(
        {"url": url, "timestamp": today.strftime("%Y%m%d")})
    try:
        data = json.loads(get(api))
    except (common.FetchError, ValueError):
        return None
    closest = ((data.get("archived_snapshots") or {}).get("closest") or {}) if isinstance(data, dict) else {}
    m = re.search(r"/web/(\d{14})/(.+)$", closest.get("url") or "")
    return (m.group(1), m.group(2)) if m and closest.get("available") and closest.get("status") == "200" else None


class WaybackMonths:
    """The latest Wayback capture of each month for a URL, oldest first, from the CDX index plus the
    Availability API's newest capture, which the index lists only hours later.

    rows   [(timestamp, original)] after `keep`, one a month, sorted by date (CDX groups rows by URL variant)
    cdx    the CDX query, to cite
    error  why the CDX query failed (an outage answers with an HTML page), or None
    added  the timestamp of a capture the Availability API added because CDX had not listed it, or None"""

    def __init__(self, url, get, keep=lambda original: True, today=None):
        self.cdx = "https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(
            {"url": url, "fl": "timestamp,original", "filter": "statuscode:200", "collapse": "timestamp:6",
             "output": "json"})
        self.error = None
        try:
            rows = [(r[0], r[1]) for r in json.loads(get(self.cdx) or "[]")[1:]]
        except (common.FetchError, ValueError) as e:
            rows, self.error = [], str(e)
        rows = [(ts, original) for ts, original in rows if keep(original)]
        latest = wayback_closest(url.rstrip("*"), get, today or dt.date.today())
        self.added = latest[0] if latest and keep(latest[1]) and latest[0] not in {ts for ts, _ in rows} else None
        if self.added:
            rows.append(latest)
        self.rows = list({ts[:6]: (ts, original) for ts, original in sorted(rows)}.values())


def wayback_read(rows, get, sleep=time.sleep, pause=1.5):
    """Each capture's archived copy as (timestamp, original, text or None, error or None), pausing between
    requests, and whether it stopped early: the archive refuses connections after a burst, so three failed
    fetches end the run."""
    out, errors = [], 0
    for i, (ts, original) in enumerate(rows):
        if i:
            sleep(pause)
        try:
            body = get(f"https://web.archive.org/web/{ts}id_/{original}")
        except common.FetchError as e:
            out.append((ts, original, None, str(e)))
            errors += 1
            if errors >= 3:
                return out, i + 1 < len(rows)
            continue
        out.append((ts, original, body if isinstance(body, str) else common.decode_body(body), None))
    return out, False


def linkedin_history(company, get, sleep=time.sleep, captures=LINKEDIN_CAPTURES, today=None):
    """LinkedIn's public company page as the Wayback Machine captured it, one capture a month: the employee
    count LinkedIn shows (members listing the company, not payroll), followers, size band and headquarters."""
    slug = _linkedin_slug(company)
    if not slug:
        yield {"type": "footprint_unavailable", "part": "linkedin", "error": f"not a LinkedIn company page: {company}"}
        return
    # the prefix search also matches longer slugs (acme* finds acme-foods): keep this company's page only
    months = WaybackMonths(f"linkedin.com/company/{slug}*", get, keep=lambda o: _linkedin_slug(o) == slug, today=today)
    if months.error and not months.rows:
        yield {"type": "footprint_unavailable", "part": "linkedin", "error": months.error, "url": months.cdx}
        return
    read, stopped = wayback_read(list(reversed(months.rows[-captures:])), get, sleep)
    snapshots, walls, errors = [], 0, 0
    for ts, original, text, error in read:
        fields = linkedin_page_fields(text) if text is not None else None
        if error:
            errors += 1
        elif not fields:
            walls += 1
        else:
            snap = {"type": "linkedin_snapshot", "date": wayback_day(ts), **fields,
                    "url": f"https://web.archive.org/web/{ts}/{original}"}
            snapshots.append(snap)
            yield snap
    counted = sorted((s for s in snapshots if s["employees"]), key=lambda s: s["date"])
    summary = {"type": "linkedin_summary", "company_page": f"https://www.linkedin.com/company/{slug}/",
               "captures_listed": len(months.rows), "captures_read": len(read),
               "readable": len(snapshots), "login_walls": walls, "fetch_errors": errors, "url": months.cdx}
    if months.added:
        summary["latest_from_availability_api"] = (f"the capture of {wayback_day(months.added)} came from the "
                                                   "Availability API, since the CDX index had not listed it yet")
    if months.error:
        summary["cdx_unavailable"] = (f"the CDX index failed ({months.error}), so only the capture closest to today "
                                      "was read; run again later for the history")
    if len(counted) >= 2:
        a, b = counted[0], counted[-1]
        years = (dt.date.fromisoformat(b["date"]) - dt.date.fromisoformat(a["date"])).days / 365.25
        change = (b["employees"] - a["employees"]) / a["employees"]
        summary["employees_change"] = {"from": a["employees"], "from_date": a["date"], "to": b["employees"],
                                       "to_date": b["date"], "percent": round(100 * change, 1),
                                       "percent_a_year": round(100 * change / years, 1) if years >= 0.25 else None}
    if stopped:
        summary["stopped_early"] = "the archive refused three requests (it limits bursts); run again later for the rest"
    summary["note"] = ("employees is LinkedIn's count of members who list the company, not payroll; most captures of "
                       "LinkedIn are login walls, and small or new companies are rarely captured at all")
    yield summary


def footprint_report(domain, github=None, founded=None, fetcher=None, today=None, whois=None, linkedin=None,
                     sleep=time.sleep):
    """The domain's registration (RDAP), the site's history (Wayback Machine), a GitHub organisation's
    activity, and LinkedIn's archived company page, with a flag when the claimed founding year is older than
    both domain and site."""
    get = fetcher or (lambda u: common.fetch_bytes(u, None))
    today = today or dt.date.today()
    domain = _domain_of(domain)
    years, registered = [], None
    try:
        services = json.loads(get(RDAP_BOOTSTRAP))["services"]
        labels = domain.split(".")
        base = next((urls[0] for i in range(1, len(labels)) for tlds, urls in services
                     if ".".join(labels[i:]) in tlds), None)
        if not base:  # no RDAP for this registry: ask its WHOIS server instead
            try:
                w = whois_domain(domain, whois)
            except OSError as e:
                w, err = None, str(e)
            else:
                err = f"no RDAP service or WHOIS server for .{labels[-1]}"
            if w and w["registered"]:
                years.append(int(w["registered"][:4]))
                registered = w["registered"]
                yield {"type": "footprint_domain", "domain": domain, **w}
            else:
                yield {"type": "footprint_unavailable", "part": "domain",
                       "error": err if not w else "WHOIS gave no creation date"}
        else:
            url = base.rstrip("/") + "/domain/" + domain
            d = json.loads(get(url))
            events = {e.get("eventAction"): (e.get("eventDate") or "")[:10] for e in d.get("events") or []}
            registrar = next((v[3] for e in d.get("entities") or [] if "registrar" in (e.get("roles") or [])
                              for v in (e.get("vcardArray") or [None, []])[1] if v[0] == "fn"), None)
            if events.get("registration"):
                years.append(int(events["registration"][:4]))
                registered = events["registration"]
            yield {"type": "footprint_domain", "domain": domain, "registered": events.get("registration"),
                   "expires": events.get("expiration"), "last_changed": events.get("last changed"),
                   "registrar": registrar, "status": d.get("status"), "url": url}
    except (common.FetchError, ValueError, KeyError) as e:
        yield {"type": "footprint_unavailable", "part": "domain", "error": str(e)}
    cdx = "https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(
        {"url": domain, "fl": "timestamp,statuscode", "collapse": "timestamp:6", "output": "json"})
    try:
        rows = json.loads(get(cdx) or b"[]")[1:]
        if rows:
            by_year = {}
            for ts, status in rows:
                y = by_year.setdefault(ts[:4], {"months": 0, "months_ok": 0})
                y["months"] += 1
                y["months_ok"] += status == "200"
            cut = (registered or "").replace("-", "")
            prior = [ts for ts, _ in rows if cut and ts[:8] < cut]  # a previous owner's site
            own = [ts for ts, _ in rows if not (cut and ts[:8] < cut)]
            first, last = (own[0] if own else None), rows[-1][0]
            if first:
                years.append(int(first[:4]))
            yield {"type": "footprint_wayback", "domain": domain, "first_capture": wayback_day(first) if first else None,
                   "last_capture": wayback_day(last), "by_year": by_year,
                   **({"prior_owner_captures": {"first": wayback_day(prior[0]), "last": wayback_day(prior[-1]), "months": len(prior),
                                                "note": "captures from before the domain's current registration, "
                                                        "usually an earlier owner's site; left out of first_capture"}}
                      if prior else {}),
                   "page": f"https://web.archive.org/web/{(first or rows[0][0])[:8]}000000*/{domain}", "url": cdx}
        else:
            yield {"type": "footprint_wayback", "domain": domain, "first_capture": None, "url": cdx}
    except (common.FetchError, ValueError) as e:
        yield {"type": "footprint_unavailable", "part": "wayback", "error": str(e), "url": cdx}
    if github:
        try:
            org = json.loads(get(f"https://api.github.com/orgs/{github}"))
            repos = json.loads(get(f"https://api.github.com/orgs/{github}/repos?sort=pushed&per_page=100&type=public"))
            own = [r for r in repos if not r.get("fork") and not r.get("archived")]
            pushed = sorted((r.get("pushed_at") or "")[:10] for r in own)
            cutoff = (today - dt.timedelta(days=183)).isoformat()
            yield {"type": "footprint_github", "org": github, "name": org.get("name"), "created": (org.get("created_at") or "")[:10],
                   "public_repos": org.get("public_repos"), "blog": org.get("blog") or None,
                   "last_push": pushed[-1] if pushed else None, "repos_pushed_last_6_months": sum(p >= cutoff for p in pushed),
                   "stars": sum(r.get("stargazers_count") or 0 for r in own),
                   "top_repos": [{"name": r["name"], "stars": r.get("stargazers_count"), "pushed": (r.get("pushed_at") or "")[:10]}
                                 for r in sorted(own, key=lambda r: -(r.get("stargazers_count") or 0))[:5]],
                   "url": f"https://github.com/{github}"}
        except (common.FetchError, ValueError, KeyError, TypeError) as e:
            yield {"type": "footprint_unavailable", "part": "github", "error": str(e)}
    if linkedin:
        yield from linkedin_history(linkedin, get, sleep, today=today)
    if founded and len(years) == 2 and int(founded) < min(years) - 2:
        yield {"type": "footprint_flag", "severity": "review", "founded": int(founded), "domain_registered": years[0],
               "first_capture": years[1],
               "detail": "the claimed founding year is more than two years older than both the domain's registration "
                         "and the site's first archived copy; look for an earlier domain before calling it a red flag"}


# --------------------------------------------------------------- hiring ----

JOB_BOARDS = [  # provider, pattern for the board token in a careers page or URL
    ("greenhouse", r"greenhouse\.io/embed/job_board(?:/js)?\?for=([A-Za-z0-9_-]+)"),
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/([A-Za-z0-9_-]+)"),
    ("lever", r"jobs(?:\.eu)?\.lever\.co/([A-Za-z0-9_-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)"),
    # the providers' APIs, which a careers page that builds its list in JavaScript calls
    ("greenhouse", r"boards-api(?:\.eu)?\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)"),
    ("lever", r"api(?:\.eu)?\.lever\.co/v0/postings/([A-Za-z0-9_-]+)"),
    ("ashby", r"api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9_.-]+)"),
]
BOARD_PAGES = {"greenhouse": ["https://job-boards.greenhouse.io/{t}", "https://boards.greenhouse.io/{t}"],
               "lever": ["https://jobs.lever.co/{t}"]}
BOARD_JOB_LINK = {"greenhouse": r"/{t}/jobs/(\d+)", "lever": r"jobs\.lever\.co/{t}/([0-9a-f-]{{36}})"}


# applicant tracking systems whose boards this command cannot read; named so the report says why
UNSUPPORTED_BOARDS = [("comeet", r"comeet\.(?:co|com)\b"), ("workable", r"apply\.workable\.com|workable\.com/api"),
                      ("smartrecruiters", r"smartrecruiters\.com"), ("bamboohr", r"\.bamboohr\.com"),
                      ("teamtailor", r"teamtailor\.com"), ("recruitee", r"recruitee\.com"),
                      ("personio", r"jobs\.personio\.(?:de|com)"), ("workday", r"myworkdayjobs\.com"),
                      ("icims", r"\.icims\.com"), ("jobvite", r"jobs\.jobvite\.com"),
                      ("factorial", r"factorialhr\.com/ats|\.factorialhr\.com/job_posting")]


def unsupported_board(text):
    """The name of an applicant tracking system the page uses that this command cannot read, or None."""
    for name, pattern in UNSUPPORTED_BOARDS:
        if re.search(pattern, text, re.I):
            return name
    return None


def find_job_board(text):
    """(provider, token) for the first job board linked from a careers page, or None."""
    for provider, pattern in JOB_BOARDS:
        for m in re.finditer(pattern, text):
            if m.group(1).lower() not in ("embed", "jobs", "js"):
                return provider, m.group(1)
    return None


def job_board_openings(provider, token, get):
    """Open roles as (title, department, location[, posted date]) from the provider's public jobs API."""
    if provider == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/departments"
        jobs = [(j.get("title"), d.get("name"), (j.get("location") or {}).get("name"))
                for d in json.loads(get(url)).get("departments") or [] for j in d.get("jobs") or []]
    elif provider == "lever":
        url = f"https://api.lever.co/v0/postings/{token}?mode=json"
        jobs = [(j.get("text"), (j.get("categories") or {}).get("team"), (j.get("categories") or {}).get("location"),
                 dt.datetime.fromtimestamp(j["createdAt"] / 1000, dt.timezone.utc).date().isoformat()
                 if isinstance(j.get("createdAt"), (int, float)) else None)
                for j in json.loads(get(url))]
    else:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
        jobs = [(j.get("title"), j.get("department"), j.get("location"), (j.get("publishedAt") or "")[:10] or None)
                for j in json.loads(get(url)).get("jobs") or [] if j.get("isListed", True)]
    return jobs, url


def job_history(provider, token, get, months=12, pause=1.0, sleep=time.sleep, today=None):
    """Approximate open-role counts from monthly Wayback Machine snapshots of the board page."""
    link = BOARD_JOB_LINK.get(provider)
    if not link:
        yield {"type": "jobs_history_unavailable", "provider": provider,
               "note": "this provider's board page is built by JavaScript, so archived copies hold no job list; "
                       "use the jobs_posting_ages record (posting dates of the roles open now) instead"}
        return
    pattern = re.compile(link.format(t=re.escape(token)))
    for page in BOARD_PAGES[provider]:
        archived = WaybackMonths(page.format(t=token), get, today=today)
        if archived.rows:
            break
    if not archived.rows:
        yield {"type": "jobs_history_unavailable", "provider": provider, "note": "no archived copies of the board page",
               **({"error": archived.error} if archived.error else {})}
        return
    read, stopped = wayback_read(archived.rows[-months:], get, sleep, pause)
    for ts, original, text, error in read:
        snap = f"https://web.archive.org/web/{ts}id_/{original}"
        if error:
            yield {"type": "jobs_snapshot_unreadable", "date": wayback_day(ts), "error": error}
        else:
            yield {"type": "jobs_snapshot", "date": wayback_day(ts), "open_roles": len(set(pattern.findall(text))),
                   "approximate": True, "url": snap}
    if stopped:
        yield {"type": "jobs_snapshot_unreadable", "error": "the archive refused three requests (it limits bursts); "
                                                            "the older months were not read, so run again later"}


def jobs_report(target, history=False, fetcher=None, pause=1.0, offices=()):
    """Open roles from the company's job board, by department and location, and
    optionally a monthly trend from archived copies of the board page. `offices`
    (cities or countries) picks between boards guessed from the domain name."""
    get = fetcher or (lambda u: common.fetch(u, None))
    m = re.fullmatch(r"(greenhouse|lever|ashby):([A-Za-z0-9_.-]+)", target)
    board = (m.group(1), m.group(2)) if m else find_job_board(target)
    other_ats = None
    if not board:
        try:
            page = get(target)
        except common.FetchError as e:  # a site that refuses scripts can still have a board under its domain's name
            yield {"type": "jobs_page_unreadable", "url": target, "error": str(e),
                   "note": "the careers page could not be read (do not retry it another way); trying boards named "
                           "after the domain instead"}
            page = ""
        board = find_job_board(page)
        other_ats = None if board else unsupported_board(page)
    guessed = False
    if not board:  # many careers pages build the job list in JavaScript; try the domain's name as the board
        label = (urllib.parse.urlparse(target).hostname or "").removeprefix("www.").split(".")[0]
        words = [o.lower() for o in offices if o.strip()]
        candidates = []
        for provider in ("greenhouse", "ashby", "lever"):
            try:
                found = job_board_openings(provider, label, get)[0] if label else []
            except (common.FetchError, ValueError):
                continue
            if found:  # another company can own the same name on another provider ("lovable" on Greenhouse)
                places = {}
                for j in found:
                    places[j[2] or "unspecified"] = places.get(j[2] or "unspecified", 0) + 1
                candidates.append({"provider": provider, "board": label, "open_roles": len(found),
                                   "top_locations": [k for k, _ in sorted(places.items(), key=lambda x: -x[1])[:5]],
                                   "office_matches": sum(1 for j in found if j[2] and any(w in j[2].lower() for w in words))})
        if len(candidates) > 1:
            yield {"type": "jobs_board_candidates", "candidates": candidates, "offices": list(offices),
                   "note": "several providers have a board with the domain's name; compare their locations with the "
                           "company's offices"}
        best = max((c["office_matches"] for c in candidates), default=0)
        picks = [c for c in candidates if c["office_matches"] == best] if words else candidates
        if len(picks) == 1:
            board, guessed, guess = (picks[0]["provider"], label), True, picks[0]
        elif candidates:
            yield {"type": "jobs_board_ambiguous", "url": target,
                   "note": "no single board matches the offices given (--offices); rerun with provider:token "
                           "for the company's own board"}
            return
    if not board and other_ats:
        yield {"type": "jobs_board_unsupported", "provider": other_ats, "url": target,
               "note": f"the careers page uses {other_ats}, whose board this command cannot read; count the roles on the "
                       "careers page by hand, and say under Gaps that no trend was measured"}
        return
    if not board:
        yield {"type": "jobs_board_unknown", "url": target,
               "note": "no Greenhouse, Lever or Ashby board is linked from this page; pass provider:token if you know it"}
        return
    provider, token = board
    try:
        jobs, url = job_board_openings(provider, token, get)
    except (common.FetchError, ValueError) as e:
        yield {"type": "error", "error": f"{provider} board {token}: {e}"}
        return
    if guessed:
        yield {"type": "jobs_board_guessed", "provider": provider, "board": token, "url": url,
               **({"offices": list(offices), "office_matches": guess["office_matches"]} if words else {}),
               "note": "the careers page links no board, so this one was found by the company's domain name; "
                       "check that its locations are the company's offices before using the counts"
                       + ("; none of its roles is in an office given, so it may be another company's board"
                          if words and not guess["office_matches"] else "")}

    def tally(i):
        counts = {}
        for j in jobs:
            counts[j[i] or "unspecified"] = counts.get(j[i] or "unspecified", 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))
    yield {"type": "jobs_openings", "provider": provider, "board": token, "open_roles": len(jobs),
           "by_department": tally(1), "by_location": dict(list(tally(2).items())[:15]), "url": url}
    posted = sorted(j[3] for j in jobs if len(j) > 3 and j[3])
    if posted:
        today = dt.date.today()
        ages = sorted((today - uk._date(d)).days for d in posted)
        months = {}
        for d in posted:
            if (today - uk._date(d)).days <= 366:
                months[d[:7]] = months.get(d[:7], 0) + 1
        yield {"type": "jobs_posting_ages", "provider": provider, "dated_roles": len(posted),
               "posted_by_month": dict(sorted(months.items())), "median_age_days": ages[len(ages) // 2],
               "oldest": posted[0], "newest": posted[-1], "url": url,
               "note": "the open roles by the month they were posted: a proxy for recent hiring, not a count of past "
                       "openings (roles filled or withdrawn are gone). Many old roles still open can mean evergreen "
                       "or stale postings"}
    if history:
        yield from job_history(provider, token, get, pause=pause)
