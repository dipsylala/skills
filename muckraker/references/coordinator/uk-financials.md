# Financials, run by you when only UK accounts are filed

After running UK Companies House yourself ([uk-companies-house.md](uk-companies-house.md)), write `<run folder>/financials.md` yourself only when every item below holds:

1. `uk-accounts` printed records for the UK companies.
2. The entity has no tagged SEC financials: the entity record has no CIK, or `mr.py edgar-facts <CIK>` returned `no_xbrl_financials`. With a CIK and no SEC contact from the user, `edgar-facts` cannot run, so this item is unknown.
3. The entity record names no company outside the UK and US that files accounts.
4. `uk-accounts` printed no `uk_accounts_latest_scanned` record (the newest accounts have a text layer).

If any item fails or is unknown, send the Financials agent with the path of `uk-accounts.jsonl`.

When all four hold, `uk-accounts` has covered every filed set of accounts. Write the report from its records instead of sending the Financials agent, working through the checks in [financials.md](../sources/financials.md): the multi-year table, the derived figures, the notes from `uk_accounts_notes`, and any `sign_mismatch` or `uk_accounts_scanned` records. Say under Gaps that group accounts are not published, and leave group figures from ratings or press to SKILL.md step 4.
