"""Prévisualisation pure d'un relevé CSV CAD contre une vue M5 des créances.

Le module ne lit aucun registre et n'effectue aucune écriture. L'adaptateur fournit une vue
complète issue de `facturation.comptes_a_recevoir`, ainsi que la version et la tête hashée du
snapshot qu'il a lu. Le rapprochement proposé exige l'identifiant exact de facture ET son solde
dû exact. Il ne certifie ni la source bancaire ni le snapshot M5.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from . import encodage

DEVISE = "CAD"
OCTETS_MAX = 1_048_576
LIGNES_MAX = 2_000
CHAMP_MAX = 4_096
_CLES_MAPPING = frozenset({"date", "montant", "reference_facture"})
_DATE_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_MONTANT = re.compile(r"-?(?:0|[1-9][0-9]{0,11})\.[0-9]{2}\Z")
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MONTANT_MAX = Decimal("999999999999.99")


def _refus(code: str, detail: str, *, ligne: int | None = None) -> tuple[None, dict[str, Any]]:
    verdict: dict[str, Any] = {"code": code, "detail": detail}
    if ligne is not None:
        verdict["ligne"] = ligne
    return None, verdict


def _montant_m5(valeur: object) -> Decimal | None:
    if isinstance(valeur, Decimal):
        montant = valeur
    elif isinstance(valeur, str) and len(valeur) <= 16 and _MONTANT.fullmatch(valeur):
        try:
            montant = Decimal(valeur)
        except InvalidOperation:
            return None
    else:
        return None
    if not montant.is_finite():
        return None
    if montant <= 0 or montant > _MONTANT_MAX or montant.as_tuple().exponent < -2:
        return None
    return montant


def _instantane_valide(snapshot: object) -> tuple[dict[str, Decimal] | None, dict[str, Any] | None]:
    if not isinstance(snapshot, Mapping) or set(snapshot) != {"version", "empreinte", "total_complet", "factures"}:
        return None, {"code": "REJ-M53-SNAPSHOT-STRUCTURE", "detail": "snapshot M5 incomplet ou mal formé"}
    version = snapshot.get("version")
    empreinte = snapshot.get("empreinte")
    total_complet = snapshot.get("total_complet")
    factures = snapshot.get("factures")
    if type(version) is not int or version < 0 or total_complet is not True:
        return None, {"code": "REJ-M53-SNAPSHOT-INCOMPLET", "detail": "la vue M5 doit être complète et versionnée"}
    if not isinstance(factures, list) or len(factures) > 20_000:
        return None, {"code": "REJ-M53-SNAPSHOT-STRUCTURE", "detail": "liste de créances M5 invalide ou hors limite"}
    if version == 0 and not factures:
        if empreinte is not None:
            return None, {"code": "REJ-M53-SNAPSHOT-EMPREINTE", "detail": "une vue vide ne porte pas de tête de chaîne"}
    elif not isinstance(empreinte, str) or not _SHA256.fullmatch(empreinte):
        return None, {"code": "REJ-M53-SNAPSHOT-EMPREINTE", "detail": "empreinte de snapshot M5 invalide"}

    par_id: dict[str, Decimal] = {}
    for index, facture in enumerate(factures, start=1):
        if not isinstance(facture, Mapping):
            return None, {"code": "REJ-M53-SNAPSHOT-FACTURE", "detail": "facture M5 mal formée", "ligne": index}
        facture_id = facture.get("facture_id")
        montant = _montant_m5(facture.get("montant_apres_taxes"))
        if not isinstance(facture_id, str) or not _REFERENCE.fullmatch(facture_id) or montant is None:
            return None, {"code": "REJ-M53-SNAPSHOT-FACTURE", "detail": "facture M5 invalide", "ligne": index}
        if facture_id in par_id:
            return None, {"code": "REJ-M53-SNAPSHOT-AMBIGU", "detail": "identifiant de facture répété dans la vue M5"}
        par_id[facture_id] = montant
    if bool(factures) and version == 0:
        return None, {"code": "REJ-M53-SNAPSHOT-VERSION", "detail": "une vue M5 non vide exige une version positive"}
    return par_id, None


def previsualiser_releve_csv(
    contenu: bytes,
    *,
    compte_interne_id: str,
    devise: str,
    mapping_colonnes: Mapping[str, str],
    snapshot_factures: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Normalise et propose les correspondances exactes, sans modifier les entrées.

    `snapshot_factures` a la forme `{version, empreinte, total_complet, factures}`. `factures`
    reprend la liste de `facturation.comptes_a_recevoir`; `version` et `empreinte` sont fournis
    par l'adaptateur M5 qui a lu cette vue. `mapping_colonnes` contient exactement les noms de
    colonnes CSV utilisés pour `date`, `montant`, et `reference_facture`.

    Retourne `(résultat, None)` ou `(None, verdict)`. Les verdicts ne contiennent jamais le
    texte brut des lignes ni les colonnes non mappées.
    """
    if not isinstance(contenu, bytes) or not contenu:
        return _refus("REJ-M53-CSV-SOURCE", "le relevé doit être fourni en octets UTF-8 non vides")
    if len(contenu) > OCTETS_MAX:
        return _refus("REJ-M53-CSV-TROP-GROS", "le relevé dépasse la limite de 1 Mio")
    if not isinstance(compte_interne_id, str) or not _REFERENCE.fullmatch(compte_interne_id):
        return _refus("REJ-M53-COMPTE-INVALIDE", "compte interne absent ou invalide")
    if devise != DEVISE:
        return _refus("REJ-M53-DEVISE-NON-CAD", "seuls les relevés CAD sont pris en charge")
    if (not isinstance(mapping_colonnes, Mapping) or set(mapping_colonnes) != _CLES_MAPPING
            or any(not isinstance(v, str) or not v or len(v) > 128 for v in mapping_colonnes.values())
            or len(set(mapping_colonnes.values())) != len(_CLES_MAPPING)):
        return _refus("REJ-M53-MAPPING-INVALIDE", "mapping explicite des trois colonnes requis")
    montants_factures, verdict = _instantane_valide(snapshot_factures)
    if verdict is not None:
        return None, verdict
    assert montants_factures is not None

    try:
        texte = contenu.decode("utf-8-sig", errors="strict")
        lecteur = csv.DictReader(io.StringIO(texte, newline=""), strict=True)
        entetes = lecteur.fieldnames
        if (not entetes or any(not isinstance(champ, str) or not champ or len(champ) > 128 for champ in entetes)
                or len(entetes) != len(set(entetes))
                or any(mapping_colonnes[cle] not in entetes for cle in _CLES_MAPPING)):
            return _refus("REJ-M53-CSV-ENTETES", "entêtes absentes, répétées ou incompatibles avec le mapping")
        lignes: list[dict[str, Any]] = []
        signatures: set[tuple[str, str, str]] = set()
        for numero, brut in enumerate(lecteur, start=2):
            if numero - 1 > LIGNES_MAX:
                return _refus("REJ-M53-CSV-TROP-DE-LIGNES", "le relevé dépasse 2 000 lignes", ligne=numero)
            if None in brut or any(valeur is None for valeur in brut.values()):
                return _refus("REJ-M53-CSV-COLONNES", "nombre de cellules incompatible avec l'entête", ligne=numero)
            if any(len(valeur) > CHAMP_MAX for valeur in brut.values()):
                return _refus("REJ-M53-CSV-CHAMP-TROP-GROS", "une cellule dépasse la limite", ligne=numero)
            date_texte = brut[mapping_colonnes["date"]]
            montant_texte = brut[mapping_colonnes["montant"]]
            reference = brut[mapping_colonnes["reference_facture"]]
            if any(
                valeur.lstrip().startswith(("=", "+", "@"))
                or (valeur.lstrip().startswith("-") and nom_colonne != mapping_colonnes["montant"])
                for nom_colonne, valeur in brut.items()
            ):
                return _refus("REJ-M53-CSV-FORMULE", "cellule de formule refusée", ligne=numero)
            if not _DATE_ISO.fullmatch(date_texte):
                return _refus("REJ-M53-CSV-DATE", "date de transaction non ISO", ligne=numero)
            try:
                jour = date.fromisoformat(date_texte)
            except ValueError:
                return _refus("REJ-M53-CSV-DATE", "date de transaction invalide", ligne=numero)
            if jour.isoformat() != date_texte:
                return _refus("REJ-M53-CSV-DATE", "date de transaction non canonique", ligne=numero)
            if (not _MONTANT.fullmatch(montant_texte) or montant_texte == "-0.00"
                    or not _REFERENCE.fullmatch(reference)):
                return _refus("REJ-M53-CSV-VALEUR", "montant ou référence de facture non canonique", ligne=numero)
            try:
                montant = Decimal(montant_texte)
            except InvalidOperation:
                return _refus("REJ-M53-CSV-MONTANT", "montant de transaction invalide", ligne=numero)
            if not montant.is_finite() or montant.copy_abs() > _MONTANT_MAX:
                return _refus("REJ-M53-CSV-MONTANT", "montant hors domaine", ligne=numero)
            signature = (date_texte, montant_texte, reference)
            if signature in signatures:
                return _refus("REJ-M53-CSV-DOUBLON", "ligne bancaire répétée", ligne=numero)
            signatures.add(signature)
            lignes.append({"numero": numero, "date": jour.isoformat(), "montant": montant,
                           "reference_facture": reference})
    except (UnicodeDecodeError, csv.Error):
        return _refus("REJ-M53-CSV-LECTURE", "CSV UTF-8 invalide ou mal formé")

    references = Counter(ligne["reference_facture"] for ligne in lignes)
    normalisees: list[dict[str, Any]] = []
    propositions: list[dict[str, Any]] = []
    for ligne in lignes:
        montant = ligne["montant"]
        reference = ligne["reference_facture"]
        statut = "NON_RAPPROCHE"
        facture_id: str | None = None
        montant_du: Decimal | None = None
        if references[reference] > 1:
            statut = "REFERENCE_REPETEE_SPLIT_NON_SUPPORTE"
        elif montant <= 0:
            statut = "FLUX_SORTANT_HORS_AR" if montant < 0 else "MONTANT_ZERO_NON_RAPPROCHABLE"
        elif reference not in montants_factures:
            statut = "REFERENCE_FACTURE_INCONNUE"
        else:
            montant_du = montants_factures[reference]
            facture_id = reference
            if montant == montant_du:
                statut = "PROPOSITION_EXACTE"
                propositions.append({
                    "ligne": ligne["numero"], "facture_id": facture_id,
                    "montant": format(montant, ".2f"), "statut": "PROPOSE",
                })
            elif montant < montant_du:
                statut = "PAIEMENT_PARTIEL_NON_SUPPORTE"
            else:
                statut = "FRAIS_OU_ECART_NON_SUPPORTE"
        normalisees.append({
            "numero": ligne["numero"], "date": ligne["date"], "montant": format(montant, ".2f"),
            "reference_facture": reference, "statut_rapprochement": statut,
            "facture_id": facture_id,
            "montant_du": format(montant_du, ".2f") if montant_du is not None else None,
        })

    sha_csv = hashlib.sha256(contenu).hexdigest()
    version = snapshot_factures["version"]
    empreinte_source = snapshot_factures["empreinte"]
    empreinte_vue = encodage.empreinte(montants_factures)
    lot_id = encodage.empreinte({
        "sha256_csv": sha_csv, "compte_interne_id": compte_interne_id, "devise": devise,
        "mapping_colonnes": dict(mapping_colonnes), "version_factures": version,
        "empreinte_factures": empreinte_source, "empreinte_vue_factures": empreinte_vue,
    })
    return {
        "statut": "PROPOSITIONS_PRESENTES" if propositions else "AUCUNE_PROPOSITION",
        "compte_interne_id": compte_interne_id,
        "devise": DEVISE,
        "lot_id": lot_id,
        "source_csv": {"sha256": sha_csv, "octets": len(contenu), "lignes": len(normalisees)},
        "source_factures": {"version": version, "empreinte": empreinte_source, "empreinte_vue": empreinte_vue},
        "lignes": normalisees,
        "propositions": propositions,
        "limites": [
            "Rapprochement proposé seulement : aucune facture, aucun mouvement ni solde n'est modifié",
            "La référence doit être le facture_id M5 exact et le montant doit égaler le dû complet",
            "Partiels, splits, frais, frais bancaires et associations par montant seul ne sont pas pris en charge",
            "L'adaptateur doit fournir une vue M5 complète et vérifier son intégrité avant cet appel",
            "La provenance bancaire, les dépôts et l'identité du compte doivent être vérifiés par un humain",
        ],
    }, None
