"""Moteur de rapprochement bancaire de M5 : un relevé normalisé contre les lignes du compte Banque du grand livre.

Module pur et DÉTERMINISTE : mêmes entrées, même rapprochement, même reçu, sur toute machine. Aucune horloge, aucun
registre, aucun réseau, aucune écriture. L'adaptateur (`outils_operations.py`) lui apporte le relevé
(`releve_bancaire.lire_releve`), les lignes du livre et les pièces ouvertes ; il en tire un ÉTAT DE RAPPROCHEMENT et un
reçu rejouable (`recu_calcul`).

Règles d'appariement, appliquées dans cet ordre, chacune EXPLIQUÉE dans le résultat (`regle`, `explication`,
`confiance`). La confiance n'est pas une probabilité : elle est fixée par la règle (`haute`, `moyenne`, `a_confirmer`).

| Règle | Critère | Confiance |
|---|---|---|
| R1 `montant_date_reference` | même montant signé, même date, et une référence de la banque (numéro de 4 caractères ou
  plus contenant un chiffre) figure dans le libellé ou la pièce du livre | haute |
| R2 `montant_reference` | même montant, même référence, dates à moins de `fenetre_jours` | haute |
| R3 `montant_date_proche` | même montant, dates à moins de `fenetre_jours` ; candidat unique, ou candidats
  interchangeables appariés dans l'ordre (alors `ambigu`) | moyenne (a_confirmer si ambigu) |
| R4 `somme_de_lignes` | le montant de la banque est la somme de 2 à 4 lignes du livre (même signe, dates à moins de
  `fenetre_jours`) ; une seule combinaison possible | moyenne |
| R5 `element_anterieur_en_circulation` | même montant, ligne du livre antérieure ou égale, à moins de
  `anciennete_max_jours` : un chèque ou un dépôt en circulation d'une période précédente ; candidat unique |
  a_confirmer |

Ce qui reste est un ÉCART nommé, jamais absorbé : lignes de la banque absentes du livre (frais, intérêts,
encaissements non comptabilisés — avec des PISTES parmi les factures ouvertes de même montant, jamais appliquées),
lignes du livre absentes de la banque (dépôts en transit, chèques en circulation), et l'écart résiduel du relevé
ajusté contre le livre ajusté. Un frais bancaire n'est classé que si l'appelant a DÉCLARÉ ses motifs et son compte
de charge : rien n'est supposé.

La confirmation (« ce rapprochement est bon ») est un geste HUMAIN (N4) : le moteur ne la produit jamais.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import encodage, recu_calcul, verdicts_operations

__all__ = ["VERSION", "FENETRE_MAX", "rapprocher", "empreinte_livre"]

VERSION = "1.0.0"
FENETRE_MAX = 30
ANCIENNETE_MAX = 365
_CANDIDATS_SOMME_MAX = 20
_TAILLE_SOMME_MAX = 4
_LISTE_MAX = 200
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_JETON = re.compile(r"[A-Z0-9][A-Z0-9._:/-]{3,}")
_METHODE = (
    "Appariement déterministe en cinq règles ordonnées (montant et date et référence ; montant et référence ; montant "
    "et date proche ; somme de 2 à 4 lignes ; élément antérieur en circulation) ; solde du relevé + dépôts en transit "
    "− chèques en circulation, contre solde du livre + opérations de la banque non comptabilisées ; écart résiduel."
)


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_operations.construire_verdict(code, detail=detail)


def _txt(valeur: Decimal) -> str:
    return format(valeur.quantize(_CENT, rounding=ROUND_HALF_UP), "f")


def _jours(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def _jetons(texte: str) -> set[str]:
    return {j for j in _JETON.findall(texte.upper()) if any(c.isdigit() for c in j)}


def empreinte_livre(livre: Sequence[Mapping[str, Any]]) -> str:
    """L'empreinte des lignes du livre qu'un rapprochement a vues (ordre canonique)."""
    return encodage.empreinte(
        "m5.rapprochement.livre.v1",
        sorted([[ligne["cle"], ligne["date"], ligne["montant"], ligne["statut"]] for ligne in livre]),
    )


def _valider_parametres(
    fenetre_jours: Any,
    anciennete_max_jours: Any,
    motifs_frais: Any,
    compte_frais: Any,
) -> dict[str, str] | None:
    if type(fenetre_jours) is not int or not 0 <= fenetre_jours <= FENETRE_MAX:
        return _verdict("REJ-BANQUE-FENETRE-INVALIDE", f"fenetre_jours : entier de 0 à {FENETRE_MAX}")
    if type(anciennete_max_jours) is not int or not 0 <= anciennete_max_jours <= ANCIENNETE_MAX:
        return _verdict("REJ-BANQUE-FENETRE-INVALIDE", f"anciennete_max_jours : entier de 0 à {ANCIENNETE_MAX}")
    if (
        not isinstance(motifs_frais, (list, tuple))
        or len(motifs_frais) > 20
        or not all(isinstance(m, str) and 3 <= len(m.strip()) <= 60 for m in motifs_frais)
    ):
        return _verdict("REJ-OPS-ENTREE-INVALIDE", "motifs_frais : au plus 20 textes de 3 à 60 caractères")
    if motifs_frais and (not isinstance(compte_frais, str) or not re.fullmatch(r"[1-9][0-9]{3}", compte_frais)):
        return _verdict(
            "REJ-OPS-CONFIGURATION-A-DECLARER",
            "des motifs de frais bancaires sont déclarés sans le compte de charge où les ranger : "
            "déclarer compte_frais_bancaires (un compte du plan, jamais supposé)",
        )
    return None


def _comparer_ordre(ligne: Mapping[str, Any]) -> tuple[str, int]:
    return ligne["date"], ligne["ligne"]


def rapprocher(
    releve: Mapping[str, Any],
    livre: Sequence[Mapping[str, Any]],
    *,
    solde_livre: Decimal,
    fenetre_jours: int,
    anciennete_max_jours: int,
    motifs_frais: Sequence[str] = (),
    compte_frais: str | None = None,
    ouverts_clients: Sequence[Mapping[str, Any]] = (),
    ouverts_fournisseurs: Sequence[Mapping[str, Any]] = (),
    cles_deja_rapprochees: Sequence[str] = (),
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Rapproche `releve` et `livre` (lignes `{cle, ecriture_id, date, montant (Decimal, + = entrée à la banque),
    libelle, piece, statut}`) : l'état de rapprochement et son reçu, ou le refus. `solde_livre` est le solde du compte
    Banque du livre à la fin du relevé (toutes les lignes datées au plus tard ce jour-là). `cles_deja_rapprochees` :
    les lignes du livre déjà constatées par un rapprochement antérieur (elles ne sont plus « en circulation »)."""
    refus = _valider_parametres(fenetre_jours, anciennete_max_jours, motifs_frais, compte_frais)
    if refus is not None:
        return None, refus
    fin = releve["date_fin"]
    exclues = set(cles_deja_rapprochees)
    banque = sorted(
        ({**ligne, "montant": Decimal(ligne["montant"])} for ligne in releve["lignes"]), key=_comparer_ordre
    )
    dispo = sorted(
        (ligne for ligne in livre if ligne["cle"] not in exclues and ligne["date"] <= fin),
        key=lambda ligne: (ligne["date"], ligne["cle"]),
    )
    libres = {ligne["cle"]: ligne for ligne in dispo}
    appariements: list[dict[str, Any]] = []
    ambigus: list[dict[str, Any]] = []
    restantes = {ligne["ligne"]: ligne for ligne in banque}

    def apparier(
        ligne_banque: Mapping[str, Any],
        cles: list[str],
        regle: str,
        confiance: str,
        explication: str,
        ambigu: bool = False,
    ) -> None:
        appariements.append(
            {
                "ligne_banque": ligne_banque["ligne"],
                "cles_livre": list(cles),
                "regle": regle,
                "confiance": confiance,
                "ambigu": ambigu,
                "explication": explication,
                "montant": _txt(ligne_banque["montant"]),
                "date_banque": ligne_banque["date"],
            }
        )
        for cle in cles:
            del libres[cle]
        del restantes[ligne_banque["ligne"]]

    def candidats(ligne_banque: Mapping[str, Any], fenetre: int | None, reference: bool) -> list[Mapping[str, Any]]:
        jetons = _jetons(ligne_banque["description"] + " " + ligne_banque["reference"])
        sortis = []
        for candidat in libres.values():
            if candidat["montant"] != ligne_banque["montant"]:
                continue
            if fenetre is not None and _jours(candidat["date"], ligne_banque["date"]) > fenetre:
                continue
            if reference:
                texte = (candidat["libelle"] + " " + candidat["piece"]).upper()
                if not any(j in texte for j in jetons):
                    continue
            sortis.append(candidat)
        return sorted(sortis, key=lambda c: (_jours(c["date"], ligne_banque["date"]), c["date"], c["cle"]))

    # R1 : montant, date et référence
    for ligne in list(restantes.values()):
        trouves = [c for c in candidats(ligne, 0, True)]
        if trouves:
            apparier(
                ligne,
                [trouves[0]["cle"]],
                "montant_date_reference",
                "haute",
                "même montant, même date et une référence de la banque figure dans le libellé ou la pièce du livre"
                + (" (plusieurs lignes identiques du livre : appariée dans l'ordre)" if len(trouves) > 1 else ""),
                ambigu=len(trouves) > 1,
            )
    # R2 : montant et référence, dates proches
    for ligne in list(restantes.values()):
        trouves = candidats(ligne, fenetre_jours, True)
        if trouves:
            apparier(
                ligne,
                [trouves[0]["cle"]],
                "montant_reference",
                "haute",
                f"même montant et une référence commune, dates à {_jours(trouves[0]['date'], ligne['date'])} "
                f"jour(s) d'écart (fenêtre {fenetre_jours})",
                ambigu=len(trouves) > 1,
            )
    # R3 : montant et date proche
    for ligne in list(restantes.values()):
        trouves = candidats(ligne, fenetre_jours, False)
        if not trouves:
            continue
        plus_proche = _jours(trouves[0]["date"], ligne["date"])
        egaux = [c for c in trouves if _jours(c["date"], ligne["date"]) == plus_proche]
        if len(egaux) == 1:
            apparier(
                ligne,
                [egaux[0]["cle"]],
                "montant_date_proche",
                "moyenne",
                f"même montant, dates à {plus_proche} jour(s) d'écart (fenêtre {fenetre_jours}), aucune référence "
                "commune",
            )
        else:
            apparier(
                ligne,
                [egaux[0]["cle"]],
                "montant_date_proche",
                "a_confirmer",
                f"même montant, {len(egaux)} lignes du livre interchangeables à {plus_proche} jour(s) : appariée "
                "dans l'ordre ; le total ne change pas, la pièce visée est à confirmer",
                ambigu=True,
            )
    # R4 : somme de lignes du livre
    for ligne in list(restantes.values()):
        signe = ligne["montant"] > 0
        proches = [
            c
            for c in libres.values()
            if (c["montant"] > 0) == signe and _jours(c["date"], ligne["date"]) <= fenetre_jours
        ][:_CANDIDATS_SOMME_MAX]
        proches.sort(key=lambda c: (_jours(c["date"], ligne["date"]), c["date"], c["cle"]))
        proches = proches[:_CANDIDATS_SOMME_MAX]
        trouves_somme: list[tuple[str, ...]] = []
        for taille in range(2, _TAILLE_SOMME_MAX + 1):
            for combinaison in itertools.combinations(proches, taille):
                if sum((c["montant"] for c in combinaison), _ZERO) == ligne["montant"]:
                    trouves_somme.append(tuple(sorted(c["cle"] for c in combinaison)))
            if trouves_somme:
                break
        uniques = sorted(set(trouves_somme))
        if len(uniques) == 1:
            apparier(
                ligne,
                list(uniques[0]),
                "somme_de_lignes",
                "moyenne",
                f"le montant est la somme de {len(uniques[0])} lignes du livre à moins de {fenetre_jours} "
                "jour(s) ; une seule combinaison possible",
            )
        elif len(uniques) > 1:
            ambigus.append(
                {
                    "ligne_banque": ligne["ligne"],
                    "combinaisons": [list(u) for u in uniques[:5]],
                    "explication": f"{len(uniques)} combinaisons de lignes du livre donnent ce montant : "
                    "non appariée, à trancher par une personne",
                }
            )
    # R5 : élément antérieur en circulation
    for ligne in list(restantes.values()):
        trouves = [
            c
            for c in candidats(ligne, None, False)
            if c["date"] <= ligne["date"] and _jours(c["date"], ligne["date"]) <= anciennete_max_jours
        ]
        if len(trouves) == 1:
            apparier(
                ligne,
                [trouves[0]["cle"]],
                "element_anterieur_en_circulation",
                "a_confirmer",
                f"même montant, ligne du livre datée de {_jours(trouves[0]['date'], ligne['date'])} jour(s) "
                "avant : un chèque ou un dépôt en circulation d'une période précédente ?",
            )
        elif len(trouves) > 1:
            ambigus.append(
                {
                    "ligne_banque": ligne["ligne"],
                    "combinaisons": [[c["cle"]] for c in trouves[:5]],
                    "explication": f"{len(trouves)} lignes antérieures du livre portent ce montant : non "
                    "appariée, à trancher par une personne",
                }
            )

    # Ce qui reste : écarts nommés
    motifs = [m.strip().upper() for m in motifs_frais]
    frais_suggeres: list[dict[str, Any]] = []
    non_comptabilisees: list[dict[str, Any]] = []
    for ligne in restantes.values():
        texte = ligne["description"].upper()
        entree = {
            "ligne": ligne["ligne"],
            "date": ligne["date"],
            "montant": _txt(ligne["montant"]),
            "description": ligne["description"],
            "reference": ligne["reference"],
        }
        if ligne["montant"] < 0 and motifs and any(m in texte for m in motifs):
            frais_suggeres.append(
                {
                    **entree,
                    "compte_charge": compte_frais,
                    "explication": "le libellé contient un motif de frais déclaré par l'entreprise",
                }
            )
            continue
        entree["pistes"] = _pistes(ligne, ouverts_clients, ouverts_fournisseurs)
        non_comptabilisees.append(entree)
    suspens = [ligne for ligne in libres.values()]
    depots_transit = [c for c in suspens if c["montant"] > 0]
    cheques = [c for c in suspens if c["montant"] < 0]
    total_depots = sum((c["montant"] for c in depots_transit), _ZERO)
    total_cheques = sum((-c["montant"] for c in cheques), _ZERO)
    net_banque_non_compta = sum((Decimal(e["montant"]) for e in non_comptabilisees), _ZERO)
    net_frais = sum((Decimal(e["montant"]) for e in frais_suggeres), _ZERO)
    solde_releve = None if releve.get("solde_fin") is None else Decimal(releve["solde_fin"])
    releve_ajuste = None if solde_releve is None else solde_releve + total_depots - total_cheques
    livre_ajuste = solde_livre + net_banque_non_compta + net_frais
    ecart = None if releve_ajuste is None else releve_ajuste - livre_ajuste
    etat_calcule = "INCOMPLET" if ecart is None else ("EQUILIBRE" if ecart == 0 else "ECART")

    def borner(liste: list[Any]) -> tuple[list[Any], int]:
        return liste[:_LISTE_MAX], max(0, len(liste) - _LISTE_MAX)

    cles_rapprochees = sorted({cle for a in appariements for cle in a["cles_livre"]})
    compte = {
        r: sum(1 for a in appariements if a["regle"] == r)
        for r in (
            "montant_date_reference",
            "montant_reference",
            "montant_date_proche",
            "somme_de_lignes",
            "element_anterieur_en_circulation",
        )
    }
    transit, transit_reste = borner([_vue_livre(c) for c in depots_transit])
    circulation, circulation_reste = borner([_vue_livre(c) for c in cheques])
    non_compta, non_compta_reste = borner(non_comptabilisees)
    etat = {
        "periode": {"debut": releve["date_debut"], "fin": fin},
        "compte_masque": releve.get("compte_masque"),
        "releve": {
            "sha256": releve["sha256"],
            "nom": releve["nom"],
            "format": releve["format"],
            "lignes": len(releve["lignes"]),
            "solde_fin": releve.get("solde_fin"),
            "solde_fin_source": releve.get("solde_fin_source"),
        },
        "parametres": {
            "fenetre_jours": fenetre_jours,
            "anciennete_max_jours": anciennete_max_jours,
            "motifs_frais": sorted(m.strip() for m in motifs_frais),
            "compte_frais": compte_frais,
        },
        "appariements": {
            "nombre": len(appariements),
            "par_regle": compte,
            "a_confirmer": sum(1 for a in appariements if a["confiance"] == "a_confirmer"),
        },
        "ambigus": ambigus[:20],
        "depots_en_transit": {
            "nombre": len(depots_transit),
            "total": _txt(total_depots),
            "lignes": transit,
            "reste": transit_reste,
        },
        "cheques_en_circulation": {
            "nombre": len(cheques),
            "total": _txt(total_cheques),
            "lignes": circulation,
            "reste": circulation_reste,
        },
        "non_comptabilise_a_la_banque": {
            "nombre": len(non_comptabilisees),
            "net": _txt(net_banque_non_compta),
            "lignes": non_compta,
            "reste": non_compta_reste,
        },
        "frais_suggeres": {"nombre": len(frais_suggeres), "net": _txt(net_frais), "lignes": frais_suggeres[:50]},
        "solde_releve": None if solde_releve is None else _txt(solde_releve),
        "solde_livre": _txt(solde_livre),
        "releve_ajuste": None if releve_ajuste is None else _txt(releve_ajuste),
        "livre_ajuste": _txt(livre_ajuste),
        "ecart": None if ecart is None else _txt(ecart),
        "etat": etat_calcule,
        "cles_livre_rapprochees": cles_rapprochees,
        "explication_etat": {
            "EQUILIBRE": "le relevé ajusté et le livre ajusté concordent au cent près",
            "ECART": "un écart résiduel demeure : il est nommé, jamais absorbé ; à expliquer avant toute confirmation",
            "INCOMPLET": (
                "solde de fin du relevé non renseigné : l'écart n'est pas calculable (fournir solde_fin_declare)"
            ),
        }[etat_calcule],
    }
    avertissements = [
        "Rapprochement PRÉPARÉ : il devient fiable seulement après confirmation d'une personne (N4).",
        "Les confiances sont fixées par la règle d'appariement, ce ne sont pas des probabilités.",
    ]
    if any(a["confiance"] == "a_confirmer" for a in appariements):
        avertissements.append("Au moins un appariement est « a_confirmer » : vérifier la pièce avant de confirmer.")
    entrees = {
        "releve_sha256": releve["sha256"],
        "empreinte_livre": empreinte_livre([{**c, "montant": _txt(c["montant"])} for c in dispo]),
        "solde_livre": _txt(solde_livre),
        "cles_exclues": encodage.empreinte(sorted(exclues)),
        "ouverts": encodage.empreinte(
            [
                sorted(
                    (str(o.get("facture_id") or o.get("facture_fournisseur_id")), str(o["montant"]))
                    for o in (*ouverts_clients, *ouverts_fournisseurs)
                )
            ]
        ),
        "parametres": etat["parametres"],
    }
    resultat = {
        "etat": etat_calcule,
        "ecart": etat["ecart"],
        "appariements": len(appariements),
        "depots_en_transit": _txt(total_depots),
        "cheques_en_circulation": _txt(total_cheques),
        "non_comptabilise_net": _txt(net_banque_non_compta + net_frais),
        "empreinte_appariements": encodage.empreinte(
            "m5.rapprochement.appariements.v1", [[a["ligne_banque"], a["cles_livre"], a["regle"]] for a in appariements]
        ),
        "empreinte_etat": encodage.empreinte("m5.rapprochement.etat.v1", etat),
    }
    recu = recu_calcul.construire(
        moteur="rapprochement_bancaire",
        version_moteur=VERSION,
        methode=_METHODE,
        precision={"montants": "Decimal au cent, aucun flottant"},
        parametres=etat["parametres"],
        entrees=entrees,
        resultat=resultat,
        avertissements=avertissements,
    )
    return {"etat": etat, "appariements": appariements, "recu": recu}, None


def _vue_livre(ligne: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cle": ligne["cle"],
        "date": ligne["date"],
        "montant": _txt(ligne["montant"]),
        "libelle": ligne["libelle"],
        "statut": ligne["statut"],
    }


def _pistes(
    ligne: Mapping[str, Any], clients: Sequence[Mapping[str, Any]], fournisseurs: Sequence[Mapping[str, Any]]
) -> list[dict[str, str]]:
    montant = ligne["montant"]
    pistes: list[dict[str, str]] = []
    if montant > 0:
        for facture in clients:
            if Decimal(str(facture["montant"])) == montant:
                pistes.append(
                    {
                        "genre": "facture_client",
                        "reference": str(facture["facture_id"]),
                        "note": "un encaissement possible de cette facture ouverte ; l'enregistrer est N5",
                    }
                )
    else:
        for facture in fournisseurs:
            if Decimal(str(facture["montant"])) == -montant:
                pistes.append(
                    {
                        "genre": "facture_fournisseur",
                        "reference": str(facture["facture_fournisseur_id"]),
                        "note": "un paiement possible de cette facture ouverte ; hors de M5 (N5)",
                    }
                )
    return sorted(pistes, key=lambda p: p["reference"])[:5]
