"""Connettore Conad.

Stato: in preparazione. Il lettore delle pagine verrà scritto sui risultati
della ricognizione (workflow "Ricognizione catene"); fino ad allora il
connettore resta disattivato e non viene eseguito.
"""

from __future__ import annotations

from .base import Connettore


class Conad(Connettore):
    id = "conad"
    nome = "Conad"
    sito = "https://www.conad.it/"
    pagine_note = ()
    attivo = False
