"""Contrats horaires individuels, append-only, sans paie ni mouvement financier.

Module métier pur : le propriétaire de l'identité humaine et du stockage est `outils.py`.
Le journal est une suite Registre distincte du principal et des comptes à payer.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import registre, validation

TYPE_ENREGISTRE = "contrat_horaire_enregistre"
TYPE_REVOQUE = "contrat_horaire_revoque"
DEVISE = "CAD"
TAUX_MAX = Decimal("999999.99")
_FORMAT_TAUX = re.compile(r"(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,2})?\Z")
_FORMAT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z")


def _refus(code: str, detail: str = "") -> tuple[None, dict[str, str]]:
    return None, validation.construire_verdict(code, detail=detail)


def _date_iso(valeur: object) -> date | None:
    if not isinstance(valeur, str):
        return None
    try:
        parsed = date.fromisoformat(valeur)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == valeur else None


def _periode(
    valide_du: object, valide_jusqu_au: object, fuseau: object, *, fin_inclusive: bool = False,
) -> tuple[date, date] | None:
    debut, fin = _date_iso(valide_du), _date_iso(valide_jusqu_au)
    bornes_inversees = debut is not None and fin is not None and (debut > fin if fin_inclusive else debut >= fin)
    if debut is None or fin is None or bornes_inversees or not isinstance(fuseau, str) or not fuseau.strip():
        return None
    try:
        ZoneInfo(fuseau)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return debut, fin


def _valider_taux(texte: object) -> Decimal | None:
    if not isinstance(texte, str) or len(texte) > 16 or not _FORMAT_TAUX.fullmatch(texte):
        return None
    try:
        taux = Decimal(texte)
    except InvalidOperation:
        return None
    if not taux.is_finite() or taux <= 0 or taux > TAUX_MAX:
        return None
    return taux


def _chaine_valide(maillons: list[dict]) -> bool:
    try:
        valide, _ = registre.Registre(maillons=maillons).valider_chaine()
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return False
    return valide is True


def _etats_courants(journal: registre.Registre) -> tuple[dict[str, dict] | None, dict | None]:
    """Valide les transitions métier après la chaîne et renvoie une tête unique par contrat."""
    maillons = journal.lire()
    if not _chaine_valide(maillons):
        return None, validation.construire_verdict(
            "REJ-SALAIRE-CHAINE-INVALIDE", detail="la chaîne du journal salarial est invalide; aucune réparation tentée"
        )
    etats: dict[str, dict] = {}
    for maillon in maillons:
        type_entree = maillon.get("type_entree")
        if type_entree not in {TYPE_ENREGISTRE, TYPE_REVOQUE}:
            return None, validation.construire_verdict(
                "REJ-SALAIRE-STRUCTURE-INVALIDE", detail="type de maillon inconnu dans le journal salarial"
            )
        ident = maillon.get("contrat_id")
        personne = maillon.get("employee_person_id")
        revision = maillon.get("revision")
        precedent = etats.get(ident) if isinstance(ident, str) else None
        attendu = (precedent["revision"] + 1) if precedent else 1
        if (not isinstance(ident, str) or not _FORMAT_ID.fullmatch(ident)
                or not isinstance(personne, str) or not personne
                or type(revision) is not int or revision != attendu
                or maillon.get("remplace_ligne_id") != (precedent["ligne_id"] if precedent else None)
                or (precedent is not None and personne != precedent["employee_person_id"])):
            return None, validation.construire_verdict(
                "REJ-SALAIRE-STRUCTURE-INVALIDE", detail="révision orpheline, répétée ou reliée au mauvais salarié"
            )
        if type_entree == TYPE_ENREGISTRE:
            periode = _periode(maillon.get("valide_du"), maillon.get("valide_jusqu_au"), maillon.get("fuseau"))
            if (periode is None or maillon.get("devise") != DEVISE
                    or maillon.get("schema_version") != 1
                    or _valider_taux(maillon.get("taux_horaire")) is None
                    or not isinstance(maillon.get("source_humaine"), str)
                    or not maillon["source_humaine"].strip()
                    or len(maillon["source_humaine"]) > 500
                    or not isinstance(maillon.get("motif"), str)
                    or not maillon["motif"].strip()
                    or len(maillon["motif"]) > 500
                    or not _signataire_valide(maillon)
                    or not _horodatage_valide(maillon.get("horodatage"))
                    or _date_iso(maillon.get("date_source")) is None):
                return None, validation.construire_verdict(
                    "REJ-SALAIRE-STRUCTURE-INVALIDE", detail="maillon de contrat incomplet ou invalide"
                )
        elif (maillon.get("schema_version") != 1
              or not isinstance(maillon.get("motif"), str) or not maillon["motif"].strip()
              or len(maillon["motif"]) > 500
              or not _signataire_valide(maillon)
              or not _horodatage_valide(maillon.get("horodatage"))
              or precedent is None or precedent["type_entree"] != TYPE_ENREGISTRE
              or any(maillon.get(c) != precedent.get(c) for c in ("valide_du", "valide_jusqu_au", "fuseau"))):
            return None, validation.construire_verdict(
                "REJ-SALAIRE-STRUCTURE-INVALIDE", detail="maillon de révocation incomplet ou relié au mauvais contrat"
            )
        etats[ident] = maillon
    return etats, None


def _valider_source(source_humaine: object, date_source: object) -> bool:
    return (
        isinstance(source_humaine, str) and 1 <= len(source_humaine.strip()) <= 500
        and _date_iso(date_source) is not None
    )


def _signataire_valide(maillon: dict) -> bool:
    signataire = maillon.get("approbateur")
    return (
        isinstance(signataire, dict)
        and isinstance(signataire.get("personne"), str)
        and bool(signataire["personne"].strip())
        and signataire.get("role") in {"finance", "nathan_owner"}
        and signataire.get("voie") in {"appareil", "console", "approbation"}
        and (
            signataire.get("decision_id") is None
            or isinstance(signataire.get("decision_id"), str) and bool(signataire["decision_id"].strip())
        )
    )


def _horodatage_valide(valeur: object) -> bool:
    if not isinstance(valeur, str):
        return False
    try:
        instant = datetime.fromisoformat(valeur)
    except ValueError:
        return False
    return instant.tzinfo is not None


def enregistrer(
    journal: registre.Registre,
    *,
    employee_person_id: str,
    contrat_id: str,
    valide_du: str,
    valide_jusqu_au: str,
    fuseau: str,
    devise: str,
    taux_horaire: str,
    source_humaine: str,
    date_source: str,
    revision_attendue: int,
    ligne_id_attendue: str,
    motif: str,
    approbateur: dict[str, str],
    horodatage: str,
) -> tuple[dict | None, dict | None]:
    etats, verdict = _etats_courants(journal)
    if verdict:
        return None, verdict
    if (not isinstance(contrat_id, str) or not _FORMAT_ID.fullmatch(contrat_id)
            or not isinstance(employee_person_id, str) or not employee_person_id):
        return _refus("REJ-SALAIRE-CONTRAT-INVALIDE", "identifiant salarié ou contrat invalide")
    if devise != DEVISE or _valider_taux(taux_horaire) is None:
        return _refus("REJ-SALAIRE-TAUX-INVALIDE", "taux doit être un texte décimal positif CAD, au plus 999999.99")
    periode = _periode(valide_du, valide_jusqu_au, fuseau)
    if periode is None:
        return _refus("REJ-SALAIRE-PERIODE-INVALIDE", "dates ISO valides, début < fin exclusive, fuseau IANA requis")
    if not _valider_source(source_humaine, date_source):
        return _refus(
            "REJ-SALAIRE-SOURCE-INVALIDE",
            "référence/source humaine (1 à 500 caractères) et date ISO requises",
        )
    if not isinstance(motif, str) or not 1 <= len(motif.strip()) <= 500:
        return _refus("REJ-SALAIRE-CONTRAT-INVALIDE", "motif humain requis (1 à 500 caractères)")
    if (not isinstance(approbateur, dict) or not isinstance(approbateur.get("personne"), str)
            or approbateur.get("role") not in {"finance", "nathan_owner"}
            or approbateur.get("voie") not in {"appareil", "console", "approbation"}
            or (approbateur.get("voie") == "approbation" and not approbateur.get("decision_id"))):
        return _refus("REJ-SALAIRE-IDENTITE-REQUIS", "provenance N4 humaine confirmée requise")
    try:
        instant = datetime.fromisoformat(horodatage)
    except (TypeError, ValueError):
        instant = None
    if instant is None or instant.tzinfo is None:
        return _refus("REJ-SALAIRE-CONTRAT-INVALIDE", "horodatage serveur ISO 8601 avec fuseau requis")

    precedent = etats.get(contrat_id)
    revision_actuelle = precedent["revision"] if precedent else 0
    ligne_actuelle = precedent["ligne_id"] if precedent else ""
    if (type(revision_attendue) is not int or revision_attendue != revision_actuelle
            or ligne_id_attendue != ligne_actuelle):
        return _refus("REJ-SALAIRE-REVISION-PERIMEE", "tête attendue absente ou déjà remplacée; relire le contrat")
    if precedent and precedent["type_entree"] == TYPE_REVOQUE:
        return _refus("REJ-SALAIRE-CONTRAT-REVOQUE", "créer un nouvel identifiant de contrat après révocation")
    if precedent and precedent["employee_person_id"] != employee_person_id:
        return _refus("REJ-SALAIRE-CONTRAT-INVALIDE", "un identifiant de contrat ne peut changer de salarié")

    debut, fin = periode
    for autre_id, etat in etats.items():
        if autre_id == contrat_id or etat["type_entree"] != TYPE_ENREGISTRE:
            continue
        if etat["employee_person_id"] != employee_person_id:
            continue
        autre_debut = _date_iso(etat["valide_du"])
        autre_fin = _date_iso(etat["valide_jusqu_au"])
        if autre_debut is None or autre_fin is None or debut < autre_fin and autre_debut < fin:
            return _refus(
                "REJ-SALAIRE-CHEVAUCHEMENT",
                "une autre révision courante couvre déjà une date de cette période",
            )

    maillon = {
        "type_entree": TYPE_ENREGISTRE,
        "schema_version": 1,
        "contrat_id": contrat_id,
        "employee_person_id": employee_person_id,
        "revision": revision_actuelle + 1,
        "remplace_ligne_id": ligne_actuelle or None,
        "valide_du": valide_du,
        "valide_jusqu_au": valide_jusqu_au,
        "fuseau": fuseau,
        "devise": DEVISE,
        "taux_horaire": taux_horaire,
        "source_humaine": source_humaine.strip(),
        "date_source": date_source,
        "motif": motif.strip(),
        "approbateur": approbateur,
        "horodatage": instant.isoformat(),
    }
    ligne_id = journal.ajouter(maillon)
    ajoute = journal.lire()[-1]
    if ajoute.get("ligne_id") != ligne_id:
        raise RuntimeError("maillon salarial ajouté introuvable")
    return ajoute, None


def revoquer(
    journal: registre.Registre,
    *,
    employee_person_id: str,
    contrat_id: str,
    revision_attendue: int,
    ligne_id_attendue: str,
    motif: str,
    approbateur: dict[str, str],
    horodatage: str,
) -> tuple[dict | None, dict | None]:
    etats, verdict = _etats_courants(journal)
    if verdict:
        return None, verdict
    precedent = etats.get(contrat_id)
    if precedent is None or precedent["employee_person_id"] != employee_person_id:
        return _refus("REJ-SALAIRE-CONTRAT-ABSENT", "contrat courant introuvable pour cette personne")
    if precedent["type_entree"] == TYPE_REVOQUE:
        return _refus("REJ-SALAIRE-CONTRAT-REVOQUE", "contrat déjà révoqué")
    if (type(revision_attendue) is not int or revision_attendue != precedent["revision"]
            or ligne_id_attendue != precedent["ligne_id"]):
        return _refus("REJ-SALAIRE-REVISION-PERIMEE", "tête attendue absente ou déjà remplacée; relire le contrat")
    if not isinstance(motif, str) or not 1 <= len(motif.strip()) <= 500:
        return _refus("REJ-SALAIRE-CONTRAT-INVALIDE", "motif humain requis (1 à 500 caractères)")
    if (not isinstance(approbateur, dict) or approbateur.get("role") not in {"finance", "nathan_owner"}
            or approbateur.get("voie") not in {"appareil", "console", "approbation"}
            or (approbateur.get("voie") == "approbation" and not approbateur.get("decision_id"))):
        return _refus("REJ-SALAIRE-IDENTITE-REQUIS", "provenance N4 humaine confirmée requise")
    try:
        instant = datetime.fromisoformat(horodatage)
    except (TypeError, ValueError):
        instant = None
    if instant is None or instant.tzinfo is None:
        return _refus("REJ-SALAIRE-CONTRAT-INVALIDE", "horodatage serveur ISO 8601 avec fuseau requis")
    ligne_id = journal.ajouter({
        "type_entree": TYPE_REVOQUE,
        "schema_version": 1,
        "contrat_id": contrat_id,
        "employee_person_id": employee_person_id,
        "revision": precedent["revision"] + 1,
        "remplace_ligne_id": precedent["ligne_id"],
        "valide_du": precedent["valide_du"],
        "valide_jusqu_au": precedent["valide_jusqu_au"],
        "fuseau": precedent["fuseau"],
        "motif": motif.strip(),
        "approbateur": approbateur,
        "horodatage": instant.isoformat(),
    })
    ajoute = journal.lire()[-1]
    if ajoute.get("ligne_id") != ligne_id:
        raise RuntimeError("maillon de révocation salariale ajouté introuvable")
    return ajoute, None


def lire(
    journal: registre.Registre,
    *,
    employee_person_id: str,
    valide_du: str,
    valide_jusqu_au: str,
    fuseau: str,
) -> tuple[dict | None, dict | None]:
    periode = _periode(valide_du, valide_jusqu_au, fuseau, fin_inclusive=True)
    if periode is None:
        return _refus("REJ-SALAIRE-PERIODE-INVALIDE", "dates ISO valides, fin demandée ≥ début, fuseau IANA requis")
    etats, verdict = _etats_courants(journal)
    if verdict:
        return None, verdict
    debut, fin = periode
    intersectants = []
    couvrants = []
    revocations_couvrantes = []
    for etat in etats.values():
        if etat["employee_person_id"] != employee_person_id:
            continue
        if etat["type_entree"] == TYPE_REVOQUE:
            r_debut, r_fin = _date_iso(etat.get("valide_du")), _date_iso(etat.get("valide_jusqu_au"))
            if r_debut is not None and r_fin is not None and debut < r_fin and r_debut <= fin:
                revocations_couvrantes.append(etat)
            continue
        if etat["type_entree"] != TYPE_ENREGISTRE:
            continue
        e_debut, e_fin = _date_iso(etat["valide_du"]), _date_iso(etat["valide_jusqu_au"])
        if e_debut is None or e_fin is None:
            return _refus("REJ-SALAIRE-STRUCTURE-INVALIDE", "bornes de contrat illisibles")
        if debut < e_fin and e_debut <= fin:
            intersectants.append(etat)
        if e_debut <= debut and fin < e_fin and etat["fuseau"] == fuseau:
            couvrants.append(etat)
    if len(intersectants) > 1:
        return _refus(
            "REJ-SALAIRE-TAUX-AMBIGU",
            "plusieurs contrats courants touchent la période; un taux unique est requis",
        )
    if len(couvrants) == 1:
        return couvrants[0], None
    if revocations_couvrantes:
        return _refus("REJ-SALAIRE-CONTRAT-REVOQUE", "le contrat qui touche la période a été révoqué")
    return _refus("REJ-SALAIRE-COUVERTURE-ABSENTE", "aucun contrat unique ne couvre toute la période demandée")
