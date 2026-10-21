"""L'app du propriétaire lit les attentes des départements par pages, PAR `Capacites` (PLAN T1.5-e).

Constat de l'E2E de T1.5 : au-delà d'environ trois attentes, `m9_lister_demandes_approbation` ne faisait que
COMPTER les suivantes (`attentes_reste`), sans moyen de les lire. Ici, les vrais manifestes, le vrai
`Capacites`, une base migrée, une personne réelle : `decalage_attentes` lit la suite, page après page, sous la
troncature de 6 000 caractères, sans rien perdre ni répéter. Les attentes sont déclarées par M6 (fonction
`attentes()` remplacée par des faits fictifs, `fictif: true` : ce test prouve la lecture par pages, pas les
règles de M6, qui ont leurs tests).
"""

from __future__ import annotations

import json
from pathlib import Path

import m6_material_control.outils as m6_outils
import pytest
from m9_strategic_intelligence.outils import outils
from m9_strategic_intelligence.registre import RegistreSnapshots

from opsys import contexte, identite, jetons, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
LISTER = "m9_lister_demandes_approbation"
PROPRIO = contexte.IdentiteAppelante(personne="proprio.fictif", role="admin")
EMPLOYE = contexte.IdentiteAppelante(personne="employe.fictif", role="employee")
NOMBRE = 14


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "proprio.fictif", "Propriétaire Fictif", "mot-de-passe-proprio-1234",
                                ["admin", "nathan_owner"])
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-1234", ["employee"])
    yield url
    stockage.liberer()


@pytest.fixture
def capacites(base_durable):
    return Capacites(charger_departements(_RACINE_DEPARTEMENTS), stockage.transaction,
                     filtre={"m09-strategic-intelligence"}, memoire=False)


@pytest.fixture
def attentes_de_m6(monkeypatch):
    """`NOMBRE` besoins de commande fictifs, du plus ancien au plus récent (un article chacun)."""
    faits = [{
        "type": "besoin_commande", "id": f"besoin_commande:article-{i:02d}-fictif", "niveau": "N2",
        "resume": f"Stock bas : article-{i:02d}-fictif — {'x' * 200}",
        "depuis": f"2026-09-{i + 1:02d}T15:00:00+00:00",
        "action_proposee": "Créer un bon de commande (jamais seul) : à décider par le propriétaire",
    } for i in range(NOMBRE)]
    monkeypatch.setattr(m6_outils, "attentes", lambda: list(faits))
    return faits


def _lister(capacites, arguments, identite_appelante=PROPRIO):
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler(LISTER, arguments)


def _taille_socle(reponse: dict) -> int:
    """Ce que `Capacites._tronquer` mesure : `json.dumps(reponse, ensure_ascii=False)`."""
    return len(json.dumps(reponse, ensure_ascii=False))


def test_le_schema_de_la_liste_offre_un_decalage_entier_positif_et_aucune_personne():
    liste = next(o for o in outils(RegistreSnapshots(), alertes_cible=[]) if o.nom == LISTER)
    schema = liste.parametres

    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"limite", "decalage_attentes"}
    assert schema["properties"]["decalage_attentes"]["type"] == "integer"
    assert schema["properties"]["decalage_attentes"]["minimum"] == 0
    assert "required" not in schema  # sans argument, la liste reste celle d'avant
    for interdit in ("personne", "role", "identifiant", "appareil", "par", "utilisateur"):
        assert interdit not in schema["properties"]


@pytest.mark.parametrize("decalage", ["2", 1.5, True, None])
def test_un_decalage_qui_n_est_pas_un_entier_est_refuse_avant_d_atteindre_la_logique(decalage):
    liste = next(o for o in outils(RegistreSnapshots(), alertes_cible=[]) if o.nom == LISTER)

    reponse = executer(liste, {"decalage_attentes": decalage})

    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"


def test_un_decalage_negatif_est_un_verdict_de_la_logique_pas_une_page(capacites, attentes_de_m6):
    """Le validateur du socle ne lit pas `minimum` : c'est `lister_demandes` qui refuse, avec un verdict."""
    reponse = _lister(capacites, {"decalage_attentes": -1})

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "decalage_invalide"


def test_les_attentes_se_lisent_par_capacites_page_apres_page_chacune_une_fois(capacites, attentes_de_m6):
    lues, pages, decalage = [], [], 0
    while decalage is not None:
        reponse = _lister(capacites, {"decalage_attentes": decalage} if decalage else {})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
        assert "tronque" not in reponse and _taille_socle(reponse) <= jetons.LIMITE_SORTIE_DEFAUT
        page = reponse["resultat"]["resultat"]
        assert page["attentes_decalage"] == decalage and page["total_attentes"] == NOMBRE
        assert page["attentes_affichees"] == len(page["attentes"]) > 0
        lues.extend(a["id"] for a in page["attentes"])
        pages.append(page)
        decalage = page["attentes_suivant"]
        assert len(pages) < 50, "la lecture ne progresse pas"

    assert len(pages) > 1  # ce que l'écran ne pouvait pas lire avant : les attentes au-delà de la première page
    assert lues == [a["id"] for a in attentes_de_m6]  # toutes, une fois, la plus ancienne d'abord
    assert pages[-1]["attentes_reste"] == 0 and pages[0]["attentes_reste"] == NOMBRE - pages[0]["attentes_affichees"]
    assert all(a["departement"] == "m06-material-control" for p in pages for a in p["attentes"])


def test_un_decalage_hors_plage_rend_une_page_vide_par_capacites(capacites, attentes_de_m6):
    reponse = _lister(capacites, {"decalage_attentes": NOMBRE + 40})

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True
    page = reponse["resultat"]["resultat"]
    assert page["attentes"] == [] and page["attentes_suivant"] is None and page["attentes_reste"] == 0
    assert page["total_attentes"] == NOMBRE


def test_un_employe_ne_lit_aucune_page(capacites, attentes_de_m6):
    reponse = _lister(capacites, {"decalage_attentes": 3}, EMPLOYE)

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "role_appareil_insuffisant"


def test_sans_identite_de_l_appareil_aucune_page(capacites, attentes_de_m6):
    reponse = capacites.appeler(LISTER, {"decalage_attentes": 3})

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "identite_absente"
