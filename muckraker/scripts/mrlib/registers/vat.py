"""EU VAT numbers in VIES."""

import json
import re
from .. import common


# ------------------------------------------------------------ EU VAT (VIES) ----

VIES_API = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{cc}/vat/{number}"
VIES_COUNTRIES = {"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU", "IE", "IT", "LT",
                  "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "XI"}


def vat_report(country, number, fetcher=None):
    """An EU VAT number checked in VIES: whether it is valid now, and the registered name and address
    where the member state discloses them (Italy, Sweden, France and others do; Spain and Germany do not)."""
    get = fetcher or (lambda u: common.fetch(u, None))
    cc = country.strip().upper().replace("GR", "EL")
    num = re.sub(r"[\s.\-/]", "", number).upper()
    if num.startswith(cc):
        num = num[len(cc):]
    if cc not in VIES_COUNTRIES:
        yield {"type": "vat_note", "note": f"VIES covers EU member states (and XI for Northern Ireland), not {country}"}
        return
    url = VIES_API.format(cc=cc, number=num)
    d = json.loads(get(url))
    name = (d.get("name") or "").strip()
    address = re.sub(r"\s*\n\s*", ", ", (d.get("address") or "").strip()).strip(", ")
    hidden = name in ("", "---")
    yield {"type": "vat_record", "country": cc, "vat_number": f"{cc}{num}", "valid": d.get("isValid"),
           "name": None if hidden else name, "address": None if address in ("", "---") else address,
           "checked": (d.get("requestDate") or "")[:10] or None, "url": url,
           "note": ("this member state does not disclose the name or address through VIES; the check shows only "
                    "whether the number is valid" if hidden else
                    "the name the tax authority holds now: compare it with the name the company uses, since a "
                    "renamed holding keeps its brand in the press")
                   + ("" if d.get("isValid") else "; an invalid number can be a typo, a deregistered company, or a "
                                                  "group VAT registration under another number")}
