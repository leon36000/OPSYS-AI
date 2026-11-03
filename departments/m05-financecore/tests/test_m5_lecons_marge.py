"""M10-06 côté M5 : la marge PRÉVUE d'un devis accepté consomme une leçon promue d'écart de marge,
cite sa source, et reste une proposition. Sans leçon ou sous le minimum DÉCLARÉ, aucune correction.
Fictif.
"""

from __future__ import annotations

from types import SimpleNamespace

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import devis_recus, wct_recus

from opsys import identite, stockage
from opsys.mnemo import lecons as mnemo_lecons
from opsys.outils import executer_atomique

FICTIF = True
DEP = "m05-financecore"
DEVIS = "DEVIS-M10-06-FICTIF"
HORODATAGE = "2026-10-04T12:00:00+00:00"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m5-m10-06.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    chemin = tmp_path / "department.yaml"
    chemin.write_text(
        yaml.safe_dump(
            {
                "configuration": {
                    "taux_horaire_main_d_oeuvre": "50.00",
                    "lecons_consommees": {"echantillon_minimum": 6},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(m5_outils, "_MANIFESTE", chemin)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-fictif-123", ["nathan_owner"])
    yield url
    stockage.liberer()


def _registre_lecons():
    from m10_memoire.registre import Registre

    return Registre(stockage.maillons("m10-memoire", "lecons"))


def _promouvoir(parametre="-15.00", *, chantiers=6, sources=("rentabilite-fictive-1",)):
    registre = _registre_lecons()
    contenu = {"parametre": parametre, "mode": "decalage_cad", "chantiers": chantiers, "coherence": "0.9000"}
    ident = mnemo_lecons.lecon_id("ecart_marge", DEP, "marge", {"parametre": parametre})
    registre.ajouter(
        {
            "type_entree": mnemo_lecons.TYPE_PROPOSEE,
            "horodatage": HORODATAGE,
            "lecon_id": ident,
            "genre": "ecart_marge",
            "cible": DEP,
            "cle": "marge",
            "contenu": contenu,
            "libelle": "Écart de marge fictif M10-06.",
            "texte_agent": "Gabarit fictif sans chiffre.",
            "sources": list(sources),
            "propose_par": "m10-memoire",
        }
    )
    registre.ajouter(
        {
            "type_entree": mnemo_lecons.TYPE_EVALUATION,
            "partie": "mesure",
            "horodatage": HORODATAGE,
            "lecon_id": ident,
            "mesure": {"mesurable": True, "ameliore": True, "regression": False, "chantiers_test": 2},
            "amelioration_mesurable": True,
            "par": "m10-memoire",
        }
    )
    registre.ajouter(
        {
            "type_entree": mnemo_lecons.TYPE_EVALUATION,
            "partie": "gabarit",
            "horodatage": HORODATAGE,
            "lecon_id": ident,
            "garde_gabarit": {"regressions": [], "bloquants_nouveaux": []},
            "empreinte_garde": "g" * 64,
            "par": "m10-memoire",
        }
    )
    acteur = SimpleNamespace(par="nathan", role="nathan_owner", source="cli")
    mnemo_lecons.decider(
        registre, ident, "canari", acteur=acteur, motif="Essai fictif de marge sur une part.",
        horodatage=HORODATAGE, pourcentage=50, empreinte_garde="g" * 64,
    )
    mnemo_lecons.decider(
        registre, ident, "complete", acteur=acteur, motif="Promotion fictive après le canari.",
        horodatage=HORODATAGE, empreinte_garde="g" * 64,
    )
    return ident


def _devis_accepte(cout_total="480.00", prix_total="600.00"):
    with stockage.transaction():
        stockage.maillons(DEP, "devis_recus").append(
            devis_recus.construire(
                DEVIS, "LEAD-M10-06-FICTIF", "CHANTIER-M10-06-FICTIF",
                [
                    {
                        "reference_ligne": "L0", "description": "Gouttières fictives", "quantite": "40",
                        "unite": "pi", "prix_unitaire": "10.00", "prix_ligne": "400.00",
                        "reference_besoin_materiau": "gouttiere-alu-5po-fictif",
                    }
                ],
                prix_total, "2026-10-01T10:00:00+00:00", cout_total=cout_total, taux_marge="0.25",
            )
        )


def _wct():
    with stockage.transaction():
        stockage.maillons(DEP, "wct_recus").append(
            wct_recus.construire(
                "WCT-M10-06-FICTIF", "INT-M10-06-FICTIF", DEVIS, "2026-10-02T16:00:00+00:00",
                duree_reelle_minutes=180,
            )
        )


def _outil(nom):
    return next(o for o in m5_outils.outils() if o.nom == nom)


def _appeler(**surcharges):
    arguments = {"devis_id": DEVIS, "role": "admin", "autorise_couts": True}
    arguments.update(surcharges)
    reponse = executer_atomique(_outil("m5_lire_rentabilite_chantier"), arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _prevision(resultat):
    (chantier,) = resultat["resultat"]["chantiers"]
    return chantier["rentabilite"]["prevision_marge_avec_lecons"]


def test_la_marge_prevue_est_ajustee_par_la_lecon_et_la_cite(base_durable):
    _devis_accepte()
    _wct()
    ident = _promouvoir("-15.00")
    resultat = _appeler()
    assert resultat["accepte"] is True, resultat
    prevision = _prevision(resultat)
    assert prevision["statut"] == "correction_proposee"
    assert prevision["application"] == "proposee_non_appliquee"
    (ligne,) = prevision["lignes"]
    assert ligne["base"] == "120.00" and ligne["valeur"] == "105.00"
    assert ligne["attribution"]["lecon_id"] == ident
    assert ligne["attribution"]["sources"] == ["rentabilite-fictive-1"]
    assert ligne["attribution"]["echantillon"] == 6
    (chantier,) = resultat["resultat"]["chantiers"]
    assert chantier["rentabilite"]["marge_prevue"] == "120.00"
    assert "mention" in resultat["resultat"]


def test_sans_lecon_aucune_correction_et_la_marge_prevue_reste_la_source(base_durable):
    _devis_accepte()
    _wct()
    resultat = _appeler()
    prevision = _prevision(resultat)
    assert prevision["statut"] == "aucune_lecon_active"
    (ligne,) = prevision["lignes"]
    assert ligne["corrigee"] is False and ligne["valeur"] == "120.00"
    (chantier,) = resultat["resultat"]["chantiers"]
    assert chantier["rentabilite"]["marge_prevue"] == "120.00"


def test_un_echantillon_sous_le_minimum_declare_ne_corrige_pas(base_durable, monkeypatch, tmp_path):
    chemin = tmp_path / "department.yaml"
    chemin.write_text(
        yaml.safe_dump(
            {
                "configuration": {
                    "taux_horaire_main_d_oeuvre": "50.00",
                    "lecons_consommees": {"echantillon_minimum": 7},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(m5_outils, "_MANIFESTE", chemin)
    _devis_accepte()
    _wct()
    _promouvoir("-15.00", chantiers=6)
    prevision = _prevision(_appeler())
    (ligne,) = prevision["lignes"]
    assert ligne["corrigee"] is False and ligne["valeur"] == "120.00"
    assert ligne["raison"] == "echantillon_insuffisant"


def test_sans_droit_aux_couts_aucun_montant_n_est_rendu(base_durable):
    _devis_accepte()
    _wct()
    resultat = _appeler(autorise_couts=False)
    assert resultat["accepte"] is True
    (chantier,) = resultat["resultat"]["chantiers"]
    assert "marge_prevue" not in chantier["rentabilite"]
    assert "prevision_marge_avec_lecons" not in chantier["rentabilite"]


def test_un_devis_inconnu_est_un_refus_nomme(base_durable):
    resultat = _appeler(devis_id="DEVIS-INCONNU-FICTIF")
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-RENTABILITE-CHANTIER-INCONNU"


def test_sans_identite_d_appareil_autorise_couts_reste_obligatoire(base_durable):
    _devis_accepte()
    _wct()
    resultat = _appeler(autorise_couts=None)
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-AUTORISE-COUTS-REQUIS"


def _lecon_marge(parametre="-15.00", chantiers=6):
    return {
        "lecon_id": "lc-fictive-marge-directe",
        "genre": "ecart_marge",
        "cible": DEP,
        "cle": "marge",
        "etat": "complete",
        "propose_le": HORODATAGE,
        "sources": ["rentabilite-fictive-1"],
        "contenu": {"parametre": parametre, "mode": "decalage_cad", "chantiers": chantiers},
    }


def _manifeste_lecons(tmp_path, monkeypatch, minimum=6):
    chemin = tmp_path / "department.yaml"
    chemin.write_text(
        yaml.safe_dump({"configuration": {"lecons_consommees": {"echantillon_minimum": minimum}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(m5_outils, "_MANIFESTE", chemin)


def test_un_minimum_non_declare_n_appelle_pas_le_registre(tmp_path, monkeypatch):
    _manifeste_lecons(tmp_path, monkeypatch, minimum=None)
    from opsys.mnemo import consommation as consommation_lecons

    def _panne(*_args, **_kwargs):
        raise AssertionError("le registre ne doit pas être lu sans minimum déclaré")

    monkeypatch.setattr(consommation_lecons, "lecons_actives", _panne)
    reponse = m5_outils._prevision_marge_avec_lecons("120.00", DEVIS)
    assert reponse["statut"] == "minimum_non_declare"
    assert "n'est pas déclaré" in reponse["avertissement"]


def test_un_minimum_invalide_est_dit(tmp_path, monkeypatch):
    _manifeste_lecons(tmp_path, monkeypatch, minimum=0)
    reponse = m5_outils._prevision_marge_avec_lecons("120.00", DEVIS)
    assert reponse["statut"] == "minimum_invalide"
    assert "invalide" in reponse["avertissement"]


def test_un_registre_indisponible_est_dit(tmp_path, monkeypatch):
    _manifeste_lecons(tmp_path, monkeypatch)
    from opsys.mnemo import consommation as consommation_lecons

    def _panne(*_args, **_kwargs):
        raise RuntimeError("registre indisponible (fictif)")

    monkeypatch.setattr(consommation_lecons, "lecons_actives", _panne)
    reponse = m5_outils._prevision_marge_avec_lecons("120.00", DEVIS)
    assert reponse["statut"] == "registre_indisponible"
    assert "indisponible" in reponse["avertissement"]


def test_une_correction_proposee_garde_son_avertissement_par_defaut(tmp_path, monkeypatch):
    _manifeste_lecons(tmp_path, monkeypatch)
    from opsys.mnemo import consommation as consommation_lecons

    monkeypatch.setattr(
        consommation_lecons, "lecons_actives",
        lambda *_a, **_k: {"lecons": [_lecon_marge()]},
    )
    reponse = m5_outils._prevision_marge_avec_lecons("120.00", DEVIS)
    assert reponse["statut"] == "correction_proposee"
    assert "Aucune correction" not in reponse["avertissement"]


def test_la_trace_d_un_chantier_detail_est_a_jour(base_durable):
    _devis_accepte()
    _wct()
    etat = m5_outils._etat_chantier(DEVIS)
    assert etat["statut"] == "calculee"
    with stockage.transaction():
        stockage.maillons(DEP, "rentabilite").append({
            "devis_id": DEVIS, "version_entrees": etat["rentabilite"]["version_entrees"],
        })
    resultat = _appeler()
    (chantier,) = resultat["resultat"]["chantiers"]
    assert chantier["trace"]["a_jour"] is True
