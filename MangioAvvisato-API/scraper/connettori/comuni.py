"""Strumenti comuni ai connettori: lettura del modello di richiamo, filtri, date."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from .. import config
from ..parse import classify_risk, clean_text, extract_pdf_text, parse_italian_date, parse_pdf_text, split_lots


class AvvisoScartato(Exception):
    """L'avviso non va importato (non alimentare, illeggibile, troppo vecchio...).
    Viene ricordato, così alle esecuzioni successive non si riscarica."""


# Prodotti non alimentari che le catene pubblicano nella stessa pagina dei richiami.
NON_ALIMENTARI = re.compile(
    r"aspirapolver|giocattol|peluche|adesiv|sabbia|caricabatteri|power ?bank|lampad|"
    r"elettrodomestic|frullator|bollitor|ferro da stiro|asciugacapell|piastra per capelli|"
    r"cosmetic|crema solare|shampoo|detersiv|seggiolin|passeggin|bicicletta|monopattin|"
    r"cavo usb|alimentatore|smartphone|tablet|rowenta|stendibianch|pentol|padell",
    re.I,
)


def sembra_alimentare(*testi: str | None) -> bool:
    return not any(t and NON_ALIMENTARI.search(t) for t in testi)


def e_modello_di_richiamo(testo: str) -> bool:
    """Il testo è il modello di richiamo dei prodotti alimentari (Ministero della Salute)?"""
    t = testo.lower()
    return "denominazione di vendita" in t and "lotto" in t and "motivo del richiamo" in t


def troppo_vecchio(data_iso: str | None, oggi: date | None = None) -> bool:
    if not data_iso:
        return False
    try:
        giorni = ((oggi or date.today()) - date.fromisoformat(data_iso[:10])).days
    except ValueError:
        return False
    return giorni > config.CATENE_ETA_MASSIMA_GIORNI


def data_da_timestamp_ms(testo: str) -> str | None:
    """Data da un numero di 13 cifre (millisecondi) come quelli nei nomi dei file."""
    m = re.search(r"(?<!\d)(1[6-9]\d{11})(?!\d)", testo)
    if not m:
        return None
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).date().isoformat()


def leggi_modello(testo: str) -> dict:
    """Campi del modello di richiamo, più data e marchio del prodotto (stanno sulla stessa riga)."""
    campi = parse_pdf_text(testo)
    m_data = re.search(r"Data\s*:\s*\[?\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", testo)
    m_marchio = re.search(r"Marchio del prodotto\s*:\s*([^\n]+)", testo)
    campi["data_modello"] = parse_italian_date(m_data.group(1)) if m_data else None
    campi["marchio_prodotto"] = clean_text(m_marchio.group(1)) if m_marchio else None
    lotti: list[str] = []
    for lotto in [pulisci_valore(l) for l in campi.get("lotti") or []]:
        for parte in split_lots(lotto):
            # "K155 - K175 - K176": più lotti separati da trattini, se ogni pezzo sembra un codice
            pezzi = [x.strip() for x in re.split(r"\s+[-–]\s+|\s*;\s*", parte) if x.strip()]
            if len(pezzi) > 1 and all(len(x) >= 3 and re.search(r"\d", x) for x in pezzi):
                lotti += pezzi
            else:
                lotti.append(parte)
    campi["lotti"] = list(dict.fromkeys(l for l in lotti if l))
    return campi


def pulisci_valore(valore: str | None) -> str:
    """Toglie parentesi quadre ("[PL2116]") e parole del modulo ("INTERESSATO") dai valori."""
    v = re.sub(r"^\s*interessat[oi]\b[:\s]*", "", valore or "", flags=re.I)
    v = re.sub(r"[\[\]]", " ", v)
    return " ".join(v.split())


# Parole che indicano il tipo di rischio nelle descrizioni libere delle catene.
_RISCHI = [
    ("allergeni", r"allerg|(glutine|latte|uov[ao]|arachid|frutta a guscio|nocciol|mandorl|soia|senape|sedano|sesamo|solfit|lupin|crostace|mollusc|pesce)"
                  r"[^.]{0,80}(non dichiarat|non indicat|non riportat|non presente in etichetta)|(non dichiarat|tracce di)[^.]{0,60}"
                  r"(glutine|latte|uov[ao]|arachid|frutta a guscio|nocciol|mandorl|soia|senape|sedano|sesamo|solfit|lupin|crostace|mollusc)"),
    ("microbiologico", r"microbiolog|listeri|salmonell|escherichia|e\.? ?coli|stec\b|botulin|clostridi|muff[ae]|norovirus|epatite|"
                       r"bacillus|campylobacter|enterobatter|stafilococc|staphylococc|carica batteric|lievit[io] oltre"),
    ("chimico", r"chimic|ocratossin|aflatossin|micotossin|ossido di etilene|pesticid|fitofarmac|residu[io] di|metalli pesanti|piombo|"
                r"cadmio|mercurio|arsenico|istamina|diossin|idrocarburi|\bipa\b|acrilammide|alcaloidi|3-mcpd|glicidil|sostanz[ae] non consentit"),
    ("fisico", r"fisic|corp[oi] estrane|framment|vetro|schegg|plastica|metallic|metallo|osso|ossa\b|pietr|sassolin"),
]


def classifica_rischio(*testi: str | None) -> str:
    """Tipo di rischio da un testo libero; per i testi con le parole del Ministero vale classify_risk."""
    testo = " ".join(t for t in testi if t)
    esplicito = classify_risk(testo)
    if esplicito != "altro":
        return esplicito
    basso = testo.lower()
    for categoria, regola in _RISCHI:
        if re.search(regola, basso):
            return categoria
    return "altro"


def scarica_testo_pdf(fetcher, url: str) -> str:
    risposta = fetcher.get(url)
    return extract_pdf_text(risposta.content, config.PDF_TIMEOUT) or ""


def motivo_breve(motivo: str | None) -> str | None:
    if not motivo:
        return None
    breve = re.split(r"(?<=[.;])\s", motivo.strip(), maxsplit=1)[0]
    return breve if len(breve) <= 160 else breve[:157].rstrip() + "…"


def record_da_modello(connettore, avviso, campi: dict, **altri) -> dict:
    """Record del richiamo a partire dal modello ministeriale letto nel PDF."""
    motivo = campi.get("motivo_esteso")
    dettagli = {k: v for k, v in campi.items() if k not in ("data_modello", "marchio_prodotto") and v}
    marca_alternativa = altri.pop("marca", None)
    motivo_alternativo = altri.pop("motivo", None)
    return connettore.record_base(
        avviso,
        denominazione=campi.get("denominazione_vendita") or avviso.titolo,
        marca=campi.get("marchio_prodotto") or campi.get("operatore") or marca_alternativa,
        motivo=motivo_breve(motivo) or motivo_alternativo,
        categoria_rischio=classifica_rischio(motivo, avviso.titolo),
        pdf_url=avviso.url if avviso.url.lower().split("?")[0].endswith(".pdf") else None,
        data_pubblicazione=avviso.data or campi.get("data_modello"),
        dettagli=dettagli,
        **altri,
    )
