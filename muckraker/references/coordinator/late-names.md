# Names found late

Reports often name group companies, people, and owners the entity record lacked. Follow up each kind below in SKILL.md step 4, before confirming red flags.

## Companies

An ultimate parent or controlling party in a subsidiary's accounts, the entity a rating agency rates, a borrower or holding vehicle in lenders' filings. For each such name, run `mr.py gleif "<name>"` and, if it could borrow and the user gave the SEC contact, `mr.py --user-agent "<SEC User-Agent>" marks --skip-seen "<run folder>/debt-and-valuation-marks.jsonl" "<name>" "<distinctive word>" >> "<run folder>/debt-and-valuation-marks.jsonl"`, adding what they find to the GLEIF and Debt and valuation marks reports.

## People and owners

Officers, directors, and legal owners that the reports name and the entity record lacked, such as the related persons in a Form D, the directors of a subsidiary found late, or the legal owners a register lists (datacvr's owners with 5% or more, for example), count as new names by default. A spelling variant of a screened name counts as screened, and so does any name containing a distinctive word the Sanctions and offshore agent already searched in every list it used, such as "Mitnick" for every Mitnick vehicle; its report lists its searches per list.

- Ten or fewer unscreened names: screen them yourself as [sanctions-offshore.md](../sources/sanctions-offshore.md) describes. Run `mr.py csl` and `mr.py icij` once each with all of them, search each in OpenSanctions (with the API key, or its website search through the web fetch tool), and write the results to `<run folder>/late-names.md` in the brief's report format.
- More than ten: send one agent with the Sanctions and offshore source file, those names only, and that report file.

Fold the findings in either way. Holding vehicles rarely have court cases of their own, so leave courts to the main run. If you screen none, list the unscreened names under Gaps.

## Registers for group companies

When reports name group companies registered outside the US and UK that GLEIF, a register, or the accounts confirm as current subsidiaries (not an acquisition named only in the press, which may have been an asset purchase) and the National registers agent was not sent, send it now for those companies, with its own report file, and fold its findings in; if you send none, list those companies under Gaps. When the country has an `mr.py` command ([national-register-commands.md](national-register-commands.md)), run it for the new company first (for Luxembourg, rerun `lu` with every group company's RCS number in one run) and give the agent the file; when a register agent is still to be sent, wait for the register agents already running to report before sending it, so one agent covers every company found in that country.
