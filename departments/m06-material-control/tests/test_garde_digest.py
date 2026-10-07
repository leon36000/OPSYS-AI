"""Le digest refuse une identité non autorisée avant de lire le stock (données fictives).

La garde utilise les personnes réelles de la base et le contexte transmis par le Core.
Une absence de contexte garde la voie interne ; un contexte admin invalide ne l'imite pas.
"""

from __future__ import annotations

import json

import pytest
from m6_material_control import outils as outils_m6
from m6_material_control.registre import Registre
from sqlalchemy import text

from opsys import contexte, identite, stockage
from opsys.outils import executer, executer_atomique

FICTIF = True
ADMIN = contexte.IdentiteAppelante("admin.fictif", "admin")
EMPLOYE = contexte.IdentiteAppelante("employe.fictif", "employee")
VENDEUR = contexte.IdentiteAppelante("vendeur.fictif", "seller")
SEUILS = [{"chantier_id": "CH-fictif", "materiau_id": "MAT-fictif", "seuil_quantite": 8.0}]
MOUVEMENTS = [
    {"type_mouvement": "RECEPTION", "chantier_id": "CH-fictif", "materiau_id": "MAT-fictif",
     "quantite": 5.0, "cout_unitaire": 10.0},
    {"type_mouvement": "VARIANCE_INVENTAIRE", "chantier_id": "CH-fictif", "materiau_id": "MAT-fictif",
     "quantite": -2.0, "cout_unitaire": None},
]


@pytest.fixture
def digest_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'digest-fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        for appelante in (ADMIN, EMPLOYE, VENDEUR):
            identite.creer_personne(
                cnx, appelante.personne, "Personne Fictive", "mot-de-passe-fictif-1234", [appelante.role],
            )
        reg = Registre(stockage.maillons("m06-material-control", "principal"))
        for mouvement in MOUVEMENTS:
            _, erreur = reg.ajouter(mouvement)
            assert erreur is None
    yield next(o for o in outils_m6.outils() if o.nom == "m6_produire_digest")
    stockage.liberer()


def _etat():
    """Toutes les tables, pas seulement le stock : une lecture ne modifie aucune donnée."""
    with stockage.transaction() as cnx:
        tables = cnx.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )).scalars().all()
        return {
            nom: sorted(
                [dict(ligne) for ligne in cnx.execute(text(f'SELECT * FROM "{nom}"')).mappings()],
                key=lambda ligne: json.dumps(ligne, sort_keys=True, default=str),
            ) for nom in tables
        }


def _observer_lectures(monkeypatch):
    """Spies de frontière : la confirmation d'identité et les calculs restent réels."""
    appels = {"registre": 0, "digest": 0}
    lire = outils_m6._registre_de_l_appel
    calculer = outils_m6.digest.produire_digest_quotidien

    def registre(*args, **kwargs):
        appels["registre"] += 1
        return lire(*args, **kwargs)

    def digest(*args, **kwargs):
        appels["digest"] += 1
        return calculer(*args, **kwargs)

    monkeypatch.setattr(outils_m6, "_registre_de_l_appel", registre)
    monkeypatch.setattr(outils_m6.digest, "produire_digest_quotidien", digest)
    return appels


@pytest.mark.parametrize(("appelante", "perturbation"), [
    pytest.param(EMPLOYE, None, id="employe_actif"),
    pytest.param(VENDEUR, None, id="vendeur_actif"),
    pytest.param(contexte.IdentiteAppelante("fantome.fictif", "admin"), None, id="admin_inconnu"),
    pytest.param(ADMIN, "inactive", id="admin_inactif"),
    pytest.param(ADMIN, "role_retire", id="admin_role_retire"),
    pytest.param(contexte.IdentiteAppelante(EMPLOYE.personne, "admin"), None, id="admin_non_porte"),
])
def test_identite_non_autorisee_ne_lit_ni_ne_calcule_le_digest(digest_durable, monkeypatch, appelante, perturbation):
    if perturbation is not None:
        with stockage.transaction() as cnx:
            if perturbation == "inactive":
                identite.activer(cnx, ADMIN.personne, False)
            else:
                identite.retirer_role(cnx, ADMIN.personne, "admin")
    avant = _etat()
    appels = _observer_lectures(monkeypatch)
    with contexte.appele_par_appareil(appelante):
        reponse = executer_atomique(digest_durable, {"seuils_reorder": SEUILS})

    assert reponse["ok"] is True
    assert reponse["resultat"].get("accepte") is False, reponse
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert appels == {"registre": 0, "digest": 0}
    assert _etat() == avant


def test_admin_confirme_lit_le_meme_digest_que_la_voie_interne_sans_mutation(digest_durable):
    avant = _etat()
    interne = executer_atomique(digest_durable, {"seuils_reorder": SEUILS})
    with contexte.appele_par_appareil(ADMIN):
        admin = executer_atomique(digest_durable, {"seuils_reorder": SEUILS})

    assert admin == interne
    assert admin["ok"] is True
    resultat = admin["resultat"]
    assert {k: v for k, v in resultat.items() if k != "hash_digest"} == {
        "type": "DIGEST_MATERIEL", "nb_variances_stock": 1, "nb_reorders_suggeres": 1,
        "variances_significatives": [{"chantier_id": "CH-fictif", "materiau_id": "MAT-fictif",
                                     "verdict_variance": "STOCK_INFERIEUR_AU_THEORIQUE", "ecart": -2.0}],
        "reorders": [{"chantier_id": "CH-fictif", "materiau_id": "MAT-fictif", "quantite_suggeree": 3.0}],
    }
    assert len(resultat["hash_digest"]) == 64
    assert _etat() == avant


def test_un_admin_hors_transaction_ne_lit_pas_un_historique_fourni(digest_durable, monkeypatch):
    avant = _etat()
    appels = _observer_lectures(monkeypatch)
    with contexte.appele_par_appareil(ADMIN):
        reponse = executer(digest_durable, {"registre_historique": MOUVEMENTS, "seuils_reorder": SEUILS})

    assert reponse["ok"] is True
    assert reponse["resultat"].get("accepte") is False, reponse
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert appels == {"registre": 0, "digest": 0}
    assert _etat() == avant


def test_apres_un_contexte_refuse_la_voie_interne_pure_reste_accessible(digest_durable):
    args = {"registre_historique": MOUVEMENTS, "seuils_reorder": SEUILS}
    avant = _etat()
    interne = executer(digest_durable, args)
    with contexte.appele_par_appareil(EMPLOYE):
        refuse = executer_atomique(digest_durable, {"seuils_reorder": SEUILS})
    assert refuse["resultat"].get("accepte") is False, refuse
    assert contexte.identite_appelante() is None
    assert executer(digest_durable, args) == interne
    assert interne["ok"] is True and interne["resultat"]["nb_reorders_suggeres"] == 1
    assert _etat() == avant
