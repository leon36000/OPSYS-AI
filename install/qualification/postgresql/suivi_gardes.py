"""Suivi des points de passage des gardes portées pendant un test : « ce test PostgreSQL est-il passé AU-DELÀ du
contrôle de moteur ? ».

Pourquoi : une garde levée n'est « portée » que si un test PostgreSQL réel a exécuté le code qui la suit sans qu'elle
refuse. `gardes.portees()` donne, pour chaque point de contrôle, sa ligne de passage (la première instruction après le
`if … : raise`) ou, à défaut, le retour de sa fonction. Ce module surveille ces lignes avec `sys.monitoring`
(Python 3.12+) et rend, par test, les identifiants de points franchis. Rien n'est instrumenté dans le code livré.

Coût : un rappel par fonction distincte appelée et par test (désactivé aussitôt pour tout ce qui n'est pas une cible),
puis un rappel par ligne de passage. Inerte sans `OPSYS_QUALIF_PG_ADMIN_URL` (voir `plugin_pg.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parents[2]


class Suivi:
    def __init__(self, portees: list[dict]) -> None:
        self.vus: set[str] = set()
        self.par_fichier: dict[str, list[dict]] = {}
        for p in portees:
            self.par_fichier.setdefault(str(RACINE / p["fichier"]), []).append(p)
        self.outil = sys.monitoring.PROFILER_ID
        sys.monitoring.use_tool_id(self.outil, "opsys-gardes")
        e = sys.monitoring.events
        sys.monitoring.register_callback(self.outil, e.PY_START, self._debut)
        sys.monitoring.register_callback(self.outil, e.LINE, self._ligne)
        sys.monitoring.register_callback(self.outil, e.PY_RETURN, self._retour)
        sys.monitoring.register_callback(self.outil, e.PY_YIELD, self._retour)
        sys.monitoring.set_events(self.outil, e.PY_START)
        self._lignes: dict[tuple[str, int], list[str]] = {}
        self._retours: dict[tuple[str, int], list[str]] = {}

    def _debut(self, code, _offset):
        cibles = self.par_fichier.get(code.co_filename)
        if not cibles:
            return sys.monitoring.DISABLE
        fin = max((ligne for _, _, ligne in code.co_lines() if ligne), default=code.co_firstlineno)
        retenues = [p for p in cibles if code.co_firstlineno <= p["ligne"] <= fin]
        if not retenues:
            return sys.monitoring.DISABLE
        e = sys.monitoring.events
        for p in retenues:
            if p["passage"] is not None:
                self._lignes.setdefault((code.co_filename, p["passage"]), []).append(p["id"])
            else:
                self._retours.setdefault((code.co_filename, code.co_firstlineno), []).append(p["id"])
        sys.monitoring.set_local_events(self.outil, code, e.LINE | e.PY_RETURN | e.PY_YIELD)
        return sys.monitoring.DISABLE

    def _ligne(self, code, ligne):
        identifiants = self._lignes.get((code.co_filename, ligne))
        if identifiants:
            self.vus.update(identifiants)
        return sys.monitoring.DISABLE

    def _retour(self, code, _offset, _valeur):
        identifiants = self._retours.get((code.co_filename, code.co_firstlineno))
        if identifiants:
            self.vus.update(identifiants)
        return sys.monitoring.DISABLE

    def debut_de_test(self) -> None:
        self.vus = set()
        sys.monitoring.restart_events()

    def fin_de_test(self) -> list[str]:
        return sorted(self.vus)
