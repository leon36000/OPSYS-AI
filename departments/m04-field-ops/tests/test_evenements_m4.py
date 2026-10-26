"""M4 côté bus d'événements (ADR-0009 §3, PLAN T1.2-b et point 4) :

- `m4_completer_intervention` publie `m4.travaux_termines` dans la MÊME transaction que le
  WCT qu'il vient d'écrire (`executer_atomique`, base SQLite temporaire migrée, comme
  `tests/test_evenements.py::test_atomicite_ecriture_et_evenement_annulees_ensemble`) ; une
  complétion refusée (preuves incomplètes) n'en publie aucun.
- `consommateurs()["m6.variance_chantier"]` (`_recevoir_variance_chantier`) fait passer
  l'intervention de `completed_pending_review` à `completed_verified` seulement quand
  `statut_variance == "evaluee"` et `signal_critique is False`, jamais autrement.

Import : comme `test_registre_durable.py`, ce fichier ne touche pas `sys.path` (pythonpath du
`pyproject.toml` racine) et ne monte AUCUNE base pour les fonctions pures ; seuls les tests
`base_durable` migrent une base SQLite temporaire (ADR-0009).
"""

from __future__ import annotations

import contextlib
import datetime as dt

import pytest
from m2_preparation_estimation import marqueur_m2
from m3_estimation.outils import outils as outils_m3
from m3_estimation.outils import registre_production as registre_m3_production
from m4_field_ops import calibration_projection, cedule
from m4_field_ops import outbox as outbox_mod
from m4_field_ops import registre as registre_mod
from m4_field_ops.outbox import CHAMPS_WCT
from m4_field_ops.outils import consommateurs, outils
from sqlalchemy import func, select, update

from opsys import contexte, evenements, identite, stockage
from opsys.departements import charger_departements
from opsys.evenements import schemas
from opsys.outils import executer, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

SEL = "sel-evenements-m4"
VILLE = "Montreal"
FIX_GPS = {"latitude": 45.5088, "longitude": -73.5878}
ATTESTATION = {"fictif": True, "appareil_id": "APP-EVT"}
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}


def _preuves_ok(par_nom, deposer_photo_test):
    """T1.4-e2 : dossier de preuves avec une référence de photo RÉELLE (déposée par le VRAI
    outil `m4_deposer_fichier`), jamais une chaîne inventée."""
    return {
        "checklist_complete": True, "photos_apres": [deposer_photo_test(par_nom)],
        "notes": "RAS.", "signature": None,
    }


def _contrat(lead_id):
    return {
        "lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale",
        "ville": VILLE, "canal": "telephone",
        "contact": {"nom": "Client", "telephone": "0102030405"}, "urgence_declaree": False,
    }


def _contrat_v2(lead_id, service="gouttieres"):
    """LeadQualifie v2 (PLAN T0.13-b) : `schema_version` et `service` remplacent `type_travaux`."""
    return {
        "schema_version": 2, "lead_id": lead_id, "conversation_id": "C1", "service": service,
        "ville": VILLE, "canal": "formulaire",
        "contact": {"nom": "Client", "telephone": "0102030405"}, "urgence_declaree": False,
    }


def _marqueur(lead_id):
    return {
        "readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
        "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32,
    }


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _mener_a_sur_site(par_nom, lead_id, contrat=None, devis_id=None, pointages=None):
    arguments_plan = {
        "contrat": _contrat(lead_id) if contrat is None else contrat, "marqueur": _marqueur(lead_id),
        "horodatage": "2025-06-02T08:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": ["T1"], "fenetres_disponibles": [FENETRE],
    }
    if devis_id is not None:
        arguments_plan["devis_id"] = devis_id
    plan = executer_atomique(par_nom["m4_planifier_intervention"], arguments_plan)
    assert plan["ok"] is True, plan
    i_id = plan["resultat"]["intervention_id"]

    # PLAN T4.2 (POLITIQUE-geolocalisation.md §4) : m4_pointer n'enregistre un fix GPS QUE si le
    # consentement est actif — précondition nécessaire avant tout pointage à fix réel ci-dessous.
    consentement = executer_atomique(par_nom["m4_definir_consentement_gps"], {
        "technicien_id": "T1", "action": "donne", "horodatage": "2025-06-02T07:00:00+00:00",
        "version_politique": "POLITIQUE-geolocalisation-v1-test",
        "preuve": {"fictif": True, "reference": "consentement-test"},
    })
    assert consentement["ok"] is True and consentement["resultat"]["accepte"] is True, consentement

    depart = executer_atomique(par_nom["m4_demarrer_route"], {
        "intervention_id": i_id, "technicien_id": "T1", "horodatage": "2025-06-02T08:30:00+00:00",
    })
    assert depart["ok"] is True and depart["resultat"]["accepte"] is True, depart

    token = cedule.tokeniser_ville(SEL, VILLE)
    referentiel = {token: {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}
    pointages = pointages or (("arrivee", "2025-06-02T09:00:00+00:00"), ("depart", "2025-06-02T11:30:00+00:00"))
    for action, horo in pointages:
        r = executer_atomique(par_nom["m4_pointer"], {
            "intervention_id": i_id, "technicien_id": "T1", "action": action, "horodatage": horo,
            "fix_gps": FIX_GPS, "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": referentiel, "ville": VILLE, "sel": SEL,
        })
        assert r["ok"] is True and r["resultat"]["accepte"] is True, r
    return i_id


def _compte_sortants(type_evenement=None):
    requete = select(func.count()).select_from(EVENEMENTS_SORTANTS)
    if type_evenement is not None:
        requete = requete.where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
    with stockage.transaction() as cnx:
        return cnx.execute(requete).scalar_one()


def _charge_publiee(type_evenement):
    with stockage.transaction() as cnx:
        ligne = cnx.execute(
            select(EVENEMENTS_SORTANTS)
            .where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
        ).mappings().one()
    return dict(ligne), codec.decoder(ligne["charge"])


# -- publication dans la même transaction que le WCT (T1.2-b, point 1) -------------------------
def test_completion_acceptee_publie_m4_travaux_termines_dans_la_meme_transaction(base_durable, deposer_photo_test):
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-1")

    assert _compte_sortants("m4.travaux_termines") == 0

    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _preuves_ok(par_nom, deposer_photo_test),
    })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion
    wct_id = completion["resultat"]["resultat"]["wct_id"]

    assert _compte_sortants("m4.travaux_termines") == 1
    ligne, charge = _charge_publiee("m4.travaux_termines")
    assert ligne["evenement_id"] == wct_id, "idempotence par WCT : evenement_id == wct_id"
    assert ligne["producteur"] == "m04-field-ops"
    assert charge["wct_id"] == wct_id
    assert charge["intervention_id"] == i_id
    assert charge["statut"] == "completed_pending_review"
    # T1.2-f : type_travaux (CHAMPS_WCT_OPTIONNELS) s'ajoute AU-DESSUS de CHAMPS_WCT, connu ici
    # puisque _contrat() en porte un — jamais ville (Loi 25, tokenisée dans le registre M4).
    assert set(charge) == set(CHAMPS_WCT) | {"type_travaux"}
    assert charge["type_travaux"] == "renovation_totale"
    # T1.5-c : aucun écart n'était connu de M4 ; le statut, lui, dit « pas encore vérifié ».
    assert charge["ecart_signale"] is False


def test_completion_avec_une_demande_d_ecart_ouverte_signale_l_ecart_dans_le_wct_et_l_evenement(
    base_durable, deposer_photo_test,
):
    """T1.5-c : `ecart_signale` a une source vraie — une demande d'écart métier ouverte, lue au registre —
    et jamais « vrai par précaution ». La complétion reste à vérifier dans les deux cas."""
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-ECART-OUVERT")
    demande = executer_atomique(par_nom["m4_creer_demande_ecart"], {
        "intervention_id": i_id,
        "version_prevue": {"duree_minutes": 120, "perimetre": "gouttières", "materiaux": ["gouttière"]},
        "version_declaree": {"duree_minutes": 150, "perimetre": "gouttières et soffite",
                             "materiaux": ["gouttière", "soffite"]},
        "horodatage": "2025-06-02T11:32:00+00:00",
    })
    assert demande["ok"] is True and demande["resultat"]["accepte"] is True, demande

    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _preuves_ok(par_nom, deposer_photo_test),
    })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion
    accuse = completion["resultat"]["resultat"]
    assert (accuse["statut"], accuse["ecart_signale"]) == ("completed_pending_review", True)
    _, charge = _charge_publiee("m4.travaux_termines")
    assert (charge["statut"], charge["ecart_signale"]) == ("completed_pending_review", True)
    assert _wct_pour(par_nom, i_id)["ecart_signale"] is True


def test_completion_sans_ecart_connu_ne_signale_aucun_ecart_mais_reste_a_verifier(base_durable, deposer_photo_test):
    """Le pendant : sans demande d'écart, le WCT ne prétend pas qu'un écart existe (`ecart_signale`
    faux) ; la complétion reste pourtant `completed_pending_review`, parce que les matériaux ne sont
    pas encore comparés au prévu (§6) — c'est le statut qui le dit, pas un écart inventé."""
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-SANS-ECART")
    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _preuves_ok(par_nom, deposer_photo_test),
    })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion
    accuse = completion["resultat"]["resultat"]
    assert (accuse["statut"], accuse["ecart_signale"]) == ("completed_pending_review", False)
    wct = _wct_pour(par_nom, i_id)
    assert (wct["statut"], wct["ecart_signale"], wct["revue_id"]) == ("completed_pending_review", False, None)
    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": i_id})
    assert statut["resultat"]["statut"] == "completed_pending_review"


def test_completion_d_un_lead_v2_publie_service_et_jamais_type_travaux(
    base_durable, deposer_photo_test, declarer_services,
):
    """PLAN T0.13-b : le WCT d'un lead v2 porte `service` (clé additive du catalogue), jamais `type_travaux`,
    et l'accusé de la planification puis la liste des interventions parlent la même langue."""
    declarer_services()
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-V2", contrat=_contrat_v2("L-EVT-V2", "soffite_fascia"))

    liste = executer_atomique(par_nom["m4_lister_interventions"], {})["resultat"]
    [intervention] = [i for i in liste if i["intervention_id"] == i_id]
    assert intervention["service"] == "soffite_fascia" and "type_travaux" not in intervention

    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _preuves_ok(par_nom, deposer_photo_test),
    })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion
    _, charge = _charge_publiee("m4.travaux_termines")
    assert set(charge) == set(CHAMPS_WCT) | {"service"}
    assert charge["service"] == "soffite_fascia" and "type_travaux" not in charge
    # Le catalogue du socle accepte cette forme : `service` y est déclaré, additif (jamais requis).
    assert schemas.erreurs_charge("m4.travaux_termines", charge) == []
    schema = evenements.schema("m4.travaux_termines")
    assert "service" in schema["properties"] and "service" not in schema["required"]
    assert _wct_pour(par_nom, i_id)["service"] == "soffite_fascia"


def test_la_planification_d_un_lead_v2_rend_l_assignation_avec_service(base_durable, declarer_services):
    declarer_services()
    par_nom = {o.nom: o for o in outils()}
    plan = executer_atomique(par_nom["m4_planifier_intervention"], {
        "contrat": _contrat_v2("L-PLAN-V2"), "marqueur": _marqueur("L-PLAN-V2"),
        "horodatage": "2025-06-02T08:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": ["T1"], "fenetres_disponibles": [FENETRE],
    })
    assert plan["ok"] is True and plan["resultat"]["etape"] == "complet", plan
    assignation = plan["resultat"]["assignation"]
    assert assignation["service"] == "gouttieres" and "type_travaux" not in assignation
    assert assignation["technicien_id"] == "T1"


def test_la_planification_d_un_lead_v2_dont_le_service_n_est_pas_declare_est_refusee(
    base_durable, declarer_services,
):
    declarer_services("revetement")
    par_nom = {o.nom: o for o in outils()}
    plan = executer_atomique(par_nom["m4_planifier_intervention"], {
        "contrat": _contrat_v2("L-PLAN-V2-REFUS"), "marqueur": _marqueur("L-PLAN-V2-REFUS"),
        "horodatage": "2025-06-02T08:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": ["T1"], "fenetres_disponibles": [FENETRE],
    })
    assert plan["ok"] is True
    assert plan["resultat"]["etape"] == "inscription" and plan["resultat"]["accepte"] is False
    verdict = plan["resultat"]["verdict"]
    assert verdict["code"] == "REJ-ENUM-INVALIDE" and "REJ-SERVICE-INCONNU" in verdict["detail"]
    liste = executer_atomique(par_nom["m4_lister_interventions"], {})["resultat"]
    assert liste == []  # rien n'a été inscrit


def test_completion_refusee_ne_publie_rien(base_durable, deposer_photo_test):
    """Preuves incomplètes -> l'outil renvoie `accepte: False` (pas un refus_metier) sans
    jamais atteindre l'outbox ni le bus."""
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-REFUS")

    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": {**_preuves_ok(par_nom, deposer_photo_test), "photos_apres": []},
    })
    assert completion["ok"] is True
    assert completion["resultat"]["accepte"] is False
    assert completion["resultat"]["verdict"]["code"] == "REJ-CHAMP-VIDE"
    assert _compte_sortants("m4.travaux_termines") == 0


def test_completion_hors_transaction_ne_publie_rien_et_ne_leve_pas(base_durable, deposer_photo_test):
    """Suite pure de `test_outils_agent.py` (registre EN MÉMOIRE, `executer` sans
    transaction) : `stockage.connexion_courante()` est None, donc aucun appel à
    `evenements.publier` n'est tenté — sans base migrée, ce serait sinon une panne. T1.4-e2 :
    `base_durable` migre quand même une base (nécessaire pour vérifier la référence de photo,
    une lecture pure qui ouvre sa PROPRE transaction quand aucune n'est ambiante,
    `outils._verifier_reference_fichier`) ; `m4_deposer_fichier`/`m4_etat_fichier` ignorent
    `registre_cible` (aucun mode « en mémoire » pour le dépôt de fichiers, par construction) —
    seule `m4_completer_intervention` reste ici sur le registre EN MÉMOIRE, sans transaction."""
    from m4_field_ops.registre import Registre

    par_nom = {o.nom: o for o in outils(Registre())}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-MEMOIRE")
    reponse = executer(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _preuves_ok(par_nom, deposer_photo_test),
    })
    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is True
    assert reponse["resultat"]["resultat"]["statut"] == "completed_pending_review"


# -- consommateurs() : m6.variance_chantier fait ou non passer à completed_verified -----------
def _wct_pour(par_nom, i_id):
    boite = executer_atomique(par_nom["m4_lire_outbox"], {})
    return next(e["wct"] for e in boite["resultat"] if e["wct"]["intervention_id"] == i_id)


def _variance_charge(**overrides):
    base = {
        "evenement_id": "m6-variance-test", "wct_id": "wct-inexistant",
        "intervention_id": "i-inexistant", "chantier_id": "C1",
        "statut_variance": "evaluee", "signal_critique": False,
        "seuil_pourcentage": 0.30, "horodatage_completion": "2025-06-02T11:35:00+00:00",
    }
    base.update(overrides)
    return base


def test_declaration_module_consommateurs():
    # PLAN T4.10-b : M4 consomme aussi `m3.devis_accepte` (test_consommer_devis_accepte.py) ; PLAN T4.14-b :
    # `m6.materiel_pret` (test_materiel_pret_recu.py).
    assert set(consommateurs()) == {"m6.variance_chantier", "m3.devis_accepte", "m6.materiel_pret"}


def test_recevoir_variance_chantier_evaluee_sans_signal_passe_a_completed_verified(base_durable, deposer_photo_test):
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-VERIFIE")
    executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _preuves_ok(par_nom, deposer_photo_test),
    })
    wct = _wct_pour(par_nom, i_id)

    with stockage.transaction():
        resultat = consommateurs()["m6.variance_chantier"](_variance_charge(
            wct_id=wct["wct_id"], intervention_id=i_id,
            horodatage_completion=wct["horodatage_completion"],
        ))
    assert resultat["traite"] is True
    assert resultat["verifie"] is True

    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": i_id})
    assert statut["resultat"]["statut"] == "completed_verified"


@pytest.mark.parametrize(
    "overrides",
    [
        {"statut_variance": "prevu_absent", "signal_critique": None},
        {"statut_variance": "declaration_absente", "signal_critique": None},
        {"statut_variance": "seuil_absent", "signal_critique": None, "seuil_pourcentage": None},
        {"statut_variance": "evaluee", "signal_critique": True},
    ],
)
def test_recevoir_variance_chantier_ne_verifie_jamais_hors_evaluee_sans_signal(
    base_durable, overrides, deposer_photo_test,
):
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-NON-VERIFIE")
    executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _preuves_ok(par_nom, deposer_photo_test),
    })
    wct = _wct_pour(par_nom, i_id)

    with stockage.transaction():
        resultat = consommateurs()["m6.variance_chantier"](_variance_charge(
            wct_id=wct["wct_id"], intervention_id=i_id,
            horodatage_completion=wct["horodatage_completion"], **overrides,
        ))
    assert resultat["traite"] is True
    assert resultat["verifie"] is False

    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": i_id})
    assert statut["resultat"]["statut"] == "completed_pending_review"


def test_recevoir_variance_chantier_redelivrance_ne_change_rien(base_durable, deposer_photo_test):
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-REDELIVRE")
    executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _preuves_ok(par_nom, deposer_photo_test),
    })
    wct = _wct_pour(par_nom, i_id)
    charge = _variance_charge(
        wct_id=wct["wct_id"], intervention_id=i_id, horodatage_completion=wct["horodatage_completion"],
    )

    with stockage.transaction():
        consommateurs()["m6.variance_chantier"](charge)
    with stockage.transaction():
        resultat2 = consommateurs()["m6.variance_chantier"](charge)
    assert resultat2["verifie"] is False  # deja_verifie : rien de neuf, jamais un refus

    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": i_id})
    assert statut["resultat"]["statut"] == "completed_verified"


# ==================================================================================
# T1.2-f : les champs CLIENT (Loi 25) ne sont acceptés que pendant un appel d'appareil
# (opsys.contexte.receptionne_de, socle T1.4-b) ; le WCT et la charge publiée les portent
# alors, catalogue-valides ; hors appel d'appareil, leur seule présence est un refus nommé.
# ==================================================================================
_HORODATAGE_APPAREIL_TEST = contexte.HorodatageAppareil(
    appareil="tel-employe-t1-2-f-fictif",
    horodatage_appareil=dt.datetime(2025, 6, 2, 11, 35, 0, tzinfo=dt.UTC),
    recu_le=dt.datetime(2025, 6, 2, 11, 35, 5, tzinfo=dt.UTC),
)
_VERSION_TEXTE = "consentement-client-fr-CA-v1-test"
_ADMIN_FICTIF = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")


@contextlib.contextmanager
def _appel_d_appareil():
    """Un appel d'appareil tel que le socle le pose : la personne authentifiée (créée en base, T1.4-k) ET
    les deux horloges. PLAN T1.5-d : un consentement client dit qui l'a recueilli, donc l'exige."""
    with stockage.transaction() as cnx:
        if identite.personne(cnx, _ADMIN_FICTIF.personne) is None:
            identite.creer_personne(cnx, _ADMIN_FICTIF.personne, "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
    with contextlib.ExitStack() as pile:
        pile.enter_context(contexte.appele_par_appareil(_ADMIN_FICTIF))
        pile.enter_context(contexte.receptionne_de(_HORODATAGE_APPAREIL_TEST))
        yield


def test_completion_appel_appareil_avec_consentement_porte_les_champs_client_et_publie_valide(
    base_durable, deposer_photo_test,
):
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-APPAREIL-CONSENT")

    with _appel_d_appareil():
        completion = executer_atomique(par_nom["m4_completer_intervention"], {
            "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
            "preuves_completion": _preuves_ok(par_nom, deposer_photo_test),
            "photos": ["chantier-apres-1.jpg"],
            "description_factuelle": "Gouttières remplacées, aucun incident.",
            "consentement_marketing": True, "client_satisfait": True,
            "consentement_version_texte": _VERSION_TEXTE,
        })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion
    wct_id = completion["resultat"]["resultat"]["wct_id"]

    # -- le WCT (registre, m4_lire_outbox) porte les champs fournis ------------------------
    wct = _wct_pour(par_nom, i_id)
    assert wct["photos"] == ["chantier-apres-1.jpg"]
    assert wct["description_factuelle"] == "Gouttières remplacées, aucun incident."
    assert wct["consentement_marketing"] is True
    assert wct["client_satisfait"] is True
    assert wct["type_travaux"] == "renovation_totale"
    # PLAN T1.5-d : la preuve du consentement, posée par le serveur (personne et heure de réception).
    assert wct["consentement_recueilli_par"] == "admin.fictif"
    assert wct["consentement_recueilli_le"] == "2025-06-02T11:35:05+00:00"
    assert wct["consentement_version_texte"] == _VERSION_TEXTE
    assert "consentement_demande_avis" not in wct  # non envoyé : jamais déduit de consentement_marketing

    # -- la charge publiée les porte AUSSI, et valide intégralement le schéma JSON du catalogue
    ligne, charge = _charge_publiee("m4.travaux_termines")
    assert ligne["evenement_id"] == wct_id
    assert charge["photos"] == ["chantier-apres-1.jpg"]
    assert charge["consentement_marketing"] is True
    assert charge["client_satisfait"] is True
    assert schemas.erreurs_charge("m4.travaux_termines", charge) == []


def test_completion_champs_client_hors_appel_appareil_refuse_nomme_rien_ecrit_ni_publie(
    base_durable, deposer_photo_test,
):
    """Hors d'un appel d'appareil (aucun ``contexte.receptionne_de`` actif), la seule PRÉSENCE
    d'un champ client est un refus nommé — même avec des preuves par ailleurs valides, même un
    seul des quatre champs fourni (ici ``client_satisfait=None``, valeur pourtant permise par le
    catalogue : c'est la PRÉSENCE, jamais la valeur, qui est jugée)."""
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-SANS-APPAREIL")
    assert _compte_sortants("m4.travaux_termines") == 0

    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _preuves_ok(par_nom, deposer_photo_test), "client_satisfait": None,
    })
    assert completion["ok"] is True
    assert completion["resultat"]["accepte"] is False
    assert completion["resultat"]["verdict"]["code"] == "REJ-CHAMPS-CLIENT-HORS-APPAREIL"

    # Rien n'a été écrit : l'intervention reste sur_site, aucun WCT dans l'outbox, rien publié.
    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": i_id})
    assert statut["resultat"]["statut"] == "sur_site"
    boite = executer_atomique(par_nom["m4_lire_outbox"], {})
    assert not any(e["wct"]["intervention_id"] == i_id for e in boite["resultat"])
    assert _compte_sortants("m4.travaux_termines") == 0


# ==================================================================================
# T1.2-f, bout en bout M4 -> M7 : le VRAI consommateur M7 (charger_departements(), comme en
# production), evenements.repartir SCOPÉ À M7 SEUL (patron déjà établi par
# test_cascade_travaux_termines_variance.py::_deps_bus — les
# autres consommateurs, dont M2, sont hors du périmètre de cette preuve et un lead de test
# inconnu de M2 y déclencherait une quarantaine sans rapport).
# ==================================================================================
def test_completion_appel_appareil_consentement_et_satisfaction_produit_un_brouillon_avis_m7_reel(
    base_durable, deposer_photo_test,
):
    deps = charger_departements()
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-M7-CONSENT")

    with _appel_d_appareil():
        completion = executer_atomique(par_nom["m4_completer_intervention"], {
            "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
            "preuves_completion": _preuves_ok(par_nom, deposer_photo_test),
            "consentement_demande_avis": True, "client_satisfait": True,
            "consentement_version_texte": _VERSION_TEXTE,
        })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion

    resume = evenements.repartir({"m07-marketing": deps["m07-marketing"]}, maintenant="2025-06-02T12:00:00+00:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0 and resume["traites"] == 1, resume

    demandes = list(stockage.maillons("m07-marketing", "demandes_avis"))
    assert any(d.get("intervention_id") == i_id for d in demandes)


def test_completion_sans_consentement_ne_produit_aucun_brouillon_avis_m7_reel(base_durable, deposer_photo_test):
    deps = charger_departements()
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-M7-SANS-CONSENT")

    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _preuves_ok(par_nom, deposer_photo_test),
    })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion

    resume = evenements.repartir({"m07-marketing": deps["m07-marketing"]}, maintenant="2025-06-02T12:00:00+00:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0 and resume["traites"] == 1, resume

    demandes = list(stockage.maillons("m07-marketing", "demandes_avis"))
    assert not any(d.get("intervention_id") == i_id for d in demandes)


def test_m3_cohorte_lit_projection_m4_et_bus_sans_activer_candidate(base_durable, deposer_photo_test):
    """Le chemin outil M3→projection SDK M4 relit le WCT publié et exige le statut courant vérifié."""
    par_nom = {outil.nom: outil for outil in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-CALIBRATION-R32")
    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id,
        "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _preuves_ok(par_nom, deposer_photo_test),
    })
    assert completion["resultat"]["resultat"]["statut"] == "completed_pending_review"
    wct_id = completion["resultat"]["resultat"]["wct_id"]
    assert evenements.charge_publiee("m4.travaux_termines", wct_id)["statut"] == "completed_pending_review"
    with contexte.appeler_en_tant_que("m01-front-office"):
        refus_appelant = executer_atomique(par_nom["m4_lire_faits_calibration_m3"], {"wct_ids": [wct_id]})
    assert refus_appelant["resultat"]["observations"] == []
    assert refus_appelant["resultat"]["refus"] == [{"motif": "departement_appelant_non_autorise"}]
    departements = charger_departements()
    livraison = evenements.repartir(
        {"m03-estimation": departements["m03-estimation"]}, maintenant="2025-06-02T12:30:00+00:00",
    )
    assert livraison["traites"] == 1 and livraison["echecs"] == 0

    # La projection et l'outil de cohorte s'exécutent sous l'origine fiable M3.
    with contexte.appeler_en_tant_que("m03-estimation"):
        projection = executer_atomique(par_nom["m4_lire_faits_calibration_m3"], {"wct_ids": [wct_id]})
        assert projection["resultat"]["observations"] == []
        assert projection["resultat"]["refus"] == [{
            "wct_id": wct_id, "motif": "statut_courant_non_verifie",
        }]

        # Le WCT initial reste pending dans le bus; la transition auditée confirme le statut courant.
        with stockage.transaction():
            journal = registre_mod.Registre(stockage.maillons("m04-field-ops", "principal"))
            accuse, verdict = outbox_mod.resoudre_revue_completion(
                i_id, "verifiee", "2025-06-02T12:00:00+00:00", journal,
                motif="Vérification de fixture de test.",
            )
        assert verdict is None and accuse["statut"] == "completed_verified"
        assert evenements.charge_publiee("m4.travaux_termines", wct_id)["statut"] == "completed_pending_review"

        projection = executer_atomique(par_nom["m4_lire_faits_calibration_m3"], {"wct_ids": [wct_id]})
        [fait] = projection["resultat"]["observations"]
        assert fait["statut_publie"] == "completed_pending_review"
        assert fait["statut_courant"] == "completed_verified"
        assert fait["horodatage_debut"] == "2025-06-02T09:00:00Z"
        assert fait["duree_reelle_minutes"] == 150

        outils_m3_par_nom = {outil.nom: outil for outil in outils_m3()}
        rapport = executer_atomique(outils_m3_par_nom["m3_evaluer_calibration_cohortes"], {
            "coupure_utc": "2025-06-03T00:00:00Z",
        })["resultat"]
    assert rapport["candidate_active"] is False
    assert rapport["statut"] == "insuffisant"
    assert rapport["refus_projection_m4"] == []
    assert rapport["refus_jointure_m3"] == {"lien_devis_lead_absent": 1}

    # Le bus reste la source canonique : une charge divergente n'est pas absorbée comme fait.
    charge_falsifiee = evenements.charge_publiee("m4.travaux_termines", wct_id)
    charge_falsifiee["duree_reelle_minutes"] += 1
    with stockage.transaction() as cnx:
        cnx.execute(
            update(EVENEMENTS_SORTANTS)
            .where(EVENEMENTS_SORTANTS.c.evenement_id == wct_id)
            .values(charge=codec.encoder(charge_falsifiee))
        )
    with contexte.appeler_en_tant_que("m03-estimation"):
        projection_falsifiee = executer_atomique(
            par_nom["m4_lire_faits_calibration_m3"], {"wct_ids": [wct_id]},
        )["resultat"]
    assert projection_falsifiee["observations"] == []
    assert projection_falsifiee["refus"] == [{"wct_id": wct_id, "motif": "fait_bus_absent_ou_divergent"}]


def test_m3_cohorte_jointure_positive_depuis_estimation_devis_et_wct_durables(
    base_durable, deposer_photo_test,
):
    """Le parcours durable bout à bout admet une observation réelle et garde la candidate inactive."""
    lead_id = "LEAD-CALIBRATION-R32-POSITIF"
    outils3 = {outil.nom: outil for outil in outils_m3()}
    contrat_estimation = {
        "lead_id": lead_id, "conversation_id": "CONV-CALIBRATION-R32-POSITIF",
        "type_travaux": "renovation_totale", "ville": VILLE, "canal": "formulaire",
        "contact": {"nom": "Client", "telephone": "5145550101"}, "urgence_declaree": False,
    }
    estimation = executer_atomique(outils3["m3_estimer_projet"], {
        "contrat": contrat_estimation,
        "marqueur": marqueur_m2(lead_id, contrat=contrat_estimation),
        "photos": [{
            "photo_id": "photo-calibration-r32", "resolution_largeur": 3000, "resolution_hauteur": 2000,
            "eclairage": 7, "angle": "face", "reference_echelle": {"type": "porte", "dimensions_connues": True},
        }],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": {
            "version": "calibration-r32-test", "unite": "pi_lin",
            "semantique_temps": "duree_ecoulee_intervention",
            "postes": {"renovation_totale": {
                "cout_unitaire_min": 10.0, "cout_unitaire_max": 20.0, "duree_minutes_par_unite": 10.0,
            }},
        },
        "quantite": 10, "plancher_rentable": 1, "graine": 42,
    })
    assert estimation["ok"] is True and estimation["resultat"]["accepte"] is True, estimation
    devis_id = estimation["resultat"]["estimation"]["devis_id"]
    source_hash = estimation["resultat"]["estimation"]["hash_maillon"]
    source = next(m for m in registre_m3_production().lire() if m["hash_maillon"] == source_hash)
    assert source["charge"]["trace_calibration_temps"]["semantique_temps"] == "duree_ecoulee_intervention"
    assert source["charge"]["trace_calibration_temps"]["duree_estimee_minutes"] == "100.0"

    cree = executer_atomique(outils3["m3_creer_devis"], {
        "devis_id": devis_id, "estimation_source_hash": source_hash, "lead_id": lead_id,
        "chantier_id": "CHANTIER-CALIBRATION-R32-POSITIF",
        "lignes": [{
            "description": "Travaux de rénovation", "quantite": "10", "unite": "pi_lin",
            "cout_unitaire": "12.00", "reference_besoin_materiau": None,
        }],
        "taux_marge": "0.20", "horodatage": "2025-06-01T13:00:00Z",
    })
    assert cree["ok"] is True and cree["resultat"]["accepte"] is True, cree
    accepte = executer_atomique(outils3["m3_marquer_devis_accepte"], {
        "devis_id": devis_id, "approbateur": "nathan", "horodatage": "2025-06-01T14:00:00Z",
    })
    assert accepte["ok"] is True and accepte["resultat"]["accepte"] is True, accepte

    par_nom = {outil.nom: outil for outil in outils()}
    pause_pointages = (
        ("arrivee", "2025-06-02T09:00:00+00:00"),
        ("pause_debut", "2025-06-02T10:00:00+00:00"),
        ("pause_fin", "2025-06-02T10:15:00+00:00"),
        ("depart", "2025-06-02T11:30:00+00:00"),
    )
    i_id = _mener_a_sur_site(
        par_nom, lead_id, devis_id=devis_id, pointages=pause_pointages,
    )
    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _preuves_ok(par_nom, deposer_photo_test),
    })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion
    wct_id = completion["resultat"]["resultat"]["wct_id"]
    wct = evenements.charge_publiee("m4.travaux_termines", wct_id)
    assert wct is not None
    assert wct["devis_id"] == devis_id and wct["lead_id"] == lead_id
    assert wct["duree_reelle_minutes"] == 135  # 150 minutes sur site moins 15 de pause; déplacement hors fenêtre.
    with stockage.transaction():
        faits_m4 = registre_mod.Registre(stockage.maillons("m04-field-ops", "principal"))
        assert outbox_mod.calculer_minutes_deplacement(faits_m4, i_id) == (30, None)
        assert outbox_mod.calculer_minutes_pause(faits_m4, i_id) == (15, None)

    departements = charger_departements()
    livraison = evenements.repartir(
        {"m03-estimation": departements["m03-estimation"]}, maintenant="2025-06-02T12:30:00+00:00",
    )
    assert livraison["traites"] == 1 and livraison["echecs"] == 0, livraison
    with stockage.transaction():
        recu = next(
            m for m in stockage.maillons("m03-estimation", "estime_vs_reel")
            if m.get("wct_id") == wct["wct_id"]
        )
    assert recu["type_entree"] == "wct_recu" and recu["wct_id"] == wct["wct_id"]

    with stockage.transaction():
        reg = registre_mod.Registre(stockage.maillons("m04-field-ops", "principal"))
        accuse, verdict = outbox_mod.resoudre_revue_completion(
            i_id, "verifiee", "2025-06-02T12:00:00+00:00", reg, motif="Validation fictive pour test d’intégration.",
        )
    assert verdict is None and accuse["statut"] == "completed_verified"
    outils3 = {outil.nom: outil for outil in outils_m3()}
    with contexte.appeler_en_tant_que("m03-estimation"):
        rapport = executer_atomique(outils3["m3_evaluer_calibration_cohortes"], {
            "coupure_utc": "2025-06-03T00:00:00Z",
        })["resultat"]
    assert rapport["candidate_active"] is False
    assert rapport["compteurs"]["observations_distinctes_valides"] == 1
    assert rapport["refus_jointure_m3"] == {}
    assert rapport["refus_projection_m4"] == []
    assert rapport["source_wct_ids"] == "registre_m03_estime_vs_reel"
    assert rapport["completude_corpus_m4"] == "non_prouvee"


def test_projection_refuse_arrivee_absente_sans_fabriquer_debut(monkeypatch):
    wct = {
        "wct_id": "WCT-SANS-ARRIVEE", "intervention_id": "INT-SANS-ARRIVEE",
        "lead_id": "LEAD-SANS-ARRIVEE", "devis_id": "DEVIS-SANS-ARRIVEE",
        "statut": "completed_pending_review", "hash_maillon": "a" * 64,
        "horodatage_completion": "2025-06-02T11:35:00+00:00", "duree_reelle_minutes": 150,
    }
    maillons = [
        {"wct": wct, "hash_maillon": "a" * 64},
        {"type_entree": "pointage", "intervention_id": "INT-SANS-ARRIVEE", "action": "depart",
         "horodatage": "2025-06-02T11:30:00+00:00"},
    ]

    class RegistreFixture:
        def taille(self):
            return len(maillons)

        def valider_chaine(self):
            return True

        def lire(self):
            return maillons

    monkeypatch.setattr(calibration_projection.outbox, "verifier_invariants_outbox", lambda _reg: (True, ""))
    monkeypatch.setattr(calibration_projection.etats, "statut_courant", lambda *_args: "completed_verified")
    monkeypatch.setattr(calibration_projection.evenements, "charge_publiee", lambda *_args: wct)
    resultat = calibration_projection.lire_projections([wct["wct_id"]], RegistreFixture())
    assert resultat["observations"] == []
    assert resultat["refus"] == [{"wct_id": wct["wct_id"], "motif": "arrivee_ou_depart_absent"}]


def test_projection_refuse_chaine_corrompue_et_depassement_quota_avant_lecture():
    class RegistreEspion:
        lu = False

        def taille(self):
            return 1

        def valider_chaine(self):
            return False

        def lire(self):
            self.lu = True
            return []

    corrompu = RegistreEspion()
    resultat = calibration_projection.lire_projections(["WCT-CORROMPU"], corrompu)
    assert resultat == {"observations": [], "refus": [{"motif": "chaine_m4_non_valide"}]}
    assert corrompu.lu is False

    class RegistreHorsQuota(RegistreEspion):
        def taille(self):
            return 20001

        def valider_chaine(self):
            raise AssertionError("la borne doit être vérifiée avant le parcours")

    hors_quota = RegistreHorsQuota()
    resultat = calibration_projection.lire_projections(["WCT-HORS-QUOTA"], hors_quota)
    assert resultat == {
        "observations": [], "refus": [{"motif": "registre_m4_hors_borne", "limite": 20000}],
    }
    assert hors_quota.lu is False
