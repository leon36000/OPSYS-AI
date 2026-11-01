"""Mesures d'entreprise tirées des RÉSUMÉS que les départements publient pour M8 (phase 2 : D1 à D3, D5, D6 de
``docs/architecture/M8-ENTREPOT-SOURCES.md``).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge (les instants viennent des faits reçus). Même patron et
mêmes règles que ``mesures_interdepartements`` (dont il partage les helpers par ``mesures_communes``) :

1. TEL QUEL. Un total, un compte ou un montant que le département propriétaire a arrêté passe du fait reçu à la mesure
   sans être refait. Les seules opérations de M8 sont des SOMMES de faits de même nature (en ``Decimal``), deux rapports
   (la part des heures planifiées, le coût par lead) et un écart de définition NOMMÉ ; chacune dit ses entrées.
2. UNE ABSENCE N'EST JAMAIS UN ZÉRO. Un constat « non calculable » du propriétaire (capacité d'une semaine sans profil,
taux
   de conversion sous le seuil de M2, plaintes « aucune déclarée par la source ») donne une mesure non calculable qui
   cite
   ses causes ; un jour, une semaine ou une source qu'aucun fait ne couvre est dit (couverture partielle), jamais compté
   à zéro.
3. LA VERSION QUI FAIT FOI EST LA DERNIÈRE PUBLIÉE (``publie_le``, donné par le bus), pas la dernière livrée : l'ordre
de
   livraison n'est pas garanti. Exceptions : la dépense comptabilisée (le plus grand ``sequence`` de M5) et l'état d'une
   facture (le plus avancé).
4. LE DÉPARTEMENT SOURCE DIT SA FRAÎCHEUR. Le dernier fait d'une mesure est l'instant du constat (``constate_le``) ou
le jour
   qu'il porte ; la fenêtre que M7 déclare pour ses sources s'applique quand la mesure en dépend.

Aucune de ces mesures ne porte une personne, un client, un fournisseur, un article ou un nom de campagne : les résumés
n'en
ont pas.
"""

from __future__ import annotations

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import entonnoir, nombres, operations_recues, synthese
from .mesures_communes import (
    Resultat,
    de_type,
    dernier_par_publication,
    empreinte_faits,
    fenetre_source_s,
    jour,
    manque,
    non_calculable,
    ordre_publication,
    partielle,
    plus_recent,
)

_CENT = Decimal(100)
_BASE_COMPTABILISEE = "HORS_TAXES"
_STATUTS_FACTURE_RANG = {"ENVOYEE": 1, "PAYEE": 2, "ANNULEE": 2}
_STATUT_ANNULEE = "ANNULEE"
_PORTEE_DATEE = "journees_datees_seulement"
_ETAT_CONNUE = "CONNUE"
_ETAT_AUCUNE = "AUCUNE_DECLAREE_PAR_SOURCE"
_SOURCES_RECHERCHE = ("search_console", "bing_webmaster")
_SOURCES_AUDIENCE = ("umami", "matomo")
_JOURS_PAR_RELEVE_MAX = 3660

_SOURCE_M5_DEPENSE = "M5 (m5.depense_publicitaire_constatee)"
_SOURCE_M5_FACTURES = "M5 (m5.facture_emise_constatee)"
_SOURCE_M7_PERFORMANCE = "M7 (m7.performance_signaux_constatee)"
_SOURCE_M7_DEPENSES = "M7 (m7.depenses_marketing_constatees)"
_SOURCE_M4 = "M4 (m4.capacite_equipe_constatee)"
_SOURCE_M2 = "M2 (m2.pipeline_constate)"
_SOURCE_M6 = "M6 (m6.disponibilite_constatee)"
_SOURCE_M1 = "M1 (m1.plaintes_constatees)"


def _decimal(valeur: Any) -> Decimal | None:
    return nombres.decimal_lu(valeur)


def _jour_instant(texte: Any) -> str | None:
    return synthese.jour_en_instant(texte)


def _dernier_jour_emis(factures: list[dict[str, Any]]) -> str | None:
    """L'instant (début du jour d'émission, le plus ancien possible) de la facture émise le plus récemment."""
    jours = [_jour_instant(f.get("emise_le")) for f in factures]
    return plus_recent([j for j in jours if j is not None])


def _plus_ancien(instants: list[str | None]) -> str | None:
    """Le plus ANCIEN de plusieurs instants lisibles, ``None`` si l'un d'eux est illisible : une mesure bâtie sur deux
    sources n'est pas plus fraîche que la moins fraîche (jamais plus récente qu'elle n'est)."""
    lus = [(entonnoir.instant_lu(texte), texte) for texte in instants]
    if not lus or any(instant is None for instant, _ in lus):
        return None
    return min(lus, key=lambda paire: paire[0])[1]


# ---------------------------------------------------------------------------
# M5 (D1) : dépense publicitaire comptabilisée, et son écart avec les relevés de M7
# ---------------------------------------------------------------------------
_MANQUE_DEPENSE_COMPTABILISEE = manque(
    "m5.depense_publicitaire_constatee",
    _SOURCE_M5_DEPENSE,
    "aucun constat de la dépense publicitaire comptabilisée reçu : M5 n'en a publié aucun "
    "(m5_constater_depense_publicitaire), ou rien livré par le bus",
)


def _dernier_constat_depense(operations: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Le dernier constat de M5 : le plus grand ``sequence`` (le rang du constat dans le registre de M5, qui survit à un
    retour à une version antérieure des données), puis la publication la plus récente, puis le dernier reçu."""
    constats = [
        (indice, fait)
        for indice, fait in enumerate(operations)
        if fait.get("type_entree") == operations_recues.TYPE_DEPENSE_COMPTABILISEE
    ]
    lisibles = [
        (i, f) for i, f in constats if type(f.get("sequence")) is int and not isinstance(f.get("sequence"), bool)
    ]
    if not lisibles:
        return None
    return max(lisibles, key=lambda paire: (paire[1]["sequence"], *ordre_publication(paire[1], paire[0])))[1]


def _depense_comptabilisee_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    dernier = _dernier_constat_depense(reg["operations"])
    if dernier is None:
        return non_calculable([_MANQUE_DEPENSE_COMPTABILISEE])
    instant = _jour_instant(dernier.get("date_reference"))
    montant = _decimal(dernier.get("comptabilise_cad"))
    brouillons_cad = _decimal(dernier.get("brouillons_en_attente_cad"))
    entrees = {
        "periode_debut": dernier.get("periode_debut"),
        "periode_fin": dernier.get("periode_fin"),
        "date_reference": dernier.get("date_reference"),
        "sequence": dernier.get("sequence"),
        "version_donnees": dernier.get("version_donnees"),
        "base_taxes": dernier.get("base_taxes"),
        "ecritures_definitives": dernier.get("ecritures_definitives"),
        "brouillons_en_attente": dernier.get("brouillons_en_attente"),
        "brouillons_en_attente_cad": dernier.get("brouillons_en_attente_cad"),
    }
    if montant is None or brouillons_cad is None:
        return non_calculable(
            [
                manque(
                    "comptabilise_cad",
                    _SOURCE_M5_DEPENSE,
                    "constat illisible : montant comptabilisé ou brouillons absents",
                )
            ],
            entrees,
            instant,
        )
    entrees["empreinte_faits"] = empreinte_faits([dernier])
    en_attente = dernier.get("brouillons_en_attente")
    couverture = None
    if type(en_attente) is int and en_attente > 0:
        definitives = dernier.get("ecritures_definitives") if type(dernier.get("ecritures_definitives")) is int else 0
        couverture = partielle(
            definitives,
            definitives + en_attente,
            f"{en_attente} brouillon(s) de charge attendent la validation d'une personne : ils ne sont pas encore "
            "comptabilisés (leur montant est dans les entrées)",
        )
    return nombres.texte_decimal(montant), entrees, [], instant, couverture, None


def _derniers_releves(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """La dernière révision de chaque relevé de M7 : une révision REMPLACE la précédente, elle ne s'y ajoute pas."""
    dernieres: dict[str, dict[str, Any]] = {}
    for fait in de_type(operations, operations_recues.TYPE_DEPENSE):
        identifiant, revision = fait.get("releve_id"), fait.get("revision")
        if not isinstance(identifiant, str) or type(revision) is not int:
            continue
        actuelle = dernieres.get(identifiant)
        if actuelle is None or revision > actuelle["revision"]:
            dernieres[identifiant] = fait
    return list(dernieres.values())


def _ecart_depense_pub_comptabilisee_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    """ÉCART DE DÉFINITION entre M7 (somme des relevés de la période du constat) et M5 (ce que le grand livre en a
    comptabilisé). Positif : les relevés dépassent le comptabilisé. Seuls les relevés HORS_TAXES dont la période tient
    ENTIÈRE dans celle du constat sont comparés : M5 ne comptabilise que les relevés hors taxes (un relevé
    TAXES_INCLUSES
    attend une décision fiscale), et un relevé à cheval sur la période n'est ni dedans ni dehors. Ce qui est écarté est
    dit (couverture partielle)."""
    operations = reg["operations"]
    dernier = _dernier_constat_depense(operations)
    if dernier is None:
        return non_calculable([_MANQUE_DEPENSE_COMPTABILISEE])
    releves = _derniers_releves(operations)
    if not releves:
        return non_calculable(
            [
                manque(
                    "m7.depenses_marketing_constatees",
                    _SOURCE_M7_DEPENSES,
                    "aucun relevé de dépense publicitaire reçu de M7 : il n'y a rien à comparer à ce que M5 a "
                    "comptabilisé",
                )
            ],
            {"periode_debut": dernier.get("periode_debut"), "periode_fin": dernier.get("periode_fin")},
        )
    debut, fin = jour(dernier.get("periode_debut")), jour(dernier.get("periode_fin"))
    comptabilise = _decimal(dernier.get("comptabilise_cad"))
    entrees_constat = {
        "periode_debut": dernier.get("periode_debut"),
        "periode_fin": dernier.get("periode_fin"),
        "sequence": dernier.get("sequence"),
        "comptabilise_cad": dernier.get("comptabilise_cad"),
        "brouillons_en_attente": dernier.get("brouillons_en_attente"),
        "brouillons_en_attente_cad": dernier.get("brouillons_en_attente_cad"),
    }
    if debut is None or fin is None or fin < debut or comptabilise is None:
        return non_calculable(
            [manque("periode", _SOURCE_M5_DEPENSE, "constat illisible : période ou montant comptabilisé absents")],
            entrees_constat,
            _jour_instant(dernier.get("date_reference")),
        )
    comparables: list[dict[str, Any]] = []
    a_cheval: list[str] = []
    hors_periode = 0
    taxes_incluses = 0
    illisibles: list[str] = []
    for releve in releves:
        d, f = jour(releve.get("periode_debut")), jour(releve.get("periode_fin"))
        montant = _decimal(releve.get("montant_cad"))
        if d is None or f is None or f < d or montant is None or (f - d).days >= _JOURS_PAR_RELEVE_MAX:
            illisibles.append(str(releve.get("releve_id")))
        elif f < debut or d > fin:
            hors_periode += 1
        elif d < debut or f > fin:
            a_cheval.append(str(releve.get("releve_id")))
        elif releve.get("base_taxes") != _BASE_COMPTABILISEE:
            taxes_incluses += 1
        else:
            comparables.append(releve)
    if illisibles:
        return non_calculable(
            [
                manque(
                    "periode",
                    _SOURCE_M7_DEPENSES,
                    f"{len(illisibles)} relevé(s) illisible(s) ou inversé(s) : aucun écart n'est calculé",
                )
            ],
            entrees_constat,
            _jour_instant(dernier.get("date_reference")),
        )
    if not comparables:
        return non_calculable(
            [
                manque(
                    "m7.depenses_marketing_constatees",
                    _SOURCE_M7_DEPENSES,
                    "aucun relevé HORS_TAXES de M7 ne tient dans la période du constat de M5 "
                    f"({dernier.get('periode_debut')} au {dernier.get('periode_fin')}) : "
                    f"{hors_periode} hors de la période, {len(a_cheval)} à cheval sur ses bornes, "
                    f"{taxes_incluses} taxes incluses",
                )
            ],
            entrees_constat,
            _jour_instant(dernier.get("date_reference")),
        )
    somme = sum((Decimal(str(_decimal(r.get("montant_cad")))) for r in comparables), Decimal(0))
    ecart = somme - comptabilise
    ecartes = len(a_cheval) + taxes_incluses
    brouillons = dernier.get("brouillons_en_attente")
    entrees = {
        **entrees_constat,
        "somme_releves_cad": nombres.texte_decimal(somme),
        "n_releves_compares": len(comparables),
        "n_releves_a_cheval": len(a_cheval),
        "n_releves_taxes_incluses": taxes_incluses,
        "n_releves_hors_periode": hors_periode,
        "empreinte_faits": empreinte_faits([dernier, *comparables]),
    }
    raisons = []
    en_attente = type(brouillons) is int and brouillons > 0
    if ecartes:
        raisons.append(
            f"{ecartes} relevé(s) ne sont pas comparés (à cheval sur les bornes de la période, ou TAXES_INCLUSES que "
            f"M5 ne "
            "comptabilise pas)"
        )
    if en_attente:
        compte = "" if ecartes else f"{brouillons} "
        raisons.append(
            f"{compte}brouillon(s) de charge attendent la validation d'une personne : ils expliquent une partie de "
            f"l'écart"
        )
    couverture = None
    if raisons:
        definitives = dernier.get("ecritures_definitives")
        if ecartes or not en_attente or type(definitives) is not int:
            couverture = partielle(len(comparables), len(comparables) + ecartes, " ; ".join(raisons))
        else:  # seuls des brouillons attendent : la couverture se compte en écritures (définitives sur définitives +
            # brouillons)
            couverture = partielle(definitives, definitives + brouillons, " ; ".join(raisons))
    canaux = {str(r.get("canal")) for r in comparables}
    fenetre, _ = fenetre_source_s(canaux, de_type(operations, operations_recues.TYPE_SIGNAUX))
    instant = _plus_ancien(
        [_jour_instant(dernier.get("date_reference")), plus_recent([r.get("releve_le") for r in comparables])]
    )
    return nombres.texte_decimal(ecart), entrees, [], instant, couverture, fenetre


# ---------------------------------------------------------------------------
# M5 (D3) : factures émises
# ---------------------------------------------------------------------------
_MANQUE_FACTURES = manque(
    "m5.facture_emise_constatee",
    _SOURCE_M5_FACTURES,
    "aucune facture émise reçue : M5 n'en a envoyé aucune (m5_constater_factures_emises), ou rien livré par le bus",
)


def _factures_courantes(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """L'état courant de chaque facture : le plus AVANCÉ (PAYEE ou ANNULEE après ENVOYEE), à égalité le plus récemment
    publié. Quel que soit l'ordre de livraison, une facture payée ne redevient pas « envoyée »."""
    meilleures: dict[str, tuple[tuple[int, Any, int], dict[str, Any]]] = {}
    for indice, fait in enumerate(operations):
        if fait.get("type_entree") != operations_recues.TYPE_FACTURE_EMISE:
            continue
        identifiant, rang_statut = fait.get("facture_id"), _STATUTS_FACTURE_RANG.get(str(fait.get("statut")))
        if not isinstance(identifiant, str) or not identifiant or rang_statut is None:
            continue
        cle = (rang_statut, *ordre_publication(fait, indice))
        actuelle = meilleures.get(identifiant)
        if actuelle is None or cle > actuelle[0]:
            meilleures[identifiant] = (cle, fait)
    return [fait for _, fait in meilleures.values()]


def _factures_emises(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    courantes = _factures_courantes(reg["operations"])
    if not courantes:
        return non_calculable([_MANQUE_FACTURES])
    actives = [f for f in courantes if f.get("statut") != _STATUT_ANNULEE]
    entrees = {
        "par_statut": dict(sorted(Counter(str(f.get("statut")) for f in courantes).items())),
        "n_annulees_apres_envoi": len(courantes) - len(actives),
        "empreinte_faits": empreinte_faits(courantes),
    }
    instant = _dernier_jour_emis(courantes)
    return str(len(actives)), entrees, [], instant, None, None


def _facturation_emise_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    courantes = _factures_courantes(reg["operations"])
    if not courantes:
        return non_calculable([_MANQUE_FACTURES])
    actives = [f for f in courantes if f.get("statut") != _STATUT_ANNULEE]
    avant = [_decimal(f.get("montant_avant_taxes_cad")) for f in actives]
    apres = [_decimal(f.get("montant_apres_taxes_cad")) for f in actives]
    taxes = [_decimal(f.get("total_taxes_cad")) for f in actives]
    instant = _dernier_jour_emis(courantes)
    if not actives:
        return non_calculable(
            [
                manque(
                    "factures_emises",
                    _SOURCE_M5_FACTURES,
                    "toutes les factures reçues sont annulées après l'envoi : aucun montant facturé",
                )
            ],
            {"n_annulees_apres_envoi": len(courantes)},
            instant,
        )
    if any(m is None for m in (*avant, *apres, *taxes)):
        return non_calculable(
            [manque("montant_avant_taxes_cad", _SOURCE_M5_FACTURES, "une facture porte un montant illisible")],
            {"n_factures": len(actives)},
            instant,
        )
    entrees = {
        "n_factures": len(actives),
        "n_annulees_apres_envoi": len(courantes) - len(actives),
        "total_taxes_cad": nombres.texte_decimal(sum((m for m in taxes if m is not None), Decimal(0))),
        "montant_apres_taxes_cad": nombres.texte_decimal(sum((m for m in apres if m is not None), Decimal(0))),
        "empreinte_faits": empreinte_faits(actives),
    }
    somme = sum((m for m in avant if m is not None), Decimal(0))
    return nombres.texte_decimal(somme), entrees, [], instant, None, None


# ---------------------------------------------------------------------------
# M7 : valeurs de signaux de performance (clics, impressions, visites du site)
# ---------------------------------------------------------------------------
def _performance_courante(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """La dernière version publiée de chaque (source, compte, période) réelle (jamais un compte de démonstration)."""
    meilleures: dict[tuple[Any, ...], tuple[tuple[Any, int], dict[str, Any]]] = {}
    for indice, fait in enumerate(operations):
        if fait.get("type_entree") != operations_recues.TYPE_PERFORMANCE or fait.get("fictif") is True:
            continue
        cle = (fait.get("source"), fait.get("compte_ref"), fait.get("periode_debut"), fait.get("periode_fin"))
        rang = ordre_publication(fait, indice)
        actuelle = meilleures.get(cle)
        if actuelle is None or rang > actuelle[0]:
            meilleures[cle] = (rang, fait)
    return [fait for _, fait in meilleures.values()]


def _total_signal(
    reg: dict[str, list[dict[str, Any]]], mesure: str, sources: tuple[str, ...], unique: bool
) -> Resultat:
    """Le total d'une mesure de signal (``clics``, ``impressions``, ``visites``) sur les sources qui la portent.
    ``unique`` : une seule source peut être sommée (deux outils d'audience se recoupent : leurs visites ne
    s'additionnent
    pas). Deux périodes d'une même source et d'un même compte qui se chevauchent : aucune somme (des jours compteraient
    deux fois)."""
    faits = [f for f in _performance_courante(reg["operations"]) if f.get("source") in sources]
    manque_source = manque(
        "m7.performance_signaux_constatee",
        _SOURCE_M7_PERFORMANCE,
        f"aucun résumé de {mesure} d'une source propre ({', '.join(sources)}) reçu : la source n'est pas branchée, n'a "
        "jamais été lue, ou rien livré par le bus",
    )
    if not faits:
        return non_calculable([manque_source])
    portant = [f for f in faits if f.get(mesure) is not None]
    if not portant:
        return non_calculable(
            [
                manque(
                    mesure,
                    _SOURCE_M7_PERFORMANCE,
                    f"les résumés reçus ne portent aucune valeur de {mesure} (aucun fait de la source n'en a)",
                )
            ],
            {"n_resumes": len(faits)},
            plus_recent([f.get("derniere_observation_le") for f in faits]),
        )
    valeurs = [_decimal(f.get(mesure)) for f in portant]
    if any(v is None for v in valeurs):
        return non_calculable(
            [manque(mesure, _SOURCE_M7_PERFORMANCE, "un résumé porte une valeur illisible")],
            {"n_resumes": len(portant)},
        )
    presentes = sorted({str(f.get("source")) for f in portant})
    if unique and len(presentes) > 1:
        return non_calculable(
            [
                manque(
                    mesure,
                    _SOURCE_M7_PERFORMANCE,
                    f"deux outils d'audience ({', '.join(presentes)}) comptent chacun des visites : elles se "
                    f"recoupent, "
                    "aucune somme n'est faite",
                )
            ],
            {"sources": presentes},
            plus_recent([f.get("derniere_observation_le") for f in portant]),
        )
    par_groupe: dict[tuple[Any, Any], list[tuple[Any, Any]]] = {}
    for f in portant:
        par_groupe.setdefault((f.get("source"), f.get("compte_ref")), []).append(
            (f.get("periode_debut"), f.get("periode_fin"))
        )
    for (source, compte), periodes in sorted(par_groupe.items()):
        periodes.sort()
        for (_, fin_precedente), (debut_suivant, _) in zip(periodes, periodes[1:], strict=False):
            if debut_suivant <= fin_precedente:
                return non_calculable(
                    [
                        manque(
                            "periode",
                            _SOURCE_M7_PERFORMANCE,
                            f"deux résumés de la source {source} ({compte}) se chevauchent : la somme compterait des "
                            "jours deux fois, aucune somme n'est faite",
                        )
                    ],
                    {"n_resumes": len(portant)},
                )
    jours_periode = sum(int(f["jours_periode"]) for f in portant if type(f.get("jours_periode")) is int)
    jours_couverts = sum(int(f["jours_couverts"]) for f in portant if type(f.get("jours_couverts")) is int)
    fenetres = [
        f["fraicheur_fenetre_h"] * 3600
        for f in portant
        if type(f.get("fraicheur_fenetre_h")) is int and f["fraicheur_fenetre_h"] >= 1
    ]
    entrees = {
        "par_source": {
            source: {
                "resumes": sum(1 for f in portant if f.get("source") == source),
                "jours_couverts": sum(
                    f["jours_couverts"]
                    for f in portant
                    if f.get("source") == source and type(f.get("jours_couverts")) is int
                ),
                "jours_periode": sum(
                    f["jours_periode"]
                    for f in portant
                    if f.get("source") == source and type(f.get("jours_periode")) is int
                ),
            }
            for source in presentes
        },
        "empreinte_faits": empreinte_faits(portant),
    }
    couverture = None
    if jours_couverts < jours_periode:
        couverture = partielle(
            jours_couverts,
            jours_periode,
            f"{jours_couverts} jour(s) sur {jours_periode} ont un fait de la source ; les "
            f"{jours_periode - jours_couverts} "
            "autre(s) ne sont pas des zéros",
        )
    total = sum((v for v in valeurs if v is not None), Decimal(0))
    return (
        nombres.texte_decimal(total).removesuffix(".00"),
        entrees,
        [],
        plus_recent([f.get("derniere_observation_le") for f in portant]),
        couverture,
        min(fenetres) if fenetres else None,
    )


def _clics_recherche(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    return _total_signal(reg, "clics", _SOURCES_RECHERCHE, unique=False)


def _impressions_recherche(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    return _total_signal(reg, "impressions", _SOURCES_RECHERCHE, unique=False)


def _visites_site(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    return _total_signal(reg, "visites", _SOURCES_AUDIENCE, unique=True)


# ---------------------------------------------------------------------------
# M4 : capacité des équipes d'une semaine
# ---------------------------------------------------------------------------
_MANQUE_CAPACITE = manque(
    "m4.capacite_equipe_constatee",
    _SOURCE_M4,
    "aucun constat de capacité reçu : M4 n'en a publié aucun (m4_constater_capacite_equipe), ou rien livré par le bus",
)


def _constat_capacite(operations: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Le constat de la semaine la plus récente, à la portée des journées DATÉES (la capacité réelle de la semaine, pas
    la
    semaine type) : le dernier publié de cette semaine."""
    datees = [
        f
        for f in operations
        if f.get("type_entree") == operations_recues.TYPE_CAPACITE
        and f.get("portee") == _PORTEE_DATEE
        and jour(f.get("semaine_debut")) is not None
    ]
    if not datees:
        return None
    derniere_semaine = max(f["semaine_debut"] for f in datees)
    return dernier_par_publication([f for f in datees if f["semaine_debut"] == derniere_semaine])


def _capacite(reg: dict[str, list[dict[str, Any]]], champ: str) -> Resultat:
    constat = _constat_capacite(reg["operations"])
    if constat is None:
        return non_calculable([_MANQUE_CAPACITE])
    instant = constat.get("constate_le")
    entrees = {"semaine_debut": constat.get("semaine_debut"), "portee": constat.get("portee")}
    if constat.get("calculable") is not True:
        codes = [str(code) for code in constat.get("manque") or []]
        return non_calculable(
            [
                manque(
                    code,
                    _SOURCE_M4,
                    f"M4 ne peut pas chiffrer la capacité de la semaine du {constat.get('semaine_debut')} ({code}) : "
                    "une capacité absente n'est pas zéro",
                )
                for code in codes
            ]
            or [manque("capacite", _SOURCE_M4, "M4 ne peut pas chiffrer la capacité de la semaine")],
            entrees,
            instant,
        )
    valeur = _decimal(constat.get(champ))
    if valeur is None:
        return non_calculable(
            [manque(champ, _SOURCE_M4, "le constat de M4 porte une valeur illisible")], entrees, instant
        )
    return (
        nombres.texte_decimal(valeur),
        {**entrees, "version_donnees": constat.get("version_donnees"), "empreinte_faits": empreinte_faits([constat])},
        [],
        instant,
        None,
        None,
    )


def _capacite_heures_disponibles(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    return _capacite(reg, "heures_disponibles")


def _capacite_heures_planifiees(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    return _capacite(reg, "heures_planifiees")


def _charge_planifiee_pct(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    """La part des heures d'équipe déclarées qui sont planifiées : planifiées / disponibles, du MÊME constat. Sans heure
    disponible déclarée, un pourcentage n'a pas de sens : non calculable."""
    constat = _constat_capacite(reg["operations"])
    if constat is None:
        return non_calculable([_MANQUE_CAPACITE])
    disponibles = _capacite(reg, "heures_disponibles")
    planifiees = _capacite(reg, "heures_planifiees")
    if disponibles[0] is None:
        return disponibles
    if planifiees[0] is None:
        return planifiees
    base = Decimal(disponibles[0])
    if base <= 0:
        return non_calculable(
            [
                manque(
                    "heures_disponibles",
                    _SOURCE_M4,
                    "aucune heure d'équipe déclarée disponible cette semaine : un pourcentage n'a pas de sens",
                )
            ],
            disponibles[1],
            constat.get("constate_le"),
        )
    pct = (Decimal(planifiees[0]) / base * _CENT).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    entrees = {**disponibles[1], "heures_disponibles": disponibles[0], "heures_planifiees": planifiees[0]}
    return nombres.texte_decimal(pct), entrees, [], constat.get("constate_le"), None, None


# ---------------------------------------------------------------------------
# M2 : pipeline commercial
# ---------------------------------------------------------------------------
_MANQUE_PIPELINE = manque(
    "m2.pipeline_constate",
    _SOURCE_M2,
    "aucun constat du pipeline reçu : M2 n'en a publié aucun (m2_constater_pipeline), ou rien livré par le bus",
)


def _constat_pipeline(operations: list[dict[str, Any]]) -> dict[str, Any] | None:
    constats = [
        f
        for f in operations
        if f.get("type_entree") == operations_recues.TYPE_PIPELINE and jour(f.get("date_reference")) is not None
    ]
    if not constats:
        return None
    derniere_date = max(f["date_reference"] for f in constats)
    return dernier_par_publication([f for f in constats if f["date_reference"] == derniere_date])


def _entrees_pipeline(constat: dict[str, Any]) -> dict[str, Any]:
    return {
        "date_reference": constat.get("date_reference"),
        "version_donnees": constat.get("version_donnees"),
        "total": constat.get("total"),
        "resolus": constat.get("resolus"),
        "convertis_un_jour": constat.get("convertis_un_jour"),
        "perdus": constat.get("perdus"),
        "empreinte_faits": empreinte_faits([constat]),
    }


def _pipeline_leads_ouverts(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    constat = _constat_pipeline(reg["operations"])
    if constat is None:
        return non_calculable([_MANQUE_PIPELINE])
    ouverts = constat.get("ouverts")
    if type(ouverts) is not int or ouverts < 0:
        return non_calculable(
            [manque("ouverts", _SOURCE_M2, "le compte du constat est illisible")], {}, constat.get("constate_le")
        )
    return str(ouverts), _entrees_pipeline(constat), [], constat.get("constate_le"), None, None


def _taux_conversion_resolus_pct(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    constat = _constat_pipeline(reg["operations"])
    if constat is None:
        return non_calculable([_MANQUE_PIPELINE])
    taux = _decimal(constat.get("taux_conversion_resolus_pct"))
    if taux is None:
        return non_calculable(
            [
                manque(
                    "taux_conversion_resolus_pct",
                    _SOURCE_M2,
                    f"M2 refuse de conclure : {constat.get('resolus')} lead(s) résolu(s), l'échantillon est sous son "
                    "seuil déclaré (ce n'est pas 0 %)",
                )
            ],
            _entrees_pipeline(constat),
            constat.get("constate_le"),
        )
    return nombres.texte_decimal(taux), _entrees_pipeline(constat), [], constat.get("constate_le"), None, None


def _valeur_ponderee_pipeline_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    constat = _constat_pipeline(reg["operations"])
    if constat is None:
        return non_calculable([_MANQUE_PIPELINE])
    valeur = _decimal(constat.get("valeur_ponderee_cad"))
    if valeur is None:
        return non_calculable(
            [
                manque(
                    "valeur_ponderee_cad",
                    _SOURCE_M2,
                    "M2 n'a pas pu pondérer le pipeline : aucune valeur déclarée par les vendeurs sur les leads "
                    "ouverts, ou échantillon sous le seuil (ce n'est pas 0 $)",
                )
            ],
            _entrees_pipeline(constat),
            constat.get("constate_le"),
        )
    return nombres.texte_decimal(valeur), _entrees_pipeline(constat), [], constat.get("constate_le"), None, None


# ---------------------------------------------------------------------------
# M6 : disponibilité du matériel
# ---------------------------------------------------------------------------
_MANQUE_DISPONIBILITE = manque(
    "m6.disponibilite_constatee",
    _SOURCE_M6,
    "aucun constat de disponibilité reçu : M6 n'en a publié aucun (m6_constater_disponibilite), ou rien livré par le "
    "bus",
)


def _constat_disponibilite(operations: list[dict[str, Any]]) -> dict[str, Any] | None:
    constats = [
        f
        for f in operations
        if f.get("type_entree") == operations_recues.TYPE_DISPONIBILITE and jour(f.get("date_reference")) is not None
    ]
    if not constats:
        return None
    derniere_date = max(f["date_reference"] for f in constats)
    return dernier_par_publication([f for f in constats if f["date_reference"] == derniere_date])


def _compte_disponibilite(reg: dict[str, list[dict[str, Any]]], champ: str, exige_articles: bool) -> Resultat:
    constat = _constat_disponibilite(reg["operations"])
    if constat is None:
        return non_calculable([_MANQUE_DISPONIBILITE])
    instant = constat.get("constate_le")
    entrees = {
        "date_reference": constat.get("date_reference"),
        "version_donnees": constat.get("version_donnees"),
        "articles_suivis": constat.get("articles_suivis"),
        "reservations_actives": constat.get("reservations_actives"),
        "empreinte_faits": empreinte_faits([constat]),
    }
    nombre = constat.get(champ)
    if type(nombre) is not int or nombre < 0:
        return non_calculable([manque(champ, _SOURCE_M6, "le compte du constat est illisible")], entrees, instant)
    if exige_articles and constat.get("articles_suivis") == 0:
        return non_calculable(
            [
                manque(
                    "articles_suivis", _SOURCE_M6, "M6 ne suit encore aucun article : un zéro ne dirait rien du stock"
                )
            ],
            entrees,
            instant,
        )
    return str(nombre), entrees, [], instant, None, None


def _articles_en_rupture(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    return _compte_disponibilite(reg, "articles_en_rupture", True)


def _articles_sur_reserves(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    return _compte_disponibilite(reg, "articles_sur_reserves", True)


def _reservations_incompletes(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    return _compte_disponibilite(reg, "reservations_incompletes", False)


# ---------------------------------------------------------------------------
# M1 : plaintes
# ---------------------------------------------------------------------------
def _plaintes_periode(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    constats = [
        f
        for f in reg["operations"]
        if f.get("type_entree") == operations_recues.TYPE_PLAINTES and jour(f.get("date_reference")) is not None
    ]
    if not constats:
        return non_calculable(
            [
                manque(
                    "m1.plaintes_constatees",
                    _SOURCE_M1,
                    "aucun constat des plaintes reçu : M1 n'en a publié aucun (m1_constater_plaintes), ou rien livré "
                    "par le bus",
                )
            ]
        )
    derniere_date = max(f["date_reference"] for f in constats)
    constat = dernier_par_publication([f for f in constats if f["date_reference"] == derniere_date])
    assert constat is not None
    instant = _jour_instant(constat.get("date_reference"))
    entrees = {
        "date_reference": constat.get("date_reference"),
        "jours": constat.get("jours"),
        "etat": constat.get("etat"),
        "empreinte_faits": empreinte_faits([constat]),
    }
    nombre = constat.get("nombre")
    if constat.get("etat") != _ETAT_CONNUE or type(nombre) is not int or nombre < 0:
        if constat.get("etat") == _ETAT_AUCUNE:
            raison = (
                "M1 a lu son registre sans y trouver de plainte que ses règles reconnaissent : ce n'est pas « zéro "
                "plainte » (une plainte que les règles ne reconnaissent pas n'y figure pas)"
            )
        else:
            raison = (
                f"M1 n'est pas branché sur les plaintes (état {constat.get('etat')}) : le nombre est inconnu, pas zéro"
            )
        return non_calculable([manque("nombre", _SOURCE_M1, raison)], entrees, instant)
    return str(nombre), entrees, [], instant, None, None


# ---------------------------------------------------------------------------
# D6 : leads publicitaires et coût par lead publicitaire
# ---------------------------------------------------------------------------
def declarations_canaux(registre: list[dict[str, Any]]) -> tuple[dict[str, tuple[str, ...]], dict[str, Any] | None]:
    """``(canaux, None)`` quand le propriétaire a déclaré la correspondance canal -> sources UTM (D6), ``({}, manque)``
    sinon (jamais une correspondance devinée). Le registre ``declarations`` porte au plus un fait
    ``canaux_marketing``."""
    faits = de_type(registre, "canaux_marketing")
    fait = faits[-1] if faits else None
    canaux = fait.get("canaux") if isinstance(fait, dict) else None
    if isinstance(canaux, dict) and canaux:
        propres = {
            str(canal): tuple(str(s) for s in sources)
            for canal, sources in sorted(canaux.items())
            if isinstance(sources, (list, tuple)) and sources
        }
        if propres:
            return propres, None
    verdict = fait.get("verdict") if isinstance(fait, dict) else None
    raison = (
        "le profil d'entreprise est invalide : la correspondance canaux -> sources UTM n'est pas lue"
        if verdict == "REJ-PROFIL-INVALIDE"
        else "le propriétaire n'a déclaré aucune correspondance entre ses canaux publicitaires et les sources UTM de "
        "ses "
        "leads (entreprise.yaml, clé canaux_marketing) : M8 n'en devine aucune"
    )
    return {}, manque("canaux_marketing", "propriétaire (entreprise.yaml)", raison)


def _leads_par_canal(
    reg: dict[str, list[dict[str, Any]]], canaux: dict[str, tuple[str, ...]]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], int, int]:
    """Les leads de M2 rangés par canal d'après leur ``utm_source`` déclarée. Rend ``(par_canal, tous, sans_source,
    source_non_declaree)``."""
    leads = []
    vus: set[str] = set()
    for fait in de_type(reg["entonnoir"], entonnoir.TYPE_LEAD_RECU):
        identifiant = fait.get("lead_id")
        if isinstance(identifiant, str) and identifiant and identifiant not in vus:
            vus.add(identifiant)
            leads.append(fait)
    canal_de_source = {source: canal for canal, sources in canaux.items() for source in sources}
    par_canal: dict[str, list[dict[str, Any]]] = {}
    sans_source = 0
    non_declaree = 0
    for lead in leads:
        source = lead.get("utm_source")
        if not isinstance(source, str) or not source:
            sans_source += 1
        elif source in canal_de_source:
            par_canal.setdefault(canal_de_source[source], []).append(lead)
        else:
            non_declaree += 1
    return par_canal, leads, sans_source, non_declaree


def _leads_publicitaires(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    canaux, manque_declaration = declarations_canaux(reg.get("declarations", []))
    if manque_declaration is not None:
        return non_calculable([manque_declaration])
    par_canal, leads, sans_source, non_declaree = _leads_par_canal(reg, canaux)
    if not leads:
        return non_calculable(
            [
                manque(
                    "m2.client_associe",
                    "M2 (m2.client_associe)",
                    "aucun lead reçu de M2 : M8 ne peut pas distinguer « aucun lead publicitaire » de « rien livré »",
                )
            ]
        )
    retenus = [lead for liste in par_canal.values() for lead in liste]
    entrees = {
        "par_canal": {canal: len(liste) for canal, liste in sorted(par_canal.items())},
        "n_leads": len(leads),
        "n_leads_sans_source": sans_source,
        "n_leads_source_non_declaree": non_declaree,
        "empreinte_faits": empreinte_faits(retenus),
    }
    couverture = None
    if sans_source:
        couverture = partielle(
            len(leads) - sans_source,
            len(leads),
            f"{sans_source} lead(s) sur {len(leads)} n'ont pas de source UTM : M8 ne peut pas dire s'ils viennent "
            f"d'une "
            "publicité",
        )
    return (
        str(len(retenus)),
        entrees,
        [],
        plus_recent([lead.get("horodatage") for lead in leads]),
        couverture,
        None,
    )


def _depenses_par_canal(
    operations: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    """Par canal, la somme des dernières révisions des relevés de M7 et la période qu'elles couvrent ; ou un manque si
    les
    relevés ne se laissent pas sommer (période illisible, bases de taxes mixtes, chevauchement dans un canal)."""
    releves = _derniers_releves(operations)
    if not releves:
        return {}, manque(
            "m7.depenses_marketing_constatees",
            _SOURCE_M7_DEPENSES,
            "aucun relevé de dépense publicitaire reçu : M7 n'en a inscrit aucun, ou rien livré par le bus",
        )
    bases = sorted({str(r.get("base_taxes")) for r in releves})
    if len(bases) != 1:
        return {}, manque(
            "base_taxes",
            _SOURCE_M7_DEPENSES,
            "bases de taxes différentes entre les relevés (" + ", ".join(bases) + ") : aucune somme",
        )
    par_canal: dict[str, list[tuple[Any, Any, Decimal, dict[str, Any]]]] = {}
    for releve in releves:
        d, f, montant = (
            jour(releve.get("periode_debut")),
            jour(releve.get("periode_fin")),
            _decimal(releve.get("montant_cad")),
        )
        if d is None or f is None or f < d or montant is None or (f - d).days >= _JOURS_PAR_RELEVE_MAX:
            return {}, manque(
                "periode", _SOURCE_M7_DEPENSES, "un relevé a une période ou un montant illisible : aucune somme"
            )
        par_canal.setdefault(str(releve.get("canal")), []).append((d, f, montant, releve))
    sortie: dict[str, dict[str, Any]] = {}
    for canal, lignes in sorted(par_canal.items()):
        lignes.sort(key=lambda ligne: (ligne[0], ligne[1]))
        for (_, fin_precedente, _, _), (debut_suivant, _, _, _) in zip(lignes, lignes[1:], strict=False):
            if debut_suivant <= fin_precedente:
                return {}, manque(
                    "periode", _SOURCE_M7_DEPENSES, f"deux relevés du canal {canal} se chevauchent : aucune somme"
                )
        sortie[canal] = {
            "somme": sum((ligne[2] for ligne in lignes), Decimal(0)),
            "du": lignes[0][0].isoformat(),
            "au": lignes[-1][1].isoformat(),
            "releves": [ligne[3] for ligne in lignes],
            "jours_sans_releve": sum((b[0] - a[1]).days - 1 for a, b in zip(lignes, lignes[1:], strict=False)),
        }
    return sortie, None


def _cout_par_lead_pub_cad(reg: dict[str, list[dict[str, Any]]]) -> Resultat:
    """Dépense publicitaire (relevés de M7) divisée par les leads de M2 que la correspondance déclarée rattache aux
    mêmes
    canaux, sur la période que chaque canal couvre. Un canal sans relevé ou sans source déclarée n'y entre pas, et
    c'est dit."""
    canaux, manque_declaration = declarations_canaux(reg.get("declarations", []))
    if manque_declaration is not None:
        return non_calculable([manque_declaration])
    depenses, manque_depenses = _depenses_par_canal(reg["operations"])
    if manque_depenses is not None:
        return non_calculable([manque_depenses])
    par_canal, leads, _sans_source, _non_declaree = _leads_par_canal(reg, canaux)
    if not leads:
        return non_calculable(
            [
                manque(
                    "m2.client_associe",
                    "M2 (m2.client_associe)",
                    "aucun lead reçu de M2 : le coût par lead n'a pas de dénominateur",
                )
            ]
        )
    comparables = sorted(set(depenses) & set(canaux))
    sans_declaration = sorted(set(depenses) - set(canaux))
    if not comparables:
        return non_calculable(
            [
                manque(
                    "canaux_marketing",
                    "propriétaire (entreprise.yaml)",
                    f"aucun canal avec relevés ({', '.join(sorted(depenses))}) n'a de source UTM déclarée : M8 ne "
                    "rattache aucun lead à ces dépenses",
                )
            ],
            {"canaux_avec_releves": sorted(depenses)},
        )
    total_depense = Decimal(0)
    total_leads = 0
    detail: dict[str, Any] = {}
    faits_utilises: list[dict[str, Any]] = []
    for canal in comparables:
        depense = depenses[canal]
        d, f = depense["du"], depense["au"]
        dans_la_periode = [
            lead
            for lead in par_canal.get(canal, [])
            if isinstance(lead.get("horodatage"), str) and d <= lead["horodatage"][:10] <= f
        ]
        total_depense += depense["somme"]
        total_leads += len(dans_la_periode)
        faits_utilises += [*depense["releves"], *dans_la_periode]
        detail[canal] = {
            "du": d,
            "au": f,
            "depense_cad": nombres.texte_decimal(depense["somme"]),
            "leads": len(dans_la_periode),
            "jours_sans_releve": depense["jours_sans_releve"],
        }
    entrees = {
        "par_canal": detail,
        "depense_totale_cad": nombres.texte_decimal(total_depense),
        "leads_publicitaires": total_leads,
        "canaux_sans_source_declaree": sans_declaration,
        "empreinte_faits": empreinte_faits(faits_utilises),
    }
    instant = plus_recent(
        [r.get("releve_le") for canal in comparables for r in depenses[canal]["releves"]]
        + [lead.get("horodatage") for liste in par_canal.values() for lead in liste]
    )
    fenetre, _ = fenetre_source_s(set(comparables), de_type(reg["operations"], operations_recues.TYPE_SIGNAUX))
    if total_leads == 0:
        return non_calculable(
            [
                manque(
                    "m2.client_associe",
                    "M2 (m2.client_associe)",
                    "aucun lead rattaché aux canaux publicitaires dans la période des relevés : diviser par zéro n'a "
                    "pas de "
                    "sens, le coût par lead est inconnu",
                )
            ],
            entrees,
            instant,
        )
    raisons = []
    jours_sans = sum(info["jours_sans_releve"] for info in detail.values())
    if jours_sans:
        raisons.append(
            f"{jours_sans} jour(s) sans relevé à l'intérieur des périodes couvertes (ce ne sont pas des zéros)"
        )
    if sans_declaration:
        raisons.append(
            f"{len(sans_declaration)} canal(aux) avec relevés sans source UTM déclarée "
            f"({', '.join(sans_declaration)}) n'y entre(nt) pas"
        )
    couverture = (
        {
            **partielle(len(comparables), len(comparables) + len(sans_declaration), " ; ".join(raisons)),
            "jours_sans_releve": jours_sans,
        }
        if raisons
        else None
    )
    cout = total_depense / Decimal(total_leads)
    return nombres.texte_decimal(cout), entrees, [], instant, couverture, fenetre


CALCULS = {
    "m8_depense_pub_comptabilisee_cad": _depense_comptabilisee_cad,
    "m8_ecart_depense_pub_comptabilisee_cad": _ecart_depense_pub_comptabilisee_cad,
    "m8_factures_emises": _factures_emises,
    "m8_facturation_emise_cad": _facturation_emise_cad,
    "m8_clics_recherche": _clics_recherche,
    "m8_impressions_recherche": _impressions_recherche,
    "m8_visites_site": _visites_site,
    "m8_capacite_heures_disponibles": _capacite_heures_disponibles,
    "m8_capacite_heures_planifiees": _capacite_heures_planifiees,
    "m8_charge_planifiee_pct": _charge_planifiee_pct,
    "m8_pipeline_leads_ouverts": _pipeline_leads_ouverts,
    "m8_taux_conversion_resolus_pct": _taux_conversion_resolus_pct,
    "m8_valeur_ponderee_pipeline_cad": _valeur_ponderee_pipeline_cad,
    "m8_articles_en_rupture": _articles_en_rupture,
    "m8_articles_sur_reserves": _articles_sur_reserves,
    "m8_reservations_incompletes": _reservations_incompletes,
    "m8_plaintes_periode": _plaintes_periode,
    "m8_leads_publicitaires": _leads_publicitaires,
    "m8_cout_par_lead_pub_cad": _cout_par_lead_pub_cad,
}

__all__ = ["CALCULS", "declarations_canaux"]
