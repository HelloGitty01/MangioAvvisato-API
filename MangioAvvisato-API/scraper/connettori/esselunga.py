"""Connettore Esselunga.

Pagina: https://www.esselunga.it/it-it/servizio-clienti/allerte-e-richiami.html
Ogni avviso è un riquadro (.cmp-teaser) con titolo "Richiamo prodotto/i", il nome
del prodotto e il link al PDF del cartello. La pagina non ha date: la data si legge
dal PDF. Si importano solo gli avvisi il cui PDF è il modello di richiamo alimentare:
così si escludono i prodotti non alimentari (pubblicati nella stessa pagina) e i PDF
che sono solo immagini.
"""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import Avviso, Connettore
from .comuni import AvvisoScartato, e_modello_di_richiamo, leggi_modello, record_da_modello, scarica_testo_pdf

PAGINA = "https://www.esselunga.it/it-it/servizio-clienti/allerte-e-richiami.html"


def avvisi_da_html(html: str, base: str = PAGINA) -> list[Avviso]:
    soup = BeautifulSoup(html, "html.parser")
    avvisi: dict[str, Avviso] = {}
    for riquadro in soup.select(".cmp-teaser"):
        titolo = riquadro.select_one(".cmp-teaser__title")
        if not titolo or "richiam" not in titolo.get_text(" ", strip=True).lower():
            continue
        link = riquadro.select_one("a[href]")
        if not link or ".pdf" not in link["href"].lower():
            continue
        url = urljoin(base, link["href"])
        descrizione = riquadro.select_one(".cmp-teaser__description")
        nome = " ".join(descrizione.get_text(" ", strip=True).split()) if descrizione else ""
        if url in avvisi:   # più prodotti nello stesso cartello
            avvisi[url].extra["prodotti"].append(nome)
        else:
            avvisi[url] = Avviso(url=url, titolo=nome, extra={"prodotti": [nome]})
    return list(avvisi.values())


class Esselunga(Connettore):
    id = "esselunga"
    nome = "Esselunga"
    sito = "https://www.esselunga.it/"
    pagine_note = (PAGINA,)
    attivo = True

    def scopri(self, fetcher) -> list[Avviso]:
        return avvisi_da_html(fetcher.get(PAGINA).text)

    def elabora(self, fetcher, avviso: Avviso) -> dict:
        testo = scarica_testo_pdf(fetcher, avviso.url)
        if not e_modello_di_richiamo(testo):
            raise AvvisoScartato("PDF senza modello di richiamo alimentare (immagine o prodotto non alimentare)")
        campi = leggi_modello(testo)
        prodotti = [p for p in avviso.extra.get("prodotti", []) if p]
        return record_da_modello(self, avviso, campi, titolo=" · ".join(prodotti) or None)
