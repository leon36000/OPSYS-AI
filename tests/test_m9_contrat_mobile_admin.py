"""Contrat serveur M9 pour l'admin mobile : portées lues du manifeste réel, quatre profils, sorties bornées (fictif).

Ce test ne ferme pas M9.22 : l'écran, le réseau interrompu et la vue périmée côté app restent à la phase mobile finale.
"""

from __future__ import annotations

import json

import pytest

from opsys import contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements

FICTIF = True
M9 = "m09-strategic-intelligence"
LECTURES_MOBILE = {
    "m9_salle_de_guerre": {"reference": "2026-10-21T14:00:00Z"},
    "m9_radar_risques": {"connaissance": "2026-10-21T14:00:00Z"},
    "m9_lire_actions": {},
    "m9_lire_veille": {"connaissance": "2026-10-21T14:00:00Z"},
}
BORNE_TELEPHONE = 5900


@pytest.fixture
def capacites(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'mobile.db'}")
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur", "mot-de-passe-vendeur-123", ["seller"])
        identite.creer_personne(cnx, "employe.fictif", "Employé", "mot-de-passe-employe-123", ["employee"])
        identite.creer_personne(cnx, "client.fictif", "Client", "mot-de-passe-client-1234", ["client"])
    yield Capacites(charger_departements(), stockage.transaction, filtre={M9}, memoire=False)
    stockage.liberer()


IDENTIFIANTS = {
    "admin": "admin.fictif",
    "seller": "vendeur.fictif",
    "employee": "employe.fictif",
    "client": "client.fictif",
}


def _appel(c, nom, arguments, profil):
    with contexte.appele_par_appareil(IdentiteAppelante(IDENTIFIANTS[profil], profil, source="appareil")):
        return c.appeler(nom, arguments)


def test_aucun_outil_m9_n_est_ouvert_a_un_profil_autre_que_l_admin_sur_appareil():
    outils = charger_departements()[M9].charger_outils()
    assert len(outils) >= 40
    trop_larges = {o.nom: sorted(o.roles_appareil) for o in outils if not set(o.roles_appareil or ()) <= {"admin"}}
    assert trop_larges == {}, f"outil M9 ouvert à un autre profil que l'admin : {trop_larges}"
    admin = {o.nom for o in outils if set(o.roles_appareil or ()) == {"admin"}}
    assert {*LECTURES_MOBILE} <= admin, "les lectures du contrat mobile doivent être déclarées admin"


@pytest.mark.parametrize("nom", sorted(LECTURES_MOBILE))
def test_lecture_admin_acceptee_bornee_et_trois_autres_profils_refuses(capacites, nom):
    arguments = LECTURES_MOBILE[nom]
    admin = _appel(capacites, nom, arguments, "admin")
    assert admin["ok"] is True and admin["resultat"]["accepte"] is True, admin
    assert len(json.dumps(admin["resultat"], ensure_ascii=False)) <= BORNE_TELEPHONE, (
        "sortie trop grosse pour un téléphone"
    )
    for profil in ("seller", "employee", "client"):
        refus = _appel(capacites, nom, arguments, profil)
        assert refus["ok"] is False or refus["resultat"].get("accepte") is False, (nom, profil)
        assert "faits" not in json.dumps(refus) and "vue" not in refus.get("resultat", {}), (nom, profil)
