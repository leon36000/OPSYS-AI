"""Le catalogue des connecteurs de lecture : à chaque source déclarée, sa classe, et la manière de la construire.

`construire(compte, fournisseurs, ...)` rend le connecteur de la source du compte avec le transport donné ; SANS
transport,
c'est `TransportNonBranche` : tout appel est un refus typé (`REJ-SIGNAUX-TRANSPORT-NON-BRANCHE`). Aucun transport réel
n'existe
dans ce dépôt ; les doubles de test (`doubles_*.py`) sont les seuls transports qui répondent.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from . import modele
from .analytique import ConnecteurMatomo, ConnecteurUmami
from .base import ConnecteurLecture, FournisseurSecret
from .bing_webmaster import ConnecteurBingWebmaster
from .comptes import CompteSource
from .erreurs import refus
from .gbp import ConnecteurGbpAvis, ConnecteurGbpInsights
from .pagespeed import ConnecteurCrux, ConnecteurPageSpeed
from .publicite import ConnecteurGoogleAds, ConnecteurMetaAds
from .search_console import ConnecteurSearchConsole
from .transport import Transport, TransportNonBranche

CONNECTEURS: Mapping[str, type[ConnecteurLecture]] = {
    modele.SEARCH_CONSOLE: ConnecteurSearchConsole,
    modele.PAGESPEED: ConnecteurPageSpeed,
    modele.CRUX: ConnecteurCrux,
    modele.BING_WEBMASTER: ConnecteurBingWebmaster,
    modele.UMAMI: ConnecteurUmami,
    modele.MATOMO: ConnecteurMatomo,
    modele.GBP_AVIS: ConnecteurGbpAvis,
    modele.GBP_INSIGHTS: ConnecteurGbpInsights,
    modele.GOOGLE_ADS: ConnecteurGoogleAds,
    modele.META_ADS: ConnecteurMetaAds,
}


def construire(
    compte: CompteSource,
    fournisseurs: Mapping[str, FournisseurSecret],
    *,
    maintenant: Callable[[], datetime],
    masqueur: Any,
    transport: Transport | None = None,
) -> ConnecteurLecture:
    classe = CONNECTEURS.get(compte.source)
    if classe is None:
        raise refus("REJ-SIGNAUX-SOURCE-INCONNUE", f"aucun connecteur de lecture pour {compte.source!r}", 422)
    return classe(transport or TransportNonBranche(), compte, fournisseurs, maintenant=maintenant, masqueur=masqueur)


__all__ = ["CONNECTEURS", "construire"]
