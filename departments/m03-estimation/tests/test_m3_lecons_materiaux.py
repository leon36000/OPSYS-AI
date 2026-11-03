"""M10-06 côté M3 : la prévision de quantités de matériaux consomme une leçon promue, cite sa source,
et ne touche JAMAIS au prix. Une leçon absente ou un échantillon sous le minimum DÉCLARÉ ne corrige rien.
Fictif.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from m2_preparation_estimation import marqueur_m2

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import outils as outils_m3  # noqa: E402

from opsys import identite, stockage  # noqa: E402
from opsys.mnemo import lecons as mnemo_lecons  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402

FICTIF = True
DEP = "m03-estimation"
LEAD = "lead-m10-06-materiaux-fictif"
HORODATAGE = "2026-10-03T14:00:00+00:00"
MATERIAU = "gouttiere-alu-5po-fictif"

BAREME = {
    "version": "fictif-2026-m10-06",
    "unite": "pi2",
    "postes": {
        "ravalement": {
            "cout_unitaire_min": 40.0,
            "cout_unitaire_max": 160.0,
            "cout_unitaire_mode": 70.0,
            "materiaux": [
                {
                    "materiau": MATERIAU,
                    "quantite_par_unite": "2",
                    "unite": "pi",
                    "facteur_perte": "0.10",
                }
            ],
        }
    },
}
QUANTITE = 25
PLANCHER = 1500
GRAINE = 20261003


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m3-m10-06.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-fictif-123", ["nathan_owner"])
    yield url
    stockage.liberer()


def _registre_lecons():
    from m10_memoire.registre import Registre

    return Registre(stockage.maillons("m10-memoire", "lecons"))


def _promouvoir(genre, cible, cle, contenu, sources, *, horodatage=HORODATAGE):
    """Écrit une leçon PROPOSÉE, son évaluation chiffrée favorable, sa garde et deux décisions humaines réelles."""
    registre = _registre_lecons()
    ident = mnemo_lecons.lecon_id(genre, cible, cle, {"parametre": contenu["parametre"]})
    registre.ajouter(
        {
            "type_entree": mnemo_lecons.TYPE_PROPOSEE,
            "horodatage": horodatage,
            "lecon_id": ident,
            "genre": genre,
            "cible": cible,
            "cle": cle,
            "contenu": contenu,
            "libelle": "Leçon fictive de test M10-06.",
            "texte_agent": "Gabarit fictif sans chiffre.",
            "sources": list(sources),
            "propose_par": "m10-memoire",
        }
    )
    registre.ajouter(
        {
            "type_entree": mnemo_lecons.TYPE_EVALUATION,
            "partie": "mesure",
            "horodatage": horodatage,
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
            "horodatage": horodatage,
            "lecon_id": ident,
            "garde_gabarit": {"regressions": [], "bloquants_nouveaux": []},
            "empreinte_garde": "g" * 64,
            "par": "m10-memoire",
        }
    )
    acteur = SimpleNamespace(par="nathan", role="nathan_owner", source="cli")
    mnemo_lecons.decider(
        registre, ident, "canari", acteur=acteur, motif="Essai fictif sur une part des cas.",
        horodatage=horodatage, pourcentage=50, empreinte_garde="g" * 64,
    )
    mnemo_lecons.decider(
        registre, ident, "complete", acteur=acteur, motif="Promotion fictive après le canari.",
        horodatage=horodatage, empreinte_garde="g" * 64,
    )
    return ident


def _manifeste(tmp_path, monkeypatch, minimum=6):
    chemin = tmp_path / "department.yaml"
    chemin.write_text(
        json.dumps(
            {
                "configuration": {
                    "lecons_consommees": {"echantillon_minimum": minimum},
                    "revue_devis": {"minimum_rentable_cad": PLANCHER},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(outils_m3, "_MANIFESTE", chemin)


def _outil(nom):
    return next(o for o in outils_m3.outils() if o.nom == nom)


def _estimer():
    contrat = {
        "lead_id": LEAD,
        "conversation_id": "conv-m10-06-fictive",
        "type_travaux": "ravalement",
        "ville": "Quebec",
        "canal": "formulaire",
        "contact": {"nom": "Client FICTIF", "telephone": "5145550101"},
        "urgence_declaree": False,
    }
    arguments = {
        "contrat": contrat,
        "marqueur": marqueur_m2(LEAD, contrat=contrat),
        "photos": [
            {
                "photo_id": "p1",
                "resolution_largeur": 3000,
                "resolution_hauteur": 2000,
                "eclairage": 7,
                "angle": "face",
                "reference_echelle": None,
            }
        ],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": BAREME,
        "quantite": QUANTITE,
        "plancher_rentable": PLANCHER,
        "graine": GRAINE,
        "taux_marge": "0.35",
        "taux_marge_scenarios": {"normal": "0.30"},
    }
    reponse = executer_atomique(_outil("m3_estimer_projet"), arguments)
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def test_l_estimation_affiche_la_quantite_ajustee_et_sa_lecon_sans_toucher_au_prix(tmp_path, monkeypatch, base_durable):
    _manifeste(tmp_path, monkeypatch)
    ident = _promouvoir(
        "ecart_materiau",
        "m06-material-control",
        MATERIAU,
        {"parametre": "1.15", "mode": "facteur", "chantiers": 6, "coherence": "0.8000"},
        ["ligne-fictive-1", "ligne-fictive-2"],
    )
    resultat = _estimer()

    prevision = resultat["prevision_materiaux_avec_lecons"]
    assert prevision["statut"] == "correction_proposee"
    assert prevision["application"] == "proposee_non_appliquee"
    assert prevision["niveau_humain"] == "N4"
    (ligne,) = [x for x in prevision["lignes"] if x["cle"] == MATERIAU]
    assert Decimal(ligne["base"]) == Decimal("50")
    assert Decimal(ligne["valeur"]) == Decimal("57.50")
    assert ligne["attribution"]["lecon_id"] == ident
    assert ligne["attribution"]["sources"] == ["ligne-fictive-1", "ligne-fictive-2"]
    assert ligne["attribution"]["echantillon"] == 6
    # Les besoins publiés à M6 et le prix restent EXACTEMENT ceux du calcul déterministe.
    besoin = next(x for x in resultat["besoins_materiaux"]["lignes"] if x["materiau"] == MATERIAU)
    assert Decimal(besoin["quantite_estimee"]) == Decimal("50")
    assert resultat["prix_recommande"] is not None


def test_sans_lecon_promue_aucune_correction_et_la_raison_est_dite(tmp_path, monkeypatch, base_durable):
    _manifeste(tmp_path, monkeypatch)
    resultat = _estimer()
    prevision = resultat["prevision_materiaux_avec_lecons"]
    assert prevision["statut"] == "aucune_lecon_active"
    (ligne,) = prevision["lignes"]
    assert ligne["corrigee"] is False and Decimal(ligne["valeur"]) == Decimal("50")
    assert ligne["raison"] == "aucune_lecon_active"


def test_un_echantillon_sous_le_minimum_declare_ne_corrige_rien(tmp_path, monkeypatch, base_durable):
    _manifeste(tmp_path, monkeypatch, minimum=7)
    _promouvoir(
        "ecart_materiau",
        "m06-material-control",
        MATERIAU,
        {"parametre": "1.15", "mode": "facteur", "chantiers": 6, "coherence": "0.8000"},
        ["ligne-fictive-1"],
    )
    prevision = _estimer()["prevision_materiaux_avec_lecons"]
    assert prevision["statut"] == "aucune_correction"
    (ligne,) = prevision["lignes"]
    assert ligne["corrigee"] is False and Decimal(ligne["valeur"]) == Decimal("50")
    assert ligne["raison"] == "echantillon_insuffisant"
    assert ligne["minimum_echantillon"] == 7


def test_un_minimum_non_declare_est_un_refus_nomme_pas_une_valeur_par_defaut(tmp_path, monkeypatch, base_durable):
    chemin = tmp_path / "department.yaml"
    chemin.write_text(json.dumps({"configuration": {"lecons_consommees": {}}}), encoding="utf-8")
    monkeypatch.setattr(outils_m3, "_MANIFESTE", chemin)
    prevision = _estimer()["prevision_materiaux_avec_lecons"]
    assert prevision["statut"] == "minimum_non_declare"
    assert prevision["minimum_echantillon"] is None
    (ligne,) = prevision["lignes"]
    assert ligne["corrigee"] is False and "echantillon_minimum" in prevision["avertissement"]


def test_aucune_lecon_d_un_autre_materiau_ne_s_applique(tmp_path, monkeypatch, base_durable):
    _manifeste(tmp_path, monkeypatch)
    _promouvoir(
        "ecart_materiau",
        "m06-material-control",
        "autre-materiau-fictif",
        {"parametre": "1.15", "mode": "facteur", "chantiers": 6, "coherence": "0.8000"},
        ["ligne-fictive-1"],
    )
    prevision = _estimer()["prevision_materiaux_avec_lecons"]
    (ligne,) = prevision["lignes"]
    assert ligne["corrigee"] is False and ligne["raison"] == "aucune_lecon_active"


def test_l_outil_de_lecture_retrouve_l_estimation_du_devis_et_sa_lecon(tmp_path, monkeypatch, base_durable):
    _manifeste(tmp_path, monkeypatch)
    _promouvoir(
        "ecart_materiau",
        "m06-material-control",
        MATERIAU,
        {"parametre": "1.15", "mode": "facteur", "chantiers": 6, "coherence": "0.8000"},
        ["ligne-fictive-1"],
    )
    estimation = _estimer()
    hash_source = estimation["estimation"]["hash_maillon"]
    devis_id = estimation["besoins_materiaux"]["devis_id"]
    creation = executer_atomique(_outil("m3_creer_devis"), {
        "devis_id": devis_id,
        "lead_id": LEAD,
        "chantier_id": None,
        "lignes": [{
            "description": "Gouttières fictives", "quantite": "25", "unite": "pi2",
            "cout_unitaire": "10.00", "reference_besoin_materiau": None,
        }],
        "taux_marge": "0.35",
        "horodatage": "2026-10-03T15:00:00+00:00",
        "estimation_source_hash": hash_source,
    })
    assert creation["ok"] is True and creation["resultat"]["accepte"] is True, creation
    reponse = executer_atomique(
        _outil("m3_prevoir_materiaux_avec_lecons"), {"devis_id": devis_id}
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    prevision = reponse["resultat"]["prevision_materiaux_avec_lecons"]
    (ligne,) = prevision["lignes"]
    assert Decimal(ligne["base"]) == Decimal("50") and Decimal(ligne["valeur"]) == Decimal("57.50")
    assert ligne["attribution"]["lecon_id"]


def test_l_outil_de_lecture_refuse_un_devis_sans_estimation_source(base_durable):
    reponse = executer_atomique(
        _outil("m3_prevoir_materiaux_avec_lecons"), {"devis_id": "DEVIS-INCONNU-FICTIF"}
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-DEVIS-INTROUVABLE"


def test_un_registre_indisponible_est_dit_et_ne_corrige_rien(tmp_path, monkeypatch):
    _manifeste(tmp_path, monkeypatch)
    from opsys.mnemo import consommation as consommation_lecons

    def _panne(*_args, **_kwargs):
        raise RuntimeError("registre indisponible (fictif)")

    monkeypatch.setattr(consommation_lecons, "lecons_actives", _panne)
    reponse = outils_m3._prevision_materiaux_avec_lecons(
        {"lignes": [{"materiau": MATERIAU, "quantite_estimee": "2"}]}, "lead-fictif"
    )
    assert reponse["statut"] == "registre_indisponible"
    assert "indisponible" in reponse["avertissement"]
    assert reponse["lignes"][0]["corrigee"] is False


def test_un_minimum_non_declare_n_appelle_pas_le_registre(tmp_path, monkeypatch):
    chemin = tmp_path / "department.yaml"
    chemin.write_text(json.dumps({"configuration": {"lecons_consommees": {}}}), encoding="utf-8")
    monkeypatch.setattr(outils_m3, "_MANIFESTE", chemin)
    from opsys.mnemo import consommation as consommation_lecons

    def _panne(*_args, **_kwargs):
        raise AssertionError("le registre ne doit pas être lu sans minimum déclaré")

    monkeypatch.setattr(consommation_lecons, "lecons_actives", _panne)
    reponse = outils_m3._prevision_materiaux_avec_lecons(
        {"lignes": [{"materiau": MATERIAU, "quantite_estimee": "2"}]}, "lead-fictif"
    )
    assert reponse["statut"] == "minimum_non_declare"


def test_une_correction_proposee_garde_son_avertissement_par_defaut(tmp_path, monkeypatch, base_durable):
    _manifeste(tmp_path, monkeypatch)
    _promouvoir(
        "ecart_materiau",
        "m06-material-control",
        MATERIAU,
        {"parametre": "1.15", "mode": "facteur", "chantiers": 6, "coherence": "0.8000"},
        ["ligne-fictive-1"],
    )
    prevision = _estimer()["prevision_materiaux_avec_lecons"]
    assert "Aucune correction" not in prevision["avertissement"]


def test_la_cle_de_canari_prend_le_lead_puis_le_hash_de_version():
    assert outils_m3._cle_application_lecons({"lead_id": "lead-fictif"}, {}) == "lead-fictif"
    assert outils_m3._cle_application_lecons({"lead_id": 123}, {"estimation": {"hash_maillon": "a" * 64}}) == "a" * 64
    assert outils_m3._cle_application_lecons({}, {"estimation": {"hash_maillon": 123}}) is None
    assert outils_m3._cle_application_lecons(None, None) is None


def test_l_outil_de_lecture_refuse_un_devis_sans_lien_d_estimation(base_durable):
    creation = executer_atomique(_outil("m3_creer_devis"), {
        "devis_id": "DEVIS-SANS-ESTIMATION-FICTIF",
        "lead_id": LEAD,
        "chantier_id": None,
        "lignes": [{
            "description": "Gouttières fictives", "quantite": "1", "unite": "forfait",
            "cout_unitaire": "10.00", "reference_besoin_materiau": None,
        }],
        "taux_marge": "0.35",
        "horodatage": "2026-10-03T15:00:00+00:00",
    })
    assert creation["ok"] is True and creation["resultat"]["accepte"] is True, creation
    reponse = executer_atomique(
        _outil("m3_prevoir_materiaux_avec_lecons"), {"devis_id": "DEVIS-SANS-ESTIMATION-FICTIF"}
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"


def test_le_schema_du_nouvel_outil_borne_le_devis_id_et_ferme_les_arguments():
    outil = _outil("m3_prevoir_materiaux_avec_lecons")
    schema = outil.parametres
    assert schema["required"] == ["devis_id"] and schema["additionalProperties"] is False
    assert schema["properties"]["devis_id"]["minLength"] == 1
    assert schema["properties"]["devis_id"]["maxLength"] == 128
