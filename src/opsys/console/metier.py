"""Actions métier internes de console, bornées et signées par une personne active.

Les décisions humaines utilisent la voie d'approbation canonique. Les brouillons et lectures
ne passent pas par un modèle; ils conservent les transactions et les contrats d'outils existants.
"""

from __future__ import annotations

import hashlib
import importlib
from collections.abc import Mapping
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection

from .. import approbations, contexte, idempotence, identite, stockage
from ..capacites import Capacites
from ..departements import Departement
from ..etat import journaliser
from ..outils import Autonomie, Niveau, Outil, executer_atomique, valider_arguments
from .securite import Session

# Surface fermée : aucune écriture externe, dépense ou soumission officielle.
LECTURES = {
    "m1_lire_transfert": "m01-front-office",
    "m1_produire_digest": "m01-front-office",
    "m7_lister_inbox_reputation": "m07-marketing",
    "m7_lire_profil_marque_courant": "m07-marketing",
    "m7_lire_campagne_locale": "m07-marketing",
    "m5_etat_tresorerie": "m05-financecore",
    "m5_lire_calendrier_obligations": "m05-financecore",
    "m5_preparer_dossier_decision_cfo": "m05-financecore",
    "m5_preparer_brut_regulier": "m05-financecore",
    "m5_preparer_dossier_webras": "m05-financecore",
    "m5_verifier_admission_paie_preparatoire": "m05-financecore",
    "m7_lister_contenus_chantier": "m07-marketing",
    "m7_lister_calendrier": "m07-marketing",
    "m7_lire_performance_campagnes": "m07-marketing",
    "m7_lire_dossier_medias": "m07-marketing",
    "m9_lister_suivis_decision": "m09-strategic-intelligence",
    "m9_lire_suivi_decision": "m09-strategic-intelligence",
    "m9_bilan_suivis_decision": "m09-strategic-intelligence",
    "m9_rapport_periode": "m09-strategic-intelligence",
    "m9_observations_chantier_periode": "m09-strategic-intelligence",
    "m9_rapport_activite_periode": "m09-strategic-intelligence",
    # CRM secrétariat (répertoire et dossier client) : lectures pures de la vérité commerciale M2.
    "m4_lire_cedule_semaine": "m04-field-ops",
    "m4_lire_calendrier_plan": "m04-field-ops",
    "m2_lister_leads": "m02-revenue-crm",
    "m2_trouver_client_de_lead": "m02-revenue-crm",
    "m2_obtenir_client_360": "m02-revenue-crm",
    "m2_lister_historique_contact_client": "m02-revenue-crm",
    "m2_reconcilier_memoire_contact_client": "m02-revenue-crm",
    "m3_lister_devis_lead_admin": "m03-estimation",
    "m3_lire_devis": "m03-estimation",
}
# Les lecteurs M9 revérifient l'admin SQL de la persona : jamais la persona propriétaire, même cumulée.
_LECTURES_ADMIN_M9 = frozenset({
    "m9_lister_suivis_decision", "m9_lire_suivi_decision", "m9_bilan_suivis_decision", "m9_rapport_periode",
    "m9_observations_chantier_periode", "m9_rapport_activite_periode",
})
# Les lecteurs M2 n'ont de portée que pour `seller` et `admin` (`m2_revenue_crm.acces.ROLES_LEADS`) : la console
# les appelle avec le rôle `admin` confirmé en base, jamais sans identité d'appareil ni sous `nathan_owner` seul.
_LECTURES_ADMIN_M2 = frozenset({
    "m2_lister_leads", "m2_trouver_client_de_lead", "m2_obtenir_client_360", "m2_lister_historique_contact_client",
    "m2_reconcilier_memoire_contact_client",
})
_LECTURES_ADMIN_M3 = frozenset({"m3_lister_devis_lead_admin", "m3_lire_devis"})
_LECTURES_ADMIN_M4 = frozenset({"m4_lire_cedule_semaine", "m4_lire_calendrier_plan"})
_LECTURES_ADMIN = _LECTURES_ADMIN_M9 | _LECTURES_ADMIN_M2 | _LECTURES_ADMIN_M3 | _LECTURES_ADMIN_M4
_COMMANDES_ADMIN_M2 = frozenset({"m2_enregistrer_interaction", "m2_corriger_contact_client"})
_COMMANDES_ADMIN_M4 = frozenset({"m4_confirmer_dates_cedule"})
_OUTILS_ADMIN = _LECTURES_ADMIN | _COMMANDES_ADMIN_M2 | _COMMANDES_ADMIN_M4
COMMANDES = {
    "m4_confirmer_dates_cedule": "m04-field-ops",
    "m2_corriger_contact_client": "m02-revenue-crm",
    "m2_enregistrer_interaction": "m02-revenue-crm",
    "m1_importer_appel_manuellement": "m01-front-office",
    "m1_clore_transfert": "m01-front-office",
    "m1_consigner_suivi_rappel": "m01-front-office",
    "m7_importer_avis_manuel": "m07-marketing",
    "m7_decider_reponse_avis": "m07-marketing",
    "m7_exporter_reponse_avis_manuel": "m07-marketing",
    "m7_configurer_profil_marque": "m07-marketing",
    "m7_enregistrer_observation_growth": "m07-marketing",
    "m7_generer_plan_growth_30j": "m07-marketing",
    "m7_proposer_campagne_locale": "m07-marketing",
    "m7_approuver_budget_campagne": "m07-marketing",
    "m7_enregistrer_consentement_reference": "m07-marketing",
    "m5_preparer_decision_capital": "m05-financecore",
    "m7_proposer_contenus_chantier": "m07-marketing",
    "m7_decider_contenu": "m07-marketing",
    "m7_proposer_creneau_calendrier": "m07-marketing",
    "m7_decider_creneau_calendrier": "m07-marketing",
    "m7_exporter_creneau_manuel": "m07-marketing",
}
DECISIONS_HUMAINES = {
    "m1_clore_transfert",
    "m7_decider_reponse_avis",
    "m7_exporter_reponse_avis_manuel",
    "m7_configurer_profil_marque",
    "m7_approuver_budget_campagne",
    "m7_decider_contenu",
    "m7_decider_creneau_calendrier",
    "m7_exporter_creneau_manuel",
}
_COMMANDES_MEDIAS = {
    "m7_preparer_media_humain", "m7_decider_dossier_medias", "m7_remettre_dossier_medias_manuel",
}
_NOM_MODULE_SERVICE_M7 = "m7_marketing.usine.service"
_SCHEMA_PREPARER_MEDIA = {
    "type": "object",
    "properties": {
        "contenu_id": {"type": "string", "minLength": 1, "maxLength": 200},
        "source_ref": {"type": "string", "minLength": 1, "maxLength": 90},
        "revision_attendue": {"type": "integer", "minimum": 0},
        "empreinte_attendue": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "snapshot_attendu": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "attestation_humaine": {"type": "string", "minLength": 20, "maxLength": 500},
        "fichier_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
    "required": ["contenu_id", "source_ref", "revision_attendue", "empreinte_attendue", "snapshot_attendu",
                 "attestation_humaine", "fichier_sha256"],
    "additionalProperties": False,
}
_SCHEMA_REVUE_MEDIA = {
    "type": "object",
    "properties": {
        "contenu_id": {"type": "string", "minLength": 1, "maxLength": 200},
        "decision": {"type": "string", "enum": ["approuver", "rejeter"]},
        "revision_attendue": {"type": "integer", "minimum": 1},
        "empreinte_attendue": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "snapshot_attendu": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "attestation_humaine": {"type": "string", "minLength": 20, "maxLength": 500},
    },
    "required": ["contenu_id", "decision", "revision_attendue", "empreinte_attendue", "snapshot_attendu",
                 "attestation_humaine"],
    "additionalProperties": False,
}
_SCHEMA_REMISE_MEDIA = {
    "type": "object",
    "properties": {"creneau_id": {"type": "string", "minLength": 1, "maxLength": 200}},
    "required": ["creneau_id"],
    "additionalProperties": False,
}
_SCHEMA_LIRE_DOSSIER_MEDIA = {
    "type": "object",
    "properties": {"contenu_id": {"type": "string", "minLength": 1, "maxLength": 200}},
    "required": ["contenu_id"],
    "additionalProperties": False,
}


_SCHEMA_REVISER_TEXTE = {
    "type": "object",
    "properties": {
        "contenu_id": {"type": "string", "minLength": 1, "maxLength": 200},
        "revision_attendue": {"type": "integer", "minimum": 1},
        "empreinte_texte_attendue": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "snapshot_attendu": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "texte": {"type": "string", "minLength": 1, "maxLength": 2000},
    },
    "required": ["contenu_id", "revision_attendue", "empreinte_texte_attendue", "snapshot_attendu", "texte"],
    "additionalProperties": False,
}


def _executer_edition_texte(cnx, deps, session, personne, nom, arguments, mutation_id):
    departement = "m07-marketing"
    if "nathan_owner" not in personne.roles:
        raise PermissionError("édition réservée au propriétaire humain")
    module = deps[departement].module_outils if departement in deps else None
    if not isinstance(module, str) or module.rsplit(".", 1)[0] != "m7_marketing":
        raise KeyError("service édition M7 indisponible")
    service = importlib.import_module(_NOM_MODULE_SERVICE_M7)
    with (
        contexte.appele_par_appareil(
            contexte.IdentiteAppelante(personne.identifiant, "nathan_owner", source="console")
        ),
        contexte.appeler_en_tant_que(departement, origine="console"),
    ):
        if nom == "m7_lire_edition_texte_humain":
            if mutation_id is not None or valider_arguments(_SCHEMA_LIRE_DOSSIER_MEDIA, arguments):
                raise ValueError("lecture édition invalide")
            return service.lire_edition_texte_humain(**arguments)
        if cnx.engine.dialect.name != "sqlite":
            return {
                "accepte": False,
                "verdict": {
                    "code": "REJ-TEXTE-ECRITURE-NON-QUALIFIEE",
                    "detail": "édition qualifiée sur SQLite seulement",
                },
            }
        if valider_arguments(_SCHEMA_REVISER_TEXTE, arguments):
            raise ValueError("arguments édition invalides")
        if not isinstance(mutation_id, str) or not 1 <= len(mutation_id) <= 200 or not mutation_id.strip():
            raise ValueError("mutation_id requis, 200 caractères au plus")
        # Contrôle vivant avant tout reçu historique. Ne réapplique pas le CAS de sa propre ancienne écriture.
        refus = service.verifier_rejeu_edition_texte(arguments["contenu_id"])
        if refus is not None:
            return refus
        maintenant = datetime.now(UTC)
        meta = idempotence.Meta(mutation_id, f"console:{personne.identifiant}", maintenant.isoformat())
        try:
            reclamation = idempotence.reclamer(cnx, meta, nom, arguments, maintenant)
        except idempotence.MutationConflit as exc:
            raise ValueError("conflit de commande édition") from exc
        if reclamation.rejouee:
            return {**reclamation.reponse, "rejoue": True}
        reponse = service.reviser_texte_humain(**arguments, horodatage=maintenant.isoformat(timespec="microseconds"))
        idempotence.finaliser(cnx, meta, reponse)
        journaliser(
            cnx,
            personne.identifiant,
            "console.action_interne",
            nom,
            {"departement": departement, "mutation_id": mutation_id, "ok": reponse.get("accepte")},
        )
        return reponse


_COMMANDES_CMO = {
    "m7_proposer_strategie_humaine": "proposer",
    "m7_decider_strategie_humaine": "decider",
    "m7_revoir_strategie_humaine": "revoir",
}


def _port_cmo(cnx, deps, session):
    if session.expire <= datetime.now(UTC).timestamp():
        raise PermissionError("CMO-SESSION-EXPIREE")
    if (stockage.connexion_courante() is not cnx or cnx.engine.dialect.name != "sqlite"
            or "m07-marketing" not in deps or deps["m07-marketing"].module_outils != "m7_marketing.outils"):
        raise ValueError("CMO-PORT-NON-QUALIFIE")
    personne = identite.personne_active(cnx, session.utilisateur)
    if personne is None or not personne.roles.intersection({"admin", "nathan_owner"}):
        raise PermissionError("CMO-AUTORITE-RETIREE")
    return personne, importlib.import_module("m7_marketing.cmo_strategie")


def _identite_cmo(personne):
    return contexte.IdentiteAppelante(
        personne.identifiant, "nathan_owner" if "nathan_owner" in personne.roles else "admin", source="console",
    )


def projection_cmo(cnx, deps, session, parametres):
    """Le serveur relit les trois propriétaires; le client ne fournit jamais une projection."""
    from m7_marketing import plan_cmo

    from . import frontoffice_marketing

    _port_cmo(cnx, deps, session)
    charges = []
    for nom, arguments in (
        ("m7_lire_profil_marque_courant", {}), ("m7_lister_calendrier", {}),
        ("m7_lire_performance_campagnes", {"debut": parametres["debut"], "fin": parametres["fin"]}),
    ):
        ok, charge, _ = frontoffice_marketing.resultat_metier(executer(cnx, deps, session, nom, arguments))
        if not ok or not isinstance(charge, Mapping) or charge.get("tronque") or charge.get("truncated"):
            raise ValueError("CMO-SOURCE-PROJECTION-INCOMPLETE")
        charges.append(charge)
    return plan_cmo.projeter(**parametres, profil_marque=charges[0], calendrier=charges[1], performance=charges[2])


def lire_strategies_cmo(cnx, deps, session, *, projection=None):
    personne, service = _port_cmo(cnx, deps, session)
    with (
        contexte.appele_par_appareil(_identite_cmo(personne)),
        contexte.appeler_en_tant_que("m07-marketing", origine="console"),
    ):
        resultat = service.lire(cnx)
        if projection is not None:
            from m7_marketing import growth_lecture

            textes, tete = growth_lecture.lire_prefixe(cnx)
            observations = growth_lecture.decoder_prefixe(textes)
            p = projection["periode_observee"]
            retenues = [o for o in observations
                        if p["debut"] <= o["periode"]["debut"] <= o["periode"]["fin"] <= p["fin"]]
            resultat.update(projection_attendue=service.empreinte(projection), growth_tete=tete,
                            observations=[{k: o[k] for k in (
                                "observation_id", "empreinte", "metrique", "unite", "valeur", "periode",
                            )}
                                          for o in retenues[:100]],
                            observations_total=len(retenues), observations_selecteur_limite=len(retenues) > 100)
        _port_cmo(cnx, deps, session)
        return resultat


def _executer_strategie_cmo(cnx, deps, session, nom, arguments, mutation_id):
    personne, service = _port_cmo(cnx, deps, session)
    commande = _COMMANDES_CMO[nom]
    service.valider_commande(commande, arguments)
    if commande == "decider" and "nathan_owner" not in personne.roles:
        raise PermissionError("CMO-DECISION-PROPRIETAIRE-REQUISE")
    if not isinstance(mutation_id, str) or not mutation_id.strip() or len(mutation_id) > 200:
        raise ValueError("CMO-MUTATION-INVALIDE")
    recu_le = datetime.now(UTC)
    meta = idempotence.Meta(mutation_id, f"console:{personne.identifiant}", recu_le.isoformat())
    try:
        reclamation = idempotence.reclamer(cnx, meta, nom, arguments, recu_le)
    except idempotence.MutationConflit as exc:
        raise ValueError("CMO-MUTATION-CONFLIT") from exc
    personne, _ = _port_cmo(cnx, deps, session)
    if commande == "decider" and "nathan_owner" not in personne.roles:
        raise PermissionError("CMO-DECISION-PROPRIETAIRE-RETIREE")
    if reclamation.rejouee:
        return {**reclamation.reponse, "rejoue": True}
    projection = None
    role_cmo = _identite_cmo(personne).role
    with (
        contexte.appele_par_appareil(_identite_cmo(personne)),
        contexte.appeler_en_tant_que("m07-marketing", origine="console"),
    ):
        if commande == "proposer":
            projection = projection_cmo(cnx, deps, session, arguments["parametres"])
        elif commande == "decider":
            historique = service.lire(cnx)["programmes"].get(arguments["programme_id"], [])
            if arguments["revision"] > len(historique):
                raise ValueError("CMO-REVISION-INCONNUE")
            parametres = historique[arguments["revision"] - 1]["proposition"]["charge"]["parametres"]
            projection = projection_cmo(cnx, deps, session, parametres)
        reponse = service.executer(
            cnx, commande, dict(arguments), projection=projection,
            horodatage=datetime.now(UTC).isoformat(timespec="microseconds"),
        )
    actuelle, _ = _port_cmo(cnx, deps, session)
    if role_cmo not in actuelle.roles:
        raise PermissionError("CMO-ROLE-RETIRE-AVANT-FINALISATION")
    if commande == "decider" and "nathan_owner" not in actuelle.roles:
        raise PermissionError("CMO-DECISION-PROPRIETAIRE-RETIREE")
    idempotence.finaliser(cnx, meta, reponse)
    journaliser(cnx, personne.identifiant, "console.action_interne", nom,
                {"departement": "m07-marketing", "mutation_id": mutation_id, "ok": True})
    return reponse


def _executer_observation_growth_humaine(cnx, deps, session, personne, arguments, mutation_id):
    """Commande interne privée : absente du catalogue MCP et des arguments du writer agent."""
    departement = "m07-marketing"
    module = deps[departement].module_outils if departement in deps else None
    if module != "m7_marketing.outils" or cnx.engine.dialect.name != "sqlite":
        raise ValueError("GROWTH-ECRITURE-NON-QUALIFIEE")
    if stockage.connexion_courante() is not cnx:
        raise ValueError("GROWTH-CONNEXION-NON-CANONIQUE")
    if not isinstance(arguments, Mapping) or set(arguments) != {"observation", "rang_attendu", "empreinte_attendue"}:
        raise ValueError("GROWTH-COMMANDE-INVALIDE")
    if not isinstance(mutation_id, str) or not 1 <= len(mutation_id) <= 200 or not mutation_id.strip():
        raise ValueError("mutation_id requis, 200 caractères au plus")
    outil = next((o for o in deps[departement].charger_outils() if o.nom == "m7_enregistrer_observation_growth"), None)
    if outil is None or valider_arguments(outil.parametres, arguments["observation"]):
        raise ValueError("GROWTH-ARGUMENTS-INVALIDES")
    nom = "m7_enregistrer_observation_humaine"
    recu_le = datetime.now(UTC)
    meta = idempotence.Meta(mutation_id, f"console:{personne.identifiant}", recu_le.isoformat())
    try:
        reclamation = idempotence.reclamer(cnx, meta, nom, arguments, recu_le)
    except idempotence.MutationConflit as exc:
        raise ValueError("GROWTH-CONFLIT-COMMANDE") from exc
    # Autorité actuelle avant reçu historique; son ancien CAS n'est pas exécuté une deuxième fois.
    actuelle = identite.personne_active(cnx, session.utilisateur)
    if actuelle is None or not actuelle.roles.intersection({"admin", "nathan_owner"}):
        raise PermissionError("autorité humaine Growth retirée")
    if reclamation.rejouee:
        return {**reclamation.reponse, "rejoue": True}
    service = importlib.import_module("m7_marketing.growth")
    role = "nathan_owner" if "nathan_owner" in actuelle.roles else "admin"
    with (
        contexte.appele_par_appareil(contexte.IdentiteAppelante(actuelle.identifiant, role, source="console")),
        contexte.appeler_en_tant_que(departement, origine="console"),
    ):
        reponse = service.enregistrer_observation_humaine(
            dict(arguments["observation"]), rang_attendu=arguments["rang_attendu"],
            empreinte_attendue=arguments["empreinte_attendue"],
            horodatage=datetime.now(UTC).isoformat(timespec="microseconds"),
        )
    actuelle = identite.personne_active(cnx, session.utilisateur)
    if actuelle is None or role not in actuelle.roles:
        raise PermissionError("autorité humaine Growth retirée")
    idempotence.finaliser(cnx, meta, reponse)
    journaliser(cnx, personne.identifiant, "console.action_interne", nom,
                {"departement": departement, "mutation_id": mutation_id, "ok": True})
    return reponse



def _executer_note_commande(cnx, deps, session, personne, nom, arguments, mutation_id):
    """Port humain privé : Meta réelle, autorité avant cache, réponse complète bornée."""
    from m6_material_control import notes_commande as n
    from m6_material_control import outils as m6

    departement = "m06-material-control"
    if (session.expire <= datetime.now(UTC).timestamp() or "admin" not in personne.roles):
        raise PermissionError("session admin active requise")
    if (departement not in deps or deps[departement].module_outils != "m6_material_control.outils"):
        raise KeyError("service notes M6 indisponible")
    outil = next((o for o in deps[departement].charger_outils() if o.nom == nom), None)
    if outil is None:
        raise KeyError("outil M6 indisponible")
    if not isinstance(arguments, Mapping) or valider_arguments(outil.parametres, arguments):
        raise ValueError("arguments de note invalides")
    ecriture = nom == n.ECRIRE
    if (ecriture and (not isinstance(mutation_id, str) or not mutation_id.strip() or len(mutation_id) > 200)
            or (not ecriture and mutation_id is not None)):
        raise ValueError("intention de note invalide")
    if ecriture and cnx.dialect.name != "sqlite":
        return {"ok": True, "resultat": n.refuser("ECRITURE-NON-QUALIFIEE")}
    with (
        contexte.appele_par_appareil(contexte.IdentiteAppelante(personne.identifiant, "admin", source="console")),
        contexte.appeler_en_tant_que(departement, origine="console"),
        contexte.sortie_bornee(n.BORNE_SORTIE),
    ):
        m6.autoriser_note_commande()
        if not ecriture:
            return executer_atomique(outil, dict(arguments))
        maintenant = datetime.now(UTC)
        meta = idempotence.Meta(mutation_id, f"console:{personne.identifiant}", maintenant.isoformat())
        with (
            m6.contexte_mutation_note_commande(meta),
            contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, maintenant, maintenant)),
        ):
            try:
                recu = idempotence.reclamer(cnx, meta, nom, dict(arguments), maintenant)
            except idempotence.MutationConflit as exc:
                raise ValueError("conflit d'intention de note") from exc
            if recu.rejouee:
                try:
                    m6.verifier_rejeu_note_commande(dict(arguments), recu.reponse)
                except n.Refus as exc:
                    return {"ok": True, "resultat": n.refuser(exc.suffixe)}
                return {**recu.reponse, "rejoue": True}
            reponse = executer_atomique(outil, dict(arguments))
            if reponse.get("ok") is True:
                n.verifier_borne(reponse["resultat"], n.BORNE_SORTIE)
            idempotence.finaliser(cnx, meta, reponse)
            # Le journal métier M6 contient uniquement les références, jamais le texte.
            return reponse


def _executer_annotations(cnx, deps, session, personne, nom, arguments, mutation_id):
    """Port humain M4 : intention dans le maillon privé, aucune copie dans le reçu central."""
    from m4_field_ops import outils as m4

    dept = "m04-field-ops"
    if session.expire <= datetime.now(UTC).timestamp() or "admin" not in personne.roles:
        raise PermissionError("session admin active requise")
    if dept not in deps or deps[dept].module_outils != "m4_field_ops.outils":
        raise KeyError("annotations M4 indisponibles")
    outil = next((o for o in deps[dept].charger_outils() if o.nom == nom), None)
    if outil is None:
        raise KeyError("outil M4 indisponible")
    ecriture = nom in {"m4_enregistrer_annotation_calendrier", "m4_definir_couleur_calendrier"}
    if not isinstance(arguments, Mapping) or valider_arguments(outil.parametres, arguments):
        raise ValueError("annotation invalide")
    if (ecriture and (type(mutation_id) is not str or not mutation_id.strip() or len(mutation_id) > 200)
            or (not ecriture and mutation_id is not None)):
        raise ValueError("intention d'annotation invalide")
    maintenant = datetime.now(UTC)
    meta = (idempotence.Meta(mutation_id, "console:" + personne.identifiant, maintenant.isoformat())
            if ecriture else None)
    with (
        contexte.appele_par_appareil(contexte.IdentiteAppelante(personne.identifiant, "admin", source="console")),
        contexte.appeler_en_tant_que(dept, origine="console"),
        contexte.sortie_bornee(262144 if nom in {"m4_resumer_annotations_calendrier",
                                               "m4_resumer_couleurs_calendrier"} else 65536),
        m4.contexte_annotation_calendrier(meta),
        contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, maintenant, maintenant))
        if ecriture else nullcontext(),
    ):
        return executer_atomique(outil, dict(arguments))


def _executer_agenda(cnx, deps, session, personne, nom, arguments, mutation_id):
    """Port humain M2 : intention dans le maillon privé, aucune copie dans le reçu central."""
    from m2_revenue_crm import outils as m2

    dept = "m02-revenue-crm"
    if session.expire <= datetime.now(UTC).timestamp() or "admin" not in personne.roles:
        raise PermissionError("session admin active requise")
    if dept not in deps or deps[dept].module_outils != "m2_revenue_crm.outils":
        raise KeyError("agenda M2 indisponible")
    outil = next((o for o in deps[dept].charger_outils() if o.nom == nom), None)
    if outil is None:
        raise KeyError("outil M2 indisponible")
    ecriture = nom == "m2_enregistrer_rendez_vous"
    if not isinstance(arguments, Mapping) or valider_arguments(outil.parametres, arguments):
        raise ValueError("rendez-vous invalide")
    if (ecriture and (type(mutation_id) is not str or not mutation_id.strip() or len(mutation_id) > 200)
            or (not ecriture and mutation_id is not None)):
        raise ValueError("intention de rendez-vous invalide")
    maintenant = datetime.now(UTC)
    meta = (idempotence.Meta(mutation_id, "console:" + personne.identifiant, maintenant.isoformat())
            if ecriture else None)
    with (
        contexte.appele_par_appareil(contexte.IdentiteAppelante(personne.identifiant, "admin", source="console")),
        contexte.appeler_en_tant_que(dept, origine="console"),
        contexte.sortie_bornee(65536),
        m2.contexte_agenda(meta),
        contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, maintenant, maintenant))
        if ecriture else nullcontext(),
    ):
        return executer_atomique(outil, dict(arguments))


def _executer_catalogue_m6(cnx, deps, session, personne, nom, arguments, mutation_id):
    from m6_material_control import catalogue_console as catalogue

    if session.expire <= datetime.now(UTC).timestamp() or "admin" not in personne.roles:
        raise PermissionError("session admin active requise")
    dept = catalogue.DEPARTEMENT
    if dept not in deps or deps[dept].module_outils != "m6_material_control.outils":
        raise KeyError("catalogue M6 indisponible")
    outil = next((o for o in deps[dept].charger_outils() if o.nom == nom), None)
    if outil is None:
        raise KeyError("outil M6 indisponible")
    ecriture = nom == "m6_enregistrer_materiau_console"
    if not isinstance(arguments, Mapping) or valider_arguments(outil.parametres, arguments):
        raise ValueError("fiche matériau invalide")
    if (ecriture and (type(mutation_id) is not str or not mutation_id.strip() or len(mutation_id) > 200)
            or (not ecriture and mutation_id is not None)):
        raise ValueError("intention de catalogue invalide")
    maintenant = datetime.now(UTC)
    meta = (idempotence.Meta(mutation_id, "console:" + personne.identifiant, maintenant.isoformat())
            if ecriture else None)
    with (
        contexte.appele_par_appareil(contexte.IdentiteAppelante(personne.identifiant, "admin", source="console")),
        contexte.appeler_en_tant_que(dept, origine="console"), contexte.sortie_bornee(65536),
        catalogue.contexte_mutation(meta),
        contexte.receptionne_de(contexte.HorodatageAppareil("console:" + personne.identifiant, maintenant, maintenant)),
    ):
        return executer_atomique(outil, dict(arguments))


def _executer_modeles(cnx, deps, session, personne, nom, arguments, mutation_id):
    """Port humain M3 : intention dans le maillon privé, aucune copie dans le reçu central."""
    from m3_estimation import outils as m3

    dept = "m03-estimation"
    if session.expire <= datetime.now(UTC).timestamp() or "admin" not in personne.roles:
        raise PermissionError("session admin active requise")
    if dept not in deps or deps[dept].module_outils != "m3_estimation.outils":
        raise KeyError("catalogue M3 indisponible")
    outil = next((o for o in deps[dept].charger_outils() if o.nom == nom), None)
    if outil is None:
        raise KeyError("outil M3 indisponible")
    ecriture = nom in {"m3_enregistrer_modele_soumission", "m3_creer_devis_depuis_modele",
                       "m3_enregistrer_lignes_modele", "m3_creer_devis_prefill"}
    if not isinstance(arguments, Mapping) or valider_arguments(outil.parametres, arguments):
        raise ValueError("modèle invalide")
    if (ecriture and (type(mutation_id) is not str or not mutation_id.strip() or len(mutation_id) > 200)
            or (not ecriture and mutation_id is not None)):
        raise ValueError("intention de modèle invalide")
    maintenant = datetime.now(UTC)
    meta = (idempotence.Meta(mutation_id, "console:" + personne.identifiant, maintenant.isoformat())
            if ecriture else None)
    with (
        contexte.appele_par_appareil(contexte.IdentiteAppelante(personne.identifiant, "admin", source="console")),
        contexte.appeler_en_tant_que(dept, origine="console"),
        contexte.sortie_bornee(65536),
        m3.contexte_modeles(meta),
        contexte.receptionne_de(contexte.HorodatageAppareil(
            "console:" + personne.identifiant, maintenant, maintenant)),
    ):
        return executer_atomique(outil, dict(arguments))


def executer(
    cnx: Connection,
    deps: Mapping[str, Departement],
    session: Session,
    nom: str,
    arguments: Mapping[str, Any],
    *,
    mutation_id: str | None = None,
    octets_prives: bytes | None = None,
    preuve_commande: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    personne = identite.personne_active(cnx, session.utilisateur)
    if personne is None or not personne.roles.intersection({"nathan_owner", "admin"}):
        raise PermissionError("administration métier requise")
    if nom in _OUTILS_ADMIN and "admin" not in personne.roles:
        raise PermissionError("admin SQL requis pour cet outil métier")
    if nom in (_COMMANDES_ADMIN_M2 | _COMMANDES_ADMIN_M4) and session.expire <= datetime.now(UTC).timestamp():
        raise PermissionError("session de note expirée")
    if nom == "m1_consigner_suivi_rappel" and session.expire <= datetime.now(UTC).timestamp():
        raise PermissionError("session de suivi expirée")
    if nom in {
        "m5_affecter_cout_marketing", "m5_revoquer_affectation_cout_marketing", "m5_lire_couts_marketing_affectes",
    }:
        from . import couts_marketing

        return couts_marketing.executer_action(cnx, deps, session, nom, arguments, mutation_id)
    if nom in _COMMANDES_CMO:
        return _executer_strategie_cmo(cnx, deps, session, nom, arguments, mutation_id)
    if nom == "m7_enregistrer_observation_humaine":
        return _executer_observation_growth_humaine(cnx, deps, session, personne, arguments, mutation_id)
    if nom in {"m7_lire_edition_texte_humain", "m7_reviser_texte_humain"}:
        return _executer_edition_texte(cnx, deps, session, personne, nom, arguments, mutation_id)
    if nom in {"m6_enregistrer_materiau_console", "m6_lire_materiau_console", "m6_lister_materiaux_console"}:
        return _executer_catalogue_m6(cnx, deps, session, personne, nom, arguments, mutation_id)
    if nom in {"m3_lister_fournisseurs_modele", "m3_enregistrer_lignes_modele", "m3_lire_lignes_modele",
                   "m3_lire_tarif_modele", "m3_creer_devis_prefill",
                   "m3_enregistrer_modele_soumission", "m3_lire_modele_soumission", "m3_lister_modeles_soumission",
               "m3_creer_devis_depuis_modele", "m3_document_devis_console"}:
        return _executer_modeles(cnx, deps, session, personne, nom, arguments, mutation_id)
    if nom in {"m2_enregistrer_rendez_vous", "m2_lire_agenda_vendeur", "m2_historique_rendez_vous",
                   "m2_lire_rencontres_lead"}:
        return _executer_agenda(cnx, deps, session, personne, nom, arguments, mutation_id)
    if nom in {"m4_enregistrer_annotation_calendrier", "m4_lire_annotations_calendrier",
               "m4_resumer_annotations_calendrier", "m4_definir_couleur_calendrier",
               "m4_lire_couleurs_calendrier", "m4_resumer_couleurs_calendrier", "m4_lire_apercu_mois",
                   "m4_lire_page_cedule_semaine"}:
        return _executer_annotations(cnx, deps, session, personne, nom, arguments, mutation_id)
    if nom in {"m6_enregistrer_note_commande", "m6_lire_note_commande", "m6_lister_notes_commande"}:
        return _executer_note_commande(cnx, deps, session, personne, nom, arguments, mutation_id)
    surfaces = COMMANDES if mutation_id is not None else LECTURES
    departement = surfaces.get(nom)
    est_media = nom == "m7_lire_dossier_medias" or nom in _COMMANDES_MEDIAS
    if est_media and "nathan_owner" not in personne.roles:
        raise PermissionError("propriétaire humain requis")
    if nom in _COMMANDES_MEDIAS and mutation_id is None:
        raise ValueError("mutation média requise")
    if est_media and departement is None:
        departement = "m07-marketing"
    if departement is None or departement not in deps:
        raise KeyError("action métier inconnue")
    if est_media:
        module_outils = deps[departement].module_outils
        if not isinstance(module_outils, str) or module_outils.rsplit(".", 1)[0] != "m7_marketing":
            raise KeyError("service médias M7 indisponible")
        service = importlib.import_module(_NOM_MODULE_SERVICE_M7)
        if nom == "m7_lire_dossier_medias":
            if mutation_id is not None:
                raise ValueError("lecture média sans mutation_id")
            if not isinstance(arguments, Mapping) or valider_arguments(_SCHEMA_LIRE_DOSSIER_MEDIA, arguments):
                raise ValueError("arguments de lecture média invalides")
            contenu_id = arguments["contenu_id"]
            with (
                contexte.appele_par_appareil(
                    contexte.IdentiteAppelante(personne.identifiant, "nathan_owner", source="console")
                ),
                contexte.appeler_en_tant_que(departement, origine="console"),
            ):
                return service.lire_dossier_medias(contenu_id)
        if not isinstance(arguments, Mapping):
            raise ValueError("arguments : objet requis")
        schema_media = (
            _SCHEMA_PREPARER_MEDIA if nom == "m7_preparer_media_humain"
            else _SCHEMA_REMISE_MEDIA if nom == "m7_remettre_dossier_medias_manuel"
            else _SCHEMA_REVUE_MEDIA
        )
        erreurs_media = valider_arguments(schema_media, arguments)
        if erreurs_media:
            raise ValueError("arguments médias invalides")
        charge_idempotence = dict(arguments)
        maintenant = datetime.now(UTC)
        charge_media = {**charge_idempotence, "horodatage": maintenant.isoformat(timespec="microseconds")}
        charge_media["horodatage"] = maintenant.isoformat(timespec="microseconds")
        if not isinstance(mutation_id, str) or not 1 <= len(mutation_id) <= 200 or not mutation_id.strip():
            raise ValueError("mutation_id requis, 200 caractères au plus")
        meta_media = idempotence.Meta(mutation_id, f"console:{personne.identifiant}", maintenant.isoformat())
        try:
            reclamation_media = idempotence.reclamer(cnx, meta_media, nom, charge_idempotence, maintenant)
        except idempotence.MutationConflit as exc:
            raise ValueError("conflit de commande médias") from exc
        if reclamation_media.rejouee:
            return {**reclamation_media.reponse, "rejoue": True}
        if nom == "m7_preparer_media_humain":
            empreinte = charge_media.get("fichier_sha256")
            if not isinstance(octets_prives, bytes) or hashlib.sha256(octets_prives).hexdigest() != empreinte:
                raise ValueError("fichier préparé absent ou empreinte incohérente")
            with (
                contexte.appele_par_appareil(
                    contexte.IdentiteAppelante(personne.identifiant, "nathan_owner", source="console")
                ),
                contexte.appeler_en_tant_que(departement, origine="console"),
            ):
                reponse_media = service.preparer_media_humain(
                    **{k: v for k, v in charge_media.items() if k != "fichier_sha256"}, octets=octets_prives,
                )
        else:
            schema_decision = _SCHEMA_REVUE_MEDIA if nom == "m7_decider_dossier_medias" else _SCHEMA_REMISE_MEDIA
            service_callback = (
                service.decider_dossier_medias if nom == "m7_decider_dossier_medias"
                else service.remettre_dossier_medias_manuel
            )
            outil_revue = Outil(
                nom=nom,
                description="Décision privée du propriétaire sur un dossier de médias, sans publication externe.",
                parametres={
                    **schema_decision,
                    "properties": {**schema_decision["properties"], "horodatage": {"type": "string"}},
                    "required": [*schema_decision["required"], "horodatage"],
                },
                fonction=lambda **kwargs: service_callback(**kwargs),
                autonomie=Autonomie.T1,
                niveau=Niveau.N3,
            )
            identifiant = approbations.creer_demande(cnx, departement, nom, charge_media, niveau=approbations.Niveau.N3)
            with contexte.appele_par_appareil(None):
                decision = approbations.decider(
                    cnx, identifiant, True, personne.identifiant, {nom: outil_revue}, deps,
                    motif="Revue humaine privée du dossier de médias",
                )
            reponse_media = {**decision["reponse"], "approbation_id": identifiant}
        idempotence.finaliser(cnx, meta_media, reponse_media)
        journaliser(cnx, personne.identifiant, "console.action_interne", nom,
                    {"departement": departement, "mutation_id": mutation_id, "ok": reponse_media.get("accepte")})
        return reponse_media
    if nom in {"m5_preparer_brut_regulier", "m5_preparer_dossier_webras"}:
        # Réutilise le même port privé que MCP. `stockage.transaction` rejoint la transaction
        # déjà ouverte par la console (point de sauvegarde), sans créer une identité ou connexion.
        capacites = Capacites(
            deps,
            stockage.transaction,
            filtre={departement},
            appelant=departement,
            memoire=False,
        )
        entree = capacites.index.get(nom)
        outil = entree[1] if entree is not None else None
    else:
        outil = next((o for o in deps[departement].charger_outils() if o.nom == nom), None)
    if outil is None:
        raise KeyError("action métier indisponible")
    if not isinstance(arguments, Mapping):
        raise ValueError("arguments : objet requis")
    charge = dict(arguments)
    maintenant = datetime.now(UTC)
    if "horodatage" in outil.parametres.get("properties", {}):
        if "horodatage" in charge:
            raise ValueError("horodatage créé par le serveur")
        charge["horodatage"] = maintenant.isoformat(timespec="microseconds")
    if "aujourd_hui" in outil.parametres.get("properties", {}):
        if "aujourd_hui" in charge:
            raise ValueError("aujourd_hui créé par le serveur")
        charge["aujourd_hui"] = maintenant.date().isoformat()
    erreurs = valider_arguments(outil.parametres, charge)
    if erreurs:
        raise ValueError("arguments métier invalides : " + str(erreurs))
    meta = None
    if mutation_id is not None:
        if not isinstance(mutation_id, str) or not 1 <= len(mutation_id) <= 200 or not mutation_id.strip():
            raise ValueError("mutation_id requis, 200 caractères au plus")
        meta = idempotence.Meta(mutation_id, f"console:{personne.identifiant}", maintenant.isoformat())
        try:
            charge_recu = arguments if preuve_commande is None else {
                "arguments": dict(arguments), "preuve_commande": dict(preuve_commande),
            }
            reclamation = idempotence.reclamer(cnx, meta, nom, charge_recu, maintenant)
        except idempotence.MutationConflit as exc:
            raise ValueError("conflit de commande métier") from exc
        if reclamation.rejouee:
            if nom == "m1_consigner_suivi_rappel":
                vivante = identite.personne_active(cnx, session.utilisateur)
                if (session.expire <= datetime.now(UTC).timestamp() or vivante is None
                        or not vivante.roles.intersection({"nathan_owner", "admin"})):
                    raise PermissionError("autorité de suivi retirée")
            return {**reclamation.reponse, "rejoue": True}
    if nom in DECISIONS_HUMAINES:
        # La personne presse le bouton; le socle applique les mêmes rôles et trace la décision.
        # N3 aussi pour l'export manuel, dont le service exige une preuve propriétaire vivante.
        ident = approbations.creer_demande(cnx, departement, nom, charge, niveau=approbations.Niveau.N3)
        with contexte.appele_par_appareil(None):
            decision = approbations.decider(
                cnx,
                ident,
                True,
                personne.identifiant,
                {nom: outil},
                deps,
                motif="Action interne demandée depuis la console authentifiée",
            )
        reponse = {**decision["reponse"], "approbation_id": ident}
    else:
        role = "nathan_owner" if "nathan_owner" in personne.roles and nom not in _OUTILS_ADMIN else "admin"
        with (
            contexte.appele_par_appareil(contexte.IdentiteAppelante(personne.identifiant, role, source="console")),
            contexte.appeler_en_tant_que(departement, origine=departement),
            contexte.receptionne_de(contexte.HorodatageAppareil(
                f"console:{personne.identifiant}", maintenant, maintenant,
            )) if nom == "m4_confirmer_dates_cedule" else nullcontext(),
        ):
            reponse = executer_atomique(outil, charge)
    if nom == "m1_consigner_suivi_rappel":
        personne_vivante = identite.personne_active(cnx, session.utilisateur)
        if (session.expire <= datetime.now(UTC).timestamp() or personne_vivante is None
                or not personne_vivante.roles.intersection({"nathan_owner", "admin"})):
            raise PermissionError("autorité de suivi retirée")
        code_refus = None
        if reponse.get("ok") is False:
            details = reponse.get("details")
            code_refus = details[0] if isinstance(details, list) and details else str(details or "")
        else:
            resultat_outil = reponse.get("resultat")
            if isinstance(resultat_outil, Mapping) and resultat_outil.get("accepte") is False:
                verdict = resultat_outil.get("verdict")
                code_refus = (
                    str(verdict.get("code") or "REJ-SUIVI-RAPPEL-REPONSE-INVALIDE")
                    if isinstance(verdict, Mapping) else "REJ-SUIVI-RAPPEL-REPONSE-INVALIDE"
                )
        if code_refus:
            if code_refus == "REJ-SUIVI-RAPPEL-REPONSE-INVALIDE":
                raise RuntimeError("réponse de suivi non qualifiée")
            if any(mot in code_refus for mot in ("HUMAIN", "IDENTITE", "ROLE-INSUFFISANT")):
                raise PermissionError(code_refus)
            if any(mot in code_refus for mot in ("STOCKAGE", "CHAINE", "HISTORIQUE", "SOURCE-INDISPONIBLE")):
                raise RuntimeError("source de suivi indisponible")
            raise ValueError(code_refus)
        if reponse.get("ok") is not True:
            raise ValueError("REJ-SUIVI-RAPPEL-REPONSE-INVALIDE")
    if meta is not None:
        idempotence.finaliser(cnx, meta, reponse)
        journaliser(
            cnx,
            personne.identifiant,
            "console.action_interne",
            nom,
            {"departement": departement, "mutation_id": mutation_id, "ok": reponse.get("ok")},
        )
    return reponse


def lire_media_prive(
    cnx: Connection, deps: Mapping[str, Departement], session: Session, contenu_id: str,
    reference: str, *, mode: str,
) -> tuple[bytes, str] | None:
    """Port binaire fermé à la console propriétaire; aucun outil d'agent ne retourne d'octets."""
    personne = identite.personne_active(cnx, session.utilisateur)
    if personne is None or "nathan_owner" not in personne.roles:
        raise PermissionError("propriétaire humain requis")
    departement = deps.get("m07-marketing")
    if departement is None or departement.module_outils.rsplit(".", 1)[0] != "m7_marketing":
        raise KeyError("service médias M7 indisponible")
    service = importlib.import_module(_NOM_MODULE_SERVICE_M7)
    with (
        contexte.appele_par_appareil(
            contexte.IdentiteAppelante(personne.identifiant, "nathan_owner", source="console")
        ),
        contexte.appeler_en_tant_que("m07-marketing", origine="console"),
    ):
        return service.lire_media_prive(contenu_id, reference, mode=mode)


def exiger_proprietaire_media(cnx: Connection, session: Session) -> None:
    personne = identite.personne_active(cnx, session.utilisateur)
    if personne is None or "nathan_owner" not in personne.roles:
        raise PermissionError("propriétaire humain requis")
