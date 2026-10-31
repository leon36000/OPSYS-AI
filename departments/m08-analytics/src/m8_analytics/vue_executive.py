"""Vue exécutive de M8, pour le propriétaire (PLAN T4.19 ; DEFINITION-PRODUIT.md §7 M8.6 « tableau de bord exécutif
(simple, clair, actionnable) », §8 « pour la finance, M8 consomme M5 et ne recalcule pas », §9.5 profil admin).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge. ``outils.py``, seul point de contact avec le socle,
lit les faits et les attentes de M6, puis appelle ``assembler``. Quatre sections, chacune dit d'où vient son chiffre :

1. ``entonnoir`` — les métriques gouvernées de ``entonnoir.py`` (version de définition et propriétaire de chacune),
   les événements reçus et leur fraîcheur, les devis qui attendent, les seuils à configurer (GATE NATHAN) ;
2. ``marge_reelle`` — la marge de chaque chantier telle que M5 l'a publiée (``m5.rentabilite_chantier``), affichée
   seulement si le verdict est ``CALCULEE``, le coût complet et ``prix_definitif is True``. M8 reprend le montant
   sans un seul calcul : aucune somme, aucun arrondi, aucun écart. Facture brouillon ou finalité historique inconnue
   est exclue avec un motif ; les autres manques nomment les codes de M5 ;
3. ``stock_a_commander`` — les besoins de commande TELS QUE M6 les publie à la file du propriétaire (``attentes()``),
   avec son résumé et son action proposée : M8 n'a aucun stock, aucun seuil ni aucune quantité à lui ;
4. ``cash_libre`` — le DERNIER constat que M5 a publié (``m5.cash_libre_constate``), tel quel, avec son âge
   (``cash_libre.py``) ; « manque » si M5 n'en a publié aucun, et où le lire. M8 ne le recalcule jamais.

Une donnée absente donne un « manque » nommé (``manques``, une fois, dédoublonné), jamais un zéro ni une valeur par
défaut. La vue ne décide de rien et ne propose aucune action de son cru : M2 relance déjà les devis sans réponse, M6
propose sa commande ; M8 rapporte le chiffre (SOUL).

BORNE : la réponse d'un outil est tronquée par ``Capacites`` au-delà de la limite du socle. Chaque liste est
plafonnée, puis la vue entière est mesurée comme le socle la mesure : ce qui ne tient pas est retiré de la fin de la
plus longue liste et COMPTÉ (``reste``), jamais perdu en silence ni coupé au milieu. Quand il ne reste plus aucune
liste à raccourcir, la décomposition du cash libre est retirée à son tour (``cash_libre.reduire`` : comptée et dite) ;
les montants du constat, son statut, ce qui manque, ses réserves et sa mention ne sont jamais retirés.
"""

from __future__ import annotations

import json
from typing import Any

from . import cash_libre, entonnoir, mesures_chantier

_LIMITE_LISTE = 3
_TYPE_ATTENTE_BESOIN_COMMANDE = "besoin_commande"
_TYPE_ATTENTE_SEUIL_A_CONFIGURER = "seuil_a_configurer"
_PORTEE = (
    "Tous les faits reçus, sans fenêtre de période. M8 calcule l'entonnoir ; marge réelle, cash libre (M5) et stock à "
    "commander (M6) sont repris tels que publiés, sans recalcul."
)
_CONFIGURATION_SEUILS = "department.yaml de m08-analytics, configuration.seuils_entonnoir"


def _ajouter_manques(manques: list[dict[str, str]], nouveaux: list[dict[str, str]]) -> None:
    """Ajoute chaque manque UNE fois : « aucun devis accepté reçu » vaut pour trois métriques et ne se répète pas."""
    for manque in nouveaux:
        if manque not in manques:
            manques.append(dict(manque))


# ---------------------------------------------------------------------------
# 1. L'entonnoir
# ---------------------------------------------------------------------------
def _ligne_mesure(mesure: dict[str, Any]) -> dict[str, Any]:
    ligne: dict[str, Any] = {
        "metric_id": mesure["metric_id"], "nom": mesure["nom"], "valeur": mesure["valeur"], "unite": mesure["unite"],
        "statut": mesure["statut"], "proprietaire": mesure["proprietaire"],
        "version_definition": mesure["version_definition"],
    }
    if mesure["statut"] == entonnoir.STATUT_NON_CALCULABLE:
        ligne["manque"] = list(dict.fromkeys(manque["champ"] for manque in mesure["manque"]))
    elif mesure["entrees"]:
        ligne["entrees"] = mesure["entrees"]
    return ligne


def _liste_bornee(identifiants: list[str], limite: int) -> dict[str, Any]:
    return {"n": len(identifiants), "devis": identifiants[:limite], "reste": max(len(identifiants) - limite, 0)}


def section_entonnoir(
    situation: dict[str, Any], manques: list[dict[str, str]], limite: int = _LIMITE_LISTE
) -> dict[str, Any]:
    """Section « entonnoir » : les mesures (compactes : le détail de ce qui manque va une fois à ``manques``), les
    sources, les devis qui attendent et les seuils. Un seuil non configuré n'est PAS une alerte : c'est un manque
    dit une fois, avec l'endroit où le définir ; une clé de configuration qui ne surveille rien est dite
    (``ignores``)."""
    for mesure in situation["mesures"]:
        if mesure["statut"] == entonnoir.STATUT_NON_CALCULABLE:
            _ajouter_manques(manques, mesure["manque"])
    a_configurer = [e["metric_id"] for e in situation["seuils"] if e["statut"] == entonnoir.SEUIL_A_CONFIGURER]
    invalides = [e["metric_id"] for e in situation["seuils"] if e["statut"] == entonnoir.SEUIL_INVALIDE]
    evalues = [
        {cle: e[cle] for cle in ("metric_id", "statut", "valeur", "unite", "sens", "seuil")}
        for e in situation["seuils"] if e["statut"] in (entonnoir.SEUIL_FRANCHI, entonnoir.SEUIL_NON_FRANCHI)
    ]
    ignores = list(situation["seuils_ignores"])
    seuils: dict[str, Any] = {
        "a_configurer": a_configurer, "invalides": invalides, "ignores": ignores, "evalues": evalues,
    }
    if a_configurer or invalides or ignores:
        seuils["configuration"] = _CONFIGURATION_SEUILS
    devis = situation["devis"]
    return {
        "mesures": [_ligne_mesure(mesure) for mesure in situation["mesures"]],
        "sources": situation["sources"],
        "devis_en_attente": {
            "sans_reponse": _liste_bornee(devis["sans_reponse"], limite),
            "brouillons_en_retard": _liste_bornee(devis["brouillons_en_retard"], limite),
        },
        "seuils": seuils,
    }


# ---------------------------------------------------------------------------
# 2. La marge réelle, telle que M5 la publie
# ---------------------------------------------------------------------------
def _rentabilite_courante(faits_chantier: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Par chantier, le fait de M5 de plus grand ``sequence`` (l'état courant : le bus ne garantit pas l'ordre de
    livraison) ; sans ``sequence``, le dernier reçu, comme ``mesures_chantier.assembler_faits``."""
    courantes: dict[str, dict[str, Any]] = {}
    for fait in faits_chantier:
        if fait.get("type_entree") != "rentabilite" or not isinstance(fait.get("wct_id"), str):
            continue
        actuel = courantes.get(fait["wct_id"])
        rang = fait.get("sequence") if isinstance(fait.get("sequence"), int) else 0
        rang_actuel = actuel.get("sequence") if actuel is not None and isinstance(actuel.get("sequence"), int) else 0
        if actuel is None or rang >= rang_actuel:
            courantes[fait["wct_id"]] = fait
    return courantes


def _raison_marge_absente(rentabilite: dict[str, Any] | None) -> str:
    if rentabilite is None:
        return "M5 n'a rien publié pour ce chantier (m5.rentabilite_chantier)"
    codes = rentabilite.get("manque")
    if isinstance(codes, list) and codes:
        return "M5 n'a pas chiffré la marge réelle : " + ", ".join(str(code) for code in codes)
    return f"M5 n'a pas chiffré la marge réelle (verdict {rentabilite.get('verdict')})"


def _rang_recent(ligne: dict[str, Any]) -> tuple[Any, ...]:
    """Le plus récent d'abord ; un instant illisible passe en dernier, l'identifiant départage : jamais l'ordre de
    réception."""
    instant = entonnoir.instant_lu(ligne["horodatage_completion"])
    return (0, -instant.timestamp(), ligne["wct_id"]) if instant is not None else (1, 0.0, ligne["wct_id"])


def section_marge_reelle(faits_chantier: list[dict[str, Any]], limite: int = _LIMITE_LISTE) -> dict[str, Any]:
    """Une ligne par chantier terminé : la marge M5 qualifiée, verbatim, ou la raison de son exclusion.

    Une marge sans verdict calculé, coût complet et prix définitif n'est pas déclarée réelle. AUCUNE somme,
    moyenne ni arrondi : un montant qualifié est exactement celui de M5."""
    rentabilites = _rentabilite_courante(faits_chantier)
    lignes: list[dict[str, Any]] = []
    vus: set[str] = set()
    for wct in faits_chantier:
        wct_id = wct.get("wct_id")
        if wct.get("type_entree") != "wct" or not isinstance(wct_id, str) or wct_id in vus:
            continue
        vus.add(wct_id)
        rentabilite = rentabilites.get(wct_id)
        raison_qualification = (
            mesures_chantier.raison_marge_reelle_non_qualifiee(rentabilite)
            if rentabilite is not None else None
        )
        marge = (
            rentabilite.get("marge_reelle_cad")
            if rentabilite is not None and raison_qualification is None else None
        )
        ligne: dict[str, Any] = {
            "wct_id": wct_id, "devis_id": wct.get("devis_id"),
            "horodatage_completion": wct.get("horodatage_completion"),
            "statut": entonnoir.STATUT_CALCULEE if marge is not None else entonnoir.STATUT_NON_CALCULABLE,
            "marge_reelle_cad": marge,
        }
        # La source M5 est commune à la section : ne pas la répéter avec verdict/coût
        # sur chaque ligne, pour préserver le budget de sortie et les trois cas ordinaires.
        if rentabilite is not None and "prix_definitif" in rentabilite:
            ligne["prix_definitif"] = rentabilite["prix_definitif"]
        if marge is None:
            ligne["raison"] = raison_qualification or _raison_marge_absente(rentabilite)
        lignes.append(ligne)
    lignes.sort(key=_rang_recent)
    connues = len([ligne for ligne in lignes if ligne["marge_reelle_cad"] is not None])
    return {
        "source": "M5 (m5.rentabilite_chantier), prix définitif/coût complet, reprise sans aucun calcul",
        "n_chantiers": len(lignes), "n_marge_connue": connues, "n_non_calculable": len(lignes) - connues,
        "chantiers": lignes[:limite], "reste": max(len(lignes) - limite, 0),
    }


# ---------------------------------------------------------------------------
# 3. Le stock à commander, tel que M6 le publie
# ---------------------------------------------------------------------------
def section_stock(
    attentes: list[dict[str, Any]] | None, raison_manque: str | None, manques: list[dict[str, str]],
    limite: int = _LIMITE_LISTE,
) -> dict[str, Any]:
    """Les besoins de commande de M6, tels que sa fonction ``attentes()`` les met à la file du propriétaire : son
    résumé, son action proposée, son ordre. ``attentes`` est ``None`` quand M6 n'a pas pu être lu
    (``raison_manque`` dit pourquoi) : un manque nommé, jamais « rien à commander ». Une liste vide est ce que M6
    publie : M6 ne signale que les articles qu'il a constatés."""
    source = "M6 (attentes du propriétaire, type besoin_commande)"
    if attentes is None:
        manque = {"champ": "stock_a_commander", "source": source, "raison": raison_manque or "M6 n'a pas pu être lu"}
        _ajouter_manques(manques, [manque])
        return {"source": source, "statut": "manque", "manque": ["stock_a_commander"]}
    besoins = [attente for attente in attentes if attente.get("type") == _TYPE_ATTENTE_BESOIN_COMMANDE]
    a_configurer = [attente for attente in attentes if attente.get("type") == _TYPE_ATTENTE_SEUIL_A_CONFIGURER]
    for attente in a_configurer:
        _ajouter_manques(manques, [{
            "champ": "seuil_reapprovisionnement", "source": "M6 (configuration.reapprovisionnement)",
            "raison": str(attente.get("resume")),
        }])
    return {
        "source": source, "statut": "lu", "n_articles": len(besoins),
        "articles": [
            {cle: attente.get(cle) for cle in ("id", "resume", "depuis", "action_proposee")}
            for attente in besoins[:limite]
        ],
        "reste": max(len(besoins) - limite, 0),
        "seuils_a_configurer": bool(a_configurer),
    }


# ---------------------------------------------------------------------------
# 4. Le cash libre, tel que M5 l'a constaté
# ---------------------------------------------------------------------------
def section_cash_libre(
    faits_cash_libre: list[dict[str, Any]], aujourd_hui: str | None, manques: list[dict[str, str]]
) -> dict[str, Any]:
    """Le cash libre réel de M5 (T4.16) : le DERNIER constat qu'il a publié (``m5.cash_libre_constate``, T4.19-b), tel
    quel, avec son âge quand l'appelant donne ``aujourd_hui`` ; « manque » si M5 n'en a publié aucun. Un constat « non
    calculable » est montré comme tel, avec ce qui manque : jamais un chiffre de M8 (``cash_libre.py``)."""
    return cash_libre.section(faits_cash_libre, aujourd_hui, manques)


# ---------------------------------------------------------------------------
# La vue, bornée sous la limite de sortie du socle
# ---------------------------------------------------------------------------
def _taille(vue: dict[str, Any]) -> int:
    return len(json.dumps(vue, ensure_ascii=False))


def _listes_bornables(vue: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    attente = vue["entonnoir"]["devis_en_attente"]
    return [
        (vue["marge_reelle"], "chantiers"),
        (vue["stock_a_commander"], "articles"),
        (attente["sans_reponse"], "devis"),
        (attente["brouillons_en_retard"], "devis"),
    ]


def _borner(vue: dict[str, Any], budget_caracteres: int | None) -> dict[str, Any]:
    """Retire un élément à la fois de la fin de la plus longue liste tant que la vue dépasse la borne, et le COMPTE
    dans ``reste``. Sans aucune liste à raccourcir, retire la décomposition du cash libre (comptée et dite).
    Fail-closed : si la vue est encore trop grosse, c'est une erreur, jamais une réponse coupée au milieu."""
    if budget_caracteres is None:
        return vue
    while _taille(vue) > budget_caracteres:
        candidates = [(conteneur, cle) for conteneur, cle in _listes_bornables(vue) if conteneur.get(cle)]
        if not candidates:
            if cash_libre.reduire(vue["cash_libre"]):
                continue
            raise ValueError(f"la vue exécutive dépasse à elle seule la borne de {budget_caracteres} caractères")
        conteneur, cle = max(candidates, key=lambda paire: len(paire[0][paire[1]]))
        conteneur[cle].pop()
        conteneur["reste"] += 1
    return vue


def assembler(
    situation: dict[str, Any], faits_chantier: list[dict[str, Any]], attentes_m6: list[dict[str, Any]] | None,
    raison_manque_m6: str | None, budget_caracteres: int | None = None, *,
    faits_cash_libre: list[dict[str, Any]] | None = None, aujourd_hui: str | None = None,
    fraicheur_attendue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """La vue exécutive : ``situation`` est celle de ``entonnoir.situation``, ``faits_chantier`` le registre des
    chantiers terminés (marge réelle de M5), ``attentes_m6`` ce que M6 publie (``None`` s'il n'a pas pu être lu),
    ``faits_cash_libre`` le registre des constats du cash libre de M5 (aucun : « manque »), ``aujourd_hui`` (AAAA-MM-JJ,
    de l'appelant : M8 n'a pas d'horloge) pour l'âge du constat. ``fraicheur_attendue`` : les clés que
    ``fraicheur_lectures.declarer`` ajoute quand le propriétaire a déclaré une fenêtre (vide : la vue est inchangée,
    aucune clé de plus) ; elles entrent dans la vue AVANT la borne, qui les mesure. Lecture pure : rien n'est écrit,
    rien n'est publié."""
    manques: list[dict[str, str]] = []
    vue = {
        "vue": "executive",
        "portee": _PORTEE,
        "entonnoir": section_entonnoir(situation, manques),
        "marge_reelle": section_marge_reelle(faits_chantier),
        "stock_a_commander": section_stock(attentes_m6, raison_manque_m6, manques),
        "cash_libre": section_cash_libre(faits_cash_libre or [], aujourd_hui, manques),
        "manques": manques,
    }
    if fraicheur_attendue:
        vue.update(fraicheur_attendue)
    return _borner(vue, budget_caracteres)


__all__ = [
    "assembler",
    "section_cash_libre",
    "section_entonnoir",
    "section_marge_reelle",
    "section_stock",
]
