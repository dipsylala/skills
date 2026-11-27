"""National registers outside the US and UK, one module per country, and their --help record lists."""



# The record types each national-register command prints, shown by `mr.py <cc> --help`. national-registers.md
# says which flags are red flags and what the records lack; keep the field lists here so they match the code.
REGISTER_RECORDS = {
    "fr": """records:
  fr_company          register profile
  fr_officer          officers and the statutory auditor
  fr_finances         the register's published figures, or published: false (accounts filed
                      confidentially under art. L. 232-25, or not filed)
  fr_accounts_filed   a BODACC accounts-filing notice: financial year end, confidential or not
  fr_registered       a BODACC registration notice: registration and activity start dates
  fr_capital          a capital increase or reduction, with the capital before and after
  fr_officer_change   an officer change, in the notice's own wording
  fr_notice           every other BODACC notice, with its kind (and its description where it has one)
  fr_insolvency       an insolvency notice (none means BODACC has none)
  fr_struck_off       a striking-off notice
  fr_flag             a financial year whose accounts should have a BODACC filing notice by now and have none""",
    "ie": """records:
  ie_company          CRO profile: last and next annual return dates, the name's effective date
  ie_accounts_filed   an accounts filing, with the days it took after its annual return date
  ie_summary          notes, such as the profile's last return being newer than the yearly filings datasets
  ie_flag             an annual return overdue, or filed more than 56 days after its annual return date""",
    "lu": """records (from the newest --quarters quarterly Centrale des Bilans files):
  lu_accounts_filed   a filing: deposit date against the deadline of seven months after the year end
  lu_accounts_year    a year's main figures: total assets, equity, cash, debts, convertible loans, bank debt,
                      debts to affiliates, net result, and turnover and staff costs where the profit and loss
                      account is filed in full (abridged accounts leave turnover out)
  lu_flag             late accounts (recent: true for a year ended in the last three years), or negative equity
                      at the latest year end; quotes holds the text to quote
  lu_quarter_unreadable  a quarterly file that could not be read, so filings deposited in it are missing""",
    "no": """records:
  no_company          Enhetsregisteret profile: bankruptcy and winding-up flags, share capital, number of shares
  no_officer          a current officer or the auditor, with a person's birth month and year
  no_subunit          a sub-unit (branch or establishment), with its employees and address
  no_accounts_year    a year's filed figures (last three years), with the link to the filed PDF
  no_accounts_filed   an accounts filing: receipt date against the deadline of seven months after the year end
  no_capital          a capital change announcement
  no_agreement        a section 3-8 agreement, with the counterparty it names (usually a shareholder)
  no_notice           every other announcement, with the text of officer and auditor changes (last 24 months)
  no_flag             bankruptcy, winding-up or compulsory dissolution; negative equity at the latest year end;
                      late accounts (recent: true when the year ended in the last three years); accounts past
                      their deadline and not filed""",
    "fi": """records (PRH open data, CC BY 4.0):
  fi_company          YTJ profile: trade register status, other and former names, the Virre page
  fi_notice           a registered notice: date, type, entry codes described, topics (capital, board, auditor,
                      accounts, insolvency); deduplicated by record number
  fi_accounts_digital the period of accounts filed digitally (figures not parsed)
  fi_unavailable      a source that could not be read: the registered notices or the digital accounts
  fi_summary          dates of capital events, board and auditor changes, and accounts registrations
  fi_flag             bankruptcy, restructuring or liquidation; removal from the trade register; accounts
                      registered more than eight months after the year end, or past that deadline and not
                      registered
Without --fy-end, the year end comes from digitally filed accounts, or the deadline check is skipped.""",
    "dk": """records (every dk_* record carries transport: the source is served over plain http):
  dk_accounts_filed   a filing: approval and publication dates against the ARL section 138 deadline, its
                      documents, and a parent_group_accounts link when a parent consolidates the company
  dk_accounts_year    a year's figures, scope entity or group; reported is an IFRS report's undimensioned figures
  dk_report_facts     reporting class, audit firm, approval date
  dk_officers         executive and supervisory boards and auditors named in a report
  dk_unavailable      a year's XBRL report that could not be read
  dk_notes            notes on going concern, events after the year end, parent and related parties,
                      subsidiaries, security, and the auditor's remarks
  dk_flag             late accounts (major when more than a week late on a year ended in the last three years);
                      accounts past their deadline and not published; a gap between filed periods; negative
                      equity; a modified audit opinion; an auditor's remark on a Companies Act breach; a
                      going-concern note (severity: review)""",
    "il": """records (from the Public Knowledge Workshop's daily copy of the register):
  il_company          profile: Hebrew and English names, type, status and status_en, sub-status, registration
                      date, violating flag, last annual report year, address, objects, Israeli government
                      contracts or support, copy_date, register_url
  il_flag             a violating company (major); a status other than active (major, or minor for a voluntary
                      liquidation); a sub-status warning before strike-off; an annual report more than a year
                      behind (minor)""",
    "es": """records (from BORME section A PDFs, and section C with --scan-from):
  es_entry            a published inscription: sheet (hoja), number, date, acts, officers (each with its act and
                      role), and capital (each change with the resulting subscribed capital, nominal amounts)
  es_summary          the current capital and current officers, worked out from appointments and removals
  es_notice           a section C announcement naming the company (liquidation balance, merger, capital reduction)
  es_scan             with --scan-from: the dates, number of BORME days and province scanned
  es_unreadable       a BORME PDF that could not be read
  es_flag             dissolution, extinction, insolvency proceeding or provisionally closed sheet (major);
                      inscription numbers missing from the PDFs read (minor)""",
    "br": """records (Receita Federal CNPJ open data, via minhareceita.org):
  br_company          legal and trade name, legal form, size, head office or branch, registration status with its
                      date and reason, special situation, start date, capital, activity, city, month of the data
  br_partner          a partner or administrator in the QSA: role, entry date, a foreign partner's country and
                      legal representative in Brazil
  br_flag             a status other than ATIVA, or a special situation (recuperacao judicial, falencia,
                      liquidacao); both major""",
}

# Record types several register commands share, printed by each command that has the case.
REGISTER_COMMON_RECORDS = """also, where this command has them:
  {cc}_candidate        a company matching a name search, with its number: run again with the right one
  {cc}_note             a message: a malformed number, no such company, or something the source does not give
  {cc}_summary          counts of what was read and flagged, and what the source leaves out"""


def register_help(cc):
    """The records part of `mr.py <cc> --help`: the country's own record types, then the shared ones."""
    return REGISTER_RECORDS[cc] + "\n" + REGISTER_COMMON_RECORDS.format(cc=cc)
