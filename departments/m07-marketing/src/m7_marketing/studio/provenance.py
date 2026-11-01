"""Journal append-only de la PROVENANCE des fonds générés (R5 §7, E7 : dossier de droits).

Chaque génération écrit un maillon chaîné (`journal_chaine`) : modèle, version, référence des poids, graine, invite et
invite négative, paramètres, nature du générateur (réel ou double), instantané de licence (verdict de la politique à ce
moment, empreinte du profil du client), empreinte de la demande et de la sortie, brief d'origine. Un maillon n'est
jamais
retouché ; la chaîne se vérifie. Le hachage de chaîne d'un maillon (`chaine`) est l'EMPREINTE DE PROVENANCE reportée
dans
les métadonnées des visuels : de l'image livrée on remonte au maillon, donc à la graine et à l'invite.

Aucun secret : un adaptateur ne remet jamais sa clé ; la masquer reste de la responsabilité de l'exécuteur
(`secrets_coffre.masquage`). Module pur : le journal est n'importe quelle séquence `append`/`len`/itération.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from .. import journal_chaine
from .generation import DemandeGeneration, SortieGeneration

TYPE_GENERATION = "generation"
REJ_JOURNAL_ALTERE = "REJ-STUDIO-PROVENANCE-JOURNAL-ALTERE"
REJ_PROVENANCE_INCOMPLETE = "REJ-STUDIO-PROVENANCE-INCOMPLETE"
CHAMPS_GENERATION = (
    "job_id",
    "brief_id",
    "brief_empreinte",
    "genre",
    "fournisseur_id",
    "modele",
    "version_modele",
    "poids_ref",
    "nature_generateur",
    "graine",
    "invite",
    "invite_negative",
    "parametres",
    "demande_empreinte",
    "licence",
    "sortie",
    "marquage_ia",
    "par",
)


class ProvenanceErreur(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code, self.detail = code, detail


def maillon_de(
    demande: DemandeGeneration,
    sortie: SortieGeneration,
    instantane_licence: Mapping[str, Any],
    fournisseur_id: str,
    par: str,
) -> dict[str, Any]:
    return {
        "job_id": demande.job_id,
        "brief_id": demande.brief_id,
        "brief_empreinte": demande.brief_empreinte,
        "genre": demande.genre,
        "fournisseur_id": fournisseur_id,
        "modele": sortie.modele,
        "version_modele": sortie.version_modele,
        "poids_ref": sortie.poids_ref,
        "nature_generateur": sortie.nature,
        "graine": sortie.graine,
        "invite": sortie.invite_effective,
        "invite_negative": demande.invite_negative,
        "parametres": {**dict(demande.parametres), **dict(sortie.parametres)},
        "demande_empreinte": demande.empreinte(),
        "licence": dict(instantane_licence),
        "sortie": {
            "sha256": hashlib.sha256(sortie.octets).hexdigest(),
            "octets": len(sortie.octets),
            "format": sortie.format,
            "largeur": sortie.largeur,
            "hauteur": sortie.hauteur,
            "duree_s": sortie.duree_s,
        },
        "marquage_ia": True,
        "par": par,
    }


def enregistrer(
    journal: Any,
    demande: DemandeGeneration,
    sortie: SortieGeneration,
    instantane_licence: Mapping[str, Any],
    fournisseur_id: str,
    par: str,
    horodatage: str,
) -> dict[str, Any]:
    """Ajoute le maillon de provenance et le rend (avec `chaine` : l'empreinte de provenance)."""
    problemes = journal_chaine.verifier(journal)
    if problemes:
        raise ProvenanceErreur(REJ_JOURNAL_ALTERE, "; ".join(problemes[:3]))
    donnees = maillon_de(demande, sortie, instantane_licence, fournisseur_id, par)
    if set(donnees) != set(CHAMPS_GENERATION):
        raise ProvenanceErreur(REJ_PROVENANCE_INCOMPLETE, "champs de provenance incomplets")
    if not donnees["invite"] or type(donnees["graine"]) is not int:
        raise ProvenanceErreur(REJ_PROVENANCE_INCOMPLETE, "invite et graine entière sont obligatoires")
    return journal_chaine.ajouter(journal, TYPE_GENERATION, donnees, horodatage)


def trouver(journal: Any, chaine: str) -> dict[str, Any] | None:
    """Le maillon dont l'empreinte de provenance (`chaine`) est celle-ci, si la chaîne est intègre."""
    if journal_chaine.verifier(journal):
        return None
    return next((m for m in journal_chaine.de_type(journal, TYPE_GENERATION) if m["chaine"] == chaine), None)


def trouver_par_sortie(journal: Any, sha256: str) -> dict[str, Any] | None:
    if journal_chaine.verifier(journal):
        return None
    return next((m for m in journal_chaine.de_type(journal, TYPE_GENERATION) if m["sortie"]["sha256"] == sha256), None)


def vers_provenance_de_composition(maillon: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que `composition.composer_visuel` reçoit : l'empreinte de provenance et les faits qui entrent au marquage."""
    return {
        "chaine": maillon["chaine"],
        "modele": maillon["modele"],
        "version_modele": maillon["version_modele"],
        "graine": maillon["graine"],
    }
