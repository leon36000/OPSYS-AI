"""Mesures d'entreprise tirées des constats que les AUTRES départements ont publiés (M1, M3, M4, M5, M6, M7).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge (les instants viennent des faits reçus). Même patron
que ``synthese.py`` : chaque métrique est définie une seule fois dans ``metrics/m8-interdepartements.v1.yaml`` (nom,
formule, source, unité CAD pour un montant, propriétaire) et porte la version de sa définition ; un calcul manquant ou
une entrée absente donne « non calculable, manque X », jamais un zéro inventé.

Trois règles qui ne changent pas d'une mesure à l'autre :

1. TEL QUEL OU CUMULÉ, JAMAIS REFAIT. Un montant de M5 (créances, comptes à payer) passe du fait reçu à la mesure sans
   calcul. Une marge est cumulée chantier par chantier à partir de la marge que M5 a chiffrée et qui a passé les gardes
   de ``mesures_chantier`` (prix définitif, coût réel complet) ; M8 ne fait pas la comptabilité.
2. LA COUVERTURE EST DITE. Une mesure calculée sur une partie seulement de ce qu'elle devrait couvrir (« 2 chantiers sur
   4 », « 2 jours sans relevé ») garde sa valeur, porte ``couverture = {etat: partielle, couverts, attendus, raison}``
   et son ``detail`` le dit en toutes lettres. Une mesure sans source est ``inconnue`` (non calculable). Une valeur
   partielle n'est jamais présentée comme complète, et un jour sans relevé n'est jamais un zéro.
3. LES ÉCARTS DE DÉFINITION SONT DES MESURES NOMMÉES. Marge réelle (M5) contre marge prévue (M3), relevés de dépense
(M7) contre dépense comptabilisée (M5), demandes qualifiées par M1 contre leads reçus par M2 : deux définitions de deux
   départements ne se moyennent pas, leur écart se montre sous son nom, avec les deux côtés dans ``entrees``.

Chaque mesure calculée porte, dans ``entrees``, l'``empreinte_faits`` des faits qu'elle a utilisés (indépendante de
l'ordre de livraison) : la même suite de faits donne la même empreinte, un fait utilisé qui change en donne une autre.

Forme d'une mesure : celle de ``entonnoir.construire_mesure`` plus ``dernier_fait_le`` (l'instant du fait le plus récent
qui la porte), ``couverture`` et ``fenetre_source_s`` (la fenêtre de fraîcheur que le département SOURCE déclare
lui-même, quand il en déclare une ; ``fraicheur_mesures`` retient la plus stricte des fenêtres).
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import cash_libre, contenus, encodage, entonnoir, mesures_chantier, nombres, operations_recues, synthese

_CHEMIN_METRIQUES = Path(__file__).resolve().parents[2] / "metrics" / "m8-interdepartements.v1.yaml"
_REGISTRE = "des mesures interdépartements"

_MINUTES_PAR_HEURE = Decimal("60")
_JOURS_PAR_RELEVE_MAX = 3660  # dix ans : au-delà, la période d'un relevé n'est pas crédible, le relevé est refusé
_CITES = 3
_SEVERITE_CRITIQUE = "critique"
_VERDICT_CONFORME = "CONFORME"
# Canal de dépense (M7 `depenses_marketing_constatees`) -> source de signaux de M7 qui dit sa fraîcheur.
_SOURCE_DU_CANAL = {"google_ads": "google_ads", "meta": "meta_ads"}

Resultat = tuple[str | None, dict[str, Any], list[dict[str, str]], str | None, dict[str, Any] | None, int | None]


def charger_definitions(chemin: str | Path | None = None) -> dict[str, dict[str, str]]:
    """Définitions de ``metrics/m8-interdepartements.v1.yaml`` : mêmes contrôles et mêmes refus que les autres registres
    (fail-closed, garde de devise CAD, chaque métrique a un propriétaire connu)."""
    return entonnoir.charger_definitions(chemin if chemin is not None else _CHEMIN_METRIQUES, registre=_REGISTRE)


# ---------------------------------------------------------------------------
# Petits outils communs
# ---------------------------------------------------------------------------
def _manque(champ: str, source: str, raison: str) -> dict[str, str]:
    return {"champ": champ, "source": source, "raison": raison}


def _non_calculable(
    manque: list[dict[str, str]], entrees: dict[str, Any] | None = None, instant: str | None = None
) -> Resultat:
    return None, entrees or {}, manque, instant, None, None


def _empreinte_faits(faits: list[dict[str, Any]]) -> str:
    """Empreinte des faits utilisés, indépendante de l'ordre de livraison : chaque fait est mis en forme canonique,
    puis les
    formes sont triées."""
    return encodage.empreinte(sorted(encodage.encoder_canonique(fait) for fait in faits))


def _de_type(faits: list[dict[str, Any]], type_entree: str) -> list[dict[str, Any]]:
    return [fait for fait in faits if fait.get("type_entree") == type_entree]


def _uniques(faits: list[dict[str, Any]], cle: str) -> list[dict[str, Any]]:
    """Le premier fait de chaque valeur de ``cle`` (une relivraison n'ajoute rien) ; un fait sans identifiant lisible
    n'est
    pas un fait."""
    vus: set[str] = set()
    uniques = []
    for fait in faits:
        identifiant = fait.get(cle)
        if isinstance(identifiant, str) and identifiant and identifiant not in vus:
            vus.add(identifiant)
            uniques.append(fait)
    return uniques


def _plus_recent(instants: list[Any]) -> str | None:
    lus = [(entonnoir.instant_lu(texte), texte) for texte in instants]
    lisibles = [(instant, texte) for instant, texte in lus if instant is not None]
    return max(lisibles, key=lambda paire: paire[0])[1] if lisibles else None


def _cites(identifiants: list[str]) -> str:
    cites = ", ".join(identifiants[:_CITES])
    reste = len(identifiants) - _CITES
    return f"{cites} et {reste} autre(s)" if reste > 0 else cites


def _partielle(couverts: int, attendus: int, raison: str) -> dict[str, Any]:
    return {
        "etat": "partielle",
        "couverts": couverts,
        "attendus": attendus,
        "manquants": attendus - couverts,
        "raison": raison,
    }


def _jour(texte: Any) -> date | None:
    if not isinstance(texte, str) or len(texte) != 10:
        return None
    try:
        return date.fromisoformat(texte)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# M5 (+ M3, M4) : la marge des chantiers terminés
# ---------------------------------------------------------------------------
_MANQUE_WCT = _manque(
    "m4.travaux_termines",
    "M4 (m4.travaux_termines)",
    "aucun chantier terminé reçu : rien terminé par M4, ou rien livré par le bus",
)


def _analyser_chantiers(faits_chantier: list[dict[str, Any]]) -> dict[str, Any]:
    """Pour chaque chantier terminé, la marge réelle et l'écart de marge TELS QUE ``mesures_chantier`` les mesure (mêmes
    gardes : prix définitif, coût réel complet), et les faits utilisés."""
    definitions = mesures_chantier.charger_definitions()
    wcts = synthese.wcts_uniques(faits_chantier)
    marges: list[tuple[dict[str, Any], Decimal]] = []
    ecarts: list[tuple[dict[str, Any], Decimal]] = []
    utilises_marge: list[dict[str, Any]] = []
    utilises_ecart: list[dict[str, Any]] = []
    raisons: Counter[str] = Counter()
    for wct in wcts:
        faits = mesures_chantier.assembler_faits(wct["wct_id"], faits_chantier)
        if faits is None:  # pragma: no cover - l'identifiant vient d'un fait wct
            continue
        lues = {m["metric_id"]: m for m in mesures_chantier.mesurer_chantier(faits, definitions)}
        marge = lues["m8_marge_reelle_cad"]
        ecart = lues["m8_ecart_marge_cad"]
        if marge["statut"] == entonnoir.STATUT_CALCULEE:
            marges.append((wct, Decimal(marge["valeur"])))
            utilises_marge += [wct, faits["rentabilite"]]
        elif faits["rentabilite"] is None:
            raisons["aucune trace de rentabilité reçue de M5"] += 1
        else:
            raisons[
                mesures_chantier.raison_marge_reelle_non_qualifiee(faits["rentabilite"])
                or "marge réelle illisible ou absente de la trace de M5"
            ] += 1
        if ecart["statut"] == entonnoir.STATUT_CALCULEE:
            ecarts.append((wct, Decimal(ecart["valeur"])))
            utilises_ecart += [wct, faits["rentabilite"], faits["devis"]]
    return {
        "wcts": wcts,
        "marges": marges,
        "ecarts": ecarts,
        "faits_marge": utilises_marge,
        "faits_ecart": utilises_ecart,
        "raisons_sans_marge": dict(sorted(raisons.items())),
    }


def _raison_sans_marge(analyse: dict[str, Any]) -> str:
    """Pourquoi M5 n'a chiffré aucune marge : ce que M5 et les gardes de M8 en disent, chantier par chantier."""
    detail = "; ".join(f"{n} chantier(s) : {raison}" for raison, n in analyse["raisons_sans_marge"].items())
    return (
        "aucune marge réelle chiffrée par M5 pour les chantiers terminés (" + (detail or "rien livré par le bus") + ")"
    )


def _couverture_chantiers(couverts: int, attendus: int, objet: str) -> dict[str, Any] | None:
    if couverts == attendus:
        return None
    return _partielle(
        couverts,
        attendus,
        f"{couverts} chantier(s) sur {attendus} terminé(s) {objet} ; les {attendus - couverts} autre(s) n'y sont pas",
    )


def _chantiers_marge_reelle(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    analyse = _analyser_chantiers(reg["chantier"])
    wcts, marges = analyse["wcts"], analyse["marges"]
    if not wcts:
        return _non_calculable([_MANQUE_WCT])
    manque_m5 = _manque("m5.rentabilite_chantier", "M5 (m5.rentabilite_chantier)", _raison_sans_marge(analyse))
    if not marges:
        return _non_calculable([manque_m5], {"n_chantiers_termines": len(wcts)}, synthese.plus_recent_completion(wcts))
    entrees = {
        "n_chantiers_termines": len(wcts),
        "n_marge_chiffree": len(marges),
        "n_sans_marge_chiffree": len(wcts) - len(marges),
        "empreinte_faits": _empreinte_faits(analyse["faits_marge"]),
    }
    instant = synthese.plus_recent_completion([wct for wct, _ in marges])
    return (
        str(len(marges)),
        entrees,
        [],
        instant,
        _couverture_chantiers(len(marges), len(wcts), "ont une marge réelle chiffrée"),
        None,
    )


def _marge_reelle_cumulee_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    analyse = _analyser_chantiers(reg["chantier"])
    wcts, marges = analyse["wcts"], analyse["marges"]
    if not wcts:
        return _non_calculable([_MANQUE_WCT])
    if not marges:
        return _non_calculable(
            [_manque("m5.rentabilite_chantier", "M5 (m5.rentabilite_chantier)", _raison_sans_marge(analyse))],
            {"n_chantiers_termines": len(wcts)},
            synthese.plus_recent_completion(wcts),
        )
    somme = sum((valeur for _, valeur in marges), Decimal(0))
    entrees = {
        "n_chantiers_termines": len(wcts),
        "n_marge_chiffree": len(marges),
        "n_sans_marge_chiffree": len(wcts) - len(marges),
        "empreinte_faits": _empreinte_faits(analyse["faits_marge"]),
    }
    instant = synthese.plus_recent_completion([wct for wct, _ in marges])
    return (
        nombres.texte_decimal(somme),
        entrees,
        [],
        instant,
        _couverture_chantiers(len(marges), len(wcts), "ont une marge réelle chiffrée"),
        None,
    )


def _chantiers_en_perte(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    analyse = _analyser_chantiers(reg["chantier"])
    wcts, marges = analyse["wcts"], analyse["marges"]
    if not wcts:
        return _non_calculable([_MANQUE_WCT])
    if not marges:
        return _non_calculable(
            [_manque("m5.rentabilite_chantier", "M5 (m5.rentabilite_chantier)", _raison_sans_marge(analyse))],
            {"n_chantiers_termines": len(wcts)},
            synthese.plus_recent_completion(wcts),
        )
    en_perte = [wct for wct, valeur in marges if valeur < 0]
    entrees = {
        "n_chantiers_termines": len(wcts),
        "n_marge_chiffree": len(marges),
        "n_sans_marge_chiffree": len(wcts) - len(marges),
        "empreinte_faits": _empreinte_faits(analyse["faits_marge"]),
    }
    instant = synthese.plus_recent_completion([wct for wct, _ in marges])
    return (
        str(len(en_perte)),
        entrees,
        [],
        instant,
        _couverture_chantiers(len(marges), len(wcts), "ont une marge réelle chiffrée"),
        None,
    )


def _ecart_marge_cumule_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    analyse = _analyser_chantiers(reg["chantier"])
    wcts, marges, ecarts = analyse["wcts"], analyse["marges"], analyse["ecarts"]
    if not wcts:
        return _non_calculable([_MANQUE_WCT])
    if not ecarts:
        return _non_calculable(
            [
                _manque(
                    "m8_ecart_marge_cad",
                    "M5 (m5.rentabilite_chantier) et M3 (m3.devis_accepte)",
                    "aucun chantier terminé ne porte à la fois la marge réelle de M5 et le prix et le coût du "
                    "devis de M3",
                )
            ],
            {"n_chantiers_termines": len(wcts), "n_marge_chiffree": len(marges)},
            synthese.plus_recent_completion(wcts),
        )
    somme = sum((valeur for _, valeur in ecarts), Decimal(0))
    entrees = {
        "n_chantiers_termines": len(wcts),
        "n_chantiers_mesures": len(ecarts),
        "n_marge_chiffree_sans_prevu_de_m3": len(marges) - len(ecarts),
        "n_sans_marge_chiffree": len(wcts) - len(marges),
        "empreinte_faits": _empreinte_faits(analyse["faits_ecart"]),
    }
    instant = synthese.plus_recent_completion([wct for wct, _ in ecarts])
    return (
        nombres.texte_decimal(somme),
        entrees,
        [],
        instant,
        _couverture_chantiers(len(ecarts), len(wcts), "portent la marge réelle de M5 et le prévu de M3"),
        None,
    )


def _heures_sur_site_chantiers(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    wcts = synthese.wcts_uniques(reg["chantier"])
    if not wcts:
        return _non_calculable([_MANQUE_WCT])
    lisibles = [
        wct for wct in wcts if type(wct.get("duree_reelle_minutes")) is int and wct["duree_reelle_minutes"] >= 0
    ]
    if not lisibles:
        return _non_calculable(
            [
                _manque(
                    "duree_reelle_minutes",
                    "M4 (m4.travaux_termines)",
                    "aucune durée réelle lisible parmi les chantiers terminés",
                )
            ],
            {"n_chantiers_termines": len(wcts)},
            synthese.plus_recent_completion(wcts),
        )
    minutes = sum(Decimal(wct["duree_reelle_minutes"]) for wct in lisibles)
    entrees = {
        "n_chantiers_termines": len(wcts),
        "n_durees_lues": len(lisibles),
        "n_durees_illisibles": len(wcts) - len(lisibles),
        "minutes_total": int(minutes),
        "empreinte_faits": _empreinte_faits(lisibles),
    }
    couverture = None
    if len(lisibles) < len(wcts):
        couverture = _partielle(
            len(lisibles),
            len(wcts),
            f"{len(lisibles)} chantier(s) sur {len(wcts)} terminé(s) ont une durée lisible ; les "
            f"{len(wcts) - len(lisibles)} autre(s) n'y sont pas",
        )
    return (
        nombres.texte_decimal(minutes / _MINUTES_PAR_HEURE),
        entrees,
        [],
        synthese.plus_recent_completion(lisibles),
        couverture,
        None,
    )


# ---------------------------------------------------------------------------
# M5 : les constats comptables et le cash libre
# ---------------------------------------------------------------------------
_MANQUE_COMPTABLE = _manque(
    "m5.mesures_comptables_constatees",
    "M5 (m5.mesures_comptables_constatees)",
    "aucun constat des mesures comptables reçu : M5 n'en a publié aucun (m5_constater_mesures_comptables), ou rien "
    "livré par le bus",
)


def _creances(reg: dict[str, list[dict[str, Any]]], tranche: str | None) -> Resultat:
    """``tranche`` : ``None`` pour le total, ``"90+"`` pour la tranche de 90 jours et plus. Le constat est refusé s'il
    est incohérent (total différent de la somme des tranches) : ce n'est pas un recalcul, c'est une garde contre un
    constat
    forgé ou corrompu."""
    dernier = operations_recues.dernier_constat_comptable(reg["operations"])
    if dernier is None:
        return _non_calculable([_MANQUE_COMPTABLE])
    instant = synthese.jour_en_instant(dernier.get("date_reference"))
    creances = dernier.get("creances")
    total = nombres.decimal_lu(creances.get("total")) if isinstance(creances, dict) else None
    tranches = creances.get("par_tranche") if isinstance(creances, dict) else None
    lues = {nom: nombres.decimal_lu(valeur) for nom, valeur in tranches.items()} if isinstance(tranches, dict) else {}
    if total is None or not lues or any(valeur is None for valeur in lues.values()):
        return _non_calculable(
            [
                _manque(
                    "creances", "M5 (m5.mesures_comptables_constatees)", "constat illisible : total ou tranches absents"
                )
            ],
            {"date_reference": dernier.get("date_reference")},
            instant,
        )
    if sum(lues.values(), Decimal(0)) != total:
        return _non_calculable(
            [
                _manque(
                    "creances",
                    "M5 (m5.mesures_comptables_constatees)",
                    "constat incohérent : le total des créances n'est pas la somme de ses tranches d'âge ; "
                    "M8 ne corrige rien, M5 doit refaire son constat",
                )
            ],
            {"date_reference": dernier.get("date_reference")},
            instant,
        )
    valeur = creances["total"] if tranche is None else creances["par_tranche"][tranche]
    entrees = {
        "date_reference": dernier["date_reference"],
        "version_donnees": dernier["version_donnees"],
        "nombre_de_creances": creances.get("nombre"),
        "empreinte_faits": _empreinte_faits([dernier]),
    }
    return valeur, entrees, [], instant, None, None


def _creances_ouvertes_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    return _creances(reg, None)


def _creances_90_jours_plus_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    return _creances(reg, "90+")


def _composante_du_cash_libre(reg: dict[str, list[dict[str, Any]]], composante_id: str, libelle: str) -> Resultat:
    """Une composante du dernier constat du cash libre de M5 (le solde, ou une des obligations retranchées), reprise
    telle quelle. Si M5 n'a pas pu la chiffrer : non calculable, avec les codes de M5 et le plancher qu'il connaît
    (un repère, jamais le total)."""
    source = "M5 (m5.cash_libre_constate)"
    constat = cash_libre.constat_courant(reg["cash_libre"])
    if constat is None:
        return _non_calculable([_manque("m5.cash_libre_constate", source, "aucun constat du cash libre reçu")])
    instant = synthese.jour_en_instant(constat.get("date_reference"))
    composantes = [
        constat.get("solde"),
        *(constat.get("composantes") if isinstance(constat.get("composantes"), list) else []),
    ]
    composante = next((c for c in composantes if isinstance(c, dict) and c.get("id") == composante_id), None)
    entrees = {"date_reference": constat.get("date_reference"), "sequence": constat.get("sequence")}
    if composante is None:
        return _non_calculable(
            [_manque(composante_id, source, f"la composante « {libelle} » est absente du constat")], entrees, instant
        )
    montant = composante.get("montant_cad")
    if composante.get("statut") == "CALCULE" and nombres.decimal_lu(montant) is not None:
        return montant, {**entrees, "empreinte_faits": _empreinte_faits([constat])}, [], instant, None, None
    codes = [
        str(m.get("code"))
        for m in constat.get("manque") or []
        if isinstance(m, dict) and m.get("composante") == composante_id
    ]
    raison = f"M5 n'a pas pu chiffrer {libelle}" + (f" (codes de M5 : {', '.join(codes)})" if codes else "")
    plancher = composante.get("plancher_cad")
    if plancher is not None:
        entrees["plancher_cad"] = plancher
        raison += f" ; le plancher connu ({plancher}) est un repère, jamais le total"
    return _non_calculable([_manque(composante_id, source, raison)], entrees, instant)


def _comptes_a_payer_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    return _composante_du_cash_libre(reg, "comptes_a_payer", "les comptes à payer")


def _solde_tresorerie_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    return _composante_du_cash_libre(reg, "solde", "le solde")


def _taxes_a_remettre_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    return _composante_du_cash_libre(reg, "taxes_a_remettre", "les taxes à remettre")


def _ecritures_en_attente(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    """Les brouillons d'écriture que M5 a préparés et qu'aucune personne n'a encore validés (N4), tels que le dernier
    constat des mesures comptables les compte : un retard de validation, jamais une erreur."""
    dernier = operations_recues.dernier_constat_comptable(reg["operations"])
    if dernier is None:
        return _non_calculable([_MANQUE_COMPTABLE])
    instant = synthese.jour_en_instant(dernier.get("date_reference"))
    nombre = dernier.get("brouillons_en_attente")
    if type(nombre) is not int or nombre < 0:
        return _non_calculable(
            [
                _manque(
                    "brouillons_en_attente",
                    "M5 (m5.mesures_comptables_constatees)",
                    "le compte du constat est illisible",
                )
            ],
            {"date_reference": dernier.get("date_reference")},
            instant,
        )
    entrees = {
        "date_reference": dernier["date_reference"],
        "version_donnees": dernier["version_donnees"],
        "empreinte_faits": _empreinte_faits([dernier]),
    }
    return str(nombre), entrees, [], instant, None, None


# ---------------------------------------------------------------------------
# M7 : dépenses publicitaires, conversions, anomalies
# ---------------------------------------------------------------------------
_SOURCE_DEPENSES = "M7 (m7.depenses_marketing_constatees)"


def _derniers_releves(faits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """La dernière révision de chaque relevé : une révision REMPLACE la précédente, elle ne s'y additionne jamais."""
    dernieres: dict[str, dict[str, Any]] = {}
    for fait in faits:
        identifiant = fait.get("releve_id")
        revision = fait.get("revision")
        if not isinstance(identifiant, str) or type(revision) is not int:
            continue
        actuelle = dernieres.get(identifiant)
        if actuelle is None or revision > actuelle["revision"]:
            dernieres[identifiant] = fait
    return list(dernieres.values())


def _fenetre_source_s(canaux: set[str], signaux: list[dict[str, Any]]) -> tuple[int | None, list[str]]:
    """La fenêtre (secondes) que M7 déclare pour les sources publicitaires des canaux présents : la plus stricte,
    d'après
    la dernière lecture de chaque source. Les canaux dont M7 n'a donné aucun signal sont dits, jamais devinés."""
    derniers: dict[str, tuple[Any, dict[str, Any]]] = {}
    for signal in signaux:
        instant = entonnoir.instant_lu(signal.get("derniere_lecture_reussie_le"))
        if instant is None or signal.get("fictif") is True:
            continue
        actuel = derniers.get(signal.get("source"))
        if actuel is None or instant >= actuel[0]:
            derniers[signal.get("source")] = (instant, signal)
    fenetres = []
    sans_fenetre = []
    for canal in sorted(canaux):
        signal = derniers.get(_SOURCE_DU_CANAL.get(canal, ""))
        heures = signal[1].get("fraicheur_fenetre_h") if signal is not None else None
        if type(heures) is int and heures >= 1:
            fenetres.append(heures * 3600)
        else:
            sans_fenetre.append(canal)
    return (min(fenetres) if fenetres else None), sans_fenetre


def _releves_depense_pub_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    operations = reg["operations"]
    releves = _derniers_releves(_de_type(operations, operations_recues.TYPE_DEPENSE))
    if not releves:
        return _non_calculable(
            [
                _manque(
                    "m7.depenses_marketing_constatees",
                    _SOURCE_DEPENSES,
                    "aucun relevé de dépense publicitaire reçu : M7 n'en a inscrit aucun (connecteur "
                    "publicitaire non branché ou "
                    "rien livré par le bus)",
                )
            ]
        )
    periodes: dict[str, list[tuple[date, date, dict[str, Any]]]] = {}
    illisibles = []
    for releve in releves:
        debut, fin = _jour(releve.get("periode_debut")), _jour(releve.get("periode_fin"))
        if debut is None or fin is None or fin < debut or (fin - debut).days >= _JOURS_PAR_RELEVE_MAX:
            illisibles.append(str(releve.get("releve_id")))
            continue
        periodes.setdefault(str(releve.get("canal")), []).append((debut, fin, releve))
    if illisibles:
        return _non_calculable(
            [
                _manque(
                    "periode",
                    _SOURCE_DEPENSES,
                    f"{len(illisibles)} relevé(s) dont la période est illisible ou inversée : "
                    f"{_cites(sorted(illisibles))}",
                )
            ],
            {"n_releves": len(releves)},
        )
    bases = sorted({str(releve.get("base_taxes")) for releve in releves})
    if len(bases) != 1:
        return _non_calculable(
            [
                _manque(
                    "base_taxes",
                    _SOURCE_DEPENSES,
                    "bases de taxes différentes entre les relevés ("
                    + ", ".join(bases)
                    + ") : aucune somme n'est faite",
                )
            ],
            {"n_releves": len(releves)},
        )
    jours_sans_releve = 0
    par_canal: dict[str, dict[str, Any]] = {}
    for canal, lignes in sorted(periodes.items()):
        lignes.sort(key=lambda ligne: (ligne[0], ligne[1]))
        manquants = 0
        for (_, fin_precedente, _), (debut_suivant, _, _) in zip(lignes, lignes[1:], strict=False):
            if debut_suivant <= fin_precedente:
                return _non_calculable(
                    [
                        _manque(
                            "periode",
                            _SOURCE_DEPENSES,
                            f"deux relevés du canal {canal} se chevauchent : la somme compterait des jours "
                            "deux fois, aucune "
                            "somme n'est faite",
                        )
                    ],
                    {"n_releves": len(releves)},
                )
            manquants += (debut_suivant - fin_precedente).days - 1
        jours_sans_releve += manquants
        par_canal[canal] = {
            "releves": len(lignes),
            "du": lignes[0][0].isoformat(),
            "au": lignes[-1][1].isoformat(),
            "jours_sans_releve": manquants,
        }
    montants = [nombres.decimal_lu(releve.get("montant_cad")) for releve in releves]
    if any(montant is None for montant in montants):
        return _non_calculable([_manque("montant_cad", _SOURCE_DEPENSES, "un relevé porte un montant illisible")])
    somme = sum((m for m in montants if m is not None), Decimal(0))
    fenetre, sans_fenetre = _fenetre_source_s(set(par_canal), _de_type(operations, operations_recues.TYPE_SIGNAUX))
    illisibles_le = sum(1 for releve in releves if entonnoir.instant_lu(releve.get("releve_le")) is None)
    entrees = {
        "n_releves": len(releves),
        "base_taxes": bases[0],
        "par_canal": par_canal,
        "jours_sans_releve": jours_sans_releve,
        "n_releve_le_illisibles": illisibles_le,
        "canaux_sans_fenetre_de_m7": sans_fenetre,
        "empreinte_faits": _empreinte_faits(releves),
    }
    couverture = None
    if jours_sans_releve:
        couverture = {
            "etat": "partielle",
            "jours_sans_releve": jours_sans_releve,
            "raison": f"{jours_sans_releve} jour(s) sans relevé à l'intérieur de la période couverte : "
            "ce ne sont pas des zéros",
        }
    instant = _plus_recent([releve.get("releve_le") for releve in releves])
    return nombres.texte_decimal(somme), entrees, [], instant, couverture, fenetre


def _conversions_hors_ligne(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    conversions = _uniques(_de_type(reg["operations"], operations_recues.TYPE_CONVERSION), "conversion_id")
    if not conversions:
        return _non_calculable(
            [
                _manque(
                    "m7.conversion_hors_ligne_importee",
                    "M7 (m7.conversion_hors_ligne_importee)",
                    "aucune conversion hors ligne reçue : M8 ne peut pas distinguer « aucune issue » de « rien livré »",
                )
            ]
        )
    entrees = {
        "par_type": dict(sorted(Counter(str(c.get("type")) for c in conversions).items())),
        "n_sans_source_normalisee": sum(1 for c in conversions if c.get("source_normalisee") is not True),
        "empreinte_faits": _empreinte_faits(conversions),
    }
    return str(len(conversions)), entrees, [], _plus_recent([c.get("importee_le") for c in conversions]), None, None


def _anomalies_depense_critiques(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    toutes = _uniques(_de_type(reg["operations"], operations_recues.TYPE_ANOMALIE), "anomalie_id")
    reelles = [a for a in toutes if a.get("fictif") is not True]
    if not reelles:
        return _non_calculable(
            [
                _manque(
                    "m7.anomalie_depense_detectee",
                    "M7 (m7.anomalie_depense_detectee)",
                    "aucune anomalie de dépense réelle reçue : M8 ne peut pas distinguer « aucune anomalie » "
                    "de « rien livré »",
                )
            ],
            {"n_fictifs_ignores": len(toutes)},
        )
    critiques = [a for a in reelles if a.get("severite") == _SEVERITE_CRITIQUE]
    entrees = {
        "n_anomalies_reelles": len(reelles),
        "n_fictifs_ignores": len(toutes) - len(reelles),
        "empreinte_faits": _empreinte_faits(critiques),
    }
    return str(len(critiques)), entrees, [], _plus_recent([a.get("detectee_le") for a in reelles]), None, None


def _ecart_depense_pub_comptabilisee_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    """Écart de définition entre M7 (relevés) et M5 (dépense comptabilisée) : aucun événement ne publie la dépense
    comptabilisée, la mesure est donc non calculable PAR CONSTRUCTION et le dit (décision à prendre, pas un oubli)."""
    return _non_calculable(
        [
            _manque(
                "charges_marketing_comptabilisees",
                "M5 (aucun événement ne les publie)",
                "M5 range un brouillon de charge pour chaque relevé de M7 (validation humaine N4) mais ne "
                "publie aucun total "
                "comptabilisé, et M8 ne lit pas le grand livre de M5 : l'écart entre les relevés et la "
                "dépense comptabilisée ne "
                "peut pas être mesuré ; décision requise (voir M8-ENTREPOT-SOURCES.md)",
            )
        ]
    )


# ---------------------------------------------------------------------------
# M6 : réceptions ; M1 et M2 : demandes
# ---------------------------------------------------------------------------
def _receptions(reg: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    vus: set[tuple[Any, Any]] = set()
    uniques = []
    for fait in _de_type(reg["operations"], operations_recues.TYPE_RECEPTION):
        cle = (fait.get("po_id"), fait.get("hash_maillon"))
        if all(isinstance(partie, str) and partie for partie in cle) and cle not in vus:
            vus.add(cle)
            uniques.append(fait)
    return uniques


_MANQUE_RECEPTION = _manque(
    "m6.reception_enregistree",
    "M6 (m6.reception_enregistree)",
    "aucune réception de matériaux reçue : M6 n'en a enregistré aucune, ou rien livré par le bus",
)


def _receptions_materiaux(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    receptions = _receptions(reg)
    if not receptions:
        return _non_calculable([_MANQUE_RECEPTION])
    entrees = {
        "n_bons_de_commande": len({r["po_id"] for r in receptions}),
        "empreinte_faits": _empreinte_faits(receptions),
    }
    return (
        str(len(receptions)),
        entrees,
        [],
        _plus_recent([r.get("horodatage_reception") for r in receptions]),
        None,
        None,
    )


def _receptions_avec_ecart(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    receptions = _receptions(reg)
    if not receptions:
        return _non_calculable([_MANQUE_RECEPTION])
    avec_ecart = [r for r in receptions if r.get("verdict_reception") != _VERDICT_CONFORME]
    entrees = {
        "n_receptions": len(receptions),
        "par_verdict": dict(sorted(Counter(str(r.get("verdict_reception")) for r in receptions).items())),
        "empreinte_faits": _empreinte_faits(receptions),
    }
    return (
        str(len(avec_ecart)),
        entrees,
        [],
        _plus_recent([r.get("horodatage_reception") for r in receptions]),
        None,
        None,
    )


def _commandes_envoyees(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    commandes = _uniques(_de_type(reg["operations"], operations_recues.TYPE_COMMANDE), "po_id")
    if not commandes:
        return _non_calculable(
            [
                _manque(
                    "m1.commande_courriel_envoyee",
                    "M1 (m1.commande_courriel_envoyee)",
                    "aucune commande envoyée reçue : aucun bon de commande n'est parti après l'approbation du sas, ou "
                    "rien livré par le bus",
                )
            ]
        )
    entrees = {"empreinte_faits": _empreinte_faits(commandes)}
    return str(len(commandes)), entrees, [], _plus_recent([c.get("envoye_le") for c in commandes]), None, None


def _demandes_m1(reg: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return _uniques(_de_type(reg["contenus"], contenus.TYPE_LEAD_M1), "lead_id")


_MANQUE_M1 = _manque(
    "m1.lead_qualifie",
    "M1 (m1.lead_qualifie)",
    "aucune demande qualifiée reçue de M1 : rien qualifié, ou rien livré par le bus",
)


def _demandes_qualifiees_m1(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    demandes = _demandes_m1(reg)
    if not demandes:
        return _non_calculable([_MANQUE_M1])
    entrees = {"empreinte_faits": _empreinte_faits(demandes)}
    return str(len(demandes)), entrees, [], _plus_recent([d.get("horodatage") for d in demandes]), None, None


def _demandes_m1_sans_lead_m2(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    demandes = _demandes_m1(reg)
    leads = _uniques(_de_type(reg["entonnoir"], entonnoir.TYPE_LEAD_RECU), "lead_id")
    if not demandes:
        return _non_calculable([_MANQUE_M1])
    if not leads:
        return _non_calculable(
            [
                _manque(
                    "m2.client_associe",
                    "M2 (m2.client_associe)",
                    "aucun lead reçu de M2 : M8 ne peut pas dire si M2 n'a rien reçu ou si le bus n'a rien "
                    "livré, l'écart ne serait "
                    "que la liste entière des demandes de M1",
                )
            ],
            {"n_demandes_m1": len(demandes)},
        )
    ids_m1 = {d["lead_id"] for d in demandes}
    ids_m2 = {lead["lead_id"] for lead in leads}
    entrees = {
        "n_demandes_m1": len(ids_m1),
        "n_leads_m2": len(ids_m2),
        "n_demandes_m1_avec_lead_m2": len(ids_m1 & ids_m2),
        "n_leads_m2_sans_demande_m1": len(ids_m2 - ids_m1),
        "empreinte_faits": _empreinte_faits([*demandes, *leads]),
    }
    instant = _plus_recent([d.get("horodatage") for d in demandes] + [lead.get("horodatage") for lead in leads])
    return str(len(ids_m1 - ids_m2)), entrees, [], instant, None, None


_CALCULS = {
    "m8_chantiers_marge_reelle": _chantiers_marge_reelle,
    "m8_marge_reelle_cumulee_cad": _marge_reelle_cumulee_cad,
    "m8_chantiers_en_perte": _chantiers_en_perte,
    "m8_ecart_marge_cumule_cad": _ecart_marge_cumule_cad,
    "m8_creances_ouvertes_cad": _creances_ouvertes_cad,
    "m8_creances_90_jours_plus_cad": _creances_90_jours_plus_cad,
    "m8_ecritures_en_attente": _ecritures_en_attente,
    "m8_comptes_a_payer_cad": _comptes_a_payer_cad,
    "m8_solde_tresorerie_cad": _solde_tresorerie_cad,
    "m8_taxes_a_remettre_cad": _taxes_a_remettre_cad,
    "m8_releves_depense_pub_cad": _releves_depense_pub_cad,
    "m8_conversions_hors_ligne": _conversions_hors_ligne,
    "m8_anomalies_depense_critiques": _anomalies_depense_critiques,
    "m8_ecart_depense_pub_comptabilisee_cad": _ecart_depense_pub_comptabilisee_cad,
    "m8_heures_sur_site_chantiers": _heures_sur_site_chantiers,
    "m8_commandes_envoyees": _commandes_envoyees,
    "m8_receptions_materiaux": _receptions_materiaux,
    "m8_receptions_avec_ecart": _receptions_avec_ecart,
    "m8_demandes_qualifiees_m1": _demandes_qualifiees_m1,
    "m8_demandes_m1_sans_lead_m2": _demandes_m1_sans_lead_m2,
}


def mesurer(registres: dict[str, list[dict[str, Any]]], definitions: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Les mesures interdépartements, une par métrique du registre, dans l'ordre du registre. ``registres`` porte les
    cinq registres de M8 (``chantier``, ``entonnoir``, ``contenus``, ``cash_libre``, ``operations``). Une métrique sans
    calcul est non calculable, nommément."""
    mesures = []
    for metric_id, definition in definitions.items():
        calcul = _CALCULS.get(metric_id)
        if calcul is None:
            valeur, entrees, manque, instant, couverture, fenetre = _non_calculable(
                [_manque("calcul", "M8", "aucun calcul enregistré pour cette métrique")]
            )
        else:
            valeur, entrees, manque, instant, couverture, fenetre = calcul(registres)
        mesure = entonnoir.construire_mesure(metric_id, definition, valeur, entrees, manque)
        mesure["dernier_fait_le"] = instant
        mesure["fenetre_source_s"] = fenetre
        if valeur is None:
            mesure["couverture"] = {"etat": "inconnue"}
        elif couverture is None:
            mesure["couverture"] = {"etat": "complete"}
        else:
            mesure["couverture"] = couverture
            mesure["detail"] = f"couverture partielle : {couverture['raison']}"
        mesures.append(mesure)
    return mesures


__all__ = ["charger_definitions", "mesurer"]
