"""Rapport privé observé : composition fermée d'outils publics T0, sans vérité financière nouvelle."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from opsys import contexte, identite, outils

from .securite import Session

MAX_OCTETS = 32 * 1024
MAX_CAMPAGNES = 50
MAX_REFERENCES = 100
_SOURCES = {
    "m7_lire_performance_campagnes": "m07-marketing",
    "m2_lister_leads": "m02-revenue-crm",
    "m8_lire_mesures_contenus": "m08-analytics",
    "m5_lire_rentabilite_chantier": "m05-financecore",
}
_DECIMAL = re.compile(r"^-?[0-9]{1,30}(?:\.[0-9]{1,8})?$")
_EMPREINTE = re.compile(r"^[0-9a-f]{64}$")


class SourceIndisponible(ValueError):
    """Diagnostic fermé : aucune charge brute d'un département ne sort dans l'erreur HTTP."""


def _texte(valeur: Any, *, nullable: bool = False) -> str | None:
    if nullable and valeur is None:
        return None
    if not isinstance(valeur, str) or not valeur or len(valeur.encode("utf-8")) > 2048:
        raise SourceIndisponible("SOURCE_FORME_INVALIDE")
    return valeur


def _nombre(valeur: Any, *, nullable: bool = False) -> int | None:
    if nullable and valeur is None:
        return None
    if type(valeur) is not int or not 0 <= valeur <= 2**63 - 1:
        raise SourceIndisponible("SOURCE_FORME_INVALIDE")
    return valeur


def _montant(valeur: Any) -> str | None:
    if valeur is None:
        return None
    if not isinstance(valeur, str) or not _DECIMAL.fullmatch(valeur):
        raise SourceIndisponible("SOURCE_MONTANT_INVALIDE")
    return valeur


def _confirmer(cnx_factory: Callable, session: Session, role: str | None = None) -> str:
    with cnx_factory() as cnx:
        personne = identite.personne_active(cnx, session.utilisateur)
        if personne is None:
            raise PermissionError("IDENTITE_HUMAINE_INACTIVE")
        if role is None:
            role = "admin" if "admin" in personne.roles else "nathan_owner"
        if role not in {"admin", "nathan_owner"} or role not in personne.roles:
            raise PermissionError("ROLE_HUMAIN_RETIRE")
    return role


def _charge(reponse: Any) -> Mapping[str, Any]:
    if not isinstance(reponse, Mapping) or reponse.get("ok") is not True:
        raise SourceIndisponible("SOURCE_REFUSEE")
    charge = reponse.get("resultat")
    if not isinstance(charge, Mapping):
        raise SourceIndisponible("SOURCE_FORME_INVALIDE")
    if charge.get("accepte") is False or charge.get("ok") is False:
        raise SourceIndisponible("SOURCE_REFUSEE")
    if charge.get("accepte") is True:
        charge = charge.get("resultat")
    if not isinstance(charge, Mapping) or charge.get("tronque") is True or charge.get("truncated") is True:
        raise SourceIndisponible("SOURCE_FORME_INVALIDE")
    return charge


def _page(charge: Mapping, *, depart: int, m2: bool) -> tuple[list, int | None, int]:
    pagination = charge if m2 else charge.get("affichage")
    lignes = charge.get("leads" if m2 else "contenus")
    if not isinstance(pagination, Mapping) or not isinstance(lignes, list) or len(lignes) > (20 if m2 else 100):
        raise SourceIndisponible("SOURCE_PAGE_INVALIDE")
    cle_depart, cle_n, cle_total, cle_suivant = (
        ("decalage", "affichees", "total", "suivant") if m2
        else ("depart", "affiches", "n_contenus", "prochain_depart")
    )
    total = _nombre(pagination.get(cle_total))
    nombre = _nombre(pagination.get(cle_n))
    reste = _nombre(pagination.get("reste"))
    suivant = _nombre(pagination.get(cle_suivant), nullable=True)
    if pagination.get(cle_depart) != depart or type(pagination.get(cle_depart)) is not int:
        raise SourceIndisponible("SOURCE_PAGE_INVALIDE")
    if nombre != len(lignes) or depart + nombre + reste != total:
        raise SourceIndisponible("SOURCE_PAGE_INVALIDE")
    if (reste == 0 and suivant is not None) or (reste > 0 and (suivant != depart + nombre or nombre == 0)):
        raise SourceIndisponible("SOURCE_CURSEUR_INVALIDE")
    return lignes, suivant, reste


def construire(
    session: Session, deps: Mapping, cnx_factory: Callable, *, debut: str, fin: str,
) -> dict[str, Any]:
    """Ne reçoit que deux dates ; noms d'outils, budgets et identité sont choisis côté serveur."""
    try:
        debut_date, fin_date = date.fromisoformat(debut), date.fromisoformat(fin)
    except (TypeError, ValueError) as exc:
        raise ValueError("PERIODE_DATE_INVALIDE") from exc
    if debut_date.isoformat() != debut or fin_date.isoformat() != fin or not 0 <= (fin_date - debut_date).days <= 365:
        raise ValueError("PERIODE_DATE_INVALIDE")
    role = _confirmer(cnx_factory, session)
    lue_le = datetime.now(UTC).isoformat()
    appels = 0

    def appeler(nom: str, arguments: Mapping) -> Mapping:
        nonlocal appels
        _confirmer(cnx_factory, session, role)
        departement = _SOURCES[nom]
        dep = deps.get(departement)
        if dep is None:
            raise SourceIndisponible("SOURCE_ABSENTE")
        catalogue = [o for o in dep.charger_outils() if o.nom == nom]
        if len(catalogue) != 1 or catalogue[0].autonomie != outils.Autonomie.T0 \
                or catalogue[0].niveau_effectif != outils.Niveau.N0:
            raise SourceIndisponible("SOURCE_CONTRAT_INVALIDE")
        if appels >= 9:
            raise SourceIndisponible("SOURCE_BUDGET_APPELS")
        appels += 1
        with cnx_factory(), contexte.appeler_en_tant_que(departement, origine="m07-marketing"), \
                contexte.appele_par_appareil(contexte.IdentiteAppelante(session.utilisateur, role, "console")):
            reponse = outils.executer_atomique(catalogue[0], arguments)
        _confirmer(cnx_factory, session, role)
        return _charge(reponse)

    performance = appeler("m7_lire_performance_campagnes", {"debut": debut, "fin": fin})
    campagnes = performance.get("campagnes")
    refs = performance.get("source_refs")
    observation = performance.get("observation_source")
    if not isinstance(campagnes, list) or not isinstance(refs, list) or not isinstance(observation, Mapping) \
            or performance.get("type") != "PERFORMANCE_CAMPAGNES" \
            or performance.get("periode") != {"debut": debut, "fin": fin}:
        raise SourceIndisponible("SOURCE_M7_INVALIDE")
    if observation.get("integrite") != "historique_non_scelle":
        raise SourceIndisponible("SOURCE_M7_INVALIDE")
    if not isinstance(observation.get("empreinte_lecture_sha256"), str) \
            or not _EMPREINTE.fullmatch(observation["empreinte_lecture_sha256"]):
        raise SourceIndisponible("SOURCE_M7_INVALIDE")
    exclusions = performance.get("exclusions")
    if not isinstance(exclusions, Mapping):
        raise SourceIndisponible("SOURCE_M7_INVALIDE")
    exclusions = {_texte(cle): _nombre(nombre) for cle, nombre in exclusions.items()}
    references = []
    leads, devis = set(), []
    for ref in refs:
        if not isinstance(ref, Mapping):
            raise SourceIndisponible("SOURCE_M7_INVALIDE")
        type_, reference = _texte(ref.get("type")), _texte(ref.get("reference"))
        if type_ == "m2.client_associe":
            leads.add(reference)
        elif type_ == "m3.devis_accepte" and reference not in devis:
            devis.append(reference)
        if len(references) < MAX_REFERENCES:
            propre = {"type": type_, "reference": reference}
            if "sequence" in ref:
                propre["sequence"] = _nombre(ref["sequence"])
            references.append(propre)

    lignes_campagnes = []
    indices_refs = {(r["type"], r["reference"], r.get("sequence")): i for i, r in enumerate(references)}
    total_liens = 0
    for campagne in campagnes:
        if not isinstance(campagne, Mapping) or not isinstance(campagne.get("source_refs"), list):
            raise SourceIndisponible("SOURCE_M7_INVALIDE")
        total_liens += len(campagne["source_refs"])
    for ligne in campagnes[:MAX_CAMPAGNES]:
        if not isinstance(ligne, Mapping):
            raise SourceIndisponible("SOURCE_M7_INVALIDE")
        propre = {cle: _texte(ligne.get(cle), nullable=True) for cle in ("source", "campagne")}
        propre.update({cle: _nombre(ligne.get(cle)) for cle in (
            "leads_associes_observes", "devis_acceptes", "chantiers_marge_constatee",
        )})
        propre["marge_constatee_M5_cad"] = _montant(ligne.get("marge_constatee_M5_cad"))
        propre.update(cout_ads_cad=None, cout_par_lead_cad=None, roi=None)
        propre["couverture"] = _texte(ligne.get("couverture"))
        manque = ligne.get("manque")
        if not isinstance(manque, list) or len(manque) > 128:
            raise SourceIndisponible("SOURCE_M7_INVALIDE")
        propre["manque"] = [_texte(m) for m in manque]
        propre["references_indices"] = [
            indices_refs[cle] for ref in ligne["source_refs"] if isinstance(ref, Mapping)
            and (cle := (ref.get("type"), ref.get("reference"), ref.get("sequence"))) in indices_refs
        ]
        lignes_campagnes.append(propre)

    resultat = {
        "type": "RAPPORT_ACQUISITION_OBSERVEE", "periode_metier": {"debut": debut, "fin": fin},
        "lue_le": lue_le, "observation_source": dict(observation),
        "campagnes": lignes_campagnes, "references": references,
        "exclusions_m7": exclusions,
        "crm_courant": {"statut": "NON_AUTORISEE", "lignes": [], "reste_source": None},
        "contenus_cumules": {"statut": "NON_AUTORISEE", "lignes": [], "reste_source": None},
        "finance_courante": {"statut": "PARTIELLE", "lignes": [], "devis_non_lus": max(0, len(devis) - 4)},
        "omissions": {"campagnes": max(0, len(campagnes) - MAX_CAMPAGNES),
                      "references": max(0, len(refs) - MAX_REFERENCES), "crm": 0, "contenus": 0, "finance": 0,
                      "liens_campagnes": total_liens - sum(len(c["references_indices"]) for c in lignes_campagnes)},
        "limites": [
            "Faits disponibles à la lecture, pas une photographie connue à la fin de la période.",
            "Historique non scellé : l'empreinte de lecture n'authentifie pas les producteurs passés.",
            "CRM et finance courants ; M8 cumulé sans période : ces sections ne s'additionnent pas.",
            "Dépenses publicitaires non branchées, ROI inconnu, aucune causalité démontrée.",
            "Neuf appels maximum ; les lecteurs amont peuvent encore lire tout leur historique.",
        ],
    }
    if role == "admin":
        for nom, section, m2 in (
            ("m2_lister_leads", "crm_courant", True), ("m8_lire_mesures_contenus", "contenus_cumules", False),
        ):
            lignes, depart, reste, total_attendu = [], 0, 0, None
            leads_vus = set()
            try:
                for _ in range(2):
                    arguments = {"horodatage": lue_le, "decalage": depart, "limite": 20} if m2 else {"depart": depart}
                    charge = appeler(nom, arguments)
                    page, suivant, reste = _page(charge, depart=depart, m2=m2)
                    pagination = charge if m2 else charge["affichage"]
                    total_page = pagination["total" if m2 else "n_contenus"]
                    if total_attendu is not None and total_page != total_attendu:
                        raise SourceIndisponible("SOURCE_PAGE_CHANGEANTE")
                    total_attendu = total_page
                    for ligne in page:
                        if not isinstance(ligne, Mapping):
                            raise SourceIndisponible("SOURCE_PAGE_INVALIDE")
                        if m2:
                            lead_id = _texte(ligne.get("lead_id"))
                            if lead_id in leads_vus:
                                raise SourceIndisponible("SOURCE_PAGE_REPETEE")
                            leads_vus.add(lead_id)
                            if lead_id in leads:
                                lignes.append({"lead_id": lead_id, "statut": _texte(ligne.get("statut"))})
                        else:
                            propre = {cle: _texte(ligne.get(cle), nullable=True) for cle in (
                                "utm_content", "canal", "exporte_le", "suivi",
                            )}
                            propre.update({cle: _nombre(ligne.get(cle), nullable=True) for cle in (
                                "leads", "devis_envoyes", "devis_acceptes",
                            )})
                            lignes.append(propre)
                    if suivant is None:
                        break
                    depart = suivant
                resultat[section] = {"statut": "PARTIELLE" if reste else "PAGES_LUES",
                                     "lignes": lignes, "reste_source": reste}
                if m2:
                    resultat[section]["leads_references_non_rencontres"] = len(
                        leads - {ligne["lead_id"] for ligne in lignes}
                    )
                if not m2:
                    sources = charge.get("sources")
                    if not isinstance(sources, list) or len(sources) > 16 \
                            or not all(isinstance(s, Mapping) for s in sources):
                        raise SourceIndisponible("SOURCE_M8_INVALIDE")
                    resultat[section]["sources"] = [{
                        "evenement": _texte(s.get("evenement")), "faits_recus": _nombre(s.get("n")),
                        "dernier_fait_le": _texte(s.get("dernier_fait_le"), nullable=True),
                    } for s in sources]
            except (SourceIndisponible, KeyError, TypeError):
                resultat[section] = {"statut": "INDISPONIBLE_OU_INVALIDE", "lignes": [], "reste_source": None}

    for devis_id in devis[:4]:
        try:
            charge = appeler("m5_lire_rentabilite_chantier", {"devis_id": devis_id, "limite": 1})
            chantiers = charge.get("chantiers")
            if not isinstance(chantiers, list) or len(chantiers) != 1 or chantiers[0].get("devis_id") != devis_id:
                raise SourceIndisponible("SOURCE_M5_INVALIDE")
            chantier = chantiers[0]
            propre = {"devis_id": devis_id, "statut": _texte(chantier.get("statut"))}
            rentabilite, trace = chantier.get("rentabilite"), chantier.get("trace")
            if rentabilite is not None:
                if not isinstance(rentabilite, Mapping) or not isinstance(trace, Mapping):
                    raise SourceIndisponible("SOURCE_M5_INVALIDE")
                propre.update({cle: _montant(rentabilite.get(cle)) for cle in ("prix_facture", "marge_reelle")})
                propre["verdict"] = _texte(rentabilite.get("verdict"))
                if type(rentabilite.get("prix_definitif")) is not bool or type(trace.get("a_jour")) is not bool:
                    raise SourceIndisponible("SOURCE_M5_INVALIDE")
                propre["prix_definitif"] = rentabilite["prix_definitif"]
                version = _texte(trace.get("version_entrees"))
                if not _EMPREINTE.fullmatch(version):
                    raise SourceIndisponible("SOURCE_M5_INVALIDE")
                propre["trace"] = {"version_entrees": version, "a_jour": trace["a_jour"]}
                cout = rentabilite.get("cout_reel")
                if not isinstance(cout, Mapping) or type(cout.get("complet")) is not bool:
                    raise SourceIndisponible("SOURCE_M5_INVALIDE")
                propre["cout_reel"] = {"complet": cout["complet"], "cout_total": _montant(cout.get("cout_total")),
                                       "cout_total_connu": _montant(cout.get("cout_total_connu"))}
                manque = rentabilite.get("manque")
                if not isinstance(manque, list) or len(manque) > 128 or not all(isinstance(m, Mapping) for m in manque):
                    raise SourceIndisponible("SOURCE_M5_INVALIDE")
                propre["manque"] = [_texte(m.get("code")) for m in manque]
            resultat["finance_courante"]["lignes"].append(propre)
        except (SourceIndisponible, KeyError, TypeError, AttributeError):
            resultat["finance_courante"]["lignes"].append({"devis_id": devis_id, "statut": "INCONNU_SOURCE"})

    resultat["budget"] = {"appels_effectues": appels, "maximum_appels": 9, "maximum_octets": MAX_OCTETS}
    _borner_sortie(resultat)
    _confirmer(cnx_factory, session, role)
    return resultat


def _borner_sortie(resultat: dict[str, Any]) -> None:
    collections = [(resultat, "campagnes", "campagnes"), (resultat, "references", "references"),
                   (resultat["crm_courant"], "lignes", "crm"),
                   (resultat["contenus_cumules"], "lignes", "contenus"),
                   (resultat["finance_courante"], "lignes", "finance")]
    while len(json.dumps(
        {"ok": True, "resultat": resultat}, ensure_ascii=False, allow_nan=False,
    ).encode()) > MAX_OCTETS:
        candidats = [(parent, cle, compteur) for parent, cle, compteur in collections if parent[cle]]
        if not candidats:
            raise SourceIndisponible("RAPPORT_SQUELETTE_TROP_GRAND")
        parent, cle, compteur = max(candidats, key=lambda item: len(json.dumps(
            item[0][item[1]][-1], ensure_ascii=False,
        )))
        retire = parent[cle].pop()
        resultat["omissions"][compteur] += 1
        if cle == "campagnes":
            resultat["omissions"]["liens_campagnes"] += len(retire["references_indices"])
        if cle == "references":
            for campagne in resultat["campagnes"]:
                avant = campagne["references_indices"]
                campagne["references_indices"] = [i for i in avant if i < len(resultat["references"])]
                resultat["omissions"]["liens_campagnes"] += len(avant) - len(campagne["references_indices"])
