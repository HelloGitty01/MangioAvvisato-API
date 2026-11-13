"""Registro dei connettori delle catene di supermercati."""

from __future__ import annotations

from .base import Avviso, Connettore
from .carrefour import Carrefour
from .conad import Conad
from .coop import Coop
from .esselunga import Esselunga
from .lidl import Lidl

TUTTI: list[Connettore] = [Coop(), Esselunga(), Carrefour(), Lidl(), Conad()]


def attivi() -> list[Connettore]:
    return [c for c in TUTTI if c.attivo]


def per_id(cid: str) -> Connettore | None:
    return next((c for c in TUTTI if c.id == cid), None)


__all__ = ["Avviso", "Connettore", "TUTTI", "attivi", "per_id"]
