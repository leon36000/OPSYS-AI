"""Chaîne de bout en bout PLAN T1.2-d (côté M6) : `m3.devis_accepte` -> M6 garde le prévu (le
bus, plus d'un appel manuel à `m6_enregistrer_besoins_prevus`) -> `m4.travaux_termines` -> M6
compare au réel déclaré -> `m6.variance_chantier` -> M4 décide `completed_verified` ou reste en
revue.

Fichier côté M6 (la consigne du coordinateur : ne pas toucher `departments/m04-field-ops/`),
mais réutilise l'API PUBLIQUE de M4 (chargée par `departements.charger_departements()`, jamais
modifiée) pour construire un WCT réel — mêmes helpers `_completer_intervention`/`_statut`/
`_repartir_jusqua_stable`/`_evenements_publies` que
`departments/m04-field-ops/tests/test_cascade_travaux_termines_variance.py` (PLAN T1.2-b),
copiés ici tels quels (lecture seule de l'API publique M4, aucune modification de M4).

`m3.devis_accepte` est simulé par `evenements.publier(...)` directement, conforme à
`src/opsys/evenements/catalogue/m3.devis_accepte.json`, plutôt que par un outil M3 : cette
chaîne prouve la MÉCANIQUE de la cascade côté M6 (bus, idempotence, transition M4), pas la
logique métier de M3 (hors périmètre de cette tranche, propre suite de tests de M3).

`evenements.repartir` ne route QUE M4 et M6 (`_deps_bus`, jamais `deps` en entier, jamais M3) :
M3 ne CONSOMME rien ici (seulement « publié » directement, ci-dessus) ; M2/M7/M8/M10
consomment aussi `m4.travaux_termines` sur la branche intégrée — les exclure évite un WCT de
test sans lead réel chez M2 (quarantaine légitime) et des comptes globaux fragiles (même règle
que le fichier M4 cité plus haut).

Les quatre scénarios du correctif (T1.2-d, point 4) :
- devis accepté puis complétion puis déclaration conforme -> `completed_verified`, sans aucun
  appel manuel à `m6_enregistrer_besoins_prevus` ;
- devis sans matériau (aucune ligne `reference_besoin_materiau`) -> le chantier peut quand même
  être vérifié (prévu vide connu, jamais un blocage) ;
- `chantier_id` nul dans le devis -> résolu plus tard depuis la déclaration, jamais deviné ;
- relivraison du même `m3.devis_accepte` -> aucun doublon (ni maillon, ni événement).
"""

from __future__ import annotations

import pytest
from m4_field_ops import cedule
from sqlalchemy import select

from opsys import departements, evenements, stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

SEL = "sel-t1-2-d-m6"
VILLE = "Montreal"
FIX_GPS = {"latitude": 45.5088, "longitude": -73.5878}
ATTESTATION = {"fictif": True, "appareil_id": "APP-T1-2-D"}
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
    """Départements RÉELS (pas de fixture de démonstration), comme au démarrage de l'instance."""
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

    # PLAN T4.2 (POLITIQUE-geolocalisation.md §4) : m4_pointer ne retient un fix GPS que si le
    # consentement du technicien est actif ; sans lui, le pointage passe en mode manuel (en_revue).
    consentement = executer_atomique(m4["m4_definir_consentement_gps"], {
        "technicien_id": "T1", "action": "donne", "horodatage": "2025-06-02T08:00:00+00:00",
        "version_politique": "POLITIQUE-geolocalisation-v1-test",
        "preuve": {"fictif": True, "reference": "consentement-test"},
    })
    assert consentement["ok"] is True and consentement["resultat"]["accepte"] is True, consentement

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


def _declarer_materiaux_utilises(deps, wct_id, intervention_id, chantier_id, quantite, materiau_id="MAT-1"):
    m6 = _outils(deps, "m06-material-control")
    _receptionner(deps, chantier_id, materiau_id, max(quantite, 1.0) * 2, po_id=f"PO-{wct_id}")
    r = executer_atomique(m6["m6_declarer_materiaux_utilises"], {
        "wct": _wct_pour_m6(deps, wct_id),
        "formulaire": {
            "wct_id": wct_id, "intervention_id": intervention_id, "chantier_id": chantier_id,
            "lignes_materiaux": [{
                "type_ligne": "prevu" if materiau_id == "MAT-1" else "non_prevu",
                "materiau_id": materiau_id, "quantite": quantite, "unite": "boite",
                **({"quantite_estimee": quantite} if materiau_id == "MAT-1" else {}),
            }],
        },
    })
    assert r["ok"] is True and r["resultat"]["accepte"] is True, r


def _ligne_devis(reference_ligne, quantite, unite, reference_besoin_materiau, prix_unitaire="10.00"):
    return {
        "reference_ligne": reference_ligne, "description": "ligne de test",
        "quantite": quantite, "unite": unite, "prix_unitaire": prix_unitaire,
        "prix_ligne": prix_unitaire, "reference_besoin_materiau": reference_besoin_materiau,
    }


def _devis_accepte_publie(devis_id, chantier_id, lignes):
    """Simule M3 (catalogue `m3.devis_accepte`) par `evenements.publier` DIRECTEMENT : voir la
    docstring du module. `publier` ouvre sa propre transaction hors de tout outil (bus.py)."""
    charge = {
        "devis_id": devis_id, "lead_id": "lead-t12d", "chantier_id": chantier_id, "lignes": lignes,
        "cout_total": "100.00", "prix_total": "135.00", "taux_marge": "0.35",
        "horodatage_acceptation": "2025-06-01T10:00:00-04:00",
    }
    evenements.publier(
        "m3.devis_accepte", "m03-estimation", charge, evenement_id=f"m3-devis-accepte-{devis_id}",
    )


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
def test_devis_accepte_completion_declaration_conforme_donne_completed_verified_sans_appel_manuel(
    base_migree, deps,
):
    # Aucun m6_enregistrer_besoins_prevus dans ce test : le prévu vient SEULEMENT du bus.
    i_id, wct_id = _completer_intervention(deps, "L-T12D-NOMINAL", "DEVIS-T12D-NOMINAL")
    _devis_accepte_publie("DEVIS-T12D-NOMINAL", "CHANTIER-T12D-NOMINAL", [
        _ligne_devis("DEVIS-T12D-NOMINAL-L1", "10", "boite", "MAT-1"),
    ])
    _declarer_materiaux_utilises(deps, wct_id, i_id, "CHANTIER-T12D-NOMINAL", quantite=10.0)

    resume = _repartir_jusqua_stable(deps)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    variance = _evenements_publies("m6.variance_chantier")[-1]
    assert variance["statut_variance"] == "evaluee"
    assert variance["signal_critique"] is False
    assert variance["chantier_id"] == "CHANTIER-T12D-NOMINAL"
    assert variance["lignes"] == [{
        "materiau": "MAT-1", "unite": "boite",
        "quantite_prevue": "10.0", "quantite_reelle": "10.0",
        "ecart_pourcentage": "0.0", "critique": False,
    }]
    assert _statut(deps, i_id) == "completed_verified"


def test_devis_sans_materiau_le_chantier_peut_etre_verifie(base_migree, deps):
    i_id, wct_id = _completer_intervention(deps, "L-T12D-VIDE", "DEVIS-T12D-VIDE")
    # Devis accepté SANS aucune ligne reliée à un besoin matériau (main-d'oeuvre seulement) :
    # prévu vide connu (besoins_prevus.py), jamais un blocage.
    _devis_accepte_publie("DEVIS-T12D-VIDE", "CHANTIER-T12D-VIDE", [
        _ligne_devis("DEVIS-T12D-VIDE-L1", "5", "heure", None),
    ])
    _declarer_materiaux_utilises(
        deps, wct_id, i_id, "CHANTIER-T12D-VIDE", quantite=3.0, materiau_id="MAT-IMPREVU",
    )

    resume = _repartir_jusqua_stable(deps)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    variance = _evenements_publies("m6.variance_chantier")[-1]
    assert variance["statut_variance"] == "evaluee"
    assert variance["signal_critique"] is False, "NON_PREVU n'est jamais critique (ecart_pourcentage indéfini)"
    ligne = variance["lignes"][0]
    assert ligne["materiau"] == "MAT-IMPREVU"
    assert ligne["quantite_prevue"] == "0.0"
    assert ligne["quantite_reelle"] == "3.0"
    assert ligne["ecart_pourcentage"] is None
    assert ligne["critique"] is False
    assert _statut(deps, i_id) == "completed_verified"


def test_devis_chantier_id_nul_resolu_plus_tard_depuis_la_declaration(base_migree, deps):
    i_id, wct_id = _completer_intervention(deps, "L-T12D-CHANTIER-NUL", "DEVIS-T12D-CHANTIER-NUL")
    # M3 accepte le devis AVANT que M4 planifie le chantier : chantier_id nul, jamais deviné.
    _devis_accepte_publie("DEVIS-T12D-CHANTIER-NUL", None, [
        _ligne_devis("DEVIS-T12D-CHANTIER-NUL-L1", "10", "boite", "MAT-1"),
    ])
    _declarer_materiaux_utilises(deps, wct_id, i_id, "CHANTIER-T12D-RESOLU", quantite=10.0)

    resume = _repartir_jusqua_stable(deps)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    variance = _evenements_publies("m6.variance_chantier")[-1]
    assert variance["statut_variance"] == "evaluee"
    assert variance["chantier_id"] == "CHANTIER-T12D-RESOLU", (
        "chantier_id résolu depuis la déclaration (qui le connaît toujours), jamais deviné à "
        "l'acceptation du devis -- sans quoi variance_chantier.evaluer(None, ...) filtrerait les "
        "mouvements déclarés sous le VRAI chantier_id et les traiterait comme jamais déclarés."
    )
    assert variance["signal_critique"] is False
    assert _statut(deps, i_id) == "completed_verified"


def test_relivraison_du_meme_devis_accepte_naucun_doublon(base_migree, deps):
    i_id, wct_id = _completer_intervention(deps, "L-T12D-REDELIVRE", "DEVIS-T12D-REDELIVRE")
    _devis_accepte_publie("DEVIS-T12D-REDELIVRE", "CHANTIER-T12D-REDELIVRE", [
        _ligne_devis("DEVIS-T12D-REDELIVRE-L1", "10", "boite", "MAT-1"),
    ])
    _declarer_materiaux_utilises(deps, wct_id, i_id, "CHANTIER-T12D-REDELIVRE", quantite=10.0)

    _repartir_jusqua_stable(deps)
    assert _statut(deps, i_id) == "completed_verified"
    # 2 événements : `m4.travaux_termines` est le PLUS ANCIEN publié (avant `m3.devis_accepte`,
    # simulant le flux réel où le devis arrive après la complétion) -- repartir le livre donc en
    # premier (prevu_absent), puis livre m3.devis_accepte qui réévalue tout seul (evaluee). Même
    # patron que le prévu tardif (test_evenements_m6.py::
    # test_prevu_arrive_apres_completion_reevalue_et_publie_evaluee).
    variances_avant = _evenements_publies("m6.variance_chantier")
    assert len(variances_avant) == 2
    assert [v["statut_variance"] for v in variances_avant] == ["prevu_absent", "evaluee"]
    assert len(_evenements_publies("m3.devis_accepte")) == 1

    # Republier le MÊME m3.devis_accepte (même evenement_id déterministe, comme le ferait une
    # redélivrance ou un rejeu de M3) : ON CONFLICT DO NOTHING côté bus -- aucun second maillon.
    _devis_accepte_publie("DEVIS-T12D-REDELIVRE", "CHANTIER-T12D-REDELIVRE", [
        _ligne_devis("DEVIS-T12D-REDELIVRE-L1", "10", "boite", "MAT-1"),
    ])
    assert len(_evenements_publies("m3.devis_accepte")) == 1, "publier() avec le même evenement_id est un no-op"

    resume_apres = _repartir_jusqua_stable(deps)
    assert resume_apres["livres"] == 0
    assert _statut(deps, i_id) == "completed_verified"
    assert len(_evenements_publies("m6.variance_chantier")) == 2, "aucun doublon après la relivraison"
