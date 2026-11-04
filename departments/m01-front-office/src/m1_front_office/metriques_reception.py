"""M1-H : les métriques de réception, calculées sur le registre anti-perte, jamais par un modèle.

Le constat `m1_constater_reception` alimente M8 (et, par lui, la direction) avec des agrégats DÉTERMINISTES d'une
période : délai jusqu'à la première prise en charge humaine, appels manqués rappelés, leads par service et par ville,
hors zone, photos reçues. Aucune donnée personnelle : ni contact, ni texte, ni conversation, ni identifiant de lead.

**Une absence n'est pas un zéro.** Chaque métrique porte un ÉTAT :

- `CALCULEE` : la source existe pour la période et la valeur est un compte ou un ratio exact ;
- `NON_EVALUEE` : la source manque ou n'est pas tracée, et `valeur` est `null` (jamais 0). Le motif est un code fermé
  (`AUCUN_SIGNAL`, `AUCUN_APPEL_MANQUE`, `AUCUNE_PRISE_EN_CHARGE`, `HORS_ZONE_NON_TRACE`, `PHOTOS_NON_TRACEES`…).

**Ce que M1 ne trace pas encore, et ne prétend donc pas mesurer** :

- **hors zone** : la qualification ne conserve pas la ville refusée ; une demande hors zone n'est pas distinguée d'une
  demande sans ville. Le constat dit `NON_EVALUEE` au lieu d'un zéro trompeur ;
- **photos reçues** : M1 ne reçoit pas de pièces (M1-L non livré) ; il n'y a aucune source de « photo reçue » ;
- **raison de perte** : elle appartient à M2 (aucun champ dans M1). Le constat ne la fabrique pas.

Les seuils (objectif de délai, cible de rappel) ne sont pas ici : ce sont des réglages de direction (CFG-1). Le
constat ne compare donc rien à un objectif et n'invente aucun « bon » ou « mauvais » résultat.

Module pur : aucune horloge, aucune base, aucun réseau.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import transferts

CONSTAT = "m1.reception_constatee"
JOURS_DEFAUT = 7
JOURS_MAX = 92

CALCULEE = "CALCULEE"
NON_EVALUEE = "NON_EVALUEE"

MOTIF_AUCUN_SIGNAL = "AUCUN_SIGNAL"
MOTIF_AUCUN_TRANSFERT = "AUCUN_TRANSFERT"
MOTIF_AUCUNE_PRISE_EN_CHARGE = "AUCUNE_PRISE_EN_CHARGE"
MOTIF_AUCUN_APPEL_MANQUE = "AUCUN_APPEL_MANQUE"
MOTIF_HORS_ZONE_NON_TRACE = "HORS_ZONE_NON_TRACE"
MOTIF_PHOTOS_NON_TRACEES = "PHOTOS_NON_TRACEES"

STATUTS_APPEL_MANQUE = frozenset({"manque", "voicemail"})
SOURCES_DE_RAPPEL = frozenset({transferts.EVT_TENTATIVE_SANS_CONTACT})
_CENT = Decimal("0.01")


def periode_valide(jours: Any) -> bool:
    return isinstance(jours, int) and not isinstance(jours, bool) and 1 <= jours <= JOURS_MAX


def _jour(horodatage: Any) -> str | None:
    if not isinstance(horodatage, str) or len(horodatage) < 10:
        return None
    jour = horodatage[:10]
    try:
        dt.date.fromisoformat(jour)
    except ValueError:
        return None
    return jour


def _instant(horodatage: Any) -> dt.datetime | None:
    try:
        quand = dt.datetime.fromisoformat(horodatage)
    except (TypeError, ValueError, OverflowError):
        return None
    return quand.astimezone(dt.UTC) if quand.tzinfo is not None else None


def _dans(jour: str | None, debut: str, fin: str) -> bool:
    return jour is not None and debut <= jour <= fin


def _non_evaluee(motif: str, **extra: Any) -> dict[str, Any]:
    return {"statut": NON_EVALUEE, "motif": motif, **extra}


def _ratio(numerateur: int, denominateur: int) -> str:
    return str((Decimal(numerateur) * 100 / Decimal(denominateur)).quantize(_CENT, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------------------------------------------
# Les trois métriques calculables aujourd'hui
# ---------------------------------------------------------------------------------------------------------------


def _delai_premiere_prise_en_charge(
    lignes: Sequence[Mapping[str, Any]], debut: str, fin: str
) -> dict[str, Any]:
    """Le délai entre l'ouverture d'un transfert et la PREMIÈRE ligne humaine (`prise_en_charge` ou `clos`).

    Seuls les transferts ouverts dans la période sont mesurés. Un transfert encore sans ligne humaine n'entre pas
    dans la médiane (`en_attente`) : il n'a pas de délai, pas un délai de zéro.
    """
    par_transfert: dict[str, list[Mapping[str, Any]]] = {}
    for ligne in lignes:
        if ligne.get("type_entree") == "transfert":
            identifiant = ligne.get("transfert_id")
            if isinstance(identifiant, str):
                par_transfert.setdefault(identifiant, []).append(ligne)
    delais: list[int] = []
    en_attente = 0
    for etat in transferts.lire(lignes):
        ouverture = etat.ouverture
        if not _dans(_jour(ouverture.get("horodatage")), debut, fin):
            continue
        depart = _instant(ouverture.get("horodatage"))
        humaines = [
            _instant(m.get("horodatage"))
            for m in par_transfert.get(etat.identifiant, ())
            if m.get("evenement") in (transferts.EVT_PRISE_EN_CHARGE, transferts.EVT_CLOS)
        ]
        humaines = [h for h in humaines if h is not None]
        if depart is None or not humaines:
            en_attente += 1
            continue
        premier = min(humaines)
        if premier < depart:
            # Un registre incohérent n'est jamais converti en durée négative : le transfert reste « en attente ».
            en_attente += 1
            continue
        delais.append(int((premier - depart).total_seconds()))
    if not delais:
        return _non_evaluee(
            MOTIF_AUCUNE_PRISE_EN_CHARGE if par_transfert else MOTIF_AUCUN_TRANSFERT,
            median_s=None, max_s=None, echantillon=0, en_attente=en_attente,
        )
    tries = sorted(delais)
    milieu = len(tries) // 2
    median = tries[milieu] if len(tries) % 2 else (tries[milieu - 1] + tries[milieu]) // 2
    return {
        "statut": CALCULEE,
        "motif": None,
        "median_s": median,
        "max_s": max(tries),
        "echantillon": len(tries),
        "en_attente": en_attente,
    }


def _a_ete_rappele(
    lignes: Sequence[Mapping[str, Any]], etat: transferts.EtatTransfert | None
) -> bool:
    # Seules les actions placées entre l'ouverture et la première clôture canonique sont recevables.
    if etat is None:
        return False
    # lire conserve les objets-lignes du registre; leur identité repère sans ambiguïté les bornes dans son ordre.
    index_ouverture = next((i for i, ligne in enumerate(lignes) if ligne is etat.ouverture), None)
    if index_ouverture is None:
        return False
    index_cloture = (
        next((i for i, ligne in enumerate(lignes) if ligne is etat.cloture), None)
        if etat.cloture is not None else None
    )
    if etat.cloture is not None and index_cloture is None:
        return False
    for i, ligne in enumerate(lignes):
        if i <= index_ouverture or (index_cloture is not None and i >= index_cloture):
            continue
        if (
            ligne.get("type_entree") == "transfert"
            and ligne.get("transfert_id") == etat.identifiant
            and ligne.get("evenement") in SOURCES_DE_RAPPEL
        ):
            return True
    return etat.cloture is not None and etat.cloture.get("issue") == "contact_reussi"


def _appels_manques_rappeles(
    lignes: Sequence[Mapping[str, Any]], debut: str, fin: str
) -> dict[str, Any]:
    """Part des appels manqués importés dans la période qui ont reçu une tentative de rappel HUMAINE.

    La source est la ligne `appel_importe` (statut manque/voicemail) et la tâche de rappel qu'elle porte dans sa
    réponse ; « rappelé » exige une tentative (`tentative_sans_contact`) ou une clôture `contact_reussi`. Une simple
    `prise_en_charge` — quelqu'un a pris la tâche — ne prouve aucun appel : elle ne compte pas. Un appel sans tâche de
    rappel compte au dénominateur et pas au numérateur : il n'a pas été rappelé par M1, et le dire est plus juste que
    l'écarter.
    """
    appels = [
        ligne for ligne in lignes
        if ligne.get("type_entree") == "appel_importe"
        and ligne.get("statut") in STATUTS_APPEL_MANQUE
        and _dans(_jour(ligne.get("horodatage")), debut, fin)
    ]
    if not appels:
        return _non_evaluee(MOTIF_AUCUN_APPEL_MANQUE, valeur=None, numerateur=None, denominateur=None)
    rappeles = 0
    etats_par_id = {etat.identifiant: etat for etat in transferts.lire(lignes)}
    for ligne in appels:
        reponse = ligne.get("reponse")
        tache = reponse.get("tache_rappel") if isinstance(reponse, Mapping) else None
        transfert_id = tache.get("transfert_id") if isinstance(tache, Mapping) else None
        if isinstance(transfert_id, str) and _a_ete_rappele(lignes, etats_par_id.get(transfert_id)):
            rappeles += 1
    return {
        "statut": CALCULEE,
        "motif": None,
        "valeur": _ratio(rappeles, len(appels)),
        "numerateur": rappeles,
        "denominateur": len(appels),
    }


def _leads_par(
    lignes: Sequence[Mapping[str, Any]], debut: str, fin: str, cle: str
) -> dict[str, Any]:
    """Comptes de leads émis dans la période, groupés par `service` ou `ville`. Une période sans signal reçu n'est
    pas « zéro lead » : la source n'a rien à dire (`NON_EVALUEE`). Avec des signaux et aucun lead, le zéro est un vrai
    zéro (les règles n'ont rien qualifié)."""
    signaux = [x for x in lignes if x.get("type_entree") == "signal" and _dans(_jour(x.get("horodatage")), debut, fin)]
    if not signaux:
        return _non_evaluee(MOTIF_AUCUN_SIGNAL, comptes=None, total=None)
    comptes: dict[str, int] = {}
    total = 0
    for ligne in lignes:
        if ligne.get("type_entree") != "lead_emis" or not _dans(_jour(ligne.get("horodatage")), debut, fin):
            continue
        lead = ligne.get("lead")
        valeur = lead.get(cle) if isinstance(lead, Mapping) else None
        libelle = valeur if isinstance(valeur, str) and valeur else "non_renseigne"
        comptes[libelle] = comptes.get(libelle, 0) + 1
        total += 1
    return {"statut": CALCULEE, "motif": None, "comptes": dict(sorted(comptes.items())), "total": total}


def _empreinte(contenu: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(contenu, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------------------------------------------
# Le constat
# ---------------------------------------------------------------------------------------------------------------


def constater(lignes: Iterable[Mapping[str, Any]], *, date_reference: str, jours: int = JOURS_DEFAUT) -> dict[str, Any]:
    """Le constat `m1.reception_constatee` de la période, sans identifiant d'événement (l'adaptateur le pose)."""
    if not periode_valide(jours):
        raise ValueError(f"REJ-M1-RECEPTION-PERIODE: jours doit être un entier de 1 à {JOURS_MAX}")
    try:
        fin = dt.date.fromisoformat(date_reference)
    except (TypeError, ValueError):
        raise ValueError("REJ-M1-RECEPTION-DATE: date_reference doit être AAAA-MM-JJ") from None
    debut = (fin - dt.timedelta(days=jours - 1)).isoformat()
    fin_txt = fin.isoformat()
    lignes = list(lignes)
    contenu: dict[str, Any] = {
        "date_reference": fin_txt,
        "jours": jours,
        "periode": {"debut": debut, "fin": fin_txt},
        "delai_premiere_prise_en_charge_s": _delai_premiere_prise_en_charge(lignes, debut, fin_txt),
        "appels_manques_rappeles_pct": _appels_manques_rappeles(lignes, debut, fin_txt),
        "leads_par_service": _leads_par(lignes, debut, fin_txt, "service"),
        "leads_par_ville": _leads_par(lignes, debut, fin_txt, "ville"),
        "hors_zone": _non_evaluee(MOTIF_HORS_ZONE_NON_TRACE, valeur=None),
        "photos_recues_pct": _non_evaluee(MOTIF_PHOTOS_NON_TRACEES, valeur=None, numerateur=None, denominateur=None),
    }
    contenu["empreinte_contenu"] = _empreinte(contenu)
    return contenu
