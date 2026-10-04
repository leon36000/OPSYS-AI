"""Échéanciers contractuels humains utilisés comme flux de prévision M5.8a.

Cette brique ne transforme pas un devis accepté en contrat. Elle vérifie un
échéancier saisi et revu par un humain contre le HT du devis M3; le TTC vient
explicitement de la pièce contractuelle. Aucune taxe n'est calculée ici.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Context, Decimal, InvalidOperation, localcontext
from typing import Any

from . import facturation, prevision, registre, validation

TYPE_ENREGISTRE = "echeancier_contrat_enregistre"
TYPE_REVOQUE = "echeancier_contrat_revoque"
DEVISE = "CAD"
MAX_ECHEANCES = 8
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z")
_MONTANT = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,2})?\Z")
_CONTEXTE = Context(prec=64)


def _refus(code: str, detail: str) -> tuple[None, dict[str, str]]:
    return None, validation.construire_verdict(code, detail=detail)


def _date_iso(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        result = date.fromisoformat(value)
    except ValueError:
        return None
    return result if result.isoformat() == value else None


def _montant(value: Any) -> Decimal | None:
    if not isinstance(value, str) or len(value) > 16 or not _MONTANT.fullmatch(value):
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount > 0 else None


def _chaine_valide(journal: registre.Registre) -> bool:
    try:
        valide, _detail = journal.valider_chaine()
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return False
    return valide is True


def etats_courants(journal: registre.Registre) -> tuple[dict[str, dict[str, Any]] | None, dict | None]:
    maillons = journal.lire()
    if not _chaine_valide(journal):
        return None, validation.construire_verdict(
            "REJ-CONTRAT-CHAINE-INVALIDE", detail="chaîne des échéanciers invalide; aucune réparation tentée"
        )
    etats: dict[str, dict[str, Any]] = {}
    for index, maillon in enumerate(maillons):
        if not isinstance(maillon, dict):
            return None, validation.construire_verdict(
                "REJ-CONTRAT-STRUCTURE-INVALIDE", detail=f"maillon {index} mal formé"
            )
        ident = maillon.get("contrat_id")
        courant = etats.get(ident) if isinstance(ident, str) else None
        revision_attendue = courant["revision"] + 1 if courant else 1
        if (maillon.get("type_entree") not in {TYPE_ENREGISTRE, TYPE_REVOQUE}
                or not isinstance(ident, str) or not _ID.fullmatch(ident)
                or type(maillon.get("revision")) is not int or maillon["revision"] != revision_attendue
                or maillon.get("remplace_ligne_id") != (courant["ligne_id"] if courant else None)):
            return None, validation.construire_verdict(
                "REJ-CONTRAT-STRUCTURE-INVALIDE", detail="version orpheline, répétée ou reliée à la mauvaise tête"
            )
        if maillon["type_entree"] == TYPE_ENREGISTRE:
            verdict = _valider_contenu(maillon)
        else:
            verdict = _valider_retrait(maillon, courant)
        if verdict is not None:
            return None, verdict
        etats[ident] = maillon
    return etats, None


def _valider_contenu(maillon: Mapping[str, Any]) -> dict | None:
    if (type(maillon.get("schema_version")) is not int or maillon["schema_version"] != 1
            or not isinstance(maillon.get("devis_id"), str) or not maillon["devis_id"].strip()
            or maillon.get("devise") != DEVISE
            or _montant(maillon.get("prix_ht")) is None or _montant(maillon.get("prix_ttc")) is None
            or _date_iso(maillon.get("date_source")) is None
            or not isinstance(maillon.get("source_humaine"), str)
            or not 1 <= len(maillon["source_humaine"].strip()) <= 500
            or _date_iso(maillon.get("couverture_jusquau")) is None
            or not isinstance(maillon.get("motif"), str)
            or not 1 <= len(maillon["motif"].strip()) <= 500
            or not _signataire_valide(maillon)
            or not _horodatage_valide(maillon.get("horodatage"))
            or not isinstance(maillon.get("echeances"), list)
            or not 1 <= len(maillon["echeances"]) <= MAX_ECHEANCES):
        return validation.construire_verdict(
            "REJ-CONTRAT-STRUCTURE-INVALIDE", detail="échéancier contractuel incomplet ou hors limites"
        )
    dates: set[date] = set()
    derniere_date: date | None = None
    total = Decimal("0")
    couverture = _date_iso(maillon["couverture_jusquau"])
    with localcontext(_CONTEXTE):
        for echeance in maillon["echeances"]:
            if not isinstance(echeance, dict) or set(echeance) != {"date", "montant_ttc"}:
                return validation.construire_verdict(
                    "REJ-CONTRAT-STRUCTURE-INVALIDE", detail="échéance non structurée"
                )
            jour = _date_iso(echeance.get("date"))
            montant = _montant(echeance.get("montant_ttc"))
            if (jour is None or montant is None or jour > couverture or jour in dates
                    or (derniere_date is not None and jour < derniere_date)):
                return validation.construire_verdict(
                    "REJ-CONTRAT-ECHEANCIER-INVALIDE", detail="date ou montant d'échéance invalide ou répété"
                )
            dates.add(jour)
            derniere_date = jour
            total += montant
    if total != _montant(maillon["prix_ttc"]):
        return validation.construire_verdict(
            "REJ-CONTRAT-TTC-INCOHERENT", detail="la somme TTC des échéances ne correspond pas au TTC déclaré"
        )
    if not _signataire_valide(maillon):
        return validation.construire_verdict(
            "REJ-CONTRAT-STRUCTURE-INVALIDE", detail="provenance de revue humaine absente"
        )
    return None


def _valider_retrait(maillon: Mapping[str, Any], courant: Mapping[str, Any] | None) -> dict | None:
    if (courant is None or courant.get("type_entree") != TYPE_ENREGISTRE
            or type(maillon.get("schema_version")) is not int or maillon["schema_version"] != 1
            or maillon.get("devis_id") != courant.get("devis_id")
            or not isinstance(maillon.get("motif"), str)
            or not 1 <= len(maillon["motif"].strip()) <= 500
            or not _signataire_valide(maillon)
            or not _horodatage_valide(maillon.get("horodatage"))):
        return validation.construire_verdict(
            "REJ-CONTRAT-STRUCTURE-INVALIDE", detail="révocation incomplète ou reliée au mauvais contrat"
        )
    return None


def _signataire_valide(maillon: Mapping[str, Any]) -> bool:
    signataire = maillon.get("approbateur")
    return (
        isinstance(signataire, dict)
        and isinstance(signataire.get("personne"), str) and bool(signataire["personne"].strip())
        and signataire.get("role") in {"finance", "nathan_owner"}
        and signataire.get("voie") in {"console", "appareil", "approbation"}
        and (signataire.get("decision_id") is None or isinstance(signataire.get("decision_id"), str))
    )


def _horodatage_valide(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        instant = datetime.fromisoformat(value)
    except ValueError:
        return False
    return instant.tzinfo is not None


def enregistrer(
    journal: registre.Registre,
    *,
    devis: Mapping[str, Any],
    contrat_id: str,
    devis_id: str,
    prix_ht: str,
    prix_ttc: str,
    devise: str,
    source_humaine: str,
    date_source: str,
    couverture_jusquau: str,
    echeances: list[dict[str, str]],
    revision_attendue: int,
    ligne_id_attendue: str,
    motif: str,
    approbateur: dict[str, str],
    horodatage: str,
) -> tuple[dict | None, dict | None]:
    etats, verdict = etats_courants(journal)
    if verdict is not None:
        return None, verdict
    if (not isinstance(contrat_id, str) or not _ID.fullmatch(contrat_id)
            or not isinstance(devis_id, str) or devis.get("devis_id") != devis_id):
        return _refus("REJ-CONTRAT-IDENTIFIANT-INVALIDE", "contrat ou devis accepté inconnu")
    prix_devis = _montant(devis.get("prix_total"))
    if prix_devis is None or _montant(prix_ht) != prix_devis:
        return _refus("REJ-CONTRAT-HT-INCOHERENT", "prix HT déclaré différent ou absent du devis M3 accepté")
    if devise != DEVISE or _montant(prix_ht) is None or _montant(prix_ttc) is None:
        return _refus("REJ-CONTRAT-MONTANT-INVALIDE", "prix HT et TTC positifs en CAD, en texte décimal, requis")
    if _montant(prix_ht) != prix_devis:
        return _refus("REJ-CONTRAT-HT-INCOHERENT", "prix HT déclaré différent du prix_total HT du devis M3")
    if (not isinstance(source_humaine, str) or not 1 <= len(source_humaine.strip()) <= 500
            or _date_iso(date_source) is None or not isinstance(motif, str)
            or not 1 <= len(motif.strip()) <= 500 or not isinstance(approbateur, dict)
            or not isinstance(echeances, list)):
        return _refus("REJ-CONTRAT-SOURCE-INVALIDE", "source, date, échéances et motif de revue humaine requis")
    couverture = _date_iso(couverture_jusquau)
    if couverture is None:
        return _refus("REJ-CONTRAT-COUVERTURE-INVALIDE", "date de couverture ISO requise")
    courant = etats.get(contrat_id)
    revision = courant["revision"] if courant else 0
    ligne_id = courant["ligne_id"] if courant else ""
    if (type(revision_attendue) is not int or revision_attendue != revision or ligne_id_attendue != ligne_id):
        return _refus("REJ-CONTRAT-REVISION-PERIMEE", "tête attendue absente ou remplacée; relire le contrat")
    if courant and courant["type_entree"] == TYPE_REVOQUE:
        return _refus("REJ-CONTRAT-REVOQUE", "un contrat révoqué ne peut être réactivé")
    if (courant and (courant["devis_id"] != devis_id
                     or _montant(courant["prix_ht"]) != _montant(prix_ht))):
        return _refus("REJ-CONTRAT-HT-INCOHERENT", "le devis et le prix HT sont immuables pour ce contrat")
    if any(
        ident != contrat_id and etat.get("type_entree") == TYPE_ENREGISTRE and etat.get("devis_id") == devis_id
        for ident, etat in etats.items()
    ):
        return _refus("REJ-CONTRAT-DEJA-LIE", "un échéancier courant existe déjà pour ce devis")
    entree = {
        "type_entree": TYPE_ENREGISTRE, "schema_version": 1, "contrat_id": contrat_id,
        "devis_id": devis_id, "revision": revision + 1, "remplace_ligne_id": ligne_id or None,
        "prix_ht": prix_ht, "prix_ttc": prix_ttc, "devise": devise,
        "source_humaine": source_humaine.strip(), "date_source": date_source,
        "couverture_jusquau": couverture.isoformat(), "echeances": echeances,
        "motif": motif.strip(), "approbateur": approbateur, "horodatage": horodatage,
    }
    verdict = _valider_contenu(entree)
    if verdict is not None:
        return None, verdict
    ligne_id = journal.ajouter(entree)
    return next(maillon for maillon in journal.lire() if maillon["ligne_id"] == ligne_id), None


def revoquer(
    journal: registre.Registre, *, contrat_id: str, devis_id: str, revision_attendue: int,
    ligne_id_attendue: str, motif: str, approbateur: dict[str, str], horodatage: str,
) -> tuple[dict | None, dict | None]:
    etats, verdict = etats_courants(journal)
    if verdict is not None:
        return None, verdict
    courant = etats.get(contrat_id)
    if (courant is None or courant.get("type_entree") != TYPE_ENREGISTRE
            or courant.get("devis_id") != devis_id):
        return _refus("REJ-CONTRAT-INTROUVABLE", "échéancier courant introuvable")
    if (type(revision_attendue) is not int or revision_attendue != courant["revision"]
            or ligne_id_attendue != courant["ligne_id"]):
        return _refus("REJ-CONTRAT-REVISION-PERIMEE", "tête attendue absente ou remplacée; relire le contrat")
    signataire_valide = _signataire_valide({"approbateur": approbateur})
    if not isinstance(motif, str) or not 1 <= len(motif.strip()) <= 500 or not signataire_valide:
        return _refus("REJ-CONTRAT-SOURCE-INVALIDE", "motif et approbateur N4 requis")
    entree = {
        "type_entree": TYPE_REVOQUE, "schema_version": 1, "contrat_id": contrat_id,
        "devis_id": devis_id, "revision": courant["revision"] + 1,
        "remplace_ligne_id": courant["ligne_id"], "motif": motif.strip(),
        "approbateur": approbateur, "horodatage": horodatage,
    }
    ligne_id = journal.ajouter(entree)
    return next(maillon for maillon in journal.lire() if maillon["ligne_id"] == ligne_id), None


def flux_prevision(
    contrats: Iterable[Mapping[str, Any]],
    devis: Iterable[Mapping[str, Any]],
    factures: registre.Registre,
    *,
    fin_horizon: date,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[str], bool, list[dict[str, str]]]:
    contrats = list(contrats)
    devis = list(devis)
    devis_par_id = {item.get("devis_id"): item for item in devis if isinstance(item.get("devis_id"), str)}
    flux: list[dict[str, Any]] = []
    inclus: list[dict[str, str]] = []
    bloques: list[dict[str, str]] = []
    devis_couverts: set[str] = set()
    incomplet = False
    actifs_par_devis: dict[str, int] = {}
    for contrat in contrats:
        if contrat.get("type_entree") == TYPE_ENREGISTRE:
            actifs_par_devis[contrat["devis_id"]] = actifs_par_devis.get(contrat["devis_id"], 0) + 1
    for contrat in sorted(contrats, key=lambda item: (str(item.get("devis_id")), str(item.get("contrat_id")))):
        if contrat.get("type_entree") != TYPE_ENREGISTRE:
            continue
        devis_id = contrat["devis_id"]
        devis_couverts.add(devis_id)
        if actifs_par_devis.get(devis_id, 0) != 1:
            bloques.append({"contrat_id": contrat["contrat_id"], "devis_id": devis_id,
                            "code": "REJ-CONTRAT-ECHEANCIERS-AMBIGUS"})
            incomplet = True
            continue
        if devis_id not in devis_par_id:
            bloques.append({"contrat_id": contrat["contrat_id"], "devis_id": devis_id,
                            "code": "REJ-CONTRAT-DEVIS-ABSENT"})
            incomplet = True
            continue
        if _montant(devis_par_id[devis_id].get("prix_total")) != _montant(contrat["prix_ht"]):
            bloques.append({"contrat_id": contrat["contrat_id"], "devis_id": devis_id,
                            "code": "REJ-CONTRAT-HT-INCOHERENT"})
            incomplet = True
            continue
        if _date_iso(contrat["couverture_jusquau"]) < fin_horizon:
            bloques.append({"contrat_id": contrat["contrat_id"], "devis_id": devis_id,
                            "code": "REJ-CONTRAT-COUVERTURE-INCOMPLETE"})
            incomplet = True
            continue
        facture_active = facturation.facture_active_pour_devis(factures, devis_id)
        if facture_active is not None:
            bloques.append({"contrat_id": contrat["contrat_id"], "devis_id": devis_id,
                            "code": "REJ-CONTRAT-FACTURE-EXISTANTE",
                            "facture_id": str(facture_active.get("facture_id", ""))})
            incomplet = True
            continue
        for index, echeance in enumerate(contrat["echeances"], start=1):
            jour = _date_iso(echeance["date"])
            montant = _montant(echeance["montant_ttc"])
            # Entrées contractuelles : le TTC est transcrit de la pièce; aucun taux ni taxe n'est calculé.
            flux.append(prevision._flux(
                f"contrat:{contrat['contrat_id']}:{index}", prevision.ENTREE, "echeancier_contrat",
                montant, jour, f"date saisie au contrat {contrat['contrat_id']}",
                f"contrat {contrat['contrat_id']} / échéance {index} / source {contrat['source_humaine']}",
                [], contrat_id=contrat["contrat_id"], devis_id=devis_id,
            ))
            inclus.append({"contrat_id": contrat["contrat_id"], "devis_id": devis_id,
                           "echeance": str(index), "date": jour.isoformat(),
                           "montant_ttc": format(montant, ".2f"),
                           "source_humaine": contrat["source_humaine"],
                           "qualification_source": "REFERENCE_HUMAINE_NON_VERIFIEE",
                           "date_source": contrat["date_source"], "ligne_id": contrat["ligne_id"]})
    sans_echeancier = sorted(
        devis_id for devis_id in devis_par_id if devis_id not in devis_couverts
    )
    if sans_echeancier:
        incomplet = True
    return flux, inclus, sans_echeancier, incomplet, bloques
