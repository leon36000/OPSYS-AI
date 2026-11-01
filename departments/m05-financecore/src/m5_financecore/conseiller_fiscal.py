"""Conseiller fiscal et comptable STRATÉGIQUE de M5 (M5.15) : une analyse de situation à partir des données de
l'entreprise et de règles SOURCÉES, jamais d'une règle inventée.

Module pur : aucune horloge, aucun registre, aucun réseau. L'adaptateur (`outils_conseillers.py`) lui apporte la base
fiscale chargée, les données lues des registres (soldes du grand livre, échéances du calendrier, taux utilisés) et les
passages que la base de connaissances (RAG, `connaissances_fiscales.py`) a rendus pour le sujet.

CHAQUE affirmation cite ses sources et leur statut de revue :
- `regle_base_fiscale` : un paramètre de la base fiscale versionnée (`base_fiscale.py`) avec son statut (`brouillon`,
  `revu_1`, `approuve` : deux réviseurs distincts) et son empreinte ;
- `donnee_entreprise` : un fait que le code a lu dans les registres de M5 (grand livre, calendrier déclaré) ;
- `calendrier_fiscal` : les dates transcrites du calendrier versionné (« A_VALIDER » par le CPA tant qu'il ne l'a
pas fait) ; - `connaissance` : un passage PUBLIÉ de la base de connaissances, avec son éditeur, son type d'autorité
(« officielle »,
  « reconnue », « interne », « tierce », « fictive »), son état, sa version et sa fraîcheur.

Le marquage est mécanique : toute sortie qui s'appuie sur une source non approuvée (règle sans deux réviseurs,
calendrier non validé par le CPA, texte dont l'autorité n'est pas « officielle », source périmée, démonstration
fictive) est marquée « ESSAI/non approuvé » ; en mode « officiel », une source non approuvée est un REFUS, jamais
une affirmation. Une règle « non renseignée » (absente de la base, hors couverture, sans valeur) est un REFUS qui
dit quelle source officielle fournir (`REJ-CONSEIL-REGLE-NON-RENSEIGNEE`) : aucune valeur n'est estimée, aucun «
dernier taux connu » n'est repris.

Les « pistes » (rémunération du dirigeant, déduction pour amortissement, structure, acomptes, régimes de taxes) sont des
SUJETS À DISCUTER avec le CPA : sans chiffrage (`chiffrer` faux), elles rendent la piste, les questions à poser et
l'état des règles requises ; avec chiffrage, elles exigent chacune de leurs règles et refusent dès qu'une est non
renseignée. M5
ne recommande jamais une structure ni une stratégie : « À valider auprès d'un comptable (CPA) / professionnel
qualifié ».
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from . import analyse, base_fiscale, grand_livre, verdicts_operations

__all__ = ["VERSION", "analyser", "lister_sujets", "requete_connaissance", "MARQUAGE_ESSAI"]

VERSION = "1.0.0"
MARQUAGE_ESSAI = (
    "ESSAI/non approuvé : le mode essai est demandé, ou au moins une source n'est pas approuvée (règle sans "
    "deux réviseurs, calendrier non validé par le CPA, autorité non officielle, source périmée ou "
    "démonstration fictive), ou la piste n'est pas chiffrable."
)
_MARQUAGE_APPROUVE = (
    "Sources approuvées (règles revues par deux personnes distinctes, autorité officielle) : la "
    "validation par un CPA est tout de même requise."
)
_MARQUAGE_DONNEES = "Données de l'entreprise seulement (aucune règle externe invoquée) : à faire valider par le CPA."
_MODES = ("officiel", "essai")
_HYPOTHESE_CREDITS = "crédits de taxes sur intrants supposés récupérables à 100 % (comme ailleurs dans M5)"

_SUJETS: dict[str, dict[str, Any]] = {
    "taxes_tps_tvq_a_remettre": {
        "titre": "TPS/TVQ à remettre selon le grand livre",
        "genre": "analyse",
        "regles_requises": ["fed.tps.taux", "qc.tvq.taux"],
        "donnees": ["grand_livre"],
        "requete": "taxe de vente remise déclaration crédit de taxe sur les intrants",
        "questions": [
            "Le solde du grand livre inclut-il toutes les factures de la période de déclaration ?",
            "Les crédits sur intrants sont-ils tous admissibles à 100 % ?",
        ],
    },
    "echeances_tps_tvq": {
        "titre": "Échéances de production et de paiement TPS/TVQ",
        "genre": "analyse",
        "regles_requises": [],
        "donnees": ["echeances"],
        "requete": "échéance de déclaration et de paiement de la taxe de vente",
        "questions": [
            "La fréquence de production et la fin d'exercice déclarées sont-elles celles de la confirmation "
            "d'inscription ?",
            "La date de la dernière remise est-elle exacte ?",
        ],
    },
    "controle_des_taux_appliques": {
        "titre": "Taux de TPS et de TVQ appliqués par M5 contre la base fiscale",
        "genre": "analyse",
        "regles_requises": ["fed.tps.taux", "qc.tvq.taux"],
        "donnees": ["taux_utilises"],
        "requete": "taux de la taxe de vente",
        "questions": ["Les taux de la base fiscale ont-ils été relus par deux personnes contre le texte officiel ?"],
    },
    "remuneration_salaire_dividendes": {
        "titre": "Rémunération du dirigeant : salaire ou dividendes",
        "genre": "piste",
        "piste": (
            "Comparer, pour un même bénéfice, la charge fiscale et sociale totale (société et particulier) selon la "
            "part versée en salaire ou en dividendes."
        ),
        "regles_requises": [
            "fed.impot.societe.taux_petite_entreprise",
            "qc.impot.societe.taux_petite_entreprise",
            "fed.impot.dividendes.majoration_et_credit",
            "qc.impot.dividendes.majoration_et_credit",
            "fed.impot.societe.plafond_affaires_petite_entreprise",
        ],
        "requete": "rémunération du dirigeant salaire dividendes",
        "questions": [
            "Quel est le bénéfice avant rémunération prévu pour l'exercice ?",
            "Le dirigeant a-t-il d'autres revenus, une famille à charge, un régime d'épargne-retraite à alimenter ?",
            "Quels taux et seuils l'exercice visé applique-t-il (sources officielles à fournir) ?",
        ],
    },
    "deduction_amortissement_cca": {
        "titre": "Déduction pour amortissement (catégories de DPA/CCA)",
        "genre": "piste",
        "piste": (
            "Classer les acquisitions de l'exercice par catégorie de déduction et choisir le moment de la réclamer."
        ),
        "regles_requises": [
            "fed.impot.dpa.taux_par_categorie",
            "qc.impot.dpa.taux_par_categorie",
            "fed.impot.dpa.regle_demi_annee",
        ],
        "requete": "déduction pour amortissement catégorie",
        "questions": [
            "Quelles acquisitions (véhicule, équipement, bâtiment) ont été faites, à quelle date de mise en service ?",
            "Quelle est la catégorie de chacune selon la liste officielle ?",
        ],
    },
    "acomptes_provisionnels_impot": {
        "titre": "Acomptes provisionnels d'impôt",
        "genre": "piste",
        "piste": "Établir si des acomptes provisionnels sont exigés et selon quelle méthode de calcul.",
        "regles_requises": [
            "fed.impot.acomptes.seuil_exigibilite",
            "fed.impot.acomptes.methodes",
            "qc.impot.acomptes.seuil_exigibilite",
        ],
        "requete": "acomptes provisionnels impôt",
        "questions": ["Quel est l'impôt des deux dernières années ?", "Quelle méthode de calcul le CPA retient-il ?"],
    },
    "regime_declaration_taxes": {
        "titre": "Régime de déclaration des taxes (petit fournisseur, méthode rapide)",
        "genre": "piste",
        "piste": "Vérifier si un régime simplifié de déclaration s'applique à l'entreprise et à quelles conditions.",
        "regles_requises": [
            "fed.tps.seuil_petit_fournisseur",
            "fed.tps.methode_rapide.conditions",
            "qc.tvq.methode_rapide.conditions",
        ],
        "requete": "petit fournisseur méthode rapide taxe de vente",
        "questions": [
            "Quels sont les revenus taxables des quatre derniers trimestres ?",
            "L'entreprise a-t-elle déjà choisi une méthode de comptabilité simplifiée ?",
        ],
    },
    "structure_juridique": {
        "titre": "Structure juridique de l'entreprise",
        "genre": "piste",
        "piste": (
            "Faire examiner par un conseiller juridique et un CPA la forme d'exploitation (entreprise individuelle, "
            "société par actions, société de personnes) : c'est une question juridique, M5 ne la tranche pas."
        ),
        "regles_requises": [
            "fed.impot.societe.taux_petite_entreprise",
            "qc.impot.societe.taux_petite_entreprise",
            "fed.impot.particulier.bareme_comparatif",
        ],
        "requete": "structure juridique société par actions entreprise individuelle",
        "questions": [
            "Quels sont les objectifs (responsabilité, relève, financement) ?",
            "Quelle est la situation personnelle de l'actionnaire ?",
        ],
    },
}


def lister_sujets() -> list[dict[str, Any]]:
    """Les sujets d'analyse, avec ce que chacun exige (règles et données) : rien n'est caché à l'appelant."""
    return [
        {
            "sujet": cle,
            "titre": s["titre"],
            "genre": s["genre"],
            "regles_requises": list(s["regles_requises"]),
            "donnees": list(s.get("donnees", [])),
            "requete_connaissance": s["requete"],
        }
        for cle, s in sorted(_SUJETS.items())
    ]


def requete_connaissance(sujet: str) -> str | None:
    """La requête que l'adaptateur envoie à la base de connaissances pour ce sujet (ou `None` si le sujet est "
    "inconnu)."""
    return _SUJETS[sujet]["requete"] if sujet in _SUJETS else None


def _verdict(code: str, detail: str = "", **supplement: Any) -> dict[str, Any]:
    return {**verdicts_operations.construire_verdict(code, detail=detail), **supplement}


def _source_regle(regle: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "regle_base_fiscale",
        "identifiant": regle["identifiant"],
        "valeur": str(regle["valeur"]),
        "unite": regle["unite"],
        "statut_revue": regle["statut_revue"],
        "approuve": regle["statut_revue"] == "approuve",
        "empreinte": regle["empreinte"],
        "effet": regle["effet"],
        "sources_officielles": [
            {"organisme": s.get("organisme"), "titre": s.get("titre"), "url": s.get("url")} for s in regle["sources"]
        ],
    }


def _passage(passage: Mapping[str, Any]) -> dict[str, Any]:
    """Un passage de la base de connaissances, classé SANS le promouvoir : seule une autorité « officielle », à jour
    et non
    fictive est approuvée ; tout le reste est un essai, et le type d'autorité est dit tel quel."""
    source = passage["source"]
    approuve = (
        source["type_autorite"] == "officielle"
        and source["etat"] == "publie"
        and not source["perime"]
        and not passage.get("demonstration_fictive")
    )
    raisons = []
    if source["type_autorite"] != "officielle":
        raisons.append(f"autorité « {source['type_autorite']} », pas « officielle »")
    if source["perime"]:
        raisons.append("source périmée (" + str(source.get("motif_peremption")) + ")")
    if passage.get("demonstration_fictive"):
        raisons.append("démonstration FICTIVE : jamais une source réelle")
    return {
        "type": "connaissance",
        "cle": source["cle"],
        "titre": source["titre"],
        "version": source["version"],
        "version_id": source["version_id"],
        "etat": source["etat"],
        "editeur": source["editeur"],
        "type_autorite": source["type_autorite"],
        "reference": source["reference"],
        "date_publication": source["date_publication"],
        "approuve": approuve,
        "raisons_essai": raisons,
        "demonstration_fictive": bool(passage.get("demonstration_fictive")),
        "extrait": passage["texte"][:300],
        "sha256": source["sha256"],
    }


def _resoudre_regles(
    base: Any, identifiants: Sequence[str], aujourd_hui: str, mode: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    """`(résolues, non renseignées, non approuvées)` : une règle INCONNUE, hors couverture ou sans valeur est « non
    renseignée » ; en mode officiel, une règle valorisée mais non approuvée est « non approuvée »."""
    resolues, manquantes, non_approuvees = [], [], []
    for ident in identifiants:
        regle, verdict = base_fiscale.resoudre(base, ident, aujourd_hui, mode=mode)
        if verdict is None:
            resolues.append(regle)
        elif verdict["code"] == "REJ-BASEFISC-NON-APPROUVE":
            non_approuvees.append({"regle": ident, "code": verdict["code"], "detail": verdict["detail"]})
        else:
            manquantes.append(
                {
                    "regle": ident,
                    "code": verdict["code"],
                    "detail": verdict["detail"],
                    "action": "fournir la source officielle (organisme, titre, URL, date de consultation) "
                    "puis la faire relire par deux personnes",
                }
            )
    return resolues, manquantes, non_approuvees


def _affirmation(ident: str, texte: str, nature: str, statut: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": ident, "texte": texte, "nature": nature, "statut": statut, "sources": sources}


def _montant(valeur: Any) -> str:
    return format(Decimal(str(valeur)), "f")


def _affirmations_taxes(
    donnees: Mapping[str, Any],
    aujourd_hui: str,
    resolues: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    livre = donnees["grand_livre"]
    soldes = livre["soldes"]
    tps = Decimal(soldes["tps_a_percevoir"]) - Decimal(soldes["tps_cti"])
    tvq = Decimal(soldes["tvq_a_percevoir"]) - Decimal(soldes["tvq_rti"])
    source_livre = {
        "type": "donnee_entreprise",
        "registre": "grand_livre",
        "tete": livre["tete"],
        "description": "soldes des écritures DÉFINITIVES datées au plus tard le " + aujourd_hui,
    }
    resultat = [
        _affirmation(
            "taxes_selon_livre",
            f"Au {aujourd_hui}, le grand livre porte {_montant(soldes['tps_a_percevoir'])} $ de TPS à percevoir et "
            f"{_montant(soldes['tps_cti'])} $ de CTI, soit {_montant(tps)} $ de TPS nette ; "
            f"{_montant(soldes['tvq_a_percevoir'])} $ "
            f"de TVQ à percevoir et {_montant(soldes['tvq_rti'])} $ de RTI, soit {_montant(tvq)} $ de TVQ nette. "
            f"Cumul depuis l'ouverture du grand livre (la dernière remise n'est pas déduite) ; {_HYPOTHESE_CREDITS}.",
            "donnee_entreprise",
            "DONNEE_ENTREPRISE",
            [source_livre],
        )
    ]
    for regle in resolues:
        resultat.append(
            _affirmation(
                "taux_" + regle["identifiant"],
                f"Taux utilisé pour {regle['libelle']} : {regle['valeur']} ({regle['unite']}), en vigueur le "
                f"{regle['date_demandee']}.",
                "regle_base_fiscale",
                "APPROUVE" if regle["statut_revue"] == "approuve" else "ESSAI",
                [_source_regle(regle)],
            )
        )
    return resultat


def _affirmation_echeances(donnees: Mapping[str, Any], mode: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    echeances = donnees["echeances"]
    if "verdict" in echeances:
        v = echeances["verdict"]
        return [
            _affirmation(
                "echeances_inconnues",
                f"Échéance non établie : {v['detail']}",
                "calendrier_fiscal",
                "INCONNU",
                [{"type": "calendrier_fiscal", "code": v["code"]}],
            )
        ], None
    validations = echeances["validation_cpa"]
    valide = all(statut == "VALIDE_PAR_LE_CPA" for statut in validations.values())
    if mode == "officiel" and not valide:
        return [], _verdict(
            "REJ-CONSEIL-SOURCE-NON-APPROUVEE",
            "mode officiel : le calendrier fiscal n'est pas validé par le CPA "
            f"({', '.join(f'{a} : {s}' for a, s in sorted(validations.items()))})",
        )
    source = {
        "type": "calendrier_fiscal",
        "versions": echeances["versions"],
        "validation_cpa": validations,
        "approuve": valide,
        "sources_officielles": [
            {"organisme": s["organisme"], "titre": s["titre"], "url": s["url"], "consulte_le": s["consulte_le"]}
            for s in echeances["sources"]
        ][:4],
    }
    resultat = []
    for index, e in enumerate(echeances["echeances"][:4]):
        resultat.append(
            _affirmation(
                f"echeance_{index + 1}",
                f"Période du {e['periode_debut']} au {e['periode_fin']} : paiement au plus tard le "
                f"{e['limite_paiement']} "
                f"({e['jours_avant_paiement']} jours), production au plus tard le {e['limite_production']} "
                f"({e['statut']}).",
                "calendrier_fiscal",
                "APPROUVE" if valide else "ESSAI",
                [source],
            )
        )
    if not resultat:
        resultat.append(
            _affirmation(
                "aucune_echeance",
                "Aucune échéance à venir n'est connue du calendrier déclaré.",
                "calendrier_fiscal",
                "INCONNU",
                [source],
            )
        )
    return resultat, None


def _affirmations_controle(donnees: Mapping[str, Any], resolues: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    utilises = donnees["taux_utilises"]
    table = {"fed.tps.taux": "tps_federale", "qc.tvq.taux": "tvq_quebec"}
    resultat = []
    for regle in resolues:
        id_taux = table[regle["identifiant"]]
        utilise = utilises.get(id_taux)
        concorde = utilise is not None and Decimal(str(utilise)) == Decimal(str(regle["valeur"]))
        resultat.append(
            _affirmation(
                "controle_" + id_taux,
                f"Le taux de {regle['libelle']} utilisé par M5 ({utilise}) "
                + (
                    "concorde avec la base fiscale."
                    if concorde
                    else f"DIFFÈRE de la base fiscale ({regle['valeur']}) : "
                    "l'écart est à expliquer avant toute facturation."
                ),
                "regle_base_fiscale",
                ("APPROUVE" if regle["statut_revue"] == "approuve" else "ESSAI") if concorde else "ESSAI",
                [
                    _source_regle(regle),
                    {"type": "donnee_entreprise", "registre": "taux_fiscaux.v1.yaml", "valeur": str(utilise)},
                ],
            )
        )
    return resultat


def analyser(
    sujet: Any,
    *,
    mode: Any,
    aujourd_hui: Any,
    chiffrer: Any,
    base: Any,
    donnees: Mapping[str, Any],
    passages: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """L'analyse du `sujet` ou le refus nommé. Aucune affirmation sans source ; aucune règle estimée ; le marquage est
    mécanique. Voir l'en-tête du module pour les refus."""
    if not isinstance(sujet, str) or sujet not in _SUJETS:
        return None, _verdict("REJ-CONSEIL-SUJET-INCONNU", f"sujet parmi {sorted(_SUJETS)}")
    if not isinstance(mode, str) or mode not in _MODES:
        return None, _verdict("REJ-CONSEIL-MODE-INVALIDE", "mode explicite requis : « officiel » ou « essai »")
    if grand_livre._date(aujourd_hui) is None:
        return None, _verdict("REJ-CONSEIL-ENTREE-INVALIDE", f"aujourd_hui {aujourd_hui!r} : AAAA-MM-JJ exigé")
    if type(chiffrer) is not bool:
        return None, _verdict("REJ-CONSEIL-ENTREE-INVALIDE", "chiffrer : vrai ou faux, jamais supposé")
    fiche = _SUJETS[sujet]
    exige_regles = fiche["genre"] == "analyse" or chiffrer
    resolues: list[dict[str, Any]] = []
    manquantes: list[dict[str, str]] = []
    non_approuvees: list[dict[str, str]] = []
    if fiche["regles_requises"]:
        resolues, manquantes, non_approuvees = _resoudre_regles(base, fiche["regles_requises"], aujourd_hui, mode)
    if exige_regles and manquantes:
        return None, _verdict(
            "REJ-CONSEIL-REGLE-NON-RENSEIGNEE",
            "règle(s) non renseignée(s) — source officielle requise : "
            + "; ".join(m["regle"] for m in manquantes)
            + ". Aucune valeur n'est estimée ; fournir les sources, les faire relire par deux personnes, ou poser la "
            "question au CPA.",
            a_fournir=manquantes,
            questions_pour_le_cpa=list(fiche["questions"]),
        )
    if exige_regles and non_approuvees:
        return None, _verdict(
            "REJ-CONSEIL-SOURCE-NON-APPROUVEE",
            "mode officiel : règle(s) non approuvée(s) par deux réviseurs distincts : "
            + "; ".join(n["regle"] for n in non_approuvees),
            a_fournir=non_approuvees,
            questions_pour_le_cpa=list(fiche["questions"]),
        )
    for besoin in fiche.get("donnees", []):
        if besoin not in donnees:
            return None, _verdict(
                "REJ-CONSEIL-DONNEE-MANQUANTE", f"donnée de l'entreprise absente : {besoin}", a_fournir=[besoin]
            )
    affirmations: list[dict[str, Any]] = []
    hypotheses: list[str] = []
    if sujet == "taxes_tps_tvq_a_remettre":
        affirmations = _affirmations_taxes(donnees, aujourd_hui, resolues)
        hypotheses.append(_HYPOTHESE_CREDITS)
    elif sujet == "echeances_tps_tvq":
        affirmations, refus = _affirmation_echeances(donnees, mode)
        if refus is not None:
            return None, refus
    elif sujet == "controle_des_taux_appliques":
        affirmations = _affirmations_controle(donnees, resolues)
    contexte = [_passage(p) for p in passages[:4]]
    piste = None
    if fiche["genre"] == "piste":
        piste = {
            "description": fiche["piste"],
            "chiffrage": (
                "REFUSÉ tant qu'une règle requise n'est pas renseignée et approuvée"
                if manquantes or non_approuvees
                else "possible : toutes les règles requises sont renseignées"
            ),
            "regles_requises_etat": [{"regle": r["identifiant"], "statut_revue": r["statut_revue"]} for r in resolues]
            + [{"regle": m["regle"], "statut_revue": "non renseignée — source officielle requise"} for m in manquantes]
            + [{"regle": n["regle"], "statut_revue": "non approuvée (mode officiel)"} for n in non_approuvees],
        }
    statuts = [a["statut"] for a in affirmations]
    contexte_essai = any(not c["approuve"] for c in contexte)
    essai = mode == "essai" or "ESSAI" in statuts or "INCONNU" in statuts or piste is not None or contexte_essai
    if essai:
        marquage = MARQUAGE_ESSAI
    elif "APPROUVE" in statuts:
        marquage = _MARQUAGE_APPROUVE
    else:
        marquage = _MARQUAGE_DONNEES
    sortie = {
        "schema": "m5-analyse-fiscale/1",
        "version": VERSION,
        "sujet": sujet,
        "titre": fiche["titre"],
        "mode": mode,
        "date_reference": aujourd_hui,
        "essai": essai,
        "marquage": marquage,
        "affirmations": affirmations,
        "piste": piste,
        "contexte_documentaire": contexte,
        "inconnus": [a["texte"] for a in affirmations if a["statut"] == "INCONNU"],
        "hypotheses": hypotheses,
        "questions_pour_le_cpa": list(fiche["questions"]),
        "regles_non_renseignees": manquantes,
        "mention_comptable": analyse.MENTION_COMPTABLE,
        "garde": (
            "Aucune recommandation : analyse de situation sourcée. Aucune règle n'est estimée ; une source non "
            "approuvée est marquée « ESSAI/non approuvé »."
        ),
    }
    return sortie, None
