"""Projection réelle bornée : canons fictifs, aucune configuration ou donnée métier écrite."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import event, update

from opsys import agents
from opsys.console import configuration_lecture as lecture
from opsys.departements import charger_departements
from opsys.stockage.schema import AGENTS_CONFIGURABLES


@pytest.fixture(autouse=True)
def _base_isolee(monkeypatch, opsys_home):
    monkeypatch.delenv("OPSYS_BASE_URL", raising=False)


def _profil(ident):
    return {
        "id": ident, "departement": "m03-estimation", "responsabilite": "Préparation fictive",
        "palier_modele": "standard", "outils": [], "budget_jour": 1000, "budget_mois": 10000,
        "limite_tours": 8, "limite_reessais": 2, "limite_concurrence": 1,
        "declencheurs": [{"type": "manuel"}],
    }


def _fichier(tmp_path, texte):
    path = tmp_path / "paliers-fictifs.yaml"
    path.write_text(texte, encoding="utf-8")
    return path


def test_profils_comptes_en_sql_et_resume_limite_sans_champs_libres(session, nathan, tmp_path):
    deps = charger_departements()
    with session() as cnx:
        for index in range(55):
            agents.creer(cnx, deps, _profil(f"fictif-{index:03}"), par=nathan,
                         mutation_id=f"creation-fictive-{index:03}")
        avant = cnx.exec_driver_sql("SELECT count(*) FROM journal").scalar()
        requetes = []

        def noter(_cnx, _cursor, statement, _parameters, _context, _many):
            requetes.append(statement)

        event.listen(cnx, "before_cursor_execute", noter)
        result = lecture.lire(cnx, deps, {}, _fichier(tmp_path, "paliers: {}\n"))
        event.remove(cnx, "before_cursor_execute", noter)
        assert cnx.exec_driver_sql("SELECT count(*) FROM journal").scalar() == avant
    assert result["profils"]["total"] == 55
    assert result["profils"]["retournes"] == 50
    assert result["profils"]["omis"] == 5
    m3 = next(d for d in result["departements"] if d["code"] == "M3")
    assert m3["specialistes"] == {"total": 55, "actifs": 0, "inactifs": 55}
    select_profils = [s.lower() for s in requetes if "agents_configurables" in s]
    assert any("count(" in s for s in select_profils)
    assert any("limit" in s for s in select_profils)
    assert all(not any(champ in s for champ in ("responsabilite", "outils", "declencheurs", "modifie_par"))
               for s in select_profils)
    assert "Préparation fictive" not in json.dumps(result, ensure_ascii=False)


def test_noms_de_references_sans_url_dsn_valeur_modele_ni_secret(session, tmp_path):
    paliers = _fichier(tmp_path, """paliers:
  standard:
    provider: custom
    model: modele-avec-sentinelle-secrete
    base_url: https://fictif.invalid/?token=sentinelle-url
    api_key_env: FICTIF_API_KEY
""")
    with session() as cnx:
        result = lecture.lire(cnx, charger_departements(), {"FICTIF_API_KEY": "sentinelle-cle"}, paliers)
    text = json.dumps(result, ensure_ascii=False)
    assert "FICTIF_API_KEY" in text
    assert all(s not in text for s in ("sentinelle-cle", "sentinelle-url", "fictif.invalid",
                                     "modele-avec-sentinelle-secrete", "base_url", "api_key_env"))
    tier = next(t for t in result["paliers"] if t["nom"] == "standard")
    assert tier["statut"] == "presence_declaree" and tier["authentification_distante"] == "non_verifiee"


def test_local_sans_cle_et_fichier_absent_restent_declaratifs(session, tmp_path):
    local = _fichier(tmp_path, "paliers:\n  local:\n    provider: custom\n    model: fictif\n    base_url: http://local.invalid/v1\n")
    with session() as cnx:
        result = lecture.lire(cnx, charger_departements(), {}, local)
        missing = lecture.lire(cnx, charger_departements(), {}, tmp_path / "absent.yaml")
    tier = next(t for t in result["paliers"] if t["nom"] == "local")
    assert tier["references_requises"] == [] and tier["statut"] == "presence_declaree"
    assert all(t["statut"] == "non_configure" for t in missing["paliers"])


@pytest.mark.parametrize("texte", [
    "paliers: {}\npaliers: {}\n",
    "paliers:\n  local:\n    provider: custom\n    provider: openai\n    model: fictif\n",
    "paliers:\n  fort:\n    provider: openai\n    model: .inf\n",
    "paliers:\n  fort:\n    provider: openai\n    model: .nan\n",
    "paliers:\n  fort:\n    provider: openai\n    model: 2026-10-02\n",
    "paliers: []\n",
    "paliers:\n  autre:\n    provider: openai\n    model: fictif\n",
    "paliers: {}\nsecret: sentinelle-privee\n",
    "paliers:\n  fort:\n    provider: openai\n    model: fictif\n    api_key_env: valeur-interdite\n",
    "paliers: &cycle\n  fort: *cycle\n",
])
def test_paliers_malformes_refus_metier_expurge(session, tmp_path, texte):
    with session() as cnx, pytest.raises(lecture.ConfigurationLectureErreur) as erreur:
        lecture.lire(cnx, charger_departements(), {}, _fichier(tmp_path, texte))
    assert erreur.value.statut == 409
    assert "sentinelle" not in str(erreur.value) and str(tmp_path) not in str(erreur.value)


def test_octets_utf8_bornes_avant_parser(session, tmp_path, monkeypatch):
    path = _fichier(tmp_path, "é" * 32769)

    def parser_interdit(*_args, **_kwargs):
        pytest.fail("un fichier excessif doit être refusé avant parsing")

    monkeypatch.setattr(lecture.yaml, "parse", parser_interdit)
    with session() as cnx, pytest.raises(lecture.ConfigurationLectureErreur, match="paliers_trop_volumineux"):
        lecture.lire(cnx, charger_departements(), {}, path)


def test_profondeur_refusee_avant_construction(session, tmp_path, monkeypatch):
    path = _fichier(tmp_path, "paliers: " + "[" * 20 + "0" + "]" * 20)
    deps = charger_departements()

    def restaurer_interdit(*_args, **_kwargs):
        pytest.fail("la profondeur doit être refusée avant construction")

    monkeypatch.setattr(lecture.yaml, "load", restaurer_interdit)
    with session() as cnx, pytest.raises(lecture.ConfigurationLectureErreur, match="structure_excessive"):
        lecture.lire(cnx, deps, {}, path)


def test_departements_excessifs_refuses_avant_paliers(session, tmp_path, monkeypatch):
    dep = next(iter(charger_departements().values()))
    with session() as cnx, pytest.raises(lecture.ConfigurationLectureErreur, match="trop_de_departements"):
        lecture.lire(cnx, {f"fictif-{i}": dep for i in range(17)}, {}, tmp_path / "absent.yaml")


def test_identifiant_db_excessif_refuse_sans_materialiser_resume(session, nathan, tmp_path):
    deps = charger_departements()
    with session() as cnx:
        agents.creer(cnx, deps, _profil("fictif-identifiant"), par=nathan, mutation_id="creation-fictive-id")
        cnx.execute(update(AGENTS_CONFIGURABLES).values(id="x" * 65))
        with pytest.raises(lecture.ConfigurationLectureErreur, match="registre_agents_invalide"):
            lecture.lire(cnx, deps, {}, _fichier(tmp_path, "paliers: {}\n"))


def test_borne_sortie_utf8():
    lecture.verifier_sortie(b"x" * 65536)
    with pytest.raises(lecture.ConfigurationLectureErreur) as erreur:
        lecture.verifier_sortie(("é" * 32769).encode("utf-8"))
    assert erreur.value.statut == 413


def _profil_entreprise(tmp_path, texte):
    path = tmp_path / "entreprise-fictive.yaml"
    path.write_text(texte, encoding="utf-8")
    return path


def test_avatars_par_defaut_projetes_sans_profil(session, tmp_path):
    with session() as cnx:
        result = lecture.lire(cnx, charger_departements(), {}, _fichier(tmp_path, "paliers: {}\n"),
                              tmp_path / "absent.yaml")
    assert result["avatars"] == {"statut": "defaut", "personnalises": []}
    m1 = next(d for d in result["departements"] if d["code"] == "M1")
    assert m1["avatar"]["nom"] == "Léa" and m1["avatar"]["voix"] == "voix.lea.defaut"
    assert m1["avatar"]["canaux"] == {"messagerie": "disponible", "voix": "prevu", "audiovisuel": "prevu"}
    assert m1["avatar"]["sources"] == {"nom": "manifeste", "voix": "manifeste", "visage": "manifeste"}
    assert [d["avatar"]["nom"] for d in result["departements"]] == [
        "Léa", "Victor", "Mathis", "Gabriel", "Sophie", "Rosalie", "Chloé", "Olivier", "Athéna", "Mnémo",
    ]


def test_avatar_personnalise_par_le_client_projete_avec_sa_provenance(session, tmp_path):
    profil = _profil_entreprise(tmp_path, "avatars:\n  m01-front-office:\n    nom: Julie\n")
    with session() as cnx:
        result = lecture.lire(cnx, charger_departements(), {}, _fichier(tmp_path, "paliers: {}\n"), profil)
    assert result["avatars"] == {"statut": "personnalise", "personnalises": ["m01-front-office"]}
    m1 = next(d for d in result["departements"] if d["code"] == "M1")
    assert m1["avatar"]["nom"] == "Julie" and m1["avatar"]["sources"]["nom"] == "entreprise"
    assert m1["avatar"]["voix"] == "voix.lea.defaut"


@pytest.mark.parametrize("texte", [
    "avatars:\n  m02-revenue-crm:\n    nom: Léa\n",           # doublon avec M1
    "avatars:\n  m01-front-office:\n    nom: Julie 2\n",      # caractère refusé
    "avatars:\n  m01-front-office:\n    role: Patronne\n",    # champ non personnalisable
    "avatars: [\n",                                          # YAML illisible
])
def test_avatars_invalides_ne_montrent_aucune_identite_ni_chemin(session, tmp_path, texte):
    profil = _profil_entreprise(tmp_path, texte)
    with session() as cnx:
        result = lecture.lire(cnx, charger_departements(), {}, _fichier(tmp_path, "paliers: {}\n"), profil)
    assert result["avatars"] == {"statut": "profil_invalide"}
    assert all(d["avatar"] is None for d in result["departements"])
    texte_sortie = json.dumps(result, ensure_ascii=False)
    assert str(tmp_path) not in texte_sortie and "Léa" not in texte_sortie and "Julie" not in texte_sortie


def test_profil_entreprise_trop_volumineux_refuse_avant_lecture(session, tmp_path, monkeypatch):
    profil = _profil_entreprise(tmp_path, "# " + "x" * lecture.MAX_OCTETS + "\n")
    monkeypatch.setattr(lecture.avatars, "identites_effectives",
                        lambda *_a, **_k: pytest.fail("profil trop volumineux : aucune lecture"))
    with session() as cnx:
        result = lecture.lire(cnx, charger_departements(), {}, _fichier(tmp_path, "paliers: {}\n"), profil)
    assert result["avatars"] == {"statut": "profil_trop_volumineux"}
    assert all(d["avatar"] is None for d in result["departements"])
