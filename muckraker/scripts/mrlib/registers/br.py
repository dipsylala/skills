"""Brazil: Receita Federal CNPJ open data."""

import json
import re
from .. import common


# --------------------------------------------------------------- Brazil ----

MINHARECEITA = "https://minhareceita.org/"  # the Receita Federal's CNPJ open data; BrasilAPI's robots.txt bars /api/


def br_report(cnpj, fetcher=None):
    """A Brazilian company from the Receita Federal's CNPJ open data: registration status, special
    situation (judicial recovery, bankruptcy), capital, activity, and partners and administrators."""
    get = fetcher or (lambda u: common.fetch(u, None))
    number = re.sub(r"\D", "", cnpj)
    if len(number) != 14:
        yield {"type": "br_note", "note": "mr.py br takes a 14-digit CNPJ (with or without punctuation)"}
        return
    url = MINHARECEITA + number
    try:
        d = json.loads(get(url))
    except common.FetchError as e:
        if "HTTP 400" in str(e) or "HTTP 404" in str(e):
            yield {"type": "br_note", "url": url, "note": f"the CNPJ open data has no company {number}"}
            return
        raise
    try:
        month = json.loads(get(MINHARECEITA + "updated")).get("message")
    except (common.FetchError, ValueError):
        month = None
    status, special = d.get("descricao_situacao_cadastral"), (d.get("situacao_especial") or "").strip()
    yield {"type": "br_company", "cnpj": number, "name": d.get("razao_social"), "trade_name": d.get("nome_fantasia") or None,
           "legal_form": d.get("natureza_juridica"), "size": d.get("porte"),
           "office": d.get("descricao_identificador_matriz_filial"), "status": status,
           "status_since": d.get("data_situacao_cadastral"), "status_reason": d.get("descricao_motivo_situacao_cadastral"),
           "special_situation": special or None, "special_since": d.get("data_situacao_especial"),
           "started": d.get("data_inicio_atividade"), "capital_brl": d.get("capital_social"),
           "activity": d.get("cnae_fiscal_descricao"), "city": ", ".join(filter(None, [d.get("municipio"), d.get("uf")])),
           "data_month": month, "url": url}
    for p in d.get("qsa") or []:
        yield {"type": "br_partner", "name": p.get("nome_socio"), "role": p.get("qualificacao_socio"),
               "since": p.get("data_entrada_sociedade"), **({"country": p["pais"]} if p.get("pais") else {}),
               **({"representative": p["nome_representante_legal"],
                   "representative_role": p.get("qualificacao_representante_legal")}
                  if p.get("nome_representante_legal") else {}), "url": url}
    if status and status != "ATIVA":
        yield {"type": "br_flag", "flag": "not active", "severity": "major", "status": status,
               "since": d.get("data_situacao_cadastral"), "reason": d.get("descricao_motivo_situacao_cadastral"), "url": url}
    if special:
        yield {"type": "br_flag", "flag": "special situation", "severity": "major", "situation": special,
               "since": d.get("data_situacao_especial"),
               "rule": "the Receita records judicial recovery (recuperação judicial), bankruptcy (falência) or "
                       "liquidation as a special situation", "url": url}
