"""Adaptateur des outils M3.2 (contexte de site), M3.3/M3.5 (vision) et M3.7 (géospatial).

Toute la logique est dans des modules purs (``contexte_site``, ``vision_*``, ``geometrie_polygone``, ``geospatial``) ;
ce module choisit le support durable (journal ``site_vision``), lit la configuration, publie les événements et déclare
les outils. Il vit à part de ``outils.py`` (déjà très long) et y est assemblé par ``outils()``.

Aucun détecteur de vision n'est branché en production (``_DETECTEURS`` vide) : l'outil de pipeline le dit. Les tests
branchent des doubles (``brancher_detecteur``) ; un futur service local de détection s'y branchera de la même façon,
sans toucher à la gouvernance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from opsys import approbations, contexte, evenements, stockage
from opsys import meteo as meteo_opsys
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage.schema import APPROBATIONS

from . import (
    contexte_site,
    geometrie_polygone,
    geospatial,
    journal_site,
    politique_photos,
    verdicts,
    vision_contrat,
    vision_gouvernance,
    vision_modeles,
)

_DEPARTEMENT = "m03-estimation"
_REGISTRE = "site_vision"
_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"
_CHEMIN_POLITIQUE_PHOTOS = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "compliance"
    / "politiques"
    / "POLITIQUE-photos-non-contractuelles.md"
)
_ESSAIS = 3
_OUTIL_HUMAIN = "m3_valider_candidat_par_humain"

# Détecteurs branchés (port ``DetecteurVision``). VIDE en production : aucun modèle de vision n'est installé ni
# qualifié.
_DETECTEURS: dict[str, Any] = {}
# Ports géospatiaux branchés. Par défaut : aucune source (``PortAbsent``).
_PORTS_GEO: dict[str, Any] = {
    "cadastre": geospatial.PortAbsent(),
    "role": geospatial.PortAbsent(),
    "imagerie": geospatial.PortAbsent(),
}


def brancher_detecteur(detecteur: Any) -> None:
    """Branche un détecteur derrière le port (tests, futur service local). Jamais appelé par un outil."""
    _DETECTEURS[detecteur.modele.identifiant] = detecteur


def debrancher_detecteurs() -> None:
    _DETECTEURS.clear()


def brancher_ports_geospatiaux(*, cadastre: Any = None, role: Any = None, imagerie: Any = None) -> None:
    for nom, port in (("cadastre", cadastre), ("role", role), ("imagerie", imagerie)):
        if port is not None:
            _PORTS_GEO[nom] = port


def debrancher_ports_geospatiaux() -> None:
    _PORTS_GEO.update(
        {"cadastre": geospatial.PortAbsent(), "role": geospatial.PortAbsent(), "imagerie": geospatial.PortAbsent()}
    )


def _refus(code: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "verdict": verdicts.construire_verdict(code, detail)}


def _journal() -> journal_site.JournalSite:
    return journal_site.JournalSite(stockage.maillons(_DEPARTEMENT, _REGISTRE))


def _ecrire(operation: Any) -> Any:
    for _ in range(_ESSAIS - 1):
        try:
            return operation()
        except stockage.EcritureConcurrente:
            continue
    return operation()


def _journal_sain(journal: journal_site.JournalSite) -> dict[str, Any] | None:
    ok, raison = journal.valider_chaine()
    return None if ok else _refus("REJ-SITE-JOURNAL-ALTERE", f"chaîne du journal altérée ({raison}) : rien n'est écrit")


def _configuration() -> dict[str, Any]:
    try:
        brut = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    configuration = brut.get("configuration") if isinstance(brut, dict) else None
    return configuration if isinstance(configuration, dict) else {}


def _politique_vision() -> Any:
    """``configuration.vision_gouvernance`` de ``department.yaml`` : VIDE à dessein (décision de l'entreprise, jamais un
    défaut inventé). Un appelant ne la fournit pas : un agent ne peut pas se donner sa propre tolérance."""
    return _configuration().get("vision_gouvernance")


def _politique_photos_validee() -> bool:
    try:
        return politique_photos.politique_est_validee(_CHEMIN_POLITIQUE_PHOTOS.read_text(encoding="utf-8"))
    except OSError:
        return False


def _cnx() -> Any:
    return stockage.connexion_courante()


# ---------------------------------------------------------------------------------------------------- M3.2
def _meteo_service(service: str) -> dict[str, Any]:
    profil, _verdict = meteo_opsys.charger_meteo()
    if profil is None:
        return {
            "service": service,
            "profil_present": False,
            "risques_juges": [],
            "sans_objet": [],
            "a_decider": list(meteo_opsys.RISQUES),
        }
    regles = profil.get(meteo_opsys.CLE_SERVICES_METEO, {}).get(service)
    a_decider = meteo_opsys.risques_a_decider(regles)
    sans_objet = sorted(regles.get(meteo_opsys.CLE_SANS_OBJET, ())) if regles else []
    juges = [r for r in meteo_opsys.RISQUES if r not in a_decider and r not in sans_objet]
    return {
        "service": service,
        "profil_present": True,
        "reference": meteo_opsys.empreinte_meteo(profil),
        "fuseau": profil.get(meteo_opsys.CLE_FUSEAU),
        "risques_juges": juges,
        "sans_objet": sans_objet,
        "a_decider": a_decider,
    }


def _dernier_contexte(journal: journal_site.JournalSite, lead_id: str) -> dict[str, Any] | None:
    for maillon in reversed(journal.lire(journal_site.TYPE_CONTEXTE)):
        if maillon["charge"]["lead_id"] == lead_id:
            return maillon["charge"]
    return None


def construire_contexte_site(
    lead_id: str,
    service: str,
    date_reference: str,
    municipalite: str | None = None,
    profil_propriete: dict[str, Any] | None = None,
    profil_geospatial: dict[str, Any] | None = None,
    facteurs_declares: dict[str, Any] | None = None,
    permis_municipaux: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    journal = _journal()
    altere = _journal_sain(journal)
    if altere is not None:
        return altere
    entrees: dict[str, Any] = {"lead_id": lead_id, "service": service, "date_reference": date_reference}
    for cle, valeur in (
        ("municipalite", municipalite),
        ("profil_propriete", profil_propriete),
        ("profil_geospatial", profil_geospatial),
        ("facteurs_declares", facteurs_declares),
        ("permis_municipaux", permis_municipaux),
    ):
        if valeur is not None:
            entrees[cle] = valeur
    if isinstance(service, str) and service:
        entrees["meteo_service"] = _meteo_service(service)
    precedent = _dernier_contexte(journal, lead_id) if isinstance(lead_id, str) else None
    resultat, verdict = contexte_site.construire(entrees, precedent)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    nouvelle = precedent is None or resultat["empreinte"] != precedent["empreinte"]
    if nouvelle:
        _ecrire(lambda: journal.ajouter(journal_site.TYPE_CONTEXTE, resultat))
        evenements.publier(
            "m3.contexte_site_pret",
            _DEPARTEMENT,
            {
                "lead_id": resultat["lead_id"],
                "service": resultat["service"],
                "version": resultat["version"],
                "empreinte": resultat["empreinte"],
                "date_reference": resultat["date_reference"],
                "facteurs": [
                    {
                        "facteur": f["facteur"],
                        "statut": f["statut"],
                        "valeur": f["valeur"] if f["statut"] == "connu" else None,
                    }
                    for f in resultat["facteurs"]
                ],
                "inconnus": resultat["inconnus"],
                "a_verifier": resultat["a_verifier"],
                "conflits": resultat["conflits"],
            },
            evenement_id=f"m3-contexte-site-{resultat['lead_id']}-v{resultat['version']}",
        )
    return {"accepte": True, "resultat": {"contexte": resultat, "nouvelle_version": nouvelle}}


def lire_contexte_site(lead_id: str, version: int | None = None) -> dict[str, Any]:
    journal = _journal()
    altere = _journal_sain(journal)
    if altere is not None:
        return altere
    versions = [m["charge"] for m in journal.lire(journal_site.TYPE_CONTEXTE) if m["charge"]["lead_id"] == lead_id]
    if version is not None:
        versions = [v for v in versions if v["version"] == version]
    if not versions:
        return _refus(
            "REJ-CONTEXTE-INTROUVABLE", "aucune version du contexte de site pour ce lead (la construire d'abord)"
        )
    return {
        "accepte": True,
        "resultat": {
            "contexte": versions[-1],
            "versions": len(versions),
            "hypotheses": contexte_site.resume_hypotheses(versions[-1]),
        },
    }


def resume_contexte_pour_estimation(
    lead_id: str, empreinte: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Ce que `m3_estimer_projet` reprend d'une version du contexte de site (hypothèses, manques) ; `(None, verdict)`
    si l'empreinte
    n'est celle d'aucune version de CE lead. Doit s'appeler dans la transaction de l'appel. Lecture seule."""
    journal = _journal()
    ok, raison = journal.valider_chaine()
    if not ok:
        return None, verdicts.construire_verdict("REJ-SITE-JOURNAL-ALTERE", f"chaîne du journal altérée ({raison})")
    versions = [m["charge"] for m in journal.lire(journal_site.TYPE_CONTEXTE) if m["charge"]["lead_id"] == lead_id]
    trouvee = next((v for v in versions if v["empreinte"] == empreinte), None)
    if trouvee is None:
        return None, verdicts.construire_verdict(
            "REJ-CONTEXTE-INTROUVABLE", "aucune version du contexte de site de ce lead n'a cette empreinte"
        )
    return {
        **contexte_site.resume_hypotheses(trouvee),
        "version_courante": trouvee is versions[-1] or trouvee["empreinte"] == versions[-1]["empreinte"],
    }, None


# ---------------------------------------------------------------------------------------------------- M3.3, M3.5
def _candidats_et_decisions(
    journal: journal_site.JournalSite,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    candidats = {m["charge"]["candidat"]["candidat_id"]: m["charge"] for m in journal.lire(journal_site.TYPE_CANDIDAT)}
    decisions = {m["charge"]["decision"]["candidat_id"]: m["charge"] for m in journal.lire(journal_site.TYPE_DECISION)}
    return candidats, decisions


def executer_pipeline_vision(lead_id: str, photo: dict[str, Any], objets: list[str], modele_id: str) -> dict[str, Any]:
    if not isinstance(lead_id, str) or not lead_id.strip():
        return _refus("REJ-VISION-PHOTO-INVALIDE", "lead_id requis")
    detecteur = _DETECTEURS.get(modele_id) if isinstance(modele_id, str) else None
    if detecteur is None:
        return _refus(
            "REJ-VISION-MODELE-INCONNU",
            "aucun détecteur de vision n'est branché sous ce nom (contrat prêt, aucun modèle qualifié)",
        )
    journal = _journal()
    altere = _journal_sain(journal)
    if altere is not None:
        return altere
    qualifies = vision_modeles.modeles_qualifies(vision_modeles.vues(_cnx()))
    sortie, verdict = vision_contrat.executer(
        photo, detecteur, objets, politique_validee=_politique_photos_validee(), modeles_qualifies=qualifies
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    connus, _ = _candidats_et_decisions(journal)
    nouveaux = 0
    for candidat in sortie["candidats"]:
        if candidat["candidat_id"] not in connus:
            _ecrire(lambda c=candidat: journal.ajouter(journal_site.TYPE_CANDIDAT, {"candidat": c, "lead_id": lead_id}))
            nouveaux += 1
    return {"accepte": True, "resultat": {**sortie, "nouveaux_candidats_journalises": nouveaux}}


def lire_candidats_vision(photo_id: str | None = None, candidat_id: str | None = None) -> dict[str, Any]:
    journal = _journal()
    altere = _journal_sain(journal)
    if altere is not None:
        return altere
    candidats, decisions = _candidats_et_decisions(journal)
    politique, verdict_politique = vision_gouvernance.lire_politique(_politique_vision())
    lignes = []
    for ident, entree in candidats.items():
        c = entree["candidat"]
        if (photo_id is not None and c["photo_id"] != photo_id) or (candidat_id is not None and ident != candidat_id):
            continue
        decision = decisions.get(ident, {}).get("decision")
        lignes.append(
            {
                "candidat": c,
                "lead_id": entree["lead_id"],
                "decision": decision,
                "evaluation": None if politique is None else vision_gouvernance.evaluer(c, politique),
                "statut": decision["statut"] if decision else "candidate_non_validee",
            }
        )
    return {
        "accepte": True,
        "resultat": {
            "candidats": lignes,
            "politique_declaree": politique is not None,
            "politique_manque": None if politique is not None else verdict_politique["detail"],
        },
    }


def _charger_candidat(
    journal: journal_site.JournalSite, candidat_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """``(entrée, décision existante)`` ou ``(None, verdict)`` si le candidat est inconnu."""
    candidats, decisions = _candidats_et_decisions(journal)
    entree = candidats.get(candidat_id) if isinstance(candidat_id, str) else None
    if entree is None:
        return None, verdicts.construire_verdict(
            "REJ-VISION-CANDIDAT-INTROUVABLE", "aucun candidat de ce nom au journal"
        )
    return entree, decisions.get(candidat_id)


def _enregistrer_decision(
    journal: journal_site.JournalSite,
    entree: dict[str, Any],
    existante: dict[str, Any] | None,
    decision: dict[str, Any],
) -> dict[str, Any]:
    if existante is not None:
        if existante["decision"]["empreinte"] == decision["empreinte"]:
            return {"accepte": True, "resultat": {"decision": existante["decision"], "rejoue": True}}
        return _refus(
            "REJ-VISION-DECISION-CONFLIT",
            f"une décision existe déjà pour ce candidat ({existante['decision']['statut']}) : elle est immuable",
        )
    _ecrire(lambda: journal.ajouter(journal_site.TYPE_DECISION, {"decision": decision, "lead_id": entree["lead_id"]}))
    if decision["utilisable_comme_mesure"]:
        c = entree["candidat"]
        evenements.publier(
            "m3.mesure_vision_validee",
            _DEPARTEMENT,
            {
                "lead_id": entree["lead_id"],
                "candidat_id": c["candidat_id"],
                "photo_id": c["photo_id"],
                "objet": c["objet"],
                "grandeur": c["grandeur"],
                "unite": decision["unite"],
                "valeur_retenue": decision["valeur_retenue"],
                "incertitude_emploi": decision["incertitude_emploi"],
                "origine_valeur": decision["origine_valeur"],
                "voie": decision["voie"],
                "decision_empreinte": decision["empreinte"],
                "modele": {"identifiant": c["modele"]["identifiant"], "version": c["modele"]["version"]},
            },
            evenement_id=f"m3-mesure-vision-{c['candidat_id']}",
        )
    return {"accepte": True, "resultat": {"decision": decision, "rejoue": False}}


def valider_candidat_par_reference(candidat_id: str, reference: dict[str, Any]) -> dict[str, Any]:
    politique, verdict = vision_gouvernance.lire_politique(_politique_vision())
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    journal = _journal()
    altere = _journal_sain(journal)
    if altere is not None:
        return altere
    entree, existante = _charger_candidat(journal, candidat_id)
    if entree is None:
        return {"accepte": False, "verdict": existante}
    decision, verdict = vision_gouvernance.decider_par_reference(entree["candidat"], politique, reference)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return _enregistrer_decision(journal, entree, existante, decision)


def _decision_humaine(arguments: dict[str, Any]) -> tuple[str, str, str] | None:
    """``(personne, demande, instant)`` de la décision approuvée qui fait exécuter CET appel, sinon ``None``."""
    cnx = _cnx()
    if cnx is None:
        return None
    signataire = approbations.approbateur_en_cours(cnx, _OUTIL_HUMAIN, _DEPARTEMENT)
    demande = contexte.demande_approuvee_en_cours()
    if signataire is None or demande is None:
        return None
    ligne = cnx.execute(
        select(APPROBATIONS.c.arguments, APPROBATIONS.c.decide_le).where(APPROBATIONS.c.id == demande)
    ).one_or_none()
    if ligne is None or not ligne.decide_le or json.loads(ligne.arguments) != arguments:
        return None
    return signataire.personne, str(demande), ligne.decide_le


def valider_candidat_par_humain(candidat_id: str, decision: str, valeur_corrigee: str | None = None) -> dict[str, Any]:
    arguments = {"candidat_id": candidat_id, "decision": decision, "valeur_corrigee": valeur_corrigee}
    approuvee = _decision_humaine(arguments)
    if approuvee is None:
        return _refus(
            "REJ-VISION-DECISION-SANS-APPROBATION",
            "la validation d'un candidat par une personne ne s'exécute que sur une décision approuvée dans la "
            "file "
            "d'approbation OPSYS ; ne présente pas la mesure comme validée",
        )
    politique, verdict = vision_gouvernance.lire_politique(_politique_vision())
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    journal = _journal()
    altere = _journal_sain(journal)
    if altere is not None:
        return altere
    entree, existante = _charger_candidat(journal, candidat_id)
    if entree is None:
        return {"accepte": False, "verdict": existante}
    personne, demande, instant = approuvee
    validation = {"valide_par": personne, "valide_le": instant, "approbation_ref": demande, "decision": decision}
    if valeur_corrigee is not None:
        validation["valeur_corrigee"] = valeur_corrigee
    resultat, verdict = vision_gouvernance.decider_par_humain(entree["candidat"], politique, validation)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return _enregistrer_decision(journal, entree, existante, resultat)


def lister_modeles_vision() -> dict[str, Any]:
    cnx = _cnx()
    if cnx is None:
        with stockage.transaction() as ouverte:
            return {"accepte": True, "resultat": vision_modeles.synthese(vision_modeles.vues(ouverte))}
    return {"accepte": True, "resultat": vision_modeles.synthese(vision_modeles.vues(cnx))}


# ---------------------------------------------------------------------------------------------------- M3.7
def calculer_aire_polygone(
    systeme: str,
    sommets: list[list[str]],
    incertitude_position_m: str | None = None,
    facteur_echelle_grille: str | None = None,
) -> dict[str, Any]:
    entrees: dict[str, Any] = {"systeme": systeme, "sommets": sommets}
    if incertitude_position_m is not None:
        entrees["incertitude_position_m"] = incertitude_position_m
    if facteur_echelle_grille is not None:
        entrees["facteur_echelle_grille"] = facteur_echelle_grille
    recu, verdict = geometrie_polygone.calculer(entrees)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": {"recu": recu}}


def agreger_donnees_geospatiales(adresse: dict[str, Any]) -> dict[str, Any]:
    resultat, verdict = geospatial.agreger(adresse, _PORTS_GEO["cadastre"], _PORTS_GEO["role"], _PORTS_GEO["imagerie"])
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": resultat}


def lister_sources_geospatiales() -> dict[str, Any]:
    return {
        "accepte": True,
        "resultat": {
            "sources_candidates": geospatial.sources_candidates(),
            "ports": {
                nom: ("non_configure" if isinstance(p, geospatial.PortAbsent) else "branche")
                for nom, p in _PORTS_GEO.items()
            },
            "mise_en_garde": "Toutes les sources sont à vérifier (licence, couverture, fraîcheur) ; "
            "aucune n'est utilisée ici.",
        },
    }


# ---------------------------------------------------------------------------------------------------- déclarations
_OBJET = {"type": "object"}


def _schema(proprietes: dict[str, Any], requis: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False}


def outils_site_vision() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m3_construire_contexte_site",
            description=(
                "Agrège le contexte du site d'un lead (accès, hauteur, pente, âge, matériaux existants, contraintes "
                "saisonnières, "
                "règles météo de l'entreprise pour le service, permis municipaux) depuis le profil de propriété de M2, "
                "un profil "
                "géospatial et des déclarations SOURCÉES. Un facteur sans source est « inconnu », un permis reste « à "
                "vérifier », "
                "deux sources qui se contredisent sont un « conflit » : rien n'est inventé ni tranché. Rend une "
                "version "
                "chaînée du contexte, ses hypothèses d'estimation structurées et publie m3.contexte_site_pret. Ne "
                "chiffre aucun "
                "effet sur le prix. Permis : À valider auprès d'un professionnel qualifié (municipalité)."
            ),
            parametres=_schema(
                {
                    "lead_id": {"type": "string"},
                    "service": {"type": "string", "description": "code du service déclaré"},
                    "date_reference": {"type": "string", "description": "AAAA-MM-JJ, fournie (aucune horloge)"},
                    "municipalite": {"type": "string"},
                    "profil_propriete": {
                        "type": "object",
                        "description": "{identifiant, version, recu_le, faits} : profil M2",
                    },
                    "profil_geospatial": {
                        "type": "object",
                        "description": "faits_pour_contexte de m3_agreger_donnees_geospatiales",
                    },
                    "facteurs_declares": {
                        "type": "object",
                        "description": "{facteur: {valeur, declare_par, declare_le, reference?}}",
                    },
                    "permis_municipaux": {
                        "type": "array",
                        "items": _OBJET,
                        "description": "[{type_permis, exigence, verifie_par, verifie_le, reference}]",
                    },
                },
                ["lead_id", "service", "date_reference"],
            ),
            fonction=construire_contexte_site,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m3_lire_contexte_site",
            description="Relit la dernière version (ou une version donnée) du contexte de site d'un lead, avec ses "
            "hypothèses "
            "d'estimation. Lecture seule.",
            parametres=_schema({"lead_id": {"type": "string"}, "version": {"type": "integer"}}, ["lead_id"]),
            fonction=lire_contexte_site,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m3_executer_pipeline_vision",
            description=(
                "Fait passer une photo (empreinte, dimensions, provenance, échelle) dans un détecteur de vision "
                "branché "
                "derrière le "
                "port et journalise des CANDIDATS de mesures (géométrie + confiance ; la valeur est calculée par le "
                "code depuis "
                "l'échelle). Un candidat n'est JAMAIS une mesure. Aucun détecteur n'est branché aujourd'hui : l'outil "
                "refuse "
                "(contrat prêt, aucun modèle qualifié). Une photo réelle exige une politique photos validée, un "
                "consentement et un "
                "modèle qualifié activé."
            ),
            parametres=_schema(
                {
                    "lead_id": {"type": "string"},
                    "photo": {
                        "type": "object",
                        "description": "{photo_id, empreinte_sha256, largeur, hauteur, provenance, echelle?}",
                    },
                    "objets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "codes d'objets à chercher (1 à 10)",
                    },
                    "modele_id": {"type": "string"},
                },
                ["lead_id", "photo", "objets", "modele_id"],
            ),
            fonction=executer_pipeline_vision,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m3_lire_candidats_vision",
            description="Liste les candidats de mesures issus de la vision (d'une photo ou d'un candidat), leur "
            "évaluation face à "
            "la politique déclarée par l'entreprise et la décision prise. Lecture seule.",
            parametres=_schema({"photo_id": {"type": "string"}, "candidat_id": {"type": "string"}}, []),
            fonction=lire_candidats_vision,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m3_valider_candidat_par_reference",
            description=(
                "Confronte un candidat de vision à une MESURE DE RÉFÉRENCE (mesure manuelle, plan, mesure plane M3.6) "
                "de même "
                "unité : validé seulement si l'écart respecte la tolérance déclarée par l'entreprise, sinon rejeté "
                "pour "
                "écart. La "
                "politique (seuil de confiance, tolérances) vient de la configuration, jamais de l'appelant. Une "
                "décision par "
                "candidat, immuable. Publie m3.mesure_vision_validee quand validé."
            ),
            parametres=_schema(
                {
                    "candidat_id": {"type": "string"},
                    "reference": {
                        "type": "object",
                        "description": "{reference_id, source, valeur, unite, mesure_par, mesure_le, "
                        "incertitude_absolue?}",
                    },
                },
                ["candidat_id", "reference"],
            ),
            fonction=valider_candidat_par_reference,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom=_OUTIL_HUMAIN,
            description=(
                "Décision d'une PERSONNE sur un candidat de vision : valider, refuser ou valider avec une valeur "
                "corrigée. "
                "S'exécute seulement sur une décision approuvée dans la file d'approbation (N3) ; la personne et "
                "l'heure viennent de "
                "l'approbation, jamais des arguments. Une décision par candidat, immuable."
            ),
            parametres=_schema(
                {
                    "candidat_id": {"type": "string"},
                    "decision": {"type": "string", "enum": ["valider", "refuser"]},
                    "valeur_corrigee": {
                        "type": ["string", "null"],
                        "description": "texte décimal, avec « valider » seulement",
                    },
                },
                ["candidat_id", "decision", "valeur_corrigee"],
            ),
            fonction=valider_candidat_par_humain,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m3_lister_modeles_vision",
            description="État du registre des modèles de vision (capacité « vision » du registre de fournisseurs) : "
            "drapeaux de "
            "licence, qualification, activation et conclusion honnête (aucun modèle qualifié tant que rien "
            "n'est "
            "mesuré sur des photos réelles consenties). Aucun poids téléchargé. Lecture seule.",
            parametres=_schema({}, []),
            fonction=lister_modeles_vision,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m3_calculer_aire_polygone",
            description=(
                "Aire et périmètre d'un polygone par le moteur déterministe (formule du lacet en Decimal, projection "
                "locale "
                "documentée), avec un REÇU rejouable. Sommets : textes décimaux, jamais des flottants. Refuse un "
                "polygone "
                "auto-intersecté, hors du Québec ou de plus de 2 000 m. Mesure géométrique à partir de coordonnées "
                "fournies : "
                "pas un arpentage."
            ),
            parametres=_schema(
                {
                    "systeme": {"type": "string", "enum": ["geographique", "plan_metrique"]},
                    "sommets": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}},
                        "description": "[[latitude, longitude]] ou [[x, y]] en mètres",
                    },
                    "incertitude_position_m": {"type": "string"},
                    "facteur_echelle_grille": {"type": "string"},
                },
                ["systeme", "sommets"],
            ),
            fonction=calculer_aire_polygone,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m3_agreger_donnees_geospatiales",
            description=(
                "Interroge les ports cadastre, rôle d'évaluation et imagerie (aucune source branchée "
                "aujourd'hui : "
                "« non_configure ») et rend lot, surface calculée par le moteur, unité d'évaluation et "
                "références "
                "d'imagerie (contexte seulement), chacune avec sa source. Lecture seule."
            ),
            parametres=_schema(
                {"adresse": {"type": "object", "description": "{numero_civique, odonyme, municipalite, code_postal?}"}},
                ["adresse"],
            ),
            fonction=agreger_donnees_geospatiales,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m3_lister_sources_geospatiales",
            description="Sources publiques candidates du Québec (cadastre, rôle d'évaluation, imagerie, adresses) avec "
            "leurs "
            "licences présumées, TOUTES à vérifier, et l'état des ports. Lecture seule.",
            parametres=_schema({}, []),
            fonction=lister_sources_geospatiales,
            autonomie=Autonomie.T0,
        ),
    )
