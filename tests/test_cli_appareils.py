"""`opsys appareils ...` : attribution personne/rôle d'un appareil déjà approuvé côté core
(ADR-0009 §5, PLAN T1.4-c4). Contrat : `docs/architecture/IDEMPOTENCE.md` §7 bis.

Preuve que la commande fait bien les DEUX choses attendues (fixer personne/rôle ET régénérer le
fragment `opsys/appareils.json`), pas seulement l'une des deux — `opsys.appareils.appairer` est
déjà testée seule dans `tests/test_appareils.py`, et `openclaw.ecrire_appareils` dans
`tests/test_openclaw_roles.py` ; ce fichier teste leur câblage par la CLI, telle qu'un opérateur
l'appellerait réellement.
"""

from __future__ import annotations

import json

import pytest

from opsys import appareils, cli, identite

FICTIF = True  # tout identifiant ci-dessous est fictif (AGENTS.md)

MOT_DE_PASSE = "un-mot-de-passe-solide-123"


def _creer(cnx, identifiant, roles):
    return identite.creer_personne(cnx, identifiant, identifiant.title(), MOT_DE_PASSE, roles)


def test_appairer_fixe_la_personne_et_le_role_et_regenere_le_fragment(session, tmp_path):
    with session() as cnx:
        _creer(cnx, "jdupont", ["employee"])
    config_dir = tmp_path / "config"

    code = cli.main([
        "appareils", "appairer", "tel-fictif-cli-1",
        "--personne", "jdupont", "--role", "employee",
        "--config-dir", str(config_dir),
    ])

    assert code == 0
    fragment = json.loads((config_dir / "opsys" / "appareils.json").read_text(encoding="utf-8"))
    assert fragment == {"appareils": {"tel-fictif-cli-1": {"personne": "jdupont", "role": "employee"}}}
    with session() as cnx:
        appareil = appareils.appareil(cnx, "tel-fictif-cli-1")
    assert appareil is not None
    assert (appareil.personne, appareil.role) == ("jdupont", "employee")


def test_reappairer_change_le_role_et_regenere_le_fragment(session, tmp_path):
    with session() as cnx:
        _creer(cnx, "nathan", ["nathan_owner", "admin"])
    config_dir = tmp_path / "config"

    premier = cli.main([
        "appareils", "appairer", "tel-fictif-cli-2",
        "--personne", "nathan", "--role", "admin",
        "--config-dir", str(config_dir),
    ])
    assert premier == 0
    fragment_1 = json.loads((config_dir / "opsys" / "appareils.json").read_text(encoding="utf-8"))
    assert fragment_1 == {"appareils": {"tel-fictif-cli-2": {"personne": "nathan", "role": "admin"}}}

    with session() as cnx:
        _creer(cnx, "vendeur1", ["seller"])
    second = cli.main([
        "appareils", "appairer", "tel-fictif-cli-2",
        "--personne", "vendeur1", "--role", "seller",
        "--config-dir", str(config_dir),
    ])
    assert second == 0
    fragment_2 = json.loads((config_dir / "opsys" / "appareils.json").read_text(encoding="utf-8"))
    assert fragment_2 == {"appareils": {"tel-fictif-cli-2": {"personne": "vendeur1", "role": "seller"}}}


def test_appairer_refuse_si_la_personne_ne_porte_pas_deja_le_role(session, tmp_path):
    """Fail-closed jusque dans la CLI : ValueError d'`appareils.appairer` propagée, rien écrit."""
    with session() as cnx:
        _creer(cnx, "employe1", ["employee"])
    config_dir = tmp_path / "config"

    with pytest.raises(ValueError, match="ne porte pas le rôle"):
        cli.main([
            "appareils", "appairer", "tel-fictif-cli-3",
            "--personne", "employe1", "--role", "admin",
            "--config-dir", str(config_dir),
        ])
    assert not (config_dir / "opsys" / "appareils.json").exists()


def test_appairer_exige_personne_et_role(session, tmp_path):
    config_dir = tmp_path / "config"
    code = cli.main([
        "appareils", "appairer", "tel-fictif-cli-4", "--config-dir", str(config_dir),
    ])
    assert code == 2
    assert not (config_dir / "opsys").exists()


def test_appairer_exige_un_identifiant(tmp_path):
    code = cli.main([
        "appareils", "appairer", "--personne", "jdupont", "--role", "employee",
        "--config-dir", str(tmp_path / "config"),
    ])
    assert code == 2


def test_lister(session, tmp_path):
    with session() as cnx:
        _creer(cnx, "jdupont", ["employee"])
    config_dir = tmp_path / "config"
    cli.main([
        "appareils", "appairer", "tel-fictif-cli-5",
        "--personne", "jdupont", "--role", "employee", "--config-dir", str(config_dir),
    ])

    code = cli.main(["appareils", "lister", "--config-dir", str(config_dir)])

    assert code == 0
    with session() as cnx:
        assert [a.identifiant for a in appareils.lister(cnx)] == ["tel-fictif-cli-5"]


def test_revoquer_regenere_le_fragment_sans_lappareil(session, tmp_path):
    with session() as cnx:
        _creer(cnx, "jdupont", ["employee"])
    config_dir = tmp_path / "config"
    cli.main([
        "appareils", "appairer", "tel-fictif-cli-6",
        "--personne", "jdupont", "--role", "employee", "--config-dir", str(config_dir),
    ])

    code = cli.main(["appareils", "revoquer", "tel-fictif-cli-6", "--config-dir", str(config_dir)])

    assert code == 0
    fragment = json.loads((config_dir / "opsys" / "appareils.json").read_text(encoding="utf-8"))
    assert fragment == {"appareils": {}}
    with session() as cnx:
        assert appareils.appareil(cnx, "tel-fictif-cli-6") is None
