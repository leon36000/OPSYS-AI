"""Validation DÉTERMINISTE d'une facture extraite à l'onboarding (VLM/LLM -> JSON) : rien n'est cru, tout est recalculé.

Module pur (ADR-0009, comme `comptes_a_payer.py`) : ni `opsys`, ni horloge, ni réseau. Le socle
(`opsys.ingestion_onboarding`) lui passe l'extraction du fournisseur de capacité, les taux versionnés, l'identité
fiscale déclarée de l'entreprise et le jour du dépôt ; ce module rend un VERDICT, jamais une facture corrigée.

Contrôles, tous exécutés (chaque incohérence est une raison distincte, avec les deux chiffres) :

1. schéma JSON STRICT (`opsys.facture/v1`) : clés exactes, types, montants en TEXTE décimal (jamais un flottant) ;
2. chaque ligne : quantité × prix unitaire arrondi au cent (`ROUND_HALF_UP`) = montant de la ligne ;
3. somme des lignes = sous-total ;
4. TPS et TVQ RECALCULÉES sur le sous-total par `taxes.calculer_taxes` (taux versionnés `taux_fiscaux.v1.yaml`,
   arrondi au cent `ROUND_HALF_UP`, la règle citée dans `taxes.py`), comparées au cent aux taxes imprimées ;
5. total imprimé = sous-total + taxes recalculées (le contrôle même de la saisie M5, `_controler_total`) ;
6. numéros TPS (`123456789 RT 0001`) et TVQ (`1234567890 TQ 0001`) : FORME seulement (aucun appel à l'ARC ni à Revenu
   Québec, aucun chiffre de contrôle supposé) ; une taxe facturée sans le numéro correspondant est signalée ;
7. dates : vraie date, pas après le jour du dépôt, pas plus de `ANCIENNETE_MAX_ANS` ans avant ; échéance pas avant la
   date ;
8. fournisseur identifiable (nom de l'émetteur) ; devise CAD ; sous-total strictement positif ;
9. SENS de la facture contre l'identité fiscale de l'entreprise (`entreprise.yaml`, clé `identite_fiscale`) : une
   facture que l'entreprise a ÉMISE n'est pas un compte à payer ; une facture adressée à quelqu'un d'autre non plus.

Aucune tolérance n'est inventée : un écart d'un cent est un écart. Le statut est `PRET` sans aucune raison,
`A_VERIFIER` sinon. Les lignes exonérées ou détaxées ne sont pas modélisées : leur écart de taxes est SIGNALÉ.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Any

from . import taxes

__all__ = ["ANCIENNETE_MAX_ANS", "CODES_VALIDATION", "SCHEMA", "normaliser_no_tps", "normaliser_no_tvq", "valider"]

SCHEMA = "opsys.facture/v1"
ANCIENNETE_MAX_ANS = 10
LIGNES_MAX = 200
CODES_VALIDATION: tuple[str, ...] = (
    "REJ-ING-FACTURE-SCHEMA",
    "REJ-ING-FACTURE-DEVISE",
    "REJ-ING-FACTURE-FOURNISSEUR-NON-IDENTIFIABLE",
    "REJ-ING-FACTURE-NUMERO-INVALIDE",
    "REJ-ING-FACTURE-DATE-INVALIDE",
    "REJ-ING-FACTURE-DATE-FUTURE",
    "REJ-ING-FACTURE-DATE-ANCIENNE",
    "REJ-ING-FACTURE-ECHEANCE-AVANT-DATE",
    "REJ-ING-FACTURE-LIGNE-MONTANT",
    "REJ-ING-FACTURE-SOMME-LIGNES",
    "REJ-ING-FACTURE-MONTANT-NON-POSITIF",
    "REJ-ING-FACTURE-TPS-ECART",
    "REJ-ING-FACTURE-TVQ-ECART",
    "REJ-ING-FACTURE-TOTAL-ECART",
    "REJ-ING-FACTURE-NO-TPS-FORME",
    "REJ-ING-FACTURE-NO-TVQ-FORME",
    "REJ-ING-FACTURE-NO-TPS-ABSENT",
    "REJ-ING-FACTURE-NO-TVQ-ABSENT",
    "REJ-ING-FACTURE-TAUX-INDISPONIBLES",
    "REJ-ING-FACTURE-EMISE-PAR-L-ENTREPRISE",
    "REJ-ING-FACTURE-DESTINATAIRE-NON-RECONNU",
)
_CODES = frozenset(CODES_VALIDATION)
_CENT = Decimal("0.01")
_CONTEXTE = Context(prec=80)
_MONTANT = re.compile(r"-?[0-9]{1,12}(\.[0-9]{1,2})?")
_QUANTITE = re.compile(r"-?[0-9]{1,9}(\.[0-9]{1,6})?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_NO_TPS = re.compile(r"([0-9]{9})RT([0-9]{4})")
_NO_TVQ = re.compile(r"([0-9]{10})TQ([0-9]{4})")
_RACINE = {"schema", "emetteur", "destinataire", "numero", "date", "devise", "lignes", "sous_total", "tps", "tvq",
           "total"}
_RACINE_OPTIONNELLE = {"echeance", "citations"}
_EMETTEUR = {"nom", "no_tps", "no_tvq"}
_EMETTEUR_OPTIONNEL = {"adresse"}
_DESTINATAIRE = {"nom"}
_DESTINATAIRE_OPTIONNEL = {"no_tps", "no_tvq"}
_LIGNE = {"description", "quantite", "prix_unitaire", "montant"}
_TEXTE_MAX = 300


def _raison(code: str, detail: str) -> dict[str, str]:
    if code not in _CODES:
        raise ValueError(f"raison hors catalogue : {code!r}")
    return {"code": code, "detail": detail}


def _compact(texte: str) -> str:
    return re.sub(r"[\s-]+", "", texte).upper()


def normaliser_no_tps(numero: str) -> str | None:
    correspondance = _NO_TPS.fullmatch(_compact(numero))
    return f"{correspondance.group(1)} RT {correspondance.group(2)}" if correspondance else None


def normaliser_no_tvq(numero: str) -> str | None:
    correspondance = _NO_TVQ.fullmatch(_compact(numero))
    return f"{correspondance.group(1)} TQ {correspondance.group(2)}" if correspondance else None


def _nom_compare(nom: str) -> str:
    simple = "".join(c for c in unicodedata.normalize("NFKD", nom) if not unicodedata.combining(c)).casefold()
    mots = re.sub(r"[^0-9a-z]+", " ", simple).split()
    while len(mots) > 1 and mots[-1] in {"inc", "ltee", "ltd", "enr", "senc", "limitee"}:
        mots.pop()
    return " ".join(mots)


def _texte(valeur: Any, *, requis: bool = True) -> bool:
    if valeur is None:
        return not requis
    return isinstance(valeur, str) and len(valeur) <= _TEXTE_MAX and valeur.isprintable() and (
        bool(valeur.strip()) or not requis)


def _cles(objet: Any, exactes: set[str], optionnelles: set[str], chemin: str) -> str | None:
    if not isinstance(objet, Mapping):
        return f"{chemin} : un objet est attendu"
    manquantes = exactes - set(objet)
    inconnues = set(objet) - exactes - optionnelles
    if manquantes or inconnues:
        return f"{chemin} : clés manquantes {sorted(manquantes)}, inconnues {sorted(inconnues)}"
    return None


def _schema(extraction: Any) -> str | None:
    """`None` si l'extraction a exactement la forme `opsys.facture/v1` ; sinon le premier écart, son chemin compris."""
    ecart = _cles(extraction, _RACINE, _RACINE_OPTIONNELLE, "facture")
    if ecart:
        return ecart
    if extraction["schema"] != SCHEMA:
        return f"facture.schema : {SCHEMA!r} attendu"
    ecart = (_cles(extraction["emetteur"], _EMETTEUR, _EMETTEUR_OPTIONNEL, "emetteur")
             or _cles(extraction["destinataire"], _DESTINATAIRE, _DESTINATAIRE_OPTIONNEL, "destinataire"))
    if ecart:
        return ecart
    for chemin, valeur, requis in (
        ("emetteur.nom", extraction["emetteur"]["nom"], False), ("emetteur.no_tps", extraction["emetteur"]["no_tps"],
                                                                 False),
        ("emetteur.no_tvq", extraction["emetteur"]["no_tvq"], False),
        ("emetteur.adresse", extraction["emetteur"].get("adresse"), False),
        ("destinataire.nom", extraction["destinataire"]["nom"], False),
        ("destinataire.no_tps", extraction["destinataire"].get("no_tps"), False),
        ("destinataire.no_tvq", extraction["destinataire"].get("no_tvq"), False),
        ("numero", extraction["numero"], False), ("date", extraction["date"], True),
        ("devise", extraction["devise"], True), ("echeance", extraction.get("echeance"), False),
    ):
        if not _texte(valeur, requis=requis):
            return f"{chemin} : texte imprimable de {_TEXTE_MAX} caractères au plus attendu"
    for champ in ("sous_total", "tps", "tvq", "total"):
        if not isinstance(extraction[champ], str) or _MONTANT.fullmatch(extraction[champ]) is None:
            return f"{champ} : montant en texte décimal attendu (ex. \"1234.50\"), jamais un nombre JSON"
    lignes = extraction["lignes"]
    if not isinstance(lignes, list) or not 1 <= len(lignes) <= LIGNES_MAX:
        return f"lignes : liste de 1 à {LIGNES_MAX} lignes attendue"
    for index, ligne in enumerate(lignes, 1):
        ecart = _cles(ligne, _LIGNE, set(), f"lignes[{index}]")
        if ecart:
            return ecart
        if not _texte(ligne["description"], requis=False):
            return f"lignes[{index}].description : texte imprimable attendu"
        for champ, gabarit in (("quantite", _QUANTITE), ("prix_unitaire", _QUANTITE), ("montant", _MONTANT)):
            if not isinstance(ligne[champ], str) or gabarit.fullmatch(ligne[champ]) is None:
                return f"lignes[{index}].{champ} : nombre en texte décimal attendu"
    if "citations" in extraction and not isinstance(extraction["citations"], Mapping):
        return "citations : un objet {champ: {page, extrait}} est attendu"
    return None


def _jour(texte: str | None) -> date | None:
    if not isinstance(texte, str) or _DATE.fullmatch(texte) is None:
        return None
    try:
        return date.fromisoformat(texte)
    except ValueError:
        return None


def _au_cent(valeur: Decimal) -> Decimal:
    return valeur.quantize(_CENT, rounding=ROUND_HALF_UP, context=_CONTEXTE)


def _direction(extraction: Mapping[str, Any], identite: Mapping[str, Any] | None) -> tuple[str, dict | None]:
    if identite is None:
        return "indeterminee", _raison("REJ-ING-FACTURE-DESTINATAIRE-NON-RECONNU", "identité fiscale de l'entreprise "
                                       "non déclarée (entreprise.yaml, clé identite_fiscale) : le sens de la facture "
                                       "ne peut pas être établi")
    nom_legal = _nom_compare(identite.get("nom_legal") or "")
    tps = normaliser_no_tps(identite.get("tps") or "")
    tvq = normaliser_no_tvq(identite.get("tvq") or "")
    emetteur, destinataire = extraction["emetteur"], extraction["destinataire"]

    def est_l_entreprise(bloc: Mapping[str, Any]) -> bool:
        return bool(
            (nom_legal and bloc.get("nom") and _nom_compare(bloc["nom"]) == nom_legal)
            or (tps and bloc.get("no_tps") and normaliser_no_tps(bloc["no_tps"]) == tps)
            or (tvq and bloc.get("no_tvq") and normaliser_no_tvq(bloc["no_tvq"]) == tvq))

    if est_l_entreprise(emetteur):
        return "client", _raison("REJ-ING-FACTURE-EMISE-PAR-L-ENTREPRISE", "l'émetteur est l'entreprise elle-même : "
                                 "c'est une facture CLIENT (compte à recevoir), pas un compte à payer")
    if est_l_entreprise(destinataire):
        return "fournisseur", None
    return "indeterminee", _raison("REJ-ING-FACTURE-DESTINATAIRE-NON-RECONNU", "ni l'émetteur ni le destinataire ne "
                                   "correspondent à l'identité fiscale déclarée de l'entreprise : à qui est-elle ?")


def valider(
    extraction: Any, *, dictionnaire_taux: Mapping[str, Any], identite: Mapping[str, Any] | None, jour_depot: date,
) -> dict[str, Any]:
    """`{"statut", "raisons", "direction", "facture"}` : `facture` est la LECTURE normalisée (textes, montants
    imprimés ET recalculés), `None` si le schéma est rompu. Ne lève jamais pour un contenu : toute anomalie est une
    raison."""
    ecart = _schema(extraction)
    if ecart is not None:
        return {"statut": "A_VERIFIER", "raisons": [_raison("REJ-ING-FACTURE-SCHEMA", ecart)],
                "direction": "indeterminee", "facture": None}
    raisons: list[dict[str, str]] = []
    emetteur = extraction["emetteur"]
    if extraction["devise"] != "CAD":
        raisons.append(_raison("REJ-ING-FACTURE-DEVISE", f"devise {extraction['devise']!r} : CAD seulement"))
    fournisseur = (emetteur["nom"] or "").strip()
    if not fournisseur:
        raisons.append(_raison("REJ-ING-FACTURE-FOURNISSEUR-NON-IDENTIFIABLE", "nom de l'émetteur absent"))
    numero = (extraction["numero"] or "").strip()
    if not numero or len(numero) > 64:
        raisons.append(_raison("REJ-ING-FACTURE-NUMERO-INVALIDE", "numéro de facture absent ou de plus de 64 "
                                                                  "caractères"))

    jour = _jour(extraction["date"])
    if jour is None:
        raisons.append(_raison("REJ-ING-FACTURE-DATE-INVALIDE", f"date {extraction['date']!r} : AAAA-MM-JJ réelle"))
    elif jour > jour_depot:
        raisons.append(_raison("REJ-ING-FACTURE-DATE-FUTURE", f"date {jour} postérieure au dépôt ({jour_depot})"))
    elif jour < jour_depot.replace(year=jour_depot.year - ANCIENNETE_MAX_ANS, day=min(jour_depot.day, 28)):
        raisons.append(_raison("REJ-ING-FACTURE-DATE-ANCIENNE", f"date {jour} : plus de {ANCIENNETE_MAX_ANS} ans avant "
                                                                f"le dépôt ({jour_depot})"))
    if extraction.get("echeance") is not None:
        echeance = _jour(extraction["echeance"])
        if echeance is None:
            raisons.append(_raison("REJ-ING-FACTURE-DATE-INVALIDE",
                                   f"échéance {extraction['echeance']!r} : AAAA-MM-JJ"))
        elif jour is not None and echeance < jour:
            raisons.append(_raison("REJ-ING-FACTURE-ECHEANCE-AVANT-DATE", f"échéance {echeance} avant la date {jour}"))

    lignes = []
    somme = Decimal("0.00")
    for index, ligne in enumerate(extraction["lignes"], 1):
        quantite, prix, montant = Decimal(ligne["quantite"]), Decimal(ligne["prix_unitaire"]), Decimal(ligne["montant"])
        attendu = _au_cent(_CONTEXTE.multiply(quantite, prix))
        if attendu != montant:
            raisons.append(_raison("REJ-ING-FACTURE-LIGNE-MONTANT", f"ligne {index} : {quantite} × {prix} = {attendu}, "
                                                                     f"montant imprimé {montant}"))
        somme += montant
        lignes.append({"description": ligne["description"], "quantite": ligne["quantite"],
                       "prix_unitaire": ligne["prix_unitaire"], "montant": ligne["montant"]})
    sous_total = Decimal(extraction["sous_total"])
    tps, tvq, total = Decimal(extraction["tps"]), Decimal(extraction["tvq"]), Decimal(extraction["total"])
    if somme != sous_total:
        raisons.append(_raison("REJ-ING-FACTURE-SOMME-LIGNES", f"somme des lignes {somme} ≠ sous-total imprimé "
                                                               f"{sous_total}"))
    lecture: dict[str, Any] = {
        "fournisseur": fournisseur, "numero": numero, "date": extraction["date"],
        "echeance": extraction.get("echeance"),
        "devise": extraction["devise"], "destinataire": extraction["destinataire"]["nom"],
        "no_tps": None, "no_tvq": None, "lignes": lignes, "sous_total": str(sous_total), "tps": str(tps),
        "tvq": str(tvq), "total": str(total), "tps_recalculee": None, "tvq_recalculee": None, "total_recalcule": None,
    }
    if sous_total <= 0:
        raisons.append(_raison("REJ-ING-FACTURE-MONTANT-NON-POSITIF", f"sous-total {sous_total} : une note de crédit "
                                                                      "n'est pas un compte à payer"))
    else:
        calcul, refus = taxes.calculer_taxes(sous_total, dictionnaire_taux)
        if refus is not None:
            raisons.append(_raison("REJ-ING-FACTURE-TAUX-INDISPONIBLES", f"taux versionnés : {refus['code']}"))
        else:
            par_id = {taxe["id"]: taxe["montant"] for taxe in calcul["taxes"]}
            tps_calc, tvq_calc = par_id["tps_federale"], par_id["tvq_quebec"]
            total_calc = calcul["montant_apres_taxes"]
            lecture.update(tps_recalculee=str(tps_calc), tvq_recalculee=str(tvq_calc), total_recalcule=str(total_calc))
            if tps != tps_calc:
                raisons.append(_raison("REJ-ING-FACTURE-TPS-ECART", f"TPS imprimée {tps}, recalculée {tps_calc} "
                                                                    f"(5 % de {sous_total}, au cent)"))
            if tvq != tvq_calc:
                raisons.append(_raison("REJ-ING-FACTURE-TVQ-ECART", f"TVQ imprimée {tvq}, recalculée {tvq_calc} "
                                                                    f"(9,975 % de {sous_total}, au cent)"))
            if total != total_calc:
                raisons.append(_raison("REJ-ING-FACTURE-TOTAL-ECART", f"total imprimé {total}, recalculé {total_calc} "
                                                                      f"({sous_total} + taxes recalculées)"))

    for champ, normaliser, code_forme, code_absent, montant, nom in (
        ("no_tps", normaliser_no_tps, "REJ-ING-FACTURE-NO-TPS-FORME", "REJ-ING-FACTURE-NO-TPS-ABSENT", tps, "TPS"),
        ("no_tvq", normaliser_no_tvq, "REJ-ING-FACTURE-NO-TVQ-FORME", "REJ-ING-FACTURE-NO-TVQ-ABSENT", tvq, "TVQ"),
    ):
        brut = emetteur[champ]
        if brut:
            forme = normaliser(brut)
            if forme is None:
                raisons.append(_raison(code_forme, f"numéro {nom} {brut!r} hors de la forme attendue"))
            lecture[champ] = forme or brut
        elif montant > 0:
            raisons.append(_raison(code_absent, f"{nom} facturée ({montant}) sans numéro d'inscription {nom}"))

    direction, raison_direction = _direction(extraction, identite)
    if raison_direction is not None:
        raisons.append(raison_direction)
    return {"statut": "A_VERIFIER" if raisons else "PRET", "raisons": raisons, "direction": direction,
            "facture": lecture}
