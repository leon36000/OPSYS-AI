"""PLAN T4.27-a : `m4_lire_retards_incidents`, sur les VRAIS outils, une base SQLite migrée et de vraies personnes.

M4 ne tient aucun calendrier : le retard sur la cédule ne se mesure pas. Ce que M4 enregistre déjà, c'est les REPORTS
(`m4_signaler_report`) et les demandes de revue ouvertes (`m4_creer_demande_ecart`, anomalies de pointage) : l'admin les
lit, avec leur âge, sans rien écrire.

Ce que ce fichier prouve, par les outils qui écrivent ces faits (l'employé signale, l'admin reporte) :
  * le relevé montre ce que les gestes ont écrit, et cesse de le montrer quand l'intervention n'est plus reportée ou que
    la demande est résolue ;
  * l'âge vient de la référence de l'appelant ; « bloquée » dès 24 h comme le digest, dont il donne les mêmes demandes ;
  * l'employé, le vendeur et une identité non confirmée sont refusés dans le code ; un agent peut lire ;
  * la lecture n'écrit rien ; la limite d'une réponse d'appareil est tenue ;
  * PLAN T4.27-a2 : l'heure d'un report et d'une demande d'écart est celle de RÉCEPTION du serveur (comme le punch, le
    départ et la complétion) : l'horloge de l'appareil ne fausse plus l'âge. Ici, chaque geste de l'app est fait avec
    une heure écrite absurde et une heure de réception connue : tout le relevé suit la seconde. Le détail (heure de
    l'appareil gardée à part, rejeu, faits d'avant, origine de chaque ligne) est dans `test_heure_du_serveur_outils.py`
    et `test_heure_du_serveur_rejeu.py`.
Données fictives (`fictif: true`) : personnes, appareils et identifiants portent « fictif ».
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json

import pytest
from m4_field_ops import digest, retards
from m4_field_ops import outils as outils_m4
from m4_field_ops import registre as registre_m4
from m4_field_ops.outils import outils

from opsys import contexte, identite, jetons, politiques, stockage
from opsys.outils import executer_atomique

FICTIF = True
SEL = "sel-t4-27-a-fictif"
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}
REFERENCE = "2025-06-05T09:30:00+00:00"
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
LEA = contexte.IdentiteAppelante(personne="lea.fictif", role="employee")
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")
INCONNUE = contexte.IdentiteAppelante(personne="fantome.fictif", role="admin")


# -- installation -----------------------------------------------------------------------------------
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
        identite.creer_personne(cnx, "lea.fictif", "Léa Fictive", "mot-de-passe-lea-12345", ["employee"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])
    return {o.nom: o for o in outils()}


@contextlib.contextmanager
def _appareil(identite_appelante, recu_le=None):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
            if recu_le is not None:
                pile.enter_context(
                    contexte.receptionne_de(
                        contexte.HorodatageAppareil(
                            appareil="tel-fictif-t4-27-a",
                            horodatage_appareil=dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
                            recu_le=recu_le,
                        )
                    )
                )
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=None, recu_le=None):
    with _appareil(identite_appelante, recu_le):
        return executer_atomique(par_nom[nom], arguments)


def _maillons():
    with stockage.transaction():
        return json.dumps(registre_m4.Registre(stockage.maillons("m04-field-ops", "principal")).lire(), sort_keys=True)


def _contrat(lead_id):
    return {
        "lead_id": lead_id,
        "conversation_id": "C1",
        "type_travaux": "renovation_totale",
        "ville": "Montreal",
        "canal": "telephone",
        "contact": {"nom": "Client fictif", "telephone": "0102030405"},
        "urgence_declaree": False,
    }


def _marqueur(lead_id):
    return {
        "readiness_ok": True,
        "lead_id": lead_id,
        "hash_tete_registre": None,
        "horodatage": "2025-06-01T12:00:00+00:00",
        "empreinte": "ab" * 32,
    }


def _planifier(par_nom, lead_id, technicien) -> str:
    reponse = _appeler(
        par_nom,
        "m4_planifier_intervention",
        {
            "contrat": _contrat(lead_id),
            "marqueur": _marqueur(lead_id),
            "horodatage": "2025-06-02T06:00:00+00:00",
            "sel": SEL,
            "techniciens_disponibles": [technicien],
            "fenetres_disponibles": [FENETRE],
        },
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["intervention_id"]


# L'heure que l'appelant écrit, volontairement absurde : pendant un appel d'appareil, seule l'heure de RÉCEPTION du
# serveur (`recu_le`) fait foi (T4.27-a2). Si elle fuitait dans un âge, ces tests le diraient tout de suite.
HEURE_ECRITE_ABSURDE = "2000-01-01T00:00:00+00:00"


def _reporter(par_nom, intervention_id, motif, recu_le, identite_appelante):
    reponse = _appeler(
        par_nom,
        "m4_signaler_report",
        {"intervention_id": intervention_id, "motif": motif, "horodatage": HEURE_ECRITE_ABSURDE},
        identite_appelante,
        dt.datetime.fromisoformat(recu_le),
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def _ecart(par_nom, intervention_id, recu_le, identite_appelante):
    reponse = _appeler(
        par_nom,
        "m4_creer_demande_ecart",
        {
            "intervention_id": intervention_id,
            "version_prevue": {"duree_minutes": 60, "perimetre": "perimetre prevu", "materiaux": ["m1"]},
            "version_declaree": {"duree_minutes": 90, "perimetre": "PERIMETRE-LIBRE-DU-TERRAIN", "materiaux": ["m2"]},
            "horodatage": HEURE_ECRITE_ABSURDE,
        },
        identite_appelante,
        dt.datetime.fromisoformat(recu_le),
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]["demande_id"]


def _lire(par_nom, reference=REFERENCE, identite_appelante=ADMIN):
    return _appeler(par_nom, "m4_lire_retards_incidents", {"horodatage_reference": reference}, identite_appelante)


def _releve(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _code_refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


@pytest.fixture
def monde(par_nom):
    """Trois interventions planifiées (deux à Marc, une à Léa) : un report du client absent, un report de l'admin, un
    écart déclaré par Marc. Heures de RÉCEPTION du serveur : 2025-06-03 08:00, 2025-06-04 07:00 et 2025-06-04 12:00."""
    a = _planifier(par_nom, "L-A", "marc.fictif")
    b = _planifier(par_nom, "L-B", "marc.fictif")
    c = _planifier(par_nom, "L-C", "lea.fictif")
    _reporter(par_nom, a, "client_absent", "2025-06-03T08:00:00+00:00", MARC)
    _reporter(par_nom, c, "decision_admin", "2025-06-04T07:00:00+00:00", ADMIN)
    demande = _ecart(par_nom, b, "2025-06-04T12:00:00+00:00", MARC)
    return {"a": a, "b": b, "c": c, "demande": demande}


# =========================================================================================
# 1. L'outil : T0, réservé à l'admin, décrit
# =========================================================================================
def test_l_outil_est_de_lecture_t0_reserve_a_l_admin_et_decrit(par_nom):
    outil = par_nom["m4_lire_retards_incidents"]
    assert outil.autonomie.name == "T0" and outil.roles_appareil == frozenset({"admin"})
    assert not politiques.approbation_requise_niveau(outil.niveau_effectif, "ombre")
    assert outil.parametres["required"] == ["horodatage_reference"]
    assert set(outil.parametres["properties"]) == {"horodatage_reference"}
    assert outil.parametres["additionalProperties"] is False
    assert len(outil.description) <= 1024
    for mot in ("REPORTS", "INCIDENTS", "non_mesurable", "jamais « aucun retard »", "Réservé à l'admin", "24 h"):
        assert mot in outil.description, mot


def test_l_outil_est_a_la_fin_de_la_liste(par_nom):
    assert list(par_nom)[-1] == "m4_lire_retards_incidents"


# =========================================================================================
# 2. Le relevé montre ce que les gestes ont écrit
# =========================================================================================
def test_le_releve_montre_les_reports_et_l_incident_ecrits_par_les_gestes_de_l_employe_et_de_l_admin(par_nom, monde):
    releve = _releve(_lire(par_nom))
    assert releve["reference"] == REFERENCE and releve["seuil_blocage_heures"] == 24
    assert releve["reports"]["liste"] == [
        {
            "intervention_id": monde["a"],
            "motif": "client_absent",
            "depuis": "2025-06-03T08:00:00+00:00",
            "origine_heure": "serveur",
            "heures_ecoulees": 49,
        },
        {
            "intervention_id": monde["c"],
            "motif": "decision_admin",
            "depuis": "2025-06-04T07:00:00+00:00",
            "origine_heure": "serveur",
            "heures_ecoulees": 26,
        },
    ]
    assert releve["reports"]["par_motif"] == {"client_absent": 1, "meteo": 0, "decision_admin": 1}
    assert releve["incidents"]["liste"] == [
        {
            "demande_id": monde["demande"],
            "intervention_id": monde["b"],
            "type_demande": "ecart_metier",
            "depuis": "2025-06-04T12:00:00+00:00",
            "origine_heure": "serveur",
            "heures_ecoulees": 21,
            "bloquee": False,
        }
    ]
    assert releve["incidents"]["bloques"] == 0 and releve["retard_sur_cedule"]["statut"] == "non_mesurable"


def test_le_releve_dit_bloquee_des_24_h_et_donne_les_memes_demandes_que_le_digest(par_nom, monde):
    reference = "2025-06-05T12:00:00+00:00"  # 24 h pile après la demande d'écart
    releve = _releve(_lire(par_nom, reference))
    assert releve["incidents"]["liste"][0]["heures_ecoulees"] == 24 and releve["incidents"]["liste"][0]["bloquee"]
    du_digest = _appeler(
        par_nom, "m4_produire_digest", {"date_cible": "2025-06-05", "horodatage_reference": reference}, ADMIN
    )
    bloquees = du_digest["resultat"]["resultat"]["interventions_bloquees_en_revue"]
    assert {ligne["demande_id"] for ligne in bloquees} == {monde["demande"]}
    assert [ligne["heures_ecoulees"] for ligne in bloquees] == [24]
    assert releve["incidents"]["bloques"] == len(bloquees)


def test_les_incidents_du_releve_sont_ceux_de_lister_pending_review(par_nom, monde):
    en_attente = _appeler(par_nom, "m4_lister_pending_review", {}, ADMIN)["resultat"]
    releve = _releve(_lire(par_nom))
    assert {d["demande_id"] for d in en_attente} == {ligne["demande_id"] for ligne in releve["incidents"]["liste"]}
    assert releve["incidents"]["total"] == len(en_attente)


def test_un_report_annule_ou_replanifie_et_une_demande_resolue_sortent_du_releve(par_nom, monde):
    annulation = _appeler(
        par_nom,
        "m4_annuler_intervention",
        {"intervention_id": monde["a"], "horodatage": "2025-06-05T08:00:00+00:00"},
    )
    assert annulation["resultat"]["accepte"] is True
    rejet = _appeler(
        par_nom,
        "m4_resoudre_demande",
        {"demande_id": monde["demande"], "decision": "rejetee", "horodatage": "2025-06-05T08:30:00+00:00"},
        ADMIN,
    )
    assert rejet["ok"] is True and rejet["resultat"]["accepte"] is True, rejet
    releve = _releve(_lire(par_nom))
    assert [ligne["intervention_id"] for ligne in releve["reports"]["liste"]] == [monde["c"]]
    assert releve["incidents"]["total"] == 0 and releve["incidents"]["liste"] == []


def test_un_registre_sans_report_ni_incident_donne_des_listes_vides_et_reste_non_mesurable(par_nom):
    _planifier(par_nom, "L-A", "marc.fictif")
    releve = _releve(_lire(par_nom))
    assert releve["reports"]["total"] == 0 and releve["incidents"]["total"] == 0
    assert releve["retard_sur_cedule"]["statut"] == "non_mesurable"
    assert "aucun retard" not in json.dumps(releve, ensure_ascii=False).lower()


# =========================================================================================
# 3. Lecture pure et limite documentée
# =========================================================================================
def test_la_lecture_n_ecrit_rien_deux_lectures_donnent_le_meme_releve(par_nom, monde):
    avant = _maillons()
    un = _releve(_lire(par_nom))
    deux = _releve(_lire(par_nom))
    assert un == deux and _maillons() == avant


def test_le_releve_ne_porte_aucun_texte_libre_du_terrain_ni_contact(par_nom, monde):
    texte = json.dumps(_releve(_lire(par_nom)), ensure_ascii=False)
    for interdit in (
        "PERIMETRE-LIBRE-DU-TERRAIN",
        "perimetre",
        "materiaux",
        "Client fictif",
        "0102030405",
        "Montreal",
        "marc.fictif",
        "lea.fictif",
        "technicien",
        "prix",
        "montant",
    ):
        assert interdit not in texte, interdit


def test_l_heure_d_un_report_et_d_une_demande_d_ecart_est_celle_de_reception_du_serveur(par_nom):
    """PLAN T4.27-a2 (levée de la limite de T4.27-a) : comme le punch, le départ et la complétion, l'heure de RÉCEPTION
    du serveur fait foi pour un report et une demande d'écart reçus d'un appareil ; l'heure écrite par l'appelant ne
    date rien, et l'âge lu ne dépend plus de l'horloge de l'appareil."""
    a = _planifier(par_nom, "L-A", "marc.fictif")
    b = _planifier(par_nom, "L-B", "marc.fictif")
    recu_le = dt.datetime(2025, 6, 5, 9, 0, tzinfo=dt.UTC)
    reponse = _appeler(
        par_nom,
        "m4_signaler_report",
        {"intervention_id": a, "motif": "meteo", "horodatage": "2025-06-03T08:00:00+00:00"},
        MARC,
        recu_le,
    )
    assert reponse["resultat"]["accepte"] is True
    reponse = _appeler(
        par_nom,
        "m4_creer_demande_ecart",
        {
            "intervention_id": b,
            "version_prevue": {"duree_minutes": 60, "perimetre": "p", "materiaux": []},
            "version_declaree": {"duree_minutes": 90, "perimetre": "p", "materiaux": []},
            "horodatage": "2025-06-03T09:00:00+00:00",
        },
        MARC,
        recu_le,
    )
    assert reponse["resultat"]["accepte"] is True
    releve = _releve(_lire(par_nom))
    assert releve["reports"]["liste"][0]["depuis"] == recu_le.isoformat() != "2025-06-03T08:00:00+00:00"
    assert releve["incidents"]["liste"][0]["depuis"] == recu_le.isoformat() != "2025-06-03T09:00:00+00:00"
    assert releve["reports"]["liste"][0]["origine_heure"] == "serveur"
    assert releve["incidents"]["liste"][0]["origine_heure"] == "serveur"
    assert releve["reports"]["liste"][0]["heures_ecoulees"] == 0  # reçu à 09:00, référence 09:30 : 0 heure pleine


# =========================================================================================
# 4. Refus : identité et rôle
# =========================================================================================
@pytest.mark.parametrize("identite_refusee", [MARC, LEA, VENDEUR, INCONNUE], ids=["marc", "lea", "vendeur", "inconnue"])
def test_ni_l_employe_ni_le_vendeur_ni_une_identite_non_confirmee_ne_lisent_les_retards(
    par_nom, monde, identite_refusee
):
    avant = _maillons()
    assert _code_refus(_lire(par_nom, REFERENCE, identite_refusee)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _maillons() == avant


def test_un_agent_sans_identite_d_appareil_peut_lire(par_nom, monde):
    releve = _releve(_lire(par_nom, REFERENCE, None))
    assert releve["reports"]["total"] == 2 and releve["incidents"]["total"] == 1


@pytest.mark.parametrize("reference", ["", "hier", "2025-06-05", "2025-06-05T09:30:00", "2025-13-05T09:30:00+00:00"])
def test_une_reference_illisible_est_refusee_sans_rien_ecrire(par_nom, monde, reference):
    avant = _maillons()
    assert _code_refus(_lire(par_nom, reference)) == "REJ-HORODATAGE-INVALIDE"
    assert _maillons() == avant


def test_le_socle_refuse_l_argument_absent_un_mauvais_type_et_toute_cle_inconnue(par_nom, monde):
    for arguments in (
        {},
        {"horodatage_reference": 20250605},
        {"horodatage_reference": REFERENCE, "limite": 5},
        {"horodatage_reference": REFERENCE, "personne": "marc.fictif"},
        {"horodatage_reference": REFERENCE, "date_cible": "2025-06-05"},
    ):
        reponse = _appeler(par_nom, "m4_lire_retards_incidents", arguments, ADMIN)
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", arguments


# =========================================================================================
# 5. Les bornes : la limite de chaque liste, la limite d'une réponse d'appareil
# =========================================================================================
def test_la_limite_de_la_reponse_est_celle_de_l_appareil_moins_une_marge():
    assert outils_m4._LIMITE_REPONSE_LECTURE == jetons.LIMITE_SORTIE_DEFAUT - 500
    assert retards.LIMITE_PAR_LISTE == 8


def test_la_limite_par_liste_est_lue_a_l_appel_et_le_reste_est_compte(par_nom, monde, monkeypatch):
    monkeypatch.setattr(retards, "LIMITE_PAR_LISTE", 1)
    releve = _releve(_lire(par_nom))
    assert (releve["reports"]["total"], releve["reports"]["affiches"], releve["reports"]["reste"]) == (2, 1, 1)
    assert releve["reports"]["liste"][0]["intervention_id"] == monde["a"], "le plus ancien d'abord"
    assert "m4_lister_interventions" in releve["reports"]["suite"]
    assert releve["incidents"]["reste"] == 0 and releve["incidents"]["suite"] is None


def test_un_releve_plein_tient_dans_une_reponse_d_appareil(par_nom):
    for numero in range(10):
        identifiant = _planifier(par_nom, f"L-{numero:02d}", "marc.fictif")
        _reporter(par_nom, identifiant, "decision_admin", f"2025-06-03T10:{numero:02d}:00.123456-04:00", ADMIN)
        _ecart(par_nom, identifiant, f"2025-06-03T11:{numero:02d}:00.123456-04:00", MARC)
    reponse = _lire(par_nom, "2099-12-31T23:59:59.999999-04:00")
    assert len(json.dumps(reponse, ensure_ascii=False)) < jetons.LIMITE_SORTIE_DEFAUT
    assert _mesure(reponse) <= outils_m4._LIMITE_REPONSE_LECTURE
    releve = _releve(reponse)
    assert releve["reports"]["affiches"] == releve["incidents"]["affiches"] == 8
    assert releve["reports"]["reste"] == releve["incidents"]["reste"] == 2


def _mesure(reponse):
    return len(json.dumps(reponse, ensure_ascii=False))


def test_un_releve_qui_ne_tient_pas_est_refuse_jamais_tronque(par_nom, monde, monkeypatch):
    monkeypatch.setattr(outils_m4, "_LIMITE_REPONSE_LECTURE", 300)
    refus = _lire(par_nom)
    assert _code_refus(refus) == "REJ-CONTRAT-INVALIDE"
    assert "m4_lister_pending_review" in refus["resultat"]["verdict"]["detail"]
    assert _mesure(refus) < 1000


def test_le_digest_ne_dit_rien_des_reports_ce_que_le_releve_ajoute(par_nom, monde):
    """Le digest ne parle pas des reports : sans ce relevé, aucun outil de M4 ne dit pourquoi un chantier est
    reporté."""
    reponse = _appeler(
        par_nom, "m4_produire_digest", {"date_cible": "2025-06-05", "horodatage_reference": REFERENCE}, ADMIN
    )
    assert "reportee" not in json.dumps(reponse) and "client_absent" not in json.dumps(reponse)
    assert set(digest.CHAMPS_DIGEST) == set(reponse["resultat"]["resultat"])
