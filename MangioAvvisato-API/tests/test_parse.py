import json
from pathlib import Path

from scraper.discovery import urls_from_feed, urls_from_listing
from scraper.fetch import is_challenge
from scraper.parse import classify_risk, parse_detail, parse_italian_date, parse_pdf_text
from scraper.store import Store, build_public, recall_id

FIX = Path(__file__).parent / "fixtures"
URL = "https://www.salute.gov.it/new/it/ext-avviso-sicurezza-alimentare/pop-corn-0/"


def test_date():
    assert parse_italian_date("8 agosto 2026") == "2026-08-08"
    assert parse_italian_date("05/11/2026") == "2026-11-05"
    assert parse_italian_date("boh") is None


def test_risk():
    assert classify_risk("Richiamo per rischio microbiologico") == "microbiologico"
    assert classify_risk("Richiamo per presenza di allergeni non dichiarati") == "allergeni"


def test_detail():
    item = parse_detail((FIX / "dettaglio.html").read_text(), URL)
    assert item["titolo"] == "POP CORN"
    assert item["data_pubblicazione"] == "2026-08-08"
    assert item["marca"] == "SALATI PREZIOSI"
    assert item["denominazione"] == "POP CORN"
    assert item["categoria_rischio"] == "chimico"
    assert item["tipo"] == "richiamo"
    assert item["pdf_url"] == "https://www.salute.gov.it/new/sites/default/files/2026-08/modello-richiamo-pop-corn.pdf"


def test_feed():
    assert urls_from_feed((FIX / "feed.xml").read_text()) == [URL]


def test_listing():
    html = '<a href="/new/it/ext-avviso-sicurezza-alimentare/pop-corn-0/">x</a><a href="/altro/">y</a>'
    assert urls_from_listing(html) == [URL]


def test_pdf_fields():
    d = parse_pdf_text((FIX / "modello.txt").read_text())
    assert d["marchio"] == "SALATI PREZIOSI"
    assert d["lotti"] == ["L2601", "L2602", "L26/03"]
    assert d["scadenza"] == "31/12/2026"
    assert d["marchio_identificazione"] == "IT 123 CE"
    assert d["sede_stabilimento"].startswith("Via Roma 1")
    assert d["peso_volume"] == "100 g"


def test_challenge_detection():
    class R:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        text = "<h2>Browser Validation Page</h2> www.salute.gov.it is using security service for protection"
    assert is_challenge(R())


def test_build_public(tmp_path):
    store = Store(tmp_path / "data")
    item = parse_detail((FIX / "dettaglio.html").read_text(), URL)
    item["id"] = recall_id(URL)
    item["dettagli"] = parse_pdf_text((FIX / "modello.txt").read_text())
    store.upsert(item)
    store.save()
    out = tmp_path / "public"
    build_public(store, out)
    summ = json.loads((out / "v1" / "richiami.json").read_text())
    assert summ[0]["id"] == "pop-corn-0"
    assert summ[0]["lotti"] == ["L2601", "L2602", "L26/03"]
    assert (out / "v1" / "richiami" / "pop-corn-0.json").exists()
    assert json.loads((out / "v1" / "meta.json").read_text())["totale"] == 1


def test_detail_all_details():
    item = parse_detail((FIX / "dettaglio.html").read_text(), URL)
    # Il modello di richiamo è preferito agli altri PDF.
    assert item["pdf_url"].endswith("modello-richiamo-pop-corn.pdf")
    urls = [a["url"] for a in item["allegati"]]
    assert any(u.endswith("nota-integrativa.pdf") for u in urls)
    assert any(u.endswith("foto-pop-corn.jpg") for u in urls)
    assert item["campi_pagina"]["Area"] == "Sicurezza alimentare"
    assert item["campi_pagina"]["Marca"] == "SALATI PREZIOSI"


def test_pdf_extra_and_text():
    d = parse_pdf_text((FIX / "modello.txt").read_text())
    assert d["campi_extra"]["Codice EAN"] == "8001234567890"
    assert "Marchio del prodotto" in d["testo"]


def test_summary_has_links(tmp_path):
    store = Store(tmp_path / "data")
    item = parse_detail((FIX / "dettaglio.html").read_text(), URL)
    item["id"] = recall_id(URL)
    store.upsert(item)
    out = tmp_path / "public"
    build_public(store, out)
    s = json.loads((out / "v1" / "richiami.json").read_text())[0]
    assert s["url"] == URL
    assert s["pdf_url"].endswith(".pdf")


def test_outdated(tmp_path):
    store = Store(tmp_path / "data")
    store.upsert({"id": "a", "url": "https://x/a/", "versione_parser": 1})
    store.upsert({"id": "b", "url": "https://x/b/", "versione_parser": 2})
    assert store.outdated(2) == ["https://x/a/"]


class FakeFetcher:
    """Simula tre pagine di elenco; la terza ripete la seconda (fine elenco)."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url):
        self.calls.append(url)

        class R:
            text = self.pages.get(url, "")
        return R()


def _page(ids, next_href=None):
    links = "".join(f'<a href="/new/it/ext-avviso-sicurezza-alimentare/{i}/">{i}</a>' for i in ids)
    nav = f'<a rel="next" href="{next_href}">Successiva</a>' if next_href else ""
    return f"<main>{links}{nav}</main>"


def test_crawl_listing_follows_next_link():
    from scraper.discovery import crawl_listing
    base = "https://www.salute.gov.it/new/it/avvisi/elenco/"
    pages = {
        base: _page(["a", "b"], "?page=1"),
        base + "?page=1": _page(["c"], "?page=2"),
        base + "?page=2": _page(["c"]),
    }
    f = FakeFetcher(pages)
    urls = crawl_listing(f, base, max_pages=10)
    assert [u.rstrip("/").rsplit("/", 1)[-1] for u in urls] == ["a", "b", "c"]


def test_crawl_listing_fallback_page_param():
    from scraper.discovery import crawl_listing
    base = "https://www.salute.gov.it/new/it/avvisi/elenco/"
    pages = {base: _page(["a"]), base + "?page=1": _page(["b"]), base + "?page=2": ""}
    urls = crawl_listing(FakeFetcher(pages), base, max_pages=10)
    assert len(urls) == 2


def test_clean_text_repairs_broken_characters():
    from scraper.parse import clean_text
    assert clean_text("Pasta di Salame con finocchio ¿ COD 497") == "Pasta di Salame con finocchio – COD 497"
    assert clean_text("TIRAMISU¿ 200g") == "TIRAMISÙ 200g"
    assert clean_text("FILETTI DI TONNO SURGELATI¿") == "FILETTI DI TONNO SURGELATÌ" or clean_text("FILETTI DI TONNO SURGELATI¿").startswith("FILETTI DI TONNO SURGELAT")
    assert clean_text("la citta\ufffd di Roma") == "la città di Roma"
    assert clean_text("olio dell¿oliva") == "olio dell'oliva"
    assert clean_text("Uova  biologiche ") == "Uova biologiche"
    assert clean_text(None) is None


def test_pdf_wrapped_labels_do_not_leak_into_values():
    text = """Denominazione di vendita: Verdure sott'olio
Marchio del prodotto: Ferri S.a.s. di Ferri Piero
Nome o ragione sociale dell'OSA a nome del quale il prodotto
è FERRI S.A.S DI FERRI PIERO
commercializzato
Nome del produttore: FERRI S.A.S. DI FERRI PIERO
Data di scadenza o termine minimo di 28/01/28
conservazione
Descrizione peso/volume unità di 900 G
vendita
Marchio di identificazione dello stabilimento/del AA000657041PEIT
produttore
"""
    d = parse_pdf_text(text)
    assert d["operatore"] == "FERRI S.A.S DI FERRI PIERO"
    assert d["scadenza"] == "28/01/28"
    assert d["peso_volume"] == "900 G"
    assert d["marchio_identificazione"] == "AA000657041PEIT"
    assert d["produttore"] == "FERRI S.A.S. DI FERRI PIERO"


def test_gatsby_page_data_url_and_slugs():
    from scraper.discovery import page_data_url, slugs_from_text
    assert page_data_url("https://www.salute.gov.it/new/it/avvisi/avvisi-e-richiami-di-prodotti-alimentari/") == \
        "https://www.salute.gov.it/new/page-data/it/avvisi/avvisi-e-richiami-di-prodotti-alimentari/page-data.json"
    text = '{"data":{"nodes":[{"path":"/it/ext-avviso-sicurezza-alimentare/pop-corn-0/"},' \
           '{"alias":"/new/it/ext-avviso-sicurezza-alimentare/uova-biologiche-6"},' \
           '{"path":"/it/ext-avviso-sicurezza-alimentare/pop-corn-0/"},{"path":"/it/avviso-sicurezza/altro/"}]}}'
    assert slugs_from_text(text) == ["pop-corn-0", "uova-biologiche-6"]


# --- Dati dell'elenco del portale (page-data.json) ---------------------------

def _page_data():
    return (FIX / "page-data.json").read_text(encoding="utf-8")


def test_records_from_page_data():
    from scraper.discovery import records_from_page_data
    recs = records_from_page_data(_page_data())
    assert len(recs) == 4
    assert "https://www.salute.gov.it/new/it/ext-avviso-sicurezza-alimentare/salsicciotta-con-finocchio-cod-5/" in recs


def test_parse_record_fields_and_repairs():
    from scraper.discovery import records_from_page_data
    from scraper.parse import parse_record
    items = [parse_record(n, u) for u, n in records_from_page_data(_page_data()).items()]
    a, b, revoca, dep = items
    assert a["titolo"] == "Salsicciotta con finocchio – COD 5"
    assert a["data_pubblicazione"] == "2026-10-23"
    assert a["marca"] == "SALUMI EMMEDUE SRL"
    assert a["categoria_rischio"] == "microbiologico" and a["tipo"] == "richiamo"
    assert a["pdf_path"].startswith("/sites/default/files/") and a["pdf_path"].endswith(".pdf")
    assert b["titolo"] == "FILETTI DI PESCE SPADA ALL'OLIO D'OLIVA 200g"
    assert revoca["tipo"] == "revoca"
    assert dep["depubblicato"] is True


def test_download_pdf_finds_public_prefix():
    import scraper.main as m

    class R:
        def __init__(self, content): self.content = content

    class F:
        calls = []
        def get(self, url):
            self.calls.append(url)
            return R(b"%PDF-1.4 ..." if "/new/sites/" not in url else b"<html>404</html>")

    m._pdf_prefix = None
    f = F()
    url, content = m.download_pdf(f, "/sites/default/files/x.pdf")
    assert url.endswith("www.salute.gov.it/sites/default/files/x.pdf") and content.startswith(b"%PDF")
    f.calls.clear()
    m.download_pdf(f, "/sites/default/files/y.pdf")
    assert len(f.calls) == 1  # il prefisso trovato viene riusato
    m._pdf_prefix = None


def test_store_one_file_per_month_and_migration(tmp_path):
    data = tmp_path / "data"
    (data / "richiami").mkdir(parents=True)
    # formati vecchi: file unico e un file per richiamo
    (data / "richiami.json").write_text(json.dumps({"a": {"id": "a", "url": "u/a/", "data_pubblicazione": "2026-01-01"}}), encoding="utf-8")
    (data / "richiami" / "c.json").write_text(json.dumps({"id": "c", "url": "u/c/", "data_pubblicazione": "2026-02-20"}), encoding="utf-8")
    store = Store(data)
    assert store.has("a") and store.has("c")
    store.upsert({"id": "b", "url": "u/b/", "data_pubblicazione": "2026-02-01"})
    store.upsert({"id": "d", "url": "u/d/"})  # senza data
    store.save()
    assert not (data / "richiami.json").exists()
    assert sorted(p.name for p in (data / "richiami").iterdir()) == ["2026-01.json", "2026-02.json", "senza-data.json"]
    again = Store(data)
    assert [i["id"] for i in again.sorted_items()][:3] == ["c", "b", "a"]
    # cambio di data: il richiamo passa da un mese all'altro
    item = dict(again.items["b"], data_pubblicazione="2026-03-05")
    again.upsert(item)
    again.save()
    feb = json.loads((data / "richiami" / "2026-02.json").read_text(encoding="utf-8"))
    mar = json.loads((data / "richiami" / "2026-03.json").read_text(encoding="utf-8"))
    assert "b" not in feb and "b" in mar
    # un salvataggio senza modifiche non riscrive nulla
    prima = (data / "richiami" / "2026-01.json").stat().st_mtime_ns
    Store(data).save()
    assert (data / "richiami" / "2026-01.json").stat().st_mtime_ns == prima


def test_looks_valid_rejects_unexpected_content():
    from scraper.fetch import looks_valid
    challenge = b"<!doctype html><html><head><title>Un momento</title></head><body>...</body></html>"
    assert looks_valid("https://x/page-data.json", b'{"result":{}}')
    assert not looks_valid("https://x/page-data.json", challenge)
    assert looks_valid("https://x/RSS.xml", b'<?xml version="1.0"?><rss version="2.0">')
    assert not looks_valid("https://x/RSS.xml", challenge)
    assert looks_valid("https://x/m.pdf", b"%PDF-1.7")
    assert not looks_valid("https://x/m.pdf", challenge)
    assert looks_valid("https://x/pagina/", challenge)  # per le pagine HTML decide il browser


def test_revocation_links():
    from scraper.links import link_revocations
    items = [
        {"id": "r1", "tipo": "richiamo", "titolo": "Robiola", "marca": "CAPRISS", "data_pubblicazione": "2026-07-16"},
        {"id": "v1", "tipo": "revoca", "titolo": "Robiola", "marca": "Capriss", "data_pubblicazione": "2026-09-08"},
        # stesso prodotto richiamato due volte: decide il lotto
        {"id": "a1", "tipo": "richiamo", "titolo": "Uova", "marca": "AIA", "data_pubblicazione": "2026-01-10", "lotti": ["L1"]},
        {"id": "a2", "tipo": "richiamo", "titolo": "Uova", "marca": "AIA", "data_pubblicazione": "2026-03-10", "lotti": ["L2"]},
        {"id": "va", "tipo": "revoca", "titolo": "Uova", "marca": "AIA", "data_pubblicazione": "2026-04-01", "lotti": ["L2"]},
        # revoca senza indizi sufficienti: nessun collegamento
        {"id": "b1", "tipo": "richiamo", "titolo": "Pane", "marca": "Forno Rossi", "data_pubblicazione": "2026-01-01"},
        {"id": "vb", "tipo": "revoca", "titolo": "Pane", "marca": "Bianchi spa", "data_pubblicazione": "2026-02-01"},
        # revoca precedente al richiamo: impossibile
        {"id": "c1", "tipo": "richiamo", "titolo": "Latte", "marca": "X", "data_pubblicazione": "2026-05-01"},
        {"id": "vc", "tipo": "revoca", "titolo": "Latte", "marca": "X", "data_pubblicazione": "2026-04-01"},
    ]
    links = link_revocations(items)
    assert links["v1"] == {"revoca_di": "r1"}
    assert links["r1"] == {"revocato_da": "v1", "revocato_il": "2026-09-08"}
    assert links["va"] == {"revoca_di": "a2"} and "a1" not in links
    assert "vb" not in links and "vc" not in links


def test_build_public_publishes_content(tmp_path):
    store = Store(tmp_path / "data")
    store.upsert({"id": "r1", "url": "u", "tipo": "richiamo", "titolo": "Robiola", "marca": "A", "data_pubblicazione": "2026-07-16"})
    store.upsert({"id": "v1", "url": "u", "tipo": "revoca", "titolo": "Robiola", "marca": "A", "data_pubblicazione": "2026-09-08"})
    content = tmp_path / "contenuti"
    content.mkdir()
    (content / "news.json").write_text('[{"id":"a","data":"2026-01-01","titolo":"Vecchia"},{"id":"b","data":"2026-02-01","titolo":"Nuova"}]', encoding="utf-8")
    (content / "approfondimenti.json").write_text("{ non valido", encoding="utf-8")
    out = tmp_path / "public"
    build_public(store, out, content_dir=content)
    summ = {s["id"]: s for s in json.loads((out / "v1" / "richiami.json").read_text())}
    assert summ["r1"]["revocato_da"] == "v1" and summ["v1"]["revoca_di"] == "r1"
    assert [n["id"] for n in json.loads((out / "v1" / "news.json").read_text())] == ["b", "a"]
    assert json.loads((out / "v1" / "approfondimenti.json").read_text()) == {"voci": []}


def test_real_content_files_are_valid():
    root = Path(__file__).parent.parent / "contenuti"
    voci = json.loads((root / "approfondimenti.json").read_text(encoding="utf-8"))["voci"]
    assert all(v["url"].startswith("https://") and v["titolo"] and v["testo"] for v in voci)
    assert isinstance(json.loads((root / "news.json").read_text(encoding="utf-8")), list)


# --- blocchi temporanei della protezione anti-bot ---------------------------------

def test_tolleranza_ai_blocchi(tmp_path):
    from datetime import datetime, timedelta, timezone
    from scraper.main import esito_senza_dati
    store = Store(tmp_path / "data")
    # nessun controllo riuscito registrato: è un errore
    assert esito_senza_dati(store) == 3
    adesso = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)
    store.segna_controllo_riuscito((adesso - timedelta(hours=3)).isoformat())
    assert esito_senza_dati(store, adesso) == 0          # blocco isolato: solo un avviso
    store.segna_controllo_riuscito((adesso - timedelta(hours=13)).isoformat())
    assert esito_senza_dati(store, adesso) == 3          # dati fermi da troppo: errore


def test_secondo_tentativo_dopo_un_blocco(tmp_path, monkeypatch):
    import types
    import scraper.main as m
    from scraper.fetch import BlockedError
    chiamate = []
    def finta_scoperta(fetcher, backfill=False):
        chiamate.append(1)
        if len(chiamate) == 1:
            raise BlockedError("verifica anti-bot")
        return ["https://www.salute.gov.it/new/it/x/richiamo-uno/"], {}
    monkeypatch.setattr(m, "discover", finta_scoperta)
    monkeypatch.setattr(m.config, "BLOCK_RETRY_WAIT", 0)
    monkeypatch.setattr(m, "process", lambda f, url, rec: {"id": "richiamo-uno", "url": url, "data_pubblicazione": "2026-11-09"})
    class FintoFetcher:
        def reset_browser(self): chiamate.append("reset")
    store = Store(tmp_path / "data")
    args = types.SimpleNamespace(url=None, backfill=False, max_new=40)
    nuovi = []
    assert m.run(FintoFetcher(), store, args, nuovi) == 0
    assert chiamate == [1, "reset", 1] and nuovi == ["richiamo-uno"]
    assert store.ore_dall_ultimo_controllo() is not None and store.ore_dall_ultimo_controllo() < 0.1


def test_meta_indica_l_ultimo_controllo_riuscito(tmp_path):
    store = Store(tmp_path / "data")
    store.upsert({"id": "a", "url": "u/a/", "data_pubblicazione": "2026-11-01"})
    store.save()
    store.segna_controllo_riuscito("2026-11-09T13:20:00+00:00")
    build_public(store, tmp_path / "public")
    meta = json.loads((tmp_path / "public" / "v1" / "meta.json").read_text(encoding="utf-8"))
    assert meta["generato_il"] == "2026-11-09T13:20:00+00:00"
    assert meta["pubblicato_il"] >= "2026-11-09"
