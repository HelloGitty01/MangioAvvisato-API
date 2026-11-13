"""Fonti multiple: connettori delle catene, fusione con il Ministero, fonti.json."""

import json
import types

from scraper import fusione
from scraper.connettori import TUTTI, Avviso, Connettore
from scraper.ricognizione import collegamenti
from scraper.store import Store, build_public


def ministero(id_, nome, marca, data, lotti=None):
    return {"id": id_, "tipo": "richiamo", "url": f"https://www.salute.gov.it/x/{id_}/",
            "denominazione": nome, "titolo": nome, "marca": marca, "data_pubblicazione": data,
            "dettagli": {"lotti": lotti or []}}


class FintaCatena(Connettore):
    id = "finta"
    nome = "Finta Spa"
    sito = "https://www.finta.it/"
    attivo = True

    def __init__(self, avvisi):
        self._avvisi = avvisi

    def scopri(self, fetcher):
        return self._avvisi

    def elabora(self, fetcher, avviso):
        return self.record_base(avviso, denominazione=avviso.extra["nome"], marca=avviso.extra.get("marca"),
                                dettagli={"lotti": avviso.extra.get("lotti", [])}, punti_vendita="Solo Lombardia")


def test_registro_connettori():
    ids = [c.id for c in TUTTI]
    assert ids == ["coop", "esselunga", "carrefour", "lidl", "conad"]
    attivi = {c.id for c in TUTTI if c.attivo}
    assert attivi == {"esselunga", "carrefour", "conad"}     # Coop e Lidl in attesa della seconda ricognizione


def test_id_avviso_stabile():
    c = FintaCatena([])
    a = Avviso(url="https://www.finta.it/richiami/Pesto-Genovese_L171.html?x=1", titolo="Pesto")
    assert c.id_avviso(a) == "finta-pesto-genovese-l171"


def test_stesso_richiamo_criteri():
    a = ministero("a", "Pesto alla genovese fresco", "Rossi", "2026-11-01", ["L171"])
    assert fusione.stesso_richiamo(a, ministero("b", "Pesto genovese fresco", "Altra", "2026-10-20", ["L171"]))
    assert not fusione.stesso_richiamo(a, ministero("c", "Pesto alla genovese fresco", "Rossi", "2026-11-01", ["L999"]))
    assert not fusione.stesso_richiamo(a, ministero("d", "Pesto alla genovese fresco", "Rossi", "2026-06-01", ["L171"]))
    assert not fusione.stesso_richiamo(a, ministero("e", "Tortellini al prosciutto", "Rossi", "2026-11-01", ["L171"]))
    # senza lotti serve la stessa marca
    senza = ministero("f", "Pesto alla genovese fresco", "Rossi", "2026-11-03")
    assert fusione.stesso_richiamo(senza, ministero("g", "Pesto alla genovese", "ROSSI", "2026-11-01"))
    assert not fusione.stesso_richiamo(senza, ministero("h", "Pesto alla genovese", "Bianchi", "2026-11-01"))


def test_prima_la_catena_poi_il_ministero(tmp_path, monkeypatch):
    import scraper.main as m
    store = Store(tmp_path / "data")
    catena = FintaCatena([Avviso(url="https://www.finta.it/r/pesto-l171", titolo="Pesto", data="2026-10-20",
                                 extra={"nome": "Pesto alla genovese fresco", "marca": "Rossi", "lotti": ["L171"]})])
    monkeypatch.setattr(m.connettori, "attivi", lambda: [catena])
    nuovi = []
    m.esegui_connettori(None, store, nuovi)
    assert nuovi == ["finta-pesto-l171"]
    rec = store.items["finta-pesto-l171"]
    assert rec["fonti"] == ["finta"] and rec["punti_vendita"] == "Solo Lombardia"
    # arriva il Ministero: stesso record, nessun nuovo id, dati ufficiali
    mi = ministero("pesto-genovese-123", "Pesto alla genovese fresco", "Rossi", "2026-11-05", ["L171", "L172"])
    corr = fusione.trova_corrispondente(mi, store.items, solo_fonte="catena")
    assert corr["id"] == "finta-pesto-l171"
    store.upsert(fusione.integra_ministero(corr, mi))
    unito = store.items["finta-pesto-l171"]
    assert unito["fonti"] == ["ministero", "finta"] and unito["id_ministero"] == "pesto-genovese-123"
    assert unito["dettagli"]["lotti"] == ["L171", "L172"] and unito["punti_vendita"] == "Solo Lombardia"
    assert store.has("pesto-genovese-123") and len(store.items) == 1
    # salvato e riletto, l'alias resta
    store.save()
    assert Store(tmp_path / "data").has("pesto-genovese-123")


def test_prima_il_ministero_poi_la_catena(tmp_path, monkeypatch):
    import scraper.main as m
    store = Store(tmp_path / "data")
    store.upsert(ministero("pesto-genovese-123", "Pesto alla genovese fresco", "Rossi", "2026-11-05", ["L171"]))
    catena = FintaCatena([Avviso(url="https://www.finta.it/r/pesto-l171", titolo="Pesto", data="2026-11-06",
                                 extra={"nome": "Pesto genovese fresco", "marca": "Rossi", "lotti": ["L171"]})])
    monkeypatch.setattr(m.connettori, "attivi", lambda: [catena])
    nuovi = []
    m.esegui_connettori(None, store, nuovi)
    assert nuovi == [] and len(store.items) == 1          # nessuna notifica doppia
    rec = store.items["pesto-genovese-123"]
    assert rec["fonti"] == ["ministero", "finta"] and rec["catene"] == ["Finta Spa"]
    assert [d["id"] for d in rec["fonti_dettaglio"]] == ["ministero", "finta"]
    # alla prossima esecuzione l'avviso della catena è già noto
    nuovi2 = []
    m.esegui_connettori(None, store, nuovi2)
    assert nuovi2 == [] and store.has("finta-pesto-l171")
    # un nuovo passaggio del Ministero non cancella la fonte della catena
    store.upsert(ministero("pesto-genovese-123", "Pesto alla genovese fresco", "Rossi", "2026-11-05", ["L171"]))
    assert store.items["pesto-genovese-123"]["fonti"] == ["ministero", "finta"]


def test_connettore_in_errore_non_ferma_gli_altri(tmp_path, monkeypatch):
    import scraper.main as m

    class Rotta(FintaCatena):
        id = "rotta"
        def scopri(self, fetcher):
            raise RuntimeError("sito cambiato")
    buona = FintaCatena([Avviso(url="https://www.finta.it/r/uova", titolo="Uova", data="2026-11-06", extra={"nome": "Uova fresche"})])
    monkeypatch.setattr(m.connettori, "attivi", lambda: [Rotta([]), buona])
    store = Store(tmp_path / "data")
    nuovi = []
    m.esegui_connettori(None, store, nuovi)
    assert nuovi == ["finta-uova"]
    assert "finta" in store.stato()["fonti"] and "rotta" not in store.stato()["fonti"]


def test_pubblicazione_fonti(tmp_path):
    store = Store(tmp_path / "data")
    store.upsert(ministero("vecchio", "Salame", "Rossi", "2026-01-01"))     # record senza campi delle fonti
    store.save()
    store.segna_controllo_riuscito("2026-11-09T10:00:00+00:00")
    build_public(store, tmp_path / "public")
    v1 = tmp_path / "public" / "v2"
    sintesi = json.loads((v1 / "richiami.json").read_text(encoding="utf-8"))[0]
    assert sintesi["fonti"] == ["ministero"]
    dettaglio = json.loads((v1 / "richiami" / "vecchio.json").read_text(encoding="utf-8"))
    assert dettaglio["fonti_dettaglio"][0]["nome"] == "Ministero della Salute"
    fonti = json.loads((v1 / "fonti.json").read_text(encoding="utf-8"))
    assert fonti[0]["id"] == "ministero" and fonti[0]["ultimo_controllo"] == "2026-11-09T10:00:00+00:00"
    assert [f["id"] for f in fonti[1:]] == ["coop", "esselunga", "carrefour", "lidl", "conad"]
    assert {f["id"]: f["attivo"] for f in fonti[1:]} == {"coop": False, "esselunga": True, "carrefour": True, "lidl": False, "conad": True}


def test_ricognizione_trova_i_collegamenti():
    html = '''<html><body>
      <a href="/offerte">Offerte</a>
      <a href="/richiamo-prodotti.html">Richiamo prodotti</a>
      <a href="https://www.finta.it/sicurezza/avvisi-di-sicurezza">Avvisi di sicurezza</a>
      <a href="https://altro-sito.com/richiami">Richiami altrove</a>
      <a href="/static/Informazione_per_i_clienti-123.pdf">Avviso</a>
    </body></html>'''
    pagine, pdf = collegamenti(html, "https://www.finta.it/", "https://www.finta.it/")
    assert [p["url"] for p in pagine] == ["https://www.finta.it/richiamo-prodotti.html", "https://www.finta.it/sicurezza/avvisi-di-sicurezza"]
    assert pdf == ["https://www.finta.it/static/Informazione_per_i_clienti-123.pdf"]


def test_home_per_la_verifica_antibot():
    from scraper.fetch import home_di
    assert home_di("https://www.lidl.it/static/assets/avviso.pdf") == "https://www.lidl.it/"
    assert home_di("https://www.salute.gov.it/new/rss/x.xml").endswith("/new/it/")


def test_v1_solo_ministero_v2_tutto(tmp_path):
    store = Store(tmp_path / "data")
    store.upsert(ministero("mini", "Salame", "Rossi", "2026-11-01"))
    store.upsert({**ministero("coop-uova", "Uova fresche", "Coop", "2026-11-02"), "fonti": ["coop"], "catene": ["Coop"]})
    store.upsert({**ministero("coop-pesto", "Pesto", "Coop", "2026-11-03"), "fonti": ["ministero", "coop"], "catene": ["Coop"], "id_ministero": "pesto-1"})
    store.save()
    build_public(store, tmp_path / "public", content_dir=tmp_path / "contenuti")
    leggi = lambda v, f: json.loads((tmp_path / "public" / v / f).read_text(encoding="utf-8"))
    assert {r["id"] for r in leggi("v1", "richiami.json")} == {"mini", "coop-pesto"}      # le app vecchie non vedono le sole catene
    assert {r["id"] for r in leggi("v2", "richiami.json")} == {"mini", "coop-uova", "coop-pesto"}
    assert not (tmp_path / "public" / "v1" / "richiami" / "coop-uova.json").exists()
    assert (tmp_path / "public" / "v2" / "fonti.json").exists() and not (tmp_path / "public" / "v1" / "fonti.json").exists()
    assert leggi("v1", "meta.json")["totale"] == 2 and leggi("v2", "meta.json")["totale"] == 3
    assert leggi("v2", "meta.json")["schema_version"] == 2
