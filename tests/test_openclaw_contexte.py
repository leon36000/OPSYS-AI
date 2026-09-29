"""PLAN T3.3-suite : configuration du moteur de contexte du core (`opsys/contexte.json`, `plugins.slots`).

Preuve que `openclaw.generer()` écrit `contexte.json` et le choix du moteur ensemble ou pas du tout :
désactivé par défaut (aucun changement pour les agents), activé pour les seuls agents nommés, refusé en
fail-closed avant toute écriture si M10 ne peut pas servir le core. Le contrat avec le code TypeScript
(`core/src/context-engine/opsys-contexte-*.ts`) est épinglé ici en lisant ce code : la Python et le core
ne peuvent pas diverger sans qu'un test rougisse. Départements RÉELS, jamais de donnée client.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest
from m10_memoire import faits_candidats, paquets

from opsys import cli, modeles, openclaw
from opsys.departements import charger_departements
from opsys.outils import Niveau

FICTIF = True  # aucune donnée réelle : des noms d'agents et d'outils, un dossier de configuration jetable

RACINE = Path(__file__).resolve().parents[1]
MOTEUR = RACINE / "core" / "src" / "context-engine"

PALIERS = {
    "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "fort": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
}
ENVIRON = {"OPSYS_EMBEDDINGS_URL": "http://embeddings-test:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "bge-m3"}
ESTIMATION = {"m03-estimation": ["m3_estimer_projet"]}


@pytest.fixture(scope="module")
def departements():
    return charger_departements()


def _generer(departements, dossier, **options):
    return openclaw.generer(departements, dossier, PALIERS, environ=ENVIRON, **options)


def _lire(fichiers, cle):
    return json.loads(fichiers[cle].read_text(encoding="utf-8"))


# -- Désactivé par défaut ----------------------------------------------------------------------


def test_desactive_par_defaut_aucun_moteur_choisi_et_contexte_inactif(departements, tmp_path):
    fichiers = _generer(departements, tmp_path)

    assert _lire(fichiers, "contexte") == {"actif": False}
    assert "slots" not in _lire(fichiers, "plugins")


def test_un_dictionnaire_vide_est_le_meme_que_l_absence_d_argument(departements, tmp_path):
    fichiers = _generer(departements, tmp_path, contexte_entreprise={})

    assert _lire(fichiers, "contexte") == {"actif": False}
    assert "slots" not in _lire(fichiers, "plugins")


def test_le_squelette_openclaw_json_n_inclut_pas_contexte_json(tmp_path):
    """Comme `roles.json` et `metier.json` : lu directement par le core, jamais par `$include`."""
    racine = json.loads(openclaw.racine_si_absente(tmp_path).read_text(encoding="utf-8"))

    assert "contexte" not in racine
    assert "contexte" not in json.dumps(racine)


# -- Activé : un seul interrupteur, deux fichiers d'accord --------------------------------------


def test_active_ecrit_contexte_json_et_le_choix_du_moteur_ensemble(departements, tmp_path):
    fichiers = _generer(departements, tmp_path, contexte_entreprise=ESTIMATION)

    assert _lire(fichiers, "contexte") == {
        "actif": True,
        "serveur": "opsys_m10",
        "outil_paquet": "m10_paquet_contexte_affaire",
        "outil_depot": "m10_deposer_faits_candidats",
        "agents": {"m03-estimation": {"depot": ["m3_estimer_projet"]}},
    }
    plugins = _lire(fichiers, "plugins")
    assert plugins["slots"] == {"contextEngine": "opsys"}
    assert plugins["entries"]["memory-core"]["config"]["dreaming"]["enabled"] is True  # inchangé


def test_regenerer_sans_l_option_desactive_les_deux_fichiers(departements, tmp_path):
    _generer(departements, tmp_path, contexte_entreprise=ESTIMATION)

    fichiers = _generer(departements, tmp_path)

    assert _lire(fichiers, "contexte") == {"actif": False}
    assert "slots" not in _lire(fichiers, "plugins")


def test_agents_tries_outils_dedoubles_et_paquet_seul_possible(departements, tmp_path):
    fichiers = _generer(
        departements,
        tmp_path,
        contexte_entreprise={
            "m04-field-ops": [],
            "m03-estimation": ["m3_qualifier_photos", "m3_estimer_projet", "m3_qualifier_photos"],
        },
    )

    agents = _lire(fichiers, "contexte")["agents"]
    assert list(agents) == ["m03-estimation", "m04-field-ops"]
    assert agents["m03-estimation"] == {"depot": ["m3_qualifier_photos", "m3_estimer_projet"]}
    assert agents["m04-field-ops"] == {"depot": []}


def test_le_serveur_nomme_est_celui_de_mcp_json_avec_le_jeton_d_entete(departements, tmp_path):
    """Le core appelle M10 par la voie existante : même serveur, même URL, même en-tête que les agents."""
    fichiers = _generer(departements, tmp_path, contexte_entreprise=ESTIMATION)

    serveur = _lire(fichiers, "mcp")["servers"][_lire(fichiers, "contexte")["serveur"]]
    assert serveur["url"].endswith("/mcp/m10-memoire")
    assert serveur["transport"] == "streamable-http"
    assert serveur["headers"] == {"Authorization": "Bearer ${OPSYS_MCP_JETON}"}


def test_les_deux_outils_appeles_existent_avec_les_niveaux_que_le_core_suppose(departements):
    outils = {o.nom: o for o in departements["m10-memoire"].charger_outils()}

    lecture = outils[openclaw.OUTIL_PAQUET_CONTEXTE]
    depot = outils[openclaw.OUTIL_DEPOT_FAITS]
    assert lecture.niveau_effectif is Niveau.N0  # lecture : jamais d'approbation
    assert depot.niveau_effectif is Niveau.N2  # tâche interne : jamais d'approbation en mode ombre
    assert not depot.roles_appareil  # réservé au core, fermé aux appareils


# -- Fail-closed : rien n'est écrit, même en partie ---------------------------------------------


def _rien_ecrit(dossier):
    return not (dossier / "opsys").exists()


@pytest.mark.parametrize(
    ("contexte", "message"),
    [
        ({"m99-inconnu": []}, "agent inconnu"),
        ({"m03-estimation": ["m3_outil_qui_n_existe_pas"]}, "n'est pas un outil du département m03-estimation"),
        ({"m03-estimation": ["m4_pointer"]}, "n'est pas un outil du département m03-estimation"),
        ({"m03-estimation": ["opsys_etat_budget"]}, "n'est pas un outil du département m03-estimation"),
    ],
)
def test_refuse_un_agent_ou_un_outil_incoherent_sans_rien_ecrire(departements, tmp_path, contexte, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        _generer(departements, tmp_path, contexte_entreprise=contexte)

    assert _rien_ecrit(tmp_path)


def test_refuse_sans_le_departement_memoire(departements, tmp_path):
    sans_memoire = {ident: dep for ident, dep in departements.items() if ident != "m10-memoire"}

    with pytest.raises(ValueError, match="le département m10-memoire est absent"):
        _generer(sans_memoire, tmp_path, contexte_entreprise=ESTIMATION)

    assert _rien_ecrit(tmp_path)


def test_refuse_si_un_des_deux_outils_de_m10_manque(departements, tmp_path, monkeypatch):
    reels = openclaw.tous_les_outils

    def sans_depot(deps):
        index = dict(reels(deps))
        index.pop(openclaw.OUTIL_DEPOT_FAITS)
        return index

    monkeypatch.setattr(openclaw, "tous_les_outils", sans_depot)

    with pytest.raises(ValueError, match=f"l'outil {openclaw.OUTIL_DEPOT_FAITS} manque"):
        _generer(departements, tmp_path, contexte_entreprise=ESTIMATION)

    assert _rien_ecrit(tmp_path)


def test_refuse_si_le_depot_exigerait_une_approbation(departements, tmp_path, monkeypatch):
    """En N3, le mode ombre de M10 mettrait chaque dépôt en attente : le core n'écrirait jamais rien."""
    reels = openclaw.tous_les_outils

    def depot_n3(deps):
        index = dict(reels(deps))
        dep, outil = index[openclaw.OUTIL_DEPOT_FAITS]
        index[openclaw.OUTIL_DEPOT_FAITS] = (dep, dataclasses.replace(outil, niveau=Niveau.N3))
        return index

    monkeypatch.setattr(openclaw, "tous_les_outils", depot_n3)

    with pytest.raises(ValueError, match="exigerait une approbation en mode ombre"):
        _generer(departements, tmp_path, contexte_entreprise=ESTIMATION)

    assert _rien_ecrit(tmp_path)


def test_refuse_si_la_lecture_du_paquet_n_est_plus_une_lecture(departements, tmp_path, monkeypatch):
    reels = openclaw.tous_les_outils

    def lecture_t1(deps):
        index = dict(reels(deps))
        dep, outil = index[openclaw.OUTIL_PAQUET_CONTEXTE]
        index[openclaw.OUTIL_PAQUET_CONTEXTE] = (dep, dataclasses.replace(outil, autonomie=openclaw.Autonomie.T1))
        return index

    monkeypatch.setattr(openclaw, "tous_les_outils", lecture_t1)

    with pytest.raises(ValueError, match="doit être une lecture"):
        _generer(departements, tmp_path, contexte_entreprise=ESTIMATION)

    assert _rien_ecrit(tmp_path)


# -- La commande réelle -------------------------------------------------------------------------


def _preparer_commande(monkeypatch):
    monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", ENVIRON["OPSYS_EMBEDDINGS_URL"])
    monkeypatch.setenv("OPSYS_EMBEDDINGS_MODELE", ENVIRON["OPSYS_EMBEDDINGS_MODELE"])
    modeles.enregistrer_paliers(PALIERS)


def test_la_commande_sans_option_laisse_le_moteur_desactive(tmp_path, monkeypatch, capsys):
    _preparer_commande(monkeypatch)
    config = tmp_path / "oc"

    assert cli.main(["openclaw", "configurer", "--config-dir", str(config)]) == 0

    capsys.readouterr()
    assert json.loads((config / "opsys" / "contexte.json").read_text(encoding="utf-8")) == {"actif": False}
    assert "slots" not in json.loads((config / "opsys" / "plugins.json").read_text(encoding="utf-8"))


def test_la_commande_active_le_moteur_pour_les_agents_nommes(tmp_path, monkeypatch, capsys):
    _preparer_commande(monkeypatch)
    config = tmp_path / "oc"

    code = cli.main([
        "openclaw", "configurer", "--config-dir", str(config),
        "--contexte-entreprise", "m03-estimation:m3_estimer_projet",
        "--contexte-entreprise", "m04-field-ops",
        "--contexte-entreprise", "m03-estimation:m3_qualifier_photos",
    ])

    assert code == 0
    assert "contexte:" in capsys.readouterr().out
    contexte = json.loads((config / "opsys" / "contexte.json").read_text(encoding="utf-8"))
    assert contexte["agents"] == {
        "m03-estimation": {"depot": ["m3_estimer_projet", "m3_qualifier_photos"]},
        "m04-field-ops": {"depot": []},
    }
    plugins = json.loads((config / "opsys" / "plugins.json").read_text(encoding="utf-8"))
    assert plugins["slots"] == {"contextEngine": "opsys"}


def test_la_commande_refuse_un_agent_sans_nom(tmp_path, monkeypatch, capsys):
    _preparer_commande(monkeypatch)

    with pytest.raises(SystemExit) as sortie:
        cli.main(["openclaw", "configurer", "--config-dir", str(tmp_path / "oc"),
                  "--contexte-entreprise", ":m3_estimer_projet"])

    assert sortie.value.code == 2
    assert "agent manquant" in capsys.readouterr().err
    assert _rien_ecrit(tmp_path / "oc")


# -- Contrat avec le code du core (lu, pas exécuté) ---------------------------------------------


def _source(nom):
    return (MOTEUR / nom).read_text(encoding="utf-8")


def test_le_core_choisit_le_moteur_sous_l_identifiant_que_python_ecrit():
    assert f'OPSYS_CONTEXT_ENGINE_ID = "{openclaw.MOTEUR_CONTEXTE}"' in _source("opsys-contexte-engine.ts")


def test_le_core_lit_les_cles_que_python_ecrit_dans_contexte_json():
    lecture = _source("opsys-contexte-config.ts")
    for cle in ("actif", "serveur", "outil_paquet", "outil_depot", "delai_ms", "agents", "depot"):
        assert f"raw.{cle}" in lecture or f"settings.{cle}" in lecture or f'"{cle}"' in lecture, cle
    assert f'"{openclaw.OUTIL_PAQUET_CONTEXTE}"' in lecture
    assert f'"{openclaw.OUTIL_DEPOT_FAITS}"' in lecture


def test_le_core_attend_les_quatre_couches_de_m10_dans_le_meme_ordre():
    lecture = _source("opsys-contexte-paquet.ts")
    noms = [
        paquets.COUCHE_REGLES_ENTREPRISE,
        paquets.COUCHE_FAITS_AFFAIRE,
        paquets.COUCHE_EVENEMENTS_RECENTS,
        paquets.COUCHE_SIGNAUX_NON_RESOLUS,
    ]
    declaration = re.search(r"OPSYS_PAQUET_LAYERS = \[(.*?)\] as const", lecture, re.DOTALL)
    assert declaration is not None
    assert re.findall(r'"([a-z_]+)"', declaration.group(1)) == noms


def test_le_core_lit_les_champs_du_paquet_que_m10_produit():
    lecture = _source("opsys-contexte-paquet.ts")
    for cle in ("affaire_id", "budget_caracteres", "caracteres_utilises", "couches", "nom", "vide", "tronque",
                "nb_total", "nb_inclus", "nb_omis", "caracteres", "faits", "identifiant", "horodatage",
                "source", "resume"):
        assert f".{cle}" in lecture or f"{cle}," in lecture or f"{cle}:" in lecture, cle


def test_le_core_envoie_les_champs_que_m10_accepte_au_depot():
    depot = _source("opsys-contexte-depot.ts")
    moteur = _source("opsys-contexte-engine.ts")
    for champ in sorted(faits_candidats.CHAMPS_FAIT_CANDIDAT):
        assert f"{champ}:" in depot or f"{champ}," in depot, champ
    for argument in ("affaire_id", "departement", "faits", "horodatage"):
        assert f"{argument}:" in moteur, argument


def test_la_forme_d_un_code_est_la_meme_des_deux_cotes():
    """`CODE_PATTERN` du core et `_CODE` de M10 : un code que le core garde, M10 l'accepte."""
    depot = _source("opsys-contexte-depot.ts")
    motif = re.search(r"CODE_PATTERN = /(.*?)/u;", depot)
    assert motif is not None
    assert motif.group(1) == faits_candidats._CODE.pattern


def test_la_taille_de_lot_du_core_est_celle_que_m10_accepte():
    moteur = _source("opsys-contexte-engine.ts")
    lot = re.search(r"DEPOSIT_BATCH_SIZE = (\d+);", moteur)
    assert lot is not None
    assert int(lot.group(1)) == faits_candidats.NB_FAITS_MAX_PAR_DEPOT


def test_le_marqueur_d_indisponibilite_est_dans_le_contexte_du_tour():
    assert "contexte d'entreprise indisponible" in _source("opsys-contexte-paquet.ts")
