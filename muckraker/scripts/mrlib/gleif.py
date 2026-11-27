"""GLEIF: LEI search, an LEI's record, its parent chain and subsidiaries."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from . import common


# ---------------------------------------------------------------- GLEIF ----

GLEIF = "https://api.gleif.org/api/v1"
LEI_RE = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
OFFSHORE = {  # ISO 3166 codes of common secrecy and offshore jurisdictions
    "VG": "British Virgin Islands", "KY": "Cayman Islands", "BM": "Bermuda", "JE": "Jersey",
    "GG": "Guernsey", "IM": "Isle of Man", "PA": "Panama", "SC": "Seychelles", "BS": "Bahamas",
    "BZ": "Belize", "MH": "Marshall Islands", "AI": "Anguilla", "TC": "Turks and Caicos Islands",
    "GI": "Gibraltar", "LI": "Liechtenstein", "MU": "Mauritius", "VU": "Vanuatu", "WS": "Samoa",
    "CW": "Curaçao", "KN": "Saint Kitts and Nevis", "LB": "Lebanon", "CK": "Cook Islands",
}


def gleif_json(path, fetcher=None):
    """GLEIF API response as a dict, or None for 404 (no such relationship)."""
    try:
        return json.loads((fetcher or (lambda u: common.fetch(u, None)))(GLEIF + path))
    except common.FetchError as e:
        if "HTTP 404" in str(e):
            return None
        raise


def gleif_entity(record):
    a = record["attributes"]
    e, reg = a["entity"], a["registration"]
    addr = e.get("legalAddress") or {}
    hq = e.get("headquartersAddress") or {}

    def one_line(x):
        return ", ".join(p for p in [*(x.get("addressLines") or []), x.get("city"), x.get("region"),
                                     x.get("postalCode"), x.get("country")] if p) or None
    return {
        "lei": a["lei"],
        "legal_name": e["legalName"]["name"],
        "other_names": [n["name"] for n in e.get("otherNames") or []],
        "jurisdiction": e.get("jurisdiction"),
        "country": (e.get("jurisdiction") or "")[:2] or addr.get("country"),
        "legal_form": (e.get("legalForm") or {}).get("id"),
        "registered_as": e.get("registeredAs"),
        "registration_authority": ((e.get("registeredAt") or {}).get("id")),
        "entity_status": e.get("status"),
        "lei_status": reg.get("status"),
        "category": e.get("category"),
        "legal_form_other": (e.get("legalForm") or {}).get("other"),
        "initial_registration": reg.get("initialRegistrationDate"),
        "last_update": reg.get("lastUpdateDate"),
        "next_renewal": reg.get("nextRenewalDate"),
        "legal_address": one_line(addr),
        "headquarters_address": one_line(hq),
        "url": f"{GLEIF}/lei-records/{a['lei']}",
    }


LEGAL_FORM_WORDS = {
    "inc", "incorporated", "ltd", "limited", "llc", "llp", "lp", "plc", "corp", "corporation", "company", "co",
    "holdings", "holding", "group", "the", "and", "of", "sa", "ag", "gmbh", "bv", "nv", "sarl", "sas", "srl",
    "spa", "ab", "as", "asa", "oy", "kft", "sro", "pty", "pte", "kk", "se", "aps", "l", "p",
}


def distinctive_words(name):
    return {w for w in re.findall(r"\w+", name.lower()) if w not in LEGAL_FORM_WORDS and len(w) > 1}


def gleif_search(name, limit, fetcher=None, registered_as=None):
    """LEI candidates by name, or by the entity's number in its national register (KVK, SIREN, HRB...)."""
    if registered_as:
        q = urllib.parse.urlencode({"filter[entity.registeredAs]": registered_as, "page[size]": str(limit)})
    else:
        q = urllib.parse.urlencode({"filter[fulltext]": name, "page[size]": str(limit)})
    data = gleif_json(f"/lei-records?{q}", fetcher) or {"data": []}
    records = data.get("data", [])
    # full-text search ranks loose matches too ("Snyk, Inc." returns car dealers);
    # keep candidates whose name or other names share a word with the query beyond its legal form
    wanted = set() if registered_as else distinctive_words(name)
    kept, dropped = 0, 0
    for rec in records:
        ent = gleif_entity(rec)
        if wanted and not wanted & distinctive_words(" ".join([ent["legal_name"] or "", *ent["other_names"]])):
            dropped += 1
            continue
        kept += 1
        yield {"type": "gleif_candidate", **{k: ent[k] for k in (
            "lei", "legal_name", "category", "jurisdiction", "registered_as", "entity_status", "lei_status",
            "legal_address", "url")}}
    if not kept:  # no LEI is itself a result; say so rather than print nothing
        note = ("no LEI record has this registration number; try the name" if registered_as else
                "no LEI record matches this name; try another spelling or a parent's name")
        if dropped:
            note += f" ({dropped} loose matches sharing none of the name's words were left out)"
        yield {"type": "gleif_no_match", "query": registered_as or name, "url": f"{GLEIF}/lei-records?{q}", "note": note}


def gleif_exception(lei, level, fetcher=None):
    data = gleif_json(f"/lei-records/{lei}/{level}-parent-reporting-exception", fetcher)
    return ((data or {}).get("data") or {}).get("attributes", {}).get("reason")


def gleif_children(lei, level, max_children, fetcher=None):
    out, page = [], 1
    while len(out) < max_children:
        data = gleif_json(f"/lei-records/{lei}/{level}-children?page[size]=100&page[number]={page}", fetcher)
        rows = (data or {}).get("data") or []
        out += [gleif_entity(r) for r in rows]
        last = ((data or {}).get("meta", {}).get("pagination") or {}).get("lastPage", 1)
        if not rows or page >= last:
            break
        page += 1
    return out[:max_children]


def gleif_report(lei, max_children=200, fetcher=None):
    """The entity, its parent chain (or why there is none), and its subsidiaries."""
    data = gleif_json(f"/lei-records/{lei}", fetcher)
    if not data:
        yield {"type": "error", "error": f"no LEI record {lei}"}
        return
    entity = gleif_entity(data["data"])
    yield {"type": "gleif_entity", **entity}
    if entity["category"] == "FUND":
        links = {}
        for rel in ("umbrella-fund", "fund-manager"):
            rec = gleif_json(f"/lei-records/{lei}/{rel}", fetcher)
            if rec and rec.get("data"):
                links[rel.replace("-", "_")] = gleif_entity(rec["data"])["legal_name"]
        yield {"type": "gleif_fund", "lei": lei, "legal_name": entity["legal_name"],
               "legal_form_other": entity["legal_form_other"], **links,
               "note": "this LEI is a fund vehicle, often an investor's fund named after a holding, not the operating "
                       "company; do not use it as the company's LEI"}
    if entity["lei_status"] in ("LAPSED", "RETIRED", "ANNULLED"):
        yield {"type": "gleif_lapsed", "lei": lei, "lei_status": entity["lei_status"],
               "last_update": entity["last_update"], "legal_name": entity["legal_name"],
               "note": "the LEI is not maintained, so its name, address and parents date from its last update; "
                       "check the name against the company register before relying on them"}

    chain, current, seen = [], lei, {lei}
    while len(chain) < 10:
        parent = gleif_json(f"/lei-records/{current}/direct-parent", fetcher)
        if not parent or not parent.get("data"):
            reason = gleif_exception(current, "direct", fetcher)
            yield {"type": "gleif_chain_end", "at_lei": current, "exception_reason": reason,
                   "note": "no direct parent reported" + (f" (reason: {reason})" if reason else "")}
            break
        p = gleif_entity(parent["data"])
        if p["lei"] in seen:
            break
        seen.add(p["lei"])
        chain.append(p)
        yield {"type": "gleif_parent", "level": len(chain), "child_lei": current, **p}
        current = p["lei"]
    ultimate = gleif_json(f"/lei-records/{lei}/ultimate-parent", fetcher)
    if ultimate and ultimate.get("data"):
        u = gleif_entity(ultimate["data"])
        if u["lei"] not in seen:
            yield {"type": "gleif_ultimate_parent", **u}
            chain.append(u)
    elif not chain:
        reason = gleif_exception(lei, "ultimate", fetcher)
        yield {"type": "gleif_no_ultimate_parent", "exception_reason": reason}

    offshore = [p for p in chain if p["country"] in OFFSHORE]
    for p in offshore:
        yield {"type": "gleif_flag", "flag": "offshore parent", "lei": p["lei"], "legal_name": p["legal_name"],
               "country": p["country"], "country_name": OFFSHORE[p["country"]], "url": p["url"]}

    kids = {k["lei"]: k for k in gleif_children(lei, "direct", max_children, fetcher)}
    for k in gleif_children(lei, "ultimate", max_children, fetcher):
        kids.setdefault(k["lei"], k)
    for k in kids.values():
        yield {"type": "gleif_child", **{f: k[f] for f in (
            "lei", "legal_name", "jurisdiction", "country", "entity_status", "lei_status", "url")}}
    countries = sorted({k["country"] for k in kids.values() if k["country"]})
    yield {"type": "gleif_summary", "lei": lei, "parents": len(chain), "children": len(kids),
           "child_countries": countries,
           "child_countries_outside_us_uk": [c for c in countries if c not in ("US", "GB")],
           "offshore_parents": [p["lei"] for p in offshore]}
