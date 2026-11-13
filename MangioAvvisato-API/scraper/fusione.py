"""Fusione dei richiami che arrivano da più fonti.

Lo stesso richiamo può comparire sul sito di una catena e sul portale del
Ministero, spesso a giorni o settimane di distanza (di solito prima la catena).
Va riconosciuto e mostrato una volta sola, con tutte le fonti:

- se arriva prima la catena, il record nasce con l'id della catena; quando
  arriva il Ministero si aggancia a quel record (stesso id: niente notifica
  doppia) e ne prende i dati ufficiali, che sono più completi;
- se arriva prima il Ministero, l'avviso della catena aggiunge solo la fonte.

Si unisce solo quando l'abbinamento è sicuro: stesso prodotto, date vicine e
almeno un indizio forte (lotti in comune, oppure stessa marca). In caso di
dubbio si tengono due record separati: un doppione è meglio di una fusione
sbagliata.
"""

from __future__ import annotations

from datetime import date

from .links import _lots, _words, norm

FINESTRA_GIORNI = 45          # distanza massima tra le date delle due pubblicazioni
SOGLIA_NOME = 0.6             # quota minima di parole del nome in comune

MINISTERO = {"id": "ministero", "nome": "Ministero della Salute", "tipo": "ministero"}


def fonti_di(item: dict) -> list[str]:
    """Fonti del record; i record del Ministero precedenti a questo formato non le hanno."""
    return item.get("fonti") or ["ministero"]


def _giorni(a: str | None, b: str | None) -> int | None:
    try:
        return abs((date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days)
    except (TypeError, ValueError):
        return None


def _somiglianza_nome(a: dict, b: dict) -> float:
    pa = _words(a.get("denominazione") or a.get("titolo"))
    pb = _words(b.get("denominazione") or b.get("titolo"))
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / min(len(pa), len(pb))


def stesso_richiamo(a: dict, b: dict) -> bool:
    if (a.get("tipo") or "richiamo") != (b.get("tipo") or "richiamo"):
        return False
    giorni = _giorni(a.get("data_pubblicazione"), b.get("data_pubblicazione"))
    if giorni is not None and giorni > FINESTRA_GIORNI:
        return False
    if _somiglianza_nome(a, b) < SOGLIA_NOME:
        return False
    lotti_a, lotti_b = _lots(a), _lots(b)
    if lotti_a and lotti_b:
        return bool(lotti_a & lotti_b)            # i lotti, se ci sono, decidono
    marca_a, marca_b = norm(a.get("marca")), norm(b.get("marca"))
    return bool(marca_a and marca_b and (marca_a == marca_b or _words(marca_a) & _words(marca_b)))


def trova_corrispondente(nuovo: dict, items: dict[str, dict], solo_fonte: str | None = None) -> dict | None:
    """Il record esistente che descrive lo stesso richiamo, se unico.

    solo_fonte="catena": cerca solo tra i record non ancora pubblicati dal Ministero.
    """
    candidati = []
    for item in items.values():
        if item.get("id") == nuovo.get("id"):
            continue
        fonti = fonti_di(item)
        if solo_fonte == "catena" and "ministero" in fonti:
            continue
        if stesso_richiamo(nuovo, item):
            candidati.append(item)
    return candidati[0] if len(candidati) == 1 else None


def _aggiungi_fonte(record: dict, voce: dict) -> None:
    dettaglio = record.setdefault("fonti_dettaglio", [])
    if not any(d.get("id") == voce["id"] for d in dettaglio):
        dettaglio.append(voce)
    fonti = record.setdefault("fonti", fonti_di(record))
    if voce["id"] not in fonti:
        fonti.append(voce["id"])


def voce_ministero(item: dict) -> dict:
    return {**MINISTERO, "url": item.get("url"), "data": item.get("data_pubblicazione")}


def integra_ministero(esistente: dict, ministero: dict) -> dict:
    """Il richiamo del Ministero arriva su un record nato da una catena:
    i dati ufficiali prevalgono, l'id e le fonti della catena restano."""
    unito = {**esistente, **{k: v for k, v in ministero.items() if v not in (None, "", [], {})}}
    unito["id"] = esistente["id"]
    unito["id_ministero"] = ministero["id"]
    unito["fonti"] = list(dict.fromkeys(["ministero"] + fonti_di(esistente)))
    unito["fonti_dettaglio"] = [voce_ministero(ministero)] + [d for d in esistente.get("fonti_dettaglio", []) if d.get("id") != "ministero"]
    unito["catene"] = esistente.get("catene", [])
    if esistente.get("punti_vendita") and not ministero.get("punti_vendita"):
        unito["punti_vendita"] = esistente["punti_vendita"]
    # i dettagli del PDF ministeriale sono più affidabili; quelli della catena completano i vuoti
    dettagli = dict(esistente.get("dettagli") or {})
    dettagli.update({k: v for k, v in (ministero.get("dettagli") or {}).items() if v not in (None, "", [], {})})
    unito["dettagli"] = dettagli
    return unito


def integra_catena(esistente: dict, catena: dict) -> dict:
    """Un avviso di una catena si aggiunge come fonte a un record già noto."""
    unito = dict(esistente)
    if "fonti_dettaglio" not in unito and "ministero" in fonti_di(esistente):
        unito["fonti_dettaglio"] = [voce_ministero(esistente)]
    for voce in catena.get("fonti_dettaglio", []):
        _aggiungi_fonte(unito, voce)
    unito["catene"] = list(dict.fromkeys((esistente.get("catene") or []) + (catena.get("catene") or [])))
    if catena.get("punti_vendita") and not esistente.get("punti_vendita"):
        unito["punti_vendita"] = catena["punti_vendita"]
    # per i dati mancanti (es. lotti non indicati dal Ministero) si usa la catena
    dettagli = dict(unito.get("dettagli") or {})
    for k, v in (catena.get("dettagli") or {}).items():
        if v not in (None, "", [], {}) and not dettagli.get(k):
            dettagli[k] = v
    unito["dettagli"] = dettagli
    alias = set(unito.get("id_catene") or [])
    alias.add(catena["id"])
    unito["id_catene"] = sorted(alias)
    return unito
