"""Curseurs de lecture et état d'ingestion.

Deux choses distinctes :

1. Le CURSEUR OPAQUE d'une page (`sig:v1:<source>:<charge>`) : ce qu'il faut pour demander la page suivante chez UN
   fournisseur (un décalage de ligne, un jeton de page). Il est lié à sa source : un curseur d'une autre source est
   refusé
   (`REJ-SIGNAUX-CURSEUR-INVALIDE`). Il ne contient jamais un secret ; sa taille est bornée.
2. L'ÉTAT D'INGESTION d'un flux (compte × flux) : la fenêtre en cours, le dernier curseur ATTEINT (écrit APRÈS les faits
   de la page, dans la même transaction), le repère `watermark` (jusqu'à quel jour la lecture est terminée), la dernière
   lecture réussie, le dernier échec typé et le compte de requêtes du jour (pour le quota). Registre append-only à
   chaîne
   de hachage ; l'état courant est le DERNIER maillon de chaque clé.

Un curseur avance seulement quand la page est écrite : un échec entre la lecture et l'écriture rejoue la page (les faits
sont idempotents), il ne la saute jamais.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import json
from collections.abc import Iterable
from typing import Any

from .. import journal_chaine
from .erreurs import refus

CURSEUR_MAX = 2048
M_ETAT = "etat_ingestion"


def encoder_curseur(source: str, donnees: dict[str, Any]) -> str:
    charge = base64.urlsafe_b64encode(json.dumps(donnees, sort_keys=True, separators=(",", ":")).encode()).decode()
    curseur = f"sig:v1:{source}:{charge.rstrip('=')}"
    if len(curseur) > CURSEUR_MAX:
        raise refus("REJ-SIGNAUX-CURSEUR-INVALIDE", "curseur trop long", 500)
    return curseur


def decoder_curseur(source: str, curseur: Any) -> dict[str, Any]:
    try:
        if not isinstance(curseur, str) or len(curseur) > CURSEUR_MAX:
            raise ValueError("taille")
        prefixe, version, src, charge = curseur.split(":", 3)
        if (prefixe, version, src) != ("sig", "v1", source):
            raise ValueError("origine")
        donnees = json.loads(base64.urlsafe_b64decode(charge + "=" * (-len(charge) % 4)))
        if not isinstance(donnees, dict):
            raise ValueError("forme")
        return donnees
    except (ValueError, binascii.Error, UnicodeError):
        raise refus("REJ-SIGNAUX-CURSEUR-INVALIDE", "curseur illisible ou d'une autre source", 422) from None


@dataclasses.dataclass(frozen=True)
class EtatIngestion:
    cle: str
    source: str
    compte_ref: str
    flux: str
    fenetre: str | None = None
    curseur: str | None = None
    termine: bool = False
    watermark: str | None = None
    derniere_lecture_reussie_le: str | None = None
    donnees_jusqu_au: str | None = None
    dernier_echec: tuple[tuple[str, str], ...] | None = None
    jour_quota: str | None = None
    appels_jour: int = 0

    def echec(self) -> dict[str, str] | None:
        return dict(self.dernier_echec) if self.dernier_echec else None


def cle_etat(source: str, compte_ref: str, flux: str) -> str:
    return f"{source}|{compte_ref}|{flux}"


def lire_etats(journal: Iterable[Any]) -> dict[str, EtatIngestion]:
    etats: dict[str, EtatIngestion] = {}
    for m in journal:
        if m["type"] != M_ETAT:
            raise refus("REJ-SIGNAUX-REGISTRE-INVALIDE", "maillon de curseur inattendu", 500)
        echec = m["dernier_echec"]
        etats[m["cle"]] = EtatIngestion(
            cle=m["cle"],
            source=m["source"],
            compte_ref=m["compte_ref"],
            flux=m["flux"],
            fenetre=m["fenetre"],
            curseur=m["curseur"],
            termine=m["termine"],
            watermark=m["watermark"],
            derniere_lecture_reussie_le=m["derniere_lecture_reussie_le"],
            donnees_jusqu_au=m["donnees_jusqu_au"],
            dernier_echec=tuple(sorted(echec.items())) if echec else None,
            jour_quota=m["jour_quota"],
            appels_jour=m["appels_jour"],
        )
    return etats


def ecrire_etat(journal: Any, etat: EtatIngestion, horodatage: str) -> None:
    journal_chaine.ajouter(
        journal,
        M_ETAT,
        {
            "cle": etat.cle,
            "source": etat.source,
            "compte_ref": etat.compte_ref,
            "flux": etat.flux,
            "fenetre": etat.fenetre,
            "curseur": etat.curseur,
            "termine": etat.termine,
            "watermark": etat.watermark,
            "derniere_lecture_reussie_le": etat.derniere_lecture_reussie_le,
            "donnees_jusqu_au": etat.donnees_jusqu_au,
            "dernier_echec": etat.echec(),
            "jour_quota": etat.jour_quota,
            "appels_jour": etat.appels_jour,
        },
        horodatage,
    )


__all__ = [
    "CURSEUR_MAX",
    "EtatIngestion",
    "cle_etat",
    "decoder_curseur",
    "ecrire_etat",
    "encoder_curseur",
    "lire_etats",
]
