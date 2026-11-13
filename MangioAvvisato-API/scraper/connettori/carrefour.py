"""Connettore Carrefour Italia.

Stato: in preparazione. Il lettore delle pagine verrà scritto sui risultati
della ricognizione (workflow "Ricognizione catene"); fino ad allora il
connettore resta disattivato e non viene eseguito.
"""

from __future__ import annotations

from .base import Connettore


class Carrefour(Connettore):
    id = "carrefour"
    nome = "Carrefour Italia"
    sito = "https://www.carrefour.it/"
    pagine_note = ('https://www.carrefour.it/richiamo-prodotti.html',)
    attivo = False
