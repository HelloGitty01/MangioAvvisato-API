"""Connettore Carrefour Italia.

Pagina: https://www.carrefour.it/richiamo-prodotti.html
Ogni avviso è una scheda (a.pd-card) con il nome del prodotto e il link al PDF del
cartello, di solito un'immagine. La data si ricava dal nome del file, che termina
con un'indicazione temporale in millisecondi. Dati disponibili: nome e data.
"""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import Avviso, Connettore
from .comuni import (AvvisoScartato, classifica_rischio, data_da_timestamp_ms, e_modello_di_richiamo, leggi_modello,
                     record_da_modello, scarica_testo_pdf, sembra_alimentare)

PAGINA = "https://www.carrefour.it/richiamo-prodotti.html"


def avvisi_da_html(html: str, base: str = PAGINA) -> list[Avviso]:
    soup = BeautifulSoup(html, "html.parser")
    avvisi: dict[str, Avviso] = {}
    for scheda in soup.select("a.pd-card[href]"):
        href = scheda["href"]
        if "richiamo" not in href.lower() or ".pdf" not in href.lower():
            continue
        titolo = scheda.select_one(".heading-text") or scheda.select_one("h2, h3")
        if not titolo:
            continue
        url = urljoin(base, href)
        nome = " ".join(titolo.get_text(" ", strip=True).split())
        avvisi.setdefault(url, Avviso(url=url, titolo=nome, data=data_da_timestamp_ms(href.split("/")[-1])))
    return list(avvisi.values())


class Carrefour(Connettore):
    id = "carrefour"
    nome = "Carrefour"
    sito = "https://www.carrefour.it/"
    pagine_note = (PAGINA,)
    attivo = True

    def scopri(self, fetcher) -> list[Avviso]:
        return avvisi_da_html(fetcher.get(PAGINA).text)

    def elabora(self, fetcher, avviso: Avviso) -> dict:
        if not sembra_alimentare(avviso.titolo):
            raise AvvisoScartato("prodotto non alimentare")
        if not avviso.data:
            raise AvvisoScartato("data non ricavabile")
        testo = scarica_testo_pdf(fetcher, avviso.url)
        if e_modello_di_richiamo(testo):
            return record_da_modello(self, avviso, leggi_modello(testo))
        return self.record_base(avviso, denominazione=avviso.titolo, categoria_rischio=classifica_rischio(avviso.titolo), pdf_url=avviso.url)
