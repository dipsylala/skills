# Sanctions and offshore

Screen the company, its group, and the people in its leadership against sanctions lists, and look for it in the offshore leaks databases. Search the legal name, trading and former names, the parent and acquisition-company names in the entity record, and the officers, directors, and controlling persons the record names.

## Where to look

- **OpenSanctions** combines the US, UK, EU, UN, and other sanctions lists with politically exposed persons (PEPs). With a key in the `OPENSANCTIONS_API_KEY` environment variable, call `https://api.opensanctions.org/search/default?q=<name>` with the header `Authorization: ApiKey <key>`, and keep the key out of your report. Without a key, the API returns 401: fetch the website search, `https://www.opensanctions.org/search/?q=<name>`, instead.
- **OFAC SDN list** (US Treasury), the official US list: `https://www.treasury.gov/ofac/downloads/sdn.csv`, a free CSV of about 6 MB. Download it once and search it for each name. Use it to confirm any US sanctions hit OpenSanctions shows.
- **ICIJ Offshore Leaks** (Panama Papers, Paradise Papers, Pandora Papers, and others). The website search answers fetch tools with an empty bot-check page, so use its reconciliation API: POST `https://offshoreleaks.icij.org/api/v1/reconcile` with the body `{"queries":{"q0":{"query":"<name>"}}}`. Each result has an `id`, a `name`, the leak it came from, and a score; the node's page is `https://offshoreleaks.icij.org/nodes/<id>`, which you can open in a browser tool if you have one.

## Checks

1. **Sanctions:** any listing of the company, a group company, or a named officer or controlling person, with the list, the programme, the listing date, and the identifiers the list gives (country, registration number, date of birth month and year). Check each hit against the entity record's identifiers; a name match alone is a possible match, and goes under Gaps with its URL.
2. **PEPs:** any officer, director, or controlling person listed as a politically exposed person, with the position the list gives.
3. **Offshore leaks:** any node whose name matches the company, a group company, or a named person, with the leak, the node type (entity, officer, intermediary), its jurisdiction, and its linked entities. Check the match against the entity record before reporting it.

Report as red flags: a sanctions listing of the company, a group company, or a named officer or controlling person (established, by the listing body's decision); and an appearance in an offshore leak that ICIJ's reporting ties to wrongdoing (an allegation). A PEP listing, or a leak appearance with no reported wrongdoing, goes under Facts: holding an offshore company is not itself wrongdoing.
