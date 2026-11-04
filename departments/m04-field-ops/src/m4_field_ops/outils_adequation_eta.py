"""Adaptateur des outils M4.11 (adéquation équipe/intervention, affectation proposée) et M4.14 (fenêtre d'arrivée du
client).

Toute la logique est pure (``adequation_equipe``, ``eta_client``, ``suivi_client``) ; ce module lit le registre et les
profils, choisit le port de routage, publie l'événement vers M1 et déclare les outils. Il vit à part de ``outils.py``
(déjà très long) et y est assemblé par ``outils()``, qui lui passe ses lectures (registre courant, profil des équipes,
position confirmée, fournisseur de matrice) : aucun import circulaire, aucune seconde source de vérité.

Aucun de ces outils n'est ouvert à un appareil (``roles_appareil`` vide) : le score d'équipe ne se montre ni à
l'employé ni au vendeur, et le client n'a pas de rôle serveur (ROLES.md).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from opsys import approbations, contexte, evenements, stockage
from opsys import reglages as reglages_direction
from opsys.garde_fou_texte import (
    ADRESSE,
    AVEU,
    AVIS_LEGAL,
    COORDONNEES,
    EXAGERATION,
    IDENTIFIANT_INTERNE,
    LIEN,
    LONGUEUR,
    NOM_CLIENT,
    PRIX_MONTANT,
    PRIX_OFFRE,
    TEXTE_VIDE,
    controler,
    motif_de_refus,
)
from opsys.garde_fou_texte import (
    profil as profil_garde_fou,
)
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage.schema import APPROBATIONS

from . import (
    adequation_equipe,
    admissibilite,
    calendrier_civil,
    calibration_projection,
    capacite_equipe,
    distances,
    encodage,
    eta_client,
    etats,
    suivi_client,
    verdicts,
)

_DEPARTEMENT = "m04-field-ops"
_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"
_OUTIL_AFFECTATION_N3 = "m4_approuver_affectation_engageante"
_OUTIL_CONSENTEMENT = "m4_enregistrer_consentement_suivi_client"
TYPE_BROUILLON = "affectation_brouillon"
TYPE_APPROUVEE = "affectation_approuvee"
TYPE_EVENEMENT_MESSAGE = "m4.message_client_brouillon_pret"
TYPE_EVENEMENT_RETRAIT = "m4.consentement_suivi_retire"
# Texte destiné au client : une fenêtre de temps, rien d'autre. La date et la promesse de délai sont permises ICI
# (c'est l'objet du message, décidé par M4 qui connaît la cédule) ; tout le reste de ce qui identifie un client ou
# engage l'entreprise est refusé.
PROFIL_TEXTE_CLIENT = profil_garde_fou(
    "m4_eta_client",
    [
        TEXTE_VIDE,
        LONGUEUR,
        LIEN,
        ADRESSE,
        COORDONNEES,
        NOM_CLIENT,
        IDENTIFIANT_INTERNE,
        PRIX_MONTANT,
        PRIX_OFFRE,
        EXAGERATION,
        AVEU,
        AVIS_LEGAL,
    ],
    texte_max=600,
)


def _refus(verdict: dict[str, Any]) -> dict[str, Any]:
    return {"accepte": False, "verdict": verdict}


def _v(code: str, detail: str = "") -> dict[str, Any]:
    return verdicts.construire_verdict(code, detail=detail)


def _configuration(cle: str) -> Any:
    """Le bloc ``configuration.<cle>`` de ``department.yaml``, relu à chaque appel, avec par-dessus les valeurs
    ADOPTÉES par la direction (CFG-1) : une valeur adoptée l'emporte sur celle du fichier, et rien d'adopté laisse
    le fichier tel quel (``reglages.lecture.superposer``). Absent : ``None`` ; illisible : ``None``, le lecteur
    du bloc dit « invalide » au lieu de deviner."""
    try:
        brut = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    configuration = brut.get("configuration") if isinstance(brut, dict) else None
    du_fichier = configuration.get(cle) if isinstance(configuration, dict) else None
    try:
        return reglages_direction.lecture.superposer(brut, ("configuration", cle), du_fichier)
    except (AttributeError, TypeError, ValueError):
        return du_fichier


def _parametres_adequation() -> Any:
    """``configuration.adequation`` de ``department.yaml`` : VIDE à dessein (poids = décision de l'entreprise)."""
    return _configuration("adequation")


def _parametres_eta() -> Any:
    return _configuration("eta_client")


def _lundi(jour: str) -> str | None:
    try:
        d = date.fromisoformat(jour)
    except (TypeError, ValueError):
        return None
    return (d - timedelta(days=d.weekday())).isoformat() if d.isoformat() == jour else None


def _instant(texte: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(texte) if isinstance(texte, str) else None
    except ValueError:
        return None
    return d if d is not None and d.tzinfo is not None else None


def _decision_approuvee(nom_outil: str, arguments: dict[str, Any]) -> tuple[str, str, str] | None:
    """``(personne, demande, instant)`` de la décision approuvée qui fait exécuter CET appel avec CES arguments,
    sinon ``None``."""
    cnx = stockage.connexion_courante()
    if cnx is None:
        return None
    signataire = approbations.approbateur_en_cours(cnx, nom_outil, _DEPARTEMENT)
    demande = contexte.demande_approuvee_en_cours()
    if signataire is None or demande is None:
        return None
    ligne = cnx.execute(
        select(APPROBATIONS.c.arguments, APPROBATIONS.c.decide_le).where(APPROBATIONS.c.id == demande)
    ).one_or_none()
    if ligne is None or not ligne.decide_le or json.loads(ligne.arguments) != arguments:
        return None
    return signataire.personne, str(demande), ligne.decide_le


def _intervention(reg: Any, intervention_id: Any) -> dict[str, Any] | None:
    if not isinstance(intervention_id, str):
        return None
    return next((i for i in etats.lister_interventions(reg) if i["intervention_id"] == intervention_id), None)


def _service_de(intervention: dict[str, Any]) -> str | None:
    valeur = intervention.get("service") or intervention.get("type_travaux")
    return valeur if isinstance(valeur, str) else None


def _historique_par_equipe(reg: Any) -> dict[str, dict[str, int]]:
    """Par équipe (= identifiant de technicien de l'assignation) : chantiers vérifiés, et ceux qui ont eu un écart
    métier.
    Agrégat d'équipe, jamais le dossier d'une personne ; sans contenu libre."""
    avec_ecart = {
        m["intervention_id"]
        for m in reg.lire()
        if m.get("type_entree") == "demande_revue" and m.get("type_demande") == "ecart_metier"
    }
    histo: dict[str, dict[str, int]] = {}
    for i in etats.lister_interventions(reg):
        equipe = i.get("technicien_assigne")
        if equipe is None or i["statut"] != "completed_verified":
            continue
        h = histo.setdefault(equipe, {"terminees": 0, "avec_ecart": 0})
        h["terminees"] += 1
        h["avec_ecart"] += 1 if i["intervention_id"] in avec_ecart else 0
    return histo


_CLES_RAPIDITE = ("chantiers", "indice_median", "borne_basse", "borne_haute")


def _rapidite_par_equipe(service: str, equipes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Indice de rapidité appris par M3 pour chaque équipe du profil, pour CE type de travaux (agrégat par couple
    équipe/type, jamais une note de personne). Lu par l'outil de M3, sous l'identité de M4 ; toute indisponibilité
    (M3 absent, politique non déclarée, aucun instantané) rend un dictionnaire vide : le critère n'a alors pas de
    donnée et l'indice le dit, il n'invente rien. Seules les lignes ÉVALUABLES sont reprises."""
    try:
        from opsys.capacites import Capacites
        from opsys.departements import charger_departements

        departements = charger_departements()
        cibles = {nom: departements[nom] for nom in ("m03-estimation", _DEPARTEMENT)}
        reponse = Capacites(
            cibles, stockage.transaction, appelant=_DEPARTEMENT, limite_sortie=200_000, memoire=False,
        ).appeler("m3_lire_performance_equipes", {"type_service": service})
    except (ImportError, KeyError, ValueError, TypeError):
        return {}
    resultat = reponse.get("resultat") if isinstance(reponse, dict) and reponse.get("ok") else None
    lignes = resultat.get("equipes") if isinstance(resultat, dict) else None
    if not isinstance(lignes, list):
        return {}
    par_ref = {
        ligne["equipe_ref"]: ligne for ligne in lignes
        if isinstance(ligne, dict) and ligne.get("evaluable") is True and ligne.get("type_service") == service
    }
    sortie = {}
    for equipe in equipes:
        ligne = par_ref.get(calibration_projection.equipe_ref(equipe["id"]))
        if ligne is not None:
            sortie[equipe["id"]] = {cle: ligne[cle] for cle in _CLES_RAPIDITE}
    return sortie


def construire(
    *,
    registre_courant: Callable[[], Any],
    lecteur_equipes: Callable[[], Callable[[], tuple[Any, Any]]],
    lire_position: Callable[[Any, str], tuple[Any, Any]],
    fournisseur_matrice: Any,
) -> tuple[Outil, ...]:
    # -------------------------------------------------------------------------------- M4.11
    def proposer_adequation(intervention_id: str, date_cible: str) -> dict[str, Any]:
        parametres, verdict = adequation_equipe.lire_parametres(_parametres_adequation())
        if verdict is not None:
            return _refus(verdict)
        lundi = _lundi(date_cible)
        if lundi is None:
            return _refus(_v("REJ-ADEQUATION-ENTREE-INVALIDE", "date_cible : AAAA-MM-JJ attendu"))
        reg = registre_courant()
        intervention = _intervention(reg, intervention_id)
        service = None if intervention is None else _service_de(intervention)
        if intervention is None or service is None:
            return _refus(_v("REJ-AFFECTATION-INTROUVABLE", "intervention inconnue ou sans service"))
        profil, verdict_profil = lecteur_equipes()()
        if profil is None:
            return _refus(verdict_profil)
        exigences, verdict = admissibilite.exigences_du_service(profil, service)
        if verdict is not None:
            return _refus(verdict)
        try:
            charge = capacite_equipe.calculer(reg, profil, None, None, lundi, None, capacite_equipe.PORTEE_SEMAINE_TYPE)
        except Exception:  # noqa: BLE001 - une preuve de registre incohérente rend la capacité inconnue, jamais zéro
            charge = {"calculable": False, "equipes": []}
        capacites = (
            {
                e["equipe_id"]: {
                    "minutes_disponibles": e["minutes_disponibles"],
                    "minutes_planifiees": e["minutes_planifiees"],
                }
                for e in charge["equipes"]
            }
            if charge.get("calculable")
            else {}
        )
        position, _ = lire_position(reg, intervention["lead_id"])  # la localisation se confirme par lead (chantier)
        histo = _historique_par_equipe(reg)
        rapidites = (
            _rapidite_par_equipe(service, profil["liste"]) if parametres["poids"].get(adequation_equipe.RAPIDITE, 0) > 0
            else {}
        )
        equipes = []
        for e in profil["liste"]:
            fiche: dict[str, Any] = {
                "equipe_id": e["id"],
                "competences": list(e["competences"]),
                "membres_declares": len(e.get("membres", ())),
            }
            if e["id"] in capacites:
                fiche["capacite"] = capacites[e["id"]]
            depot = e.get("depot")
            if position is not None and depot is not None:
                fiche["distance_m"] = distances.distance_droite_m(
                    depot["latitude_microdegres"],
                    depot["longitude_microdegres"],
                    position["latitude_microdegres"],
                    position["longitude_microdegres"],
                )
            if e["id"] in histo:
                fiche["historique"] = histo[e["id"]]
            if e["id"] in rapidites:
                fiche["rapidite"] = rapidites[e["id"]]
            equipes.append(fiche)
        ordre, verdict = adequation_equipe.ordonner(
            {
                "intervention": {
                    "intervention_id": intervention_id,
                    "service": service,
                    "date": date_cible,
                    "duree_min": exigences["duree_min"],
                    "competences_requises": exigences["competences"],
                },
                "equipes": equipes,
            },
            parametres,
        )
        if verdict is not None:
            return _refus(verdict)
        ordre["semaine_capacite"] = {
            "debut": lundi,
            "calculable": bool(charge.get("calculable")),
            "manque": list(charge.get("manque", ())),
            "portee": "semaine_type",
        }
        return {"accepte": True, "resultat": ordre}

    def calibrer(
        cas: list[dict[str, Any]], pas: int, distance_reference_km: int, historique_minimum: int
    ) -> dict[str, Any]:
        resultat, verdict = adequation_equipe.calibrer_poids(
            cas, {"distance_reference_km": distance_reference_km, "historique_minimum": historique_minimum}, pas
        )
        return _refus(verdict) if verdict is not None else {"accepte": True, "resultat": resultat}

    def enregistrer_brouillon(
        intervention_id: str,
        equipe_id: str,
        source: str,
        ordre_empreinte: str | None,
        engagement_client: bool,
        horodatage: str,
    ) -> dict[str, Any]:
        if engagement_client is not False:
            return _refus(
                _v(
                    "REJ-AFFECTATION-ENGAGEMENT-CLIENT",
                    "une affectation qui engage le client passe par m4_approuver_affectation_engageante (N3, "
                    "une "
                    "personne approuve) ; ce brouillon interne n'engage personne",
                )
            )
        if source not in ("adequation", "manuelle") or (
            ordre_empreinte is not None and not (isinstance(ordre_empreinte, str) and len(ordre_empreinte) == 64)
        ):
            return _refus(
                _v("REJ-AFFECTATION-INVALIDE", "source : adequation ou manuelle ; ordre_empreinte : SHA-256 ou null")
            )
        reception = contexte.horodatage_reception()
        quand = reception.recu_le.isoformat() if reception is not None else horodatage
        if _instant(quand) is None:
            return _refus(_v("REJ-AFFECTATION-INVALIDE", "horodatage : instant ISO 8601 avec fuseau attendu"))
        return _ecrire_affectation(
            intervention_id,
            equipe_id,
            TYPE_BROUILLON,
            quand,
            {"source": source, "ordre_empreinte": ordre_empreinte, "engagement_client": False},
        )

    def _ecrire_affectation(
        intervention_id: str, equipe_id: str, type_entree: str, horodatage: str, extra: dict[str, Any]
    ) -> dict[str, Any]:
        reg = registre_courant()
        intervention = _intervention(reg, intervention_id)
        service = None if intervention is None else _service_de(intervention)
        if intervention is None or service is None:
            return _refus(_v("REJ-AFFECTATION-INTROUVABLE", "intervention inconnue ou sans service"))
        profil, verdict_profil = lecteur_equipes()()
        if profil is None:
            return _refus(verdict_profil)
        admissibles, verdict = admissibilite.equipes_admissibles(profil, service)
        if verdict is not None:
            return _refus(verdict)
        if not isinstance(equipe_id, str) or equipe_id not in admissibles["admissibles"]:
            return _refus(
                _v(
                    "REJ-AFFECTATION-INVALIDE",
                    "cette équipe n'est pas admissible pour ce service (compétences, quart) ou n'est pas déclarée",
                )
            )
        maillons = [m for m in reg.lire() if m.get("intervention_id") == intervention_id]
        if any(m.get("type_entree") == TYPE_APPROUVEE for m in maillons):
            return _refus(
                _v(
                    "REJ-AFFECTATION-DEJA-DECIDEE",
                    "une affectation engageante a déjà été approuvée pour cette intervention",
                )
            )
        if type_entree == TYPE_APPROUVEE and not any(
            m.get("type_entree") == TYPE_BROUILLON and m.get("equipe_id") == equipe_id for m in maillons
        ):
            return _refus(
                _v(
                    "REJ-AFFECTATION-INVALIDE",
                    "aucun brouillon d'affectation pour cette équipe : en enregistrer un d'abord",
                )
            )
        entree = {
            "type_entree": type_entree,
            "horodatage": horodatage,
            "intervention_id": intervention_id,
            "equipe_id": equipe_id,
            **extra,
        }
        ligne_id = reg.ajouter(entree)
        return {
            "accepte": True,
            "resultat": {
                "ligne_id": ligne_id,
                "intervention_id": intervention_id,
                "equipe_id": equipe_id,
                "statut": "brouillon" if type_entree == TYPE_BROUILLON else "approuvee_par_une_personne",
                "affecte": False,
                "note": "aucune assignation n'est exécutée ici : l'affectation effective reste m4_appliquer_cedule",
            },
        }

    def approuver_affectation(intervention_id: str, equipe_id: str) -> dict[str, Any]:
        approuvee = _decision_approuvee(
            _OUTIL_AFFECTATION_N3, {"intervention_id": intervention_id, "equipe_id": equipe_id}
        )
        if approuvee is None:
            return _refus(
                _v(
                    "REJ-AFFECTATION-SANS-APPROBATION",
                    "une affectation qui engage le client ne s'exécute que sur une décision approuvée dans la "
                    "file "
                    "d'approbation OPSYS ; ne la présente pas comme décidée",
                )
            )
        personne, demande, instant = approuvee
        return _ecrire_affectation(
            intervention_id,
            equipe_id,
            TYPE_APPROUVEE,
            instant,
            {"approuve_par": personne, "approbation_ref": demande, "engagement_client": True},
        )

    # -------------------------------------------------------------------------------- M4.14
    def _eta(
        intervention_id: str,
        horodatage_reference: str,
        retards: list[int],
        depart: dict[str, Any] | None,
        parametres: dict[str, int],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        reg = registre_courant()
        intervention = _intervention(reg, intervention_id)
        if intervention is None:
            return None, _v("REJ-ETA-CRENEAU-INCONNU", "intervention inconnue")
        intervention_lead = intervention["lead_id"]
        try:
            lignes, _ = calendrier_civil._projection(calendrier_civil._index(reg))
        except Exception:  # noqa: BLE001 - preuve de registre incohérente : aucune fenêtre
            return None, _v("REJ-ETA-CRENEAU-INCONNU", "cédule illisible : aucune fenêtre n'est estimée")
        ligne = next(
            (x for x in lignes if x["intervention_id"] == intervention_id and x["validite"] == "date_confirmee"), None
        )
        if ligne is None:
            return None, _v(
                "REJ-ETA-CRENEAU-INCONNU", "aucun créneau daté et confirmé pour cette intervention dans la cédule"
            )
        depart_eta = None
        if depart is not None:
            if not isinstance(depart, dict) or set(depart) != {
                "instant",
                "origine",
                "latitude_microdegres",
                "longitude_microdegres",
            }:
                return None, _v(
                    "REJ-ETA-ENTREE-INVALIDE",
                    "depart : instant, origine, latitude_microdegres et longitude_microdegres",
                )
            position, verdict = lire_position(reg, intervention_lead)
            if position is None:
                return None, _v(
                    "REJ-ETA-ENTREE-INVALIDE", "adresse du chantier non confirmée : le trajet ne peut pas être estimé"
                )
            equipes = lecteur_equipes()()[0]
            reglages = (equipes or {}).get("cedule") if isinstance(equipes, dict) else None
            points = [
                {
                    "id": "depart",
                    "latitude_microdeg": depart["latitude_microdegres"],
                    "longitude_microdeg": depart["longitude_microdegres"],
                },
                {
                    "id": "site",
                    "latitude_microdeg": position["latitude_microdegres"],
                    "longitude_microdeg": position["longitude_microdegres"],
                },
            ]
            matrice, verdict = distances.obtenir_matrice(
                points,
                {
                    k: (reglages or {}).get(k)
                    for k in ("facteur_detour_milliemes", "vitesse_moyenne_kmh", "marge_par_trajet_secondes")
                },
                fournisseur_matrice,
            )
            if verdict is not None:
                return None, _v("REJ-ETA-ENTREE-INVALIDE", "trajet non estimable : " + str(verdict.get("code")))
            ids = matrice["ids"]
            depart_eta = {
                "instant": depart["instant"],
                "origine": depart["origine"],
                "trajet_secondes": matrice["secondes"][ids.index("depart")][ids.index("site")],
                "approximatif": bool(matrice["mode_bride"]),
            }
        return eta_client.estimer(
            {
                "intervention_id": intervention_id,
                "creneau": {"debut": ligne["debut"], "fin": ligne["fin"]},
                "depart": depart_eta,
                "retards_declares_minutes": retards,
                "horodatage_reference": horodatage_reference,
            },
            parametres,
        )

    def estimer_eta(
        intervention_id: str,
        horodatage_reference: str,
        retards_declares_minutes: list[int],
        depart: dict[str, Any] | None,
    ) -> dict[str, Any]:
        parametres, verdict = eta_client.lire_parametres(_parametres_eta())
        if verdict is not None:
            return _refus(verdict)
        eta, verdict = _eta(intervention_id, horodatage_reference, retards_declares_minutes, depart, parametres)
        return _refus(verdict) if verdict is not None else {"accepte": True, "resultat": eta}

    def enregistrer_consentement(
        intervention_id: str, canal: str, enonce_version: str, preuve: dict[str, Any], recueilli_le: str
    ) -> dict[str, Any]:
        arguments = {
            "intervention_id": intervention_id,
            "canal": canal,
            "enonce_version": enonce_version,
            "preuve": preuve,
            "recueilli_le": recueilli_le,
        }
        approuvee = _decision_approuvee(_OUTIL_CONSENTEMENT, arguments)
        if approuvee is None:
            return _refus(
                _v(
                    "REJ-SUIVI-SANS-APPROBATION",
                    "le consentement du client est inscrit par une PERSONNE (décision approuvée dans la file) "
                    "; un "
                    "agent seul ne peut pas l'affirmer à la place du client",
                )
            )
        parametres, verdict = eta_client.lire_parametres(_parametres_eta())
        if verdict is not None:
            return _refus(verdict)
        reg = registre_courant()
        intervention = _intervention(reg, intervention_id)
        if intervention is None:
            return _refus(_v("REJ-AFFECTATION-INTROUVABLE", "intervention inconnue"))
        personne, demande, instant = approuvee
        maillon, verdict = suivi_client.construire_consentement(
            intervention_id=intervention_id,
            lead_id=intervention["lead_id"],
            canal=canal,
            enonce_version=enonce_version,
            preuve=preuve,
            recueilli_le=recueilli_le,
            recueilli_par=personne,
            approbation_ref=demande,
            enregistre_le=instant,
            validite_jours=parametres["validite_consentement_jours"],
            maillons=reg.lire(),
        )
        if verdict is not None:
            return _refus(verdict)
        ligne_id = reg.ajouter(maillon)
        return {
            "accepte": True,
            "resultat": {
                "ligne_id": ligne_id,
                "etat": "actif",
                "canal": canal,
                "valide_jusqu_au": maillon["valide_jusqu_au"],
                "finalite": suivi_client.FINALITE,
            },
        }

    def retirer_consentement(intervention_id: str, canal: str, source: str, horodatage: str) -> dict[str, Any]:
        reg = registre_courant()
        if _intervention(reg, intervention_id) is None:
            return _refus(_v("REJ-AFFECTATION-INTROUVABLE", "intervention inconnue"))
        reception = contexte.horodatage_reception()
        quand = reception.recu_le.isoformat() if reception is not None else horodatage
        maillon, verdict = suivi_client.construire_retrait(
            intervention_id=intervention_id, canal=canal, source=source, retire_le=quand
        )
        if verdict is not None:
            return _refus(verdict)
        # Le consentement que ce retrait termine se lit AVANT d'écrire le retrait (après, l'état serait « retiré »).
        vise = suivi_client.consentement_vise_par_retrait(
            reg.lire(), intervention_id, canal, _instant(maillon["horodatage"])
        )
        ligne_id = reg.ajouter(maillon)  # un retrait se pose toujours, même sans consentement connu : il bloque
        publie = False
        if stockage.connexion_courante() is not None:
            # M1 détient le brouillon déjà publié : il ne peut pas savoir ce retrait sans cet événement (Loi 25 : le
            # retrait vaut tout de suite pour ce que M1 n'a pas encore envoyé). Même transaction que le maillon.
            evenements.publier(
                TYPE_EVENEMENT_RETRAIT,
                _DEPARTEMENT,
                {
                    "intervention_id": intervention_id,
                    "lead_id": _intervention(reg, intervention_id)["lead_id"],
                    "canal": canal,
                    "retire_le": maillon["horodatage"],
                    "consentement_ligne_id": vise,
                },
                evenement_id="m4-suivi-retire-"
                + encodage.empreinte(intervention_id, canal, maillon["horodatage"], vise or "")[:32],
            )
            publie = True
        return {
            "accepte": True,
            "resultat": {"ligne_id": ligne_id, "etat": "retire", "canal": canal, "evenement_publie": publie},
        }

    def lire_consentement(intervention_id: str, canal: str, horodatage_reference: str) -> dict[str, Any]:
        reference = _instant(horodatage_reference)
        if reference is None or canal not in suivi_client.CANAUX:
            return _refus(
                _v("REJ-SUIVI-CONSENTEMENT-INVALIDE", "canal et horodatage_reference (avec fuseau) valides requis")
            )
        return {
            "accepte": True,
            "resultat": suivi_client.etat_du_consentement(registre_courant().lire(), intervention_id, canal, reference),
        }

    def preparer_message(
        intervention_id: str,
        canal: str,
        horodatage_reference: str,
        retards_declares_minutes: list[int],
        depart: dict[str, Any] | None,
    ) -> dict[str, Any]:
        parametres, verdict = eta_client.lire_parametres(_parametres_eta())
        if verdict is not None:
            return _refus(verdict)
        reference = _instant(horodatage_reference)
        if reference is None or canal not in suivi_client.CANAUX:
            return _refus(
                _v("REJ-SUIVI-CONSENTEMENT-INVALIDE", "canal et horodatage_reference (avec fuseau) valides requis")
            )
        reg = registre_courant()
        intervention = _intervention(reg, intervention_id)
        if intervention is None:
            return _refus(_v("REJ-AFFECTATION-INTROUVABLE", "intervention inconnue"))
        maillons = reg.lire()
        etat = suivi_client.etat_du_consentement(maillons, intervention_id, canal, reference)
        if etat["etat"] != "actif":
            code = {
                "absent": "REJ-ETA-CONSENTEMENT-ABSENT",
                "retire": "REJ-ETA-CONSENTEMENT-RETIRE",
                "expire": "REJ-ETA-CONSENTEMENT-EXPIRE",
            }[etat["etat"]]
            return _refus(
                _v(
                    code,
                    f"consentement de suivi {etat['etat']} pour ce chantier et ce canal : aucun message n'est préparé",
                )
            )
        eta, verdict = _eta(intervention_id, horodatage_reference, retards_declares_minutes, depart, parametres)
        if verdict is not None:
            return _refus(verdict)
        texte = eta_client.composer_message(eta["fenetre"])
        violations = controler(texte, PROFIL_TEXTE_CLIENT)
        if violations:
            return _refus(
                _v(
                    "REJ-ETA-ENTREE-INVALIDE",
                    "le texte du message est refusé par le garde-fou : " + motif_de_refus(violations),
                )
            )
        empreinte = hashlib.sha256(texte.encode("utf-8")).hexdigest()
        deja = [
            m
            for m in maillons
            if m.get("type_entree") == suivi_client.TYPE_ETA
            and m.get("intervention_id") == intervention_id
            and m.get("canal") == canal
        ]
        if any(m["message_empreinte"] == empreinte for m in deja):
            return {
                "accepte": True,
                "resultat": {
                    "fenetre": eta["fenetre"],
                    "message": texte,
                    "deja_prepare": True,
                    "statut": "brouillon",
                    "envoi": "n3_requis_via_m1",
                },
            }
        if len(deja) >= parametres["messages_max_par_intervention"]:
            return _refus(
                _v(
                    "REJ-ETA-QUOTA-MESSAGES",
                    f"plafond de {parametres['messages_max_par_intervention']} messages par chantier et canal "
                    "atteint : "
                    "pas de nouvelle mise à jour automatique (une personne décide)",
                )
            )
        entree = suivi_client.construire_enregistrement_eta(
            intervention_id=intervention_id,
            canal=canal,
            fenetre=eta["fenetre"],
            message_empreinte=empreinte,
            consentement_ligne_id=etat.get("ligne_id"),
            prepare_le=reference.isoformat(),
            conservation_heures=parametres["conservation_heures"],
        )
        ligne_id = reg.ajouter(entree)
        publie = False
        if stockage.connexion_courante() is not None:
            evenements.publier(
                TYPE_EVENEMENT_MESSAGE,
                _DEPARTEMENT,
                {
                    "intervention_id": intervention_id,
                    "lead_id": intervention["lead_id"],
                    "canal": canal,
                    "fenetre_debut": eta["fenetre"]["debut"],
                    "fenetre_fin": eta["fenetre"]["fin"],
                    "texte": texte,
                    "statut": "brouillon",
                    "envoi": "n3_requis_via_m1",
                    "consentement_ligne_id": etat.get("ligne_id"),
                    "conserve_jusqu_au": entree["conserve_jusqu_au"],
                },
                evenement_id="m4-message-client-" + encodage.empreinte(intervention_id, canal, empreinte)[:32],
            )
            publie = True
        return {
            "accepte": True,
            "resultat": {
                "fenetre": eta["fenetre"],
                "message": texte,
                "deja_prepare": False,
                "statut": "brouillon",
                "envoi": "n3_requis_via_m1",
                "ligne_id": ligne_id,
                "evenement_publie": publie,
                "conserve_jusqu_au": entree["conserve_jusqu_au"],
                "approximatif": eta["approximatif"],
            },
        }

    # -------------------------------------------------------------------------------- déclarations
    def schema(proprietes: dict[str, Any], requis: list[str]) -> dict[str, Any]:
        return {"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False}

    depart_schema = {
        "type": ["object", "null"],
        "description": (
            "{instant, origine (fin_intervention_precedente|depot), latitude_microdegres, "
            "longitude_microdegres} : d'où "
            "l'équipe "
            "part. Sert au calcul seulement : jamais recopié dans la sortie, le registre ni l'événement."
        ),
    }
    return (
        Outil(
            nom="m4_proposer_adequation_equipes",
            description=(
                "Ordonne les équipes admissibles pour une intervention et une date (indice d'adéquation ÉQUIPE, jamais "
                "d'une "
                "personne) : compétences et capacité de la semaine type en filtre, puis marge, charge, distance du "
                "dépôt et "
                "historique de qualité agrégé selon les poids que l'entreprise a déclarés. Chaque indice est expliqué "
                "critère par "
                "critère. Refuse tout champ qui nomme un attribut personnel protégé ou une personne. Une PROPOSITION : "
                "l'humain "
                "affecte. Lecture seule."
            ),
            parametres=schema(
                {"intervention_id": {"type": "string"}, "date_cible": {"type": "string", "description": "AAAA-MM-JJ"}},
                ["intervention_id", "date_cible"],
            ),
            fonction=proposer_adequation,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m4_calibrer_poids_adequation",
            description=(
                "Cherche, sur des cas FICTIFS (fictif: true exigé), les poids qui reproduisent le mieux des "
                "choix humains "
                "d'affectation. Ne fixe aucun poids : les adopter est une décision de l'entreprise. Lecture "
                "seule."
            ),
            parametres=schema(
                {
                    "cas": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "[{fictif, entrees, choix_humain}]",
                    },
                    "pas": {"type": "integer"},
                    "distance_reference_km": {"type": "integer"},
                    "historique_minimum": {"type": "integer"},
                },
                ["cas", "pas", "distance_reference_km", "historique_minimum"],
            ),
            fonction=calibrer,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m4_enregistrer_brouillon_affectation",
            description=(
                "Inscrit un BROUILLON d'affectation interne (intervention, équipe admissible) : n'assigne "
                "personne et "
                "n'engage pas le client. Une affectation qui engage le client est refusée ici : elle passe par "
                "m4_approuver_affectation_engageante."
            ),
            parametres=schema(
                {
                    "intervention_id": {"type": "string"},
                    "equipe_id": {"type": "string"},
                    "source": {"type": "string", "enum": ["adequation", "manuelle"]},
                    "ordre_empreinte": {"type": ["string", "null"], "description": "empreinte du ordre qui l'inspire"},
                    "engagement_client": {"type": "boolean"},
                    "horodatage": {"type": "string"},
                },
                ["intervention_id", "equipe_id", "source", "ordre_empreinte", "engagement_client", "horodatage"],
            ),
            fonction=enregistrer_brouillon,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom=_OUTIL_AFFECTATION_N3,
            description=(
                "Approuve une affectation qui ENGAGE le client (date ou équipe annoncée). S'exécute seulement "
                "sur une "
                "décision approuvée dans la file (N3) ; la personne vient de l'approbation. Exige un brouillon "
                "pour la "
                "même équipe ; une seule approbation par intervention. N'assigne personne par elle-même."
            ),
            parametres=schema(
                {"intervention_id": {"type": "string"}, "equipe_id": {"type": "string"}},
                ["intervention_id", "equipe_id"],
            ),
            fonction=approuver_affectation,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m4_estimer_eta_client",
            description=(
                "Estime la FENÊTRE d'arrivée de l'équipe chez le client à partir du créneau de la cédule, du trajet "
                "(port de "
                "routage ; mode bridé sans routeur installé) et des retards déclarés : un intervalle, jamais une heure "
                "unique ni une "
                "promesse. Ne rend jamais la position de l'équipe. Lecture seule."
            ),
            parametres=schema(
                {
                    "intervention_id": {"type": "string"},
                    "horodatage_reference": {"type": "string"},
                    "retards_declares_minutes": {"type": "array", "items": {"type": "integer"}},
                    "depart": depart_schema,
                },
                ["intervention_id", "horodatage_reference", "retards_declares_minutes", "depart"],
            ),
            fonction=estimer_eta,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom=_OUTIL_CONSENTEMENT,
            description=(
                "Inscrit le consentement du CLIENT au suivi de la fenêtre d'arrivée (finalité unique, un "
                "chantier, un "
                "canal sms ou courriel, durée bornée). S'exécute seulement sur une décision approuvée dans la "
                "file (N3) : "
                "une personne l'a recueilli, un agent ne peut pas l'affirmer. Aucun contact ni position n'est "
                "gardé."
            ),
            parametres=schema(
                {
                    "intervention_id": {"type": "string"},
                    "canal": {"type": "string", "enum": list(suivi_client.CANAUX)},
                    "enonce_version": {"type": "string"},
                    "preuve": {"type": "object", "description": "{fictif, reference}"},
                    "recueilli_le": {"type": "string"},
                },
                ["intervention_id", "canal", "enonce_version", "preuve", "recueilli_le"],
            ),
            fonction=enregistrer_consentement,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m4_retirer_consentement_suivi_client",
            description=(
                "Retire le consentement de suivi d'un chantier pour un canal (STOP, demande du client, équipe, "
                "administration). "
                "Effet immédiat ; ne se lève que par un nouveau consentement recueilli après le retrait."
            ),
            parametres=schema(
                {
                    "intervention_id": {"type": "string"},
                    "canal": {"type": "string", "enum": list(suivi_client.CANAUX)},
                    "source": {"type": "string", "enum": ["client_stop", "client_demande", "equipe", "administration"]},
                    "horodatage": {"type": "string"},
                },
                ["intervention_id", "canal", "source", "horodatage"],
            ),
            fonction=retirer_consentement,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m4_lire_consentement_suivi_client",
            description="État du consentement de suivi (absent, actif, retiré, expiré) d'un chantier pour un canal. "
            "Lecture seule.",
            parametres=schema(
                {
                    "intervention_id": {"type": "string"},
                    "canal": {"type": "string", "enum": list(suivi_client.CANAUX)},
                    "horodatage_reference": {"type": "string"},
                },
                ["intervention_id", "canal", "horodatage_reference"],
            ),
            fonction=lire_consentement,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m4_preparer_message_eta_client",
            description=(
                "Prépare le BROUILLON du message d'arrivée estimée au client (texte fixe en français : une fenêtre, un "
                "avertissement, "
                "le moyen de se retirer) si le consentement de suivi est actif, et le publie à M1 "
                "(m4.message_client_brouillon_pret). "
                "N'ENVOIE RIEN : l'envoi est une décision N3 de M1. Un plafond de messages par chantier évite le "
                "harcèlement."
            ),
            parametres=schema(
                {
                    "intervention_id": {"type": "string"},
                    "canal": {"type": "string", "enum": list(suivi_client.CANAUX)},
                    "horodatage_reference": {"type": "string"},
                    "retards_declares_minutes": {"type": "array", "items": {"type": "integer"}},
                    "depart": depart_schema,
                },
                ["intervention_id", "canal", "horodatage_reference", "retards_declares_minutes", "depart"],
            ),
            fonction=preparer_message,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
    )
