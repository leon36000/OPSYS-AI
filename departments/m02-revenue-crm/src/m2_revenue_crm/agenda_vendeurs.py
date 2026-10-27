"""Agenda commercial interne : révisions durables, propriétaire sourcé, aucune horloge."""
import json
import re
import unicodedata
from copy import deepcopy
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from . import acces, encodage
from . import horodatage as heures
from .registre import Registre, VerificationError

REGISTRE = "agenda_vendeurs"
TYPE = "rendez_vous"
MAX_SOURCES = 10000
BORNE_SORTIE = 65536
FUSEAU = "America/Montreal"
_IDENTIFIANT = re.compile(r"[A-Za-z0-9_.:@-]{1,200}")
_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(?::00)?[+-][0-9]{2}:[0-9]{2}")
_CHAMPS = ("rendez_vous_id", "lead_id", "vendeur_id", "debut", "fin", "titre", "statut")


class Refus(Exception):
    def __init__(self, suffixe):
        self.suffixe = suffixe
        super().__init__(suffixe)


def refuser(suffixe):
    return {"accepte": False, "verdict": {"code": "REJ-AGENDA-" + suffixe}}


def _identifiant(valeur):
    return type(valeur) is str and _IDENTIFIANT.fullmatch(valeur) is not None


def _texte(valeur, maximum):
    return (type(valeur) is str and bool(valeur.strip()) and len(valeur) <= maximum
            and not any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in valeur))


def _instant(valeur):
    if type(valeur) is not str or _INSTANT.fullmatch(valeur) is None:
        raise Refus("ARGUMENTS")
    try:
        instant = datetime.fromisoformat(valeur)
        local = instant.astimezone(ZoneInfo(FUSEAU))
        if (not 1900 <= instant.year <= 2199 or instant.second or instant.microsecond
                or local.replace(tzinfo=None) != instant.replace(tzinfo=None)
                or local.utcoffset() != instant.utcoffset()):
            raise ValueError("heure civile invalide")
        return instant.astimezone(UTC)
    except (ValueError, OverflowError):
        raise Refus("ARGUMENTS") from None


def _intervalle(debut, fin):
    a, b = _instant(debut), _instant(fin)
    if not 0 < (b - a).total_seconds() <= 12 * 3600:
        raise Refus("ARGUMENTS")
    return a, b


def _arguments(rendez_vous_id, lead_id, vendeur_id, debut, fin, titre, statut, revision_attendue):
    if (not all(_identifiant(v) for v in (rendez_vous_id, lead_id, vendeur_id)) or not _texte(titre, 200)
            or type(statut) is not str or statut not in {"actif", "annule"}
            or type(revision_attendue) is not int or not 0 <= revision_attendue <= MAX_SOURCES):
        raise Refus("ARGUMENTS")
    _intervalle(debut, fin)
    return dict(zip((*_CHAMPS, "revision_attendue"),
                    (rendez_vous_id, lead_id, vendeur_id, debut, fin, titre, statut, revision_attendue), strict=True))


def _auteur(auteur):
    if (type(auteur) is not dict or set(auteur) != {"personne", "role"}
            or not _identifiant(auteur["personne"]) or type(auteur["role"]) is not str or auteur["role"] != "admin"):
        raise Refus("IDENTITE")


def _horodatage(valeur):
    try:
        if not _texte(valeur, 64):
            raise ValueError("heure serveur invalide")
        heures.valider_horodatage(valeur)
    except (ValueError, TypeError):
        raise Refus("ARGUMENTS") from None


def _mutation(mutation, arguments):
    if (type(mutation) is not dict or set(mutation) != {"appareil", "cle", "empreinte_arguments"}
            or not _identifiant(mutation["appareil"]) or not _identifiant(mutation["cle"])
            or type(mutation["empreinte_arguments"]) is not str
            or mutation["empreinte_arguments"] != encodage.encoder_canonique(arguments)):
        raise Refus("ARGUMENTS")


def verifier_borne(reponse, limite_sortie):
    if type(limite_sortie) is not int or limite_sortie < 1:
        raise Refus("SORTIE-TROP-VOLUMINEUSE")
    if any(len(json.dumps({"ok": True, "resultat": reponse, "rejoue": r}, ensure_ascii=False)) > limite_sortie
           for r in (False, True)):
        raise Refus("SORTIE-TROP-VOLUMINEUSE")


def _sources(principal):
    principal.assert_chaine()
    maillons = principal.lire()
    rangs = {m["ligne_id"]: rang for rang, m in enumerate(maillons)}
    leads = {m["lead_id"]: rang for rang, m in enumerate(maillons) if m["type_entree"] == "lead_ingere"}
    if len(rangs) != len(maillons):
        raise Refus("SOURCE-INVALIDE")
    proprietaires = acces.proprietaires(Registre(maillons))
    # Le CRM historique admet des owners libres; seule la cible agenda exige une
    # identité SQL de vendeur (confirmée par l'adaptateur), jamais les autres leads.
    if any(lead not in leads for lead in proprietaires):
        raise Refus("SOURCE-INVALIDE")
    return maillons, rangs, leads, proprietaires


def _evolution(m, precedente, proprietaire, dernieres, intervalles):
    if m["revision"] != (precedente["revision"] + 1 if precedente else 1):
        raise Refus("REVISION-PERIMEE")
    if precedente is None:
        if m["statut"] != "actif":
            raise Refus("ARGUMENTS")
    elif (any(m[k] != precedente[k] for k in ("lead_id", "vendeur_id")) or precedente["statut"] == "annule"):
        raise Refus("ARGUMENTS")
    if m["statut"] == "actif":
        if proprietaire != m["vendeur_id"]:
            raise Refus("PROPRIETAIRE-MODIFIE")
        debut, fin = _intervalle(m["debut"], m["fin"])
        for rid, autre in dernieres.items():
            if rid == m["rendez_vous_id"] or autre["vendeur_id"] != m["vendeur_id"] or autre["statut"] != "actif":
                continue
            a, b = intervalles[rid]
            if debut < b and a < fin:
                raise Refus("CONFLIT-HORAIRE")


def _charger(principal, agenda):
    try:
        if principal is agenda:
            raise Refus("SOURCE-INVALIDE")
        if principal.taille() > MAX_SOURCES or agenda.taille() > MAX_SOURCES:
            raise Refus("SOURCES-TROP-VOLUMINEUSES")
        source, rangs, leads, proprietaires = _sources(principal)
        agenda.assert_chaine()
        maillons = agenda.lire()
        dernieres, mutations, intervalles, caches = {}, {}, {}, {}
        cles = {*_CHAMPS, "revision", "revision_precedente", "type_entree", "auteur", "mutation", "horodatage",
                "source_principal_id", "propriete_a_ecriture", "ligne_id", "precedent_ligne_id"}
        dernier_rang = -1
        for m in maillons:
            try:
                if (type(m) is not dict or set(m) != cles or m["type_entree"] != TYPE
                        or type(m["revision"]) is not int or not 1 <= m["revision"] <= MAX_SOURCES
                        or type(m["propriete_a_ecriture"]) is not bool):
                    raise Refus("SOURCE-INVALIDE")
                arguments = _arguments(**{k: m[k] for k in _CHAMPS}, revision_attendue=m["revision"] - 1)
                _auteur(m["auteur"])
                _horodatage(m["horodatage"])
                _mutation(m["mutation"], arguments)
                rang = rangs[m["source_principal_id"]]
                if rang < dernier_rang or leads.get(m["lead_id"], MAX_SOURCES) > rang:
                    raise Refus("SOURCE-INVALIDE")
                if rang not in caches:
                    caches[rang] = acces.proprietaires(Registre(source[:rang + 1]))
                owner = caches[rang].get(m["lead_id"])
                if m["propriete_a_ecriture"] is not (owner == m["vendeur_id"]):
                    raise Refus("SOURCE-INVALIDE")
                rid = m["rendez_vous_id"]
                precedente = dernieres.get(rid)
                if m["revision_precedente"] != (precedente["ligne_id"] if precedente else None):
                    raise Refus("SOURCE-INVALIDE")
                _evolution(m, precedente, owner, dernieres, intervalles)
                cle = (m["mutation"]["appareil"], m["mutation"]["cle"])
                if cle in mutations:
                    raise Refus("SOURCE-INVALIDE")
                mutations[cle] = m
                dernieres[rid] = m
                intervalles[rid] = _intervalle(m["debut"], m["fin"])
                dernier_rang = rang
            except Refus:
                raise Refus("SOURCE-INVALIDE") from None
        return source, proprietaires, maillons, dernieres, mutations, intervalles
    except (VerificationError, KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise Refus("SOURCE-INVALIDE") from None


def _public(m, propriete):
    return {**{k: m[k] for k in _CHAMPS}, "revision": m["revision"], "source_id": m["ligne_id"],
            "auteur": deepcopy(m["auteur"]), "horodatage": m["horodatage"], "propriete_courante": propriete}


def enregistrer(principal, agenda, rendez_vous_id, lead_id, vendeur_id, debut, fin, titre, statut,
                revision_attendue, auteur, mutation, horodatage, limite_sortie=BORNE_SORTIE):
    arguments = _arguments(rendez_vous_id, lead_id, vendeur_id, debut, fin, titre, statut, revision_attendue)
    _auteur(auteur)
    _mutation(mutation, arguments)
    _horodatage(horodatage)
    source, proprietaires, _, dernieres, mutations, intervalles = _charger(principal, agenda)
    ancien = mutations.get((mutation["appareil"], mutation["cle"]))
    if ancien is not None:
        if ancien["mutation"] != mutation or ancien["auteur"] != auteur:
            raise Refus("MUTATION-CONFLIT")
        reponse = {"accepte": True, "resultat": _public(ancien, ancien["propriete_a_ecriture"]), "rejoue": True}
        verifier_borne(reponse, limite_sortie)
        return reponse
    precedente = dernieres.get(rendez_vous_id)
    m = {**{k: arguments[k] for k in _CHAMPS}, "type_entree": TYPE, "revision": revision_attendue + 1,
         "revision_precedente": precedente["ligne_id"] if precedente else None,
         "auteur": deepcopy(auteur), "mutation": deepcopy(mutation), "horodatage": horodatage,
         "source_principal_id": source[-1]["ligne_id"] if source else None,
         "propriete_a_ecriture": proprietaires.get(lead_id) == vendeur_id}
    _evolution(m, precedente, proprietaires.get(lead_id), dernieres, intervalles)
    if agenda.taille() >= MAX_SOURCES:
        raise Refus("SOURCES-TROP-VOLUMINEUSES")
    preview = {**m, "ligne_id": encodage.encoder_canonique(m, agenda.tete())}
    reponse = {"accepte": True, "resultat": _public(preview, m["propriete_a_ecriture"]), "rejoue": False}
    verifier_borne(reponse, limite_sortie)
    agenda.ajouter(m)
    return reponse


def _jour(valeur, fin_exclusive=False):
    try:
        if type(valeur) is not str:
            raise ValueError("date invalide")
        jour = date.fromisoformat(valeur)
        if (not (date(1900, 1, 1) <= jour <= date(2199, 12, 31)
                 or (fin_exclusive and jour == date(2200, 1, 1))) or jour.isoformat() != valeur):
            raise ValueError("date invalide")
        return jour
    except ValueError:
        raise Refus("ARGUMENTS") from None


def lire(principal, agenda, vendeur_id, debut_periode, fin_periode, limite_sortie=BORNE_SORTIE):
    if not _identifiant(vendeur_id):
        raise Refus("ARGUMENTS")
    a, b = _jour(debut_periode), _jour(fin_periode, fin_exclusive=True)
    if not 1 <= (b - a).days <= 31:
        raise Refus("ARGUMENTS")
    debut = datetime.combine(a, time.min, tzinfo=ZoneInfo(FUSEAU)).astimezone(UTC)
    fin = datetime.combine(b, time.min, tzinfo=ZoneInfo(FUSEAU)).astimezone(UTC)
    _, proprietaires, maillons, dernieres, _, intervalles = _charger(principal, agenda)
    selection = [m for rid, m in dernieres.items() if m["vendeur_id"] == vendeur_id
                 and intervalles[rid][0] < fin and intervalles[rid][1] > debut]
    if len(selection) > 100:
        raise Refus("SORTIE-TROP-VOLUMINEUSE")
    selection.sort(key=lambda m: (*intervalles[m["rendez_vous_id"]], m["rendez_vous_id"]))
    reponse = {"accepte": True, "resultat": {
        "vendeur_id": vendeur_id, "debut_periode": debut_periode, "fin_periode": fin_periode, "fuseau": FUSEAU,
        "rendez_vous": [_public(m, proprietaires.get(m["lead_id"]) == m["vendeur_id"]) for m in selection],
        "source_tete": maillons[-1]["ligne_id"] if maillons else None, "source_nombre": len(maillons)}}
    verifier_borne(reponse, limite_sortie)
    return reponse


def historique(principal, agenda, rendez_vous_id, limite_sortie=BORNE_SORTIE):
    if not _identifiant(rendez_vous_id):
        raise Refus("ARGUMENTS")
    _, proprietaires, maillons, dernieres, _, _ = _charger(principal, agenda)
    if rendez_vous_id not in dernieres:
        raise Refus("ARGUMENTS")
    selection = [m for m in maillons if m["rendez_vous_id"] == rendez_vous_id]
    if len(selection) > 100:
        raise Refus("SORTIE-TROP-VOLUMINEUSE")
    reponse = {"accepte": True, "resultat": {
        "rendez_vous_id": rendez_vous_id,
        "revisions": [_public(m, proprietaires.get(m["lead_id"]) == m["vendeur_id"]) for m in selection],
        "revision_courante": dernieres[rendez_vous_id]["revision"]}}
    verifier_borne(reponse, limite_sortie)
    return reponse


def lire_rencontres_lead(principal, agenda, lead_id, decalage=0, source_attendue="", limite_sortie=BORNE_SORTIE):
    """État courant de chaque rencontre du projet, sans perdre les vendeurs précédents.

    La continuation est liée aux deux registres et au lead; un changement exige une nouvelle lecture.
    """
    if (type(lead_id) is not str or re.fullmatch(r"[\w.:@\-]{1,200}", lead_id) is None
            or type(decalage) is not int
            or not 0 <= decalage <= MAX_SOURCES or decalage % 25
            or type(source_attendue) is not str
            or (source_attendue and re.fullmatch(r"[0-9a-f]{64}", source_attendue) is None)
            or (decalage > 0 and not source_attendue)):
        raise Refus("ARGUMENTS")
    source, proprietaires, maillons, dernieres, _, intervalles = _charger(principal, agenda)
    if not any(m.get("type_entree") == "lead_ingere" and m.get("lead_id") == lead_id for m in source):
        raise Refus("LEAD-INCONNU")
    tete_principal = source[-1]["ligne_id"] if source else None
    tete_agenda = maillons[-1]["ligne_id"] if maillons else None
    empreinte = encodage.encoder_canonique("rencontres-lead-v1", lead_id, tete_principal, tete_agenda)
    if source_attendue and source_attendue != empreinte:
        raise Refus("SOURCE-MODIFIEE")
    selection = [m for m in dernieres.values() if m["lead_id"] == lead_id]
    selection.sort(key=lambda m: (*intervalles[m["rendez_vous_id"]], m["rendez_vous_id"]))
    if decalage and decalage >= len(selection):
        raise Refus("ARGUMENTS")
    page = selection[decalage:decalage + 25]
    reponse = {"accepte": True, "resultat": {
        "lead_id": lead_id, "fuseau": FUSEAU, "decalage": decalage, "total": len(selection),
        "decalage_suivant": decalage + 25 if decalage + 25 < len(selection) else None,
        "source_empreinte": empreinte, "source_principal": tete_principal, "source_agenda": tete_agenda,
        "rendez_vous": [_public(m, proprietaires.get(lead_id) == m["vendeur_id"]) for m in page]}}
    verifier_borne(reponse, limite_sortie)
    return reponse
