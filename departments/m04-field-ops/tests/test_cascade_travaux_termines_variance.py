"""Chaîne de bout en bout PLAN T1.2-b (M4) + partie M6 : complétion M4 -> `m4.travaux_termines`
-> M6 garde le prévu contre le réel déclaré -> `m6.variance_chantier` -> M4 décide
`completed_verified` ou reste en revue.

Par `evenements.repartir(...)`, départements RÉELS chargés par `charger_departements()`
(jamais des départements de démonstration), base SQLite temporaire migrée (ADR-0009) — le
scénario du PLAN, T1.2-b, section Tests :
- prévu enregistré, déclaration conforme et aucun signal -> completed_verified ;
- écart de 40 % -> l'intervention reste completed_pending_review ;
- prévu absent -> l'intervention reste completed_pending_review et l'événement porte
  prevu_absent ;
- une relivraison ne change rien.

PLUS le correctif du trou du flux réel (R12 §4/§9.7) : la déclaration des matériaux — et
parfois le prévu M3, T1.2-d — arrivent presque toujours APRÈS la complétion
(`materials_submit` dépend de la complétion ; le répartiteur tourne toutes les 3 s en
production). Une deuxième famille de tests reproduit cet ORDRE exact (complétion -> repartir
-> pièce manquante enregistrée ensuite) et vérifie qu'un second `m6.variance_chantier`
`evaluee` est publié et livré sans attendre une seconde `m4.travaux_termines` qui n'arrive
jamais deux fois.

`repartir` snapshot les événements sortants une seule fois par appel (voir docstring de
`opsys.evenements.repartiteur._candidats`) : un événement publié par un consommateur PENDANT
un appel (ici, m6.variance_chantier publié par M6 en réaction à m4.travaux_termines) n'est
livré qu'à l'appel SUIVANT — cette chaîne appelle donc `repartir` deux fois (helper
`_repartir_jusqua_stable`), exactement comme le ferait le sondage de secours en production.

`repartir` reçoit un DICT DE DÉPARTEMENTS SCOPÉ à M4+M6 (`_deps_bus`), jamais `deps` en
entier : `charger_departements()` rend TOUS les départements réels, et d'autres (M2, M7, M8,
M10…) peuvent consommer `m4.travaux_termines` sans lien avec cette tranche — les compter
rendrait ce test fragile à leur ajout, et un WCT de test sans lead réel chez M2 y déclenche
une quarantaine légitime (M2 refuse un lead qu'il ne connaît pas). Un test de département
vérifie SES reçus (ici : le contenu de m6.variance_chantier et le statut final de
l'intervention M4), jamais les comptes globaux du bus.
"""

from __future__ import annotations

import pytest
from m4_field_ops import cedule
from sqlalchemy import select

from opsys import departements, evenements, stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

SEL = "sel-cascade-t1-2"
VILLE = "Montreal"
FIX_GPS = {"latitude": 45.5088, "longitude": -73.5878}
ATTESTATION = {"fictif": True, "appareil_id": "APP-CASCADE"}
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}
_PREUVES_OK = {
    "checklist_complete": True, "photos_apres": ["photo-chantier.jpg"], "notes": "RAS.", "signature": None,
}


@pytest.fixture
def base_migree(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield
    stockage.liberer()


@pytest.fixture
def deps():
    """Départements RÉELS (pas de fixture de démonstration) : preuve que la chaîne tourne
    avec les manifestes livrés, exactement comme `opsys evenements repartir` en production."""
    return departements.charger_departements()


def _outils(deps, dep_id):
    return {o.nom: o for o in deps[dep_id].charger_outils()}


def _completer_intervention(deps, lead_id, devis_id):
    m4 = _outils(deps, "m04-field-ops")
    token = cedule.tokeniser_ville(SEL, VILLE)
    referentiel = {token: {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}

    plan = executer_atomique(m4["m4_planifier_intervention"], {
        "contrat": {
            "lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale",
            "ville": VILLE, "canal": "telephone",
            "contact": {"nom": "Client Test", "telephone": "0102030405"}, "urgence_declaree": False,
        },
        "marqueur": {
            "readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
            "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32,
        },
        "horodatage": "2025-06-02T08:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": ["T1"], "fenetres_disponibles": [FENETRE],
        "devis_id": devis_id,
    })
    assert plan["ok"] is True, plan
    i_id = plan["resultat"]["intervention_id"]

    depart = executer_atomique(m4["m4_demarrer_route"], {
        "intervention_id": i_id, "technicien_id": "T1", "horodatage": "2025-06-02T08:30:00+00:00",
    })
    assert depart["ok"] is True and depart["resultat"]["accepte"] is True, depart

    for action, horo in (("arrivee", "2025-06-02T09:00:00+00:00"), ("depart", "2025-06-02T11:30:00+00:00")):
        r = executer_atomique(m4["m4_pointer"], {
            "intervention_id": i_id, "technicien_id": "T1", "action": action, "horodatage": horo,
            "fix_gps": FIX_GPS, "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": referentiel, "ville": VILLE, "sel": SEL,
        })
        assert r["ok"] is True and r["resultat"]["accepte"] is True, r

    completion = executer_atomique(m4["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _PREUVES_OK,
    })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion
    return i_id, completion["resultat"]["resultat"]["wct_id"]


def _statut(deps, intervention_id):
    m4 = _outils(deps, "m04-field-ops")
    r = executer_atomique(m4["m4_statut_intervention"], {"intervention_id": intervention_id})
    assert r["ok"] is True, r
    return r["resultat"]["statut"]


def _wct_pour_m6(deps, wct_id):
    """WctRecu (contrats.CHAMPS_WCT de M6, 12 clés) : le WCT de M4 SANS son champ `statut`."""
    m4 = _outils(deps, "m04-field-ops")
    boite = executer_atomique(m4["m4_lire_outbox"], {})
    wct_complet = next(e["wct"] for e in boite["resultat"] if e["wct"]["wct_id"] == wct_id)
    return {k: v for k, v in wct_complet.items() if k != "statut"}


def _receptionner(deps, chantier_id, materiau_id, quantite, po_id):
    m6 = _outils(deps, "m06-material-control")
    r = executer_atomique(m6["m6_receptionner_commande"], {
        "bon_demande": {
            "po_id": po_id, "chantier_id": chantier_id,
            "lignes_demandees": [{"materiau_id": materiau_id, "quantite_demandee": quantite}],
            "horodatage": "2025-05-01T00:00:00Z",
        },
        "reception_po": {
            "po_id": po_id, "chantier_id": chantier_id,
            "lignes_recues": [{"materiau_id": materiau_id, "quantite_recue": quantite}],
            "horodatage": "2025-05-02T00:00:00Z",
        },
        "catalogue_materiaux": {
            "version": "v1", "unite_monetaire": "CAD",
            "postes": {materiau_id: {"cout_unitaire": 5.0, "libelle": materiau_id}},
        },
    })
    assert r["ok"] is True and r["resultat"]["accepte"] is True, r


def _enregistrer_besoins_prevus(deps, chantier_id, devis_id, quantite_estimee, materiau_id="MAT-1"):
    m6 = _outils(deps, "m06-material-control")
    r = executer_atomique(m6["m6_enregistrer_besoins_prevus"], {
        "chantier_id": chantier_id, "devis_id": devis_id,
        "lignes": [{"materiau_id": materiau_id, "quantite_estimee": quantite_estimee, "unite": "boite"}],
    })
    assert r["ok"] is True and r["resultat"]["accepte"] is True, r


def _declarer_materiaux_utilises(deps, wct_id, intervention_id, chantier_id, quantite, materiau_id="MAT-1"):
    m6 = _outils(deps, "m06-material-control")
    _receptionner(deps, chantier_id, materiau_id, max(quantite, 1.0) * 2, po_id=f"PO-{wct_id}")
    r = executer_atomique(m6["m6_declarer_materiaux_utilises"], {
        "wct": _wct_pour_m6(deps, wct_id),
        "formulaire": {
            "wct_id": wct_id, "intervention_id": intervention_id, "chantier_id": chantier_id,
            "lignes_materiaux": [{
                "type_ligne": "prevu", "materiau_id": materiau_id, "quantite": quantite,
                "unite": "boite", "quantite_estimee": quantite,
            }],
        },
    })
    assert r["ok"] is True and r["resultat"]["accepte"] is True, r


def _deps_bus(deps):
    """M4+M6 SEULEMENT (voir docstring du module) : jamais `deps` en entier à `repartir`."""
    return {"m04-field-ops": deps["m04-field-ops"], "m06-material-control": deps["m06-material-control"]}


def _repartir_jusqua_stable(deps, *, max_passes=5):
    deps_bus = _deps_bus(deps)
    cumul = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for _ in range(max_passes):
        resume = evenements.repartir(deps_bus)
        for cle in cumul:
            cumul[cle] += resume[cle]
        if resume["livres"] == 0:
            return cumul
    raise AssertionError(f"la chaîne d'événements ne s'est pas stabilisée : {cumul}")


def _evenements_publies(type_evenement):
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS)
            .where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
            .order_by(EVENEMENTS_SORTANTS.c.cree_le)
        ).mappings().all()
    return [codec.decoder(ligne["charge"]) for ligne in lignes]


# ------------------------------------------------------------------------------------------
def test_prevu_enregistre_declaration_conforme_aucun_signal_donne_completed_verified(base_migree, deps):
    i_id, wct_id = _completer_intervention(deps, "L-CASCADE-NOMINAL", "DEVIS-NOMINAL")
    _enregistrer_besoins_prevus(deps, "CHANTIER-NOMINAL", "DEVIS-NOMINAL", quantite_estimee=10.0)
    _declarer_materiaux_utilises(deps, wct_id, i_id, "CHANTIER-NOMINAL", quantite=10.0)

    resume = _repartir_jusqua_stable(deps)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    variances = _evenements_publies("m6.variance_chantier")
    assert len(variances) == 1
    variance = variances[0]
    assert variance["wct_id"] == wct_id
    assert variance["chantier_id"] == "CHANTIER-NOMINAL"
    assert variance["statut_variance"] == "evaluee"
    assert variance["signal_critique"] is False

    assert _statut(deps, i_id) == "completed_verified"


def test_ecart_quarante_pourcent_reste_en_revue(base_migree, deps):
    i_id, wct_id = _completer_intervention(deps, "L-CASCADE-ECART", "DEVIS-ECART")
    _enregistrer_besoins_prevus(deps, "CHANTIER-ECART", "DEVIS-ECART", quantite_estimee=10.0)
    _declarer_materiaux_utilises(deps, wct_id, i_id, "CHANTIER-ECART", quantite=14.0)  # +40 %

    _repartir_jusqua_stable(deps)

    variance = _evenements_publies("m6.variance_chantier")[0]
    assert variance["statut_variance"] == "evaluee"
    assert variance["signal_critique"] is True

    assert _statut(deps, i_id) == "completed_pending_review"


def test_prevu_absent_reste_en_revue_et_evenement_porte_prevu_absent(base_migree, deps):
    i_id, wct_id = _completer_intervention(deps, "L-CASCADE-SANS-PREVU", "DEVIS-SANS-PREVU")
    # Aucun m6_enregistrer_besoins_prevus pour DEVIS-SANS-PREVU : le prévu manque.
    _declarer_materiaux_utilises(deps, wct_id, i_id, "CHANTIER-SANS-PREVU", quantite=5.0)

    _repartir_jusqua_stable(deps)

    variance = _evenements_publies("m6.variance_chantier")[0]
    assert variance["statut_variance"] == "prevu_absent"
    assert variance["signal_critique"] is None

    assert _statut(deps, i_id) == "completed_pending_review"


def test_relivraison_ne_change_rien(base_migree, deps):
    i_id, wct_id = _completer_intervention(deps, "L-CASCADE-REDELIVRE", "DEVIS-REDELIVRE")
    _enregistrer_besoins_prevus(deps, "CHANTIER-REDELIVRE", "DEVIS-REDELIVRE", quantite_estimee=10.0)
    _declarer_materiaux_utilises(deps, wct_id, i_id, "CHANTIER-REDELIVRE", quantite=10.0)

    _repartir_jusqua_stable(deps)
    assert _statut(deps, i_id) == "completed_verified"
    assert len(_evenements_publies("m6.variance_chantier")) == 1
    assert len(_evenements_publies("m4.travaux_termines")) == 1

    # Un second passage (rien de nouveau à livrer, ou une nouvelle publication de M6 avec le
    # même evenement_id déterministe) ne change ni le statut ni le nombre d'événements publiés.
    resume_apres = _repartir_jusqua_stable(deps)
    assert resume_apres["livres"] == 0
    assert _statut(deps, i_id) == "completed_verified"
    assert len(_evenements_publies("m6.variance_chantier")) == 1
    assert len(_evenements_publies("m4.travaux_termines")) == 1


# ---- correctif : le trou du flux réel (R12 §4/§9.7 — déclaration/prévu APRÈS la complétion) ----
# Dans ces quatre tests, la pièce manquante (déclaration ou prévu) est enregistrée SEULEMENT
# APRÈS que `repartir` a déjà livré m4.travaux_termines à M6 (contrairement aux tests ci-dessus,
# où tout est en place avant le premier passage) : exactement l'ordre du flux réel, où
# `materials_submit` dépend de la complétion et où le répartiteur tourne toutes les 3 s.


def test_declaration_tardive_apres_repartition_donne_un_second_evenement_evaluee(base_migree, deps):
    i_id, wct_id = _completer_intervention(deps, "L-CASCADE-DECL-TARDIVE", "DEVIS-DECL-TARDIVE")
    _enregistrer_besoins_prevus(deps, "CHANTIER-DECL-TARDIVE", "DEVIS-DECL-TARDIVE", quantite_estimee=10.0)

    _repartir_jusqua_stable(deps)  # m4.travaux_termines livré à M6 AVANT toute déclaration
    assert _statut(deps, i_id) == "completed_pending_review"
    premiere_variance = _evenements_publies("m6.variance_chantier")[0]
    assert premiere_variance["statut_variance"] == "declaration_absente"

    # La déclaration arrive ENSUITE : m6_declarer_materiaux_utilises réévalue tout seul et
    # publie un SECOND m6.variance_chantier, sans attendre une nouvelle livraison de
    # m4.travaux_termines (qui n'arrivera jamais deux fois — c'était le trou).
    _declarer_materiaux_utilises(deps, wct_id, i_id, "CHANTIER-DECL-TARDIVE", quantite=10.0)
    variances = _evenements_publies("m6.variance_chantier")
    assert len(variances) == 2
    assert variances[1]["statut_variance"] == "evaluee"
    assert variances[1]["signal_critique"] is False
    assert variances[1]["evenement_id"] == f"m6-variance-{wct_id}-evaluee"

    _repartir_jusqua_stable(deps)
    assert _statut(deps, i_id) == "completed_verified"


def test_prevu_tardif_apres_repartition_donne_un_second_evenement_evaluee(base_migree, deps):
    i_id, wct_id = _completer_intervention(deps, "L-CASCADE-PREVU-TARDIF", "DEVIS-PREVU-TARDIF")
    _declarer_materiaux_utilises(deps, wct_id, i_id, "CHANTIER-PREVU-TARDIF", quantite=10.0)

    _repartir_jusqua_stable(deps)
    assert _statut(deps, i_id) == "completed_pending_review"
    assert _evenements_publies("m6.variance_chantier")[0]["statut_variance"] == "prevu_absent"

    # Le devis M3 (T1.2-d, ailleurs) arrive ENSUITE : m6_enregistrer_besoins_prevus réévalue.
    _enregistrer_besoins_prevus(deps, "CHANTIER-PREVU-TARDIF", "DEVIS-PREVU-TARDIF", quantite_estimee=10.0)
    variances = _evenements_publies("m6.variance_chantier")
    assert len(variances) == 2
    assert variances[1]["statut_variance"] == "evaluee"
    assert variances[1]["signal_critique"] is False

    _repartir_jusqua_stable(deps)
    assert _statut(deps, i_id) == "completed_verified"


def test_declaration_tardive_avec_ecart_critique_reste_en_revue(base_migree, deps):
    i_id, wct_id = _completer_intervention(deps, "L-CASCADE-DECL-TARDIVE-ECART", "DEVIS-DECL-TARDIVE-ECART")
    _enregistrer_besoins_prevus(
        deps, "CHANTIER-DECL-TARDIVE-ECART", "DEVIS-DECL-TARDIVE-ECART", quantite_estimee=10.0,
    )

    _repartir_jusqua_stable(deps)
    assert _statut(deps, i_id) == "completed_pending_review"

    _declarer_materiaux_utilises(deps, wct_id, i_id, "CHANTIER-DECL-TARDIVE-ECART", quantite=14.0)  # +40 %
    variances = _evenements_publies("m6.variance_chantier")
    assert variances[-1]["statut_variance"] == "evaluee"
    assert variances[-1]["signal_critique"] is True

    _repartir_jusqua_stable(deps)
    assert _statut(deps, i_id) == "completed_pending_review", "signal_critique=true : reste en revue"


def test_relivraisons_et_doubles_appels_apres_arrivee_tardive_aucun_doublon(base_migree, deps):
    i_id, wct_id = _completer_intervention(deps, "L-CASCADE-DOUBLE", "DEVIS-DOUBLE")
    _enregistrer_besoins_prevus(deps, "CHANTIER-DOUBLE", "DEVIS-DOUBLE", quantite_estimee=10.0)

    _repartir_jusqua_stable(deps)
    _declarer_materiaux_utilises(deps, wct_id, i_id, "CHANTIER-DOUBLE", quantite=10.0)
    _repartir_jusqua_stable(deps)
    assert _statut(deps, i_id) == "completed_verified"
    assert len(_evenements_publies("m6.variance_chantier")) == 2  # declaration_absente puis evaluee

    # Une redélivrance directe du consommateur M6 (le bus ne la produit jamais en pratique —
    # unicité (evenement_id, consommateur) — mais un appel direct doit rester sans danger, comme
    # pour une éventuelle concurrence) ne republie rien de plus : m6-variance-{wct_id}-evaluee
    # est déjà publié, court-circuité par _evaluer_et_publier_variance.
    charge_wct = _evenements_publies("m4.travaux_termines")[0]
    with stockage.transaction():
        deps["m06-material-control"].charger_consommateurs()["m4.travaux_termines"](charge_wct)
    assert len(_evenements_publies("m6.variance_chantier")) == 2

    # Une seconde soumission de matériaux pour le même wct_id est refusée nommément (T1.1-d2,
    # inchangé) avant même d'atteindre la réévaluation.
    reponse = executer_atomique(_outils(deps, "m06-material-control")["m6_declarer_materiaux_utilises"], {
        "wct": _wct_pour_m6(deps, wct_id),
        "formulaire": {
            "wct_id": wct_id, "intervention_id": i_id, "chantier_id": "CHANTIER-DOUBLE",
            "lignes_materiaux": [{
                "type_ligne": "prevu", "materiau_id": "MAT-1", "quantite": 10.0,
                "unite": "boite", "quantite_estimee": 10.0,
            }],
        },
    })
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-DECLARATION-DEJA-SOUMISE"
    assert len(_evenements_publies("m6.variance_chantier")) == 2

    # Un second passage de repartir (tout est déjà « traite ») ne change rien non plus.
    resume = _repartir_jusqua_stable(deps)
    assert resume["livres"] == 0
    assert _statut(deps, i_id) == "completed_verified"
    assert len(_evenements_publies("m6.variance_chantier")) == 2
