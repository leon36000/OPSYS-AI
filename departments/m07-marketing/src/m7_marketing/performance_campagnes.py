"""Agrégats de campagne M7 issus des événements canoniques, sans dépense publicitaire.

Les identifiants conservés sont uniquement ceux requis pour relier les contrats M2, M3 et M5.
Les montants M5 sont repris tels quels en Decimal; ce module ne calcule jamais la rentabilité.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import LargeBinary, cast, func, select

from opsys import stockage
from opsys.stockage.schema import REGISTRES

DEPARTEMENT = "m07-marketing"
REGISTRE = (DEPARTEMENT, "performance_campagnes")
TYPES = {"m2.client_associe", "m3.devis_accepte", "m5.rentabilite_chantier"}
_CHAMPS_UTM = {"utm_source", "utm_campaign"}

# Bornes du seul lecteur privé : aucune troncature des faits avant le calcul métier.
MAX_LIGNES = 10_000
MAX_OCTETS_TOTAL = 8 * 1024 * 1024
MAX_OCTETS_LIGNE = 64 * 1024
_MAX_PROFONDEUR = 16
_MAX_NOEUDS = 2048
_MONTANT = re.compile(r"^-?[0-9]{1,30}(?:\.[0-9]{1,8})?$")
_EMPREINTE = re.compile(r"^[0-9a-f]{64}$")


def _longueur_octets(dialecte: str):
    if dialecte == "sqlite":
        return func.length(cast(REGISTRES.c.maillon, LargeBinary))
    if dialecte == "postgresql":
        # convert_to fixe UTF-8 même si l'encodage de la base est différent.
        return func.octet_length(func.convert_to(REGISTRES.c.maillon, "UTF8"))
    raise ValueError("PERFORMANCE_DIALECTE_NON_PRIS_EN_CHARGE")


def _texte_borne(valeur: Any, *, facultatif: bool = False, vide_permis: bool = False) -> bool:
    return facultatif and valeur is None or (
        isinstance(valeur, str) and (vide_permis or bool(valeur.strip())) and len(valeur.encode("utf-8")) <= 2048
    )


def _decoder_fait(texte: str) -> dict[str, Any]:
    """Ces faits normalisés ne portent aucun type codec : aucun restaurateur n'est nécessaire."""
    def constantes_refusees(_valeur: str):
        raise ValueError("nombre JSON non fini")

    def objet(paires):
        resultat = {}
        for cle, valeur in paires:
            if cle in resultat:
                raise ValueError("clé JSON répétée")
            resultat[cle] = valeur
        return resultat

    try:
        fait = json.loads(texte, parse_constant=constantes_refusees, object_pairs_hook=objet)
        pile = [(fait, 0)]
        nombre = 0
        while pile:
            valeur, profondeur = pile.pop()
            nombre += 1
            if profondeur > _MAX_PROFONDEUR or nombre > _MAX_NOEUDS:
                raise ValueError("PERFORMANCE_JSON_BORNE")
            if isinstance(valeur, dict):
                if "__opsys__" in valeur:
                    raise ValueError("étiquette hors contrat normalisé")
                pile.extend((item, profondeur + 1) for item in valeur.values())
            elif isinstance(valeur, list):
                pile.extend((item, profondeur + 1) for item in valeur)
        if not isinstance(fait, dict) or set(fait) != {"type", "charge"} or fait["type"] not in TYPES:
            raise ValueError("forme de fait invalide")
        type_ = fait["type"]
        charge = fait["charge"]
        if not isinstance(charge, dict) or set(charge) != set(_normaliser(type_, {}).get("charge", {})):
            raise ValueError("champs normalisés invalides")
        identifiants = {
            "m2.client_associe": ("lead_id", "client_ref"),
            "m3.devis_accepte": ("devis_id", "lead_id"),
            "m5.rentabilite_chantier": ("evenement_id", "devis_id", "wct_id"),
        }[type_]
        if not all(_texte_borne(charge[cle]) for cle in identifiants):
            raise ValueError("identifiant invalide")
        if type_ != "m2.client_associe" and not _texte_borne(charge["chantier_id"], facultatif=True):
            raise ValueError("chantier invalide")
        _horodatage(charge, type_)
        if type_ == "m2.client_associe" and not all(
            _texte_borne(charge[cle], facultatif=True, vide_permis=True) for cle in ("source", "campagne")
        ):
            raise ValueError("attribution invalide")
        if type_ == "m5.rentabilite_chantier":
            if type(charge["sequence"]) is not int or charge["sequence"] < 1:
                raise ValueError("séquence invalide")
            if not isinstance(charge["version_entrees"], str) or not _EMPREINTE.fullmatch(charge["version_entrees"]):
                raise ValueError("version invalide")
            if charge["devise"] != "CAD" or charge["verdict"] not in {"CALCULEE", "PARTIELLE"}:
                raise ValueError("unité ou verdict invalide")
            if type(charge["cout_reel_complet"]) is not bool:
                raise ValueError("complétude invalide")
            for cle in ("cout_reel_cad", "cout_connu_cad", "marge_reelle_cad"):
                montant = charge[cle]
                if montant is not None and (not isinstance(montant, str) or not _MONTANT.fullmatch(montant)):
                    raise ValueError("montant invalide")
            manque = charge["manque"]
            if not isinstance(manque, list) or len(manque) > 128 or not all(_texte_borne(v) for v in manque):
                raise ValueError("manques invalides")
        return fait
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RecursionError, UnicodeError) as exc:
        if str(exc) == "PERFORMANCE_JSON_BORNE":
            raise ValueError("PERFORMANCE_JSON_BORNE") from exc
        raise ValueError("PERFORMANCE_FAIT_INVALIDE") from exc


def lire_performance(debut: date, fin: date) -> dict[str, Any]:
    """Préfixe borné disponible maintenant, explicitement dépourvu de scellement historique."""
    debut, fin = _date_periode(debut), _date_periode(fin)
    if debut > fin:
        raise ValueError("PERIODE_INVERSEE")
    if (fin - debut).days > 365:
        raise ValueError("PERIODE_TROP_LONGUE")
    cnx = stockage.connexion_courante()
    if cnx is None:
        with stockage.transaction():
            return lire_performance(debut, fin)
    filtre = (REGISTRES.c.departement == REGISTRE[0]) & (REGISTRES.c.registre == REGISTRE[1])
    octets = _longueur_octets(cnx.dialect.name)
    nombre, premier, dernier, total, maximum = cnx.execute(select(
        func.count(), func.min(REGISTRES.c.rang), func.max(REGISTRES.c.rang),
        func.coalesce(func.sum(octets), 0), func.coalesce(func.max(octets), 0),
    ).where(filtre)).one()
    if nombre > MAX_LIGNES:
        raise ValueError("PERFORMANCE_BORNE_LIGNES")
    if total > MAX_OCTETS_TOTAL or maximum > MAX_OCTETS_LIGNE:
        raise ValueError("PERFORMANCE_BORNE_OCTETS")
    if nombre and (premier != 0 or dernier != nombre - 1):
        raise ValueError("PERFORMANCE_PREFIXE_INVALIDE")
    lignes = [] if not nombre else cnx.execute(select(
        REGISTRES.c.rang, REGISTRES.c.maillon, REGISTRES.c.cree_le,
    ).where(filtre, REGISTRES.c.rang <= dernier).order_by(REGISTRES.c.rang).limit(MAX_LIGNES + 1)).all()
    if len(lignes) != nombre:
        raise ValueError("PERFORMANCE_PREFIXE_INVALIDE")
    empreinte = hashlib.sha256()
    faits = []
    comparables: dict[tuple[Any, ...], dict[str, Any]] = {}
    total_lu = 0
    for rang, ligne in enumerate(lignes):
        if ligne.rang != rang:
            raise ValueError("PERFORMANCE_PREFIXE_INVALIDE")
        brut = ligne.maillon.encode("utf-8")
        total_lu += len(brut)
        if len(brut) > MAX_OCTETS_LIGNE or total_lu > MAX_OCTETS_TOTAL:
            raise ValueError("PERFORMANCE_BORNE_OCTETS")
        empreinte.update(len(brut).to_bytes(8, "big"))
        empreinte.update(brut)
        fait = _decoder_fait(ligne.maillon)
        charge = fait["charge"]
        champs_cle = {
            "m2.client_associe": ("lead_id",), "m3.devis_accepte": ("devis_id",),
            "m5.rentabilite_chantier": ("devis_id", "sequence"),
        }[fait["type"]]
        cle = (fait["type"], *(charge[c] for c in champs_cle))
        comparable = {k: v for k, v in charge.items() if k != "evenement_id"}
        if cle in comparables and comparables[cle] != comparable:
            raise ValueError("PERFORMANCE_FAITS_CONFLICTUELS")
        comparables[cle] = comparable
        faits.append(fait)
    if total_lu != total:
        raise ValueError("PERFORMANCE_PREFIXE_INVALIDE")
    resultat = construire_performance(faits, debut, fin)
    resultat["observation_source"] = {
        "lue_le": datetime.now(UTC).isoformat(), "rang_max": dernier, "lignes_lues": nombre,
        "dernier_cree_le_sql": max(ligne.cree_le for ligne in lignes).isoformat() if lignes else None,
        "fuseau_cree_le_sql": "UTC" if cnx.dialect.name == "sqlite" else "fourni_par_postgresql",
        "integrite": "historique_non_scelle", "empreinte_lecture_sha256": empreinte.hexdigest(),
        "definition_temps": "dates_metier_faits_disponibles_a_la_lecture",
    }
    return resultat


def _horodatage(charge: dict[str, Any], type_evenement: str) -> date:
    cle = {
        "m2.client_associe": "horodatage_association",
        "m3.devis_accepte": "horodatage_acceptation",
        "m5.rentabilite_chantier": "horodatage_completion",
    }[type_evenement]
    try:
        horodatage = datetime.fromisoformat(charge[cle].replace("Z", "+00:00"))
        if horodatage.tzinfo is None or horodatage.utcoffset() is None:
            raise ValueError("horodatage sans fuseau")
        return horodatage.astimezone(UTC).date()
    except (KeyError, AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"HORODATAGE_INVALIDE:{type_evenement}:{cle}") from exc


def _normaliser(type_evenement: str, charge: dict[str, Any]) -> dict[str, Any]:
    if type_evenement not in TYPES or not isinstance(charge, dict):
        raise ValueError("EVENEMENT_M7_PERFORMANCE_INVALIDE")
    if type_evenement == "m2.client_associe":
        utm = charge.get("utm")
        utm = utm if isinstance(utm, dict) else {}
        return {
            "type": type_evenement,
            "charge": {
                "lead_id": charge.get("lead_id"),
                "client_ref": charge.get("client_ref")
                or hashlib.sha256(str(charge.get("client_id", "")).encode()).hexdigest(),
                "source": (utm.get("utm_source") if isinstance(utm.get("utm_source"), str) else None)
                if utm else charge.get("source"),
                "campagne": (utm.get("utm_campaign") if isinstance(utm.get("utm_campaign"), str) else None)
                if utm else charge.get("campagne"),
                "horodatage_association": charge.get("horodatage_association"),
            },
        }
    if type_evenement == "m3.devis_accepte":
        return {
            "type": type_evenement,
            "charge": {k: charge.get(k) for k in ("devis_id", "lead_id", "chantier_id", "horodatage_acceptation")},
        }
    fields = (
        "evenement_id", "devis_id", "chantier_id", "wct_id", "sequence", "version_entrees",
        "horodatage_completion", "verdict", "devise", "cout_reel_complet", "cout_reel_cad",
        "cout_connu_cad", "marge_reelle_cad", "manque",
    )
    return {"type": type_evenement, "charge": {k: charge.get(k) for k in fields}}


def enregistrer_fait(type_evenement: str, charge: dict[str, Any]) -> dict[str, Any]:
    """Inscrit un événement canonique M2/M3/M5 dans le registre analytique privé de M7."""
    fait = _normaliser(type_evenement, charge)
    c = fait["charge"]
    cle = {
        "m2.client_associe": ("lead_id",),
        "m3.devis_accepte": ("devis_id",),
        "m5.rentabilite_chantier": ("devis_id", "sequence"),
    }[type_evenement]
    requises = cle + (("evenement_id", "wct_id") if type_evenement == "m5.rentabilite_chantier" else ())
    if any(c.get(k) in (None, "") for k in requises):
        raise ValueError(f"CLE_METIER_ABSENTE:{type_evenement}")
    faits = stockage.maillons(*REGISTRE)
    identity = tuple(c[k] for k in cle)
    comparable = json.dumps(fait, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    for existant in faits:
        if existant.get("type") != type_evenement:
            continue
        ec = existant["charge"]
        if tuple(ec.get(k) for k in cle) != identity:
            continue
        if type_evenement == "m5.rentabilite_chantier":
            # L'identifiant d'événement peut varier lors d'une republication; le fait de même séquence doit,
            # lui, être identique. Toute différence de fait financier est mise en anomalie.
            ancien = dict(existant)
            nouveau = dict(fait)
            ancien["charge"] = {k: v for k, v in ec.items() if k != "evenement_id"}
            nouveau["charge"] = {k: v for k, v in c.items() if k != "evenement_id"}
            if ancien != nouveau:
                raise ValueError("CONFLIT_RENTABILITE_M5")
            return {"accepte": True, "deja_present": True}
        precedent = json.dumps(existant, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if precedent != comparable:
            raise ValueError(f"CONFLIT_FAIT_{type_evenement.upper().replace('.', '_')}")
        return {"accepte": True, "deja_present": True}
    faits.append(fait)
    return {"accepte": True, "deja_present": False}


def _date_periode(valeur: date) -> date:
    if isinstance(valeur, datetime) or not isinstance(valeur, date):
        raise ValueError("PERIODE_DATE_INVALIDE")
    return valeur


def _refs_uniques(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    uniques: dict[tuple[Any, ...], dict[str, Any]] = {}
    for ref in refs:
        cle = (ref.get("type"), ref.get("reference"), ref.get("sequence"))
        uniques[cle] = ref
    return list(uniques.values())


def construire_performance(faits: Sequence[dict[str, Any]], debut: date, fin: date) -> dict[str, Any]:
    """Construit le rapport en cohorte des leads associés pendant la période inclusive."""
    debut, fin = _date_periode(debut), _date_periode(fin)
    if debut > fin:
        raise ValueError("PERIODE_INVERSEE")
    leads: dict[str, dict[str, Any]] = {}
    devis: dict[str, dict[str, Any]] = {}
    rentabilites: dict[tuple[str, int], dict[str, Any]] = {}
    refs: list[dict[str, Any]] = []
    anomalies: list[str] = []
    exclusions = {
        "associations_hors_cohorte": 0,
        "evenements_apres_fin": 0,
        "lead_hors_cohorte": 0,
        "lead_inconnu": 0,
        "attribution_inconnue": 0,
        "attribution_conflictuelle": 0,
        "marge_apres_fin": 0,
        "marge_sans_devis": 0,
        "chantier_m3_m5_contradictoire": 0,
    }
    leads_hors_cohorte: set[str] = set()
    for fait in faits:
        type_evenement = fait.get("type")
        if type_evenement not in TYPES:
            continue
        fait = _normaliser(type_evenement, fait.get("charge", {}))
        charge = fait["charge"]
        d = _horodatage(charge, type_evenement)
        if type_evenement == "m2.client_associe":
            if not debut <= d <= fin:
                exclusions["associations_hors_cohorte"] += 1
                if charge.get("lead_id"):
                    leads_hors_cohorte.add(charge["lead_id"])
                continue
            ident = charge.get("lead_id")
            if not ident:
                anomalies.append("LEAD_ID_ABSENT")
                continue
            attribution = (charge.get("source"), charge.get("campagne"), charge.get("client_ref"))
            ancien = leads.get(ident)
            if ancien is not None:
                if ancien["attribution"] != attribution:
                    anomalies.append("ATTRIBUTION_CONFLICTUELLE")
                    ancien["conflit"] = True
            else:
                leads[ident] = {"attribution": attribution, "conflit": False}
                refs.append({"type": type_evenement, "reference": ident})
        elif type_evenement == "m3.devis_accepte":
            if d > fin:
                exclusions["evenements_apres_fin"] += 1
                continue
            ancien = devis.get(charge["devis_id"])
            if ancien is not None and ancien != charge:
                raise ValueError("CONFLIT_DEVIS_M3")
            devis[charge["devis_id"]] = charge
            refs.append({"type": type_evenement, "reference": charge["devis_id"]})
        else:
            if d > fin:
                exclusions["marge_apres_fin"] += 1
                continue
            seq = charge["sequence"]
            if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
                raise ValueError("SEQUENCE_M5_INVALIDE")
            ident = (charge["devis_id"], seq)
            prev = rentabilites.get(ident)
            if prev is not None:
                a = {k: v for k, v in prev.items() if k != "evenement_id"}
                b = {k: v for k, v in charge.items() if k != "evenement_id"}
                if a != b:
                    raise ValueError("CONFLIT_RENTABILITE_M5")
            else:
                rentabilites[ident] = charge
            refs.append({"type": type_evenement, "reference": charge["evenement_id"], "sequence": seq})

    # M5 versionne chaque devis; garder la séquence la plus élevée, même si le WCT change.
    courant: dict[str, dict[str, Any]] = {}
    for charge in rentabilites.values():
        old = courant.get(charge["devis_id"])
        if old is None or charge["sequence"] > old["sequence"]:
            courant[charge["devis_id"]] = charge
    par_campagne: dict[tuple[str | None, str | None], dict[str, Any]] = {}
    leads_valides = {k: v for k, v in leads.items() if not v["conflit"] and v["attribution"][0] and v["attribution"][1]}
    leads_inconnus = {k: v for k, v in leads.items() if not v["conflit"] and k not in leads_valides}
    exclusions["attribution_conflictuelle"] = sum(1 for v in leads.values() if v["conflit"])
    for lead_id, fait_lead in leads_valides.items():
        source, campagne, _ = fait_lead["attribution"]
        bucket = par_campagne.setdefault(
            (source, campagne),
            {"leads": set(), "devis": set(), "wcts": {}, "m5_devis": set(), "manque": set(), "refs": []},
        )
        bucket["leads"].add(lead_id)
        bucket["refs"].append({"type": "m2.client_associe", "reference": lead_id})
    for devis_id, fait_devis in devis.items():
        lead = fait_devis.get("lead_id")
        if lead in leads_hors_cohorte:
            exclusions["lead_hors_cohorte"] += 1
        elif lead not in leads and lead:
            exclusions["lead_inconnu"] += 1
        if lead not in leads_valides:
            continue
        key = leads_valides[lead]["attribution"][:2]
        bucket = par_campagne[key]
        bucket["devis"].add(devis_id)
        bucket["refs"].append({"type": "m3.devis_accepte", "reference": devis_id})
    for devis_id, charge in courant.items():
        if devis_id not in devis:
            exclusions["marge_sans_devis"] += 1
            continue
        lead = devis.get(devis_id, {}).get("lead_id")
        if lead not in leads_valides:
            continue
        key = leads_valides[lead]["attribution"][:2]
        bucket = par_campagne[key]
        bucket["m5_devis"].add(devis_id)
        bucket["refs"].append(
            {"type": "m5.rentabilite_chantier", "reference": charge["evenement_id"], "sequence": charge["sequence"]}
        )
        marge_calculee = (
            charge.get("verdict") == "CALCULEE"
            and charge.get("devise") == "CAD"
            and charge.get("marge_reelle_cad") is not None
        )
        if charge.get("chantier_id") != devis[devis_id].get("chantier_id"):
            exclusions["chantier_m3_m5_contradictoire"] += 1
            bucket["manque"].add("CHANTIER_M3_M5_CONTRADICTOIRE")
            continue
        if marge_calculee:
            if not isinstance(charge["marge_reelle_cad"], str):
                raise ValueError("MARGE_M5_INVALIDE")
            try:
                marge = Decimal(charge["marge_reelle_cad"])
            except (InvalidOperation, TypeError) as exc:
                raise ValueError("MARGE_M5_INVALIDE") from exc
            if not marge.is_finite():
                raise ValueError("MARGE_M5_INVALIDE")
            bucket["wcts"][devis_id] = marge
        else:
            bucket["manque"].add("MARGE_M5_PARTIELLE")

    for bucket in par_campagne.values():
        sans_marge = bucket["devis"] - bucket["m5_devis"]
        if sans_marge:
            bucket["manque"].add("MARGE_M5_NON_OBSERVEE")
        if bucket["manque"]:
            bucket["manque"].add("SOMME_MARGES_CONNUES_SEULEMENT")

    manque = {"DEPENSES_NON_BRANCHEES", "COUVERTURE_SOURCES_NON_PROUVEE"}
    if not leads_valides and not leads_inconnus:
        manque.add("ATTRIBUTION_ABSENTE")
    if leads_inconnus:
        manque.add("ATTRIBUTION_INCONNUE")
    if anomalies:
        manque.update(anomalies)
    if exclusions["attribution_conflictuelle"]:
        manque.add("ATTRIBUTION_CONFLICTUELLE")
    output = []
    for (source, campagne), bucket in sorted(par_campagne.items()):
        subtotal = sum(bucket["wcts"].values(), Decimal("0.00"))
        missing = manque | bucket["manque"]
        output.append({
            "source": source, "campagne": campagne,
            "leads_associes_observes": len(bucket["leads"]), "devis_acceptes": len(bucket["devis"]),
            "chantiers_marge_constatee": len(bucket["wcts"]),
            "marge_constatee_M5_cad": format(subtotal, "f") if bucket["wcts"] else None,
            "statut_financier": "INCONNU", "couverture": "PARTIELLE", "manque": sorted(missing),
            "cout_ads_cad": None, "cout_par_lead_cad": None, "roi": None,
            "source_refs": _refs_uniques(bucket["refs"]),
        })
    if leads_inconnus:
        unknown_lead_ids = set(leads_inconnus)
        unknown_devis = {id_: charge for id_, charge in devis.items() if charge.get("lead_id") in unknown_lead_ids}
        unknown_refs = [{"type": "m2.client_associe", "reference": lead_id} for lead_id in unknown_lead_ids]
        unknown_refs.extend({"type": "m3.devis_accepte", "reference": devis_id} for devis_id in unknown_devis)
        unknown_bucket = {
            "source": None, "campagne": None, "leads_associes_observes": len(leads_inconnus),
            "devis_acceptes": len(unknown_devis), "chantiers_marge_constatee": 0, "marge_constatee_M5_cad": None,
            "statut_financier": "INCONNU", "couverture": "INCONNUE",
            "manque": ["ATTRIBUTION_ABSENTE"], "cout_ads_cad": None, "cout_par_lead_cad": None,
            "roi": None,
            "source_refs": _refs_uniques(unknown_refs),
        }
        output.append(unknown_bucket)
        exclusions["attribution_inconnue"] += len(leads_inconnus)
    return {
        "type": "PERFORMANCE_CAMPAGNES",
        "periode": {"debut": debut.isoformat(), "fin": fin.isoformat()},
        "couverture": "PARTIELLE" if output else "INCONNUE",
        "manque": sorted(manque), "source_refs": _refs_uniques(refs), "exclusions": exclusions, "campagnes": output,
    }
