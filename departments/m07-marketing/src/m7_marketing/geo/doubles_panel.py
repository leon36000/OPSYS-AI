"""Double déterministe d'un fournisseur d'API de moteur d'IA (port `PortMoteurIA`). Il ne parle à aucun service :
ses réponses sont scénarisées par question, dans l'ordre des répétitions, et ses pannes sont injectées. Il vérifie
le jeton attendu sans jamais le garder ni l'écrire. Une réponse peut contenir une consigne hostile : le panel ne
doit en tenir aucun compte.

Module sans entrée-sortie.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .panel import ErreurMoteur, ReponseMoteur


class DoubleMoteurIA:
    def __init__(self, reponses: Mapping[str, list[ReponseMoteur]], *, jeton_attendu: str,
                 defaut: ReponseMoteur | None = None, pannes: Iterable[str] = ()) -> None:
        self._reponses = {k: list(v) for k, v in reponses.items()}
        self._jeton_attendu = jeton_attendu
        self._defaut = defaut or ReponseMoteur("Aucune information.", (), 12, "double-1")
        self._pannes = iter(pannes)
        self._compteurs: dict[tuple[str, str], int] = {}
        self.appels: list[tuple[str, str]] = []

    def interroger(self, prompt: str, moteur: str, jeton: str) -> ReponseMoteur:
        self.appels.append((moteur, prompt))  # jamais le jeton
        if jeton != self._jeton_attendu:
            raise ErreurMoteur("REJ-GEO-MOTEUR-AUTH")
        panne = next(self._pannes, "ok")
        if panne == "limite":
            raise ErreurMoteur("REJ-GEO-MOTEUR-LIMITE", transitoire=True)
        if panne == "indisponible":
            raise ErreurMoteur("REJ-GEO-MOTEUR-INDISPONIBLE", transitoire=True)
        if panne == "exception_secrete":
            raise RuntimeError(f"échec de connexion avec le jeton {jeton}")
        if panne == "auth":
            raise ErreurMoteur("REJ-GEO-MOTEUR-AUTH")
        cle = (moteur, prompt)
        n = self._compteurs.get(cle, 0)
        self._compteurs[cle] = n + 1
        liste = self._reponses.get(prompt)
        return liste[n % len(liste)] if liste else self._defaut


__all__ = ["DoubleMoteurIA"]
