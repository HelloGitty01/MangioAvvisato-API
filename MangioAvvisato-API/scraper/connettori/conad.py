"""Connettore Conad.

Elenco: https://www.conad.it/news-e-approfondimenti?_tag=richiamo-prodotto&page=N
Ogni avviso è una scheda (.rt201-card-elev-news--richiamoProdotto) con data
("06 novembre 2026"), titolo ("Richiamo <prodotto> - <PRODUTTORE>") e link al PDF.
I PDF sono quasi sempre il modello di richiamo ministeriale; quando sono solo
immagini, l'avviso si importa con i dati della scheda (senza lotti).
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..parse import parse_italian_date
from .base import Avviso, Connettore
from .comuni import (AvvisoScartato, classifica_rischio, e_modello_di_richiamo, leggi_modello, record_da_modello,
                     scarica_testo_pdf, sembra_alimentare)

ELENCO = "https://www.conad.it/news-e-approfondimenti?_tag=richiamo-prodotto&page={}"
MAX_PAGINE = 5


def dividi_titolo(titolo: str) -> tuple[str, str | None]:
    """"Richiamo Salamella dolce- FRANCHI SALUMI SRL" -> ("Salamella dolce", "FRANCHI SALUMI SRL")."""
    t = re.sub(r"^\s*richiamo\s+", "", titolo, flags=re.I).strip()
    m = re.match(r"(.+?)\s*[-–]\s*([^-–]+)$", t)
    if m:
        coda = m.group(2).strip()
        lettere = [c for c in coda if c.isalpha()]
        if lettere and sum(c.isupper() for c in lettere) / len(lettere) > 0.7:   # il produttore è in maiuscolo
            return m.group(1).strip(), coda
    return t, None


def avvisi_da_html(html: str, base: str = "https://www.conad.it/") -> list[Avviso]:
    soup = BeautifulSoup(html, "html.parser")
    avvisi: dict[str, Avviso] = {}
    for scheda in soup.select(".rt201-card-elev-news--richiamoProdotto"):
        link = next((a for a in scheda.select("a[href]") if ".pdf" in a["href"].lower()), None)
        titolo = scheda.select_one(".rt201-card-elev-news__title")
        if not link or not titolo:
            continue
        url = urljoin(base, link["href"])
        data = scheda.select_one(".rt201-card-elev-news__date")
        prodotto, produttore = dividi_titolo(titolo.get_text(" ", strip=True))
        avvisi.setdefault(url, Avviso(
            url=url, titolo=prodotto,
            data=parse_italian_date(data.get_text(" ", strip=True)) if data else None,
            extra={"produttore": produttore},
        ))
    return list(avvisi.values())


class Conad(Connettore):
    id = "conad"
    nome = "Conad"
    sito = "https://www.conad.it/"
    pagine_note = ("https://www.conad.it/news-e-approfondimenti?tag=richiamo-prodotto",)
    attivo = True

    def scopri(self, fetcher) -> list[Avviso]:
        tutti: list[Avviso] = []
        for pagina in range(1, MAX_PAGINE + 1):
            avvisi = avvisi_da_html(fetcher.get(ELENCO.format(pagina)).text)
            nuovi = [a for a in avvisi if a.url not in {t.url for t in tutti}]
            if not nuovi:
                break
            tutti += nuovi
        return tutti

    def elabora(self, fetcher, avviso: Avviso) -> dict:
        produttore = avviso.extra.get("produttore")
        if not sembra_alimentare(avviso.titolo):
            raise AvvisoScartato("prodotto non alimentare")
        testo = scarica_testo_pdf(fetcher, avviso.url)
        if e_modello_di_richiamo(testo):
            return record_da_modello(self, avviso, leggi_modello(testo), marca=produttore)
        # PDF solo immagine: i dati sicuri sono quelli della scheda
        return self.record_base(
            avviso, denominazione=avviso.titolo, marca=produttore,
            categoria_rischio=classifica_rischio(avviso.titolo), pdf_url=avviso.url,
        )
