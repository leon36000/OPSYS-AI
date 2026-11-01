"""Banc de parcours navigateur (install/qualification/navigateur) : tests qui n'exigent PAS de navigateur, plus un test
qui joue le banc dans Chromium réel quand il est présent et SAUTE proprement sinon.

Sans navigateur, on prouve : l'inventaire des moyens dit ce qui manque (« prêt mais non exécuté », code 3, aucun verdict
inventé) ; chaque injection de défaut pointe vers des constats qui existent vraiment dans le script de parcours ; les
scripts JavaScript sont syntaxiquement valides ; l'instance fictive ne touche ni réseau ni donnée réelle ; les formes de
cookie forgé (échu, falsifié) sont bien refusées par la console. Données fictives.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FICTIF = True
BANC = Path(__file__).resolve().parents[1] / "install" / "qualification" / "navigateur"


def _charger(nom: str):
    sys.path.insert(0, str(BANC))
    try:
        spec = importlib.util.spec_from_file_location(f"banc_nav_{nom}", BANC / f"{nom}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(BANC))


@pytest.fixture(scope="module")
def lancer():
    return _charger("lancer")


@pytest.fixture(scope="module")
def injections():
    return _charger("injections")


def test_fichiers_du_banc_presents():
    for nom in ("lancer.py", "instance.py", "injections.py", "parcours.js", "controles_a11y.js", "README.md",
                "departement_fictif/qualif_outils.py", "departement_fictif/m09-qualif/department.yaml"):
        assert (BANC / nom).is_file(), nom


def test_inventaire_sans_navigateur_dit_ce_qui_manque_et_n_invente_aucun_verdict(lancer, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(lancer, "trouver_chromium", lambda: (None, ""))
    inv = lancer.inventaire()
    assert inv["moyens_suffisants"] is False and any("Chromium" in m for m in inv["manque"])
    res = lancer.executer(tmp_path, None, None, "essai")
    assert res["verdict"] == "NON_EXECUTE" and res["constats"] == []  # aucune instance démarrée, aucun constat fabriqué
    chemin = lancer.ecrire_preuves(tmp_path, res, "parcours-NON-EXECUTE")
    texte = chemin.with_suffix(".md").read_text(encoding="utf-8")
    assert "NON EXÉCUTÉ" in texte and "Chromium" in texte and "PASSE" not in texte
    assert lancer.main(["verifier"]) == 3
    assert lancer.main(["parcours", "--sortie", str(tmp_path)]) == 3
    assert "NON EXÉCUTÉ" in capsys.readouterr().out
    assert lancer.mutations(tmp_path, None) == 3


def test_conversion_webp_sans_imagemagick_laisse_les_png(lancer, monkeypatch, tmp_path):
    (tmp_path / "x.png").write_bytes(b"png")
    monkeypatch.setattr(lancer.shutil, "which", lambda nom: None)
    assert lancer.convertir_webp(tmp_path) == 0 and (tmp_path / "x.png").exists()


def test_inventaire_sans_node_ni_playwright(lancer, monkeypatch):
    monkeypatch.setattr(lancer.shutil, "which", lambda nom: None)
    monkeypatch.setattr(lancer, "trouver_playwright", lambda: None)
    inv = lancer.inventaire()
    assert not inv["moyens_suffisants"]
    assert any("node" in m for m in inv["manque"]) and any("playwright-core" in m for m in inv["manque"])


def test_chromium_explicite_prioritaire_et_cache_playwright(lancer, monkeypatch, tmp_path):
    faux = tmp_path / "chrome"
    faux.write_text("#!/bin/sh\n")
    monkeypatch.setenv("OPSYS_CHROMIUM", str(faux))
    assert lancer.trouver_chromium() == (str(faux), "OPSYS_CHROMIUM")
    monkeypatch.delenv("OPSYS_CHROMIUM")
    cache = tmp_path / "cache" / "chromium-1111" / "chrome-linux64"
    cache.mkdir(parents=True)
    (cache / "chrome").write_text("x")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "cache"))
    assert lancer.trouver_chromium()[0] == str(cache / "chrome")


def _constats_declares() -> set[str]:
    source = (BANC / "parcours.js").read_text(encoding="utf-8")
    declares = set()
    groupe = None
    for ligne in source.splitlines():
        m = re.match(r'\s*const G = "([a-z0-9-]+)";', ligne)
        if m:
            groupe = m.group(1)
        for ident in re.findall(r'constat\(G, "([a-z0-9-]+)"', ligne):
            declares.add(f"{groupe}/{ident}")
        for ident in re.findall(r'constat\(G, "([a-z0-9-]+)" \+', ligne):
            declares.add(f"{groupe}/{ident}")
    # Constats nommés par motif : règles a11y (« regle-… »), pages Plateforme, largeurs, parcours clavier.
    bloc_regles = source[source.index("const regles = ["):source.index("for (const r of regles)")]
    for regle in re.findall(r'"([a-z0-9-]+)"', bloc_regles):
        declares.add(f"accessibilite/regle-{regle}")
    for largeur in (375, 768, 1280):
        declares.add(f"responsive/largeur-{largeur}")
    for nom in ("departements", "approbations", "plateforme-secrets", "plateforme-fournisseurs"):
        declares |= {f"clavier/{nom}-parcours", f"clavier/{nom}-focus"}
    return declares


def test_chaque_injection_cible_des_constats_qui_existent(lancer, injections):
    declares = _constats_declares()
    assert len(injections.INJECTIONS) >= 8
    for nom, (fonction, groupes, attendus) in injections.INJECTIONS.items():
        assert callable(fonction) and groupes and attendus, nom
        for attendu in attendus:
            assert attendu in declares, (nom, attendu)
            assert attendu.split("/")[0] in {  # le groupe joué doit contenir le constat attendu
                {"connexion": "connexion", "csrf": "csrf", "deconnexion": "deconnexion", "plateforme": "plateforme",
                 "a11y": "accessibilite", "entetes": "entetes-securite", "clavier": "clavier",
                 "responsive": "responsive"}[g] for g in groupes}, (nom, attendu, groupes)


def test_les_groupes_de_parcours_sont_ceux_que_les_injections_demandent(injections):
    source = (BANC / "parcours.js").read_text(encoding="utf-8")
    tous = set(re.findall(r"^\s+(\w+): g_\w+", source[source.index("const TOUS"):], re.M)) | set(
        re.findall(r"(\w+): g_\w+", source[source.index("const TOUS"):]))
    for nom, (_, groupes, _) in injections.INJECTIONS.items():
        assert set(groupes) <= tous, (nom, groupes - tous if isinstance(groupes, set) else set(groupes) - tous)


@pytest.mark.skipif(shutil.which("node") is None, reason="node absent : syntaxe JavaScript non vérifiable")
@pytest.mark.parametrize("fichier", ["parcours.js", "controles_a11y.js"])
def test_syntaxe_javascript_du_banc(fichier):
    r = subprocess.run(["node", "--check", str(BANC / fichier)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_instance_fictive_aucun_reseau_aucune_donnee_reelle():
    source = (BANC / "instance.py").read_text(encoding="utf-8")
    source += (BANC / "departement_fictif" / "qualif_outils.py").read_text(encoding="utf-8")
    assert '"127.0.0.1"' in source and "0.0.0.0" not in source
    assert not re.search(r"https?://(?!127\.0\.0\.1|localhost)", source)
    assert "secrets.token_urlsafe" in source  # mots de passe générés à l'exécution, jamais écrits dans le dépôt
    manifeste = (BANC / "departement_fictif" / "m09-qualif" / "department.yaml").read_text(encoding="utf-8")
    assert "FICTIF" in manifeste and "mode: ombre" in manifeste
    for fichier in BANC.rglob("*"):
        if fichier.is_file() and fichier.suffix in {".py", ".js", ".md", ".yaml"}:
            texte = fichier.read_text(encoding="utf-8")
            motif = r"(?i)(api[_-]?key|password|mot_de_passe)\s*[:=]\s*[\"'][A-Za-z0-9+/=_-]{16,}[\"']"
            assert not re.search(motif, texte), fichier


def test_cookies_forges_echu_et_falsifie_sont_refuses(tmp_path):
    """Les deux cookies que le banc injecte dans Chromium sont refusés par la console elle-même (sans navigateur)."""
    from opsys.console import securite

    lancer = _charger("lancer")
    (tmp_path / "cles").mkdir()
    secret = "s" * 40
    (tmp_path / "cles" / "console.secret").write_text(secret)
    echu, falsifie = lancer.cookies_forges(tmp_path)
    assert securite.lire_session(echu, secret) is None  # signature valide mais échéance dépassée
    assert securite.lire_session(falsifie, secret) is None  # charge modifiée (élévation de rôle), signature d'origine
    autre = securite.signer_session(securite.ouvrir_session("employe-fictif", ["employee"], 600), secret)
    assert securite.lire_session(autre, secret) is not None  # le témoin positif : un cookie sain passe


def test_controle_serveur_detecte_un_secret_dans_le_journal(lancer, tmp_path):
    """Le contrôle côté serveur du banc (fuite dans les journaux) détecte réellement une fuite : mutation du journal."""
    (tmp_path / "cles").mkdir()
    (tmp_path / "cles" / "console.secret").write_text("c" * 40)
    (tmp_path / "identifiants.json").write_text(json.dumps({"proprio-fictif": "mot-de-passe-fictif-du-test-01"}))
    (tmp_path / "secret-fictif.txt").write_text("fictif-valeur-secrete-0123456789abcdef")
    (tmp_path / "instance.db").write_bytes(b"rien")

    class Faux:
        prefixe = ""
        journal = tmp_path / "serveur.log"

    Faux.journal.write_text('INFO:     127.0.0.1:1 - "POST /connexion HTTP/1.1" 401 Unauthorized\n')
    propre = {c["id"]: c["ok"] for c in lancer.controles_serveur(tmp_path, Faux)}
    assert propre["journal-mot"] and propre["journal-secret"] and propre["fail2ban-regex"]
    Faux.journal.write_text("Traceback ...\nmot-de-passe-fictif-du-test-01\nfictif-valeur-secrete-0123456789abcdef\n"
                            'INFO:     127.0.0.1:1 - "GET / HTTP/1.1" 200 OK\n')
    sale = {c["id"]: c["ok"] for c in lancer.controles_serveur(tmp_path, Faux)}
    for cle in ("journal-mot", "journal-valeur", "journal-erreurs", "fail2ban-regex"):
        assert not sale[cle], cle


def test_banc_navigateur_reel_quand_chromium_present(lancer, tmp_path):
    """Joue un extrait du banc (connexion, CSRF, en-têtes) dans Chromium RÉEL ; saute si le navigateur manque."""
    inv = lancer.inventaire()
    if not inv["moyens_suffisants"]:
        pytest.skip("navigateur réel indisponible : " + ", ".join(inv["manque"]))
    res = lancer.executer(tmp_path, ["connexion", "csrf", "entetes"], None, "pytest")
    echecs = [f"{c['groupe']}/{c['id']}" for c in res["constats"] if not c["ok"] and c["niveau"] == "bloquant"]
    assert res["verdict"] == "PASSE", echecs
    assert any(c["id"] == "inter-sites-samesite" and c["ok"] for c in res["constats"])
    assert not any(tmp_path.glob("**/*.db"))  # la base jetable ne reste pas dans le dossier de sortie
