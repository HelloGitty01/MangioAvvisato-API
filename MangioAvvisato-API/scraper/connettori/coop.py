"""Connettore Coop.

Stato: in preparazione. Il lettore delle pagine verrà scritto sui risultati
della ricognizione (workflow "Ricognizione catene"); fino ad allora il
connettore resta disattivato e non viene eseguito.
"""

from __future__ import annotations

from .base import Connettore


class Coop(Connettore):
    id = "coop"
    nome = "Coop"
    sito = "https://www.coop.it/"
    pagine_note = ("https://www.coop.it/richiamo-prodotti", "https://www.coop.it/node/11490")
    attivo = False
