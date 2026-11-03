"""M10-06 de bout en bout, sur les vrais registres et outils : M10 apprend (variance et marge),
une personne promeut, M3 et M5 consomment la leçon et citent sa source. Aucun prix n'est calculé
par la leçon ; aucune correction n'est appliquée par un modèle. Fictif.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from m2_preparation_estimation import marqueur_m2

from opsys import approbations, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import charger_departements
from opsys.mnemo import cli as mnemo_cli
from opsys.mnemo import service
from opsys.outils import executer_atomique

FICTIF = True
M10 = "m10-memoire"
M3 = "m03-estimation"
M5 = "m05-financecore"
LEAD = "lead-m10-06-e2e-fictif"
MATERIAU = "gouttiere-alu-5po-fictif"
DEVIS = "DEVIS-M10-06-E2E-FICTIF"
MAINTENANT = dt.datetime(2026, 10, 5, 12, 0, tzinfo=dt.UTC)
HORODATAGE = "2026-10-05T12:00:00+00:00"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m10-06-e2e.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    monkeypatch.setattr(service, "maintenant", lambda: MAINTENANT)
    monkeypatch.setenv("OPSYS_SQLITE_SYNCHRONOUS", "NORMAL")
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-fictif-123", ["nathan_owner"])
    deps = charger_departements()
    yield {"url": url, "deps": deps, "tmp_path": tmp_path}
    stockage.liberer()


def _m10(monde):
    return Capacites(monde["deps"], stockage.transaction, filtre={M10}, appelant=M10)


def _ok(reponse):
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _variance(i: int, prevu: Decimal, reel: Decimal):
    return {
        "evenement_id": f"m6-variance-e2e-{i:03d}",
        "wct_id": f"WCT-E2E-{i:03d}",
        "intervention_id": f"INT-E2E-{i:03d}",
        "chantier_id": f"CHANTIER-E2E-{i:03d}",
        "statut_variance": "evaluee",
        "signal_critique": False,
        "seuil_pourcentage": 0.3,
        "horodatage_completion": f"2026-09-{1 + (i % 28):02d}T14:00:00-04:00",
        "lignes": [
            {
                "materiau": MATERIAU,
                "unite": "pi",
                "quantite_prevue": str(prevu),
                "quantite_reelle": str(reel.quantize(Decimal("0.01"))),
                "ecart_pourcentage": "0.15",
                "critique": False,
            }
        ],
    }


def _rentabilite(i: int):
    return {
        "evenement_id": f"m5-rentabilite-e2e-{i:03d}",
        "devis_id": f"DEVIS-E2E-{i:03d}",
        "chantier_id": f"CHANTIER-E2E-{i:03d}",
        "wct_id": f"WCT-MARGE-{i:03d}",
        "sequence": 1,
        "version_entrees": f"{i:064x}"[-64:],
        "horodatage_completion": f"2026-09-{1 + (i % 28):02d}T16:00:00-04:00",
        "verdict": "CALCULEE",
        "devise": "CAD",
        "prix_definitif": True,
        "cout_reel_complet": True,
        "cout_reel_cad": "495.00",
        "cout_connu_cad": "495.00",
        "marge_reelle_cad": "105.00",
        "marge_prevue_cad": "120.00",
        "ecart_marge_cad": "-15.00",
        "manque": [],
    }


def _humain(monde, caps, nom, arguments):
    demande = caps.appeler(nom, arguments)
    assert demande["ok"] is True and demande["statut"] == "en_attente_approbation", demande
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx, demande["demande_id"], True, "nathan",
            outils_executables(monde["deps"], stockage.transaction), monde["deps"],
        )


def _promouvoir(monde, caps, ident):
    _ok(caps.appeler("m10_evaluer_lecon", {"lecon_id": ident}))
    stockage.liberer()  # la garde monte une instance fictive hors de la transaction courante
    garde = mnemo_cli.garde_lecon(ident, "operateur.fictif")
    assert garde["regressions"] == [] and garde["bloquants_nouveaux"] == []
    assert _humain(
        monde, caps, "m10_decider_lecon",
        {"lecon_id": ident, "etape": "canari", "pourcentage": 50, "motif": "Essai fictif sur une part des cas."},
    )["statut"] == "executee"
    assert _humain(
        monde, caps, "m10_decider_lecon",
        {"lecon_id": ident, "etape": "complete", "motif": "Promotion fictive après le canari."},
    )["statut"] == "executee"


def test_une_lecon_promue_par_une_personne_est_consommee_par_m3_puis_m5(monde, tmp_path, monkeypatch):
    from m10_memoire import outils as m10_outils

    with stockage.transaction():
        for i in range(30):
            prevu = Decimal(10 + i)
            m10_outils._recevoir_variance_chantier(_variance(i, prevu, prevu * Decimal("1.15")))
        for i in range(30):
            m10_outils._recevoir_rentabilite_chantier(_rentabilite(i))

    caps = _m10(monde)
    bilan = _ok(caps.appeler("m10_extraire_lecons", {}))
    assert len(bilan["proposees"]) >= 2
    lecons = _ok(caps.appeler("m10_lire_lecons", {}))["lecons"]
    materiau = next(x for x in lecons if x["genre"] == "ecart_materiau" and x["cle"] == MATERIAU)
    marge = next(x for x in lecons if x["genre"] == "ecart_marge" and x["cle"] == "marge")
    assert materiau["cible"] == "m06-material-control" and marge["cible"] == M5
    _promouvoir(monde, caps, materiau["lecon_id"])
    _promouvoir(monde, caps, marge["lecon_id"])

    # -- M3 : la prévision de quantités cite la leçon, les besoins publiés et le prix restent intacts
    from m3_estimation import outils as m3_outils

    manifeste_m3 = tmp_path / "m3-department.yaml"
    manifeste_m3.write_text(
        '{"configuration": {"lecons_consommees": {"echantillon_minimum": 6}, '
        '"revue_devis": {"minimum_rentable_cad": 1500}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(m3_outils, "_MANIFESTE", manifeste_m3)
    contrat = {
        "lead_id": LEAD,
        "conversation_id": "conv-m10-06-e2e",
        "type_travaux": "ravalement",
        "ville": "Quebec",
        "canal": "formulaire",
        "contact": {"nom": "Client FICTIF", "telephone": "5145550101"},
        "urgence_declaree": False,
    }
    outil_m3 = next(o for o in m3_outils.outils() if o.nom == "m3_estimer_projet")
    reponse = executer_atomique(outil_m3, {
        "contrat": contrat,
        "marqueur": marqueur_m2(LEAD, contrat=contrat),
        "photos": [{
            "photo_id": "p1", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7,
            "angle": "face", "reference_echelle": None,
        }],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": {
            "version": "fictif-2026-m10-06-e2e",
            "unite": "pi2",
            "postes": {"ravalement": {
                "cout_unitaire_min": 40.0, "cout_unitaire_max": 160.0, "cout_unitaire_mode": 70.0,
                "materiaux": [{
                    "materiau": MATERIAU, "quantite_par_unite": "2", "unite": "pi", "facteur_perte": "0.10",
                }],
            }},
        },
        "quantite": 25,
        "plancher_rentable": 1500,
        "graine": 20261005,
        "taux_marge": "0.35",
        "taux_marge_scenarios": {"normal": "0.30"},
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    estimation = reponse["resultat"]
    prevision = estimation["prevision_materiaux_avec_lecons"]
    assert prevision["statut"] == "correction_proposee"
    (ligne,) = prevision["lignes"]
    assert Decimal(ligne["base"]) == Decimal("50") and Decimal(ligne["valeur"]) == Decimal("57.50")
    assert ligne["attribution"]["lecon_id"] == materiau["lecon_id"]
    assert ligne["attribution"]["sources"] == materiau["sources"]
    assert ligne["attribution"]["date"] == materiau["propose_le"]
    assert ligne["attribution"]["echantillon"] == materiau["contenu"]["chantiers"]
    besoin = estimation["besoins_materiaux"]["lignes"][0]
    assert Decimal(besoin["quantite_estimee"]) == Decimal("50")
    assert estimation["prix_recommande"] is not None

    # -- M5 : la marge prévue, corrigée et attribuée, reste une proposition
    from m5_financecore import devis_recus, wct_recus
    from m5_financecore import outils as m5_outils

    manifeste_m5 = tmp_path / "m5-department.yaml"
    manifeste_m5.write_text(
        '{"configuration": {"taux_horaire_main_d_oeuvre": "50.00", '
        '"lecons_consommees": {"echantillon_minimum": 6}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste_m5)
    with stockage.transaction():
        stockage.maillons(M5, "devis_recus").append(devis_recus.construire(
            DEVIS, LEAD, "CHANTIER-M10-06-E2E",
            [{"reference_ligne": "L0", "description": "Gouttières fictives", "quantite": "40", "unite": "pi",
              "prix_unitaire": "10.00", "prix_ligne": "400.00", "reference_besoin_materiau": MATERIAU}],
            "600.00", "2026-10-01T10:00:00+00:00", cout_total="480.00", taux_marge="0.25",
        ))
        stockage.maillons(M5, "wct_recus").append(wct_recus.construire(
            "WCT-M10-06-E2E", "INT-M10-06-E2E", DEVIS, "2026-10-02T16:00:00+00:00",
            duree_reelle_minutes=180,
        ))
    outil_m5 = next(o for o in m5_outils.outils() if o.nom == "m5_lire_rentabilite_chantier")
    reponse = executer_atomique(outil_m5, {"devis_id": DEVIS, "role": "admin", "autorise_couts": True})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    contenu = reponse["resultat"]["resultat"]
    (chantier,) = contenu["chantiers"]
    prevision_marge = chantier["rentabilite"]["prevision_marge_avec_lecons"]
    (ligne_marge,) = prevision_marge["lignes"]
    assert Decimal(ligne_marge["base"]) == Decimal("120.00")
    assert Decimal(ligne_marge["valeur"]) == Decimal("105.00")
    assert ligne_marge["attribution"]["lecon_id"] == marge["lecon_id"]
    assert ligne_marge["attribution"]["echantillon"] == marge["contenu"]["chantiers"]
    assert prevision_marge["application"] == "proposee_non_appliquee"

    # -- retrait humain : la leçon disparaît de la lecture, la correction aussi
    assert _humain(
        monde, caps, "m10_decider_lecon",
        {"lecon_id": materiau["lecon_id"], "etape": "retour_arriere", "motif": "Retrait fictif demandé."},
    )["statut"] == "executee"
    actives = _ok(Capacites(monde["deps"], stockage.transaction, filtre={M3}, appelant=M3).appeler(
        "opsys_lecons_actives", {"cle_application": LEAD}))
    assert all(x["lecon_id"] != materiau["lecon_id"] for x in actives["lecons"])
    reponse = executer_atomique(outil_m3, {
        "contrat": contrat,
        "marqueur": marqueur_m2(LEAD, contrat=contrat),
        "photos": [{
            "photo_id": "p1", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7,
            "angle": "face", "reference_echelle": None,
        }],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": {
            "version": "fictif-2026-m10-06-e2e",
            "unite": "pi2",
            "postes": {"ravalement": {
                "cout_unitaire_min": 40.0, "cout_unitaire_max": 160.0, "cout_unitaire_mode": 70.0,
                "materiaux": [{
                    "materiau": MATERIAU, "quantite_par_unite": "2", "unite": "pi", "facteur_perte": "0.10",
                }],
            }},
        },
        "quantite": 25,
        "plancher_rentable": 1500,
        "graine": 20261005,
        "taux_marge": "0.35",
        "taux_marge_scenarios": {"normal": "0.30"},
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True
    assert reponse["resultat"]["prevision_materiaux_avec_lecons"]["statut"] == "aucune_lecon_active"
