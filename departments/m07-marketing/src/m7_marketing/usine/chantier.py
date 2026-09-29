"""D'un chantier terminé à cinq contenus en attente (PLAN T4.17, M7.3 « chantier → contenu »).

Les contenus naissent du WCT `m4.travaux_termines` déjà reçu par le bus et du profil de marque du client,
jamais d'un fait fourni par l'appelant. Ce module décide, compose et contrôle ; il n'écrit rien : l'adaptateur
(`outils.py`) lit les registres, lui passe les maillons, et écrit ce qu'il rend.

Ordre des refus (le plus fondamental d'abord, aucun travail inutile ensuite, RIEN d'écrit) :
  1. un retrait du consentement marketing de ce chantier (`retrait`) ;
  2. le consentement marketing absent, faux, ou sans sa preuve (`contenu_public.verifier_consentement`) ;
  3. un client connu insatisfait (`client_satisfait = false`) : on ne fait pas la vitrine d'un chantier que
     son client a jugé mauvais ;
  4. la nature des travaux inconnue, le profil de marque non configuré (adaptateur).

Puis, par plateforme : le texte (gabarit du code, ou texte rédigé par le modèle) passe `controle_texte` ; un
texte refusé n'est jamais enregistré, un texte accepté devient une PROPOSITION `PROPOSE` — jamais publiée,
jamais approuvée par ce module (`decision`). Idempotent : un chantier ne produit jamais deux fois la même
plateforme ; après un rejet, un nouveau texte crée une révision.

Module pur : aucune entrée-sortie, aucun import `opsys`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import unicodedata
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from ..content.contenu_public import verifier_consentement
from ..utm import utm_engine
from . import gabarits, plateformes, registre, retrait, verdicts
from .controle_texte import ContexteControle, controler_texte
from .plateformes import Plateforme

# Un champ du profil de marque qui porte encore ce repère n'a pas été renseigné par le client : il n'entre
# jamais dans un texte public (`profil_client.PLACEHOLDER_NOM` en est le cas du nom, refusé en amont).
MARQUEUR_NON_CONFIGURE = "à configurer"

STATUT_PROPOSE = "propose"
STATUT_DEJA_PROPOSE = "deja_propose"
STATUT_PARTIEL = "partiel"
STATUT_TEXTES_REFUSES = "textes_refuses"
STATUT_REFUSE = "refuse"
STATUT_CONSENTEMENT_RETIRE = "consentement_retire"
STATUT_NATURE_INCONNUE = "nature_inconnue"

ITEM_PROPOSE = "propose"
ITEM_DEJA = "deja_propose"
ITEM_REFUSE = "refuse"
ITEM_TEXTE_REQUIS = "texte_requis"

MOTS_CLICS_MAX = 10
MOTS_CLICS_SERVICE_MAX = 3
DESCRIPTION_MAX = 600
REFUS_CLIENT_INSATISFAIT = (
    "client_satisfait = false : aucun contenu public d'un chantier dont le client est insatisfait"
)
REFUS_WCT_ID_ABSENT = "wct_id absent de la charge (fail-closed) : identifiant de contenu impossible"


@dataclasses.dataclass(frozen=True)
class Nature:
    """La nature des travaux, en mots : libellé du service de l'entreprise (lead v2) ou `type_travaux` sans
    ses soulignés (lead v1), avec les termes qui alimentent les mots-clics."""

    libelle: str
    mots_cles: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Preparation:
    """Ce que `preparer` décide : les propositions à écrire, et le compte rendu par plateforme."""

    statut: str
    nouvelles: tuple[dict[str, Any], ...]
    items: tuple[dict[str, Any], ...]


def _texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _chaine(profil: Mapping[str, Any], cle: str) -> str:
    valeur = profil.get(cle)
    return valeur.strip() if isinstance(valeur, str) else ""


# -- refus de départ -----------------------------------------------------------------------------------------
def verifier_chantier(
    charge: Mapping[str, Any], retraits: Iterable[Mapping[str, Any]],
) -> tuple[str | None, str | None]:
    """`(None, None)` si le chantier peut donner du contenu, sinon `(statut, motif)` : rien n'est écrit."""
    wct_id = charge.get("wct_id")
    if not _texte_non_vide(wct_id):
        return STATUT_REFUSE, REFUS_WCT_ID_ABSENT
    bloquant = retrait.retrait_applicable(wct_id, charge.get("lead_id"), retraits)
    if bloquant is not None:
        return STATUT_CONSENTEMENT_RETIRE, (
            f"consentement marketing retiré par le client (retrait {bloquant['retrait_id']}, canal "
            f"{bloquant['canal']}) : aucune tâche de contenu pour ce chantier"
        )
    motif = verifier_consentement(charge)
    if motif is not None:
        return STATUT_REFUSE, motif
    if charge.get("client_satisfait") is False:
        return STATUT_REFUSE, REFUS_CLIENT_INSATISFAIT
    return None, None


# -- la matière d'un chantier ---------------------------------------------------------------------------------
def _mot_clic(terme: str) -> str | None:
    """`#gouttiere` : sans accents, sans espaces ni ponctuation ; `None` si rien d'exploitable."""
    sans_accents = "".join(c for c in unicodedata.normalize("NFD", terme) if not unicodedata.combining(c))
    corps = re.sub(r"[^a-z0-9]", "", sans_accents.casefold())
    return f"#{corps}" if len(corps) >= 3 else None


def mots_clics(nature: Nature, ville: str | None, profil: Mapping[str, Any]) -> tuple[str, ...]:
    """Les mots-clics du chantier : termes du service, ville, puis ceux que le profil de marque déclare.
    Tous tirés de faits ; dédoublonnés, au plus `MOTS_CLICS_MAX`."""
    candidats: list[str | None] = [_mot_clic(terme) for terme in nature.mots_cles[:MOTS_CLICS_SERVICE_MAX]]
    if ville:
        candidats.append(_mot_clic(ville))
    declares = profil.get("hashtags")
    if isinstance(declares, list):
        candidats.extend(_mot_clic(terme) for terme in declares if isinstance(terme, str))
    retenus: list[str] = []
    for mot in candidats:
        if mot is not None and mot not in retenus:
            retenus.append(mot)
    return tuple(retenus[:MOTS_CLICS_MAX])


def matiere_du_chantier(
    charge: Mapping[str, Any], profil: Mapping[str, Any], nature: Nature,
) -> tuple[gabarits.Matiere, list[str]]:
    """La `Matiere` des gabarits et les avertissements communs aux cinq contenus (ce qui manque, dit tel quel)."""
    avertissements: list[str] = []
    ville = charge.get("ville") if _texte_non_vide(charge.get("ville")) else None
    if ville is None:
        avertissements.append("ville absente du WCT (M4 ne la publie pas) : contenu sans ancrage local")
    accroche = _chaine(profil, "tagline")
    if accroche.casefold().startswith(MARQUEUR_NON_CONFIGURE):
        avertissements.append("accroche du profil de marque non configurée : le texte n'en porte pas")
        accroche = ""
    if charge.get("ecart_signale") is True:
        avertissements.append("chantier en revue (écart signalé) : à vérifier avant de publier")
    matiere = gabarits.Matiere(marque=profil["name"], accroche=accroche, nature=nature.libelle, ville=ville)
    return matiere, avertissements


def contexte_controle(
    charge: Mapping[str, Any], profil: Mapping[str, Any], longueur_max: int | None,
) -> ContexteControle:
    """Le contexte du contrôle d'un texte de ce chantier : la marque, les garanties validées du profil, et les
    identifiants du WCT qui ne doivent jamais paraître."""
    garanties = profil.get("garanties_validees")
    identifiants = tuple(
        charge[cle] for cle in ("wct_id", "intervention_id", "lead_id", "technicien_id", "devis_id", "hash_maillon")
        if _texte_non_vide(charge.get(cle))
    )
    return ContexteControle(
        garanties_validees=tuple(g for g in garanties if _texte_non_vide(g)) if isinstance(garanties, list) else (),
        noms_de_marque=(profil["name"],),
        identifiants=identifiants,
        longueur_max=longueur_max,
    )


def description_utilisable(charge: Mapping[str, Any], profil: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """`(description, None)` si la note du chantier (`description_factuelle`, écrite par l'employé) peut être
    montrée au modèle qui rédige ; `(None, motif)` sinon. Une note libre peut contenir un nom ou une adresse :
    elle passe le même contrôle qu'un texte public, et une note trop longue n'est pas montrée."""
    description = charge.get("description_factuelle")
    if not _texte_non_vide(description):
        return None, None
    if len(description) > DESCRIPTION_MAX:
        return None, f"note du chantier trop longue ({len(description)} caractères, {DESCRIPTION_MAX} au plus)"
    violations = controler_texte(description, contexte_controle(charge, profil, None))
    if violations:
        regles = ", ".join(v.regle for v in violations)
        return None, f"note du chantier non utilisable ({regles}) : elle n'est pas montrée"
    return description, None


# -- lien de suivi ---------------------------------------------------------------------------------------------
def lien_utm(
    plateforme: Plateforme, charge: Mapping[str, Any], profil: Mapping[str, Any], nature: Nature,
) -> tuple[str | None, dict[str, str] | None, str | None]:
    """`(lien, utm, avertissement)` : le lien de suivi de cette variante, validé contre le contrat gelé
    (U-01 à U-12), ou `(None, None, ce qu'il faut configurer)`. Jamais un domaine par défaut."""
    if plateforme.source_utm is None or plateforme.medium_utm is None:
        return None, None, None
    site = _chaine(profil, "site_url")
    if not site:
        return None, None, "site_url absent du profil de marque : aucun lien de suivi pour cette variante"
    try:
        annee = int(str(charge["horodatage_completion"])[:4])
        campagne = utm_engine.construire_campaign("contenu", nature.libelle, annee)
    except (KeyError, ValueError):
        return None, None, "lien de suivi impossible : année du chantier ou nature des travaux illisible"
    contenu = f"{plateforme.code}-{hashlib.sha256(str(charge['wct_id']).encode('utf-8')).hexdigest()[:8]}"
    lien = utm_engine.generer_lien_utm(site, plateforme.source_utm, plateforme.medium_utm, campagne, contenu)
    verdicts_utm = utm_engine.valider_lien_utm(lien)
    echecs = [f"{regle} {detail}".strip() for regle, verdict, detail in verdicts_utm if verdict == "fail"]
    if echecs:
        return None, None, f"lien de suivi non conforme au contrat UTM ({'; '.join(echecs)}) : site_url du profil ?"
    return lien, {
        "source": plateforme.source_utm, "medium": plateforme.medium_utm, "campaign": campagne, "content": contenu,
    }, None


# -- proposition ----------------------------------------------------------------------------------------------
def _avertissements_media(plateforme: Plateforme, photos: list[str]) -> list[str]:
    if photos or plateforme.media == plateformes.MEDIA_AUCUN:
        return []
    if plateforme.media == plateformes.MEDIA_REQUIS:
        return [f"{plateforme.libelle} exige un média : aucune photo dans le WCT, à ajouter à la main"]
    return ["aucune photo dans le WCT : publication sans média"]


def _proposition(
    charge: Mapping[str, Any], plateforme: Plateforme, revision: int, texte: str, origine_texte: str,
    nature: Nature, matiere: gabarits.Matiere, profil: Mapping[str, Any], avertissements: list[str], origine: str,
) -> dict[str, Any]:
    photos = [p for p in (charge.get("photos") or []) if isinstance(p, str)]
    lien, utm, avertissement_lien = lien_utm(plateforme, charge, profil, nature)
    canonique = json.dumps(
        {"wct_id": charge["wct_id"], "plateforme": plateforme.code, "revision": revision, "type": "contenu_chantier"},
        sort_keys=True,
    )
    return {
        "contenu_id": str(uuid.uuid5(uuid.NAMESPACE_URL, canonique)),
        "type": "contenu_chantier",
        "wct_id": charge["wct_id"],
        "lead_id": charge.get("lead_id"),
        "intervention_id": charge.get("intervention_id"),
        "plateforme": plateforme.code,
        "revision": revision,
        "nature": nature.libelle,
        "ville": matiere.ville,
        "texte": texte,
        "origine_texte": origine_texte,
        "empreinte_texte": hashlib.sha256(texte.encode("utf-8")).hexdigest(),
        "mots_clics": list(mots_clics(nature, matiere.ville, profil)) if plateforme.public else [],
        "lien_utm": lien,
        "utm": utm,
        "photos": photos,
        "avertissements": [
            *avertissements,
            *_avertissements_media(plateforme, photos),
            *([avertissement_lien] if avertissement_lien else []),
        ],
        "preuve_consentement": {
            "consentement_marketing": True,
            "recueilli_par": charge["consentement_recueilli_par"],
            "recueilli_le": charge["consentement_recueilli_le"],
            "version_texte": charge["consentement_version_texte"],
            "source": "wct_m4_travaux_termines",
            "wct_id": charge["wct_id"],
        },
        "origine": origine,
        "propose_le": charge["horodatage_completion"],
        "approval_status": registre.STATUT_PROPOSE,  # invariant — jamais auto-publié (D-043)
    }


def _apercu(texte: str) -> str:
    une_ligne = " ".join(texte.split())
    return une_ligne if len(une_ligne) <= 120 else une_ligne[:119] + "…"


def _item_existant(proposition: Mapping[str, Any], statut_courant: str) -> dict[str, Any]:
    return {
        "plateforme": proposition["plateforme"], "statut": ITEM_DEJA, "contenu_id": proposition["contenu_id"],
        "revision": proposition["revision"], "approval_status": statut_courant, "apercu": _apercu(proposition["texte"]),
    }


def preparer(
    charge: Mapping[str, Any], profil: Mapping[str, Any], nature: Nature, textes: Mapping[str, str] | None,
    propositions: Iterable[Mapping[str, Any]], decisions: Iterable[Mapping[str, Any]], origine: str,
) -> Preparation:
    """Les propositions à écrire pour ce chantier (les cinq plateformes, dans l'ordre), et le compte rendu.

    Suppose `verifier_chantier` déjà passé : ne revérifie ni le consentement ni le retrait. `textes` : le texte
    que le modèle a rédigé, par plateforme ; les autres plateformes prennent le gabarit du code. Tout texte,
    d'où qu'il vienne, passe `controle_texte` ; un texte refusé n'écrit rien et le refus nomme ses règles."""
    textes = textes or {}
    propositions = list(propositions)
    decisions = list(decisions)
    matiere, avertissements = matiere_du_chantier(charge, profil, nature)
    courantes = {p["plateforme"]: p for p in registre.dernieres_revisions(propositions, charge["wct_id"])}
    nouvelles: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for plateforme in plateformes.PLATEFORMES:
        courante = courantes.get(plateforme.code)
        revision = 1
        if courante is not None:
            statut_courant = registre.statut(courante, decisions, ())
            if statut_courant != registre.STATUT_REJETE:
                items.append(_item_existant(courante, statut_courant))
                continue
            if plateforme.code not in textes:
                items.append({
                    "plateforme": plateforme.code, "statut": ITEM_TEXTE_REQUIS, "contenu_id": courante["contenu_id"],
                    "motif": "rejeté par le propriétaire : fournis un nouveau texte (textes) qui corrige ce qu'il a "
                             "reproché",
                })
                continue
            revision = courante["revision"] + 1
        if plateforme.code in textes:
            texte, origine_texte = textes[plateforme.code].strip(), "modele"
        else:
            texte, origine_texte = gabarits.composer(plateforme.code, matiere), "gabarit"
        violations = controler_texte(texte, contexte_controle(charge, profil, plateforme.longueur_max))
        if violations:
            items.append({
                "plateforme": plateforme.code, "statut": ITEM_REFUSE, "origine_texte": origine_texte,
                "regles": [v.en_dict() for v in violations],
            })
            continue
        proposition = _proposition(
            charge, plateforme, revision, texte, origine_texte, nature, matiere, profil, avertissements, origine,
        )
        nouvelles.append(proposition)
        items.append({
            "plateforme": plateforme.code, "statut": ITEM_PROPOSE, "contenu_id": proposition["contenu_id"],
            "revision": revision, "origine_texte": origine_texte, "apercu": _apercu(texte),
            "avertissements": proposition["avertissements"],
        })
    return Preparation(_statut_global(items), tuple(nouvelles), tuple(items))


def _statut_global(items: list[dict[str, Any]]) -> str:
    statuts = {item["statut"] for item in items}
    bloques = statuts & {ITEM_REFUSE, ITEM_TEXTE_REQUIS}
    if bloques and statuts - bloques:
        return STATUT_PARTIEL
    if bloques:
        return STATUT_TEXTES_REFUSES
    return STATUT_PROPOSE if ITEM_PROPOSE in statuts else STATUT_DEJA_PROPOSE


def verdict_texte_non_conforme(regles: Iterable[str]) -> dict[str, Any]:
    return verdicts.verdict(verdicts.REJ_TEXTE_NON_CONFORME, f"règles violées : {', '.join(regles)}")
