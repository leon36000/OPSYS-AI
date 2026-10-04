"""Composition sans calculs financiers du rapport CFO M5.16 à partir des vues canoniques."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

RUBRIQUES_OFFICIELLES = {
    1: "Question posée",
    2: "Résumé exécutif",
    3: "Recommandation",
    4: "Niveau de confiance",
    5: "Données utilisées",
    6: "Données manquantes",
    7: "Hypothèses",
    8: "Scénario prudent",
    9: "Scénario normal",
    10: "Scénario optimiste",
    11: "Cashflow 13 semaines",
    12: "Projection 6 mois",
    13: "Projection 12 mois",
    14: "Projection 24 mois",
    15: "Impact taxes",
    16: "Impact paie",
    17: "Impact dette",
    18: "Impact marge",
    19: "Impact croissance",
    20: "Risques principaux",
    21: "Conditions avant d'agir",
    22: "Questions CPA/fiscaliste",
    23: "Questions banque/prêteur",
    24: "Plan d'action recommandé",
    25: "Validation requise",
}
TITRES = tuple(RUBRIQUES_OFFICIELLES.values())


def empreinte(valeur: Any) -> str:
    """Empreinte déterministe des seules entrées JSON canoniques utilisées par le rapport."""
    octets = json.dumps(valeur, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(octets).hexdigest()


def _liste(valeur: Any) -> list[Any]:
    return list(valeur) if isinstance(valeur, (list, tuple)) else []


def _composante(cash: Mapping[str, Any], identifiant: str) -> Mapping[str, Any] | None:
    for item in _liste(cash.get("composantes")):
        if isinstance(item, Mapping) and item.get("id") == identifiant:
            return item
    return None


def _ref(*refs: Mapping[str, Any], registres: Sequence[str] | None = None) -> list[dict[str, Any]]:
    permises = set(registres) if registres is not None else None
    resultat = []
    for item in refs:
        if not isinstance(item, Mapping):
            continue
        registre = item.get("registre")
        if not isinstance(registre, str) or (permises is not None and registre not in permises):
            continue
        resultat.append(
            {
                cle: item[cle]
                for cle in ("departement", "registre", "taille", "tete")
                if cle in item and (isinstance(item[cle], (str, int)) or item[cle] is None)
            }
        )
    return resultat


def _section(
    numero: int,
    contenu: Any = None,
    *,
    statut: str = "INCONNU",
    sources: Sequence[Mapping[str, Any]] | Mapping[str, Any] = (),
    manque: Sequence[str] = (),
    hypotheses: Sequence[str] = (),
    limites: Sequence[str] = (),
) -> dict[str, Any]:
    section = {
        "numero": numero,
        "titre": TITRES[numero - 1],
        "statut": statut,
        "contenu": contenu,
    }
    for cle, valeurs in (
        ("source_refs", sources),
        ("hypotheses", hypotheses),
        ("manque", manque),
        ("limites", limites),
    ):
        if valeurs:
            if cle == "source_refs" and isinstance(valeurs, Mapping):
                section[cle] = dict(valeurs)
            else:
                section[cle] = [dict(item) for item in valeurs] if cle == "source_refs" else list(valeurs)
    return section


def _liste_manques(cash: Mapping[str, Any], prevision: Mapping[str, Any] | None) -> list[str]:
    resultat: list[str] = []
    index_codes: dict[str, int] = {}
    for item in _liste(cash.get("manque")):
        if not isinstance(item, (str, int)):
            continue
        texte = str(item)
        prefixe, separateur, code = texte.partition(": ")
        cle = code if separateur and code.startswith("REJ-") else texte
        index_codes[cle] = len(resultat)
        resultat.append(texte)
    if isinstance(prevision, Mapping):
        for groupe in _liste(prevision.get("manque")):
            if isinstance(groupe, Mapping):
                code = groupe.get("code")
                if isinstance(code, str) and code:
                    debut = groupe.get("a_partir_de_semaine")
                    nombre = groupe.get("nombre")
                    contexte = f" dès semaine {debut}" if isinstance(debut, int) else ""
                    compte = f" ({nombre} flux)" if isinstance(nombre, int) else ""
                    info = f"prévision{contexte}{compte}"
                    if code in index_codes:
                        position = index_codes[code]
                        resultat[position] += f"; {info}"
                    else:
                        index_codes[code] = len(resultat)
                        resultat.append(f"{code}: {info}")
                else:
                    detail = groupe.get("detail")
                    if isinstance(detail, str) and detail:
                        resultat.append(detail[:120])
    return list(dict.fromkeys(resultat))


def _extraits_cash(cash: Mapping[str, Any]) -> dict[str, Any]:
    composantes = []
    for item in _liste(cash.get("composantes")):
        if not isinstance(item, Mapping):
            continue
        source = item.get("source")
        fraicheur = item.get("fraicheur")
        composantes.append(
            {
                "id": item.get("id"),
                "statut": item.get("statut"),
                "montant_cad": item.get("montant"),
                "source": (source.get("description") or "")[:120] if isinstance(source, Mapping) else None,
                "fraicheur": fraicheur.get("derniere_piece") if isinstance(fraicheur, Mapping) else None,
            }
        )
    solde = cash.get("solde")
    return {
        "calculable": cash.get("calculable") is True,
        "solde_cad": solde.get("montant") if isinstance(solde, Mapping) else None,
        "cash_libre_cad": cash.get("cash_libre"),
        "en_deficit": cash.get("en_deficit"),
        "composantes": composantes,
    }


def _semaines_courtes(semaines: Sequence[Any]) -> list[list[Any]]:
    resultat = []
    for semaine in semaines:
        if not isinstance(semaine, Mapping):
            continue
        ligne = [semaine.get("semaine"), semaine.get("du")]
        if semaine.get("statut") == "CALCULE":
            ligne.extend([semaine.get("entrees"), semaine.get("sorties"), semaine.get("solde_fin")])
        else:
            ligne.extend([None, None, None])
        resultat.append(ligne)
    return resultat


def composer(
    *,
    question_posee: str,
    aujourd_hui: str,
    cash: Mapping[str, Any],
    comptes_a_recevoir: Mapping[str, Any] | None,
    comptes_a_payer: Mapping[str, Any] | None,
    prevision: Mapping[str, Any] | None,
    source_refs: Sequence[Mapping[str, Any]],
    mention: str,
    manques_source: Sequence[str] = (),
    configuration_id: str = "",
    calendrier_obligations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Présente les résultats canoniques et leurs trous; ne calcule ni scénario ni recommandation."""
    if not isinstance(question_posee, str) or not 1 <= len(question_posee.strip()) <= 1000:
        raise ValueError("question_posee doit contenir de 1 à 1000 caractères")
    try:
        jour = date.fromisoformat(aujourd_hui)
    except (TypeError, ValueError) as exc:
        raise ValueError("aujourd_hui doit être une date ISO") from exc
    if jour.isoformat() != aujourd_hui or not isinstance(cash, Mapping):
        raise ValueError("instantané financier invalide")

    refs_completes = _ref(*source_refs)
    refs = {
        "colonnes": ["departement", "registre", "taille", "tete"],
        "lignes": [
            [source.get("departement"), source.get("registre"), source.get("taille"), source.get("tete")]
            for source in refs_completes
        ],
    } if refs_completes else {}
    identite_snapshot = {
        "aujourd_hui": aujourd_hui,
        "source_refs": refs_completes,
        "cash_libre_id": cash.get("cash_libre_id"),
        "prevision_id": prevision.get("prevision_id") if isinstance(prevision, Mapping) else None,
        "configuration_id": configuration_id,
    }
    snapshot_id = empreinte(identite_snapshot)
    cash_resume = _extraits_cash(cash)
    manques = list(
        dict.fromkeys(
            [
                *_liste_manques(cash, prevision),
                *manques_source,
                "Méthode scénarios/recommandation/confiance absente.",
                "Prévision max. 26 sem.; 12/24 mois inconnus.",
                "Impacts taxes, paie nette, dette, marge, croissance/prêteur inconnus.",
                "Risques/conditions du mandat inconnus.",
            ]
        )
    )
    hypotheses_brutes = _liste(cash.get("hypotheses"))
    hypotheses = [
        "Taxes: AR après remise; crédits AP saisies.",
        "TPS/TVQ séparées; solde négatif inconnu.",
        "AR hors solde; paiement futur inconnu.",
        "Réserves non classées: double compte possible.",
    ] if hypotheses_brutes else []
    refs_utilisees = _section(
        5,
        {"aujourd_hui": aujourd_hui, "devise": "CAD"},
        statut="CONNU" if refs else "INCONNU",
        sources=refs,
        manque=[] if refs else ["aucune référence de source disponible"],
    )
    sections: list[dict[str, Any]] = [
        _section(1, {"question_posee_ref": "question_posee"}, statut="CONNU"),
        _section(
            2,
            {
                "cash_libre_cad": cash_resume["cash_libre_cad"],
                "cash_libre_calculable": cash_resume["calculable"],
                "AR": None if comptes_a_recevoir is None else [
                    comptes_a_recevoir.get("nombre"), comptes_a_recevoir.get("total_a_recevoir_cad")
                ],
                "AP_cad": None if comptes_a_payer is None else comptes_a_payer.get("a_payer_apres_taxes_cad"),
            },
            statut="PARTIEL",
        ),
        _section(3, None),
        _section(4, None),
        refs_utilisees,
        _section(6, None, statut="CONNU",
                 manque=manques or ["aucun manque explicite signalé"]),
        _section(7, None, statut="PARTIEL" if hypotheses else "INCONNU", hypotheses=hypotheses),
        _section(8, None),
        _section(9, None),
        _section(10, None),
    ]

    semaines = _liste(prevision.get("semaines")) if isinstance(prevision, Mapping) else []
    semaines_13 = semaines[:13]
    contient_flux_calcules = any(
        isinstance(semaine, Mapping) and semaine.get("statut") == "CALCULE" for semaine in semaines
    )
    calculs_13 = any(
        isinstance(semaine, Mapping) and semaine.get("statut") == "CALCULE" for semaine in semaines_13
    )
    statut_prevision = "PARTIEL" if semaines_13 and calculs_13 else "INCONNU"
    lignes_13 = _semaines_courtes(semaines_13)
    contenu_13 = None if statut_prevision == "INCONNU" else {
        "horizon_semaines": 13,
        "semaines_couvertes": len(semaines_13),
        "statut_par_defaut": "CALCULE",
        "debut_premiere_semaine": lignes_13[0][1],
        "pas_jours": 7,
        "entrees_cad": [ligne[2] for ligne in lignes_13],
        "sorties_cad": [ligne[3] for ligne in lignes_13],
        "solde_fin_cad": [ligne[4] for ligne in lignes_13],
        "statuts_non_calcules": [
            [semaine.get("semaine"), semaine.get("statut")]
            for semaine in semaines_13
            if isinstance(semaine, Mapping) and semaine.get("statut") != "CALCULE"
        ],
    }
    if contenu_13 is not None and not contenu_13["statuts_non_calcules"]:
        del contenu_13["statuts_non_calcules"]
    sections.append(
        _section(11, contenu_13, statut=statut_prevision,
                 manque=["horizon partiel; voir les manques globaux"]
                 if statut_prevision != "INCONNU" and len(semaines_13) < 13 else [])
    )
    derniere_semaine = semaines[25] if len(semaines) >= 26 else None
    sections.append(
        _section(12, None)
        if not isinstance(derniere_semaine, Mapping) or not contient_flux_calcules
        else _section(
            12,
            {"horizon_semaines": 26, "fin_horizon": prevision.get("fin_horizon"),
             "derniere_semaine": _semaines_courtes([derniere_semaine])[0],
             "statut_derniere_semaine": derniere_semaine.get("statut")},
            statut="PARTIEL",
        )
    )
    sections.extend(
        [
            _section(13, None),
            _section(14, None),
        ]
    )

    taxes = _composante(cash, "taxes_a_remettre")
    paies = _composante(cash, "paies")
    dettes = _composante(cash, "dettes")
    def extrait_composante(composante: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if composante is None:
            return None
        source, fraicheur = composante.get("source"), composante.get("fraicheur")
        return {
            "statut": composante.get("statut"),
            "montant_cad": composante.get("montant"),
            "source": (source.get("description") or "")[:80] if isinstance(source, Mapping) else None,
            "fraicheur": fraicheur.get("derniere_piece") if isinstance(fraicheur, Mapping) else None,
        }

    sections.append(
        _section(15, None if taxes is None else {"composante_observee": extrait_composante(taxes)},
                 statut="PARTIEL" if taxes is not None else "INCONNU",
                 limites=["Calendrier à valider par le CPA; pas de conseil fiscal."])
    )
    obligations = calendrier_obligations.get("obligations", []) if isinstance(calendrier_obligations, Mapping) else []
    obligations_par_id = {
        item.get("id"): item for item in obligations
        if isinstance(item, Mapping) and item.get("id") in {"paies", "das"}
    } if isinstance(obligations, (list, tuple)) else {}
    paie_das: dict[str, dict[str, Any]] = {}
    for identifiant in ("paies", "das"):
        item = obligations_par_id.get(identifiant)
        if not isinstance(item, Mapping):
            continue
        periode = item.get("periode") if isinstance(item.get("periode"), Mapping) else {}
        montant = item.get("montant")
        source_montant = item.get("source_montant") if isinstance(item.get("source_montant"), Mapping) else {}
        source_echeance = item.get("source_echeance") if isinstance(item.get("source_echeance"), Mapping) else {}
        codes_manque = [
            manque.get("code") for manque in item.get("manque", []) if isinstance(manque, Mapping)
        ] if isinstance(item.get("manque"), (list, tuple)) else []
        if not any((montant, item.get("echeance"), item.get("autorite"), source_montant.get("description"),
                    source_montant.get("au"), any(source_echeance.values()),
                    periode.get("debut"), periode.get("fin"), item.get("annee"), item.get("version"))):
            continue
        paie_das[identifiant] = {
            "statut": item.get("statut"),
            "montant_declare_cad": montant,
            "montant_utilisable_cad": (
                item.get("montant_utilisable")
                if item.get("statut") in {"DOCUMENTEE_A_VALIDER", "ECHEANCE_PASSEE_A_VERIFIER"}
                else None
            ),
            "echeance": item.get("echeance"),
            "periode": [periode.get("debut"), periode.get("fin")]
            if periode.get("debut") is not None or periode.get("fin") is not None else None,
            "autorite": item.get("autorite"),
            "source_montant": [source_montant.get("description"), source_montant.get("au")]
            if source_montant.get("description") is not None or source_montant.get("au") is not None else None,
            "source_echeance": [
                source_echeance.get("description"), source_echeance.get("consultee_le"),
                source_echeance.get("applicable_du"), source_echeance.get("applicable_jusqu_au"),
            ] if any(value is not None for value in source_echeance.values()) else None,
            "echeance_statut": item.get("echeance_statut"),
            "annee": item.get("annee"),
            "version": item.get("version"),
            "manque": codes_manque,
        }
    paie_documentee = bool(paie_das)
    paie_connue = paie_documentee or (paies is not None and paies.get("montant") is not None)

    def projection_obligations() -> dict[str, Any]:
        cles = list(paie_das)
        champs = ["s", "d", "u", "e", "t"]
        champs.extend(
            code for code, nom in (
                ("p", "periode"), ("a", "autorite"), ("q", "source_montant"),
                ("j", "source_montant_au"), ("x", "source_echeance"), ("y", "annee"), ("v", "version"),
            ) if any(
                (paie_das[cle].get("source_montant")[0 if nom == "source_montant" else 1]
                 if nom in {"source_montant", "source_montant_au"}
                 and paie_das[cle].get("source_montant") is not None else paie_das[cle].get(nom)) is not None
                for cle in cles
            )
        )
        codes_champs = {
            "s": "statut", "d": "montant_declare_cad", "u": "montant_utilisable_cad",
            "e": "echeance", "t": "echeance_statut", "p": "periode", "a": "autorite",
            "q": "source_montant", "j": "source_montant_au", "x": "source_echeance",
            "y": "annee", "v": "version",
        }
        statut_codes = {"INCOMPLETE": "i", "DOCUMENTEE_A_VALIDER": "d",
                        "ECHEANCE_PASSEE_A_VERIFIER": "p", "SOURCE_PERIMEE": "x"}
        echeance_codes = {"A_VENIR": "a", "PASSEE_A_VERIFIER": "p", "NON_DECLAREE": "n"}
        lignes = []
        for cle in cles:
            ligne = []
            for champ in champs:
                nom = codes_champs[champ]
                if champ == "q":
                    source = paie_das[cle].get("source_montant")
                    valeur = source[0] if source is not None else None
                elif champ == "j":
                    source = paie_das[cle].get("source_montant")
                    valeur = source[1] if source is not None else None
                else:
                    valeur = paie_das[cle].get(nom)
                if champ == "s":
                    valeur = statut_codes.get(valeur, valeur)
                elif champ == "t":
                    valeur = echeance_codes.get(valeur, valeur)
                ligne.append(valeur)
            lignes.append(ligne)

        suffixes = {
            "MONTANT-ABSENT": "m", "SOURCE-MONTANT-ABSENTE": "s", "ECHEANCE-ABSENTE": "e",
            "PERIODE-SOURCE-ABSENTE": "p", "SOURCE-INVALIDE": "i", "PERIODE-INVALIDE": "r",
            "DATE-SOURCE-INVALIDE": "d", "ANNEE-VERSION-INVALIDE": "a", "SOURCE-PERIMEE": "x",
        }
        positions = {code: 1 << index for index, code in enumerate(suffixes)}
        masques, autres_par_cle = [], []
        for cle in cles:
            prefixe = f"REJ-CALENDRIER-{cle.upper()}-"
            masque, autres = 0, []
            for code in paie_das[cle]["manque"]:
                suffixe = code.removeprefix(prefixe) if isinstance(code, str) and code.startswith(prefixe) else None
                bit = positions.get(suffixe) if suffixe is not None else None
                if bit is None:
                    autres.append(code)
                else:
                    masque |= bit
            masques.append(masque)
            autres_par_cle.append(autres)
        manques: int | list[int] | dict[str, Any]
        manques = masques[0] if masques and all(masque == masques[0] for masque in masques[1:]) else masques
        if any(autres_par_cle):
            manques = {"masques": manques, "codes_complets_par_ligne": autres_par_cle}
        aliases_cles = {"paies": "p", "das": "d"}
        return {"obligations_declarees": ["".join(aliases_cles[cle] for cle in cles), "".join(champs), lignes, manques]}

    contenu_paie = None
    if paie_connue:
        if calendrier_obligations is None:
            contenu_paie = {
                "paies_declarees": extrait_composante(paies),
                "obligations_declarees": {},
                "limites": ["montants déclaratifs, pas une paie nette calculée; aucune exécution officielle"],
            }
        else:
            contenu_paie = {
                **projection_obligations(),
                "limites": "Déclaratif; net non calculé; pas d'exécution officielle.",
            }
    sections.append(
        _section(
            16,
            contenu_paie,
            statut="PARTIEL" if paie_connue else "INCONNU",
        )
    )
    sections.append(
        _section(17, None if dettes is None else {"dettes_declarees": extrait_composante(dettes)},
                 statut="PARTIEL" if dettes is not None and dettes.get("montant") is not None else "INCONNU")
    )
    sections.extend(
        [
            _section(18, None),
            _section(19, None),
        ]
    )
    risques = []
    if cash_resume["en_deficit"] is True:
        risques.append("cash libre négatif selon les données et réserves actuelles")
    sections.extend(
        [
            _section(20, risques or None, statut="PARTIEL" if risques else "INCONNU"),
            _section(21, None),
            _section(22, None),
            _section(23, None),
            _section(24, None),
            _section(25, {"validation_humaine": "requise", "validation_CPA": "requise pour les faits fiscaux"},
                     statut="PARTIEL"),
        ]
    )

    return {
        "type": "DOSSIER_DECISION_CFO",
        "version_contrat": "v1",
        "question_posee": question_posee,
        "reference": {"aujourd_hui": aujourd_hui, "devise": "CAD", "snapshot_id": snapshot_id},
        "statut_global": "PREPARATOIRE",
        "rubriques": sections,
        "mention": mention,
    }
