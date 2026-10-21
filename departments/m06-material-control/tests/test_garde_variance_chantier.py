"""Fictif : le rôle courant doit fermer la lecture/calcul avant le registre M6."""

from __future__ import annotations

import json

import pytest
from m6_material_control import outils
from m6_material_control.registre import Registre
from sqlalchemy import text

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique

FICTIF = True
ADMIN = contexte.IdentiteAppelante("admin.variance.fictif", "admin")
ARGS = {
    "chantier_id": "CH-FICTIF",
    "besoins_estimes": [{"materiau_id": "MAT-FICTIF", "quantite_estimee": 5.0, "unite": "unite-fictive"}],
    "seuil_pourcentage": 0.30,
    "wct_id": "WCT-FICTIF",
}


@pytest.fixture
def monde(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    db = tmp_path / "garde-variance-fictive.db"
    url = f"sqlite:///{db}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    db.chmod(0o600)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ADMIN.personne, "Administrateur fictif", "mot-de-passe-fictif-1234", ["admin"])
        reg = Registre(stockage.maillons("m06-material-control", "principal"))
        for type_, q in [("RECEPTION", 20.0), ("CONSOMMATION", -7.0), ("PERTE", -3.0)]:
            _, code = reg.ajouter(
                {
                    "type_mouvement": type_,
                    "chantier_id": "CH-FICTIF",
                    "materiau_id": "MAT-FICTIF",
                    "quantite": q,
                    "cout_unitaire": 4.0,
                    **({"wct_id": "WCT-FICTIF"} if type_ != "RECEPTION" else {}),
                }
            )
            assert code is None
    yield next(o for o in outils.outils() if o.nom == "m6_evaluer_variance_chantier")
    stockage.liberer()


def _tables():
    with stockage.transaction() as cnx:
        names = (
            cnx.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            )
            .scalars()
            .all()
        )
        return {
            n: sorted(
                [dict(x) for x in cnx.execute(text(f'SELECT * FROM "{n}"')).mappings()],
                key=lambda r: json.dumps(r, sort_keys=True, default=str),
            )
            for n in names
        }


def test_admin_role_retire_refuse_avant_registre(monde, monkeypatch):
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN.personne, "admin")
    acces = {"registre": 0, "lire": 0}
    original = outils._registre_de_l_appel

    class Observe:
        def __init__(self, real):
            self.real = real

        def lire(self):
            acces["lire"] += 1
            return self.real.lire()

    def observe(*args, **kwargs):
        acces["registre"] += 1
        return Observe(original(*args, **kwargs))

    monkeypatch.setattr(outils, "_registre_de_l_appel", observe)
    before = _tables()
    with contexte.appele_par_appareil(ADMIN):
        response = executer_atomique(monde, ARGS)
    assert _tables() == before
    assert response["ok"] and response["resultat"].get("accepte") is False, {
        "response": response,
        "source_accesses": acces,
    }
    assert response["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert acces == {"registre": 0, "lire": 0}


def test_admin_valide_et_agent_conservent_calcul_identique(monde):
    before = _tables()
    with contexte.appele_par_appareil(ADMIN):
        appareil = executer_atomique(monde, ARGS)
    interne = executer_atomique(monde, ARGS)
    assert appareil == interne and appareil["ok"] and appareil["resultat"]["accepte"]
    assert _tables() == before
