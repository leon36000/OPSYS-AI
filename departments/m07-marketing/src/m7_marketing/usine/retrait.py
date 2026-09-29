"""Registre de retrait du consentement marketing (PLAN T4.17, Loi 25 ; reste de T4.3).

Un client qui a consenti à l'usage de son chantier en contenu public peut retirer ce consentement à tout moment.
Le retrait est un FAIT durable, écrit une fois, jamais effacé (registre append-only) : il bloque, pour ce
chantier, toute tâche de contenu — proposer, décider, exporter, préparer une photo — y compris un paquet déjà
proposé ou approuvé. Il ne se lève pas : un client qui consent de nouveau le fait par un nouveau « Terminer »
(un nouveau WCT), jamais par une écriture qui défait son retrait.

- Clé : le `wct_id` du chantier. Si le WCT est connu de M7, le `lead_id` est retenu aussi et le retrait vaut
  pour tout chantier du même lead : un client qui retire son consentement ne l'a pas retiré pour une seule
  intervention. Un `wct_id` encore inconnu est accepté (le WCT peut arriver après le retrait : il sera bloqué à
  sa réception), et la réponse le dit.
- Autre clé : le `lead_id` seul (`construire_retrait_de_lead`, PLAN T4.17-c). Un client qui écrit STOP à M1 se retire
  de tout : M1 le publie au bus (`m1.retrait_consentement`) avec les `lead_id` qu'il a ouverts pour lui, et M7 inscrit
  un retrait par lead, sans `wct_id` (le chantier n'existe peut-être pas encore). Le lien est le `lead_id`, que M1,
  M2, M4 et M7 connaissent tous : jamais un contact.
- Aucun texte libre : ni motif, ni nom, ni note — un retrait n'a pas à se justifier (Loi 25) et le registre ne
  doit pas devenir un second dossier de renseignements personnels. Le canal par lequel le client l'a dit, qui
  l'a écrit et quand suffisent.
- Le retrait ne défait rien de ce qui a déjà été publié à la main : M7 ne publie jamais, mais un paquet exporté
  a pu l'être. `contenus_deja_exportes` le dit, pour que la publication soit retirée à la main.

Module pur : aucune entrée-sortie, aucun import `opsys`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from . import verdicts

CANAUX_RETRAIT = ("telephone", "courriel", "sms", "en_personne", "application")

# Pour un client qui revient, M2 ouvre une opportunité `<lead d'origine>~opp~<wct_id>` (`m2_revenue_crm.outils`) : le
# WCT du chantier suivant peut porter cet identifiant. Le retrait d'un lead vaut pour toutes ses opportunités : sans
# cela, un STOP laisserait passer le contenu du deuxième chantier d'un client qui s'est retiré. M7 ne connaît que la
# FORME de l'identifiant (comme M10, `m10_memoire.etapes`), jamais M2.
SEPARATEUR_OPPORTUNITE = "~opp~"


def lead_d_origine(lead_id: str) -> str:
    """Le lead d'origine d'un identifiant de lead ou d'opportunité : `X~opp~w` et `X` donnent `X`."""
    return lead_id.split(SEPARATEUR_OPPORTUNITE, 1)[0]


def horodatage_valide(horodatage: Any) -> bool:
    """Un horodatage ISO 8601 avec fuseau : ce qu'un département accepte comme heure fournie."""
    if not isinstance(horodatage, str) or not horodatage:
        return False
    try:
        return datetime.fromisoformat(horodatage).tzinfo is not None
    except ValueError:
        return False


def construire_retrait(
    wct_id: Any, lead_id: str | None, canal: Any, enregistre_par: str, source: str, horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(retrait, None)` ou `(None, verdict)`. `enregistre_par` et `source` sont déjà établis par l'adaptateur
    (la personne du jeton d'appareil, ou « agent ») : jamais lus d'un argument d'outil."""
    if not isinstance(wct_id, str) or not wct_id.strip():
        return None, verdicts.verdict(
            verdicts.REJ_RETRAIT_INVALIDE, "wct_id : le chantier dont le client retire son consentement"
        )
    if canal not in CANAUX_RETRAIT:
        return None, verdicts.verdict(
            verdicts.REJ_RETRAIT_INVALIDE, f"canal : par où le client l'a dit ({', '.join(CANAUX_RETRAIT)})"
        )
    if not horodatage_valide(horodatage):
        return None, verdicts.verdict(verdicts.REJ_HORODATAGE_INVALIDE, "horodatage ISO 8601 avec fuseau requis")
    wct_id = wct_id.strip()
    canonique = json.dumps({"wct_id": wct_id, "type": "retrait_consentement_marketing"}, sort_keys=True)
    return {
        "retrait_id": str(uuid.uuid5(uuid.NAMESPACE_URL, canonique)),
        "wct_id": wct_id,
        "lead_id": lead_id,
        "canal": canal,
        "enregistre_par": enregistre_par,
        "source": source,
        "horodatage": horodatage,
    }, None


def construire_retrait_de_lead(
    lead_id: Any, canal: Any, enregistre_par: str, source: str, horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(retrait, None)` ou `(None, verdict)` : le retrait d'un LEAD (et non d'un chantier), tel que le bus le dit.

    Sans `wct_id` (`None`) : il bloque tout chantier de ce lead, celui qui existe et ceux qui viendront. Même
    identifiant déterministe pour le même lead : le rejouer n'ajoute rien. `enregistre_par` et `source` disent d'où
    vient le fait (le bus), jamais un argument d'outil."""
    if not isinstance(lead_id, str) or not lead_id.strip():
        return None, verdicts.verdict(verdicts.REJ_RETRAIT_INVALIDE, "lead_id : le lead dont le client se retire")
    if canal not in CANAUX_RETRAIT:
        return None, verdicts.verdict(
            verdicts.REJ_RETRAIT_INVALIDE, f"canal : par où le client l'a dit ({', '.join(CANAUX_RETRAIT)})"
        )
    if not horodatage_valide(horodatage):
        return None, verdicts.verdict(verdicts.REJ_HORODATAGE_INVALIDE, "horodatage ISO 8601 avec fuseau requis")
    lead_id = lead_id.strip()
    canonique = json.dumps({"lead_id": lead_id, "type": "retrait_consentement_marketing"}, sort_keys=True)
    return {
        "retrait_id": str(uuid.uuid5(uuid.NAMESPACE_URL, canonique)),
        "wct_id": None,
        "lead_id": lead_id,
        "canal": canal,
        "enregistre_par": enregistre_par,
        "source": source,
        "horodatage": horodatage,
    }, None


def retrait_applicable(
    wct_id: str | None, lead_id: str | None, retraits: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Le retrait qui bloque ce chantier : celui de son `wct_id`, ou celui d'un autre chantier du même lead (ou d'une
    opportunité du même lead d'origine : `lead_d_origine`)."""
    origine = lead_d_origine(lead_id) if lead_id else ""
    for retrait in retraits:
        if wct_id is not None and retrait.get("wct_id") == wct_id:
            return retrait
        autre = retrait.get("lead_id")
        if origine and autre and lead_d_origine(autre) == origine:
            return retrait
    return None
