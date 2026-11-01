"""Cohérence documentaire : liens relatifs, chiffres clés, commandes citées, guides d'utilisation.

Le test échoue en cas de dérive : un lien cassé hors de la liste historique connue, un compteur périmé (outils, migrations, tête
alembic, registre MCP, catalogue de fournisseurs), une commande `opsys-metier` qui n'existe plus, un guide qui contredit les
manifestes. Il vérifie aussi, sur des arbres fictifs, que les contrôles échouent bien (cas négatifs).
"""

# ruff: noqa: E501  (assertions et chaînes de documentation longues, lisibles telles quelles)

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import re
import sys
from pathlib import Path

import pytest

from opsys import cli
from opsys.departements import charger_departements
from opsys.fournisseurs import catalogue

RACINE = Path(__file__).resolve().parents[1]


def _charger(chemin: str, nom: str):
    dossier = str(RACINE / Path(chemin).parent)
    sys.path.insert(0, dossier)
    spec = importlib.util.spec_from_file_location(nom, RACINE / chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


C = _charger("scripts/docs/coherence_documentaire.py", "coherence_documentaire")
S = _charger("scripts/docs/synthese_matrices.py", "synthese_matrices")
BASE_LIENS = RACINE / "docs/utilisation/liens-historiques-connus.json"


def _lire(chemin: str) -> str:
    return (RACINE / chemin).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def verificateur() -> dict[str, int]:
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        code = cli.main(["verifier"])
    ligne = next(x for x in reversed(sortie.getvalue().splitlines()) if x.startswith("OK :"))
    assert code == 0, sortie.getvalue()[-400:]
    m = re.search(r"OK : (\d+) départements, (\d+) outils.*\((\d+) outils déclarés.*?\D(\d+) avatars.*?(\d+) packs sectoriels", ligne)
    assert m, ligne
    d, o, a, av, p = map(int, m.groups())
    return {"departements": d, "outils": o, "appareils": a, "avatars": av, "packs": p}


@pytest.fixture(scope="module")
def commandes_valides() -> set[str]:
    sortie: set[str] = set()

    def parcourir(parseur: argparse.ArgumentParser, prefixe: list[str]) -> None:
        for action in parseur._actions:
            if isinstance(action, argparse._SubParsersAction):
                for nom, sp in action.choices.items():
                    sortie.add(" ".join(prefixe + [nom]))
                    parcourir(sp, prefixe + [nom])
            elif action.choices and action.dest in ("action", "cible", "sous_commande", "verbe") and not action.option_strings:
                for choix in action.choices:
                    sortie.add(" ".join(prefixe + [str(choix)]))

    parcourir(cli.construire_parseur(), [])
    return sortie


# ------------------------------------------------------------------------------------------------- liens relatifs
def test_aucun_lien_relatif_casse_hors_de_la_liste_historique_connue():
    connus = json.loads(BASE_LIENS.read_text(encoding="utf-8"))["liens"]
    casses = C.liens_casses(RACINE, C.fichiers_markdown(RACINE))
    nouveaux = {f: sorted(set(c) - set(connus.get(f, []))) for f, c in casses.items() if set(c) - set(connus.get(f, []))}
    assert nouveaux == {}, "liens cassés nouveaux (corriger le lien ou, si la cible n'a jamais été dans le dépôt, le consigner)"


def test_la_liste_historique_ne_garde_aucun_lien_reparu_ou_disparu():
    connus = json.loads(BASE_LIENS.read_text(encoding="utf-8"))["liens"]
    casses = C.liens_casses(RACINE, C.fichiers_markdown(RACINE))
    perimes = {f: sorted(set(c) - set(casses.get(f, []))) for f, c in connus.items() if set(c) - set(casses.get(f, []))}
    assert perimes == {}, "lignes de la liste historique qui ne sont plus cassées (ou dont le fichier a disparu) : les retirer"


def test_les_documents_vivants_n_ont_que_des_liens_historiques_hors_depot():
    connus = json.loads(BASE_LIENS.read_text(encoding="utf-8"))["liens"]
    historiques = ("docs/grs/", "docs/programme/", "docs/research/", "docs/reprise/", "docs/history/")
    vivants = {f: c for f, c in connus.items() if not f.startswith(historiques)}
    # seuls trois documents d'architecture ou d'exploitation renvoient à des preuves rangées hors du dépôt
    assert sorted(vivants) == ["docs/architecture/AGENTS-CRON-OPERATEUR.md", "docs/architecture/CRON-RACCORDEMENT-HOTE-2026-10-03.md",
                               "docs/exploitation/RESTAURATION-MEMOIRE-QUALIFICATION-2026-10-05.md"]
    assert all(c.startswith(("/workspace/", "../research/REPRISE-")) for cibles in vivants.values() for c in cibles)


def test_le_controle_de_liens_voit_un_lien_casse_dans_un_arbre_fictif(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("[ok](docs/a.md) [casse](docs/absent.md) [ancre](#x) [web](https://exemple.test) "
                                        "```\n[dans un bloc](nulle/part.md)\n```", encoding="utf-8")
    (tmp_path / "docs/a.md").write_text("[retour](../README.md) [absolu](/workspace/x.json) [avec ancre](../README.md#titre)", encoding="utf-8")
    casses = C.liens_casses(tmp_path, C.fichiers_markdown(tmp_path))
    assert casses == {"README.md": ["docs/absent.md"], "docs/a.md": ["/workspace/x.json"]}


# --------------------------------------------------------------------------------------------- chiffres clés
def test_les_chiffres_cles_du_readme_sont_ceux_du_verificateur_et_du_depot(verificateur):
    chiffres = C.chiffres_du_bloc(_lire("README.md"))
    n_migrations, tete = C.migrations(RACINE)
    registre = json.loads(_lire("src/opsys/registre_mcp/registre.v1.json"))
    attendu = {
        "Départements": verificateur["departements"], "Outils": verificateur["outils"],
        "Outils ouverts aux appareils": verificateur["appareils"], "Avatars": verificateur["avatars"],
        "Packs sectoriels": verificateur["packs"], "Fichiers de migration": n_migrations, "Tête alembic": tete,
        "Révision du registre MCP": registre["revision"], "Outils scellés au registre MCP": len(registre["outils"]),
        "Lignes du catalogue de fournisseurs": len(catalogue.CATALOGUE),
    }
    assert {k: str(v) for k, v in attendu.items()} == chiffres


def test_roles_md_cite_les_memes_totaux_que_le_verificateur(verificateur):
    assert f"{verificateur['appareils']} outils sur {verificateur['outils']} sont déclarés" in _lire("docs/architecture/ROLES.md")


def test_la_tete_alembic_et_le_nombre_de_migrations_viennent_des_fichiers():
    n, tete = C.migrations(RACINE)
    assert n >= 45 and tete >= "0052"  # le calcul vient des fichiers ; le README doit citer EXACTEMENT ces valeurs
    assert f"Tête alembic | {tete} |" in _lire("README.md")
    assert f"Fichiers de migration | {n} |" in _lire("README.md")


def test_une_chaine_de_migrations_a_deux_tetes_est_refusee(tmp_path):
    versions = tmp_path / "src/opsys/stockage/migrations/versions"
    versions.mkdir(parents=True)
    (versions / "0001_a.py").write_text('revision = "0001"\ndown_revision = None\n', encoding="utf-8")
    (versions / "0002_b.py").write_text('revision = "0002"\ndown_revision = "0001"\n', encoding="utf-8")
    assert C.migrations(tmp_path) == (2, "0002")
    (versions / "0003_c.py").write_text('revision = "0003"\ndown_revision = "0001"\n', encoding="utf-8")
    with pytest.raises(AssertionError, match="plusieurs têtes"):
        C.migrations(tmp_path)


def test_le_bloc_des_chiffres_se_lit_et_un_chiffre_periime_se_detecte():
    bloc = f"{C.BLOC_DEBUT}\n| Chiffre | Valeur |\n|---|---|\n| Outils | 537 |\n| Tête alembic | 0049 |\n{C.BLOC_FIN}"
    assert C.chiffres_du_bloc(bloc) == {"Outils": "537", "Tête alembic": "0049"}
    assert C.chiffres_du_bloc(bloc.replace("537", "415"))["Outils"] != "537"


def test_le_catalogue_de_fournisseurs_est_cite_avec_sa_vraie_taille():
    n = len(catalogue.CATALOGUE)
    assert f"{n} entrées" in _lire("docs/architecture/FOURNISSEURS-ET-SECRETS.md")
    assert f"catalogue de {n} entrées" in _lire("docs/architecture/M7-STUDIO-CREATIF.md")
    assert "57 entrées, licences" not in _lire("docs/architecture/FOURNISSEURS-ET-SECRETS.md")
    assert f"Le catalogue compte {n} lignes" in _lire("docs/utilisation/GUIDE-ADMINISTRATION.md")


def test_le_registre_mcp_est_cite_avec_sa_vraie_taille():
    registre = json.loads(_lire("src/opsys/registre_mcp/registre.v1.json"))
    assert f"**{len(registre['outils'])} outils**" in _lire("docs/utilisation/GUIDE-ADMINISTRATION.md")
    assert f"{len(registre['outils'])} à la révision {registre['revision']}" in _lire("docs/architecture/OBSERVABILITE-MCP.md")


# ------------------------------------------------------------------------------------------------ commandes
def test_toute_commande_opsys_metier_citee_dans_les_documents_existe(commandes_valides):
    mauvaises = {}
    for f in C.fichiers_markdown(RACINE):
        if "docs/research/" in f.as_posix() or "docs/reprise/" in f.as_posix() or "/preuves/" in f.as_posix():
            continue
        invalides = C.commandes_invalides(C.commandes_citees(f.read_text(encoding="utf-8", errors="replace")), commandes_valides)
        if invalides:
            mauvaises[f.relative_to(RACINE).as_posix()] = invalides
    assert mauvaises == {}


def test_le_controle_de_commandes_voit_une_commande_disparue(commandes_valides):
    assert "pack choisir" in commandes_valides and "registre-mcp sceller" in commandes_valides
    citees = C.commandes_citees("lancer `opsys-metier verifier` puis `opsys metier pack choisir x`, `opsys-metier mode m05 supervise`")
    assert C.commandes_invalides(citees, commandes_valides) == []
    for faux in ("opsys-metier fournisseurs supprimer", "opsys-metier ancienne-commande", "opsys metier pack effacer"):
        assert C.commandes_invalides(C.commandes_citees(faux), commandes_valides), faux


# --------------------------------------------------------------------------------------- guides d'utilisation
def test_les_quatre_documents_d_utilisation_existent_et_sont_references():
    for nom in ("GUIDE-PROPRIETAIRE", "GUIDE-ADMINISTRATION", "GLOSSAIRE-ET-FAQ", "LIMITES-CONNUES"):
        assert (RACINE / f"docs/utilisation/{nom}.md").is_file()
        assert f"utilisation/{nom}.md" in _lire("docs/README.md")
    assert "utilisation/LIMITES-CONNUES.md" in _lire("README.md")


def test_le_guide_du_proprietaire_dit_les_vrais_chiffres_et_les_vrais_avatars(verificateur):
    guide = _lire("docs/utilisation/GUIDE-PROPRIETAIRE.md")
    assert f"**{verificateur['outils']} outils**" in guide and f"**{verificateur['appareils']}** de ces outils" in guide
    lignes = {m.group(1): (m.group(2), int(m.group(3))) for m in re.finditer(r"^\| (M\d+) \| [^|]+ \| ([^|]+) \| .* \| (\d+) \|$", guide, re.M)}
    departements = charger_departements()
    assert len(lignes) == len(departements) == 10
    for dep in departements.values():
        avatar, n = lignes[dep.code]
        assert avatar.strip() == dep.avatar.nom, dep.code
        assert n == len(dep.charger_outils()), dep.code


def test_le_readme_de_m5_cite_son_nombre_d_outils_actuel():
    n = len(charger_departements()["m05-financecore"].charger_outils())
    assert f"**{n} au 1er novembre 2026**" in _lire("departments/m05-financecore/README.md")


def test_le_guide_du_proprietaire_dit_que_tout_demarre_en_ombre_et_que_la_voix_est_prevue():
    guide = _lire("docs/utilisation/GUIDE-PROPRIETAIRE.md")
    assert all(d.mode == "ombre" for d in charger_departements().values())
    assert "démarrent en mode\n« ombre »" in guide or "tous les départements démarrent en mode" in guide
    assert "seule la messagerie est disponible" in guide.lower()
    assert all(d.avatar.canaux["voix"] == "prevu" and d.avatar.canaux["messagerie"] == "disponible" for d in charger_departements().values())


def test_les_niveaux_du_guide_sont_ceux_du_code():
    from opsys.politiques import _SEUIL_APPROBATION_NIVEAU

    guide = _lire("docs/utilisation/GUIDE-PROPRIETAIRE.md")
    assert {k: v.value for k, v in _SEUIL_APPROBATION_NIVEAU.items()} == {"ombre": "N3", "supervise": "N4", "autonome": "N5"}
    assert "| `ombre` (défaut de tous les départements) | Tout geste à partir de N3 |" in guide
    assert "| `supervise` | À partir de N4 |" in guide and "| `autonome` | À partir de N5 seulement |" in guide


def test_le_guide_d_administration_marque_ce_qui_n_est_pas_qualifie():
    guide = _lire("docs/utilisation/GUIDE-ADMINISTRATION.md")
    assert guide.count("Non qualifié") + guide.count("non qualifié") + guide.count("**Non qualifié**") >= 6
    for sujet in ("Caddy/TLS", "install/install.sh", "deploy/backup.sh", "copie hors site", "Prouvé sur doubles", "prouvé sur doubles seulement"):
        assert sujet.lower() in guide.lower(), sujet
    assert "OPSYS_MCP_REGISTRE=defaut" in guide and "n'a jamais" in guide
    rapport = _lire("docs/qualification/QUALIFICATION-CONTENEUR.md")
    assert "Ceci ne qualifie PAS un VPS" in rapport and "jamais rejouées sur un vrai serveur" in guide.replace("\n", " ")


def test_la_page_des_limites_est_alimentee_par_les_matrices():
    assert S.remplacer(_lire("docs/utilisation/LIMITES-CONNUES.md")) == _lire("docs/utilisation/LIMITES-CONNUES.md"), \
        "bloc des matrices périmé : python scripts/docs/synthese_matrices.py --ecrire"
    synthese = S.donnees_synthese()
    readme = _lire("docs/reprise/MATRICES-20261031/README.md")
    assert sum(synthese[m]["total"] for m in synthese if m != "M9") == 169
    assert sum(synthese[m]["statuts"]["FAIT_PROUVE"] for m in synthese if m != "M9") == 4
    assert "| Total | 169 | 4 | 159 | 5 | 1 | 0 |" in readme


def test_la_page_des_limites_ne_laisse_aucune_capacite_sur_double_passer_pour_prete():
    page = _lire("docs/utilisation/LIMITES-CONNUES.md")
    for sujet in ("Un serveur réel (VPS)", "Courriel (Gmail, Microsoft 365, IMAP)", "Voix et visage des avatars", "WordPress et réseaux sociaux",
                  "Fiscalité, paie, subventions (M5)", "Modèles de langage réels", "Copie de sauvegarde hors site"):
        assert f"**{sujet}**" in page, sujet
    assert "Aucun département n'est déclaré « terminé »" in page
    for interdit in ("est qualifié", "est certifié", "100 %"):
        assert interdit not in page


def test_les_documents_d_utilisation_ne_pretendent_pas_a_un_avis_professionnel():
    for nom in ("GUIDE-PROPRIETAIRE", "GLOSSAIRE-ET-FAQ", "LIMITES-CONNUES"):
        texte = _lire(f"docs/utilisation/{nom}.md")
        assert "À valider auprès d'un comptable (CPA) / professionnel qualifié" in texte, nom
    assert "ne tranche rien" in _lire("docs/compliance/QUESTIONS-AVOCAT.md")
