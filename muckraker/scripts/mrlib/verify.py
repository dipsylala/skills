"""Quote checks and verify-report: confirm each red flag's quote on its cited page."""

import os
import re
from . import common
from .registers import no


# ------------------------------------------------------- verify-report -----

_URL_RE = re.compile(r"https?://[^\s<>()\"'`\]]+")
# "Quote:", or with a label in brackets: "Quote (table row):"
_QUOTE_LINE_RE = re.compile(r"\bQuote(?:\s*\([^)\n]*\))?\s*:\s*(.+)", re.I)
JS_SHELL_CHARS = 300  # a page with less visible text than this, outside its scripts, is built by JavaScript
# bot checks answer with HTTP 200 and their own page; the quote is never on it
_BOT_CHECK_RE = re.compile(r"<title>\s*(just a moment|attention required|radware block page|access denied|"
                           r"request blocked|are you a robot|human verification)", re.I)
_QUOTED_RE = re.compile(r"[\"“](.+?)[\"”]|`([^`]+)`")


def parse_red_flags(markdown):
    """Red-flag items from a report: each with its title, URLs, and quote.

    The section starts at a 'Red flags' heading or bold label and ends at the next
    heading or bold section label; items are top-level numbered or bulleted lines,
    with their indented continuation lines."""
    lines = markdown.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if re.match(r"^\s*(#+\s*|\*\*)\s*Red flags\b", l, re.I)), None)
    if start is None:
        return []
    first = next((l for l in lines[start + 1:] if l.strip()), "")
    if re.match(r"^\s*(none|no red flags)\b", first, re.I):  # "None." then explanatory bullets
        return []
    items, current = [], None
    for line in lines[start + 1:]:
        if re.match(r"^(#+\s|\*\*(Gaps|Facts|Sources)\b)", line):
            break
        if re.match(r"^(\d+[.)]|[-*])\s+", line):  # a new top-level item
            current = [line]
            items.append(current)
        elif current is not None and line.strip():
            current.append(line)
    flags = []
    for n, block in enumerate(items, 1):
        text = "\n".join(block)
        if re.match(r"^(\d+[.)]|[-*])\s+(none|no red flags)\b", block[0], re.I):
            continue
        title = re.search(r"\*\*(.+?)\*\*", block[0])
        quote = None
        m = _QUOTE_LINE_RE.search(text)
        if m:
            q = _QUOTED_RE.search(m.group(1))
            quote = (q.group(1) or q.group(2)) if q else m.group(1).strip()
        urls = list(dict.fromkeys(u.rstrip(".,;:") for u in _URL_RE.findall(text)))
        flags.append({"index": n, "title": title.group(1) if title else block[0][:120].strip(),
                      "urls": urls, "quote": quote})
    return flags


MIN_QUOTE_WORDS = 4


def quote_warnings(page, quote, matched):
    """Why a found quote may still not prove the flag: too short to carry the
    flagged figures, or matched in several places (the context shows the first)."""
    warnings = []
    # an XBRL fact quoted with its tag (<fsa:Equity>-760000000</fsa:Equity>, or an N-PORT
    # <valUSD>) names what the figure is, so it needs no surrounding words
    tagged_fact = re.search(r"<([\w.-]+:)?[A-Za-z][\w.-]*[^>]*>[^<]*\w[^<]*</", quote)
    if not tagged_fact and len(re.findall(r"\w+", re.sub(r"<[^>]+>", " ", quote))) < MIN_QUOTE_WORDS:
        warnings.append(f"quote has fewer than {MIN_QUOTE_WORDS} words, so finding it does not show the flagged "
                        "figures; quote the whole row or sentence")
    count = page.count(matched) if matched else 0
    if count > 1:
        warnings.append(f"quote appears {count} times on the page; the context shows the first, "
                        "which may be another row or period")
    return warnings


def verify_reports(paths, user_agent, fetcher=None):
    """Check every red flag's quote against its cited pages. Each page is fetched
    once; a flag passes when its quote is found on any URL it cites."""
    fetcher = fetcher or (lambda u: common.fetch(u, user_agent))
    pages = {}
    totals = {"confirmed": 0, "not_found": 0, "js_page": 0, "unreachable": 0, "too_large": 0, "no_text_layer": 0,
              "no_quote": 0, "no_url": 0}

    def page_text(url):
        if url not in pages:
            try:
                body = fetcher(url)
                if body.lstrip()[:5] == "%PDF-":  # a PDF has no searchable text here (often a scan)
                    pages[url] = ("pdf", None)
                elif _BOT_CHECK_RE.search(body[:5000]):
                    pages[url] = ("error", "the site answered with a bot check, not the page (do not retry it another "
                                           "way; check the quote in a browser)")
                elif "<script" in body.lower() and len(common.text_of(re.sub(
                        r"(?is)<(script|style|noscript|template)\b.*?</\1\s*>", "", body))) < JS_SHELL_CHARS:
                    pages[url] = ("js", no.searchable_text(body).lower())  # an app shell: the data loads later
                else:
                    pages[url] = ("ok", no.searchable_text(body).lower())
            except common.FetchError as e:
                pages[url] = ("error", str(e))
        return pages[url]

    for path in paths:
        report = pathlib_name(path)
        with open(path, encoding="utf-8", errors="replace") as f:
            flags = parse_red_flags(f.read())
        for flag in flags:
            record = {"type": "red_flag_check", "report": report, **flag}
            if not flag["quote"] or not flag["urls"]:
                record["result"] = "no_quote" if not flag["quote"] else "no_url"
                totals[record["result"]] += 1
                yield record
                continue
            errors, pdfs, shells = [], [], []
            for url in flag["urls"]:
                status, text = page_text(url)
                if status == "js":
                    shells.append(url)
                if status == "error":
                    errors.append(f"{url}: {text}")
                    continue
                if status == "pdf":
                    pdfs.append(url)
                    continue
                pos, span = no.find_quote(text, flag["quote"])
                if pos >= 0:
                    # an XML quote's match starts at its first element; context before it
                    # belongs to the previous holding, so start there
                    lead = 0 if re.search(r"<[A-Za-z/][^>]*>", flag["quote"]) else 80
                    record.update(result="confirmed", matched_url=url,
                                  context=text[max(0, pos - lead): pos + span + 80])
                    warnings = quote_warnings(text, flag["quote"], text[pos:pos + span])
                    if warnings:
                        record["warnings"] = warnings
                    totals["confirmed"] += 1
                    break
            else:
                if shells and len(shells) + len(pdfs) + len(errors) == len(flag["urls"]):
                    record.update(result="js_page", js_pages=shells,
                                  note="the cited page is built by JavaScript, so its data is not in the fetched HTML; "
                                       "open it in a browser and check the quote there")
                    totals["js_page"] += 1
                elif pdfs and len(pdfs) + len(errors) == len(flag["urls"]):
                    record.update(result="no_text_layer", pdfs=pdfs,
                                  note="the cited page is a PDF with no text to search (often a scan); read it yourself")
                    totals["no_text_layer"] += 1
                elif errors and all("larger than" in e for e in errors):
                    record.update(result="too_large", errors=errors,
                                  note="the cited file is over the size limit (bulk open data, such as Luxembourg's "
                                       "Centrale des Bilans files); check the quote against the run folder's extract "
                                       "with mr.py quote-check <extract file> \"<quote>\"")
                    totals["too_large"] += 1
                elif errors and len(errors) == len(flag["urls"]):
                    no_contact = all("needs --user-agent" in e for e in errors)
                    record.update(result="unreachable", errors=errors,
                                  note="sec.gov pages need the SEC contact: rerun with --user-agent (it is sent to "
                                       "sec.gov only), or check the quote with quote-check" if no_contact
                                  else "no cited page could be fetched; check it in a browser")
                    totals["unreachable"] += 1
                else:
                    record.update(result="not_found", errors=errors or None)
                    totals["not_found"] += 1
            yield record
    yield {"type": "verify_summary", "reports": len(paths), **totals}


def pathlib_name(path):
    return os.path.basename(path)


def is_source_report(path):
    """A source report starts with its SOURCE: line (entity.md and notes do not)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        head = f.read(2000)
    return re.search(r"^\W*SOURCE:", head, re.M) is not None


def report_paths(targets):
    out = []
    for t in targets:
        if os.path.isdir(t):
            out += sorted(os.path.join(t, n) for n in os.listdir(t)
                          if n.endswith(".md") and n != "dossier.md" and is_source_report(os.path.join(t, n)))
        else:
            out.append(t)
    return out
