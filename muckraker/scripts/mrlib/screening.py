"""Screening: the US Consolidated Screening List and ICIJ Offshore Leaks."""

import json
import re
from . import common, gleif, us


# --------------------------------------------------- screening list (CSL) ----

CSL_CSV = "https://data.trade.gov/downloadable_consolidated_screening_list/v1/consolidated.csv"


def csl_report(names, fetcher=None):
    """Entries naming the company in the US Consolidated Screening List (OFAC, BIS, State lists in one file)."""
    import csv
    import io
    get = fetcher or (lambda u: common.fetch_bytes(u, None))
    try:
        text = common.decode_body(get(CSL_CSV))
    except common.FetchError as e:
        yield {"type": "csl_unavailable", "error": str(e), "url": CSL_CSV}
        return
    csv.field_size_limit(max(csv.field_size_limit(), 10 * 1024 * 1024))
    lists, rows, found = {}, 0, 0
    for row in csv.DictReader(io.StringIO(text)):
        rows += 1
        source = row.get("source") or ""
        lists[source] = lists.get(source, 0) + 1
        aliases = [a.strip() for a in (row.get("alt_names") or "").split(";") if a.strip()]
        hits = [n for n in names if any(us._name_match(n, t) for t in [row.get("name") or ""] + aliases)]
        if not hits:
            continue
        found += 1
        listed = re.search(r"Listing Date[^,;]*,\s*(\d{4}-\d{2}-\d{2})", row.get("ids") or "")
        if listed and not row.get("start_date"):
            row["start_date"] = listed.group(1)
        yield {"type": "csl_match", "query": hits, "list": source, "name": row.get("name"),
               "entity_type": row.get("type") or None,
               **{k: row.get(k) or None for k in ("programs", "addresses", "start_date", "end_date",
                                                  "federal_register_notice", "license_requirement", "ids")},
               "alt_names": aliases or None, "remarks": (row.get("remarks") or "")[:300] or None,
               "source_list_url": row.get("source_list_url") or None,
               "source_information_url": row.get("source_information_url") or None, "url": CSL_CSV}
    yield {"type": "csl_summary", "query": names, "entries_searched": rows, "matches": found,
           "lists": sorted(lists), "url": CSL_CSV,
           "note": "a match shares every distinctive word of a name and is not yet the company: compare the address, "
                   "country, and identifiers with the entity record before reporting it. The file does not include "
                   "the UFLPA Entity List, the Section 1260H list, the FCC Covered List, or SAM.gov exclusions"}


# ------------------------------------------------------- offshore leaks ----

ICIJ_RECONCILE = "https://offshoreleaks.icij.org/api/v1/reconcile"
ICIJ_NODE = "https://offshoreleaks.icij.org/api/v1/rest/nodes/"


def icij_report(names, poster=None, fetcher=None, limit=25, max_nodes=30):
    """ICIJ Offshore Leaks nodes whose names contain every distinctive word of a name, with each node's
    leak, countries, and data date."""
    post = poster or (lambda body: us.post_json(ICIJ_RECONCILE, body))
    get = fetcher or (lambda u: common.fetch_bytes(u, None))
    queries = {f"q{i}": {"query": n, "limit": limit} for i, n in enumerate(names)}
    try:
        reply = post({"queries": queries})
    except (common.FetchError, ValueError) as e:
        yield {"type": "icij_unavailable", "error": str(e), "url": ICIJ_RECONCILE}
        return
    found, loose, nodes = {}, 0, 0
    for key, q in queries.items():
        for r in (reply.get(key) or {}).get("result") or []:
            kind = ((r.get("types") or [{}])[0]).get("name")
            if kind == "Address" or not us._name_match(q["query"], r.get("name")):
                loose += 1
                continue
            if r["id"] in found:
                found[r["id"]]["query"].append(q["query"])
                continue
            rec = {"type": "icij_node", "query": [q["query"]], "id": r["id"], "name": r.get("name"), "node_type": kind,
                   "description": r.get("description"), "url": f"https://offshoreleaks.icij.org/nodes/{r['id']}"}
            extra = sorted(gleif.distinctive_words(r.get("name") or "") - gleif.distinctive_words(q["query"]))
            if extra:  # "Vuppala Rao - Sameer" for "Sameer Rao": a different person until shown otherwise
                rec["extra_words"] = extra
            if nodes < max_nodes:
                nodes += 1
                try:
                    props = json.loads(get(ICIJ_NODE + str(r["id"]))).get("properties") or {}
                    rec.update({k: v for k, v in {
                        "leak": props.get("data_source"), "countries": props.get("country_codes"),
                        "jurisdiction": props.get("jurisdiction_description") or props.get("jurisdiction"),
                        "incorporated": props.get("incorporation_date"), "status": props.get("status"),
                        "data_current_to": props.get("valid_until")}.items() if v})
                except (common.FetchError, ValueError):
                    pass
            found[r["id"]] = rec
    yield from found.values()
    yield {"type": "icij_summary", "query": names, "matches": len(found), "loose_results_dropped": loose,
           "note": "a match shares every distinctive word of a name, which is not proof it is the company or person: "
                   "compare the node's countries, dates, and linked entities (open its `url`) with the entity record. "
                   "Appearing in a leak is not wrongdoing in itself"}
