"""Identité (ADR-0009 §5) : mots de passe, personnes, rôles, CLI `opsys personnes`."""

from __future__ import annotations

import json

import pytest
from memoire.doubles import postgres_ephemere, raison_sans_docker

from opsys import cli, identite, stockage

# -- mots de passe (hashlib.scrypt) ---------------------------------------------------------------


def test_hachage_jamais_le_clair_et_verification_correcte():
    hachage = identite.hacher_mot_de_passe("un-mot-de-passe-solide-123")
    assert "un-mot-de-passe-solide-123" not in hachage
    assert hachage.startswith("scrypt$")
    assert identite.verifier_mot_de_passe("un-mot-de-passe-solide-123", hachage)
    assert not identite.verifier_mot_de_passe("un-autre-mot-de-passe-123", hachage)


def test_deux_hachages_du_meme_mot_de_passe_different(monkeypatch):
    """Sel aléatoire par personne : même mot de passe, empreintes différentes."""
    a = identite.hacher_mot_de_passe("un-mot-de-passe-solide-123")
    b = identite.hacher_mot_de_passe("un-mot-de-passe-solide-123")
    assert a != b
    assert identite.verifier_mot_de_passe("un-mot-de-passe-solide-123", a)
    assert identite.verifier_mot_de_passe("un-mot-de-passe-solide-123", b)


def test_mot_de_passe_trop_court_refuse():
    with pytest.raises(ValueError, match="12 caractères"):
        identite.hacher_mot_de_passe("court")


@pytest.mark.parametrize("empreinte", ["", "pas-du-scrypt", "scrypt$x$y", "scrypt$16384$8$1$zz$zz",
                                       "bcrypt$16384$8$1$" + "00" * 16 + "$" + "00" * 32])
def test_empreinte_mal_formee_refuse_sans_lever(empreinte):
    assert identite.verifier_mot_de_passe("peu-importe-1234", empreinte) is False


# -- personnes et rôles ----------------------------------------------------------------------------


def test_creer_personne_et_authentifier(session):
    with session() as cnx:
        p = identite.creer_personne(cnx, "alice", "Alice Tremblay", "un-mot-de-passe-solide-123", ["seller"])
    assert (p.identifiant, p.nom, p.actif, p.roles) == ("alice", "Alice Tremblay", True, frozenset({"seller"}))
    with session() as cnx:
        assert identite.authentifier(cnx, "alice", "un-mot-de-passe-solide-123") is not None
        assert identite.authentifier(cnx, "alice", "mauvais-mot-de-passe-x") is None
        assert identite.authentifier(cnx, "fantome", "peu-importe-1234-xx") is None


def test_personne_inactive_non_active_et_non_authentifiee(session):
    with session() as cnx:
        identite.creer_personne(cnx, "bob", "Bob Gagnon", "un-mot-de-passe-solide-123", ["employee"],
                                actif=False)
        assert identite.personne(cnx, "bob").actif is False
        assert identite.personne_active(cnx, "bob") is None
        assert identite.authentifier(cnx, "bob", "un-mot-de-passe-solide-123") is None
        identite.activer(cnx, "bob", True)
        assert identite.personne_active(cnx, "bob") is not None
        assert identite.authentifier(cnx, "bob", "un-mot-de-passe-solide-123") is not None


def test_roles_ajout_retrait_idempotents(session):
    with session() as cnx:
        identite.creer_personne(cnx, "carla", "Carla Roy", "un-mot-de-passe-solide-123", [])
        identite.ajouter_role(cnx, "carla", "finance")
        identite.ajouter_role(cnx, "carla", "finance")  # idempotent, pas d'erreur
        assert identite.personne(cnx, "carla").roles == frozenset({"finance"})
        identite.retirer_role(cnx, "carla", "finance")
        identite.retirer_role(cnx, "carla", "finance")  # idempotent
        assert identite.personne(cnx, "carla").roles == frozenset()


def test_changer_mot_de_passe(session):
    with session() as cnx:
        identite.creer_personne(cnx, "dan", "Dan Roussel", "ancien-mot-de-passe-123", [])
        identite.changer_mot_de_passe(cnx, "dan", "nouveau-mot-de-passe-456")
        assert identite.authentifier(cnx, "dan", "ancien-mot-de-passe-123") is None
        assert identite.authentifier(cnx, "dan", "nouveau-mot-de-passe-456") is not None


@pytest.mark.parametrize(
    ("action", "args"),
    [("ajouter_role", ("fantome", "admin")), ("retirer_role", ("fantome", "admin")),
     ("activer", ("fantome", True)), ("changer_mot_de_passe", ("fantome", "un-mot-de-passe-solide-123"))],
)
def test_actions_sur_personne_inconnue_refusees(session, action, args):
    with session() as cnx, pytest.raises(KeyError, match="personne inconnue"):
        getattr(identite, action)(cnx, *args)


@pytest.mark.parametrize(
    ("identifiant", "message"),
    [("", "identifiant invalide"), ("Bad-Id", "identifiant invalide"), ("1abc", "identifiant invalide"),
     ("a", "identifiant invalide"), ("un identifiant avec espace", "identifiant invalide")],
)
def test_identifiant_invalide_refuse(session, identifiant, message):
    with session() as cnx, pytest.raises(ValueError, match=message):
        identite.creer_personne(cnx, identifiant, "Nom", "un-mot-de-passe-solide-123", [])


def test_identifiant_deja_utilise_refuse(session):
    with session() as cnx:
        identite.creer_personne(cnx, "gaby", "Gaby", "un-mot-de-passe-solide-123", [])
        with pytest.raises(ValueError, match="déjà utilisé"):
            identite.creer_personne(cnx, "gaby", "Gaby Autre", "un-autre-mot-de-passe-456", [])
        assert identite.personne(cnx, "gaby").nom == "Gaby"  # rien écrasé


def test_role_inconnu_refuse_a_la_creation_et_a_l_ajout(session):
    with session() as cnx:
        with pytest.raises(ValueError, match="rôle"):
            identite.creer_personne(cnx, "eve", "Eve Bouchard", "un-mot-de-passe-solide-123", ["superviseur"])
        identite.creer_personne(cnx, "eve", "Eve Bouchard", "un-mot-de-passe-solide-123", [])
        with pytest.raises(ValueError, match="rôle"):
            identite.ajouter_role(cnx, "eve", "superviseur")


def test_lister_personnes_triees(session):
    with session() as cnx:
        identite.creer_personne(cnx, "zoe", "Zoé", "un-mot-de-passe-solide-123", ["client"])
        identite.creer_personne(cnx, "adam", "Adam", "un-mot-de-passe-solide-123", ["employee"])
        personnes = identite.lister(cnx)
    assert [p.identifiant for p in personnes] == ["adam", "zoe"]


def test_vers_json_ne_contient_jamais_le_mot_de_passe(session):
    with session() as cnx:
        p = identite.creer_personne(cnx, "finn", "Finn", "un-mot-de-passe-solide-123", ["manager"])
    donnees = identite.vers_json(p)
    assert donnees == {"identifiant": "finn", "nom": "Finn", "actif": True, "roles": ["manager"]}
    assert "mot_de_passe" not in json.dumps(donnees) and "solide" not in json.dumps(donnees)


def test_roles_fermes_alignes_sur_adr_0009():
    assert {"nathan_owner", "admin", "finance", "manager", "seller", "employee", "client",
                              "system_agent"} == identite.ROLES


@pytest.mark.skipif(raison_sans_docker() is not None, reason=str(raison_sans_docker()))
def test_parite_postgresql(monkeypatch):
    """Même mécanisme que `test_stockage.py::test_postgresql_se_comporte_comme_sqlite` : personnes,
    rôles et mots de passe se comportent à l'identique sur PostgreSQL."""
    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        try:
            stockage.migrer(url)
            with stockage.transaction() as cnx:
                identite.creer_personne(cnx, "greg", "Greg Levesque", "un-mot-de-passe-solide-123",
                                        ["nathan_owner", "finance"])
            with stockage.transaction() as cnx:
                p = identite.authentifier(cnx, "greg", "un-mot-de-passe-solide-123")
                assert p is not None and p.roles == frozenset({"nathan_owner", "finance"})
                identite.retirer_role(cnx, "greg", "finance")
                assert identite.personne(cnx, "greg").roles == frozenset({"nathan_owner"})
                identite.activer(cnx, "greg", False)
                assert identite.authentifier(cnx, "greg", "un-mot-de-passe-solide-123") is None
        finally:
            stockage.liberer()


# -- CLI `opsys personnes` -------------------------------------------------------------------------


def _sortie(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_cli_creer_lister_roles_activer_mot_de_passe(session, monkeypatch, capsys):
    monkeypatch.setenv(cli.ENV_MOT_DE_PASSE_PERSONNE, "un-mot-de-passe-solide-123")
    assert cli.main(["personnes", "creer", "helene", "--nom", "Hélène Fortin", "--role", "nathan_owner"]) == 0
    cree = _sortie(capsys)
    assert cree == {"identifiant": "helene", "nom": "Hélène Fortin", "actif": True, "roles": ["nathan_owner"]}

    assert cli.main(["personnes", "lister"]) == 0
    assert _sortie(capsys) == [cree]

    assert cli.main(["personnes", "roles", "helene", "--ajouter-role", "finance"]) == 0
    assert _sortie(capsys)["roles"] == ["finance", "nathan_owner"]
    assert cli.main(["personnes", "roles", "helene", "--retirer-role", "finance"]) == 0
    assert _sortie(capsys)["roles"] == ["nathan_owner"]

    assert cli.main(["personnes", "desactiver", "helene"]) == 0
    assert _sortie(capsys) == {"identifiant": "helene", "actif": False}
    assert cli.main(["personnes", "activer", "helene"]) == 0
    assert _sortie(capsys) == {"identifiant": "helene", "actif": True}

    monkeypatch.setenv(cli.ENV_MOT_DE_PASSE_PERSONNE, "nouveau-mot-de-passe-456")
    assert cli.main(["personnes", "mot-de-passe", "helene"]) == 0
    assert _sortie(capsys) == {"identifiant": "helene", "mot_de_passe": "modifié"}
    from opsys import etat
    with etat.session() as cnx:
        assert identite.authentifier(cnx, "helene", "nouveau-mot-de-passe-456") is not None
        assert identite.authentifier(cnx, "helene", "un-mot-de-passe-solide-123") is None


def test_cli_creer_sans_nom_refuse(session, monkeypatch, capsys):
    monkeypatch.setenv(cli.ENV_MOT_DE_PASSE_PERSONNE, "un-mot-de-passe-solide-123")
    assert cli.main(["personnes", "creer", "irene"]) == 2


def test_cli_identifiant_requis_hors_lister(session, capsys):
    assert cli.main(["personnes", "activer"]) == 2


def test_cli_roles_personne_inconnue(session, capsys):
    # Cohérent avec le reste de la CLI (`cmd_mode`, `cmd_approbations`) : une KeyError/ValueError du
    # socle n'est pas capturée ici, elle remonte telle quelle.
    with pytest.raises(KeyError, match="personne inconnue"):
        cli.main(["personnes", "roles", "fantome", "--ajouter-role", "admin"])
    # Sans --ajouter-role ni --retirer-role, l'action ne fait qu'afficher : retour propre, 1.
    assert cli.main(["personnes", "roles", "fantome"]) == 1


def test_cli_mot_de_passe_jamais_en_argument():
    """Aucun `--mot-de-passe` (ou variante) n'existe sur `opsys personnes` : lu par `getpass` ou
    OPSYS_PERSONNE_MOT_DE_PASSE seulement (jamais en clair dans l'historique du shell)."""
    with pytest.raises(SystemExit):
        cli.construire_parseur().parse_args(["personnes", "creer", "jules", "--nom", "Jules",
                                             "--mot-de-passe", "peu-importe"])
