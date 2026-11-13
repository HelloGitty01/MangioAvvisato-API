"""Ricognizione dei siti delle catene di supermercati.

Da lanciare a mano (workflow "Ricognizione catene") prima di scrivere o
correggere un connettore. Per ogni catena apre il sito con Chromium, cerca i
collegamenti alle pagine dei richiami, le salva (HTML e screenshot) insieme ai
PDF che contengono, e scrive un riepilogo. Non modifica dati né pubblica nulla.

Uso:
    python -m scraper.ricognizione --out ricognizione [--catena coop]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .connettori import TUTTI
from .fetch import Fetcher, looks_like_challenge

log = logging.getLogger("ricognizione")

PAROLE = re.compile(r"richiam|ritir|allert|avvis[io] di sicurezza|sicurezza alimentare|recall", re.I)
MAX_PAGINE = 8
MAX_PDF = 6


def _stesso_sito(url: str, sito: str) -> bool:
    a, b = urlsplit(url).netloc.lower(), urlsplit(sito).netloc.lower()
    radice = lambda h: ".".join(h.split(".")[-2:])  # noqa: E731
    return radice(a) == radice(b)


def collegamenti(html: str, base: str, sito: str) -> tuple[list[dict], list[str]]:
    """Collegamenti che sembrano portare ai richiami, e PDF presenti nella pagina."""
    soup = BeautifulSoup(html, "html.parser")
    pagine, pdf = [], []
    for a in soup.find_all("a", href=True):
        url = urljoin(base, a["href"]).split("#")[0]
        testo = " ".join(a.get_text(" ", strip=True).split())[:120]
        if url.lower().split("?")[0].endswith(".pdf"):
            if url not in pdf:
                pdf.append(url)
            continue
        if _stesso_sito(url, sito) and (PAROLE.search(testo) or PAROLE.search(url)):
            if url not in [p["url"] for p in pagine]:
                pagine.append({"url": url, "testo": testo})
    return pagine, pdf


def _nome_file(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", url.split("//", 1)[-1])[:120]


def esplora(fetcher: Fetcher, connettore, cartella: Path) -> dict:
    cartella.mkdir(parents=True, exist_ok=True)
    rapporto = {"catena": connettore.nome, "sito": connettore.sito, "pagine": [], "pdf": [], "errori": []}
    coda = [connettore.sito, *connettore.pagine_note]
    visitate: set[str] = set()
    pdf_trovati: list[str] = []
    while coda and len(visitate) < MAX_PAGINE:
        url = coda.pop(0)
        if url in visitate:
            continue
        visitate.add(url)
        voce = {"url": url}
        try:
            risposta = fetcher.get(url)
            html = risposta.text
            nome = _nome_file(url)
            (cartella / f"{nome}.html").write_text(html, encoding="utf-8")
            if fetcher._page is not None:
                try:
                    fetcher._page.screenshot(path=str(cartella / f"{nome}.png"), full_page=True)
                except Exception as exc:  # noqa: BLE001
                    voce["screenshot"] = f"non salvato: {exc}"
            voce.update({
                "stato": risposta.status_code,
                "dimensione_kb": len(html.encode("utf-8")) // 1024,
                "verifica_antibot": looks_like_challenge(html),
                "titolo": (BeautifulSoup(html, "html.parser").title.get_text(strip=True) if BeautifulSoup(html, "html.parser").title else ""),
            })
            pagine, pdf = collegamenti(html, url, connettore.sito)
            voce["collegamenti_richiami"] = pagine[:30]
            voce["pdf"] = pdf[:30]
            # si seguono prima le pagine che nominano esplicitamente i richiami
            for p in sorted(pagine, key=lambda p: 0 if re.search(r"richiam", p["url"] + p["testo"], re.I) else 1):
                if p["url"] not in visitate:
                    coda.append(p["url"])
            pdf_trovati += [u for u in pdf if u not in pdf_trovati and PAROLE.search(u + " ")]
            pdf_trovati += [u for u in pdf if u not in pdf_trovati]
        except Exception as exc:  # noqa: BLE001
            voce["errore"] = str(exc).splitlines()[0]
            rapporto["errori"].append(f"{url}: {voce['errore']}")
        rapporto["pagine"].append(voce)

    for url in pdf_trovati[:MAX_PDF]:
        voce = {"url": url}
        try:
            contenuto = fetcher.get(url).content
            nome = _nome_file(url)
            (cartella / f"{nome}.pdf").write_bytes(contenuto)
            voce["dimensione_kb"] = len(contenuto) // 1024
            try:
                from .parse import extract_pdf_text
                testo = extract_pdf_text(contenuto, 60) or ""
                (cartella / f"{nome}.txt").write_text(testo, encoding="utf-8")
                voce["testo_estraibile"] = len(testo.strip()) > 50
            except Exception as exc:  # noqa: BLE001
                voce["testo_estraibile"] = False
                voce["errore_testo"] = str(exc).splitlines()[0]
        except Exception as exc:  # noqa: BLE001
            voce["errore"] = str(exc).splitlines()[0]
        rapporto["pdf"].append(voce)
    return rapporto


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("ricognizione"))
    ap.add_argument("--catena", action="append", help="solo questa catena (id, ripetibile)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    scelte = [c for c in TUTTI if not args.catena or c.id in args.catena]
    riepilogo = {}
    for connettore in scelte:
        log.info("Ricognizione %s (%s)", connettore.nome, connettore.sito)
        fetcher = Fetcher(use_browser_fallback=True)
        try:
            fetcher._start_browser()   # sempre il browser: servono gli screenshot
            riepilogo[connettore.id] = esplora(fetcher, connettore, args.out / connettore.id)
        except Exception as exc:  # noqa: BLE001
            riepilogo[connettore.id] = {"catena": connettore.nome, "errore": str(exc).splitlines()[0]}
        finally:
            fetcher.close()
        r = riepilogo[connettore.id]
        log.info("%s: %d pagine, %d PDF, %d errori", connettore.nome, len(r.get("pagine", [])), len(r.get("pdf", [])), len(r.get("errori", [])))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "riepilogo.json").write_text(json.dumps(riepilogo, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
