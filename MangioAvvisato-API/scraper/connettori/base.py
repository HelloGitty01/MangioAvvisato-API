"""Base comune dei connettori delle catene di supermercati.

Un connettore legge gli avvisi di richiamo pubblicati sul sito di una catena
(mai da aggregatori) e li trasforma in record con la stessa struttura dei
richiami del Ministero, più la fonte. Ogni connettore è indipendente: se il sito
di una catena cambia o non risponde, fallisce da solo senza fermare gli altri.

Regola sui dati: si estrae solo ciò che si legge con sicurezza. Un lotto o una
scadenza incerti si lasciano vuoti: un dato mancante è meglio di uno sbagliato.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..links import norm


@dataclass
class Avviso:
    """Un avviso trovato sul sito della catena, prima dell'elaborazione."""
    url: str
    titolo: str = ""
    data: str | None = None          # AAAA-MM-GG, se indicata
    extra: dict = field(default_factory=dict)


class Connettore:
    id: str = ""                     # identificativo breve: "coop", "lidl"...
    nome: str = ""                   # nome mostrato nell'app
    sito: str = ""                   # pagina principale del sito
    pagine_note: tuple[str, ...] = ()   # pagine dei richiami già note, per la ricognizione
    attivo: bool = False             # diventa True quando il lettore è scritto e collaudato
    max_per_esecuzione: int = 20

    # --- da implementare in ogni connettore ----------------------------------
    def scopri(self, fetcher) -> list[Avviso]:
        """Avvisi pubblicati sul sito, dal più recente."""
        raise NotImplementedError

    def elabora(self, fetcher, avviso: Avviso) -> dict:
        """Record del richiamo, con i campi comuni (vedi record_base)."""
        raise NotImplementedError

    # --- comuni ---------------------------------------------------------------
    def id_avviso(self, avviso: Avviso) -> str:
        """Identificativo stabile dell'avviso: catena + ultimo tratto dell'indirizzo."""
        coda = avviso.url.rstrip("/").split("/")[-1].split("?")[0]
        coda = re.sub(r"\.(html?|pdf|aspx)$", "", coda, flags=re.I)
        slug = re.sub(r"[^a-z0-9]+", "-", norm(coda)).strip("-") or re.sub(r"[^a-z0-9]+", "-", norm(avviso.titolo)).strip("-")
        return f"{self.id}-{slug[:80]}"

    def record_base(self, avviso: Avviso, **campi) -> dict:
        record = {
            "id": self.id_avviso(avviso),
            "tipo": "richiamo",
            "url": avviso.url,
            "titolo": avviso.titolo,
            "data_pubblicazione": avviso.data,
            "fonte": self.nome,
            "fonti": [self.id],
            "fonti_dettaglio": [{"id": self.id, "nome": self.nome, "tipo": "catena", "url": avviso.url, "data": avviso.data}],
            "catene": [self.nome],
            "dettagli": {},
        }
        record.update({k: v for k, v in campi.items() if v not in (None, "", [], {})})
        return record

    def descrizione(self) -> dict:
        return {"id": self.id, "nome": self.nome, "tipo": "catena", "sito": self.sito, "attivo": self.attivo}
