"""Collegamento tra revoche e richiami originali.

Nei dati del Ministero una revoca non indica il richiamo che annulla: il
collegamento si ricostruisce confrontando nome del prodotto, marca, date e
lotti. Si collega solo quando l'abbinamento è ragionevolmente sicuro: meglio
nessun collegamento che uno sbagliato.
"""

from __future__ import annotations

import re
import unicodedata


def norm(text: str | None) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _words(text: str | None) -> set[str]:
    return {w for w in norm(text).split() if len(w) >= 4}


def _lots(item: dict) -> set[str]:
    lots = item.get("lotti") or (item.get("dettagli") or {}).get("lotti") or []
    return {norm(x).replace(" ", "") for x in lots if norm(x)}


def _date(item: dict) -> str:
    return item.get("data_pubblicazione") or ""


def find_original(revoca: dict, richiami_by_title: dict[str, list[dict]]) -> dict | None:
    """Il richiamo annullato da questa revoca, se si può stabilire con sicurezza."""
    candidates = [
        c for c in richiami_by_title.get(norm(revoca.get("titolo") or revoca.get("denominazione")), [])
        if not _date(revoca) or not _date(c) or _date(c) <= _date(revoca)
    ]
    if not candidates:
        return None
    lots = _lots(revoca)

    same_brand = [c for c in candidates if norm(c.get("marca")) == norm(revoca.get("marca"))]
    if len(same_brand) == 1:
        return same_brand[0]
    if len(same_brand) > 1:
        # prodotto richiamato più volte: decidono i lotti, se ne indicano uno solo
        by_lot = [c for c in same_brand if lots and lots & _lots(c)]
        return by_lot[0] if len(by_lot) == 1 else None

    # marca scritta in modo diverso: serve un indizio in più (lotti o parole della marca)
    if len(candidates) == 1:
        c = candidates[0]
        if (lots and lots & _lots(c)) or (_words(revoca.get("marca")) & _words(c.get("marca"))):
            return c
    return None


def link_revocations(items: list[dict]) -> dict[str, dict]:
    """Restituisce, per id, i campi di collegamento da aggiungere:
    sulla revoca "revoca_di", sul richiamo "revocato_da" e "revocato_il"."""
    richiami = [i for i in items if i.get("tipo") != "revoca"]
    revoche = sorted((i for i in items if i.get("tipo") == "revoca"), key=_date)
    by_title: dict[str, list[dict]] = {}
    for r in richiami:
        by_title.setdefault(norm(r.get("titolo") or r.get("denominazione")), []).append(r)

    links: dict[str, dict] = {}
    for rev in revoche:
        original = find_original(rev, by_title)
        if original is None or "revocato_da" in links.get(original["id"], {}):
            continue  # se più revoche puntano allo stesso richiamo vale la prima
        links.setdefault(rev["id"], {})["revoca_di"] = original["id"]
        links.setdefault(original["id"], {}).update(
            {"revocato_da": rev["id"], "revocato_il": rev.get("data_pubblicazione")}
        )
    return links
