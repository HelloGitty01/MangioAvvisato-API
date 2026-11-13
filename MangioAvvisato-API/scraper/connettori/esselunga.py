"""Connettore Esselunga.

Stato: in preparazione. Il lettore delle pagine verrà scritto sui risultati
della ricognizione (workflow "Ricognizione catene"); fino ad allora il
connettore resta disattivato e non viene eseguito.
"""

from __future__ import annotations

from .base import Connettore


class Esselunga(Connettore):
    id = "esselunga"
    nome = "Esselunga"
    sito = "https://www.esselunga.it/"
    pagine_note = ()
    attivo = False
