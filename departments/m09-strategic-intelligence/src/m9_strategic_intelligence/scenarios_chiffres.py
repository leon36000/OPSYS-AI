"""Scénarios CHIFFRÉS par les moteurs des propriétaires (M9.8b, M9.9) : M9 compose, compare et explique ; il ne
calcule rien.

Module pur : il décrit chaque choc, traduit ses hypothèses DÉCLARÉES (une personne les donne) en arguments du moteur du
propriétaire, appelle ce moteur par le port injecté (``lecteur(departement, outil, arguments)``, le port privé du
socle) et
compose la réponse. « Le code calcule » dans le département propriétaire :

* finance (M5) : ``m5_simuler_tresorerie_monte_carlo`` (retard de paiement d'une part du carnet, hausse du coût des
  matériaux, baisse des encaissements) et ``m5_comparer_credit_bail_achat`` (achat d'un équipement) ;
* capacité (M4) : ``m4_projeter_capacite_hypotheses`` (employés absents, jours bloqués par la météo, hausse de la
demande) ;
* pipeline (M2) : ``m2_prevoir_pipeline`` (intervalle de la prévision de leads) face à un niveau hypothétique.

Chaque impact porte sa SOURCE (département, outil, arguments exacts), son REÇU (celui du propriétaire, compact) et sa
VÉRIFICATION (rejouée par le propriétaire : ``m5_verifier_recu_calcul``, ``m4_verifier_recu_projection_capacite``,
``m2_rejouer_recu_commercial``, ou rappel du calcul quand le reçu est trop gros pour revenir entier). Les valeurs sont
RECOPIÉES de la réponse du propriétaire, en texte, telles quelles ; M9 ne fait que les comparer (jamais une opération
sur un
montant). Un moteur absent, refusé ou en erreur donne « NON_CHIFFRÉ » avec ce qui manque et qui le possède : jamais
zéro,
jamais un chiffre de M9. Un « et si » reste préparatoire : aucune décision, aucune action, aucun effet externe.

Hypothèses : paramètres du choc (``parametres``) et réglages du calcul (``options``, dont la graine déclarée d'une
simulation : jamais l'horloge). Les conversions faites ici sont des changements de FORME (pourcentage -> facteur ou
fraction exigé par le moteur), pas des impacts.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

VERSION = "2026-11-02.1"
MENTION = "À valider auprès d'un comptable (CPA) / professionnel qualifié pour toute décision financière."
_LIMITES = (
    "Un « et si » préparatoire : aucune décision, aucune action, aucun message externe n'en découle.",
    "Chaque chiffre est celui d'un moteur propriétaire, recopié ; M9 ne calcule aucun impact et n'en invente aucun.",
    "Les lois, probabilités et hypothèses sont celles que la personne a déclarées ; le moteur n'en suppose aucune.",
)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
_PCT = re.compile(r"\d{1,4}(\.\d{1,2})?")
_MONTANT = re.compile(r"\d{1,12}(\.\d{1,2})?")
_TAUX = re.compile(r"(0|1)(\.\d{1,6})?|0?\.\d{1,6}")
_JOUR = re.compile(r"\d{4}-\d{2}-\d{2}")
_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T[0-9:.]{6,15}(Z|[+-]\d{2}:\d{2})")
_CODE = re.compile(r"[A-Za-z0-9_.:\-]{1,80}")
GRAINE_MAX = 2**63 - 1
TIRAGES_MAX = 10_000


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


# ------------------------------------------------------------------------------------------------ paramètres
@dataclass(frozen=True)
class Parametre:
    nom: str
    genre: str  # pct | entier | montant | taux | booleen | dates | absences
    unite: str
    minimum: Decimal | None = None
    maximum: Decimal | None = None


def _decimal(valeur: object, motif: re.Pattern, nom: str) -> Decimal:
    if type(valeur) is not str or not motif.fullmatch(valeur):
        raise _refus("REJ-SCENARIO-NOMBRE", f'{nom} : nombre décimal textuel sobre requis (ex. "30", "1250.00")')
    return Decimal(valeur)


def valider_parametre(p: Parametre, valeur: object) -> object:
    if p.genre == "entier":
        if type(valeur) is not int or not (p.minimum <= valeur <= p.maximum):  # type: ignore[operator]
            raise _refus("REJ-SCENARIO-BORNE", f"{p.nom} : entier de {p.minimum} à {p.maximum} {p.unite}")
        return valeur
    if p.genre == "booleen":
        if type(valeur) is not bool:
            raise _refus("REJ-SCENARIO-PARAMETRES", f"{p.nom} : vrai ou faux, jamais supposé")
        return valeur
    if p.genre in ("pct", "montant", "taux"):
        motif = {"pct": _PCT, "montant": _MONTANT, "taux": _TAUX}[p.genre]
        lu = _decimal(valeur, motif, p.nom)
        if p.minimum is not None and not p.minimum <= lu <= p.maximum:  # type: ignore[operator]
            raise _refus("REJ-SCENARIO-BORNE", f"{p.nom} hors de [{p.minimum}, {p.maximum}] {p.unite}")
        return valeur
    if p.genre == "dates":
        if (
            not isinstance(valeur, list)
            or not 1 <= len(valeur) <= 7
            or len(set(map(str, valeur))) != len(valeur)
            or not all(isinstance(j, str) and _JOUR.fullmatch(j) and _date_valide(j) for j in valeur)
        ):
            raise _refus("REJ-SCENARIO-PARAMETRES", f"{p.nom} : 1 à 7 jours distincts AAAA-MM-JJ")
        return sorted(valeur)
    if p.genre == "absences":
        if not isinstance(valeur, list) or not 1 <= len(valeur) <= 5:
            raise _refus("REJ-SCENARIO-PARAMETRES", f"{p.nom} : 1 à 5 absences {{equipe_id, personnes, jours}}")
        propres = []
        for rang, a in enumerate(valeur):
            if (
                not isinstance(a, Mapping)
                or set(a) != {"equipe_id", "personnes", "jours"}
                or type(a["equipe_id"]) is not str
                or not _ID.fullmatch(a["equipe_id"])
                or type(a["personnes"]) is not int
                or not 1 <= a["personnes"] <= 50
                or type(a["jours"]) is not int
                or not 1 <= a["jours"] <= 7
            ):
                raise _refus("REJ-SCENARIO-PARAMETRES", f"{p.nom}[{rang}] : équipe, personnes (1-50), jours (1-7)")
            propres.append({"equipe_id": a["equipe_id"], "personnes": a["personnes"], "jours": a["jours"]})
        return propres
    raise ValueError(p.genre)  # pragma: no cover - catalogue fermé


def _date_valide(texte: str) -> bool:
    try:
        date.fromisoformat(texte)
    except ValueError:
        return False
    return True


def _p(nom, genre, unite, minimum=None, maximum=None):
    return Parametre(
        nom, genre, unite, None if minimum is None else Decimal(minimum), None if maximum is None else Decimal(maximum)
    )


# ---------------------------------------------------------------------------------------------------- les chocs
@dataclass(frozen=True)
class Choc:
    id: str
    libelle: str
    dimension: str  # finance | capacite | pipeline
    proprietaire: str
    outil: str
    parametres: tuple[Parametre, ...]
    options: tuple[str, ...]  # options exigées du calcul (jamais un défaut caché)
    catalogue: str | None  # choc du catalogue arithmétique de ``scenarios`` que ce chiffrage remplace, s'il y en a un
    ce_que_m9_ne_fait_pas: str


CHOCS: Mapping[str, Choc] = {
    c.id: c
    for c in (
        Choc(
            "retard_paiement_carnet",
            "Retard de paiement d'une part du carnet de factures clients",
            "finance",
            "m05-financecore",
            "m5_simuler_tresorerie_monte_carlo",
            (_p("part_carnet_pct", "pct", "%", "0.01", "100"), _p("retard_semaines", "entier", "semaines", 1, 12)),
            ("graine", "tirages"),
            "retard_paiement_client",
            "M9 ne tire aucun retard et ne somme aucune facture : M5 simule ses propres flux datés.",
        ),
        Choc(
            "hausse_cout_materiaux",
            "Hausse du coût des matériaux sur les factures fournisseurs à venir",
            "finance",
            "m05-financecore",
            "m5_simuler_tresorerie_monte_carlo",
            (
                _p("hausse_min_pct", "pct", "%", "0", "200"),
                _p("hausse_probable_pct", "pct", "%", "0", "200"),
                _p("hausse_max_pct", "pct", "%", "0", "200"),
            ),
            ("graine", "tirages"),
            "hausse_cout_materiaux",
            "M9 ne majore aucun montant : M5 applique la loi triangulaire déclarée aux flux fournisseurs.",
        ),
        Choc(
            "baisse_encaissements",
            "Baisse des encaissements clients (saison morte, perte d'un client)",
            "finance",
            "m05-financecore",
            "m5_simuler_tresorerie_monte_carlo",
            (
                _p("baisse_min_pct", "pct", "%", "0", "99"),
                _p("baisse_probable_pct", "pct", "%", "0", "99"),
                _p("baisse_max_pct", "pct", "%", "0", "99"),
            ),
            ("graine", "tirages"),
            "saison_morte_faible",
            "M9 ne retranche aucun encaissement : M5 applique la loi triangulaire déclarée aux flux clients.",
        ),
        Choc(
            "achat_equipement_comparaison",
            "Achat comptant ou crédit-bail d'un équipement",
            "finance",
            "m05-financecore",
            "m5_comparer_credit_bail_achat",
            (
                _p("prix_achat", "montant", "CAD", "0.01", "1000000000"),
                _p("frais_achat", "montant", "CAD", "0", "1000000000"),
                _p("valeur_residuelle", "montant", "CAD", "0", "1000000000"),
                _p("paiement_mensuel", "montant", "CAD", "0", "1000000000"),
                _p("depot_initial", "montant", "CAD", "0", "1000000000"),
                _p("mois", "entier", "mois", 1, 120),
                _p("taux_actualisation_annuel", "taux", "fraction", "0", "1"),
                _p("paiements_en_debut_de_periode", "booleen", ""),
            ),
            (),
            "achat_equipement",
            "M9 n'actualise aucun flux : M5 compare les coûts actualisés ; l'effet fiscal n'est pas modélisé.",
        ),
        Choc(
            "absences_equipe",
            "Employés absents (jours-personnes retirés à une équipe)",
            "capacite",
            "m04-field-ops",
            "m4_projeter_capacite_hypotheses",
            (_p("absences", "absences", "personnes × jours"),),
            ("debut_semaine",),
            "absences",
            "M9 ne convertit aucune absence en heures : M4 le fait par la durée et l'effectif DÉCLARÉS.",
        ),
        Choc(
            "meteo_jours_bloques",
            "Jours de mauvais temps (aucune équipe ne travaille)",
            "capacite",
            "m04-field-ops",
            "m4_projeter_capacite_hypotheses",
            (_p("jours_bloques", "dates", "jours"),),
            ("debut_semaine",),
            "meteo",
            "M9 ne retire aucune heure : M4 recalcule la semaine type avec ces jours en congé d'équipe.",
        ),
        Choc(
            "hausse_demande_charge",
            "Hausse de la demande (heures planifiées en hausse)",
            "capacite",
            "m04-field-ops",
            "m4_projeter_capacite_hypotheses",
            (_p("hausse_demande_pct", "pct", "%", "0", "1000"),),
            ("debut_semaine",),
            "trop_de_demandes",
            "M9 ne majore aucune heure : M4 applique la hausse déclarée aux heures planifiées de la cédule.",
        ),
        Choc(
            "leads_niveau_hypothetique",
            "Niveau de leads par semaine face à l'intervalle de prévision de M2",
            "pipeline",
            "m02-revenue-crm",
            "m2_prevoir_pipeline",
            (_p("leads_par_semaine", "montant", "leads/semaine", "0", "1000000"),),
            ("serie", "methode", "horizon", "niveau"),
            "baisse_leads",
            "M9 ne prévoit rien : M2 donne l'intervalle, M9 dit seulement si le niveau déclaré y est.",
        ),
    )
}


def catalogue() -> list[dict]:
    return [
        {
            "choc": c.id,
            "libelle": c.libelle,
            "dimension": c.dimension,
            "proprietaire": c.proprietaire,
            "outil": c.outil,
            "parametres": [{"nom": p.nom, "genre": p.genre, "unite": p.unite} for p in c.parametres],
            "options": list(c.options),
            "remplace_le_choc_arithmetique": c.catalogue,
        }
        for c in CHOCS.values()
    ]


def choc(choc_id: object) -> Choc:
    if type(choc_id) is not str or choc_id not in CHOCS:
        raise _refus("REJ-SCENARIO-CHOC", f"choc chiffré parmi {sorted(CHOCS)}")
    return CHOCS[choc_id]


def valider(choc_id: object, parametres: object, options: object) -> tuple[Choc, dict, dict]:
    c = choc(choc_id)
    if not isinstance(parametres, Mapping) or set(parametres) != {p.nom for p in c.parametres}:
        raise _refus("REJ-SCENARIO-PARAMETRES", f"paramètres exacts requis : {[p.nom for p in c.parametres]}")
    propres = {p.nom: valider_parametre(p, parametres[p.nom]) for p in c.parametres}
    if c.id in ("hausse_cout_materiaux", "baisse_encaissements"):
        prefixe = "hausse" if c.id == "hausse_cout_materiaux" else "baisse"
        bas, mode, haut = (Decimal(propres[f"{prefixe}_{k}_pct"]) for k in ("min", "probable", "max"))
        if not bas <= mode <= haut or bas == haut:
            raise _refus(
                "REJ-SCENARIO-PARAMETRES", "min ≤ probable ≤ max et min < max exigés (loi triangulaire déclarée)"
            )
    return c, propres, _valider_options(c, options)


def _valider_options(c: Choc, options: object) -> dict:
    if options is None:
        options = {}
    permises = {
        "graine",
        "tirages",
        "horizon_semaines",
        "debut_semaine",
        "horodatage_reference",
        "portee",
        "serie",
        "methode",
        "horizon",
        "niveau",
        "fenetre",
        "alpha",
    }
    if not isinstance(options, Mapping) or set(options) - permises:
        raise _refus("REJ-SCENARIO-OPTION", f"options parmi {sorted(permises)}")
    manquantes = [nom for nom in c.options if nom not in options]
    if manquantes:
        raise _refus("REJ-SCENARIO-OPTION", f"options exigées, jamais supposées : {manquantes}")
    propres: dict = {}
    for nom, valeur in options.items():
        if nom == "graine":
            ok = type(valeur) is int and 0 <= valeur <= GRAINE_MAX
        elif nom == "tirages":
            ok = type(valeur) is int and 1 <= valeur <= TIRAGES_MAX
        elif nom in ("horizon_semaines",):
            ok = type(valeur) is int and 1 <= valeur <= 26
        elif nom == "horizon":
            ok = type(valeur) is int and 1 <= valeur <= 8
        elif nom == "niveau":
            ok = valeur in (80, 90, 95) and type(valeur) is int
        elif nom == "fenetre":
            ok = type(valeur) is int and 2 <= valeur <= 12
        elif nom == "debut_semaine":
            ok = (
                type(valeur) is str
                and bool(_JOUR.fullmatch(valeur))
                and _date_valide(valeur)
                and (date.fromisoformat(valeur).weekday() == 0)
            )
        elif nom == "horodatage_reference":
            ok = type(valeur) is str and bool(_INSTANT.fullmatch(valeur))
        elif nom == "portee":
            ok = valeur in ("semaine_type", "journees_datees_seulement")
        elif nom == "serie":
            ok = valeur in ("leads_ingeres", "leads_qualifies", "leads_convertis", "leads_perdus")
        elif nom == "methode":
            ok = valeur in ("moyenne_mobile", "lissage_exponentiel")
        else:  # alpha
            ok = type(valeur) is str and bool(_TAUX.fullmatch(valeur))
        if not ok:
            raise _refus("REJ-SCENARIO-OPTION", f"option {nom} hors de sa forme")
        propres[nom] = valeur
    return propres


# --------------------------------------------------------------------------------------------- appel d'un propriétaire
def _code_sur(valeur: object, defaut: str) -> str:
    return valeur if type(valeur) is str and _CODE.fullmatch(valeur) else defaut


def appeler(
    lecteur: Callable[..., Mapping], departement: str, outil: str, arguments: Mapping
) -> tuple[dict | None, str | None]:
    """``(corps, None)`` ou ``(None, code)`` : jamais une exception, jamais un chiffre de remplacement. Le texte d'un
    refus du
    propriétaire n'est pas recopié (son code seul l'est)."""
    try:
        reponse = lecteur(departement, outil, dict(arguments))
    except Exception:  # noqa: BLE001 - frontière : tout échec du port est un « non chiffré », pas un faux chiffre
        return None, "ERREUR_DU_PORT"
    if not isinstance(reponse, Mapping):
        return None, "REPONSE_ILLISIBLE"
    if reponse.get("ok") is not True:
        return None, _code_sur(reponse.get("erreur"), "ERREUR_DU_PROPRIETAIRE")
    interne = reponse.get("resultat")
    if not isinstance(interne, Mapping):
        return None, "REPONSE_ILLISIBLE"
    if interne.get("accepte") is False:
        verdict = interne.get("verdict")
        return None, _code_sur(verdict.get("code") if isinstance(verdict, Mapping) else None, "REFUS_SANS_CODE")
    if interne.get("accepte") is not True:
        return None, "REPONSE_INATTENDUE"
    return dict(interne), None


def _non_chiffre(c: Choc, impact_id: str, code: str, source: Mapping, manque: str) -> dict:
    return {
        "id": impact_id,
        "dimension": c.dimension,
        "proprietaire": c.proprietaire,
        "outil": c.outil,
        "statut": "NON_CHIFFRE",
        "raison": code,
        "manque": manque,
        "source": dict(source),
        "valeurs": None,
        "recu": None,
        "verification": None,
    }


def _source(c: Choc, arguments: Mapping) -> dict:
    return {"departement": c.proprietaire, "outil": c.outil, "arguments": copy.deepcopy(dict(arguments))}


_TEXTES_CONSTANTS_DU_RECU = ("methode", "precision", "avertissements")


def _recu_allege(recu: Mapping) -> dict:
    """Le reçu du propriétaire SANS ses entrées ni les textes constants de sa méthode (la sortie d'un outil est
    bornée) :
    l'empreinte, les paramètres, le résultat et les empreintes d'entrées y restent. Il se rejoue en rappelant le
    moteur avec
    ``source.arguments`` ; le propriétaire l'a déjà rejoué (``verification``)."""
    allege = {k: v for k, v in recu.items() if k != "entrees" and k not in _TEXTES_CONSTANTS_DU_RECU}
    allege["allege"] = [k for k in ("entrees", *_TEXTES_CONSTANTS_DU_RECU) if k in recu]
    return allege


def _facteur(pct: str, signe: int) -> str:
    """Changement de FORME : 25 % de hausse -> facteur 1.25 (ou 0.75 pour une baisse), texte décimal exact."""
    return format((Decimal(1) + signe * Decimal(pct) / Decimal(100)).normalize(), "f")


def _fraction(pct: str) -> str:
    return format((Decimal(pct) / Decimal(100)).normalize(), "f")


def _loi_triangulaire(bas: str, mode: str, haut: str, signe: int) -> dict:
    """Pour une baisse, les bornes s'inversent : la plus grande baisse donne le plus petit facteur."""
    if signe < 0:
        bas, haut = haut, bas
    return {
        "loi": "triangulaire",
        "min": _facteur(bas, signe),
        "mode": _facteur(mode, signe),
        "max": _facteur(haut, signe),
    }


# --------------------------------------------------------------------------------------------------- finance (M5)
def _arguments_monte_carlo(c: Choc, p: Mapping, o: Mapping, jour: str) -> dict:
    if c.id == "retard_paiement_carnet":
        retard = {"probabilite": _fraction(p["part_carnet_pct"]), "semaines": p["retard_semaines"]}
        distributions = {"facture_client": {"retard": retard}}
    elif c.id == "hausse_cout_materiaux":
        loi = _loi_triangulaire(p["hausse_min_pct"], p["hausse_probable_pct"], p["hausse_max_pct"], +1)
        distributions = {"facture_fournisseur": {"montant": dict(loi)}, "attendu_fournisseur": {"montant": dict(loi)}}
    else:  # baisse_encaissements
        loi = _loi_triangulaire(p["baisse_min_pct"], p["baisse_probable_pct"], p["baisse_max_pct"], -1)
        distributions = {"facture_client": {"montant": dict(loi)}, "echeancier_contrat": {"montant": dict(loi)}}
    arguments = {"aujourd_hui": jour, "graine": o["graine"], "tirages": o["tirages"], "distributions": distributions}
    if "horizon_semaines" in o:
        arguments["horizon_semaines"] = o["horizon_semaines"]
    return arguments


def _verifier_m5(lecteur, recu: Mapping, rappel: Callable[[], str | None]) -> dict:
    if "entrees" in recu:
        corps, code = appeler(lecteur, "m05-financecore", "m5_verifier_recu_calcul", {"recu": recu})
        if corps is None:
            return {"outil": "m5_verifier_recu_calcul", "mode": "rejeu", "identique": None, "non_verifie": code}
        r = corps.get("resultat") if isinstance(corps.get("resultat"), Mapping) else {}
        return {
            "outil": "m5_verifier_recu_calcul",
            "mode": "rejeu",
            "identique": r.get("identique") is True,
            "empreinte_recue": r.get("empreinte_recue"),
            "empreinte_recalculee": r.get("empreinte_recalculee"),
        }
    empreinte = rappel()
    return {
        "outil": "m5_simuler_tresorerie_monte_carlo",
        "mode": "rappel_du_calcul",
        "identique": empreinte is not None and empreinte == recu.get("empreinte"),
        "empreinte_recue": recu.get("empreinte"),
        "empreinte_recalculee": empreinte,
    }


def _impact_monte_carlo(c: Choc, p: Mapping, o: Mapping, jour: str, lecteur) -> dict:
    arguments = _arguments_monte_carlo(c, p, o, jour)
    source = _source(c, arguments)
    corps, code = appeler(lecteur, c.proprietaire, c.outil, arguments)
    if corps is None:
        return _non_chiffre(
            c,
            "tresorerie",
            code,
            source,
            f"M5 n'a pas simulé la trésorerie ({code}) : prévision non calculable, droit refusé ou moteur absent",
        )
    resultat = corps.get("resultat")
    recu = resultat.get("recu") if isinstance(resultat, Mapping) else None
    res = recu.get("resultat") if isinstance(recu, Mapping) else None
    if (
        not isinstance(res, Mapping)
        or not isinstance(res.get("colonnes"), list)
        or not isinstance(res.get("semaines"), list)
    ):
        return _non_chiffre(c, "tresorerie", "REPONSE_INATTENDUE", source, "la réponse de M5 n'a pas la forme du reçu")
    colonnes = res["colonnes"]
    voulues = ("semaine", "solde_base", "p5", "p50", "p95", "probabilite_negatif")
    if not set(voulues) <= set(colonnes):
        return _non_chiffre(c, "tresorerie", "REPONSE_INATTENDUE", source, "colonnes du reçu de M5 inattendues")
    trajectoire = [{k: ligne[colonnes.index(k)] for k in voulues} for ligne in res["semaines"]]
    premiere = next((t["semaine"] for t in trajectoire if _negatif(t["p5"])), None)
    valeurs = {
        "semaines_simulees": resultat.get("semaines_simulees"),
        "solde_initial": (recu.get("entrees") or {}).get("solde_initial"),
        "plus_bas_du_chemin": res.get("plus_bas_du_chemin"),
        "probabilite_au_moins_une_semaine_negative": res.get("probabilite_au_moins_une_semaine_negative"),
        "tirages_avec_semaine_negative": res.get("tirages_avec_semaine_negative"),
        "tirages": o["tirages"],
        "graine": o["graine"],
        "flux_perturbes": res.get("flux_perturbes"),
        "encaissements_reportes_hors_horizon": res.get("encaissements_reportes_hors_horizon"),
        "premiere_semaine_dont_le_p5_est_negatif": premiere,
        "unite": "CAD",
    }
    compact = _recu_allege(recu)

    def rappel() -> str | None:
        autre, _ = appeler(lecteur, c.proprietaire, c.outil, arguments)
        r = (autre or {}).get("resultat") or {}
        return (r.get("recu") or {}).get("empreinte") if isinstance(r, Mapping) else None

    return {
        "id": "tresorerie",
        "dimension": c.dimension,
        "proprietaire": c.proprietaire,
        "outil": c.outil,
        "statut": "CHIFFRE",
        "source": source,
        "valeurs": valeurs,
        "recu": compact,
        "verification": _verifier_m5(lecteur, recu, rappel),
        "avertissements_du_proprietaire": res_avert(recu),
    }


def res_avert(recu: Mapping) -> list[str]:
    """Les avertissements du propriétaire, abrégés (le texte entier est dans son reçu : rappeler le moteur)."""
    return [a[:110] for a in recu.get("avertissements", []) if isinstance(a, str)][:3]


def _negatif(texte: object) -> bool:
    try:
        return Decimal(str(texte)) < 0
    except InvalidOperation:
        return False


def _impact_achat(c: Choc, p: Mapping, lecteur) -> dict:
    arguments = {
        "objet": "equipement",
        "taux_actualisation_annuel": p["taux_actualisation_annuel"],
        "mois": p["mois"],
        "prix_achat": p["prix_achat"],
        "frais_achat": p["frais_achat"],
        "valeur_residuelle": p["valeur_residuelle"],
        "paiement_mensuel": p["paiement_mensuel"],
        "depot_initial": p["depot_initial"],
        "paiements_en_debut_de_periode": p["paiements_en_debut_de_periode"],
    }
    source = _source(c, arguments)
    corps, code = appeler(lecteur, c.proprietaire, c.outil, arguments)
    if corps is None:
        return _non_chiffre(
            c, "achat_equipement", code, source, f"M5 n'a pas comparé l'achat et le crédit-bail ({code})"
        )
    resultat = corps.get("resultat")
    recu = resultat.get("recu") if isinstance(resultat, Mapping) else None
    res = recu.get("resultat") if isinstance(recu, Mapping) else None
    cles = (
        "va_cout_achat",
        "va_cout_credit_bail",
        "ecart_credit_bail_moins_achat",
        "option_au_cout_actualise_le_plus_bas",
    )
    if not isinstance(res, Mapping) or not all(k in res for k in cles):
        return _non_chiffre(
            c, "achat_equipement", "REPONSE_INATTENDUE", source, "la réponse de M5 n'a pas la forme du reçu"
        )

    def rappel() -> str | None:
        autre, _ = appeler(lecteur, c.proprietaire, c.outil, arguments)
        r = (autre or {}).get("resultat") or {}
        return (r.get("recu") or {}).get("empreinte") if isinstance(r, Mapping) else None

    return {
        "id": "achat_equipement",
        "dimension": c.dimension,
        "proprietaire": c.proprietaire,
        "outil": c.outil,
        "statut": "CHIFFRE",
        "source": source,
        "unite": "CAD",
        "valeurs": {k: res[k] for k in cles} | {"unite": "CAD"},
        "recu": _recu_allege(recu),
        "verification": _verifier_m5(lecteur, recu, rappel),
        "avertissements_du_proprietaire": res_avert(recu),
    }


# ------------------------------------------------------------------------------------------------- capacité (M4)
def _hypotheses_m4(c: Choc, p: Mapping) -> dict:
    if c.id == "absences_equipe":
        return {"absences": copy.deepcopy(p["absences"])}
    if c.id == "meteo_jours_bloques":
        return {"jours_bloques": list(p["jours_bloques"])}
    return {"hausse_demande_pct": p["hausse_demande_pct"]}


def _impact_capacite(c: Choc, p: Mapping, o: Mapping, horodatage: str, lecteur) -> dict:
    arguments = {
        "debut_semaine": o["debut_semaine"],
        "hypotheses": _hypotheses_m4(c, p),
        "portee": o.get("portee", "semaine_type"),
    }
    arguments["horodatage_reference"] = o.get("horodatage_reference", horodatage)  # l'instant de lecture, tracé au reçu
    source = _source(c, arguments)
    corps, code = appeler(lecteur, c.proprietaire, c.outil, arguments)
    if corps is None:
        return _non_chiffre(c, "capacite", code, source, f"M4 n'a pas projeté la capacité ({code})")
    r = corps.get("resultat")
    if not isinstance(r, Mapping) or type(r.get("calculable")) is not bool:
        return _non_chiffre(c, "capacite", "REPONSE_INATTENDUE", source, "la réponse de M4 n'a pas la forme du contrat")
    if r["calculable"] is not True:
        manque = [m for m in r.get("manque", []) if type(m) is str and _CODE.fullmatch(m)]
        return _non_chiffre(
            c,
            "capacite",
            "NON_CALCULABLE_CHEZ_LE_PROPRIETAIRE",
            source,
            "M4 dit non calculable, manque : " + (", ".join(manque) or "non précisé"),
        )
    recu = r.get("recu")
    if not isinstance(recu, Mapping):
        return _non_chiffre(c, "capacite", "REPONSE_INATTENDUE", source, "M4 n'a rendu aucun reçu")
    verif, code_v = appeler(lecteur, c.proprietaire, "m4_verifier_recu_projection_capacite", {"recu": recu})
    verification = (
        {"outil": "m4_verifier_recu_projection_capacite", "mode": "rejeu", "identique": None, "non_verifie": code_v}
        if verif is None
        else {
            "outil": "m4_verifier_recu_projection_capacite",
            "mode": "rejeu",
            "identique": (verif.get("resultat") or {}).get("identique") is True,
            "empreinte": (verif.get("resultat") or {}).get("empreinte"),
        }
    )
    return {
        "id": "capacite",
        "dimension": c.dimension,
        "proprietaire": c.proprietaire,
        "outil": c.outil,
        "statut": "CHIFFRE",
        "source": source,
        "valeurs": {
            "semaine_debut": r.get("semaine_debut"),
            "portee": r.get("portee"),
            "unite": r.get("unite"),
            "equipes": copy.deepcopy(r.get("equipes")),
            "equipes_en_surcharge": list(r.get("equipes_en_surcharge", [])),
        },
        "recu": copy.deepcopy(dict(recu)),
        "verification": verification,
    }


# ------------------------------------------------------------------------------------------------- pipeline (M2)
def _impact_pipeline(c: Choc, p: Mapping, o: Mapping, horodatage: str, lecteur) -> dict:
    arguments = {
        "horodatage": horodatage,
        "serie": o["serie"],
        "methode": o["methode"],
        "horizon": o["horizon"],
        "niveau": o["niveau"],
        "avec_recu": True,
    }
    for cle in ("graine", "fenetre", "alpha"):
        if cle in o:
            arguments[cle] = o[cle]
    source = _source(c, arguments)
    corps, code = appeler(lecteur, c.proprietaire, c.outil, arguments)
    if corps is None:
        return _non_chiffre(
            c,
            "pipeline",
            code,
            source,
            f"M2 n'a pas prévu {o['serie']} ({code}) : historique insuffisant, droit refusé ou moteur absent",
        )
    r = corps.get("resultat")
    recu = r.get("recu") if isinstance(r, Mapping) else None
    res = recu.get("resultat") if isinstance(recu, Mapping) else None
    periodes = res.get("par_periode") if isinstance(res, Mapping) else None
    if not isinstance(periodes, list) or not periodes:
        return _non_chiffre(c, "pipeline", "REPONSE_INATTENDUE", source, "la réponse de M2 n'a pas la forme du reçu")
    niveau_hypothetique = p["leads_par_semaine"]
    lignes = []
    for periode in periodes:
        intervalle = periode.get("intervalle") if isinstance(periode, Mapping) else None
        if not isinstance(intervalle, Mapping):
            return _non_chiffre(c, "pipeline", "REPONSE_INATTENDUE", source, "intervalle de M2 illisible")
        lignes.append(
            {
                "periode": periode.get("periode"),
                "centre": periode.get("centre"),
                "intervalle": {k: intervalle.get(k) for k in ("niveau", "bas", "haut")},
                "position_du_niveau_declare": _position(
                    niveau_hypothetique, intervalle.get("bas"), intervalle.get("haut")
                ),
            }
        )
    verif, code_v = appeler(lecteur, c.proprietaire, "m2_rejouer_recu_commercial", {"recu": recu})
    res_v = (verif or {}).get("resultat") if verif else None
    verification = {
        "outil": "m2_rejouer_recu_commercial",
        "mode": "rejeu",
        "identique": None if verif is None else (res_v or {}).get("identique") is True,
        **({"non_verifie": code_v} if verif is None else {}),
    }
    return {
        "id": "pipeline",
        "dimension": c.dimension,
        "proprietaire": c.proprietaire,
        "outil": c.outil,
        "statut": "CHIFFRE",
        "source": source,
        "valeurs": {
            "serie": (res.get("serie") or {}).get("nom") if isinstance(res.get("serie"), Mapping) else None,
            "niveau_declare_par_la_personne": niveau_hypothetique,
            "unite": "leads/semaine",
            "par_periode": lignes,
        },
        "recu": _recu_allege(recu),
        "verification": verification,
    }


def _position(niveau: str, bas: object, haut: object) -> str:
    """Comparaison de deux nombres (jamais une opération) : où est le niveau déclaré face à l'intervalle de M2."""
    try:
        n, b, h = Decimal(niveau), Decimal(str(bas)), Decimal(str(haut))
    except InvalidOperation:
        return "INCOMPARABLE"
    if n < b:
        return "SOUS_L_INTERVALLE"
    if n > h:
        return "AU_DESSUS_DE_L_INTERVALLE"
    return "DANS_L_INTERVALLE"


# --------------------------------------------------------------------------------------------------------- l'entrée
def chiffrer(
    choc_id: object,
    parametres: object,
    options: object,
    *,
    jour: str,
    horodatage: str,
    lecteur: Callable[..., Mapping] | None,
) -> dict:
    """Le scénario chiffré. ``jour`` (AAAA-MM-JJ) et ``horodatage`` (RFC 3339) viennent de l'appelant : M9 n'a pas
    d'horloge.
    ``lecteur`` ``None`` (port non fourni) : tous les impacts sont NON_CHIFFRÉS."""
    c, p, o = valider(choc_id, parametres, options)
    if type(jour) is not str or not _JOUR.fullmatch(jour) or not _date_valide(jour):
        raise _refus("REJ-SCENARIO-TEMPS", "jour AAAA-MM-JJ requis")
    if type(horodatage) is not str or not _INSTANT.fullmatch(horodatage):
        raise _refus("REJ-SCENARIO-TEMPS", "horodatage RFC 3339 à fuseau explicite requis")
    port = lecteur if lecteur is not None else _port_absent
    if c.dimension == "finance" and c.outil == "m5_simuler_tresorerie_monte_carlo":
        impact = _impact_monte_carlo(c, p, o, jour, port)
    elif c.dimension == "finance":
        impact = _impact_achat(c, p, port)
    elif c.dimension == "capacite":
        impact = _impact_capacite(c, p, o, horodatage, port)
    else:
        impact = _impact_pipeline(c, p, o, horodatage, port)
    scenario = {
        "type": "SCENARIO_CHIFFRE",
        "version": VERSION,
        "choc": c.id,
        "libelle": c.libelle,
        "dimension": c.dimension,
        "remplace_le_choc_arithmetique": c.catalogue,
        "hypotheses": [
            {"nom": q.nom, "valeur": p[q.nom], "unite": q.unite, "origine": "DECLAREE_PAR_LA_PERSONNE"}
            for q in c.parametres
        ],
        "options_du_calcul": dict(o),
        "impacts": [impact],
        "chiffre": impact["statut"] == "CHIFFRE",
        "non_chiffre": [] if impact["statut"] == "CHIFFRE" else [{"impact": impact["id"], "manque": impact["manque"]}],
        "m9_calcule": False,
        "ce_que_m9_ne_fait_pas": c.ce_que_m9_ne_fait_pas,
        "decision": None,
        "action_externe": False,
        "mention": MENTION,
        "limites": list(_LIMITES),
    }
    scenario["scenario_id"] = hashlib.sha256(
        json.dumps(scenario, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return scenario


def _port_absent(departement: str, outil: str, arguments: Mapping) -> Mapping:
    return {"ok": False, "erreur": "port_absent"}
