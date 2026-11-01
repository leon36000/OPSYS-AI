"""Paquet versionné reproductible et PLAN de déploiement : un artefact, jamais une exécution."""

from __future__ import annotations

import ast
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from m7_marketing.site import deploiement, paquet, qa_site, rendu_statique, service

FICTIF = True
VERSION = "20261031T150000Z"
CIBLE = {"hote": "vps.revetements-horizon.example"}
_SITE = Path(__file__).resolve().parents[2] / "src" / "m7_marketing" / "site"


def _prepare(schema, actifs, version=VERSION, cible=CIBLE):
    resultat = service.preparer_paquet(schema, actifs, version, cible)
    assert resultat["accepte"], resultat
    return resultat


def test_archive_reproductible_meme_entree_memes_octets(fichiers, schema):
    rapport = qa_site.controler_site(fichiers, schema)
    archive_1, manifeste_1 = paquet.construire_paquet(fichiers, schema, VERSION, rapport)
    archive_2, manifeste_2 = paquet.construire_paquet(dict(fichiers), schema, VERSION, rapport)
    assert archive_1 == archive_2 and manifeste_1 == manifeste_2
    assert manifeste_1["archive"]["sha256"] == hashlib.sha256(archive_1).hexdigest()
    autre, _ = paquet.construire_paquet(fichiers, schema, "20261031T150001Z", rapport)
    assert autre != archive_1


def test_bout_en_bout_le_schema_donne_toujours_la_meme_archive(schema, actifs):
    assert _prepare(schema, actifs)["archive"] == _prepare(schema, actifs)["archive"]


def test_archive_contient_le_site_et_ses_sommes_verifiables(fichiers, schema):
    archive, manifeste = paquet.construire_paquet(fichiers, schema, VERSION, {"conforme": True, "controles": []})
    assert gzip.decompress(archive)  # gzip valide
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        membres = tar.getmembers()
        noms = [m.name for m in membres]
        assert noms == sorted(noms)
        assert set(noms) == set(fichiers) | {"SHA256SUMS"}
        assert all(m.uid == 0 and m.gid == 0 and m.mode == 0o644 and m.uname == "" for m in membres)
        sommes = tar.extractfile("SHA256SUMS").read().decode()
        for ligne in sommes.splitlines():
            empreinte, chemin = ligne.split("  ")
            assert hashlib.sha256(tar.extractfile(chemin).read()).hexdigest() == empreinte
    assert [f["chemin"] for f in manifeste["fichiers"]] == sorted(fichiers)
    assert manifeste["empreinte_schema"] == paquet.empreinte_schema(json.loads(json.dumps(schema)))


@pytest.mark.parametrize("version", ["2026-10-31", "20261331T000000Z", "20261031T150000", None])
def test_version_invalide_refusee(schema, actifs, version):
    resultat = service.preparer_paquet(schema, actifs, version, CIBLE)
    assert [r["code"] for r in resultat["refus"]] == [paquet.REJ_VERSION]
    with pytest.raises(ValueError, match=paquet.REJ_VERSION):
        paquet.construire_archive({}, str(version))


def test_paquet_refuse_si_le_qa_n_est_pas_conforme(schema, actifs):
    actifs["images/facade-revetement.svg"] = actifs["images/facade-revetement.svg"].replace(
        b"</svg>", b"<!--" + b"x" * qa_site.POIDS_PAGE_MAX + b"--></svg>"
    )
    resultat = service.preparer_paquet(schema, actifs, VERSION, CIBLE)
    assert [r["code"] for r in resultat["refus"]] == [service.REJ_QA]
    assert "QA-POIDS" in resultat["refus"][0]["detail"]


@pytest.mark.parametrize(("cible", "code"), [
    ({"hote": "vps.revetements-horizon.example", "utilisateur": "root"}, deploiement.REJ_UTILISATEUR_ROOT),
    ({"hote": "vps.revetements-horizon.example", "utilisateur": "deploy;rm -rf /"}, deploiement.REJ_UTILISATEUR),
    ({"hote": "vps.example; curl evil"}, deploiement.REJ_HOTE),
    ({"hote": "203.0.113.7"}, deploiement.REJ_HOTE),
    ({}, deploiement.REJ_HOTE),
    ({"hote": "vps.revetements-horizon.example", "port": 0}, deploiement.REJ_PORT),
    ({"hote": "vps.revetements-horizon.example", "racine": "/etc/caddy"}, deploiement.REJ_RACINE),
    ({"hote": "vps.revetements-horizon.example", "racine": "/srv/sites/../etc/revetements-horizon.example"},
     deploiement.REJ_RACINE),
    ({"hote": "vps.revetements-horizon.example", "racine": "/srv/sites/autre.example"}, deploiement.REJ_RACINE),
    ({"hote": "vps.revetements-horizon.example", "versions_conservees": 1}, deploiement.REJ_CONSERVATION),
    ({"hote": "vps.revetements-horizon.example", "version_precedente": "hier"}, deploiement.REJ_VERSION),
    ({"hote": "vps.revetements-horizon.example", "mot_de_passe": "x"}, deploiement.REJ_CIBLE),
    ("vps.revetements-horizon.example", deploiement.REJ_CIBLE),
])
def test_cible_de_deploiement_invalide_refusee(schema, actifs, cible, code):
    resultat = service.preparer_paquet(schema, actifs, VERSION, cible)
    assert code in [r["code"] for r in resultat["refus"]]


def test_plan_non_execute_utilisateur_non_root_versions_atomiques(schema, actifs):
    plan = _prepare(schema, actifs)["plan"]
    assert (plan["statut"], plan["execute"], plan["niveau_publication"]) == ("PLAN_NON_EXECUTE", False, "N3")
    assert plan["cible"] == {
        "hote": "vps.revetements-horizon.example", "utilisateur": "opsys-deploy", "port": 22,
        "racine": "/srv/sites/revetements-horizon.example", "versions_conservees": 5, "version_precedente": None,
    }
    commandes = {e["nom"]: e["commande"] for e in plan["etapes"]}
    assert list(commandes) == [
        "verifier_paquet_local", "creer_repertoire_version", "envoyer_archive", "extraire_et_verifier",
        "installer_configuration_caddy", "basculer_current", "recharger_caddy", "purger_anciennes_versions",
    ]
    assert "releases/20261031T150000Z" in commandes["creer_repertoire_version"]
    bascule = "ln -sfn releases/20261031T150000Z current.tmp && mv -Tf current.tmp current"
    assert bascule in commandes["basculer_current"]
    assert "sha256sum -c SHA256SUMS" in commandes["extraire_et_verifier"]
    assert "sudo -n /usr/bin/systemctl reload caddy" in commandes["recharger_caddy"]
    assert all("root@" not in c for c in commandes.values())
    assert [e["reversible"] for e in plan["etapes"]][-1] is False
    retour = plan["retour_arriere"]["commande"]
    assert "ln -sfn" in retour and "grep -vx 20261031T150000Z" in retour
    assert {v["nom"] for v in plan["verifications_apres"]} >= {"page_introuvable", "certificat", "en_tetes_securite"}


def test_retour_arriere_vers_une_version_precedente_nommee(schema, actifs):
    cible = {**CIBLE, "version_precedente": "20261001T120000Z"}
    plan = _prepare(schema, actifs, cible=cible)["plan"]
    assert "ln -sfn releases/20261001T120000Z current.tmp" in plan["retour_arriere"]["commande"]


def test_caddyfile_https_automatique_en_tetes_de_securite_et_csp(schema, actifs, fichiers_demo):
    caddy = _prepare(schema, actifs)["plan"]["caddyfile"]
    assert caddy.splitlines()[3] == "revetements-horizon.example {"
    assert "root * /srv/sites/revetements-horizon.example/current" in caddy
    for nom, valeur in deploiement.EN_TETES_SECURITE:
        assert f'{nom} "{valeur}"' in caddy
    css = rendu_statique.feuille_de_style(schema["charte"])
    assert rendu_statique.politique_csp(css) in fichiers_demo["index.html"].decode().replace("&#x27;", "'")
    assert f'Content-Security-Policy "{rendu_statique.politique_csp(css, en_tete_http=True)}"' in caddy
    assert "frame-ancestors 'none'" in caddy
    assert "rewrite * /en/404.html" in caddy and "rewrite * /404.html" in caddy
    assert "redir https://revetements-horizon.example{uri} permanent" in caddy
    assert "tls " not in caddy  # aucun certificat manuel : ACME automatique de Caddy


def test_plan_lisible_dit_qu_il_n_est_pas_execute(schema, actifs):
    texte = deploiement.plan_lisible(_prepare(schema, actifs)["plan"])
    assert "**PLAN_NON_EXECUTE** (rien n'a été exécuté par OPSYS)" in texte
    assert "IRRÉVERSIBLE" in texte and "## Retour arrière" in texte


def test_ecrire_paquet_version_immuable_et_rejeu(schema, actifs, tmp_path):
    prepare = _prepare(schema, actifs)
    ecrit = service.ecrire_paquet(prepare, tmp_path)
    assert ecrit["deja_prepare"] is False
    dossier = tmp_path / VERSION
    assert sorted(p.name for p in dossier.iterdir()) == sorted([
        "Caddyfile", "MANIFESTE.json", "PLAN-DEPLOIEMENT.json", "PLAN-DEPLOIEMENT.md",
        "revetements-horizon-fictif-20261031T150000Z.tar.gz",
    ])
    manifeste = json.loads((dossier / "MANIFESTE.json").read_text())
    assert manifeste["archive"]["sha256"] == hashlib.sha256(
        (dossier / "revetements-horizon-fictif-20261031T150000Z.tar.gz").read_bytes()
    ).hexdigest()
    assert service.ecrire_paquet(prepare, tmp_path)["deja_prepare"] is True
    schema["faq"][0]["reponse"]["fr-CA"] += " Merci."
    autre = service.ecrire_paquet(_prepare(schema, actifs), tmp_path)
    assert [r["code"] for r in autre["refus"]] == [service.REJ_PAQUET_EXISTANT]


_INTERDITS = {"subprocess", "socket", "paramiko", "fabric", "asyncssh", "http", "urllib", "requests", "ftplib"}


@pytest.mark.parametrize("module", sorted(p.name for p in _SITE.glob("*.py")))
def test_aucun_module_du_site_ne_peut_executer_ni_se_connecter(module):
    arbre = ast.parse((_SITE / module).read_text(encoding="utf-8"))
    importes = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            importes |= {alias.name.split(".")[0] for alias in noeud.names}
        elif isinstance(noeud, ast.ImportFrom) and noeud.module and noeud.level == 0:
            importes.add(noeud.module.split(".")[0])
        elif isinstance(noeud, ast.Attribute) and noeud.attr in ("system", "popen", "spawnv", "execv"):
            pytest.fail(f"{module} : appel {noeud.attr}")
    assert not importes & _INTERDITS, f"{module} importe {importes & _INTERDITS}"
