"""Généralisation du produit : cœur générique PME + pack sectoriel (DECISIONS-ARCHITECTE-r1 §4).

Quatre garanties, chacune par exécution :

1. NON-RÉGRESSION. Avec le pack du premier client actif, le texte d'avant la généralisation est retrouvé MOT POUR MOT
   (empreinte sha256 de chacun des dix `SOUL.md` d'avant et du skill de M3), suivi du bloc du pack, lui aussi retrouvé
   mot pour mot dans la sortie effective (`rendre_soul`, et ce que `openclaw configurer` écrit réellement).
2. PACK GÉNÉRIQUE PROPRE. Avec `generique-pme`, aucun terme sectoriel (liste du pack rénovation) dans aucune sortie
   effective : SOUL.md, AGENTS.md, skills, distribution Hermes.
3. GARDE PERMANENTE DU CŒUR. Aucun terme sectoriel dans les fichiers du cœur livrés (src/opsys, code et données des
   départements, déploiement), hors packs, tests et documentation, sauf une liste d'EXCEPTIONS explicites : fichier,
   termes permis, nombre de lignes, raison. Une exception inutilisée est elle-même un échec (pas de joker qui traîne).
4. ÉVALUATION. Un cas du corpus qui suppose le secteur porte `pack:` ; l'exécuteur n'en tient compte qu'avec ce pack.

Données FICTIVES. Ce que ces tests ne prouvent pas : qu'un agent réel se comporte aussi bien avec le cœur générique
(aucun modèle réel n'est mesuré) ; ni qu'un second secteur est qualifié.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml
from agents_base_qa import provisionner_base_qa
from sqlalchemy import select

from opsys import cli, modeles, openclaw_refus, packs, taxonomie
from opsys.console import configuration_lecture
from opsys.console.connecteurs_ui import configuration_contenu
from opsys.departements import charger_departements
from opsys.evaluation import executeur
from opsys.evaluation.corpus import RefusEvaluation, valider_corpus
from opsys.evaluation.repondants import REPONDANTS_SIMULES
from opsys.profils import generer_distribution, rendre_soul
from opsys.stockage.schema import JOURNAL

RACINE = Path(__file__).resolve().parents[1]
RENOVATION = "renovation-exterieure-qc"
GENERIQUE = "generique-pme"

# sha256 des SOUL.md (et du skill de M3) AVANT la généralisation (commit d172aa2cc), pris tels quels ;
# M5 : + paragraphe « base fiscale » de claude/m5-base-fiscale ; M7 : + paragraphe WordPress/réseaux sociaux de
# claude/m7-wordpress-social (aucun terme sectoriel dans ces ajouts) ; M2 : + paragraphes propriété, score, coach et
# prévisions de claude/m2-victor ; M1 : + paragraphe « tri, identité, rendez-vous, SMS, apprentissage » et M6 : +
# paragraphe « commande par courriel » (claude/m1-m6-lea-rosalie) ; aucun terme sectoriel dans ces ajouts ; M9 : SOUL
# réécrit pour Athéna (tableau de direction, certitude des faits, conseil gouverné, boucle de décisions ;
# claude/m9-athena),
# sans terme sectoriel : l'ancien « harnais pur sans recommandation » ne décrivait plus l'agent.
SOUL_AVANT = {
    "m01-front-office": "d8344b1aa73f688582fd813e908f22f04c66254ad090cef5c080f83cc66cb131",
    "m02-revenue-crm": "a96b26c92a38015c544c87556ad9b07c8c5e65a6ec3daa959f15a609cce4e932",
    "m03-estimation": "552ae4994c671bb7bc37b5ed5ed4e06773be5e580375a49abbc32a3298012f26",
    "m04-field-ops": "85e7ff89e5f82809c31467efc3a6d6e53f0d6ba310954c7ba36d9079f771179b",
    "m05-financecore": "aed5c1a15fb01e0c572c1120160eee182619ac1fa318edada5cafa317121608b",
    "m06-material-control": "5104a1c724c3e3afb1c3125879949cad55c2d96e661592ae25a23e7a5ae989ef",
    "m07-marketing": "04424e6974a3833c00753ba2d3a0eccfc6130fdebf761f561275f158e073a8f0",
    "m08-analytics": "5dc5fb864a0c2cf52bb48181f4bd461808d59fd720bf7c3caab25bacba0d2e14",
    "m09-strategic-intelligence": "e958ebfc5b34e593f10226c855dd9b120a48af5508ca842a2ce0d8b88e9137c1",
    # Mnémo : soi, graphe, leçons ajoutés
    "m10-memoire": "cb0aa7ddd4e3830d9f2d8036dea413f3ba97eb3727b2283af1b71d8408c07f58",
}
SKILL_M3_AVANT = "7f8bbad11d1f9daf755e3b587350bd91cdb509187bef3e2f992d5d66ed712ff3"

PALIERS = {
    "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "fort": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
}


def sha(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def deps():
    return charger_departements()


@pytest.fixture(scope="module")
def reno():
    return packs.charger_pack(RENOVATION)


@pytest.fixture(scope="module")
def generique():
    return packs.charger_pack(GENERIQUE)


@pytest.fixture(scope="module")
def termes():
    return packs.termes_sectoriels_installes()


def _outils(dep):
    return [{"nom": o.nom, "autonomie": o.autonomie.value, "description": o.description} for o in dep.charger_outils()]


# =================================================================================================== 1. non-régression
def test_avec_le_pack_renovation_chaque_soul_d_avant_est_retrouve_mot_pour_mot(deps, reno):
    assert set(SOUL_AVANT) == set(deps)
    for identifiant, attendu in SOUL_AVANT.items():
        brut = (deps[identifiant].racine / "SOUL.md").read_text(encoding="utf-8")
        assert sha(packs.rendre_jetons(brut, reno)) == attendu, identifiant


def test_le_skill_de_m3_d_avant_est_retrouve_mot_pour_mot_avec_le_pack_renovation(deps, reno, tmp_path):
    packs.copier_skill(deps["m03-estimation"].racine / "skills" / "estimer-un-projet", tmp_path / "s", reno)
    assert sha((tmp_path / "s" / "SKILL.md").read_text(encoding="utf-8")) == SKILL_M3_AVANT


def test_la_sortie_effective_garde_le_texte_d_avant_puis_le_bloc_du_pack_mot_pour_mot(deps, reno):
    for identifiant, dep in deps.items():
        effectif = rendre_soul(dep, _outils(dep), reno)
        ancien = packs.rendre_jetons((dep.racine / "SOUL.md").read_text(encoding="utf-8"), reno).rstrip()
        bloc = packs.bloc_sectoriel(reno, dep.code)
        assert effectif.startswith(ancien + "\n\n" + bloc + "\n\n## Capacités du département "), identifiant
        cle = packs.rendu.cle_departement(dep.code)
        assert reno.blocs[cle].ligne in effectif
        for section in reno.blocs[cle].inclure:
            if section == "services":
                assert all(s.libelle in effectif and all(m in effectif for m in s.mots_cles) for s in reno.services)
            if section == "glossaire":
                assert all(t.definition in effectif for t in reno.glossaire)
            if section == "baremes":
                assert all(b.libelle in effectif for b in reno.baremes)


def test_chaque_phrase_sectorielle_retiree_du_coeur_vit_dans_le_vocabulaire_du_pack(deps, reno):
    """Les cinq intitulés « entreprise de rénovation extérieure au Québec » d'avant sont ceux du vocabulaire du pack."""
    attendu = f"{reno.vocabulaire['qualificatif_secteur']} au"
    for identifiant in ("m01-front-office", "m02-revenue-crm", "m03-estimation", "m04-field-ops", "m07-marketing"):
        brut = (deps[identifiant].racine / "SOUL.md").read_text(encoding="utf-8")
        assert "{{qualificatif_secteur}}" in brut
        assert attendu.replace("\n", " ") in packs.rendre_jetons(brut, reno).replace("\n", " ")


# =================================================================================================== 2. pack générique
def test_aucune_sortie_effective_du_pack_generique_ne_porte_un_terme_sectoriel(deps, generique, termes, tmp_path):
    assert termes  # la liste vient du pack rénovation installé : sans elle, ce test ne garderait rien
    for identifiant, dep in deps.items():
        effectif = rendre_soul(dep, _outils(dep), generique)
        assert packs.termes_trouves(effectif, termes) == [], identifiant
        assert "Contexte sectoriel — Cœur générique PME" in effectif and "{{" not in effectif
        for skill in dep.skills:
            packs.copier_skill(dep.racine / "skills" / skill, tmp_path / identifiant / skill, generique)
    for fichier in tmp_path.rglob("*"):
        if fichier.is_file():
            assert packs.termes_trouves(fichier.read_text(encoding="utf-8"), termes) == [], fichier


def test_le_pack_generique_reproduit_les_cinq_intitules_sans_secteur(deps, generique):
    brut = (deps["m01-front-office"].racine / "SOUL.md").read_text(encoding="utf-8")
    assert "première ligne d'une entreprise au\nQuébec." in packs.rendre_jetons(brut, generique)
    brut = (deps["m07-marketing"].racine / "SOUL.md").read_text(encoding="utf-8")
    assert "CMO IA de l'entreprise cliente au Québec." in packs.rendre_jetons(brut, generique)


def test_la_distribution_hermes_suit_le_pack_donne(deps, reno, generique, termes, tmp_path):
    dep = deps["m03-estimation"]
    paliers = {n: {"provider": "p", "model": "m"} for n in ("rapide", "standard", "fort", "local")}
    dossier = generer_distribution(dep, tmp_path / "gen", paliers, "opsys-mcp", pack=generique)
    for fichier in dossier.rglob("*"):
        if fichier.is_file():
            assert packs.termes_trouves(fichier.read_text(encoding="utf-8"), termes) == [], fichier
    dossier = generer_distribution(dep, tmp_path / "reno", paliers, "opsys-mcp", pack=reno)
    skill = (dossier / "skills" / "estimer-un-projet" / "SKILL.md").read_text("utf-8")
    assert "projet de rénovation extérieure" in skill
    assert "Contexte sectoriel — Rénovation extérieure" in (dossier / "SOUL.md").read_text("utf-8")


def test_sans_pack_donne_la_sortie_suit_le_profil_de_l_instance(deps):
    dep = deps["m01-front-office"]
    assert "pack `generique-pme`" in rendre_soul(dep, [])
    taxonomie.fichier_profil().parent.mkdir(parents=True, exist_ok=True)
    taxonomie.fichier_profil().write_text(f"pack: {RENOVATION}\n", encoding="utf-8")
    assert f"pack `{RENOVATION}`" in rendre_soul(dep, [])


# ====================================================================== 2 bis. ce qu'écrit `openclaw configurer`
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


def _textes_de_travail(config, dep_id):
    espace = config / "opsys" / "espaces" / dep_id
    return {f.relative_to(espace).as_posix(): f.read_text(encoding="utf-8") for f in sorted(espace.rglob("*"))
            if f.is_file() and f.suffix == ".md"}


def test_openclaw_configurer_sans_pack_ecrit_un_coeur_generique_dans_soul_agents_et_skills(
        session, monkeypatch, tmp_path, deps, termes):
    config = _preparer(session, monkeypatch, tmp_path)
    assert _configurer(config) == 0
    for identifiant in deps:
        textes = _textes_de_travail(config, identifiant)
        assert {"SOUL.md", "AGENTS.md"} <= set(textes)
        for nom, texte in textes.items():
            assert packs.termes_trouves(texte, termes) == [], (identifiant, nom)
        assert f"pack `{GENERIQUE}`" in textes["SOUL.md"]


def test_openclaw_configurer_avec_le_pack_renovation_ecrit_le_texte_d_avant_et_le_bloc(
        session, monkeypatch, tmp_path, deps, reno):
    config = _preparer(session, monkeypatch, tmp_path)
    _profil({"pack": RENOVATION})
    assert _configurer(config) == 0
    for identifiant, dep in deps.items():
        soul = _textes_de_travail(config, identifiant)["SOUL.md"]
        ancien = packs.rendre_jetons((dep.racine / "SOUL.md").read_text(encoding="utf-8"), reno).rstrip()
        assert sha(packs.rendre_jetons((dep.racine / "SOUL.md").read_text(encoding="utf-8"), reno)) == (
            SOUL_AVANT[identifiant])
        assert soul.startswith(ancien + "\n\n" + packs.bloc_sectoriel(reno, dep.code))
    skill = _textes_de_travail(config, "m03-estimation")["skills/estimer-un-projet/SKILL.md"]
    assert sha(skill) == SKILL_M3_AVANT


def test_changer_de_pack_dans_le_profil_reecrit_les_espaces_au_prochain_passage(session, monkeypatch, tmp_path, termes):
    config = _preparer(session, monkeypatch, tmp_path)
    _profil({"pack": RENOVATION})
    assert _configurer(config) == 0
    assert "rénovation extérieure" in _textes_de_travail(config, "m01-front-office")["SOUL.md"]
    _profil({})
    assert _configurer(config) == 0
    soul = _textes_de_travail(config, "m01-front-office")["SOUL.md"]
    assert packs.termes_trouves(soul, termes) == [] and f"pack `{GENERIQUE}`" in soul


def _lignes_journal(session):
    with session() as cnx:
        return cnx.execute(select(JOURNAL.c.action, JOURNAL.c.cible, JOURNAL.c.details)
                           .where(JOURNAL.c.action.like("openclaw.configuration.%")).order_by(JOURNAL.c.id)).all()


@pytest.mark.parametrize("profil", [{"pack": "plomberie-qc"}, {"pack": 12}, {"pack": "../packs"}])
def test_un_pack_inconnu_ou_hostile_refuse_la_generation_sans_rien_ecrire_ni_repli_generique(
        session, monkeypatch, tmp_path, capsys, profil):
    config = _preparer(session, monkeypatch, tmp_path)
    _profil({"pack": RENOVATION})
    assert _configurer(config) == 0
    avant = {f: (config / "opsys" / "espaces" / "m01-front-office" / f).read_bytes() for f in ("SOUL.md", "AGENTS.md")}
    agents_avant = (config / "opsys" / "agents.json").read_bytes()
    capsys.readouterr()

    _profil(profil)
    for _ in range(3):  # la boucle de 300 s du VPS rejoue la commande
        assert _configurer(config) == 2
        assert "pack sectoriel invalide, rien n'est écrit" in capsys.readouterr().err
    assert {f: (config / "opsys" / "espaces" / "m01-front-office" / f).read_bytes() for f in avant} == avant
    assert (config / "opsys" / "agents.json").read_bytes() == agents_avant  # le core garde la configuration précédente
    lignes = _lignes_journal(session)
    assert [(ligne.action, ligne.cible) for ligne in lignes] == [(openclaw_refus.ACTION_REFUS, "avatars")]
    assert json.loads(lignes[0].details)["categorie"] == "pack"
    assert "plomberie" not in lignes[0].details and "entreprise.yaml" not in lignes[0].details

    with session() as cnx:
        projection = configuration_lecture.lire(cnx, charger_departements(), {})
    assert projection["generation_core"]["categorie"] == "pack"
    page = configuration_contenu(projection, "/console")
    assert "pack sectoriel de entreprise.yaml est introuvable ou invalide" in page

    _profil({"pack": RENOVATION})  # rétabli
    assert _configurer(config) == 0
    assert _lignes_journal(session)[-1].action == openclaw_refus.ACTION_RETABLIE


def test_un_pack_altere_refuse_la_generation_au_lieu_de_retomber_sur_le_generique(
        session, monkeypatch, tmp_path, capsys):
    copie = tmp_path / "packs-altere"
    shutil.copytree(RACINE / "packs", copie)
    fichier = copie / RENOVATION / "pack.yaml"
    fichier.write_text(fichier.read_text(encoding="utf-8").replace("Réparation", "Réparations", 1), encoding="utf-8")
    monkeypatch.setenv("OPSYS_PACKS", str(copie))
    config = _preparer(session, monkeypatch, tmp_path)
    _profil({"pack": RENOVATION})
    assert _configurer(config) == 2
    assert "REJ-PACK-EMPREINTE" in capsys.readouterr().err
    assert not (config / "opsys" / "espaces").exists()  # rien n'a été écrit


# ================================================================================ 3. garde permanente du cœur
EXTENSIONS = {".py", ".json", ".yaml", ".yml", ".md", ".sql", ".txt", ".html", ".svg", ".css", ".js", ".ts", ".toml",
              ".sh", ".ps1", ".conf", ".cfg"}
RACINES_DU_COEUR = ("src/opsys", "deploy", "install", "scripts", "outils")
# Dans un département, hors du périmètre : les tests, leurs fixtures et la documentation (données et exemples fictifs
# du premier client), le corpus d'évaluation (garde structurelle plus bas : un cas sectoriel porte `pack:`), le README.
HORS_PERIMETRE_DEPARTEMENT = {"tests", "fixtures", "docs", "evals"}

_CONTRAT_V1 = ("Énuméré du contrat GELÉ v1 (`type_travaux`, épinglé par SHA-256 : docs M1, test_taxonomie_derive.py) : "
               "identifiant technique à ne pas renommer")
EXCEPTIONS: dict[str, tuple[frozenset[str], int, str]] = {
    "src/opsys/taxonomie.py": (
        frozenset({"descente pluviale", "fascia", "gouttière", "revêtement", "siding", "soffite"}), 4,
        "CATALOGUE_REFERENCE : les quatre services du premier client, hérités. Copie documentée par le pack (égalité "
        "épinglée dans test_packs_sectoriels.py) ; lue par AST par verif_coherence M3 et 14 fichiers de tests. Le "
        "basculer sur le pack actif est un lot à part (PACKS-SECTORIELS.md, « Ce qui reste »)."),
    "src/opsys/garde_fou_texte/engagements.py": (
        frozenset({"rénovation"}), 2,
        "motifs du garde-fou d'engagements : « rénovation » y est un NOM DE TRAVAUX parmi d'autres (pose, "
        "installation, réfection…), détecté dans un texte destiné au public ; le retirer baisserait la détection."),
    "departments/m05-financecore/src/m5_financecore/garde_investissement.py": (
        frozenset({"gouttière", "revêtement"}), 1,
        "liste blanche des ACHATS D'EXPLOITATION (non-placements) de la garde investissement : « gouttières » et "
        "« revêtements » y sont des fournitures du premier client ; les retirer ferait refuser par prudence un "
        "achat de matériel légitime. Dette : à charger depuis le pack actif."),
    "src/opsys/registre_mcp/registre.v1.json": (
        frozenset({"isolation thermique", "ravalement", "revêtement", "rénovation"}), 7,
        "miroir GÉNÉRÉ (opsys-metier registre-mcp sceller) des descriptions et schémas d'entrée des outils des "
        "départements, un outil par ligne : il reflète les outils qui nomment encore les services du premier client "
        "(m2_ingerer_lead, m3_estimer_projet, m3_simuler_intervalle…) et tombe avec eux quand ils passeront par le "
        "pack."),
    "departments/m01-front-office/contracts/m1-demande-chiffrage.v1.yaml": (
        frozenset({"isolation thermique", "ravalement", "rénovation"}), 1, _CONTRAT_V1),
    "departments/m01-front-office/contracts/m1-lead-qualifie.v1.yaml": (
        frozenset({"isolation thermique", "ravalement", "rénovation"}), 1, _CONTRAT_V1),
    "departments/m01-front-office/contracts/m1-lead-qualifie.v2.yaml": (
        frozenset({"fascia", "gouttière", "revêtement", "soffite"}), 1,
        "contrat v2 : la contrainte cite le catalogue de référence, épinglée à `taxonomie.codes_catalogue()` par "
        "test_taxonomie_derive.py (identifiants de service)"),
    "departments/m01-front-office/src/m1_front_office/contrats.py": (
        frozenset({"isolation thermique", "ravalement", "rénovation"}), 3, _CONTRAT_V1 + " (copie M1)"),
    "departments/m02-revenue-crm/src/m2_revenue_crm/contrats.py": (
        frozenset({"isolation thermique", "ravalement", "rénovation"}), 3, _CONTRAT_V1 + " (copie M2)"),
    "departments/m03-estimation/src/m3_estimation/contrats.py": (
        frozenset({"isolation thermique", "ravalement", "rénovation"}), 3, _CONTRAT_V1 + " (copie M3)"),
    "departments/m04-field-ops/src/m4_field_ops/cedule.py": (
        frozenset({"isolation thermique", "ravalement", "rénovation"}), 1, _CONTRAT_V1 + " (copie M4)"),
    "departments/m04-field-ops/src/m4_field_ops/contrats.py": (
        frozenset({"isolation thermique", "ravalement", "rénovation"}), 1, _CONTRAT_V1 + " (copie M4)"),
    "departments/m07-marketing/src/m7_marketing/workflows/chantier_social.py": (
        frozenset({"isolation thermique", "ravalement", "rénovation"}), 1, _CONTRAT_V1 + " sans `autre` (copie M7)"),
    "departments/m07-marketing/data/saisons/calendrier-quebec.v1.yaml": (
        frozenset({"gouttière", "isolation thermique", "revêtement", "rénovation", "toit", "toiture"}), 15,
        "données saisonnières qualitatives du premier secteur, lues par m7_marketing/outils.py et 5 tests M7 par ce "
        "chemin ; à déplacer dans le pack (PACKS-SECTORIELS.md, « Ce qui reste »)"),
    "departments/m07-marketing/src/m7_marketing/site/rendu_statique.py": (
        frozenset({"toit"}), 1,
        "icône SVG du gabarit de site (un toit stylisé) : rendu visuel épinglé par les tests de site, pas un prompt"),
    "departments/m07-marketing/src/m7_marketing/site/service.py": (
        frozenset({"revêtement"}), 1,
        "SCHEMAS_DEMO : slug du site de démonstration fictif (dossier de fixtures), identifiant technique"),
    "departments/m09-strategic-intelligence/src/m9_strategic_intelligence/question_scenario.py": (
        frozenset({"bardeau", "couvreur", "fascia", "soffite", "vinyle"}), 3,
        "DETTE : vocabulaire de matériaux et de métiers du parseur de questions de scénario M9, fonctionnel et épinglé "
        "par le corpus M9 ; à externaliser vers le pack (PACKS-SECTORIELS.md, « Ce qui reste »)"),
}


def balayer(racine: Path, termes_cherches) -> dict[str, tuple[int, frozenset[str]]]:
    """`{chemin: (nombre de lignes, termes)}` pour chaque fichier du cœur qui porte un terme."""
    trouves: dict[str, tuple[int, frozenset[str]]] = {}
    for fichier in fichiers_du_coeur(racine):
        texte = fichier.read_text(encoding="utf-8")
        lignes = packs.lignes_avec_termes(texte, termes_cherches)
        if lignes:
            presents = frozenset(t for _, _, ts in lignes for t in ts)
            trouves[fichier.relative_to(racine).as_posix()] = (len(lignes), presents)
    return trouves


def fichiers_du_coeur(racine: Path):
    for base in RACINES_DU_COEUR:
        for fichier in sorted((racine / base).rglob("*")):
            if fichier.is_file() and fichier.suffix in EXTENSIONS and "__pycache__" not in fichier.parts:
                yield fichier
    for dep in sorted((racine / "departments").glob("m*")):
        for fichier in sorted(dep.rglob("*")):
            relatif = fichier.relative_to(dep)
            if (not fichier.is_file() or fichier.suffix not in EXTENSIONS or "__pycache__" in fichier.parts
                    or relatif.parts[0] in HORS_PERIMETRE_DEPARTEMENT or relatif.as_posix() == "README.md"):
                continue
            yield fichier


def juger(observe, exceptions) -> list[str]:
    problemes = []
    for chemin, (lignes, trouves) in sorted(observe.items()):
        if chemin not in exceptions:
            problemes.append(f"{chemin} : terme(s) sectoriel(s) hors exception {sorted(trouves)} ({lignes} ligne(s))")
            continue
        permis, maxi, _raison = exceptions[chemin]
        if trouves - permis:
            problemes.append(f"{chemin} : terme(s) hors de l'exception {sorted(trouves - permis)}")
        if lignes > maxi:
            problemes.append(f"{chemin} : {lignes} ligne(s) sectorielle(s), l'exception en permet {maxi}")
    for chemin in sorted(set(exceptions) - set(observe)):
        problemes.append(f"{chemin} : exception inutilisée (le fichier ne porte plus de terme) : la retirer")
    return problemes


def test_aucun_terme_sectoriel_dans_les_fichiers_du_coeur_hors_des_exceptions_explicites(termes):
    observe = balayer(RACINE, termes)
    assert juger(observe, EXCEPTIONS) == []


def test_le_perimetre_de_la_garde_couvre_les_prompts_les_manifestes_les_skills_et_le_code_des_dix_departements():
    fichiers = {f.relative_to(RACINE).as_posix() for f in fichiers_du_coeur(RACINE)}
    assert len(fichiers) > 600
    for dep in sorted((RACINE / "departments").glob("m*")):
        base = dep.relative_to(RACINE).as_posix()
        assert {f"{base}/SOUL.md", f"{base}/department.yaml"} <= fichiers, base
        assert any(f.startswith(f"{base}/skills/") for f in fichiers), base
        assert any(f.startswith(f"{base}/src/") for f in fichiers), base
    assert {"src/opsys/profils.py", "src/opsys/openclaw.py", "src/opsys/packs/rendu.py",
            "src/opsys/packs/manifeste.py"} <= fichiers
    assert not any(f.startswith(("packs/", "tests/", "docs/")) for f in fichiers)  # exemptés par définition


def test_chaque_exception_a_une_raison_et_un_fichier_reel():
    for chemin, (permis, maxi, raison) in EXCEPTIONS.items():
        assert (RACINE / chemin).is_file(), chemin
        assert permis and maxi >= 1 and len(raison) > 40, chemin
    assert not any("*" in chemin for chemin in EXCEPTIONS)  # aucun joker


def test_la_garde_voit_fuir_un_terme_et_refuse_exceptions_trop_larges_ou_inutilisees(tmp_path, termes):
    """Mutations de la garde elle-même, sur un arbre jetable."""
    (tmp_path / "src" / "opsys").mkdir(parents=True)
    (tmp_path / "departments" / "m01-x").mkdir(parents=True)
    for base in ("deploy", "install", "scripts", "outils"):
        (tmp_path / base).mkdir()
    (tmp_path / "src" / "opsys" / "propre.py").write_text("x = 1  # une PME\n", encoding="utf-8")
    assert juger(balayer(tmp_path, termes), {}) == []

    soul = tmp_path / "departments" / "m01-x" / "SOUL.md"
    soul.write_text("Tu es l'adjoint d'une entreprise de gouttières.\n", encoding="utf-8")
    (tmp_path / "departments" / "m01-x" / "tests").mkdir()
    (tmp_path / "departments" / "m01-x" / "tests" / "t.py").write_text("gouttière\n", encoding="utf-8")  # exempté
    observe = balayer(tmp_path, termes)
    assert list(observe) == ["departments/m01-x/SOUL.md"]
    assert "hors exception" in juger(observe, {})[0]

    ok = {"departments/m01-x/SOUL.md": (frozenset({"gouttière"}), 1, "raison")}
    assert juger(observe, ok) == []
    assert "hors de l'exception" in juger(observe, {"departments/m01-x/SOUL.md": (frozenset({"fascia"}), 1, "r")})[0]
    soul.write_text("gouttière\nsoffite\n", encoding="utf-8")
    assert any("en permet 1" in p for p in juger(balayer(tmp_path, termes), ok))
    soul.write_text("Propre.\n", encoding="utf-8")
    assert "exception inutilisée" in juger(balayer(tmp_path, termes), ok)[0]
    (tmp_path / "src" / "opsys" / "fuite.json").write_text('{"d": "RÉNOVATION extérieure"}', encoding="utf-8")
    assert "src/opsys/fuite.json" in juger(balayer(tmp_path, termes), {})[0]  # accents et casse ne cachent rien


def test_aucun_fichier_texte_du_coeur_n_est_illisible_donc_non_garde():
    for fichier in fichiers_du_coeur(RACINE):
        fichier.read_text(encoding="utf-8")  # UnicodeDecodeError : un fichier non probant serait un trou de la garde


def test_les_termes_sectoriels_du_pack_couvrent_les_mots_des_services_et_du_vocabulaire(reno):
    """Si un pack ajoute un service ou un mot de métier, la liste que garde le cœur doit le suivre."""
    mots = {m for s in reno.services for m in s.mots_cles} | {s.libelle for s in reno.services}
    manquants = [m for m in sorted(mots) if not packs.termes_trouves(m, reno.termes_sectoriels)
                 and m.lower() not in {"réparation", "réparer"}]
    # « Réparation » est un mot du français courant : pas sectoriel à lui seul (le service l'est par ses voisins).
    assert manquants == [], manquants
    for definition in reno.vocabulaire.values():
        assert packs.termes_trouves(definition, reno.termes_sectoriels), definition


# =================================================================================================== 4. évaluation
@pytest.fixture(scope="module")
def entrees(deps):
    return executeur.charger_corpus_departements(deps)


def _cas_sectoriels(entrees, termes):
    return {c["id"]: c for e in entrees for c in e["corpus"]["cas"]
            if packs.termes_trouves(json.dumps(c, ensure_ascii=False), termes)}


def test_un_cas_du_corpus_qui_suppose_le_secteur_porte_pack_et_seulement_lui(entrees, termes):
    sectoriels = _cas_sectoriels(entrees, termes)
    sans_etiquette = sorted(i for i, c in sectoriels.items() if c.get("pack") != RENOVATION)
    assert sans_etiquette == [], f"cas sectoriels sans `pack: {RENOVATION}` : {sans_etiquette}"
    etiquetes = {c["id"] for e in entrees for c in e["corpus"]["cas"] if "pack" in c}
    assert etiquetes == set(sectoriels), f"cas étiquetés sans terme sectoriel : {sorted(etiquetes - set(sectoriels))}"
    assert len(etiquetes) == 22


def test_les_en_tetes_des_corpus_ne_portent_aucun_terme_sectoriel(entrees, termes):
    for e in entrees:
        entete = {k: v for k, v in e["corpus"].items() if k != "cas"}
        assert packs.termes_trouves(json.dumps(entete, ensure_ascii=False), termes) == [], e["chemin"]


@pytest.fixture(scope="module")
def rapports(entrees, deps):
    repondant = REPONDANTS_SIMULES["reference"]([e["corpus"] for e in entrees])
    return {pack: executeur.evaluer(entrees, repondant, deps, pack=pack) for pack in (RENOVATION, GENERIQUE, None)}


def test_avec_le_pack_renovation_le_repondant_reference_reussit_tous_les_cas(rapports, entrees):
    rapport = rapports[RENOVATION]
    total = sum(len(e["corpus"]["cas"]) for e in entrees)  # 120 à la tranche 1 ; M2 « ventes » en ajoute 16
    assert total >= 120 and rapport["global"]["effectif"] == total and rapport["global"]["reussites"] == total
    assert rapport["global"]["score"] == "1.0000" and rapport["global"]["departements_non_qualifies"] == []
    assert rapport["pack"]["actif"] == RENOVATION and rapport["pack"]["total_ecartes"] == 0


def test_avec_le_pack_generique_les_22_cas_sectoriels_sont_ecartes_et_nommes_et_le_reste_passe(rapports, entrees):
    rapport = rapports[GENERIQUE]
    neutres = sum(1 for e in entrees for c in e["corpus"]["cas"] if "pack" not in c)  # 98 à la tranche 1 ; 114 avec M2
    assert neutres >= 98 and rapport["global"]["effectif"] == neutres and rapport["global"]["reussites"] == neutres
    assert rapport["pack"]["total_ecartes"] == 22
    ecartes = {i for ids in rapport["pack"]["cas_ecartes"].values() for i in ids}
    assert ecartes == {c["id"] for e in entrees for c in e["corpus"]["cas"] if "pack" in c}
    assert ecartes.isdisjoint({i for d in rapport["departements"].values() for i in d["cas"]})


def test_sans_pack_donne_tous_les_cas_restent_et_le_corpus_garde_sa_meme_empreinte(rapports, entrees):
    total = sum(len(e["corpus"]["cas"]) for e in entrees)
    assert rapports[None]["global"]["effectif"] == total >= 120 and rapports[None]["pack"]["actif"] is None
    assert rapports[None]["corpus"] == rapports[RENOVATION]["corpus"] == rapports[GENERIQUE]["corpus"]


def test_un_pack_demande_non_installe_ou_un_cas_etiquete_d_un_pack_inconnu_est_un_refus(entrees):
    with pytest.raises(RefusEvaluation) as exc:
        executeur.appliquer_pack(entrees, "plomberie-qc")
    assert exc.value.code == "REJ-EVAL-CORPUS-PACK"
    coquille = [{**e, "corpus": {**e["corpus"], "cas": [dict(c) for c in e["corpus"]["cas"]]}} for e in entrees]
    coquille[0]["corpus"]["cas"][0]["pack"] = "renovation-exterieur-qc"  # faute de frappe : jamais écarté en silence
    with pytest.raises(RefusEvaluation) as exc:
        executeur.appliquer_pack(coquille, RENOVATION)
    assert exc.value.code == "REJ-EVAL-CORPUS-PACK" and "renovation-exterieur-qc" in exc.value.detail


def test_le_schema_du_corpus_refuse_une_etiquette_pack_mal_formee(entrees):
    corpus = json.loads(json.dumps(entrees[0]["corpus"]))
    for mauvaise in ("Rénovation", "../x", 12, "", "a b"):
        corpus["cas"][0]["pack"] = mauvaise
        with pytest.raises(RefusEvaluation) as exc:
            valider_corpus(corpus)
        assert exc.value.code == "REJ-EVAL-CORPUS-FORME" and exc.value.chemin.endswith(".pack")


def test_la_cli_evaluer_nomme_le_pack_dans_le_rapport_et_dans_le_nom_du_fichier(tmp_path, capsys):
    base = ["evaluer", "lancer", "--repondant", "reference", "--departement", "M6", "--sortie"]
    assert cli.main([*base, str(tmp_path / "a")]) == 0  # profil sans pack : generique-pme
    fichiers = capsys.readouterr().out.split()
    assert any(f.endswith(f"-{GENERIQUE}.json") for f in fichiers)
    rapport = json.loads(Path(next(f for f in fichiers if f.endswith(".json"))).read_text(encoding="utf-8"))
    assert rapport["pack"]["actif"] == GENERIQUE and rapport["pack"]["total_ecartes"] == 6
    texte = Path(next(f for f in fichiers if f.endswith(".md"))).read_text(encoding="utf-8")
    assert "Pack sectoriel actif : `generique-pme` ; cas écartés (d'un autre pack) : 6" in texte
    assert cli.main([*base, str(tmp_path / "b"), "--pack", RENOVATION]) == 0
    assert json.loads(Path(next(f for f in capsys.readouterr().out.split() if f.endswith(".json"))).read_text(
        encoding="utf-8"))["pack"]["total_ecartes"] == 0
    assert cli.main([*base, str(tmp_path / "c"), "--tous-les-cas"]) == 0
    assert any(f.endswith("-tous-les-cas.json") for f in capsys.readouterr().out.split())
    assert cli.main([*base, str(tmp_path / "d"), "--pack", "inconnu"]) == 2
    assert "REJ-EVAL-CORPUS-PACK" in capsys.readouterr().err
    with pytest.raises(SystemExit):  # --pack et --tous-les-cas s'excluent
        cli.main([*base, str(tmp_path / "e"), "--pack", RENOVATION, "--tous-les-cas"])


def test_le_repondant_passerelle_envoie_le_soul_effectif_du_pack_actif(deps, reno, generique):
    from opsys.evaluation.repondants import RepondantPasserelle, RequeteCas

    requete = RequeteCas("m1-x", "m01-front-office", "Léa", "Bonjour", (), {}, ())

    def corps(pack):
        rep = RepondantPasserelle(deps, url="http://passerelle.test", paliers={}, schemas_outils={}, pack=pack)
        return rep.construire_requete(requete, "opsys-standard")["messages"][0]["content"]

    avec, sans = corps(reno), corps(generique)
    assert "entreprise de rénovation extérieure au\nQuébec" in avec and "pack `renovation-exterieure-qc`" in avec
    assert "entreprise au\nQuébec" in sans and "{{" not in sans and "{{" not in avec
