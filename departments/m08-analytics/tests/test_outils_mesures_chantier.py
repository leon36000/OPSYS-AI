"""Outils `m8_lire_mesures_chantier` et `m8_performance_equipe` (PLAN T1.5-d) : paliers, portée
d'appareil et, surtout, le détail nominatif par technicien réservé à l'admin authentifié.

Les faits sont injectés en mémoire (`faits_cible`) ; les tests d'identité montent une base SQLite
migrée avec de vraies personnes (fictives) et posent l'identité authentifiée d'un appareil comme
le fait OPSYS-CORE (`opsys.contexte.appele_par_appareil`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from m8_analytics import outils as m8_outils
from m8_analytics.outils import outils
from m8_analytics.registre import RegistreSnapshots

from opsys import contexte, identite, jetons, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.outils import Autonomie, executer, executer_atomique

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]

_TECHNICIENS = ("tech-fictif-a", "tech-fictif-b")


def _faits():
    faits = []
    for numero, (technicien, reel, estime) in enumerate(
        [("tech-fictif-a", 90, "100"), ("tech-fictif-b", 150, "100"), ("tech-fictif-b", 100, "100")], start=1
    ):
        faits.append({
            "type_entree": "wct", "wct_id": f"w{numero}", "intervention_id": f"i{numero}", "devis_id": f"d{numero}",
            "technicien_id": technicien, "horodatage_completion": "2026-09-28T14:00:00-04:00",
            "duree_reelle_minutes": reel, "statut": "completed_verified",
        })
        faits.append({
            "type_entree": "devis", "devis_id": f"d{numero}", "prix_total": "600.00", "cout_total": "480.00",
            "duree_estimee_minutes": estime, "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
        })
    return faits


def _par_nom(faits=None):
    return {o.nom: o for o in outils(RegistreSnapshots(), [], faits if faits is not None else _faits())}


@pytest.fixture
def base_avec_personnes(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictif", "mot-de-passe-admin-1234", ["admin"])
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-1234", ["employee"])
        identite.creer_personne(cnx, "ancien.fictif", "Ancien Admin Fictif", "mot-de-passe-ancien-1234", ["admin"],
                                actif=False)
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-1234", ["seller"])
    yield url
    stockage.liberer()


def _equipe(par_nom, identite_appareil=None):
    if identite_appareil is None:
        reponse = executer_atomique(par_nom["m8_performance_equipe"], {})
    else:
        with contexte.appele_par_appareil(identite_appareil):
            reponse = executer_atomique(par_nom["m8_performance_equipe"], {})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


# ---------------------------------------------------------------------------
# Paliers et portée d'appareil : lecture pure, admin seulement
# ---------------------------------------------------------------------------
def test_les_deux_outils_sont_t0_lecture_pure_et_reserves_au_role_admin():
    par_nom = _par_nom()
    for nom in ("m8_lire_mesures_chantier", "m8_performance_equipe"):
        assert par_nom[nom].autonomie == Autonomie.T0
        assert par_nom[nom].roles_appareil == frozenset({"admin"})  # ni employee, ni seller
        assert nom.startswith("m8_")


def test_lire_mesures_chantier_ne_montre_pas_le_technicien_et_ne_publie_rien():
    par_nom = _par_nom()
    reponse = executer(par_nom["m8_lire_mesures_chantier"], {"wct_id": "w2"})
    assert reponse["ok"] is True
    resultat = reponse["resultat"]
    assert resultat["trouve"] is True and resultat["devis_id"] == "d2"
    assert "tech-fictif" not in json.dumps(resultat)
    mesures = {m["metric_id"]: m for m in resultat["mesures"]}
    assert mesures["m8_ecart_duree_pct"]["valeur"] == "50.00"  # 150 vs 100
    assert resultat["seuils_a_configurer"] == ["m8_ecart_duree_pct"]  # aucun seuil dans le vrai manifeste


def test_lire_mesures_chantier_exige_un_wct_id():
    reponse = executer(_par_nom()["m8_lire_mesures_chantier"], {})
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"


# ---------------------------------------------------------------------------
# Performance d'équipe : nominatif seulement pour l'admin authentifié
# ---------------------------------------------------------------------------
def test_sans_identite_authentifiee_seule_l_equipe_anonyme_est_rendue(base_avec_personnes):
    resultat = _equipe(_par_nom())

    assert resultat["detail_nominatif"] == "reserve_admin"
    assert "techniciens" not in resultat
    assert resultat["equipe"]["n_techniciens"] == 2 and resultat["equipe"]["n_chantiers_mesures"] == 3
    assert resultat["equipe"]["ecart_pct"] == "13.33"  # (90 + 150 + 100 - 300) / 300
    for technicien in _TECHNICIENS:
        assert technicien not in json.dumps(resultat)


def test_l_admin_authentifie_recoit_le_detail_par_technicien_sans_classement(base_avec_personnes):
    resultat = _equipe(_par_nom(), IdentiteAppelante("admin.fictif", "admin"))

    assert resultat["detail_nominatif"] == "inclus"
    assert resultat["affichage"] == {
        "n_techniciens": 2, "depart": 0, "affiches": 2, "reste": 0, "prochain_depart": None, "message": None,
    }
    assert [t["technicien_id"] for t in resultat["techniciens"]] == list(_TECHNICIENS)  # par identifiant
    par_id = {t["technicien_id"]: t for t in resultat["techniciens"]}
    assert par_id["tech-fictif-a"]["ecart_pct"] == "-10.00"
    assert par_id["tech-fictif-b"]["ecart_pct"] == "25.00"
    assert resultat["chantiers_minimum_a_configurer"] is True
    assert all(t["suffisant"] is None for t in resultat["techniciens"])  # aucun minimum supposé


@pytest.mark.parametrize("appelante", [
    IdentiteAppelante("employe.fictif", "employee"),   # rôle non admin
    IdentiteAppelante("vendeur.fictif", "seller"),
    IdentiteAppelante("employe.fictif", "admin"),      # jeton qui prétend un rôle que la personne n'a pas
    IdentiteAppelante("ancien.fictif", "admin"),       # personne désactivée depuis l'émission du jeton
    IdentiteAppelante("inconnu.fictif", "admin"),      # personne inconnue
])
def test_toute_autre_identite_reste_sans_detail_nominatif(base_avec_personnes, appelante):
    resultat = _equipe(_par_nom(), appelante)

    assert resultat["detail_nominatif"] == "reserve_admin"
    assert "techniciens" not in resultat
    assert "tech-fictif" not in json.dumps(resultat)


def test_la_reponse_dit_ses_limites_et_qu_elle_est_non_punitive(base_avec_personnes):
    resultat = _equipe(_par_nom(), IdentiteAppelante("admin.fictif", "admin"))
    texte = " ".join(resultat["limites"]).lower()
    assert "dernier pointage" in texte and "non punitif" in texte and "sans classement" in texte
    assert resultat["metric_id"] == "m8_ecart_duree_technicien_pct" and resultat["unite"] == "pourcentage"
    assert len(resultat["version_definition"]) == 64


def test_sans_aucun_fait_l_equipe_est_vide_et_l_ecart_n_est_pas_invente(base_avec_personnes):
    resultat = _equipe(_par_nom([]), IdentiteAppelante("admin.fictif", "admin"))
    assert resultat["techniciens"] == []
    assert resultat["equipe"]["ecart_pct"] is None and resultat["equipe"]["n_chantiers_mesures"] == 0


def test_le_minimum_configure_rend_suffisant_vrai_ou_faux(base_avec_personnes, tmp_path, monkeypatch):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text("configuration:\n  performance_equipe:\n    chantiers_minimum: 2\n", encoding="utf-8")
    monkeypatch.setattr(m8_outils, "_MANIFESTE", manifeste)

    resultat = _equipe(_par_nom(), IdentiteAppelante("admin.fictif", "admin"))
    par_id = {t["technicien_id"]: t for t in resultat["techniciens"]}
    assert par_id["tech-fictif-a"]["suffisant"] is False  # 1 chantier < 2
    assert par_id["tech-fictif-b"]["suffisant"] is True  # 2 chantiers >= 2
    assert resultat["chantiers_minimum_a_configurer"] is False


# ---------------------------------------------------------------------------
# Une grande équipe : le détail nominatif tient sous la limite du socle, page par page
# ---------------------------------------------------------------------------
def test_le_detail_nominatif_d_une_grande_equipe_n_est_jamais_tronque_et_se_lit_par_pages(base_avec_personnes):
    """40 techniciens, un chantier chacun : plus que les 6 000 caractères de `Capacites` n'en laissent tenir.
    La réponse dit où reprendre (`prochain_depart`) au lieu d'être coupée au milieu."""
    identifiants = [f"tech-fictif-{numero:02d}" for numero in range(40)]
    faits = stockage.maillons("m08-analytics", "faits_chantier")
    with stockage.transaction():
        for numero, technicien in enumerate(identifiants):
            faits.append({
                "type_entree": "wct", "wct_id": f"w{numero}", "intervention_id": f"i{numero}",
                "devis_id": f"d{numero}", "technicien_id": technicien,
                "horodatage_completion": "2026-09-28T14:00:00-04:00", "duree_reelle_minutes": 100 + numero,
                "statut": "completed_verified",
            })
            faits.append({
                "type_entree": "devis", "devis_id": f"d{numero}", "prix_total": "600.00", "cout_total": "480.00",
                "duree_estimee_minutes": "100", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
            })
    capacites = Capacites(
        charger_departements(_RACINE_DEPARTEMENTS), stockage.transaction, filtre={"m08-analytics"}, memoire=False,
    )

    vus, depart, pages = [], 0, 0
    while depart is not None:
        with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
            reponse = capacites.appeler("m8_performance_equipe", {"depart": depart})
        assert reponse["ok"] is True and "tronque" not in reponse, reponse
        assert len(json.dumps(reponse, ensure_ascii=False)) <= jetons.LIMITE_SORTIE_DEFAUT
        page = reponse["resultat"]
        assert page["equipe"]["n_techniciens"] == 40  # l'équipe entière, quelle que soit la page
        assert page["affichage"]["affiches"] == len(page["techniciens"]) > 0
        vus.extend(t["technicien_id"] for t in page["techniciens"])
        depart = page["affichage"]["prochain_depart"]
        pages += 1
        assert pages < 50

    assert vus == identifiants  # les 40, une fois chacun, par identifiant
    assert pages > 1


def test_le_detail_nominatif_refuse_un_depart_invalide_ou_au_dela_de_la_fin(base_avec_personnes):
    par_nom = _par_nom()
    for depart in (-1, 3, True):
        with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
            reponse = executer_atomique(par_nom["m8_performance_equipe"], {"depart": depart})
        assert reponse["ok"] is False, depart  # -1 et 3 : refus métier ; True : type refusé par le schéma
