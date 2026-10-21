"""Registre de consentement de contact : canal, énoncé versionné, preuve, retrait (PLAN T4.9 ; DEFINITION-PRODUIT §5 P8
« consentements documentés : SMS et courriel (opt-in) », §7 M2 « opt-in respecté », §9.4 « relances autorisées »).

Module PUR : aucune entrée-sortie, aucune horloge, aucun aléa. L'adaptateur (`outils.py`) lit et écrit le registre
durable `consentements_contact` et établit QUI enregistre (personne d'un jeton d'appareil confirmé en base, ou
approbateur d'une demande) ; ce module construit les maillons et dit, pour un client et un canal, si le consentement est
actif, absent ou retiré. Il cite `docs/compliance/politiques/POLITIQUE-consentement-sms.md` (§3 ce qui est collecté, §4
comment il est documenté et retiré) sans la valider : elle reste une PROPOSITION jusqu'à la validation de Nathan (T3).

Ce que le registre garde (POLITIQUE §3 et §4) : le canal, la version de l'énoncé lu par la personne, la source
(formulaire, appel, kiosque), la preuve (son type et une RÉFÉRENCE au document : jamais le document, jamais un numéro),
l'heure du consentement et celle de l'inscription, et qui l'a inscrit. **Jamais un numéro de téléphone ni un courriel**
: le contact reste au contrat du lead ; le registre ne porte que `lead_id` et `client_id` (une empreinte).

Deux faits, un seul registre, dans l'ordre d'écriture :
  - `consentement_contact` : une personne (vendeur ou admin) inscrit le consentement d'un client pour UN canal écrit
    (`sms` ou `courriel`), avec son énoncé versionné et sa preuve ;
  - `retrait_contact` : le client s'est retiré (STOP). M1 le publie sur le bus (`m1.retrait_consentement`) avec les
    `lead_id` qu'il a ouverts pour lui, jamais son numéro ; M2 le range tel quel, sans le contact.

UN RETRAIT NE SE LÈVE JAMAIS, dans ce module ni dans M2 : il prime sur tout consentement, quels que soient l'ordre ou
l'heure des deux (comme M1, `transferts.retire`, et M7, « il ne se lève pas »). Lever un retrait est une décision du
propriétaire, pas d'un outil. Un retrait vaut pour TOUS les canaux écrits (`sms` et `courriel`) : le client a dit qu'il
ne veut plus de messages ; c'est le choix prudent, dans `canaux_retires`, seul endroit à changer si Nathan tranche
autrement. L'appel n'est pas un canal soumis au consentement : `appel` est toujours permis (mission de T4.9 : « appel
seulement »).

Le consentement est celui d'une PERSONNE, pas d'un lead : `perimetre` réunit les leads du même client (Client 360) et le
lead visé ; un retrait ou un consentement inscrit sur l'un vaut pour tous. La résolution se fait à la lecture, jamais à
l'écriture : un STOP qui arrive avant que M2 ait rangé le lead d'un client s'applique dès que le lien existe.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from opsys import garde_fou_texte

from . import horodatage as _horodatage
from . import segments, verdicts

__all__ = [
    "CANAL_APPEL",
    "CANAUX_ECRITS",
    "CANAUX_RELANCE",
    "ETAT_ABSENT",
    "ETAT_ACTIF",
    "ETAT_RETIRE",
    "SOURCES_CONSENTEMENT",
    "SOURCE_BUS_RETRAIT",
    "TYPES_PREUVE",
    "TYPE_CONSENTEMENT",
    "TYPE_RETRAIT",
    "VOIES",
    "canaux_permis",
    "canaux_retires",
    "construire_consentement",
    "construire_retrait",
    "etat_du_canal",
    "perimetre",
]

TYPE_CONSENTEMENT = "consentement_contact"
TYPE_RETRAIT = "retrait_contact"

CANAL_APPEL = "appel"
CANAUX_ECRITS = ("sms", "courriel")
CANAUX_RELANCE = (CANAL_APPEL, *CANAUX_ECRITS)

# POLITIQUE-consentement-sms §4 : « source (formulaire, appel, kiosque) » ; §3 : « preuve du consentement (écran,
# formulaire, double opt-in selon le cas) » ; §4 : « formulaire électronique ou verbal documenté ».
SOURCES_CONSENTEMENT = ("formulaire", "appel", "kiosque")
TYPES_PREUVE = ("ecran", "formulaire", "double_opt_in", "verbal_documente")

VOIE_APPAREIL = "appareil"
VOIE_APPROBATION = "approbation"
VOIES = (VOIE_APPAREIL, VOIE_APPROBATION)

SOURCE_BUS_RETRAIT = "bus:m1.retrait_consentement"

ETAT_ACTIF = "actif"
ETAT_ABSENT = "absent"
ETAT_RETIRE = "retire"

# La version de l'énoncé lu par la personne : un identifiant de version, jamais du texte libre (même forme que
# `consentement_version_texte` de M4).
_FORME_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Une référence de preuve pointe vers un document (formulaire, note d'appel) : un identifiant compact, sans espace ni
# arobase. Le garde-fou partagé refuse en plus tout téléphone ou courriel qui s'y glisserait.
_FORME_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#-]{2,119}$")
_PROFIL_REFERENCE = garde_fou_texte.profil("m2_reference_preuve", (garde_fou_texte.COORDONNEES,))


def _invalide(detail: str) -> tuple[None, dict[str, Any]]:
    return None, verdicts.construire_verdict("REJ-CONSENTEMENT-INVALIDE", detail=detail)


def _non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and bool(valeur.strip())


def _identifiant(nature: str, **cles: Any) -> str:
    """Identifiant déterministe : le même fait donne le même identifiant, donc jamais deux maillons pour lui."""
    canonique = json.dumps({**cles, "type": nature}, sort_keys=True, ensure_ascii=True)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, canonique))


def canaux_retires(canal_du_retrait: str) -> tuple[str, ...]:
    """Les canaux qu'un retrait fait taire : TOUS les canaux écrits, quel que soit celui par lequel le client l'a dit
    (un STOP par SMS retire aussi le courriel). Seul endroit à changer si le propriétaire décide qu'un retrait ne vaut
    que pour son canal. Un canal inconnu ne retire rien : il n'est pas un canal écrit."""
    return CANAUX_ECRITS if canal_du_retrait in CANAUX_ECRITS else ()


def _reference_valide(reference: Any) -> bool:
    if not isinstance(reference, str) or not _FORME_REFERENCE.match(reference):
        return False
    return garde_fou_texte.premiere_violation(reference, _PROFIL_REFERENCE) is None


def construire_consentement(
    lead_id: Any,
    client_id: Any,
    canal: Any,
    enonce_version: Any,
    source: Any,
    preuve: Any,
    recueilli_le: Any,
    enregistre_le: Any,
    enregistre_par: Any,
    voie: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(maillon, None)` ou `(None, verdict)` : le consentement d'un client pour UN canal écrit.

    Rien n'est déduit ni complété : chaque champ est fourni et contrôlé, dans l'ordre. `enregistre_par` et `voie` sont
    DÉJÀ établis par l'adaptateur (la personne du jeton confirmé, ou l'approbateur), jamais lus d'un argument d'outil.
    `recueilli_le` (l'instant du consentement) ne peut pas suivre `enregistre_le` (l'instant de l'inscription) : on
    n'inscrit pas un consentement à venir."""
    if not _non_vide(lead_id):
        return _invalide("lead_id : le lead d'où le consentement est inscrit")
    if client_id is not None and not _non_vide(client_id):
        return _invalide("client_id : absent (None) ou l'identifiant du client")
    if canal not in CANAUX_ECRITS:
        return _invalide(f"canal : un canal écrit est attendu ({', '.join(CANAUX_ECRITS)}) ; l'appel n'en demande pas")
    if not isinstance(enonce_version, str) or not _FORME_VERSION.match(enonce_version):
        return _invalide(
            "enonce_version : l'identifiant de version de l'énoncé lu (lettres, chiffres, . _ -, 64 au plus)")
    if source not in SOURCES_CONSENTEMENT:
        return _invalide(f"source : comment le consentement a été recueilli ({', '.join(SOURCES_CONSENTEMENT)})")
    if not isinstance(preuve, Mapping) or set(preuve) != {"type", "reference"}:
        return _invalide("preuve : {type, reference} attendus, rien d'autre")
    if preuve["type"] not in TYPES_PREUVE:
        return _invalide(f"preuve.type : la nature de la preuve ({', '.join(TYPES_PREUVE)})")
    if not _reference_valide(preuve["reference"]):
        return _invalide(
            "preuve.reference : l'identifiant du document qui prouve le consentement (3 à 120 caractères, sans "
            "espace), jamais un numéro de téléphone ni un courriel"
        )
    for nom, valeur in (("recueilli_le", recueilli_le), ("enregistre_le", enregistre_le)):
        try:
            _horodatage.valider_horodatage(valeur)
        except ValueError:
            return None, verdicts.construire_verdict(
                "REJ-HORODATAGE-INVALIDE", detail=f"{nom} : ISO-8601 avec fuseau attendu")
    if segments.instant_utc(recueilli_le) > segments.instant_utc(enregistre_le):
        return _invalide("recueilli_le : le consentement ne peut pas être postérieur à son inscription")
    if not _non_vide(enregistre_par):
        return _invalide("enregistre_par : la personne qui inscrit le consentement")
    if voie not in VOIES:
        return _invalide(f"voie : {', '.join(VOIES)}")
    return {
        "type_entree": TYPE_CONSENTEMENT,
        "consentement_id": _identifiant(
            TYPE_CONSENTEMENT, lead_id=lead_id, canal=canal, enonce_version=enonce_version, recueilli_le=recueilli_le),
        "lead_id": lead_id,
        "client_id": client_id,
        "canal": canal,
        "enonce_version": enonce_version,
        "source": source,
        "preuve": {"type": preuve["type"], "reference": preuve["reference"]},
        "recueilli_le": recueilli_le,
        "enregistre_le": enregistre_le,
        "enregistre_par": enregistre_par.strip(),
        "voie": voie,
    }, None


def construire_retrait(
    lead_id: Any, canal: Any, signal_id: Any, horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(maillon, None)` ou `(None, verdict)` : le retrait d'un client (STOP), tel que le bus le dit.

    Quatre champs, aucun contact : le lead, le canal du core par lequel le client l'a écrit, l'identifiant du signal
    chez M1 (« canal:identifiant du message », jamais un numéro) et l'heure du STOP, fournie par la plateforme. Même
    STOP pour le même lead : même identifiant, donc jamais deux maillons. Un STOP illisible est REFUSÉ par l'appelant
    (le répartiteur réessaie, puis met en quarantaine, visible) : un retrait n'est jamais ignoré en silence."""
    if not _non_vide(lead_id):
        return _invalide("lead_id : le lead que le client a ouvert avant son retrait")
    if canal not in CANAUX_ECRITS:
        return _invalide(f"canal : le canal du retrait ({', '.join(CANAUX_ECRITS)})")
    if not _non_vide(signal_id):
        return _invalide("signal_id : l'identifiant du signal du retrait chez M1")
    try:
        _horodatage.valider_horodatage(horodatage)
    except ValueError:
        return None, verdicts.construire_verdict(
            "REJ-HORODATAGE-INVALIDE", detail="horodatage : ISO-8601 avec fuseau attendu (l'heure du retrait)")
    return {
        "type_entree": TYPE_RETRAIT,
        "retrait_id": _identifiant(TYPE_RETRAIT, lead_id=lead_id, signal_id=signal_id),
        "lead_id": lead_id,
        "canal": canal,
        "signal_id": signal_id,
        "horodatage": horodatage,
        "source": SOURCE_BUS_RETRAIT,
    }, None


def perimetre(
    lead_id: str, client_de_lead: Mapping[str, str | None], opportunites_par_client: Mapping[str, Iterable[str]],
) -> frozenset[str]:
    """Les leads de la PERSONNE : le lead lui-même et toutes les opportunités de son client (Client 360). Un lead sans
    client n'est que lui-même. Le lead visé en fait toujours partie, même si le lien est incomplet."""
    client = client_de_lead.get(lead_id)
    if client is None:
        return frozenset({lead_id})
    return frozenset({lead_id, *opportunites_par_client.get(client, ())})


def etat_du_canal(
    canal: str,
    leads_de_la_personne: frozenset[str],
    consentements: Iterable[Mapping[str, Any]],
    retraits: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """L'état du consentement de la personne pour ce canal : `retire`, `actif` ou `absent`, jamais un quatrième.

    Un retrait qui vise un des leads de la personne et un canal qu'il fait taire (`canaux_retires`) prime sur tout : le
    PREMIER (le plus ancien) date le retrait. Sinon, le consentement le plus récent (`recueilli_le`) de la personne pour
    ce canal est actif. Sinon, absent : aucun consentement inventé, aucun consentement déduit d'un autre canal ni de
    l'origine du lead (un SMS reçu n'est pas un opt-in, POLITIQUE-consentement-sms §4)."""
    retire = None
    for retrait in retraits:
        if retrait.get("lead_id") not in leads_de_la_personne or canal not in canaux_retires(retrait.get("canal")):
            continue
        if retire is None or segments.instant_utc(retrait["horodatage"]) < segments.instant_utc(retire["horodatage"]):
            retire = retrait
    if retire is not None:
        return {
            "etat": ETAT_RETIRE, "retire_le": retire["horodatage"], "source": retire["source"],
            "canal_du_retrait": retire["canal"],
        }
    actif = None
    for consentement in consentements:
        if consentement.get("lead_id") not in leads_de_la_personne or consentement.get("canal") != canal:
            continue
        if actif is None or segments.instant_utc(consentement["recueilli_le"]) >= segments.instant_utc(
            actif["recueilli_le"]
        ):
            actif = consentement
    if actif is not None:
        return {
            "etat": ETAT_ACTIF, "enonce_version": actif["enonce_version"], "source": actif["source"],
            "preuve_type": actif["preuve"]["type"], "recueilli_le": actif["recueilli_le"],
        }
    return {"etat": ETAT_ABSENT}


def canaux_permis(
    leads_de_la_personne: frozenset[str],
    consentements: Iterable[Mapping[str, Any]],
    retraits: Iterable[Mapping[str, Any]],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """`(canaux permis, état de chaque canal écrit)`. L'appel est toujours permis ; un canal écrit ne l'est qu'avec un
    consentement ACTIF. Sans consentement actif pour aucun canal écrit : `["appel"]` seulement."""
    consentements, retraits = list(consentements), list(retraits)
    etats = {
        canal: etat_du_canal(canal, leads_de_la_personne, consentements, retraits) for canal in CANAUX_ECRITS
    }
    permis = [CANAL_APPEL, *(canal for canal in CANAUX_ECRITS if etats[canal]["etat"] == ETAT_ACTIF)]
    return permis, etats
