"""Appairage d'appareil (ADR-0009 §5, T1.4-c2) : `opsys.appareils`."""

from __future__ import annotations

import pytest

from opsys import appareils, identite

FICTIF = True  # tout appareil/identifiant ci-dessous est fictif (AGENTS.md)

MOT_DE_PASSE = "un-mot-de-passe-solide-123"


def _creer(cnx, identifiant, roles):
    return identite.creer_personne(cnx, identifiant, identifiant.title(), MOT_DE_PASSE, roles)


def test_roles_appareil_est_le_sous_ensemble_documente():
    """`ROLES_APPAREIL` = type `Profil` du mobile (`mobile/src/roles/types.ts`) moins `client` :
    ni `nathan_owner` (bloquerait le routage app, `evaluerGarde` fail-closed) ni les rôles sans
    profil mobile (`finance`/`manager`/`system_agent`)."""
    assert frozenset({"admin", "employee", "seller"}) == appareils.ROLES_APPAREIL
    assert appareils.ROLES_APPAREIL <= identite.ROLES
    assert identite.Role.NATHAN_OWNER.value not in appareils.ROLES_APPAREIL
    assert identite.Role.CLIENT.value not in appareils.ROLES_APPAREIL


def test_appairer_exige_que_la_personne_porte_deja_le_role(session):
    with session() as cnx:
        _creer(cnx, "employe1", ["employee"])
        with pytest.raises(ValueError, match="ne porte pas le rôle"):
            appareils.appairer(cnx, "tel-fictif-1", "employe1", "admin")


def test_appairer_refuse_un_role_hors_du_sous_ensemble_appareil(session):
    with session() as cnx:
        _creer(cnx, "financier1", ["finance"])
        with pytest.raises(ValueError, match="rôle d'appareil invalide"):
            appareils.appairer(cnx, "tel-fictif-2", "financier1", "finance")


def test_appairer_refuse_une_personne_inconnue_ou_inactive(session):
    with session() as cnx:
        with pytest.raises(ValueError, match="inconnue ou inactive"):
            appareils.appairer(cnx, "tel-fictif-3", "fantome", "employee")
        _creer(cnx, "employe2", ["employee"])
        identite.activer(cnx, "employe2", False)
        with pytest.raises(ValueError, match="inconnue ou inactive"):
            appareils.appairer(cnx, "tel-fictif-3", "employe2", "employee")


def test_appairer_puis_lire(session):
    with session() as cnx:
        _creer(cnx, "vendeur1", ["seller"])
        a = appareils.appairer(cnx, "tel-fictif-4", "vendeur1", "seller")
        assert (a.identifiant, a.personne, a.role) == ("tel-fictif-4", "vendeur1", "seller")
        relu = appareils.appareil(cnx, "tel-fictif-4")
        assert relu == a
        assert appareils.appareil(cnx, "tel-inconnu") is None
        assert appareils.lister(cnx) == [a]


def test_reappairer_remplace_la_ligne_existante(session):
    """Changement de téléphone ou de rôle : ré-appairer le même identifiant, pas un doublon."""
    with session() as cnx:
        _creer(cnx, "employe3", ["employee", "admin"])
        appareils.appairer(cnx, "tel-fictif-5", "employe3", "employee")
        reappaire = appareils.appairer(cnx, "tel-fictif-5", "employe3", "admin")
        assert reappaire.role == "admin"
        assert len(appareils.lister(cnx)) == 1
        assert appareils.appareil(cnx, "tel-fictif-5").role == "admin"


def test_revoquer(session):
    with session() as cnx:
        _creer(cnx, "employe4", ["employee"])
        appareils.appairer(cnx, "tel-fictif-6", "employe4", "employee")
        appareils.revoquer(cnx, "tel-fictif-6")
        assert appareils.appareil(cnx, "tel-fictif-6") is None
        with pytest.raises(KeyError, match="appareil inconnu"):
            appareils.revoquer(cnx, "tel-fictif-6")


def test_vers_json_ne_porte_aucun_secret(session):
    with session() as cnx:
        _creer(cnx, "admin-test", ["admin"])
        a = appareils.appairer(cnx, "tel-fictif-7", "admin-test", "admin")
    assert appareils.vers_json(a) == {
        "identifiant": "tel-fictif-7", "personne": "admin-test", "role": "admin",
        "appaireLe": a.appaire_le,
    }


def test_appareil_du_proprietaire_est_appaire_admin_pas_nathan_owner(session):
    """Décision T1.4-c2 (alignement mobile) : nathan_owner ne peut PAS être le rôle d'un jeton
    d'appareil (le type `Profil` du mobile n'en a pas). L'appareil du propriétaire porte donc
    `admin` — ce qui fonctionne tant que la personne porte elle-même ce rôle, même si elle porte
    AUSSI nathan_owner ; sa portée N5 vient de la personne (`opsys/personne`), jamais du jeton."""
    with session() as cnx:
        _creer(cnx, "nathan", ["nathan_owner", "admin"])
        with pytest.raises(ValueError, match="rôle d'appareil invalide"):
            appareils.appairer(cnx, "tel-fictif-nathan", "nathan", "nathan_owner")
        a = appareils.appairer(cnx, "tel-fictif-nathan", "nathan", "admin")
        assert a.role == "admin"
