"""Validation humaine au départ (PLAN T1.4-h ; ADR-0009 §4, addendum) : l'humain authentifié qui lance
lui-même une action N3 depuis son appareil n'attend pas le propriétaire, et son action laisse une trace.

Les tests passent par les VRAIS manifestes et les VRAIS outils de M3, M4 et M5 (mode `ombre` réel),
`Capacites.appeler` avec `_meta` d'idempotence et `contexte.appele_par_appareil` pour l'identité —
exactement ce que `serveur_mcp.appeler_outil` pose. Données fictives (AGENTS.md) : personnes,
appareils, clés et identifiants sont marqués « fictif ».
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import struct
import zlib
from pathlib import Path

import anyio
import pytest
from m4_field_ops import cedule, pointage
from m4_field_ops import registre as registre_m4
from mcp import Client
from sqlalchemy import select

from opsys import approbations, contexte, etat, idempotence, identite, openclaw, politiques, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import Niveau, executer_atomique
from opsys.serveur_mcp import creer_serveur
from opsys.stockage.schema import MUTATIONS_APPLIQUEES

FICTIF = True
RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[1] / "departments"
DEPARTEMENTS_TESTES = {"m03-estimation", "m04-field-ops", "m05-financecore"}

EMPLOYE = contexte.IdentiteAppelante(personne="employe.fictif", role="employee")
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")

# T1.4-k : pour un appel d'appareil, l'identifiant de technicien EST celui de la personne authentifiée
# (m4_field_ops.acces) : l'intervention est donc assignée à `employe.fictif`, pas à un « T1 » libre.
SEL = "sel-t1-4-h-fictif"
VILLE = "Montreal"
# Coordonnées reconnaissables : le test vérifie qu'elles n'atterrissent jamais en clair dans la trace.
FIX_GPS = {"latitude": 45.508812, "longitude": -73.587834}
ATTESTATION = {"fictif": True, "appareil_id": "APP-T1-4-H-FICTIF"}
FENETRE_2025 = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}


# -- installation -----------------------------------------------------------------------------------
@pytest.fixture
def capacites(session, nathan):
    """Vrais départements M3/M4/M5 (mode `ombre` de leur manifeste), base migrée, nathan présent."""
    departements = charger_departements(RACINE_DEPARTEMENTS)
    return Capacites(departements, session, filtre=DEPARTEMENTS_TESTES, memoire=False)


@pytest.fixture
def personnes(session, capacites):
    with session() as cnx:
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-1234", ["employee"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])


def _meta(cle: str = "mut-1") -> idempotence.Meta:
    return idempotence.Meta(cle=cle, appareil="tel-employe-fictif-1", horodatage_appareil="2026-09-28T10:15:00-04:00")


def _appeler(capacites, nom, arguments, identite_appelante, cle="mut-1"):
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler(nom, arguments, _meta(cle))


def _outil(capacites, nom):
    return capacites.index[nom][1]


def _referentiel():
    return {cedule.tokeniser_ville(SEL, VILLE): {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}


def _contrat(lead_id):
    return {"lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale", "ville": VILLE,
            "canal": "telephone", "contact": {"nom": "Client fictif", "telephone": "0102030405"},
            "urgence_declaree": False}


def _marqueur(lead_id):
    return {"readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
            "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32}


def _intervention_en_route(capacites, lead_id="L-T1-4-H-FICTIF") -> str:
    """Planifie une intervention et démarre la route, par les VRAIS outils M4 (préparation directe :
    ce n'est pas le geste testé, c'est son point de départ)."""
    plan = executer_atomique(_outil(capacites, "m4_planifier_intervention"), {
        "contrat": _contrat(lead_id), "marqueur": _marqueur(lead_id),
        "horodatage": "2025-06-02T07:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": [EMPLOYE.personne], "fenetres_disponibles": [FENETRE_2025],
    })
    assert plan["ok"] is True, plan
    i_id = plan["resultat"]["intervention_id"]
    consentement = executer_atomique(_outil(capacites, "m4_definir_consentement_gps"), {
        "technicien_id": EMPLOYE.personne, "action": "donne", "horodatage": "2025-06-02T06:00:00+00:00",
        "version_politique": "POLITIQUE-geolocalisation-v1-test",
        "preuve": {"fictif": True, "reference": "consentement-test"},
    })
    assert consentement["ok"] is True and consentement["resultat"]["accepte"] is True, consentement
    depart = executer_atomique(_outil(capacites, "m4_demarrer_route"), {
        "intervention_id": i_id, "technicien_id": EMPLOYE.personne, "horodatage": "2025-06-02T07:30:00+00:00",
    })
    assert depart["ok"] is True and depart["resultat"]["accepte"] is True, depart
    return i_id


def _args_pointage(i_id: str, action: str = "arrivee") -> dict:
    """Arguments d'un pointage d'appareil. La fenêtre de travail entoure « maintenant » : pendant un
    appel d'appareil, l'heure de réception du serveur fait foi (M4, T1.4-d)."""
    maintenant = dt.datetime.now(dt.UTC)
    return {
        "intervention_id": i_id, "technicien_id": EMPLOYE.personne, "action": action,
        "horodatage": "2000-01-01T00:00:00+00:00",  # ignoré pendant un appel d'appareil
        "fix_gps": FIX_GPS, "attestation": ATTESTATION,
        "fenetre_travail": {"debut": (maintenant - dt.timedelta(hours=1)).isoformat(),
                            "fin": (maintenant + dt.timedelta(hours=11)).isoformat()},
        "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL,
    }


# -- lectures d'état --------------------------------------------------------------------------------
def _statut_intervention(capacites, i_id) -> str:
    reponse = executer_atomique(_outil(capacites, "m4_statut_intervention"), {"intervention_id": i_id})
    return reponse["resultat"]["statut"]


def _pointages(i_id) -> list[dict]:
    with stockage.transaction():
        registre = registre_m4.Registre(stockage.maillons("m04-field-ops", "principal"))
        return [m for m in registre.lire()
                if m.get("type_entree") == pointage.TYPE_POINTAGE and m.get("intervention_id") == i_id]


def _demandes(session, statut=None) -> list[dict]:
    with session() as cnx:
        return approbations.lister(cnx, statut)


def _entrees_journal(session) -> list[dict]:
    with session() as cnx:
        return [e for e in etat.lire_journal(cnx) if e["action"] == approbations.ACTION_VALIDATION_AU_DEPART]


def _reclamations(session) -> list[dict]:
    with session() as cnx:
        return [dict(r) for r in cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().all()]


# -- 1. le cas nominal : l'employé pointe, en mode ombre ---------------------------------------------
def test_employe_qui_pointe_en_ombre_est_execute_et_trace(capacites, personnes, session):
    assert capacites.departements["m04-field-ops"].mode == "ombre"
    assert _outil(capacites, "m4_pointer").niveau_effectif is Niveau.N3
    i_id = _intervention_en_route(capacites)
    arguments = _args_pointage(i_id)

    reponse = _appeler(capacites, "m4_pointer", arguments, EMPLOYE)

    assert reponse["ok"] is True and reponse["rejoue"] is False
    assert reponse["resultat"]["accepte"] is True
    assert "statut" not in reponse and "demande_id" not in reponse  # pas une mise en attente
    # SES traces métier : le VRAI registre de M4, pas seulement la réponse.
    assert _statut_intervention(capacites, i_id) == "sur_site"
    assert len(_pointages(i_id)) == 1

    [trace] = _demandes(session)  # la seule ligne du journal des approbations
    assert trace["statut"] == "executee"
    assert (trace["decide_par"], trace["decide_role"]) == ("employe.fictif", "employee")
    assert (trace["departement"], trace["outil"], trace["niveau"]) == ("m04-field-ops", "m4_pointer", "N3")
    assert trace["motif_decision"] == "validation humaine au départ par la personne qui agit, ADR-0009 §4"
    assert trace["decide_le"] == trace["cree_le"] and trace["decide_le"]
    assert trace["arguments"]["intervention_id"] == i_id and trace["arguments"]["action"] == "arrivee"
    assert trace["resultat"] == {"ok": True, "accepte": True}
    assert _demandes(session, "en_attente") == []  # rien n'attend le propriétaire

    [entree] = _entrees_journal(session)
    assert entree["par"] == "employe.fictif" and entree["cible"] == trace["id"]
    assert entree["details"]["outil"] == "m4_pointer" and entree["details"]["appareil"] == "tel-employe-fictif-1"
    assert entree["details"]["role"] == "employee" and entree["details"]["niveau"] == "N3"


def test_la_trace_ne_copie_pas_le_fix_gps_en_clair(capacites, personnes, session):
    """POLITIQUE-geolocalisation §5 : la position est chiffrée dans le registre M4 (clé destructible).
    `approbations.arguments` n'est ni chiffrée ni purgée — y copier le fix défairait la destruction."""
    i_id = _intervention_en_route(capacites)
    arguments = _args_pointage(i_id)
    assert _appeler(capacites, "m4_pointer", arguments, EMPLOYE)["ok"] is True

    [trace] = _demandes(session)
    assert trace["arguments"]["fix_gps"] == approbations.VALEUR_MASQUEE
    with session() as cnx:
        tout_le_journal = json.dumps(etat.lire_journal(cnx), ensure_ascii=False)
    tout = json.dumps(trace, ensure_ascii=False) + tout_le_journal
    for coordonnee in (FIX_GPS["latitude"], FIX_GPS["longitude"]):
        assert str(coordonnee) not in tout
    # La trace reste vérifiable : l'empreinte est celle des arguments RÉELS (celle de l'idempotence).
    [entree] = _entrees_journal(session)
    assert entree["details"]["empreinte_arguments"] == idempotence.empreinte_arguments(arguments)
    # Un fix nul (mode manuel) n'est pas « masqué » : il n'y a rien à cacher, et le dire serait faux.
    manuel = {**arguments, "fix_gps": None}
    assert approbations._arguments_de_la_trace(manuel)["fix_gps"] is None


def test_completion_par_l_employe_est_executee_et_tracee(capacites, personnes, session):
    """Le second geste de terrain du problème : `m4_completer_intervention` (N3). Les faits CLIENT
    (Loi 25) n'y sont acceptés que pendant un appel d'appareil — preuve que l'exécution au départ
    reste DANS le contexte de l'appel d'appareil (horloges, identité), comme sans passe-droit."""
    i_id = _intervention_en_route(capacites, "L-T1-4-H-COMPLETION")
    for action, horodatage in (("arrivee", "2025-06-02T09:00:00+00:00"), ("depart", "2025-06-02T11:30:00+00:00")):
        r = executer_atomique(_outil(capacites, "m4_pointer"), {
            **_args_pointage(i_id, action), "horodatage": horodatage, "fenetre_travail": FENETRE_2025,
        })
        assert r["ok"] is True and r["resultat"]["accepte"] is True, r
    photo = _deposer_photo(capacites)

    reponse = _appeler(capacites, "m4_completer_intervention", {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": {"checklist_complete": True, "photos_apres": [photo], "notes": "RAS.",
                               "signature": None},
        "consentement_marketing": False, "description_factuelle": "Gouttière remplacée (fictif).",
    }, EMPLOYE, cle="mut-completion")

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    assert reponse["resultat"]["resultat"]["statut"] == "completed_pending_review"
    assert _statut_intervention(capacites, i_id) == "completed_pending_review"
    [trace] = _demandes(session)
    assert (trace["outil"], trace["niveau"], trace["statut"], trace["decide_par"]) == (
        "m4_completer_intervention", "N3", "executee", "employe.fictif")


def _png_minimal() -> bytes:
    def chunk(tag: bytes, donnees: bytes) -> bytes:
        return struct.pack(">I", len(donnees)) + tag + donnees + struct.pack(">I", zlib.crc32(tag + donnees))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff", 9)) + chunk(b"IEND", b""))


def _deposer_photo(capacites) -> str:
    contenu = _png_minimal()
    r = executer_atomique(_outil(capacites, "m4_deposer_fichier"), {
        "empreinte_sha256": hashlib.sha256(contenu).hexdigest(), "taille_octets": len(contenu),
        "type_mime": "image/png", "index_bloc": 0, "nombre_blocs": 1,
        "bloc_base64": base64.b64encode(contenu).decode("ascii"),
    })
    assert r["ok"] and r["resultat"]["accepte"] and r["resultat"]["resultat"]["complet"], r
    return r["resultat"]["resultat"]["reference"]


# -- 2. tout ce qui ne change PAS -------------------------------------------------------------------
def test_appel_sans_identite_attend_le_proprietaire_comme_avant(capacites, personnes, session):
    """Un agent, ou un appelant par secret partagé, ne porte jamais d'identité de jeton d'appareil."""
    i_id = _intervention_en_route(capacites)

    reponse = _appeler(capacites, "m4_pointer", _args_pointage(i_id), None)

    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation"
    assert _statut_intervention(capacites, i_id) == "en_route"  # rien exécuté
    assert _pointages(i_id) == []
    [demande] = _demandes(session)
    assert demande["statut"] == "en_attente" and demande["outil"] == "m4_pointer" and demande["niveau"] == "N3"
    assert demande["decide_par"] is None
    assert _entrees_journal(session) == []


def _desactiver(cnx):
    identite.activer(cnx, "employe.fictif", False)


def _retirer_role(cnx):
    identite.retirer_role(cnx, "employe.fictif", "employee")


@pytest.mark.parametrize("perturbation, appelante", [
    pytest.param(_desactiver, EMPLOYE, id="personne_desactivee"),
    pytest.param(_retirer_role, EMPLOYE, id="role_retire"),
    pytest.param(None, contexte.IdentiteAppelante("fantome.fictif", "employee"), id="personne_inconnue"),
    # Le jeton déclare `admin` mais la personne ne porte que `employee` : identité périmée ou falsifiée.
    pytest.param(None, contexte.IdentiteAppelante("employe.fictif", "admin"), id="role_non_porte"),
])
def test_identite_invalide_ne_donne_aucun_passe_droit(capacites, personnes, session, perturbation, appelante):
    """Fail-closed : identité relue EN BASE à chaque appel ; invalide → chemin normal (en attente),
    jamais exécuté, jamais tracé comme validé au départ."""
    i_id = _intervention_en_route(capacites)
    if perturbation is not None:
        with session() as cnx:
            perturbation(cnx)

    reponse = _appeler(capacites, "m4_pointer", _args_pointage(i_id), appelante)

    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation"
    assert _statut_intervention(capacites, i_id) == "en_route"
    assert _pointages(i_id) == []
    assert [d["statut"] for d in _demandes(session)] == ["en_attente"]
    assert _entrees_journal(session) == []


def test_outil_hors_de_la_portee_du_role_est_refuse_par_une_erreur_nommee(capacites, personnes, session):
    """`m3_creer_devis` (N3) est un outil de M3 : hors de la portée d'`employee` (openclaw.roles_outils).
    Refus nommé : ni exécuté, ni mis en attente du propriétaire."""
    assert _outil(capacites, "m3_creer_devis").niveau_effectif is Niveau.N3
    assert "m3_creer_devis" not in openclaw.roles_outils(capacites.departements)["employee"]

    reponse = _appeler(capacites, "m3_creer_devis", {}, EMPLOYE)

    assert reponse["ok"] is False and reponse["erreur"] == "hors_portee_role"
    assert "m3_creer_devis" in reponse["details"] and "employee" in reponse["details"]
    assert _demandes(session) == []
    assert _entrees_journal(session) == []
    # Refus enregistré comme tout refus métier (IDEMPOTENCE.md §8) : un renvoi rejoue le même refus.
    renvoi = _appeler(capacites, "m3_creer_devis", {}, EMPLOYE)
    assert renvoi["erreur"] == "hors_portee_role" and renvoi["rejoue"] is True


def test_n4_par_un_admin_va_toujours_au_proprietaire(capacites, personnes, session):
    """`m4_resoudre_revue_completion` est N4 (écriture finale) ; il est dans la portée d'`admin`,
    mais la validation au départ s'arrête à N3 : mise en attente, exécution seulement après décision."""
    outil = _outil(capacites, "m4_resoudre_revue_completion")
    assert outil.niveau_effectif is Niveau.N4
    assert outil.nom in openclaw.roles_outils(capacites.departements)["admin"]

    reponse = _appeler(capacites, "m4_resoudre_revue_completion", {
        "intervention_id": "INT-INEXISTANTE-FICTIVE", "decision": "verifiee",
        "horodatage": "2026-09-28T12:00:00+00:00", "motif": "Vérifié (fictif).",
    }, ADMIN)

    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation"
    [demande] = _demandes(session)
    assert (demande["statut"], demande["niveau"], demande["decide_par"]) == ("en_attente", "N4", None)
    assert _entrees_journal(session) == []


def test_n4_hors_portee_du_role_suit_la_file_comme_avant(capacites, personnes, session):
    """`m5_envoyer_facture` est N4 et hors de la portée d'`employee` : le refus nommé ne vise que ce qui
    passerait au départ (N3 au plus) ; un N4 « ne change pas », il va en file (le core le refuse déjà)."""
    outil = _outil(capacites, "m5_envoyer_facture")
    assert outil.niveau_effectif is Niveau.N4
    assert outil.nom not in openclaw.roles_outils(capacites.departements)["employee"]

    reponse = _appeler(capacites, "m5_envoyer_facture", {
        "facture_id": "FACT-FICTIVE-1", "horodatage": "2026-09-28T12:00:00+00:00"}, EMPLOYE)

    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation"
    assert [(d["statut"], d["niveau"]) for d in _demandes(session)] == [("en_attente", "N4")]


def test_n5_reste_au_proprietaire_et_exige_toujours_l_attestation(capacites, personnes, session, nathan):
    """`m5_enregistrer_mouvement` est T3/N5 (écriture financière). Même avec une identité d'admin
    valide, il suit la file ; et l'approuver exige toujours l'attestation du professionnel."""
    outil = _outil(capacites, "m5_enregistrer_mouvement")
    assert outil.niveau_effectif is Niveau.N5
    arguments = {"montant": "125.00", "type_mouvement": "ENCAISSEMENT", "horodatage": "2026-09-28T12:00:00+00:00",
                 "classe_retention": "STANDARD", "source": "test fictif"}

    reponse = _appeler(capacites, "m5_enregistrer_mouvement", arguments, ADMIN)

    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation"
    [demande] = _demandes(session, "en_attente")
    assert demande["niveau"] == "N5" and demande["decide_par"] is None
    outils = {o.nom: o for o in capacites.lister()}
    with session() as cnx:
        with pytest.raises(ValueError, match="attestation"):
            approbations.decider(cnx, demande["id"], True, nathan, outils, capacites.departements)
        assert approbations.lister(cnx, "en_attente")[0]["id"] == demande["id"]  # rien exécuté
    assert _entrees_journal(session) == []


def test_mode_supervise_n3_s_execute_sans_trace_comme_avant(capacites, personnes, session, nathan):
    """Hors approbation requise, la voie n'intervient pas : un N3 en mode `supervise` s'exécutait déjà
    directement, sans ligne dans les approbations — cela ne change pas."""
    with session() as cnx:
        approbations.fixer_mode(cnx, "m04-field-ops", "supervise", nathan)
    i_id = _intervention_en_route(capacites)

    reponse = _appeler(capacites, "m4_pointer", _args_pointage(i_id), EMPLOYE)

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True
    assert _statut_intervention(capacites, i_id) == "sur_site"
    assert _demandes(session) == [] and _entrees_journal(session) == []


def test_refus_metier_de_l_outil_ne_laisse_aucune_trace(capacites, personnes, session):
    """Un refus (arguments invalides) n'exécute rien : le journal ne dit jamais « exécuté » à tort."""
    i_id = _intervention_en_route(capacites)
    incomplets = {k: v for k, v in _args_pointage(i_id).items() if k != "sel"}

    reponse = _appeler(capacites, "m4_pointer", incomplets, EMPLOYE)

    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    assert _demandes(session) == [] and _entrees_journal(session) == []
    assert _pointages(i_id) == []


# -- 3. idempotence d'appareil (T1.4-b) intacte ------------------------------------------------------
def test_renvoi_idempotent_une_seule_execution_et_une_seule_trace(capacites, personnes, session):
    i_id = _intervention_en_route(capacites)
    arguments = _args_pointage(i_id)

    premiere = _appeler(capacites, "m4_pointer", arguments, EMPLOYE, cle="mut-renvoi")
    renvoi = _appeler(capacites, "m4_pointer", arguments, EMPLOYE, cle="mut-renvoi")

    assert premiere["rejoue"] is False and renvoi["rejoue"] is True
    assert renvoi["resultat"] == premiere["resultat"] and renvoi["ok"] is True
    assert len(_pointages(i_id)) == 1  # une seule exécution
    assert len(_demandes(session)) == 1 and len(_entrees_journal(session)) == 1  # une seule trace
    [reclamation] = _reclamations(session)
    assert reclamation["cle_idempotence"] == "mut-renvoi" and reclamation["statut"] == "ok"


def test_renvoi_meme_apres_perte_de_la_personne_rejoue_sans_reexecuter(capacites, personnes, session):
    """Un renvoi rejoue la réponse enregistrée : il ne repasse pas par la validation, donc désactiver
    la personne entre-temps ne fabrique ni seconde exécution ni seconde trace."""
    i_id = _intervention_en_route(capacites)
    arguments = _args_pointage(i_id)
    premiere = _appeler(capacites, "m4_pointer", arguments, EMPLOYE, cle="mut-perdu")
    with session() as cnx:
        identite.activer(cnx, "employe.fictif", False)

    renvoi = _appeler(capacites, "m4_pointer", arguments, EMPLOYE, cle="mut-perdu")

    assert renvoi["rejoue"] is True and renvoi["resultat"] == premiere["resultat"]
    assert len(_pointages(i_id)) == 1 and len(_demandes(session)) == 1


# -- 4. atomicité de la trace avec l'exécution --------------------------------------------------------
def test_trace_et_execution_reussissent_ou_echouent_ensemble(capacites, personnes, session, monkeypatch):
    """Si l'écriture de la trace échoue APRÈS que la ligne d'approbation a été écrite, tout est annulé :
    le pointage, la ligne, l'entrée d'audit ET la réclamation d'idempotence (un renvoi réessaie)."""
    i_id = _intervention_en_route(capacites)
    arguments = _args_pointage(i_id)
    originale = approbations.tracer_validation_au_depart

    def trace_puis_panne(*args, **kwargs):
        originale(*args, **kwargs)  # la ligne et l'entrée d'audit sont écrites…
        raise RuntimeError("panne simulée après l'écriture de la trace")

    monkeypatch.setattr(approbations, "tracer_validation_au_depart", trace_puis_panne)
    with pytest.raises(RuntimeError, match="panne simulée"):
        _appeler(capacites, "m4_pointer", arguments, EMPLOYE, cle="mut-panne")

    assert _pointages(i_id) == [] and _statut_intervention(capacites, i_id) == "en_route"
    assert _demandes(session) == [] and _entrees_journal(session) == []
    assert _reclamations(session) == []

    monkeypatch.setattr(approbations, "tracer_validation_au_depart", originale)
    renvoi = _appeler(capacites, "m4_pointer", arguments, EMPLOYE, cle="mut-panne")  # le renvoi réessaie
    assert renvoi["ok"] is True and renvoi["rejoue"] is False
    assert len(_pointages(i_id)) == 1 and len(_demandes(session)) == 1


def test_le_point_de_sauvegarde_annule_l_execution_meme_si_l_appelant_rattrape_l_erreur(
    capacites, personnes, session, monkeypatch
):
    """Le couple exécution + trace est un point de sauvegarde à lui seul (`Capacites._valider_au_depart`) :
    même si un appelant rattrape l'exception et poursuit sa transaction, aucune exécution ne survit
    sans sa trace."""
    i_id = _intervention_en_route(capacites)
    departement = capacites.departements["m04-field-ops"]

    def panne(*_args, **_kwargs):
        raise RuntimeError("panne de trace simulée")

    monkeypatch.setattr(approbations, "tracer_validation_au_depart", panne)
    horloges = contexte.HorodatageAppareil(
        appareil="tel-employe-fictif-1", horodatage_appareil=dt.datetime.now(dt.UTC),
        recu_le=dt.datetime.now(dt.UTC))
    with session() as cnx, contexte.appele_par_appareil(EMPLOYE), contexte.receptionne_de(horloges):
        with pytest.raises(RuntimeError, match="panne de trace"):
            capacites._valider_au_depart(cnx, departement, _outil(capacites, "m4_pointer"),
                                         _args_pointage(i_id))
        # Même transaction, exception rattrapée : le pointage écrit avant la panne a été annulé.
        assert _pointages(i_id) == []
        assert approbations.lister(cnx) == []


# -- 5. la portée du rôle vient de openclaw.roles_outils, sans copie ------------------------------------
def test_portee_du_role_est_celle_de_roles_outils(capacites):
    attendu = openclaw.roles_outils(capacites.departements)
    for role in ("employee", "seller", "admin"):
        assert capacites._outils_du_role(role) == frozenset(attendu[role])
    assert {"m4_pointer", "m4_completer_intervention"} <= capacites._outils_du_role("employee")
    assert capacites._outils_du_role("nathan_owner") == frozenset()  # aucun jeton d'appareil n'a ce rôle
    assert capacites._outils_du_role("role-inconnu") == frozenset()  # fail-closed


def test_le_socle_consulte_roles_outils_au_lieu_d_une_copie(capacites, personnes, session, monkeypatch):
    """Si `roles_outils` retire `m4_pointer` à l'employé, le socle le refuse aussitôt : la règle n'est
    pas recopiée dans `capacites.py`."""
    departements = capacites.departements
    reelle = openclaw.roles_outils(departements)
    retiree = {**reelle, "employee": tuple(n for n in reelle["employee"] if n != "m4_pointer")}
    monkeypatch.setattr(openclaw, "roles_outils", lambda _departements: retiree)
    nouvelle = Capacites(departements, session, memoire=False)
    i_id = _intervention_en_route(nouvelle)

    reponse = _appeler(nouvelle, "m4_pointer", _args_pointage(i_id), EMPLOYE)

    assert reponse["erreur"] == "hors_portee_role"
    assert _pointages(i_id) == [] and _demandes(session) == []


# -- 6. de bout en bout par MCP : l'identité vient du `_meta`, jamais des arguments --------------------
def test_mcp_de_bout_en_bout_identite_du_meta(capacites, personnes, session):
    i_id = _intervention_en_route(capacites)
    serveur = creer_serveur(capacites)
    arguments = _args_pointage(i_id)

    def meta(cle, **identite_meta):
        return {"opsys/idempotencyKey": cle, "opsys/appareil": "tel-employe-fictif-1",
                "opsys/horodatageAppareil": "2026-09-28T10:15:00-04:00", **identite_meta}

    async def scenario() -> tuple[dict, dict]:
        async with Client(serveur) as client:
            sans = await client.call_tool("m4_pointer", arguments, meta=meta("mut-mcp-sans"))
            avec = await client.call_tool("m4_pointer", arguments, meta=meta(
                "mut-mcp-avec", **{"opsys/personne": "employe.fictif", "opsys/role": "employee"}))
            return json.loads(sans.content[0].text), json.loads(avec.content[0].text)

    sans, avec = anyio.run(scenario)

    assert sans["statut"] == "en_attente_approbation"  # sans identité en `_meta` : la file
    assert avec["ok"] is True and avec["resultat"]["accepte"] is True and avec["rejoue"] is False
    assert _statut_intervention(capacites, i_id) == "sur_site" and len(_pointages(i_id)) == 1
    statuts = sorted((d["statut"], d["decide_par"]) for d in _demandes(session))
    assert statuts == [("en_attente", None), ("executee", "employe.fictif")]


# -- 7. unités : la règle et la revérification --------------------------------------------------------
@pytest.mark.parametrize("niveau, possible", [
    (Niveau.N0, True), (Niveau.N1, True), (Niveau.N2, True), (Niveau.N3, True),
    (Niveau.N4, False), (Niveau.N5, False),
])
def test_validation_au_depart_possible_s_arrete_a_n3(niveau, possible):
    assert politiques.validation_au_depart_possible(niveau) is possible


def test_signataire_valide_relit_la_base(session, personnes_sans_capacites):
    with session() as cnx:
        assert approbations.signataire_valide(cnx, None) is None
        assert approbations.signataire_valide(cnx, EMPLOYE) == EMPLOYE
        assert approbations.signataire_valide(cnx, contexte.IdentiteAppelante("fantome.fictif", "employee")) is None
        assert approbations.signataire_valide(cnx, contexte.IdentiteAppelante("employe.fictif", "admin")) is None
        identite.retirer_role(cnx, "employe.fictif", "employee")
        assert approbations.signataire_valide(cnx, EMPLOYE) is None
        identite.ajouter_role(cnx, "employe.fictif", "employee")
        assert approbations.signataire_valide(cnx, EMPLOYE) == EMPLOYE
        identite.activer(cnx, "employe.fictif", False)
        assert approbations.signataire_valide(cnx, EMPLOYE) is None


@pytest.fixture
def personnes_sans_capacites(session):
    with session() as cnx:
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-1234", ["employee"])
