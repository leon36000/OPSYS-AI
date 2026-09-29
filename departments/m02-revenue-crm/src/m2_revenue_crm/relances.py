"""Relances dues, avec consentement et fréquence limitée (PLAN T4.9 ; DEFINITION-PRODUIT §7 M2.7 « relances » et M2.13,
règles dures « pas de spam, pas d'agressivité, opt-in respecté, fréquence limitée, validation humaine au départ », §9.4
« relances autorisées »).

Module PUR : aucune entrée-sortie, aucune horloge, aucun aléa. L'instant de référence (`maintenant`), la configuration,
les faits de M3, les consentements et l'historique des relances viennent de l'appelant (`outils.py`, seul à lire le
registre, `department.yaml` et l'identité). Une même entrée donne toujours la même sortie.

CE QUE C'EST. Une relance est DUE quand un segment de T4.6 (`segments.py`) s'applique à un lead ouvert : la règle de
relance cite ce segment et la donnée qui le déclenche. Deux règles, les seules dont M2 tient déjà les faits :
  - `relance_devis_sans_reponse` (segment `quote_stale`) : un devis envoyé est resté sans réponse. Le point de départ
    est l'envoi publié par M3 (`m3.devis_envoye`, `horodatage_envoi`), jamais une date supposée ;
  - `relance_lead_dormant` (segment `dormant_lead`) : un lead ouvert n'a eu aucune activité humaine depuis le délai.
Les autres relances de M2.7 (ancien client, avis, référence, saisonnier) ne sont pas ici : leur donnée n'atteint pas M2
(`referral_candidate`, `seasonal_opportunity` sont « non calculables »), ou la demande d'avis relève de M7 et d'un
consentement distinct (T1.5-d).

LE PRÉCÉDENT DE M3 EST HONNÊTE, ET M2 LE DIT. `m3.devis_envoye` date l'APPROBATION de l'envoi par le propriétaire, pas
la livraison au client : l'envoi réel passe par M1 (T2.1-c, N4, humain) et n'existe pas encore. Le délai part donc de
cet instant, et chaque relance de devis porte `depart.remarque` et un avertissement qui le disent. Quand l'envoi réel
publiera son heure, c'est elle qui fera foi.

DÉLAIS ET FRÉQUENCE : LA CONFIGURATION DE L'ENTREPRISE, JAMAIS UN DÉFAUT INVENTÉ. Le délai de chaque règle est le seuil
de son segment (`configuration.segments` de `department.yaml`, T4.6 : `jours_soumission_perimee`,
`jours_inactivite_dormant`) ; la fréquence maximale est `jours_entre_relances` de `configuration.relances` : le nombre
minimal de jours entre deux relances d'une même PERSONNE (les leads d'un même client comptent ensemble,
`consentements.perimetre`). Ces valeurs sont VIDES à dessein : sans elles, le verdict dit « à configurer »
(`REJ-RELANCES-A-CONFIGURER`, ou « non calculable, seuil à configurer » pour un délai), jamais une valeur devinée.
Décidées par Nathan (GATE NATHAN).

DERNIÈRE RELANCE ET PROCHAINE DATE PERMISE. La dernière relance est la dernière relance PRÉPARÉE pour la personne
(`relances_preparees`) : aucun envoi n'existe encore, c'est donc le seul fait daté que M2 tient (quand l'envoi réel
existera, son heure fera foi). La prochaine date permise est cette heure plus `jours_entre_relances` jours ; jamais
relancé : aucune contrainte. Pile à cet instant, la relance est permise.

CONSENTEMENT. Chaque relance dit par quels canaux elle peut se faire : l'appel toujours ; `sms` et `courriel` seulement
avec un consentement ACTIF de la personne pour ce canal (`consentements.canaux_permis`). Sans consentement actif,
la relance est « appel seulement », jamais un message. Un retrait (STOP) prime sur tout consentement et ne se lève pas.

Ce module ne propose rien de plus qu'une relance à PRÉPARER : le texte est un gabarit FIXE (`gabarits_relance.py`), rien
n'est envoyé, aucune sortie réseau. L'envoi est une décision humaine (T2.1-c, N4).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

from . import consentements, gabarits_relance, segments, verdicts
from . import horodatage as _horodatage

__all__ = [
    "AVERTISSEMENT_ENVOI_APPROUVE",
    "CHEMIN_CONFIGURATION",
    "CLE_JOURS_ENTRE_RELANCES",
    "LIMITE_DEFAUT",
    "LIMITE_MAX",
    "MODE_APPEL_OU_MESSAGE",
    "MODE_APPEL_SEULEMENT",
    "ORDRE_RELANCES",
    "ORIGINE_DEVIS_ENVOYE",
    "ORIGINE_DEVIS_SANS_REPONSE",
    "REGLES",
    "REGLE_DEVIS",
    "REGLE_DORMANT",
    "STATUTS_A_RELANCER",
    "TYPE_ENTREE",
    "calculer",
    "devis_connus",
    "lire_configuration",
    "lister",
    "preparer",
    "valider_demande",
    "verifier_configuration",
]

REGLE_DEVIS = "relance_devis_sans_reponse"
REGLE_DORMANT = "relance_lead_dormant"

# Énoncés des règles : ce que la réponse de `m2_lister_relances` cite (`regles`).
REGLES = {
    REGLE_DEVIS: (
        "Devis envoyé resté sans réponse depuis au moins jours_soumission_perimee jours (configuration.segments), à "
        "compter de l'envoi approuvé par le propriétaire (m3.devis_envoye) : relancer le client au sujet de la "
        "soumission. Segment quote_stale (M2.11)."
    ),
    REGLE_DORMANT: (
        "Lead ouvert sans activité humaine depuis au moins jours_inactivite_dormant jours (configuration.segments) : "
        "reprendre contact pour savoir si le projet est toujours d'actualité. Segment dormant_lead (M2.11)."
    ),
}
_SEGMENT_DE_REGLE = {REGLE_DEVIS: "quote_stale", REGLE_DORMANT: "dormant_lead"}

# Les deux règles portent sur un lead OUVERT : `segments.py` n'applique `quote_stale` qu'à un lead qualifié et
# `dormant_lead` qu'à un lead nouveau ou qualifié. Un lead converti, en chantier, facturé ou perdu n'est pas à relancer
# ici.
STATUTS_A_RELANCER = ("nouveau", "qualifie")

TYPE_ENTREE = "relance_preparee"

CLE_JOURS_ENTRE_RELANCES = "jours_entre_relances"
CHEMIN_CONFIGURATION = "configuration.relances"

ORIGINE_DEVIS_ENVOYE = "m3.devis_envoye"
ORIGINE_DEVIS_SANS_REPONSE = "m3.devis_sans_reponse"

MODE_APPEL_SEULEMENT = "appel_seulement"
MODE_APPEL_OU_MESSAGE = "appel_ou_message"

AVERTISSEMENT_ENVOI_APPROUVE = (
    "Le devis est « envoyé » au sens de M3 : l'envoi est approuvé par le propriétaire, mais la livraison au client "
    "(T2.1-c) n'est pas enregistrée. Vérifie que le client l'a bien reçu avant de le relancer."
)

LIMITE_DEFAUT = 10
LIMITE_MAX = 30
ORDRE_RELANCES = (
    "échéance croissante (la plus ancienne d'abord, instants comparés en UTC), puis lead_id, puis règle"
)


# ---------------------------------------------------------------------------------------------------------
# Configuration : la fréquence maximale, jamais un défaut
# ---------------------------------------------------------------------------------------------------------
def _entier_de_jours_valide(valeur: Any) -> bool:
    """Un nombre entier de jours, au moins 1. Un booléen n'est pas un nombre de jours."""
    return isinstance(valeur, int) and not isinstance(valeur, bool) and valeur >= 1


def lire_configuration(brut: Any) -> dict[str, dict[str, Any]]:
    """`configuration.relances` : `{"jours_entre_relances": {"etat", "valeur"}}`.

    `etat` : `ok` (entier ≥ 1, `valeur` le porte), `a_configurer` (clé absente ou nulle : le bloc est vide à dessein) ou
    `invalide` (tout le reste, dont un bloc qui n'est pas un dictionnaire). `valeur` est `None` hors `ok` : jamais un
    défaut. Une clé inconnue est ignorée."""
    bloc_illisible = brut is not None and not isinstance(brut, dict)
    valeur = brut.get(CLE_JOURS_ENTRE_RELANCES) if isinstance(brut, dict) else None
    if bloc_illisible:
        etat = segments.ETAT_SEUIL_INVALIDE
    elif valeur is None:
        etat = segments.ETAT_SEUIL_A_CONFIGURER
    elif _entier_de_jours_valide(valeur):
        etat = segments.ETAT_SEUIL_OK
    else:
        etat = segments.ETAT_SEUIL_INVALIDE
    return {CLE_JOURS_ENTRE_RELANCES: {"etat": etat, "valeur": valeur if etat == segments.ETAT_SEUIL_OK else None}}


def verifier_configuration(configuration: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    """Un verdict `REJ-RELANCES-A-CONFIGURER` qui dit quoi configurer, ou `None` si la fréquence maximale est valide."""
    etat = configuration.get(CLE_JOURS_ENTRE_RELANCES, {}).get("etat", segments.ETAT_SEUIL_A_CONFIGURER)
    if etat == segments.ETAT_SEUIL_OK:
        return None
    if etat == segments.ETAT_SEUIL_INVALIDE:
        detail = (
            f"{CLE_JOURS_ENTRE_RELANCES} invalide : un entier de jours supérieur ou égal à 1 est attendu "
            f"({CHEMIN_CONFIGURATION} de department.yaml)"
        )
    else:
        detail = (
            f"fréquence maximale à configurer : {CLE_JOURS_ENTRE_RELANCES}, le nombre minimal de jours entre deux "
            f"relances d'un même client ({CHEMIN_CONFIGURATION} de department.yaml, entier ≥ 1). Aucune valeur n'est "
            "supposée : c'est une décision du propriétaire."
        )
    return verdicts.construire_verdict("REJ-RELANCES-A-CONFIGURER", detail=detail)


# ---------------------------------------------------------------------------------------------------------
# Les devis envoyés : l'envoi RÉEL publié par M3, avant le constat de M3
# ---------------------------------------------------------------------------------------------------------
def devis_connus(
    faits_sans_reponse: Iterable[Mapping[str, Any]], faits_envoyes: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Les devis envoyés que M2 connaît, UN par `devis_id`, dans la forme des faits `m3.devis_sans_reponse` que lit
    `segments.py` (`statut_devis`, `horodatage_devis`), plus `origine`.

    L'envoi publié par M3 (`m3.devis_envoye`, `horodatage_envoi`) l'emporte sur le constat de M3
    (`m3.devis_sans_reponse`) : un devis d'abord signalé « brouillon » n'est pas signalé de nouveau une fois envoyé (M3
    publie un fait par devis, sous un identifiant déterministe), et le constat ne date que « le dernier état connu ».
    Sans l'envoi, le constat reste tel quel. L'ordre est celui de la première apparition : déterministe."""
    par_devis: dict[Any, dict[str, Any]] = {}
    for fait in faits_sans_reponse:
        par_devis[fait.get("devis_id")] = {**fait, "origine": ORIGINE_DEVIS_SANS_REPONSE}
    for fait in faits_envoyes:
        par_devis[fait.get("devis_id")] = {
            "devis_id": fait.get("devis_id"),
            "lead_id": fait.get("lead_id"),
            "statut_devis": "envoye",
            "horodatage_devis": fait.get("horodatage_envoi"),
            "origine": ORIGINE_DEVIS_ENVOYE,
        }
    return list(par_devis.values())


# ---------------------------------------------------------------------------------------------------------
# Le calcul : les relances dues, leur règle, leur dernière relance, leur prochaine date permise
# ---------------------------------------------------------------------------------------------------------
def _depart(regle: str, donnee: Mapping[str, Any], devis_par_id: Mapping[Any, Mapping[str, Any]]) -> dict[str, Any]:
    """D'où part le délai : le fait et son instant (jamais une date supposée)."""
    if regle == REGLE_DEVIS:
        origine = devis_par_id.get(donnee["devis_id"], {}).get("origine")
        depart: dict[str, Any] = {"fait": origine, "instant": donnee["horodatage_devis"]}
        if origine == ORIGINE_DEVIS_ENVOYE:
            depart["remarque"] = (
                "instant de l'approbation de l'envoi par le propriétaire, pas de la livraison au client (T2.1-c)"
            )
        return depart
    return {"fait": "derniere_activite_humaine", "instant": donnee["derniere_activite"]}


def _echeance(regle: str, donnee: Mapping[str, Any]) -> Any:
    """L'instant (UTC) où la relance est devenue due : le départ du délai plus le seuil du segment."""
    depart = donnee["horodatage_devis"] if regle == REGLE_DEVIS else donnee["derniere_activite"]
    return segments.instant_utc(depart) + timedelta(days=donnee["seuil_jours"])


def _derniere_relance(preparees: Iterable[Mapping[str, Any]], leads_de_la_personne: frozenset[str]) -> Any:
    """`(instant, maillon)` de la dernière relance préparée pour la personne, ou `None`. À instant égal, la dernière
    écrite. Seuls `le` et `canal` en sortent : ni le lead ni la règle d'un autre dossier du même client."""
    derniere = None
    for maillon in preparees:
        if maillon.get("lead_id") not in leads_de_la_personne:
            continue
        instant = segments.instant_utc(maillon["prepare_le"])
        if derniere is None or instant >= derniere[0]:
            derniere = (instant, maillon)
    return derniere


def _item(
    evaluation_du_lead: Mapping[str, Any],
    regle: str,
    segment_applique: Mapping[str, Any],
    *,
    instant: Any,
    jours_entre: int,
    leads_de_la_personne: frozenset[str],
    devis_par_id: Mapping[Any, Mapping[str, Any]],
    consentements_contact: list[Mapping[str, Any]],
    retraits: list[Mapping[str, Any]],
    preparees: list[Mapping[str, Any]],
) -> dict[str, Any]:
    donnee = segment_applique["donnee"]
    derniere = _derniere_relance(preparees, leads_de_la_personne)
    if derniere is None:
        derniere_relance, prochaine, permise = None, None, True
    else:
        prochaine_instant = derniere[0] + timedelta(days=jours_entre)
        derniere_relance = {"le": derniere[1]["prepare_le"], "canal": derniere[1]["canal"]}
        prochaine, permise = prochaine_instant.isoformat(), instant >= prochaine_instant
    canaux, etats = consentements.canaux_permis(leads_de_la_personne, consentements_contact, retraits)
    return {
        "lead_id": evaluation_du_lead["lead_id"],
        "statut": evaluation_du_lead["statut"],
        "proprietaire": evaluation_du_lead["proprietaire"],
        "regle": regle,
        "segment": dict(segment_applique),
        "depart": _depart(regle, donnee, devis_par_id),
        "due_depuis": _echeance(regle, donnee).isoformat(),
        "derniere_relance": derniere_relance,
        "prochaine_date_permise": prochaine,
        "permise_maintenant": permise,
        "mode": MODE_APPEL_SEULEMENT if canaux == [consentements.CANAL_APPEL] else MODE_APPEL_OU_MESSAGE,
        "canaux_permis": canaux,
        "consentements": etats,
    }


def calculer(
    evaluation: Mapping[str, Any],
    *,
    maintenant: str,
    configuration: Mapping[str, Mapping[str, Any]],
    devis: Iterable[Mapping[str, Any]] | None,
    consentements_contact: Iterable[Mapping[str, Any]],
    retraits: Iterable[Mapping[str, Any]],
    preparees: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Les relances dues des leads évalués : `{"relances", "indetermines", "regles_non_calculables", ...}`.

    `evaluation` : ce que rend `liste_leads.evaluer` (`leads` : chacun avec ses `segments` appliqués et ses
    `non_calculables`, `non_calculables_globaux`, `opportunites_par_client`). `configuration` : `lire_configuration`,
    DÉJÀ vérifiée (`verifier_configuration`). `devis` : `devis_connus` (`None` : illisibles). `maintenant` : ISO-8601
    avec fuseau, fourni par l'appelant.

    Une règle dont le délai est « non calculable » pour tous les leads (seuil à configurer, devis illisibles) ne rend
    AUCUNE relance et figure dans `regles_non_calculables` avec ce qui manque : une liste vide se lirait « aucune
    relance due ». `indetermines` compte les leads dont un segment n'a pas pu être calculé faute d'une donnée de CE
    lead.

    Ordre : `ORDRE_RELANCES`, total et stable."""
    jours_entre = configuration[CLE_JOURS_ENTRE_RELANCES]["valeur"]
    instant = segments.instant_utc(maintenant)
    globaux = {n["segment"]: n["manque"] for n in evaluation["non_calculables_globaux"]}
    regles_non_calculables = [
        {"regle": regle, "segment": segment, "manque": globaux[segment]}
        for regle, segment in _SEGMENT_DE_REGLE.items() if segment in globaux
    ]
    devis_par_id = {fait.get("devis_id"): fait for fait in devis or ()}
    consentements_contact, retraits, preparees = list(consentements_contact), list(retraits), list(preparees)
    client_de_lead = {lead["lead_id"]: lead["client_id"] for lead in evaluation["leads"]}
    opportunites = evaluation["opportunites_par_client"]
    items: list[dict[str, Any]] = []
    indetermines = 0
    for lead in evaluation["leads"]:
        personne = consentements.perimetre(lead["lead_id"], client_de_lead, opportunites)
        for regle, segment in _SEGMENT_DE_REGLE.items():
            if segment in globaux:
                continue
            applique = next((s for s in lead["segments"] if s["segment"] == segment), None)
            if applique is None:
                if any(n["segment"] == segment for n in lead["non_calculables"]):
                    indetermines += 1
                continue
            items.append(_item(
                lead, regle, applique, instant=instant, jours_entre=jours_entre, leads_de_la_personne=personne,
                devis_par_id=devis_par_id, consentements_contact=consentements_contact, retraits=retraits,
                preparees=preparees,
            ))
    items.sort(key=lambda i: (segments.instant_utc(i["due_depuis"]), i["lead_id"], i["regle"]))
    return {
        "relances": items,
        "indetermines": indetermines,
        "regles_non_calculables": regles_non_calculables,
        "jours_entre_relances": jours_entre,
    }


# ---------------------------------------------------------------------------------------------------------
# La liste, page par page
# ---------------------------------------------------------------------------------------------------------
def valider_demande(
    regle: Any, permises_seulement: Any, decalage: Any, limite: Any, maintenant: Any,
) -> dict[str, Any] | None:
    """Un verdict si un argument de la liste est invalide, sinon `None`."""
    if regle is not None and regle not in REGLES:
        return verdicts.construire_verdict(
            "REJ-ENUM-INVALIDE", detail=f"regle {regle!r} hors de la liste {list(REGLES)}")
    if not isinstance(permises_seulement, bool):
        return verdicts.construire_verdict(
            "REJ-ENUM-INVALIDE", detail="permises_seulement : un booléen est attendu")
    if isinstance(decalage, bool) or not isinstance(decalage, int) or decalage < 0:
        return verdicts.construire_verdict(
            "REJ-PAGINATION-INVALIDE", detail="decalage : un entier supérieur ou égal à 0 est attendu")
    if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= LIMITE_MAX:
        return verdicts.construire_verdict(
            "REJ-PAGINATION-INVALIDE", detail=f"limite : un entier de 1 à {LIMITE_MAX} est attendu")
    try:
        _horodatage.valider_horodatage(maintenant)
    except ValueError:
        return verdicts.construire_verdict(
            "REJ-HORODATAGE-INVALIDE", detail="horodatage : ISO-8601 avec fuseau attendu")
    return None


def _taille(objet: Any) -> int:
    """Taille sérialisée EXACTE telle que `Capacites._tronquer` la mesure (`json.dumps` sans échappement ASCII)."""
    return len(json.dumps(objet, ensure_ascii=False))


def lister(
    calcul: Mapping[str, Any],
    *,
    regle: str | None = None,
    permises_seulement: bool = False,
    decalage: int = 0,
    limite: int = LIMITE_DEFAUT,
    budget_caracteres: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Une page des relances calculées, `(page, None)` ou `(None, verdict)`.

    Filtres : `regle` (une des `REGLES`) et `permises_seulement` (seulement celles qu'on peut préparer maintenant). Une
    règle non calculable (seuil à configurer) est REFUSÉE avec ce qui manque, `REJ-SEGMENT-NON-CALCULABLE` : une liste
    vide se lirait « aucune relance due ». La page tient dans `budget_caracteres` (taille sérialisée mesurée par le
    code, jamais estimée) et dans `limite` relances, avec toujours une relance au moins ; `suivant` est le décalage à
    demander ensuite (`None` à la fin), `reste` compte ce qui vient APRÈS la page. Un décalage au-delà de la fin rend
    une page vide.

    La page porte `regles` (l'énoncé des règles citées), `regles_des_segments` (celui des segments), et ce qui manque
    pour calculer une règle (`regles_non_calculables`)."""
    if regle is not None:
        manque = next((n["manque"] for n in calcul["regles_non_calculables"] if n["regle"] == regle), None)
        if manque is not None:
            return None, verdicts.construire_verdict(
                "REJ-SEGMENT-NON-CALCULABLE", detail=f"règle {regle} : {manque}")
    retenues = [
        i for i in calcul["relances"]
        if (regle is None or i["regle"] == regle) and (not permises_seulement or i["permise_maintenant"])
    ]
    total = len(retenues)
    fenetre = retenues[decalage: decalage + limite]

    def page(nombre: int) -> dict[str, Any]:
        affichees = fenetre[:nombre]
        apres = min(total, decalage + nombre)
        reste = total - apres
        return {
            "ordre": ORDRE_RELANCES,
            "filtre": {"regle": regle, "permises_seulement": permises_seulement},
            "jours_entre_relances": calcul["jours_entre_relances"],
            "total": total,
            "decalage": decalage,
            "affichees": nombre,
            "reste": reste,
            "suivant": apres if reste else None,
            "message": (
                None if not reste else
                (f"{reste} autres relances non affichées : poursuivre avec decalage={apres}." if reste > 1
                 else f"1 autre relance non affichée : poursuivre avec decalage={apres}.")
            ),
            "indetermines": calcul["indetermines"],
            "relances": affichees,
            "regles": {r: REGLES[r] for r in sorted({i["regle"] for i in affichees})},
            "regles_des_segments": {
                r: segments.REGLES[r] for r in sorted({i["segment"]["regle"] for i in affichees})
            },
            "regles_non_calculables": calcul["regles_non_calculables"],
        }

    nombre = 0
    while nombre < len(fenetre) and _taille(page(nombre + 1)) <= budget_caracteres:
        nombre += 1
    if fenetre and nombre == 0:
        nombre = 1
    return page(nombre), None


# ---------------------------------------------------------------------------------------------------------
# Préparer une relance : un texte FIXE, rien d'envoyé
# ---------------------------------------------------------------------------------------------------------
def _refus(code: str, detail: str) -> tuple[None, dict[str, Any]]:
    return None, verdicts.construire_verdict(code, detail=detail)


def preparer(
    calcul: Mapping[str, Any],
    *,
    lead_id: str,
    client_id: str | None,
    regle: Any,
    canal: Any,
    maintenant: str,
    prepare_par: str,
    voie: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`({"entree", "resultat"}, None)` ou `(None, verdict)` : ce que `m2_preparer_relance` écrit et rend.

    `calcul` : `calculer(...)` pour CE lead. Les contrôles se font dans cet ordre, tous AVANT la moindre écriture (c'est
    l'adaptateur qui écrit `entree`) : la règle et le canal existent ; la règle est calculable ; la relance est due pour
    ce lead (`REJ-RELANCE-NON-DUE`) ; la fréquence la permet (`REJ-RELANCE-TROP-PROCHE`, avec la prochaine date permise)
    ; le canal est permis (`REJ-CONSENTEMENT-RETIRE` ou `REJ-CONSENTEMENT-ABSENT` pour un message sans consentement
    actif). Un seul verdict, le premier.

    Le texte est le gabarit FIXE de (règle, canal) : rien n'y est composé. Le résultat dit `envoye: False` : rien n'est
    envoyé, l'envoi réel est une décision humaine (T2.1-c, N4). `prepare_par` et `voie` sont déjà établis (jamais lus
    d'un argument d'outil)."""
    if regle not in REGLES:
        return _refus("REJ-ENUM-INVALIDE", f"regle {regle!r} hors de la liste {list(REGLES)}")
    if canal not in consentements.CANAUX_RELANCE:
        return _refus("REJ-ENUM-INVALIDE", f"canal {canal!r} hors de la liste {list(consentements.CANAUX_RELANCE)}")
    manque = next((n["manque"] for n in calcul["regles_non_calculables"] if n["regle"] == regle), None)
    if manque is not None:
        return _refus("REJ-SEGMENT-NON-CALCULABLE", f"règle {regle} : {manque}")
    item = next((i for i in calcul["relances"] if i["lead_id"] == lead_id and i["regle"] == regle), None)
    if item is None:
        return _refus(
            "REJ-RELANCE-NON-DUE",
            f"aucune relance « {regle} » n'est due pour ce lead à cet instant : le segment {_SEGMENT_DE_REGLE[regle]} "
            "ne s'applique pas (statut, délai ou activité). Liste les relances dues avec m2_lister_relances.",
        )
    if not item["permise_maintenant"]:
        derniere = item["derniere_relance"]
        return _refus(
            "REJ-RELANCE-TROP-PROCHE",
            f"fréquence limitée : le client a déjà été relancé le {derniere['le']} (canal {derniere['canal']}) ; "
            f"prochaine date permise : {item['prochaine_date_permise']} "
            f"(au plus une relance tous les {calcul['jours_entre_relances']} jours).",
        )
    if canal not in item["canaux_permis"]:
        etat = item["consentements"][canal]
        if etat["etat"] == consentements.ETAT_RETIRE:
            return _refus(
                "REJ-CONSENTEMENT-RETIRE",
                f"le client s'est retiré (STOP, {etat['retire_le']}) : aucun message. Relance par appel seulement.",
            )
        return _refus(
            "REJ-CONSENTEMENT-ABSENT",
            f"aucun consentement actif pour {canal} : inscris-le avec m2_enregistrer_consentement_contact "
            "(énoncé versionné, preuve), ou relance par appel.",
        )
    modele = gabarits_relance.gabarit(regle, canal)
    if modele is None:
        raise RuntimeError(f"aucun gabarit de relance pour ({regle!r}, {canal!r}) : un gabarit par règle et par canal")
    prochaine = (segments.instant_utc(maintenant) + timedelta(days=calcul["jours_entre_relances"])).isoformat()
    identifiant = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(
        {"lead_id": lead_id, "regle": regle, "prepare_le": maintenant, "type": TYPE_ENTREE}, sort_keys=True)))
    avertissements = (
        [AVERTISSEMENT_ENVOI_APPROUVE] if item["depart"].get("fait") == ORIGINE_DEVIS_ENVOYE else []
    )
    entree = {
        "type_entree": TYPE_ENTREE,
        "relance_id": identifiant,
        "lead_id": lead_id,
        "client_id": client_id,
        "regle": regle,
        "segment": item["segment"]["segment"],
        "canal": canal,
        "gabarit": {"id": modele["id"], "version": modele["version"]},
        "texte": modele["texte"],
        "echeance": item["due_depuis"],
        "donnee": item["segment"]["donnee"],
        "prepare_le": maintenant,
        "prepare_par": prepare_par,
        "voie": voie,
    }
    resultat = {
        "relance_id": identifiant,
        "lead_id": lead_id,
        "regle": regle,
        "canal": canal,
        "nature": modele["nature"],
        "texte": modele["texte"],
        "gabarit": {"id": modele["id"], "version": modele["version"]},
        "envoye": False,
        "segment": item["segment"],
        "depart": item["depart"],
        "prepare_le": maintenant,
        "prochaine_date_permise": prochaine,
        "avertissements": avertissements,
        "a_faire": (
            "Rien n'est envoyé : l'envoi réel est une décision humaine (T2.1-c, N4). Après la relance, note le "
            "résultat au dossier avec m2_enregistrer_interaction."
        ),
    }
    return {"entree": entree, "resultat": resultat}, None
