"""Connettori delle catene, provati sulle pagine e sui PDF reali raccolti dalla ricognizione."""

import types
from datetime import date
from pathlib import Path

import pytest

from scraper.connettori import carrefour, comuni, conad, esselunga
from scraper.connettori.base import Avviso
from scraper.connettori.comuni import AvvisoScartato
from scraper.store import Store

FIX = Path(__file__).parent / "fixtures" / "catene"


def leggi(nome):
    return (FIX / nome).read_text(encoding="utf-8")


# --- Esselunga --------------------------------------------------------------

def test_esselunga_elenco():
    avvisi = esselunga.avvisi_da_html(leggi("esselunga.html"))
    assert len(avvisi) > 80                                     # oltre cento riquadri, raggruppati per PDF
    assert all(a.url.startswith("https://www.esselunga.it/") and ".pdf" in a.url.lower() for a in avvisi)
    assert all(a.data is None for a in avvisi)                   # la pagina non ha date
    latte = next(a for a in avvisi if "uuid4054014" in a.url)    # un cartello per più prodotti
    assert len(latte.extra["prodotti"]) >= 5 and any("Aptamil" in p for p in latte.extra["prodotti"])


def test_esselunga_modello_e_non_alimentari(monkeypatch):
    c = esselunga.Esselunga()
    monkeypatch.setattr(esselunga, "scarica_testo_pdf", lambda f, url: leggi("minestrone.txt"))
    r = c.elabora(None, Avviso(url="https://www.esselunga.it/x/cartello_minestrone.pdf", titolo="Minestrone", extra={"prodotti": ["Minestrone - Zuppa Toscana 500 g"]}))
    assert r["id"] == "esselunga-cartello-minestrone" and r["fonti"] == ["esselunga"]
    assert r["data_pubblicazione"] == "2026-10-07" and r["marca"] == "ORTONATURA S.A.C.A R.L."
    assert r["dettagli"]["lotti"] == ["0510"] and r["categoria_rischio"] == "allergeni"
    assert r["titolo"] == "Minestrone - Zuppa Toscana 500 g" and r["pdf_url"].endswith(".pdf")
    # gli adesivi per sabbia (amianto) non sono un alimento: niente modello, scartato
    monkeypatch.setattr(esselunga, "scarica_testo_pdf", lambda f, url: leggi("sands-sticker.txt"))
    with pytest.raises(AvvisoScartato):
        c.elabora(None, Avviso(url="https://www.esselunga.it/x/sands-sticker.pdf", titolo="Sand Stickers"))
    # PDF solo immagine: nessun testo, scartato
    monkeypatch.setattr(esselunga, "scarica_testo_pdf", lambda f, url: "")
    with pytest.raises(AvvisoScartato):
        c.elabora(None, Avviso(url="https://www.esselunga.it/x/ananas.pdf", titolo="Ananas"))


# --- Conad ------------------------------------------------------------------

def test_conad_elenco():
    avvisi = conad.avvisi_da_html(leggi("conad.html"))
    assert 6 <= len(avvisi) <= 12
    birra = avvisi[0]
    assert birra.data == "2026-11-06" and birra.titolo.startswith("Birra Castello")
    assert birra.extra["produttore"] is None                     # "cluster 0.33X3" non è un produttore
    pancetta = next(a for a in avvisi if "Pancetta" in a.titolo)
    assert pancetta.extra["produttore"] == "SALUMIFICIO CAMPIDANESE SU SARTIZZU"


def test_conad_titoli():
    assert conad.dividi_titolo("Richiamo Salamella dolce- FRANCHI SALUMI SRL") == ("Salamella dolce", "FRANCHI SALUMI SRL")
    assert conad.dividi_titolo("Richiamo Simmenthal - BOLTON FOOD SPA") == ("Simmenthal", "BOLTON FOOD SPA")
    assert conad.dividi_titolo("Richiamo Birra Castello lager - cluster 0.33X3") == ("Birra Castello lager - cluster 0.33X3", None)


def test_conad_pdf_modello_e_immagine(monkeypatch):
    c = conad.Conad()
    avviso = Avviso(url="https://www.conad.it/assets/x/trippa.pdf", titolo="Simmenthal", data="2026-10-02", extra={"produttore": "BOLTON FOOD SPA"})
    monkeypatch.setattr(conad, "scarica_testo_pdf", lambda f, url: leggi("trippa.txt"))
    r = c.elabora(None, avviso)
    assert r["dettagli"]["lotti"] == ["K155", "K175", "K176"]    # lotti separati per il controllo con la fotocamera
    assert r["data_pubblicazione"] == "2026-10-02"               # data di pubblicazione di Conad, non del modello
    assert r["marca"] == "SIMMENTHAL" and r["denominazione"] == "Trippa preparata con sugo"
    assert r["dettagli"]["scadenza"] == "30-06-2029" and r["categoria_rischio"] == "allergeni"
    # PDF immagine: si usano i dati della scheda, senza inventare lotti
    monkeypatch.setattr(conad, "scarica_testo_pdf", lambda f, url: "")
    r = c.elabora(None, avviso)
    assert r["denominazione"] == "Simmenthal" and r["marca"] == "BOLTON FOOD SPA" and not r["dettagli"]


# --- Carrefour --------------------------------------------------------------

def test_carrefour_elenco_e_data_dal_file():
    avvisi = carrefour.avvisi_da_html(leggi("carrefour.html"))
    assert len(avvisi) == 1
    a = avvisi[0]
    assert a.titolo == "Cornetto Veganok Vuoto" and a.data == "2026-06-27"


def test_carrefour_non_alimentare(monkeypatch):
    c = carrefour.Carrefour()
    with pytest.raises(AvvisoScartato):
        c.elabora(None, Avviso(url="https://www.carrefour.it/x/aspirapolvere_1782543048513.pdf", titolo="Aspirapolvere senza fili", data="2026-11-01"))


# --- regole comuni ----------------------------------------------------------

def test_modello_data_marchio_lotti():
    campi = comuni.leggi_modello(leggi("fichi.txt"))
    assert campi["data_modello"] == "2026-07-28" and campi["marchio_prodotto"] == "NOBERASCO SPA"
    assert campi["lotti"] == ["L6075A"]


def test_eta_massima():
    assert comuni.troppo_vecchio("2026-06-01", oggi=date(2026, 11, 13))
    assert not comuni.troppo_vecchio("2026-10-01", oggi=date(2026, 11, 13))
    assert not comuni.troppo_vecchio(None)


def test_scartati_ricordati(tmp_path, monkeypatch):
    import scraper.main as m

    class Vecchia(esselunga.Esselunga):
        def scopri(self, fetcher):
            return [Avviso(url="https://www.esselunga.it/x/vecchio.pdf", titolo="Vecchio", data="2025-01-01")]
        def elabora(self, fetcher, avviso):
            raise AssertionError("un avviso troppo vecchio non va nemmeno scaricato")

    monkeypatch.setattr(m.connettori, "attivi", lambda: [Vecchia()])
    store = Store(tmp_path / "data")
    nuovi = []
    m.esegui_connettori(None, store, nuovi)
    assert nuovi == [] and store.scartato("esselunga", "esselunga-vecchio")
    m.esegui_connettori(None, store, nuovi)                       # la seconda volta non viene riconsiderato


def test_secondo_modello_di_cartello():
    campi = comuni.leggi_modello(leggi("birra.txt"))
    assert campi["lotti"] == ["PL2116"] and campi["data_modello"] == "2026-11-02"


def test_classificazione_testi_liberi():
    assert comuni.classifica_rischio("Valori di Ocratossina A oltre i limiti di legge") == "chimico"
    assert comuni.classifica_rischio("Problema fisico di confezionamento.") == "fisico"
    assert comuni.classifica_rischio("Possibile presenza di Listeria monocytogenes") == "microbiologico"
    assert comuni.classifica_rischio("Presenza di sedano non dichiarato in etichetta") == "allergeni"
    assert comuni.classifica_rischio("Latte parzialmente scremato") == "altro"       # nome del prodotto, non un rischio
    assert comuni.classifica_rischio("Errata indicazione in etichetta del TMC") == "altro"


def test_avvisi_senza_data(tmp_path, monkeypatch):
    """Esselunga non indica le date: i cartelli già presenti all'attivazione sono vecchi,
    quelli comparsi dopo prendono la data del giorno in cui compaiono."""
    import scraper.main as m
    elenco = [Avviso(url="https://www.esselunga.it/x/cartello_veggarella.pdf", titolo="Veggarella", extra={"prodotti": ["Veggarella"]})]

    class Finta(esselunga.Esselunga):
        def scopri(self, fetcher):
            return list(elenco)

    monkeypatch.setattr(esselunga, "scarica_testo_pdf", lambda f, url: leggi("veggarella.txt"))
    monkeypatch.setattr(m.connettori, "attivi", lambda: [Finta()])
    store = Store(tmp_path / "data")
    nuovi = []
    m.esegui_connettori(None, store, nuovi)                       # prima esecuzione: la Veggarella c'era già
    assert nuovi == [] and store.scartato("esselunga", "esselunga-cartello-veggarella")
    elenco.insert(0, Avviso(url="https://www.esselunga.it/x/cartello_veggarella_2.pdf", titolo="Veggarella 2", extra={"prodotti": ["Veggarella"]}))
    m.esegui_connettori(None, store, nuovi)                       # nuovo cartello senza data: data di oggi
    assert nuovi == ["esselunga-cartello-veggarella-2"]
    r = store.items["esselunga-cartello-veggarella-2"]
    assert r["data_pubblicazione"] == date.today().isoformat() and r["data_stimata"] is True
