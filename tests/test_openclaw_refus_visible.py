"""Un refus de `openclaw configurer` (surcharges `avatars` invalides) est visible pour l'admin, une fois par état.

Sur le VPS, `deploy/entrypoint.sh` rejoue la commande toutes les 300 s et ignore son code de sortie ; la
configuration précédente reste en place. Ces tests rejouent la commande comme la boucle le fait, et vérifient :
une seule ligne de journal par état distinct, une ligne de rétablissement, la projection de la console
(`/connecteurs`) et l'absence du chemin ou du contenu du profil dans ce que l'admin voit.

Noms et surcharges : données FICTIVES ; dossier de configuration jetable.
"""

from __future__ import annotations

import yaml
from agents_base_qa import provisionner_base_qa
from sqlalchemy import select

from opsys import cli, modeles, openclaw_refus, taxonomie
from opsys.console import configuration_lecture
from opsys.console.connecteurs_ui import configuration_contenu
from opsys.departements import charger_departements
from opsys.stockage.schema import JOURNAL

FICTIF = True

PALIERS = {
    "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "fort": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
}
SURCHARGE_VALIDE = {"avatars": {"m01-front-office": {"nom": "Julie"}}}
SURCHARGE_CHIFFRE = {"avatars": {"m01-front-office": {"nom": "Julie2"}}}
SURCHARGE_INCONNUE = {"avatars": {"m99-inconnu": {"nom": "Julie"}}}


def _preparer(session, monkeypatch, tmp_path):
    monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", "http://embeddings-test:11434/v1")
    monkeypatch.setenv("OPSYS_EMBEDDINGS_MODELE", "bge-m3")
    modeles.enregistrer_paliers(PALIERS)
    provisionner_base_qa(session, charger_departements())
    return tmp_path / "oc"


def _profil(contenu) -> None:
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")


def _configurer(config) -> int:
    return cli.main(["openclaw", "configurer", "--config-dir", str(config)])


def _lignes(session):
    with session() as cnx:
        return cnx.execute(
            select(JOURNAL.c.action, JOURNAL.c.cible, JOURNAL.c.par, JOURNAL.c.details)
            .where(JOURNAL.c.action.like("openclaw.configuration.%"))
            .order_by(JOURNAL.c.id)
        ).all()


def _projection(session):
    with session() as cnx:
        return configuration_lecture.lire(cnx, charger_departements(), {})


def test_refus_rejoue_en_boucle_n_ecrit_qu_une_alerte_par_etat_puis_un_retablissement(
    session, monkeypatch, tmp_path, capsys,
):
    config = _preparer(session, monkeypatch, tmp_path)
    _profil(SURCHARGE_VALIDE)
    assert _configurer(config) == 0
    assert _lignes(session) == []
    assert _projection(session)["generation_core"] == {"statut": "aucun_refus_consigne"}
    agents_avant = (config / "opsys" / "agents.json").read_bytes()
    capsys.readouterr()

    _profil(SURCHARGE_CHIFFRE)
    for _ in range(3):  # trois tours de la boucle de 300 s
        assert _configurer(config) == 2
        assert "avatars des départements invalides, rien n'est écrit" in capsys.readouterr().err
    assert (config / "opsys" / "agents.json").read_bytes() == agents_avant  # le core garde l'ancienne
    lignes = _lignes(session)
    assert [(ligne.action, ligne.cible, ligne.par) for ligne in lignes] == [
        (openclaw_refus.ACTION_REFUS, "avatars", "openclaw-configurer"),
    ]
    assert "Julie2" not in lignes[0].details and "entreprise.yaml" not in lignes[0].details

    generation = _projection(session)["generation_core"]
    assert generation["statut"] == "refusee" and generation["categorie"] == "surcharges"
    page = configuration_contenu(_projection(session), "/console")
    assert "message-erreur" in page and "Configuration du core refusée depuis" in page
    assert "conserve la configuration précédente" in page and "Julie2" not in page

    _profil(SURCHARGE_INCONNUE)  # nouvel état distinct : une seconde alerte, une seule
    assert _configurer(config) == 2
    assert _configurer(config) == 2
    assert [ligne.action for ligne in _lignes(session)] == [openclaw_refus.ACTION_REFUS] * 2

    _profil(SURCHARGE_VALIDE)
    assert _configurer(config) == 0
    assert _configurer(config) == 0
    assert [ligne.action for ligne in _lignes(session)] == [
        openclaw_refus.ACTION_REFUS, openclaw_refus.ACTION_REFUS, openclaw_refus.ACTION_RETABLIE,
    ]
    assert _projection(session)["generation_core"] == {"statut": "aucun_refus_consigne"}
    assert "Configuration du core refusée" not in configuration_contenu(_projection(session), "/console")

    _profil(SURCHARGE_CHIFFRE)  # le même état revenu après un rétablissement est une nouvelle alerte
    assert _configurer(config) == 2
    assert [ligne.action for ligne in _lignes(session)][-1] == openclaw_refus.ACTION_REFUS
    assert len(_lignes(session)) == 4


def test_une_panne_du_journal_ne_masque_ni_le_refus_ni_son_code(session, monkeypatch, tmp_path, capsys):
    config = _preparer(session, monkeypatch, tmp_path)
    _profil(SURCHARGE_CHIFFRE)

    def panne(*_args, **_kwargs):
        raise RuntimeError("journal indisponible (fictif)")

    monkeypatch.setattr(openclaw_refus, "consigner_refus", panne)
    assert _configurer(config) == 2
    erreur = capsys.readouterr().err
    assert "avatars des départements invalides, rien n'est écrit" in erreur
    assert "état de la configuration non consigné dans le journal (RuntimeError)" in erreur
    assert not (config / "opsys").exists()


def test_un_refus_hors_avatars_n_est_pas_consigne_comme_refus_d_avatars(session, monkeypatch, tmp_path, capsys):
    """Les autres refus (transport, paliers…) gardent leur chemin : rien n'est attribué aux avatars à tort."""
    config = _preparer(session, monkeypatch, tmp_path)
    _profil(SURCHARGE_VALIDE)
    assert cli.main(["openclaw", "configurer", "--config-dir", str(config),
                     "--url-mcp", "http://exemple-fictif.test/mcp"]) == 2
    assert _lignes(session) == []
