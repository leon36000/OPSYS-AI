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

import datetime as dt

import pytest
from m4_field_ops import cedule
from m4_field_ops.outbox import CHAMPS_WCT
from m4_field_ops.outils import consommateurs, outils
from sqlalchemy import func, select

from opsys import contexte, evenements, stockage
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
_PREUVES_OK = {
    "checklist_complete": True, "photos_apres": ["photo-apres.jpg"], "notes": "RAS.", "signature": None,
}


def _contrat(lead_id):
    return {
        "lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale",
        "ville": VILLE, "canal": "telephone",
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


def _mener_a_sur_site(par_nom, lead_id):
    plan = executer_atomique(par_nom["m4_planifier_intervention"], {
        "contrat": _contrat(lead_id), "marqueur": _marqueur(lead_id),
        "horodatage": "2025-06-02T08:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": ["T1"], "fenetres_disponibles": [FENETRE],
    })
    assert plan["ok"] is True, plan
    i_id = plan["resultat"]["intervention_id"]

    depart = executer_atomique(par_nom["m4_demarrer_route"], {
        "intervention_id": i_id, "technicien_id": "T1", "horodatage": "2025-06-02T08:30:00+00:00",
    })
    assert depart["ok"] is True and depart["resultat"]["accepte"] is True, depart

    token = cedule.tokeniser_ville(SEL, VILLE)
    referentiel = {token: {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}
    for action, horo in (("arrivee", "2025-06-02T09:00:00+00:00"), ("depart", "2025-06-02T11:30:00+00:00")):
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
def test_completion_acceptee_publie_m4_travaux_termines_dans_la_meme_transaction(base_durable):
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-1")

    assert _compte_sortants("m4.travaux_termines") == 0

    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _PREUVES_OK,
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


def test_completion_refusee_ne_publie_rien(base_durable):
    """Preuves incomplètes -> l'outil renvoie `accepte: False` (pas un refus_metier) sans
    jamais atteindre l'outbox ni le bus."""
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-REFUS")

    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": {**_PREUVES_OK, "photos_apres": []},
    })
    assert completion["ok"] is True
    assert completion["resultat"]["accepte"] is False
    assert completion["resultat"]["verdict"]["code"] == "REJ-CHAMP-VIDE"
    assert _compte_sortants("m4.travaux_termines") == 0


def test_completion_hors_transaction_ne_publie_rien_et_ne_leve_pas():
    """Suite pure de `test_outils_agent.py` (registre EN MÉMOIRE, `executer` sans
    transaction) : `stockage.connexion_courante()` est None, donc aucun appel à
    `evenements.publier` n'est tenté — sans base migrée, ce serait sinon une panne."""
    from m4_field_ops.registre import Registre

    par_nom = {o.nom: o for o in outils(Registre())}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-MEMOIRE")
    reponse = executer(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _PREUVES_OK,
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
    assert set(consommateurs()) == {"m6.variance_chantier"}


def test_recevoir_variance_chantier_evaluee_sans_signal_passe_a_completed_verified(base_durable):
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-VERIFIE")
    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _PREUVES_OK,
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
def test_recevoir_variance_chantier_ne_verifie_jamais_hors_evaluee_sans_signal(base_durable, overrides):
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-NON-VERIFIE")
    executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _PREUVES_OK,
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


def test_recevoir_variance_chantier_redelivrance_ne_change_rien(base_durable):
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-REDELIVRE")
    executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _PREUVES_OK,
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


def test_completion_appel_appareil_avec_consentement_porte_les_champs_client_et_publie_valide(base_durable):
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-APPAREIL-CONSENT")

    with contexte.receptionne_de(_HORODATAGE_APPAREIL_TEST):
        completion = executer_atomique(par_nom["m4_completer_intervention"], {
            "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
            "preuves_completion": _PREUVES_OK,
            "photos": ["chantier-apres-1.jpg"],
            "description_factuelle": "Gouttières remplacées, aucun incident.",
            "consentement_marketing": True, "client_satisfait": True,
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

    # -- la charge publiée les porte AUSSI, et valide intégralement le schéma JSON du catalogue
    ligne, charge = _charge_publiee("m4.travaux_termines")
    assert ligne["evenement_id"] == wct_id
    assert charge["photos"] == ["chantier-apres-1.jpg"]
    assert charge["consentement_marketing"] is True
    assert charge["client_satisfait"] is True
    assert schemas.erreurs_charge("m4.travaux_termines", charge) == []


def test_completion_champs_client_hors_appel_appareil_refuse_nomme_rien_ecrit_ni_publie(base_durable):
    """Hors d'un appel d'appareil (aucun ``contexte.receptionne_de`` actif), la seule PRÉSENCE
    d'un champ client est un refus nommé — même avec des preuves par ailleurs valides, même un
    seul des quatre champs fourni (ici ``client_satisfait=None``, valeur pourtant permise par le
    catalogue : c'est la PRÉSENCE, jamais la valeur, qui est jugée)."""
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-SANS-APPAREIL")
    assert _compte_sortants("m4.travaux_termines") == 0

    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _PREUVES_OK, "client_satisfait": None,
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
# test_cascade_travaux_termines_variance.py::_wct_pour_m6 / son docstring _deps_bus — les
# autres consommateurs, dont M2, sont hors du périmètre de cette preuve et un lead de test
# inconnu de M2 y déclencherait une quarantaine sans rapport).
# ==================================================================================
def test_completion_appel_appareil_consentement_et_satisfaction_produit_un_brouillon_avis_m7_reel(base_durable):
    deps = charger_departements()
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-M7-CONSENT")

    with contexte.receptionne_de(_HORODATAGE_APPAREIL_TEST):
        completion = executer_atomique(par_nom["m4_completer_intervention"], {
            "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
            "preuves_completion": _PREUVES_OK,
            "consentement_marketing": True, "client_satisfait": True,
        })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion

    resume = evenements.repartir({"m07-marketing": deps["m07-marketing"]}, maintenant="2025-06-02T12:00:00+00:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0 and resume["traites"] == 1, resume

    demandes = list(stockage.maillons("m07-marketing", "demandes_avis"))
    assert any(d.get("intervention_id") == i_id for d in demandes)


def test_completion_sans_consentement_ne_produit_aucun_brouillon_avis_m7_reel(base_durable):
    deps = charger_departements()
    par_nom = {o.nom: o for o in outils()}
    i_id = _mener_a_sur_site(par_nom, "L-EVT-M7-SANS-CONSENT")

    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _PREUVES_OK,
    })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion

    resume = evenements.repartir({"m07-marketing": deps["m07-marketing"]}, maintenant="2025-06-02T12:00:00+00:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0 and resume["traites"] == 1, resume

    demandes = list(stockage.maillons("m07-marketing", "demandes_avis"))
    assert not any(d.get("intervention_id") == i_id for d in demandes)
