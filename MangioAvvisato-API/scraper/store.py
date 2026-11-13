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
    "fonti", "catene", "punti_vendita",
)

# campi che un nuovo passaggio del Ministero non deve cancellare
CAMPI_FONTI = ("fonti", "fonti_dettaglio", "catene", "punti_vendita", "id_catene", "id_ministero")


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
        self._alias: dict[str, str] = {}
        for item in self.items.values():
            self._indicizza(item)
        # tutto ciò che arriva da un formato vecchio va riscritto nei file mensili
        for rid, item in self.items.items():
            if rid not in self._mese:
                self._mesi_da_scrivere.add(self.mese_di(item))

    @staticmethod
    def mese_di(item: dict) -> str:
        data = item.get("data_pubblicazione") or ""
        return data[:7] if len(data) >= 7 and data[4] == "-" else "senza-data"

    # --- stato dei controlli sul portale ---------------------------------------
    @property
    def _file_stato(self) -> Path:
        return self.dir.parent / "stato.json"

    def stato(self) -> dict:
        try:
            return json.loads(self._file_stato.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def segna_controllo_riuscito(self, quando: str | None = None, fonte: str = "ministero") -> None:
        """Registra l'ora dell'ultimo controllo andato a buon fine su una fonte."""
        stato = self.stato()
        quando = quando or now_iso()
        stato.setdefault("fonti", {})[fonte] = quando
        if fonte == "ministero":
            stato["ultimo_controllo_riuscito"] = quando
        self._file_stato.parent.mkdir(parents=True, exist_ok=True)
        self._file_stato.write_text(json.dumps(stato, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def ore_dall_ultimo_controllo(self, adesso: datetime | None = None) -> float | None:
        valore = self.stato().get("ultimo_controllo_riuscito")
        if not valore:
            return None
        try:
            quando = datetime.fromisoformat(valore)
        except ValueError:
            return None
        adesso = adesso or datetime.now(timezone.utc)
        return (adesso - quando).total_seconds() / 3600

    def _indicizza(self, item: dict) -> None:
        for alias in [item.get("id_ministero"), *(item.get("id_catene") or [])]:
            if alias:
                self._alias[alias] = item["id"]

    def id_effettivo(self, rid: str) -> str | None:
        """Id del record che contiene questo richiamo (anche se arrivato da un'altra fonte)."""
        if rid in self.items:
            return rid
        return self._alias.get(rid)

    def has(self, rid: str) -> bool:
        return self.id_effettivo(rid) is not None

    def outdated(self, version: int) -> list[str]:
        """URL dei richiami elaborati con una versione dei parser precedente."""
        return [i["url"] for i in self.sorted_items() if i.get("versione_parser", 1) < version]

    def upsert(self, item: dict) -> None:
        old = self.items.get(item["id"], {})
        for campo in CAMPI_FONTI:
            if campo in old and campo not in item:
                item[campo] = old[campo]
        item["prima_rilevazione"] = old.get("prima_rilevazione", now_iso())
        item["ultimo_aggiornamento"] = now_iso()
        self.items[item["id"]] = item
        self._indicizza(item)
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


def con_fonti(item: dict) -> dict:
    """I record del Ministero precedenti alle fonti multiple non hanno i campi delle fonti."""
    if item.get("fonti"):
        return item
    voce = {"id": "ministero", "nome": "Ministero della Salute", "tipo": "ministero",
            "url": item.get("url"), "data": item.get("data_pubblicazione")}
    return {**item, "fonti": ["ministero"], "fonti_dettaglio": [voce], "catene": item.get("catene") or []}


def summary(item: dict) -> dict:
    item = con_fonti(item)
    flat = {**item, **{k: v for k, v in (item.get("dettagli") or {}).items() if k in ("lotti", "scadenza")}}
    return {k: flat.get(k) for k in SUMMARY_FIELDS if flat.get(k) not in (None, []) or k in ("id", "tipo")}


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
    """Genera l'API statica. La cartella viene ricreata da zero a ogni esecuzione.

    Due versioni affiancate:
    - v1: solo i richiami pubblicati dal Ministero, per le app precedenti alle fonti
      multiple (non saprebbero distinguere un richiamo segnalato solo da una catena);
    - v2: tutti i richiami, con le fonti, più fonti.json.
    """
    if out_dir.exists():
        shutil.rmtree(out_dir)
    # collegamenti revoca <-> richiamo, ricalcolati a ogni pubblicazione
    links = link_revocations(list(store.items.values()))
    items = [con_fonti({**i, **links.get(i["id"], {})}) for i in store.sorted_items()]
    ministeriali = [i for i in items if "ministero" in i["fonti"]]

    news = approfondimenti = None
    if content_dir is not None:
        news = _load_content(content_dir / "news.json", [])
        news = sorted(news, key=lambda n: n.get("data", ""), reverse=True) if isinstance(news, list) else []
        approfondimenti = _load_content(content_dir / "approfondimenti.json", {"voci": []})

    _scrivi_versione(out_dir / "v1", ministeriali, store, news, approfondimenti)
    _scrivi_versione(out_dir / "v2", items, store, news, approfondimenti, fonti=elenco_fonti(store))

    (out_dir / ".nojekyll").touch()
    if static_dir and static_dir.exists():
        for f in static_dir.iterdir():
            if f.is_file():
                shutil.copy(f, out_dir / f.name)


def _scrivi_versione(cartella: Path, items: list[dict], store: Store, news, approfondimenti, fonti: list[dict] | None = None) -> None:
    summaries = [summary(i) for i in items]
    _write(cartella / "richiami.json", summaries)
    _write(cartella / "ultimi.json", summaries[: config.LATEST_COUNT])
    _write(cartella / "revoche.json", [s for s in summaries if s["tipo"] == "revoca"])
    for item in items:
        _write(cartella / "richiami" / f"{item['id']}.json", item)
    _write(
        cartella / "meta.json",
        {
            "schema_version": config.SCHEMA_VERSION if fonti is None else 2,
            # Ora dell'ultimo controllo riuscito sul portale (quella mostrata dall'app);
            # se non è nota, l'ora di generazione.
            "generato_il": store.stato().get("ultimo_controllo_riuscito") or now_iso(),
            "pubblicato_il": now_iso(),
            "totale": len(items),
            "fonte": "Ministero della Salute - Richiami di prodotti alimentari da parte degli operatori"
            if fonti is None else "Ministero della Salute e catene di supermercati (vedi fonti.json)",
            "avvertenza": "Dati non ufficiali. Fa fede esclusivamente la pubblicazione sul portale del Ministero della Salute.",
        },
    )
    if fonti is not None:
        _write(cartella / "fonti.json", fonti)
    if news is not None:
        _write(cartella / "news.json", news)
        _write(cartella / "approfondimenti.json", approfondimenti)


def elenco_fonti(store: Store) -> list[dict]:
    """Le fonti delle segnalazioni, con l'ora dell'ultimo controllo riuscito.
    Le catene compaiono anche quando il connettore è ancora in preparazione
    (attivo=false), così l'app può indicarle come in arrivo."""
    from .connettori import TUTTI

    controlli = store.stato().get("fonti", {})
    if "ministero" not in controlli and store.stato().get("ultimo_controllo_riuscito"):
        controlli["ministero"] = store.stato()["ultimo_controllo_riuscito"]
    fonti = [{
        "id": "ministero", "nome": "Ministero della Salute", "tipo": "ministero",
        "sito": "https://www.salute.gov.it/new/it/avvisi/avvisi-e-richiami-di-prodotti-alimentari/",
        "attivo": True, "ultimo_controllo": controlli.get("ministero"),
    }]
    for c in TUTTI:
        fonti.append({**c.descrizione(), "ultimo_controllo": controlli.get(c.id)})
    return fonti
