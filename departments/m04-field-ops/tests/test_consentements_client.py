"""PLAN T1.5-d : « Terminer » recueille, auprès du client, son consentement à une demande d'avis.

L'employé le recueille dans l'app ; `m4_completer_intervention` le prend TEL QU'ENVOYÉ (il porte la
parole du client, comme `consentement_marketing` depuis T1.2-f), le porte dans le WCT et dit qui l'a
recueilli et quand, par le SERVEUR : la personne du jeton (confirmée en base) et l'heure de réception,
jamais un argument ni l'horloge du téléphone. Un agent ne peut toujours rien affirmer à la place du client.

Les tests passent par les VRAIS outils (`m4_field_ops.outils.outils()`, registre durable sur une base SQLite
migrée, `executer_atomique`, comme en production), avec de vraies personnes (`opsys.identite`). Chaque refus
est nommé et prouve que RIEN n'a été écrit ni publié. Données fictives (AGENTS.md).
"""

from __future__ import annotations

import contextlib
import datetime as dt

import pytest
from m4_field_ops import cedule, etats, outbox
from m4_field_ops import registre as registre_m4
from m4_field_ops.outils import outils
from sqlalchemy import func, select

from opsys import contexte, identite, stockage
from opsys.evenements import schemas
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
SEL = "sel-t1-5-d-fictif"
VILLE = "Montreal"
FIX_GPS = {"latitude": 45.5088, "longitude": -73.5878}
ATTESTATION = {"fictif": True, "appareil_id": "APP-T1-5-D-FICTIF"}
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}
VERSION_TEXTE = "consentement-client-fr-CA-v1-test"
HORLOGE_APPAREIL_DEREGLEE = dt.datetime(2000, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
RECU_LE = dt.datetime(2025, 6, 2, 11, 35, 5, tzinfo=dt.UTC)

MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")

PREUVE = ("consentement_recueilli_par", "consentement_recueilli_le", "consentement_version_texte")


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def par_nom(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
    return {o.nom: o for o in outils()}


@contextlib.contextmanager
def _appareil(identite_appelante, *, avec_horloges=True):
    """Ce que `Capacites.appeler` pose pour un appel d'appareil : l'identité authentifiée ET les deux
    horloges. `avec_horloges=False` : une identité sans heure de réception (jamais le cas réel)."""
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        if avec_horloges:
            pile.enter_context(contexte.receptionne_de(contexte.HorodatageAppareil(
                appareil="tel-fictif-t1-5-d", horodatage_appareil=HORLOGE_APPAREIL_DEREGLEE, recu_le=RECU_LE)))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=None, **options):
    with _appareil(identite_appelante, **options):
        return executer_atomique(par_nom[nom], arguments)


def _resultat(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _code_refus(reponse):
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _maillons():
    with stockage.transaction():
        return registre_m4.Registre(stockage.maillons("m04-field-ops", "principal")).lire()


def _compte_sortants():
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m4.travaux_termines")).scalar_one()


def _charge_publiee():
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m4.travaux_termines")).mappings().one()
    return dict(ligne), codec.decoder(ligne["charge"])


def _intervention_sur_site(par_nom, lead_id="L-T1-5-D") -> str:
    """Une intervention cédulée pour Marc, terminée sur place (arrivée et départ pointés)."""
    contrat = {"lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale",
               "ville": VILLE, "canal": "telephone", "contact": {"nom": "Client fictif", "telephone": "0102030405"},
               "urgence_declaree": False}
    marqueur = {"readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
                "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32}
    plan = executer_atomique(par_nom["m4_planifier_intervention"], {
        "contrat": contrat, "marqueur": marqueur, "horodatage": "2025-06-02T06:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": ["marc.fictif"], "fenetres_disponibles": [FENETRE]})
    assert plan["ok"] is True, plan
    i_id = plan["resultat"]["intervention_id"]
    assert _resultat(executer_atomique(par_nom["m4_definir_consentement_gps"], {
        "technicien_id": "marc.fictif", "action": "donne", "horodatage": "2025-06-02T06:30:00+00:00",
        "version_politique": "POLITIQUE-geolocalisation-v1-test",
        "preuve": {"fictif": True, "reference": "consentement-t1-5-d-fictif"}}))
    assert _resultat(executer_atomique(par_nom["m4_demarrer_route"], {
        "intervention_id": i_id, "technicien_id": "marc.fictif", "horodatage": "2025-06-02T07:30:00+00:00"}))
    referentiel = {cedule.tokeniser_ville(SEL, VILLE): {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}
    for action, horodatage in (("arrivee", "2025-06-02T09:00:00+00:00"), ("depart", "2025-06-02T11:30:00+00:00")):
        assert _resultat(executer_atomique(par_nom["m4_pointer"], {
            "intervention_id": i_id, "technicien_id": "marc.fictif", "action": action, "horodatage": horodatage,
            "fix_gps": FIX_GPS, "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": referentiel, "ville": VILLE, "sel": SEL}))
    return i_id


def _terminer(par_nom, i_id, photo, identite_appelante, extra=None, **options):
    return _appeler(par_nom, "m4_completer_intervention", {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": {"checklist_complete": True, "photos_apres": [photo], "notes": "RAS.",
                               "signature": None},
        **(extra or {}),
    }, identite_appelante, **options)


def _wct(i_id):
    return next(m[outbox.CLE_WCT] for m in _maillons() if m.get("type_entree") == etats.TYPE_TRANSITION
                and m.get("intervention_id") == i_id and outbox.CLE_WCT in m)


# =========================================================================================
# 1. Pendant un appel d'appareil : le consentement est porté, avec la personne et l'heure du serveur
# =========================================================================================
def test_l_employe_termine_avec_le_consentement_du_client_a_une_demande_d_avis(par_nom, deposer_photo_test):
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)

    reponse = _terminer(par_nom, i_id, photo, MARC, {
        "consentement_demande_avis": True, "consentement_version_texte": VERSION_TEXTE})

    accuse = _resultat(reponse)
    wct = _wct(i_id)
    assert wct["consentement_demande_avis"] is True
    assert wct["consentement_version_texte"] == VERSION_TEXTE
    # La personne : celle du jeton, confirmée en base. L'heure : celle de RÉCEPTION du serveur, ni l'horloge
    # déréglée du téléphone (an 2000) ni l'`horodatage` fourni dans les arguments.
    assert wct["consentement_recueilli_par"] == "marc.fictif"
    assert wct["consentement_recueilli_le"] == RECU_LE.isoformat()
    assert wct["consentement_recueilli_le"] != "2025-06-02T11:35:00+00:00"
    # Le consentement à la demande d'avis n'est pas celui des photos : rien n'est déduit.
    assert "consentement_marketing" not in wct
    assert wct["wct_id"] == accuse["wct_id"]
    with stockage.transaction():
        ok, message = outbox.verifier_invariants_outbox(
            registre_m4.Registre(stockage.maillons("m04-field-ops", "principal")))
    assert ok, message


def test_le_consentement_est_publie_valide_sur_le_bus_avec_sa_preuve(par_nom, deposer_photo_test):
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)

    accuse = _resultat(_terminer(par_nom, i_id, photo, MARC, {
        "consentement_demande_avis": True, "consentement_marketing": True,
        "consentement_version_texte": VERSION_TEXTE}))

    ligne, charge = _charge_publiee()
    assert ligne["evenement_id"] == accuse["wct_id"]
    assert charge["consentement_demande_avis"] is True and charge["consentement_marketing"] is True
    assert (charge["consentement_recueilli_par"], charge["consentement_recueilli_le"],
            charge["consentement_version_texte"]) == ("marc.fictif", RECU_LE.isoformat(), VERSION_TEXTE)
    assert schemas.erreurs_charge("m4.travaux_termines", charge) == []


def test_l_admin_qui_termine_pour_un_employe_est_celui_qui_a_recueilli_le_consentement(par_nom, deposer_photo_test):
    """La personne posée est celle qui APPELLE (jeton), pas le technicien de la cédule."""
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)

    _resultat(_terminer(par_nom, i_id, photo, ADMIN, {
        "consentement_demande_avis": True, "consentement_version_texte": VERSION_TEXTE}))

    wct = _wct(i_id)
    assert wct["consentement_recueilli_par"] == "admin.fictif"
    assert wct["technicien_id"] == "marc.fictif"  # le technicien du pointage reste ce qu'il était


def test_un_consentement_refuse_par_le_client_se_prouve_aussi(par_nom, deposer_photo_test):
    """`false` est un fait (le client a refusé) : porté tel quel, avec sa preuve, jamais transformé en absence."""
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)

    _resultat(_terminer(par_nom, i_id, photo, MARC, {
        "consentement_demande_avis": False, "consentement_version_texte": VERSION_TEXTE}))

    wct = _wct(i_id)
    assert wct["consentement_demande_avis"] is False
    assert wct["consentement_recueilli_par"] == "marc.fictif"


def test_sans_consentement_le_wct_ne_porte_ni_consentement_ni_preuve(par_nom, deposer_photo_test):
    """Comportement d'avant : un « Terminer » sans consentement n'invente ni oui, ni non, ni personne."""
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)

    _resultat(_terminer(par_nom, i_id, photo, MARC))

    wct = _wct(i_id)
    for cle in ("consentement_demande_avis", "consentement_marketing", *PREUVE):
        assert cle not in wct
    _, charge = _charge_publiee()
    assert not any(cle in charge for cle in ("consentement_demande_avis", "consentement_marketing", *PREUVE))


def test_la_satisfaction_seule_ne_demande_aucune_preuve_de_consentement(par_nom, deposer_photo_test):
    """`client_satisfait` n'est pas un consentement : envoyé seul, il n'exige rien et ne pose aucune preuve."""
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)

    _resultat(_terminer(par_nom, i_id, photo, MARC, {"client_satisfait": True}))

    wct = _wct(i_id)
    assert wct["client_satisfait"] is True
    assert not any(cle in wct for cle in PREUVE)


# =========================================================================================
# 2. Refus nommés : rien n'est écrit ni publié
# =========================================================================================
@pytest.mark.parametrize("consentement", ["consentement_demande_avis", "consentement_marketing"])
def test_un_consentement_sans_version_du_texte_est_refuse(par_nom, deposer_photo_test, consentement):
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)
    avant = _maillons()

    reponse = _terminer(par_nom, i_id, photo, MARC, {consentement: True})

    assert _code_refus(reponse) == "REJ-CONSENTEMENT-INVALIDE"
    assert "consentement_version_texte" in reponse["resultat"]["verdict"]["detail"]
    assert _maillons() == avant and _compte_sortants() == 0


@pytest.mark.parametrize("version", ["", "texte avec espaces", "é" * 3, "x" * 65, "a/b"])
def test_une_version_du_texte_mal_formee_est_refusee(par_nom, deposer_photo_test, version):
    """Une étiquette de version, jamais un texte libre ni une donnée personnelle : 1 à 64 caractères sûrs."""
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)
    avant = _maillons()

    reponse = _terminer(par_nom, i_id, photo, MARC, {
        "consentement_demande_avis": True, "consentement_version_texte": version})

    assert _code_refus(reponse) == "REJ-CONSENTEMENT-INVALIDE"
    assert _maillons() == avant and _compte_sortants() == 0


def test_une_version_sans_aucun_consentement_est_refusee(par_nom, deposer_photo_test):
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)
    avant = _maillons()

    reponse = _terminer(par_nom, i_id, photo, MARC, {"consentement_version_texte": VERSION_TEXTE})

    assert _code_refus(reponse) == "REJ-CONSENTEMENT-INVALIDE"
    assert "rien à prouver" in reponse["resultat"]["verdict"]["detail"]
    assert _maillons() == avant and _compte_sortants() == 0


def test_un_consentement_sans_personne_authentifiee_est_refuse(par_nom, deposer_photo_test):
    """Une heure de réception sans identité (jamais le cas réel : le core pose les deux) : personne
    n'a recueilli ce consentement, donc il n'existe pas. Fail-closed."""
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)
    avant = _maillons()

    reponse = _terminer(par_nom, i_id, photo, None, {
        "consentement_demande_avis": True, "consentement_version_texte": VERSION_TEXTE})

    assert _code_refus(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert "personne authentifiée" in reponse["resultat"]["verdict"]["detail"]
    assert _maillons() == avant and _compte_sortants() == 0


def test_l_identite_d_une_personne_devenue_inactive_ne_recueille_plus_de_consentement(par_nom, deposer_photo_test):
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)
    with stockage.transaction() as cnx:
        identite.activer(cnx, "marc.fictif", False)
    avant = _maillons()

    reponse = _terminer(par_nom, i_id, photo, MARC, {
        "consentement_demande_avis": True, "consentement_version_texte": VERSION_TEXTE})

    assert _code_refus(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _maillons() == avant and _compte_sortants() == 0


@pytest.mark.parametrize("extra", [
    {"consentement_demande_avis": True},
    {"consentement_demande_avis": False},
    {"consentement_version_texte": VERSION_TEXTE},
    {"consentement_demande_avis": True, "consentement_version_texte": VERSION_TEXTE},
    {"consentement_marketing": True, "consentement_version_texte": VERSION_TEXTE},
])
def test_un_agent_ne_peut_affirmer_aucun_consentement_a_la_place_du_client(par_nom, deposer_photo_test, extra):
    """Hors d'un appel d'appareil (agent, console) : leur seule PRÉSENCE est un refus nommé, même avec une
    version du texte. Le consentement demande la parole du client, recueillie par une personne."""
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)
    avant = _maillons()

    reponse = _terminer(par_nom, i_id, photo, None, extra, avec_horloges=False)

    assert _code_refus(reponse) == "REJ-CHAMPS-CLIENT-HORS-APPAREIL"
    assert _maillons() == avant and _compte_sortants() == 0
    assert not any(cle in _wct_ou_vide(i_id) for cle in ("consentement_demande_avis", *PREUVE))


def _wct_ou_vide(i_id):
    try:
        return _wct(i_id)
    except StopIteration:
        return {}


@pytest.mark.parametrize("cle", PREUVE[:2])
def test_l_appareil_ne_peut_pas_fournir_lui_meme_qui_ni_quand(par_nom, deposer_photo_test, cle):
    """La personne et l'heure sont posées par le serveur : le schéma de l'outil ne les connaît pas
    (`additionalProperties: false`), un appareil ne peut pas écrire « recueilli par Nathan »."""
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)
    avant = _maillons()

    reponse = _terminer(par_nom, i_id, photo, MARC, {
        "consentement_demande_avis": True, "consentement_version_texte": VERSION_TEXTE,
        cle: "nathan" if cle.endswith("_par") else "2025-06-02T11:00:00+00:00"})

    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", reponse
    assert _maillons() == avant and _compte_sortants() == 0


def test_un_consentement_qui_n_est_pas_un_booleen_est_refuse_par_le_schema(par_nom, deposer_photo_test):
    i_id = _intervention_sur_site(par_nom)
    photo = deposer_photo_test(par_nom)

    reponse = _terminer(par_nom, i_id, photo, MARC, {
        "consentement_demande_avis": "oui", "consentement_version_texte": VERSION_TEXTE})

    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", reponse
