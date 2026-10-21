"""PLAN T1.4-k : un appel d'appareil porte l'identité AUTHENTIFIÉE de la personne (`opsys.contexte.
appele_par_appareil`) ; M4 n'en croit plus les arguments. Un `employee` n'agit que sur les
interventions qui lui sont ASSIGNÉES, sous son propre identifiant ; l'`admin` garde toutes ; un appel
sans identité d'appareil (agent, console) se comporte comme avant.

Les tests passent par les VRAIS outils (`m4_field_ops.outils.outils()`, registre durable adossé à une
base SQLite migrée) appelés comme en production (`executer_atomique`), avec de vraies personnes créées
par `opsys.identite`. Ils nomment chaque refus, et prouvent à chaque fois que RIEN n'a été écrit au
registre (comparaison avant/après) — sinon un refus tardif, après une écriture, passerait pour un refus.
Données fictives (AGENTS.md) : personnes, appareils et identifiants sont marqués « fictif ».
"""

from __future__ import annotations

import contextlib
import datetime as dt

import pytest
from m4_field_ops import cedule, consentement, etats, pointage
from m4_field_ops import registre as registre_m4
from m4_field_ops.outils import outils

from opsys import cles_chiffrement, contexte, identite, stockage
from opsys.outils import executer_atomique

FICTIF = True
SEL = "sel-t1-4-k-fictif"
VILLE = "Montreal"
FIX_GPS = {"latitude": 45.5088, "longitude": -73.5878}
ATTESTATION = {"fictif": True, "appareil_id": "APP-T1-4-K-FICTIF"}
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}
VERSION_POLITIQUE = "POLITIQUE-geolocalisation-v1-test"
PREUVE = {"fictif": True, "reference": "consentement-t1-4-k-fictif"}
HORLOGE_APPAREIL_DEREGLEE = dt.datetime(2000, 1, 1, 0, 0, 0, tzinfo=dt.UTC)

MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
LEA = contexte.IdentiteAppelante(personne="lea.fictif", role="employee")
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")

CODE_NON_ASSIGNEE = "REJ-INTERVENTION-NON-ASSIGNEE"
CODE_IDENTITE_FOURNIE = "REJ-IDENTITE-FOURNIE-DIFFERENTE"
CODE_IDENTITE_INVALIDE = "REJ-IDENTITE-APPAREIL-INVALIDE"


# -- installation -----------------------------------------------------------------------------------
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "lea.fictif", "Léa Fictive", "mot-de-passe-lea-12345", ["employee"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])


@pytest.fixture
def par_nom(personnes):
    return {o.nom: o for o in outils()}


# -- aides -------------------------------------------------------------------------------------------
@contextlib.contextmanager
def _appareil(identite_appelante, recu_le: dt.datetime | None = None):
    """Ce que `serveur_mcp.appeler_outil` et `Capacites.appeler` posent pour un appel d'appareil :
    l'identité authentifiée ET les deux horloges. Sans identité : un appel d'agent."""
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
            pile.enter_context(contexte.receptionne_de(contexte.HorodatageAppareil(
                appareil="tel-fictif-t1-4-k", horodatage_appareil=HORLOGE_APPAREIL_DEREGLEE,
                recu_le=recu_le or dt.datetime(2025, 6, 2, 9, 0, 0, tzinfo=dt.UTC),
            )))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=None, recu_le=None):
    with _appareil(identite_appelante, recu_le):
        return executer_atomique(par_nom[nom], arguments)


def _code_refus(reponse):
    """Code du verdict d'un refus métier : `ok` reste vrai (l'outil a répondu), `accepte` est faux."""
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _resultat(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _maillons():
    with stockage.transaction():
        return registre_m4.Registre(stockage.maillons("m04-field-ops", "principal")).lire()


def _contrat(lead_id):
    return {"lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale", "ville": VILLE,
            "canal": "telephone", "contact": {"nom": "Client fictif", "telephone": "0102030405"},
            "urgence_declaree": False}


def _marqueur(lead_id):
    return {"readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
            "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32}


def _planifier(par_nom, lead_id, techniciens=("marc.fictif",), fenetres=(FENETRE,)) -> str:
    """Agent : inscrit et cédule l'intervention (`m4_planifier_intervention`, fermé aux appareils)."""
    reponse = _appeler(par_nom, "m4_planifier_intervention", {
        "contrat": _contrat(lead_id), "marqueur": _marqueur(lead_id),
        "horodatage": "2025-06-02T06:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": list(techniciens), "fenetres_disponibles": list(fenetres),
    })
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]["intervention_id"]


def _consentement(par_nom, technicien_id, action="donne", identite_appelante=None,
                  horodatage="2025-06-02T06:30:00+00:00"):
    return _appeler(par_nom, "m4_definir_consentement_gps", {
        "technicien_id": technicien_id, "action": action, "horodatage": horodatage,
        "version_politique": VERSION_POLITIQUE, "preuve": PREUVE,
    }, identite_appelante)


def _route(par_nom, i_id, technicien_id, identite_appelante=None, horodatage="2025-06-02T07:30:00+00:00"):
    return _appeler(par_nom, "m4_demarrer_route", {
        "intervention_id": i_id, "technicien_id": technicien_id, "horodatage": horodatage,
    }, identite_appelante)


def _referentiel():
    return {cedule.tokeniser_ville(SEL, VILLE): {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}


def _args_pointage(i_id, technicien_id, action="arrivee", horodatage="2025-06-02T09:00:00+00:00"):
    return {"intervention_id": i_id, "technicien_id": technicien_id, "action": action, "horodatage": horodatage,
            "fix_gps": FIX_GPS, "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL}


def _pointer(par_nom, i_id, technicien_id, action="arrivee", identite_appelante=None, recu_le=None,
             horodatage="2025-06-02T09:00:00+00:00"):
    return _appeler(par_nom, "m4_pointer", _args_pointage(i_id, technicien_id, action, horodatage),
                    identite_appelante, recu_le)


def _en_route(par_nom, lead_id, technicien_id):
    """Intervention planifiée POUR `technicien_id`, consentement GPS donné, route démarrée (agent)."""
    i_id = _planifier(par_nom, lead_id, techniciens=(technicien_id,))
    assert _consentement(par_nom, technicien_id)["ok"] is True
    _resultat(_route(par_nom, i_id, technicien_id))
    return i_id


def _statut(par_nom, i_id):
    return _resultat_statut(_appeler(par_nom, "m4_statut_intervention", {"intervention_id": i_id}))


def _resultat_statut(reponse):
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]["statut"]


def _liste(par_nom, identite_appelante=None, statut=None):
    reponse = _appeler(par_nom, "m4_lister_interventions", {} if statut is None else {"statut": statut},
                       identite_appelante)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _ids(liste):
    return {e["intervention_id"] for e in liste}


# =========================================================================================
# 1. L'assignation entre au registre à la planification (le lien intervention -> personne)
# =========================================================================================
def test_planifier_consigne_le_technicien_de_la_cedule_avant_le_depart(par_nom):
    i_id = _planifier(par_nom, "L-ASSIGNATION", techniciens=("marc.fictif",))

    [entree] = _liste(par_nom)
    assert entree["intervention_id"] == i_id and entree["statut"] == "planifiee"
    assert entree["technicien_assigne"] == "marc.fictif"  # avant TOUT départ
    assignations = [m for m in _maillons() if m["type_entree"] == etats.TYPE_ASSIGNATION]
    assert [(m["intervention_id"], m["technicien_id"]) for m in assignations] == [(i_id, "marc.fictif")]


def test_planifier_sans_fenetre_ne_consigne_aucune_assignation(par_nom):
    """La cédule ne peut rien assigner (aucune fenêtre) : personne n'est inventé, l'intervention
    n'est à personne — donc à aucun employé (fail-closed)."""
    i_id = _planifier(par_nom, "L-NON-CEDULEE", fenetres=())

    [entree] = _liste(par_nom)
    assert entree["intervention_id"] == i_id and entree["technicien_assigne"] is None
    assert [m for m in _maillons() if m["type_entree"] == etats.TYPE_ASSIGNATION] == []


def test_l_assignation_est_a_la_personne_que_la_cedule_a_retenue_pas_a_tous_les_disponibles(par_nom):
    """La cédule d'une seule intervention retient UN technicien parmi les disponibles."""
    i_id = _planifier(par_nom, "L-DISPONIBLES", techniciens=("marc.fictif", "lea.fictif"))

    [entree] = _liste(par_nom)
    assert entree["intervention_id"] == i_id
    assert entree["technicien_assigne"] in ("marc.fictif", "lea.fictif")


# =========================================================================================
# 2. m4_demarrer_route
# =========================================================================================
def test_employe_demarre_la_route_de_son_intervention(par_nom):
    i_id = _planifier(par_nom, "L-ROUTE-OK", techniciens=("marc.fictif",))

    reponse = _route(par_nom, i_id, "marc.fictif", MARC)

    assert _resultat(reponse)["statut"] == "en_route"
    assert _statut(par_nom, i_id) == "en_route"
    [entree] = _liste(par_nom)
    assert entree["technicien_assigne"] == "marc.fictif"


def test_employe_ne_demarre_pas_la_route_de_l_intervention_d_un_collegue(par_nom):
    i_lea = _planifier(par_nom, "L-ROUTE-LEA", techniciens=("lea.fictif",))
    avant = _maillons()

    # Sous son propre identifiant : l'intervention n'est pas la sienne.
    assert _code_refus(_route(par_nom, i_lea, "marc.fictif", MARC)) == CODE_NON_ASSIGNEE
    # Sous celui de sa collègue : identifiant refusé, jamais préféré en silence.
    assert _code_refus(_route(par_nom, i_lea, "lea.fictif", MARC)) == CODE_IDENTITE_FOURNIE

    assert _maillons() == avant, "aucun refus n'écrit quoi que ce soit"
    assert _statut(par_nom, i_lea) == "planifiee"


def test_employe_ne_demarre_pas_la_route_d_une_intervention_non_cedulee(par_nom):
    i_id = _planifier(par_nom, "L-ROUTE-NON-CEDULEE", fenetres=())
    avant = _maillons()

    assert _code_refus(_route(par_nom, i_id, "marc.fictif", MARC)) == CODE_NON_ASSIGNEE

    assert _maillons() == avant


def test_employe_ne_demarre_pas_une_intervention_inconnue_meme_refus_que_celle_d_un_autre(par_nom):
    i_lea = _planifier(par_nom, "L-ROUTE-SONDE", techniciens=("lea.fictif",))

    refus_autre = _route(par_nom, i_lea, "marc.fictif", MARC)
    refus_inconnue = _route(par_nom, "intervention-qui-n-existe-pas", "marc.fictif", MARC)

    assert refus_autre == refus_inconnue  # rien ne dit à un employé quelles interventions existent


def test_technicien_id_de_l_employe_different_de_la_personne_est_refuse_meme_sur_son_intervention(par_nom):
    i_marc = _planifier(par_nom, "L-ROUTE-USURPATION", techniciens=("marc.fictif",))
    avant = _maillons()

    reponse = _route(par_nom, i_marc, "lea.fictif", MARC)

    assert _code_refus(reponse) == CODE_IDENTITE_FOURNIE
    assert "technicien_id" in reponse["resultat"]["verdict"]["detail"]
    assert _maillons() == avant
    assert _statut(par_nom, i_marc) == "planifiee"  # rien n'est parti « au nom de Léa »


def test_admin_dispatche_pour_les_autres_via_son_appareil(par_nom):
    i_lea = _planifier(par_nom, "L-ROUTE-ADMIN", techniciens=("lea.fictif",))

    reponse = _route(par_nom, i_lea, "lea.fictif", ADMIN)

    assert _resultat(reponse)["statut"] == "en_route"
    assert _liste(par_nom)[0]["technicien_assigne"] == "lea.fictif"


def test_appel_sans_identite_d_appareil_garde_le_comportement_actuel(par_nom):
    """Agent ou console : aucun contrôle de personne (documenté, ROLES.md « Voie des agents »)."""
    i_lea = _planifier(par_nom, "L-ROUTE-AGENT", techniciens=("lea.fictif",))

    assert _resultat(_route(par_nom, i_lea, "n-importe-qui", None))["statut"] == "en_route"


def test_l_admin_qui_envoie_un_autre_technicien_reprend_l_intervention(par_nom):
    """Le DERNIER fait d'assignation l'emporte : Marc était cédulé, l'admin envoie Léa ; Marc perd
    l'accès, Léa l'obtient."""
    i_id = _planifier(par_nom, "L-REPRISE", techniciens=("marc.fictif",))
    _resultat(_route(par_nom, i_id, "lea.fictif", ADMIN))

    assert _ids(_liste(par_nom, MARC)) == set()
    assert _ids(_liste(par_nom, LEA)) == {i_id}
    assert _code_refus(_pointer(par_nom, i_id, "marc.fictif", identite_appelante=MARC)) == CODE_NON_ASSIGNEE


# =========================================================================================
# 3. m4_pointer
# =========================================================================================
def test_employe_pointe_sur_son_intervention(par_nom):
    i_id = _en_route(par_nom, "L-POINTAGE-OK", "marc.fictif")

    accuse = _resultat(_pointer(par_nom, i_id, "marc.fictif", identite_appelante=MARC))

    assert accuse["statut"] == "sur_site"
    assert accuse["gps_chiffre"] is True and "mode_pointage" not in accuse  # consentement actif : fix retenu


def test_employe_ne_pointe_pas_pour_l_intervention_d_un_collegue(par_nom):
    i_lea = _en_route(par_nom, "L-POINTAGE-LEA", "lea.fictif")
    avant = _maillons()

    assert _code_refus(_pointer(par_nom, i_lea, "marc.fictif", identite_appelante=MARC)) == CODE_NON_ASSIGNEE
    assert _code_refus(_pointer(par_nom, i_lea, "lea.fictif", identite_appelante=MARC)) == CODE_IDENTITE_FOURNIE

    assert _maillons() == avant, "aucun pointage, aucune trace de refus dans le registre"
    with stockage.transaction() as cnx:
        assert cles_chiffrement.lire(cnx, "m04-field-ops/gps", "marc.fictif") is None
    assert _statut(par_nom, i_lea) == "en_route"


def test_un_pointage_refuse_ne_cree_aucune_cle_de_chiffrement_gps(par_nom):
    """Le contrôle passe AVANT la clé de chiffrement (`obtenir_ou_creer` ÉCRIT dans le coffre) : un
    refus ne laisse rien, même pas une clé pour la personne visée."""
    i_lea = _en_route(par_nom, "L-POINTAGE-CLE", "lea.fictif")
    with stockage.transaction() as cnx:
        assert cles_chiffrement.lire(cnx, "m04-field-ops/gps", "lea.fictif") is None

    assert _code_refus(_pointer(par_nom, i_lea, "lea.fictif", identite_appelante=MARC)) == CODE_IDENTITE_FOURNIE

    with stockage.transaction() as cnx:
        assert cles_chiffrement.lire(cnx, "m04-field-ops/gps", "lea.fictif") is None


def test_l_admin_pointe_pour_un_technicien_via_son_appareil(par_nom):
    i_lea = _en_route(par_nom, "L-POINTAGE-ADMIN", "lea.fictif")

    accuse = _resultat(_pointer(par_nom, i_lea, "lea.fictif", identite_appelante=ADMIN))

    assert accuse["statut"] == "sur_site"


def test_le_pointage_d_appareil_garde_l_heure_du_serveur_apres_le_controle(par_nom):
    """Le contrôle d'accès ne déplace pas T1.4-d : l'heure de réception fait foi."""
    i_id = _en_route(par_nom, "L-POINTAGE-HEURE", "marc.fictif")
    recu = dt.datetime(2025, 6, 2, 10, 15, 0, tzinfo=dt.UTC)

    accuse = _resultat(_pointer(par_nom, i_id, "marc.fictif", identite_appelante=MARC, recu_le=recu,
                                horodatage="2000-01-01T00:00:00+00:00"))

    assert accuse["horodatage"] == recu.isoformat()


# =========================================================================================
# 4. m4_signaler_report et m4_creer_demande_ecart
# =========================================================================================
def _report(par_nom, i_id, identite_appelante=None, motif="meteo"):
    return _appeler(par_nom, "m4_signaler_report", {
        "intervention_id": i_id, "motif": motif, "horodatage": "2025-06-02T08:00:00+00:00",
    }, identite_appelante)


def test_employe_signale_le_report_de_son_intervention(par_nom):
    i_id = _planifier(par_nom, "L-REPORT-OK", techniciens=("marc.fictif",))

    assert _resultat(_report(par_nom, i_id, MARC))["statut"] == "reportee"


def test_employe_ne_reporte_pas_l_intervention_d_un_collegue(par_nom):
    i_lea = _planifier(par_nom, "L-REPORT-LEA", techniciens=("lea.fictif",))
    avant = _maillons()

    assert _code_refus(_report(par_nom, i_lea, MARC)) == CODE_NON_ASSIGNEE

    assert _maillons() == avant
    assert _statut(par_nom, i_lea) == "planifiee"


def test_admin_reporte_l_intervention_d_un_autre_et_l_agent_aussi(par_nom):
    i_a = _planifier(par_nom, "L-REPORT-ADMIN", techniciens=("lea.fictif",))
    i_b = _planifier(par_nom, "L-REPORT-AGENT", techniciens=("lea.fictif",))

    assert _resultat(_report(par_nom, i_a, ADMIN, motif="decision_admin"))["statut"] == "reportee"
    assert _resultat(_report(par_nom, i_b, None))["statut"] == "reportee"


def _ecart(par_nom, i_id, identite_appelante=None):
    return _appeler(par_nom, "m4_creer_demande_ecart", {
        "intervention_id": i_id,
        "version_prevue": {"duree_minutes": 120, "perimetre": "gouttières", "materiaux": ["a"]},
        "version_declaree": {"duree_minutes": 240, "perimetre": "gouttières", "materiaux": ["a"]},
        "horodatage": "2025-06-02T10:00:00+00:00",
    }, identite_appelante)


def test_employe_demande_un_ecart_sur_son_intervention(par_nom):
    i_id = _en_route(par_nom, "L-ECART-OK", "marc.fictif")

    accuse = _resultat(_ecart(par_nom, i_id, MARC))

    assert accuse["intervention_id"] == i_id and accuse["type_demande"] == "ecart_metier"


def test_employe_ne_demande_pas_un_ecart_sur_l_intervention_d_un_collegue(par_nom):
    i_lea = _en_route(par_nom, "L-ECART-LEA", "lea.fictif")
    avant = _maillons()

    assert _code_refus(_ecart(par_nom, i_lea, MARC)) == CODE_NON_ASSIGNEE

    assert _maillons() == avant
    assert _statut(par_nom, i_lea) == "en_route"  # pas passée en revue à la demande d'un tiers


def test_admin_ouvre_un_ecart_pour_un_autre(par_nom):
    i_lea = _en_route(par_nom, "L-ECART-ADMIN", "lea.fictif")

    assert _resultat(_ecart(par_nom, i_lea, ADMIN))["statut"] == "en_revue"


# =========================================================================================
# 5. m4_completer_intervention
# =========================================================================================
def _sur_site_puis_depart(par_nom, i_id, technicien_id):
    """Arrivée et départ pointés par l'agent (la préparation, pas le geste testé)."""
    for action, horodatage in (("arrivee", "2025-06-02T09:00:00+00:00"), ("depart", "2025-06-02T11:30:00+00:00")):
        _resultat(_pointer(par_nom, i_id, technicien_id, action, horodatage=horodatage))


def _completer(par_nom, i_id, photo, identite_appelante=None):
    return _appeler(par_nom, "m4_completer_intervention", {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": {"checklist_complete": True, "photos_apres": [photo], "notes": "RAS.", "signature": None},
    }, identite_appelante)


def test_employe_termine_son_intervention(par_nom, deposer_photo_test):
    i_id = _en_route(par_nom, "L-COMPLETION-OK", "marc.fictif")
    _sur_site_puis_depart(par_nom, i_id, "marc.fictif")

    accuse = _resultat(_completer(par_nom, i_id, deposer_photo_test(par_nom), MARC))

    assert accuse["statut"] == "completed_pending_review"
    assert _statut(par_nom, i_id) == "completed_pending_review"


def test_employe_ne_termine_pas_l_intervention_d_un_collegue(par_nom, deposer_photo_test):
    i_lea = _en_route(par_nom, "L-COMPLETION-LEA", "lea.fictif")
    _sur_site_puis_depart(par_nom, i_lea, "lea.fictif")
    photo = deposer_photo_test(par_nom)
    avant = _maillons()

    assert _code_refus(_completer(par_nom, i_lea, photo, MARC)) == CODE_NON_ASSIGNEE

    assert _maillons() == avant, "aucune complétion, aucun WCT"
    assert _statut(par_nom, i_lea) == "sur_site"


def test_le_refus_precede_meme_la_verification_des_preuves(par_nom):
    """Le contrôle d'accès passe avant toute lecture des preuves : un employé qui tente l'intervention
    d'un autre avec une référence de fichier bidon apprend « non assignée », pas « fichier introuvable »."""
    i_lea = _en_route(par_nom, "L-COMPLETION-ORDRE", "lea.fictif")

    reponse = _completer(par_nom, i_lea, "fichier:sha256:" + "0" * 64, MARC)

    assert _code_refus(reponse) == CODE_NON_ASSIGNEE


def test_admin_termine_l_intervention_d_un_autre(par_nom, deposer_photo_test):
    i_lea = _en_route(par_nom, "L-COMPLETION-ADMIN", "lea.fictif")
    _sur_site_puis_depart(par_nom, i_lea, "lea.fictif")

    accuse = _resultat(_completer(par_nom, i_lea, deposer_photo_test(par_nom), ADMIN))

    assert accuse["statut"] == "completed_pending_review"


# =========================================================================================
# 6. m4_deposer_fichier et m4_etat_fichier : aucune intervention portée, identité confirmée
# =========================================================================================
def _depot(par_nom, identite_appelante=None):
    import base64
    import hashlib

    contenu = b"\x89PNG\r\n\x1a\n" + b"fictif-t1-4-k"
    return _appeler(par_nom, "m4_deposer_fichier", {
        "empreinte_sha256": hashlib.sha256(contenu).hexdigest(), "taille_octets": len(contenu),
        "type_mime": "image/png", "index_bloc": 0, "nombre_blocs": 1,
        "bloc_base64": base64.b64encode(contenu).decode("ascii"),
    }, identite_appelante)


def test_le_depot_de_fichier_ne_porte_aucune_intervention_donc_aucune_assignation_a_controler(par_nom):
    """Un fichier est adressé par son contenu : rien à comparer à une assignation. Limite documentée
    (ROLES.md) : la preuve n'est rattachée à une intervention qu'à la complétion."""
    dep = _resultat(_depot(par_nom, MARC))  # aucune intervention nommée nulle part : aucun refus d'assignation

    assert dep["complet"] is True and dep["reference"].startswith("fichier:sha256:")


def test_le_depot_et_l_etat_d_un_fichier_exigent_une_identite_confirmee_en_base(par_nom):
    with stockage.transaction() as cnx:
        identite.activer(cnx, "marc.fictif", False)
    empreinte = "ab" * 32

    assert _code_refus(_depot(par_nom, MARC)) == CODE_IDENTITE_INVALIDE
    etat_marc = _appeler(par_nom, "m4_etat_fichier", {"empreinte_sha256": empreinte}, MARC)
    assert _code_refus(etat_marc) == CODE_IDENTITE_INVALIDE
    # Une personne active, elle, passe : l'état d'un fichier inconnu se lit sans refus.
    assert _resultat(_appeler(par_nom, "m4_etat_fichier", {"empreinte_sha256": empreinte}, LEA))["existe"] is False


# =========================================================================================
# 7. m4_statut_intervention et m4_lister_interventions : l'employé ne voit que les siennes
# =========================================================================================
def test_liste_de_l_employe_limitee_a_ses_interventions_celle_de_l_admin_et_de_l_agent_complete(par_nom):
    i_marc = _planifier(par_nom, "L-LISTE-MARC", techniciens=("marc.fictif",))
    i_lea = _planifier(par_nom, "L-LISTE-LEA", techniciens=("lea.fictif",))
    i_personne = _planifier(par_nom, "L-LISTE-PERSONNE", fenetres=())

    assert _ids(_liste(par_nom, MARC)) == {i_marc}
    assert _ids(_liste(par_nom, LEA)) == {i_lea}
    assert _ids(_liste(par_nom, ADMIN)) == {i_marc, i_lea, i_personne}
    assert _ids(_liste(par_nom, None)) == {i_marc, i_lea, i_personne}


def test_le_filtre_par_statut_s_applique_apres_celui_de_la_personne(par_nom):
    i_marc = _planifier(par_nom, "L-LISTE-STATUT-MARC", techniciens=("marc.fictif",))
    _planifier(par_nom, "L-LISTE-STATUT-LEA", techniciens=("lea.fictif",))
    _report(par_nom, i_marc)

    assert _ids(_liste(par_nom, MARC, statut="reportee")) == {i_marc}
    assert _liste(par_nom, MARC, statut="planifiee") == []
    assert _liste(par_nom, LEA, statut="reportee") == []


def test_un_employe_sans_intervention_recoit_une_liste_vide_pas_une_erreur(par_nom):
    _planifier(par_nom, "L-LISTE-AUTRE", techniciens=("lea.fictif",))

    assert _liste(par_nom, MARC) == []


def test_statut_de_l_intervention_d_un_collegue_est_indiscernable_d_une_intervention_inconnue(par_nom):
    i_marc = _planifier(par_nom, "L-STATUT-MARC", techniciens=("marc.fictif",))
    i_lea = _planifier(par_nom, "L-STATUT-LEA", techniciens=("lea.fictif",))

    sien = _appeler(par_nom, "m4_statut_intervention", {"intervention_id": i_marc}, MARC)
    de_l_autre = _appeler(par_nom, "m4_statut_intervention", {"intervention_id": i_lea}, MARC)
    inconnue = _appeler(par_nom, "m4_statut_intervention", {"intervention_id": "intervention-inconnue"}, MARC)

    assert sien["resultat"] == {"intervention_id": i_marc, "statut": "planifiee"}
    assert de_l_autre["resultat"] == {"intervention_id": i_lea, "statut": None}
    assert inconnue["resultat"] == {"intervention_id": "intervention-inconnue", "statut": None}
    # Admin et agent voient le vrai statut de toutes.
    for appelant in (ADMIN, None):
        assert _appeler(par_nom, "m4_statut_intervention", {"intervention_id": i_lea}, appelant)["resultat"] == {
            "intervention_id": i_lea, "statut": "planifiee"}


# =========================================================================================
# 8. Identité invalide : fail-closed, jamais crue sur parole
# =========================================================================================
def _desactiver(cnx):
    identite.activer(cnx, "marc.fictif", False)


def _retirer_role(cnx):
    identite.retirer_role(cnx, "marc.fictif", "employee")


@pytest.mark.parametrize(("perturbation", "appelante"), [
    pytest.param(_desactiver, MARC, id="personne_desactivee"),
    pytest.param(_retirer_role, MARC, id="role_retire"),
    pytest.param(None, contexte.IdentiteAppelante("fantome.fictif", "employee"), id="personne_inconnue"),
    # Le jeton déclare `admin` mais la personne ne porte que `employee` : identité périmée ou falsifiée.
    pytest.param(None, contexte.IdentiteAppelante("marc.fictif", "admin"), id="role_non_porte"),
    # Un rôle qui existe, que la personne porte, mais qui n'a aucune portée sur le terrain M4.
    pytest.param(None, contexte.IdentiteAppelante("vendeur.fictif", "seller"), id="role_sans_portee_m4"),
])
def test_identite_non_confirmee_est_refusee_par_chaque_outil_d_ecriture_et_de_lecture(par_nom, perturbation, appelante):
    i_id = _planifier(par_nom, "L-IDENTITE", techniciens=("marc.fictif",))
    if perturbation is not None:
        with stockage.transaction() as cnx:
            perturbation(cnx)
    avant = _maillons()

    refus = [
        _route(par_nom, i_id, "marc.fictif", appelante),
        _report(par_nom, i_id, appelante),
        _ecart(par_nom, i_id, appelante),
        _pointer(par_nom, i_id, "marc.fictif", identite_appelante=appelante),
        _consentement(par_nom, "marc.fictif", "retire", appelante),
    ]
    for reponse in refus:
        assert _code_refus(reponse) == CODE_IDENTITE_INVALIDE
    # Les lectures rendent une liste : le refus est une erreur métier, pas une liste vide qui le masquerait.
    for nom, arguments in (("m4_lister_interventions", {}), ("m4_statut_intervention", {"intervention_id": i_id})):
        reponse = _appeler(par_nom, nom, arguments, appelante)
        assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
        assert CODE_IDENTITE_INVALIDE in reponse["details"]

    assert _maillons() == avant


def test_identite_d_appareil_sans_transaction_est_refusee_fermee():
    """Hors transaction (registre en mémoire, aucune base jointe), l'identité n'est pas vérifiable : elle
    n'est pas crue sur parole."""
    par_nom = {o.nom: o for o in outils(registre_m4.Registre())}

    with contexte.appele_par_appareil(MARC):
        reponse = par_nom["m4_demarrer_route"].fonction(
            intervention_id="I1", technicien_id="marc.fictif", horodatage="2025-06-02T07:30:00+00:00")

    assert reponse["accepte"] is False and reponse["verdict"]["code"] == CODE_IDENTITE_INVALIDE


def test_les_arguments_ne_peuvent_pas_se_donner_une_identite(par_nom):
    """`technicien_id` est un argument comme un autre : l'identité vient de `identite_appelante()`. Sans
    identité d'appareil, l'argument garde son sens d'avant (agent) ; avec, il est comparé, pas cru."""
    i_marc = _planifier(par_nom, "L-ARGUMENT", techniciens=("marc.fictif",))

    # Léa se présente avec SON jeton mais écrit « marc.fictif » : l'identifiant fourni n'est pas le sien.
    assert _code_refus(_route(par_nom, i_marc, "marc.fictif", LEA)) == CODE_IDENTITE_FOURNIE
    # Sous son vrai identifiant, l'intervention de Marc n'est pas la sienne.
    assert _code_refus(_route(par_nom, i_marc, "lea.fictif", LEA)) == CODE_NON_ASSIGNEE
    assert _statut(par_nom, i_marc) == "planifiee"


# =========================================================================================
# 9. Consentement GPS : l'employé donne et retire SON consentement, jamais celui d'un autre
# =========================================================================================
def _historique(technicien_id):
    with stockage.transaction():
        return consentement.historique_consentement(
            registre_m4.Registre(stockage.maillons("m04-field-ops", "principal")), technicien_id)


def _actif(technicien_id):
    with stockage.transaction():
        return consentement.consentement_actif(
            registre_m4.Registre(stockage.maillons("m04-field-ops", "principal")), technicien_id)


def test_employe_donne_puis_retire_son_propre_consentement(par_nom):
    assert _actif("marc.fictif") is False  # rien avant : fail-closed

    donne = _resultat(_consentement(par_nom, "marc.fictif", "donne", MARC))
    assert donne["actif"] is True and _actif("marc.fictif") is True

    retire = _resultat(_consentement(par_nom, "marc.fictif", "retire", MARC))
    assert retire["actif"] is False and _actif("marc.fictif") is False
    assert [m["action"] for m in _historique("marc.fictif")] == ["donne", "retire"]  # les deux, jamais écrasés


def test_employe_ne_donne_ni_ne_retire_le_consentement_d_un_collegue(par_nom):
    _resultat(_consentement(par_nom, "lea.fictif", "donne"))  # consigné par l'agent
    avant = _maillons()

    for action in ("retire", "donne"):
        reponse = _consentement(par_nom, "lea.fictif", action, MARC)
        assert _code_refus(reponse) == CODE_IDENTITE_FOURNIE
        assert "technicien_id" in reponse["resultat"]["verdict"]["detail"]

    assert _maillons() == avant
    assert _actif("lea.fictif") is True, "le consentement de la collègue n'a pas bougé"


def test_le_retrait_de_l_employe_prend_effet_tout_de_suite_le_pointage_passe_en_mode_manuel(par_nom):
    i_id = _en_route(par_nom, "L-RETRAIT-IMMEDIAT", "marc.fictif")
    _resultat(_consentement(par_nom, "marc.fictif", "retire", MARC, horodatage="2025-06-02T08:00:00+00:00"))

    accuse = _resultat(_pointer(par_nom, i_id, "marc.fictif", identite_appelante=MARC))

    assert accuse["mode_pointage"] == "manuel"  # le fix fourni est IGNORÉ, le pointage n'est pas rejeté
    with stockage.transaction() as cnx:
        assert cles_chiffrement.lire(cnx, "m04-field-ops/gps", "marc.fictif") is None, "aucun fix, aucune clé"


def test_le_retrait_d_un_appareil_porte_l_heure_de_reception_du_serveur_pas_celle_de_l_appareil(par_nom):
    recu = dt.datetime(2025, 6, 2, 13, 45, 0, tzinfo=dt.UTC)
    _resultat(_consentement(par_nom, "marc.fictif", "donne"))

    accuse = _resultat(_appeler(par_nom, "m4_definir_consentement_gps", {
        "technicien_id": "marc.fictif", "action": "retire",
        "horodatage": HORLOGE_APPAREIL_DEREGLEE.isoformat(),  # ignoré pendant un appel d'appareil
        "version_politique": VERSION_POLITIQUE, "preuve": PREUVE,
    }, MARC, recu_le=recu))

    assert accuse["horodatage"] == recu.isoformat()
    assert _historique("marc.fictif")[-1]["horodatage"] == recu.isoformat()


def test_hors_appel_d_appareil_le_consentement_garde_son_horodatage_fourni(par_nom):
    accuse = _resultat(_consentement(par_nom, "marc.fictif", "donne", None, horodatage="2025-06-02T06:30:00+00:00"))

    assert accuse["horodatage"] == "2025-06-02T06:30:00+00:00"


def test_admin_consigne_le_consentement_ou_le_retrait_d_un_technicien(par_nom):
    """§4 : « l'employé peut retirer son consentement via l'app employé OU PAR ÉCRIT » — l'admin consigne
    l'écrit."""
    _resultat(_consentement(par_nom, "lea.fictif", "donne", ADMIN))
    assert _actif("lea.fictif") is True
    _resultat(_consentement(par_nom, "lea.fictif", "retire", ADMIN))
    assert _actif("lea.fictif") is False


# =========================================================================================
# 10. m4_lire_position_gps : le journal d'accès nomme la personne authentifiée
# =========================================================================================
def _ligne_id_de_pointage(par_nom, i_id, technicien_id):
    return _resultat(_pointer(par_nom, i_id, technicien_id))["ligne_id"]


def _lire_position(par_nom, ligne_id, accede_par, identite_appelante=None):
    return _appeler(par_nom, "m4_lire_position_gps", {
        "ligne_id": ligne_id, "accede_par": accede_par, "horodatage": "2025-06-02T12:00:00+00:00",
    }, identite_appelante)


def test_l_admin_lit_une_position_sous_son_propre_nom_et_l_acces_est_journalise(par_nom):
    i_id = _en_route(par_nom, "L-GPS-ADMIN", "lea.fictif")
    ligne_id = _ligne_id_de_pointage(par_nom, i_id, "lea.fictif")

    lecture = _resultat(_lire_position(par_nom, ligne_id, "admin.fictif", ADMIN))

    assert lecture == FIX_GPS
    acces_journalises = [m for m in _maillons() if m["type_entree"] == "acces_position_gps"]
    assert [m["accede_par"] for m in acces_journalises] == ["admin.fictif"]


def test_l_admin_ne_peut_pas_faire_journaliser_l_acces_sous_le_nom_d_un_autre(par_nom):
    i_id = _en_route(par_nom, "L-GPS-USURPE", "lea.fictif")
    ligne_id = _ligne_id_de_pointage(par_nom, i_id, "lea.fictif")
    avant = _maillons()

    reponse = _lire_position(par_nom, ligne_id, "marc.fictif", ADMIN)

    assert _code_refus(reponse) == CODE_IDENTITE_FOURNIE
    assert "accede_par" in reponse["resultat"]["verdict"]["detail"]
    assert _maillons() == avant, "ni position rendue, ni accès journalisé sous un faux nom"


def test_sans_identite_d_appareil_accede_par_reste_celui_de_l_appelant(par_nom):
    i_id = _en_route(par_nom, "L-GPS-AGENT", "lea.fictif")
    ligne_id = _ligne_id_de_pointage(par_nom, i_id, "lea.fictif")

    lecture = _resultat(_lire_position(par_nom, ligne_id, "superviseur-agent-fictif", None))

    assert lecture == FIX_GPS
    assert [m["accede_par"] for m in _maillons() if m["type_entree"] == "acces_position_gps"] == [
        "superviseur-agent-fictif"]


def test_un_employe_ne_lit_aucune_position_le_core_le_refuse_avant_meme_l_outil():
    """Portée d'outil (T1.4-j) : `m4_lire_position_gps` n'est pas dans `employee`."""
    tous = {o.nom: o for o in outils(registre_m4.Registre())}
    assert tous["m4_lire_position_gps"].roles_appareil == frozenset({"admin"})
    assert tous["m4_definir_consentement_gps"].roles_appareil == frozenset({"employee", "admin"})


# =========================================================================================
# 11. Ce qui n'a pas changé
# =========================================================================================
def test_l_ordre_du_registre_reste_valide_apres_assignation_et_appels_d_appareil(par_nom):
    i_id = _en_route(par_nom, "L-CHAINE", "marc.fictif")
    _resultat(_pointer(par_nom, i_id, "marc.fictif", identite_appelante=MARC))

    with stockage.transaction():
        registre = registre_m4.Registre(stockage.maillons("m04-field-ops", "principal"))
        assert registre.valider_chaine() is True
    assert pointage.TYPE_POINTAGE in {m["type_entree"] for m in _maillons()}
