"""Archivio persistente (data/richiami.json) e generazione dell'API statica (public/)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .links import link_revocations

SUMMARY_FIELDS = (
    "id", "tipo", "data_pubblicazione", "marca", "denominazione",
    "motivo", "categoria_rischio", "lotti", "scadenza", "url", "pdf_url", "depubblicato",
    "revoca_di", "revocato_da", "revocato_il",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def recall_id(url: str) -> str:
    """L'ultimo segmento dell'URL di dettaglio è stabile: 'pop-corn-0'."""
    return url.rstrip("/").rsplit("/", 1)[-1]


class Store:
    """Archivio dei richiami: un file JSON per mese di pubblicazione,
    data/richiami/AAAA-MM.json (più "senza-data.json" per i pochi senza data).

    Un file per mese tiene il repository leggero (ogni esecuzione modifica di
    solito solo il mese corrente) e facile da sfogliare (un centinaio di file).
    I formati precedenti (file unico data/richiami.json, oppure un file per
    richiamo) vengono letti e convertiti automaticamente al primo salvataggio.
    """

    def __init__(self, data_dir: Path):
        self.dir = data_dir / "richiami"
        self.legacy = data_dir / "richiami.json"
        self.items: dict[str, dict] = {}
        self._mese: dict[str, str] = {}          # id -> mese del file in cui si trova
        self._mesi_da_scrivere: set[str] = set()
        self._da_rimuovere: list[Path] = []
        if self.legacy.exists():
            self.items.update(json.loads(self.legacy.read_text(encoding="utf-8")) or {})
            self._da_rimuovere.append(self.legacy)
        if self.dir.exists():
            for f in sorted(self.dir.glob("*.json")):
                contenuto = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(contenuto, dict) and "id" in contenuto:   # vecchio formato: un file per richiamo
                    self.items[contenuto["id"]] = contenuto
                    self._da_rimuovere.append(f)
                else:                                                   # formato attuale: un file per mese
                    for rid, item in contenuto.items():
                        self.items[rid] = item
                        self._mese[rid] = f.stem
        # tutto ciò che arriva da un formato vecchio va riscritto nei file mensili
        for rid, item in self.items.items():
            if rid not in self._mese:
                self._mesi_da_scrivere.add(self.mese_di(item))

    @staticmethod
    def mese_di(item: dict) -> str:
        data = item.get("data_pubblicazione") or ""
        return data[:7] if len(data) >= 7 and data[4] == "-" else "senza-data"

    def has(self, rid: str) -> bool:
        return rid in self.items

    def outdated(self, version: int) -> list[str]:
        """URL dei richiami elaborati con una versione dei parser precedente."""
        return [i["url"] for i in self.sorted_items() if i.get("versione_parser", 1) < version]

    def upsert(self, item: dict) -> None:
        old = self.items.get(item["id"], {})
        item["prima_rilevazione"] = old.get("prima_rilevazione", now_iso())
        item["ultimo_aggiornamento"] = now_iso()
        self.items[item["id"]] = item
        self._mesi_da_scrivere.add(self.mese_di(item))
        if item["id"] in self._mese:          # se la data è cambiata, va riscritto anche il mese vecchio
            self._mesi_da_scrivere.add(self._mese[item["id"]])

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        if self._mesi_da_scrivere:
            per_mese: dict[str, dict] = {}
            for rid, item in self.items.items():
                per_mese.setdefault(self.mese_di(item), {})[rid] = item
            for mese in sorted(self._mesi_da_scrivere):
                f = self.dir / f"{mese}.json"
                voci = per_mese.get(mese)
                if not voci:
                    f.unlink(missing_ok=True)
                    continue
                tmp = self.dir / f"{mese}.json.tmp"
                tmp.write_text(json.dumps(dict(sorted(voci.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                tmp.replace(f)
                for rid in voci:
                    self._mese[rid] = mese
            self._mesi_da_scrivere.clear()
        for f in self._da_rimuovere:
            f.unlink(missing_ok=True)
        self._da_rimuovere.clear()

    def sorted_items(self) -> list[dict]:
        return sorted(
            self.items.values(),
            key=lambda i: (i.get("data_pubblicazione") or "", i.get("prima_rilevazione") or ""),
            reverse=True,
        )


def summary(item: dict) -> dict:
    flat = {**item, **{k: v for k, v in (item.get("dettagli") or {}).items() if k in ("lotti", "scadenza")}}
    return {k: flat.get(k) for k in SUMMARY_FIELDS}


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _load_content(path: Path, default):
    """Contenuti curati a mano (notizie, approfondimenti): un errore di
    sintassi nel file non deve bloccare la pubblicazione dei richiami."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"ATTENZIONE: {path.name} non è un JSON valido ({exc}): pubblico la versione vuota")
        return default


def build_public(store: Store, out_dir: Path, static_dir: Path | None = None, content_dir: Path | None = None) -> None:
    """Genera l'API statica. La cartella viene ricreata da zero a ogni esecuzione."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    v1 = out_dir / "v1"
    # collegamenti revoca <-> richiamo, ricalcolati a ogni pubblicazione
    links = link_revocations(list(store.items.values()))
    items = [{**i, **links.get(i["id"], {})} for i in store.sorted_items()]
    summaries = [summary(i) for i in items]

    _write(v1 / "richiami.json", summaries)
    _write(v1 / "ultimi.json", summaries[: config.LATEST_COUNT])
    _write(v1 / "revoche.json", [s for s in summaries if s["tipo"] == "revoca"])
    for item in items:
        _write(v1 / "richiami" / f"{item['id']}.json", item)
    _write(
        v1 / "meta.json",
        {
            "schema_version": config.SCHEMA_VERSION,
            "generato_il": now_iso(),
            "totale": len(items),
            "fonte": "Ministero della Salute - Richiami di prodotti alimentari da parte degli operatori",
            "avvertenza": "Dati non ufficiali. Fa fede esclusivamente la pubblicazione sul portale del Ministero della Salute.",
        },
    )
    if content_dir is not None:
        news = _load_content(content_dir / "news.json", [])
        news = sorted(news, key=lambda n: n.get("data", ""), reverse=True) if isinstance(news, list) else []
        _write(v1 / "news.json", news)
        _write(v1 / "approfondimenti.json", _load_content(content_dir / "approfondimenti.json", {"voci": []}))
    (out_dir / ".nojekyll").touch()
    if static_dir and static_dir.exists():
        for f in static_dir.iterdir():
            if f.is_file():
                shutil.copy(f, out_dir / f.name)
