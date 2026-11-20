# GLEIF ownership

The Global Legal Entity Identifier Foundation (GLEIF) publishes every Legal Entity Identifier (LEI) and, for most of them, the entity's direct and ultimate accounting parent. It covers every country, needs no key, and is often the quickest way to see a group's ownership chain and where its subsidiaries are registered.

## Access

Base: `https://api.gleif.org/api/v1`. Responses are JSON.

- Find the LEI: `/lei-records?filter[entity.legalName]=<name>`, or `/fuzzycompletions?field=entity.legalName&q=<name>` for near spellings. Match the result's jurisdiction, registered address, and registration authority ID against the entity record.
- Record: `/lei-records/<LEI>`.
- Parents: `/lei-records/<LEI>/direct-parent` and `/ultimate-parent`. A 404 means no parent is reported; then read `/direct-parent-reporting-exception` and `/ultimate-parent-reporting-exception`, whose `reason` says why (for example `NATURAL_PERSONS`, `NON_CONSOLIDATING`, `NO_KNOWN_PERSON`, `NON_PUBLIC`).
- Subsidiaries: `/lei-records/<LEI>/direct-children` and `/ultimate-children` (paged).

## Checks

1. **Record:** LEI, legal name, other names, legal form, jurisdiction, registration authority and the entity's ID in it, legal and headquarters addresses, entity status, LEI status (`ISSUED`, `LAPSED`, `RETIRED`), and last update date.
2. **Parents:** walk the chain from the entity to its ultimate parent, recording each parent's name, LEI, and jurisdiction. Where the chain stops, record the reporting exception and its reason.
3. **Subsidiaries:** list the direct and ultimate children with their jurisdictions, and name the countries other than the US and UK, so the coordinator can see which national registers apply.
4. **Group entities:** look up the parent and acquisition-company names in the entity record the same way, since they often hold an LEI when the operating company does not.

Report as a red flag, established by the GLEIF record, a parent chain that runs through an offshore jurisdiction (British Virgin Islands, Cayman Islands, Bermuda, Jersey, Guernsey, Isle of Man, Panama, Seychelles, and similar), or a parent withheld with the reason `NON_PUBLIC`. A lapsed LEI goes under Facts.
