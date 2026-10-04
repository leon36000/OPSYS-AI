"""R44a : provenance réelle de la marque, sans remplacer son chargeur."""

import json

import pytest
import yaml
from m7_marketing.brand import profil_client, registre
from sqlalchemy import update

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES


@pytest.fixture(autouse=True)
def _base_isolee(monkeypatch):
    monkeypatch.delenv(stockage.ENV_URL, raising=False)


def _profil():
    return {
        "name": "Entreprise fictive R44",
        "tagline": "Travaux avec soin",
        "tone": "factuel",
        "colors": ["#123456"],
        "langue": "fr",
        "site_url": "https://exemple-fictif.ca/",
    }


def test_canonique_prioritaire_et_preuve_reproductible(session, tmp_path, monkeypatch):
    legacy = tmp_path / "profile.yaml"
    legacy.write_text(yaml.safe_dump({**_profil(), "name": "Legacy fictif"}), encoding="utf-8")
    monkeypatch.setattr(profil_client, "_PROFIL_PAR_DEFAUT", legacy)
    with session():
        registre.enregistrer(_profil(), "proprietaire-fictif", "2026-10-02T12:00:00+00:00")
        snapshot = registre.lire_snapshot_marque()
        assert snapshot["profil"] == _profil()
        assert snapshot["preuve"]["source"] == "brand_profiles"
        assert snapshot["preuve"]["revision"] == 1
        assert len(snapshot["preuve"]["sha256"]) == 64
    with session():
        assert registre.lire_snapshot_marque() == snapshot


def test_canonique_altere_refuse_sans_repli_yaml(session, tmp_path, monkeypatch):
    legacy = tmp_path / "profile.yaml"
    legacy.write_text(yaml.safe_dump(_profil()), encoding="utf-8")
    monkeypatch.setattr(profil_client, "_PROFIL_PAR_DEFAUT", legacy)
    with session() as cnx:
        registre.enregistrer(_profil(), "proprietaire-fictif", "2026-10-02T12:00:00+00:00")
        ligne = list(stockage.maillons(registre.DEPARTEMENT, registre.REGISTRE))[0]
        ligne["profil"]["name"] = "Autre marque fictive"
        cnx.execute(
            update(REGISTRES)
            .where(REGISTRES.c.departement == registre.DEPARTEMENT, REGISTRES.c.registre == registre.REGISTRE)
            .values(maillon=codec.encoder(ligne))
        )
        snapshot = registre.lire_snapshot_marque()
        assert snapshot["statut"] == "refuse"
        assert snapshot["profil"] is None
        assert "preuve" not in snapshot


def test_legacy_uniquement_sans_canonique(session, tmp_path, monkeypatch):
    legacy = tmp_path / "profile.yaml"
    legacy.write_text(yaml.safe_dump(_profil()), encoding="utf-8")
    monkeypatch.setattr(profil_client, "_PROFIL_PAR_DEFAUT", legacy)
    with session():
        snapshot = registre.lire_snapshot_marque()
        assert snapshot["statut"] == "configure"
        assert snapshot["preuve"]["source"] == "yaml_legacy"
        assert snapshot["preuve"]["revision"] is None
        assert snapshot["avertissements"]
        assert len(stockage.maillons(registre.DEPARTEMENT, registre.REGISTRE)) == 0


@pytest.mark.parametrize("contenu", ["name: [", "- liste", "name: null"])
def test_yaml_malforme_diagnostic_metier(session, tmp_path, monkeypatch, contenu):
    legacy = tmp_path / "profile.yaml"
    legacy.write_text(contenu, encoding="utf-8")
    monkeypatch.setattr(profil_client, "_PROFIL_PAR_DEFAUT", legacy)
    with session():
        snapshot = registre.lire_snapshot_marque()
        assert snapshot["statut"] in {"a_configurer", "refuse"}
        assert snapshot["profil"] is None


def test_erreur_lecture_yaml_diagnostic_metier(session, tmp_path, monkeypatch):
    monkeypatch.setattr(profil_client, "_PROFIL_PAR_DEFAUT", tmp_path)
    with session():
        assert registre.lire_snapshot_marque()["statut"] == "refuse"


@pytest.mark.parametrize(
    "options",
    [
        {"garanties_validees": "garantie inventée"},
        {"heures_publication": {"facebook": "25:00"}},
        {"site_url": "http://exemple-fictif.ca/"},
        {"extra": float("nan")},
    ],
)
def test_options_non_exploitables_refusees_avant_append(session, options):
    with session():
        reponse = registre.enregistrer({**_profil(), **options}, "proprietaire-fictif", "2026-10-02T12:00:00+00:00")
        assert reponse["statut"] != "configure", json.dumps(reponse)
        assert len(stockage.maillons(registre.DEPARTEMENT, registre.REGISTRE)) == 0


@pytest.mark.parametrize(
    "champ,valeur",
    [
        ("hash_maillon", "f" * 64),
        ("hash_precedent", "f" * 64),
        ("revision", True),
        ("type", "autre_type"),
        ("hash_maillon", None),
    ],
)
def test_preuve_canonique_invalide_fermee(session, champ, valeur):
    with session() as cnx:
        registre.enregistrer(_profil(), "proprietaire-fictif", "2026-10-02T12:00:00+00:00")
        ligne = list(stockage.maillons(registre.DEPARTEMENT, registre.REGISTRE))[0]
        if valeur is None:
            ligne.pop(champ)
        else:
            ligne[champ] = valeur
        cnx.execute(
            update(REGISTRES)
            .where(REGISTRES.c.departement == registre.DEPARTEMENT, REGISTRES.c.registre == registre.REGISTRE)
            .values(maillon=codec.encoder(ligne))
        )
        assert registre.lire_snapshot_marque()["statut"] == "refuse"
        assert registre.enregistrer(_profil(), "proprietaire-fictif", "2026-10-02T13:00:00+00:00")["statut"] == "refuse"
        assert len(stockage.maillons(registre.DEPARTEMENT, registre.REGISTRE)) == 1


@pytest.mark.parametrize(
    "texte", ['{"__opsys__":"dict","v":null}', '{"__opsys__":"decimal","v":"invalide"}', "null", '{"revision":1}', "{"]
)
def test_codec_canonique_corrompu_est_un_refus_metier(session, texte):
    with session() as cnx:
        registre.enregistrer(_profil(), "proprietaire-fictif", "2026-10-02T12:00:00+00:00")
        cnx.execute(
            update(REGISTRES)
            .where(REGISTRES.c.departement == registre.DEPARTEMENT, REGISTRES.c.registre == registre.REGISTRE)
            .values(maillon=texte)
        )
        assert registre.lire_snapshot_marque()["statut"] == "refuse"


def test_ligne_historique_valide_preservee_sans_attestation_fictive(session):
    ancien = {
        "type": "brand_profile",
        "revision": 1,
        "profil": {**_profil(), "extra_historique": {"z": []}},
        "configure_par": "proprietaire-fictif",
        "horodatage": "2026-09-30T12:00:00+00:00",
    }
    with session():
        stockage.maillons(registre.DEPARTEMENT, registre.REGISTRE).append(ancien)
        snapshot = registre.lire_snapshot_marque()
        assert snapshot["statut"] == "configure" and snapshot["preuve"]["revision"] == 1
        assert "sans empreinte" in " ".join(snapshot["avertissements"])
        assert registre.enregistrer(_profil(), "proprietaire-fictif", "2026-10-02T12:00:00+00:00")["revision"] == 2
        assert list(stockage.maillons(registre.DEPARTEMENT, registre.REGISTRE))[0] == ancien
        assert registre.lire_snapshot_marque()["preuve"]["revision"] == 2
