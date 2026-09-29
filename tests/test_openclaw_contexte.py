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
from m10_memoire import (
    confidentialite,
    consolidation,
    decisions,
    faits_candidats,
    liaison,
    paquets,
    registre,
    signaux,
    variance,
    wct,
)

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

    contexte = _lire(fichiers, "contexte")
    niveaux = contexte.pop("niveaux")  # vérifié à part : un niveau par outil des départements
    assert contexte == {
        "actif": True,
        "serveur": "opsys_m10",
        "outil_paquet": "m10_paquet_contexte_affaire",
        "outil_depot": "m10_deposer_faits_candidats",
        "outil_affaire": "m10_affaire_de_la_session",
        "agents": {"m03-estimation": {"depot": ["m3_estimer_projet"], "affaire": "demande"}},
    }
    assert niveaux
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
    assert agents["m03-estimation"] == {"depot": ["m3_qualifier_photos", "m3_estimer_projet"], "affaire": "demande"}
    assert agents["m04-field-ops"] == {"depot": [], "affaire": "demande"}


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


# -- PLAN T3.3-suite-b : les niveaux des outils et l'affaire lue dans la session -------------------------


def test_niveaux_donne_le_niveau_effectif_de_chaque_outil_des_departements(departements, tmp_path):
    fichiers = _generer(departements, tmp_path, contexte_entreprise=ESTIMATION)

    niveaux = _lire(fichiers, "contexte")["niveaux"]

    attendus = {nom: outil.niveau_effectif.value for nom, (_dep, outil) in openclaw.tous_les_outils(
        departements.values()).items()}
    assert niveaux == attendus
    assert len(niveaux) == sum(len(dep.charger_outils()) for dep in departements.values())


def test_les_outils_qui_engagent_l_entreprise_sont_au_niveau_n3_ou_plus_dans_la_configuration(departements, tmp_path):
    niveaux = _lire(_generer(departements, tmp_path, contexte_entreprise=ESTIMATION), "contexte")["niveaux"]

    assert niveaux["m3_estimer_projet"] == "N3"
    assert niveaux["m3_creer_devis"] == "N3"
    assert niveaux["m10_clore_signal"] == "N3"
    assert niveaux["m10_prendre_en_compte_signal"] == "N3"
    assert niveaux["m10_lier_session_affaire"] == "N3"
    assert niveaux["m5_enregistrer_mouvement"] == "N5"
    # les lectures et le dépôt interne du core restent sous le seuil du garde
    assert niveaux["m10_paquet_contexte_affaire"] == "N0"
    assert niveaux["m10_affaire_de_la_session"] == "N0"
    assert niveaux["m10_lister_signaux"] == "N0"
    assert niveaux["m10_deposer_faits_candidats"] == "N2"


def test_le_niveau_ecrit_suit_le_niveau_de_l_outil_pas_une_liste_figee(departements, tmp_path, monkeypatch):
    reels = openclaw.tous_les_outils

    def estimer_en_n4(deps):
        index = dict(reels(deps))
        dep, outil = index["m3_estimer_projet"]
        index["m3_estimer_projet"] = (dep, dataclasses.replace(outil, niveau=Niveau.N4))
        return index

    monkeypatch.setattr(openclaw, "tous_les_outils", estimer_en_n4)

    niveaux = _lire(_generer(departements, tmp_path, contexte_entreprise=ESTIMATION), "contexte")["niveaux"]

    assert niveaux["m3_estimer_projet"] == "N4"


def test_l_affaire_vient_de_la_session_pour_les_seuls_agents_nommes(departements, tmp_path):
    fichiers = _generer(
        departements,
        tmp_path,
        contexte_entreprise={"m01-front-office": [], "m03-estimation": ["m3_estimer_projet"]},
        affaire_par_session=["m01-front-office"],
    )

    agents = _lire(fichiers, "contexte")["agents"]
    assert agents["m01-front-office"] == {"depot": [], "affaire": "session"}
    assert agents["m03-estimation"] == {"depot": ["m3_estimer_projet"], "affaire": "demande"}


def test_la_lecture_de_l_affaire_de_la_session_est_une_lecture_de_m10_fermee_aux_appareils(departements):
    outils = {o.nom: o for o in departements["m10-memoire"].charger_outils()}

    lecture = outils[openclaw.OUTIL_AFFAIRE_SESSION]
    assert lecture.niveau_effectif is Niveau.N0
    assert not lecture.roles_appareil  # appelée par le core seulement


def test_refuse_de_lire_l_affaire_dans_la_session_pour_un_agent_sans_moteur_de_contexte(departements, tmp_path):
    with pytest.raises(ValueError, match="n'active pas le moteur de contexte"):
        _generer(departements, tmp_path, contexte_entreprise=ESTIMATION, affaire_par_session=["m01-front-office"])

    assert _rien_ecrit(tmp_path)


def test_refuse_l_affaire_par_session_si_m10_ne_sait_pas_la_lire(departements, tmp_path, monkeypatch):
    reels = openclaw.tous_les_outils

    def sans_lecture(deps):
        index = dict(reels(deps))
        index.pop(openclaw.OUTIL_AFFAIRE_SESSION)
        return index

    monkeypatch.setattr(openclaw, "tous_les_outils", sans_lecture)

    with pytest.raises(ValueError, match=f"l'outil {openclaw.OUTIL_AFFAIRE_SESSION} manque"):
        _generer(departements, tmp_path, contexte_entreprise={"m01-front-office": []},
                 affaire_par_session=["m01-front-office"])

    assert _rien_ecrit(tmp_path)


def test_refuse_l_affaire_par_session_si_la_lecture_n_est_plus_une_lecture(departements, tmp_path, monkeypatch):
    reels = openclaw.tous_les_outils

    def lecture_t1(deps):
        index = dict(reels(deps))
        dep, outil = index[openclaw.OUTIL_AFFAIRE_SESSION]
        index[openclaw.OUTIL_AFFAIRE_SESSION] = (dep, dataclasses.replace(outil, autonomie=openclaw.Autonomie.T1))
        return index

    monkeypatch.setattr(openclaw, "tous_les_outils", lecture_t1)

    with pytest.raises(ValueError, match="doit être une lecture"):
        _generer(departements, tmp_path, contexte_entreprise={"m01-front-office": []},
                 affaire_par_session=["m01-front-office"])

    assert _rien_ecrit(tmp_path)


def test_sans_affaire_par_session_l_outil_de_lecture_n_est_pas_exige(departements, tmp_path, monkeypatch):
    reels = openclaw.tous_les_outils

    def sans_lecture(deps):
        index = dict(reels(deps))
        index.pop(openclaw.OUTIL_AFFAIRE_SESSION)
        return index

    monkeypatch.setattr(openclaw, "tous_les_outils", sans_lecture)

    fichiers = _generer(departements, tmp_path, contexte_entreprise=ESTIMATION)

    assert _lire(fichiers, "contexte")["agents"]["m03-estimation"]["affaire"] == "demande"


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
        "m03-estimation": {"depot": ["m3_estimer_projet", "m3_qualifier_photos"], "affaire": "demande"},
        "m04-field-ops": {"depot": [], "affaire": "demande"},
    }
    plugins = json.loads((config / "opsys" / "plugins.json").read_text(encoding="utf-8"))
    assert plugins["slots"] == {"contextEngine": "opsys"}


def test_la_commande_lit_l_affaire_dans_la_session_pour_les_agents_nommes(tmp_path, monkeypatch, capsys):
    _preparer_commande(monkeypatch)
    config = tmp_path / "oc"

    code = cli.main([
        "openclaw", "configurer", "--config-dir", str(config),
        "--contexte-entreprise", "m01-front-office",
        "--contexte-entreprise", "m03-estimation:m3_estimer_projet",
        "--affaire-par-session", "m01-front-office",
    ])

    assert code == 0
    capsys.readouterr()
    contexte = json.loads((config / "opsys" / "contexte.json").read_text(encoding="utf-8"))
    assert contexte["agents"]["m01-front-office"]["affaire"] == "session"
    assert contexte["agents"]["m03-estimation"]["affaire"] == "demande"


def test_la_commande_refuse_une_affaire_par_session_sans_moteur_de_contexte_pour_l_agent(
    tmp_path, monkeypatch, capsys
):
    _preparer_commande(monkeypatch)

    with pytest.raises(ValueError, match="n'active pas le moteur de contexte"):
        cli.main(["openclaw", "configurer", "--config-dir", str(tmp_path / "oc"),
                  "--contexte-entreprise", "m03-estimation", "--affaire-par-session", "m01-front-office"])

    capsys.readouterr()
    assert _rien_ecrit(tmp_path / "oc")


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
    for cle in ("actif", "serveur", "outil_paquet", "outil_depot", "outil_affaire", "delai_ms", "niveaux", "agents",
                "depot", "affaire"):
        assert f"raw.{cle}" in lecture or f"settings.{cle}" in lecture or f'"{cle}"' in lecture, cle
    assert f'"{openclaw.OUTIL_PAQUET_CONTEXTE}"' in lecture
    assert f'"{openclaw.OUTIL_DEPOT_FAITS}"' in lecture
    assert f'"{openclaw.OUTIL_AFFAIRE_SESSION}"' in lecture
    for source in (openclaw.AFFAIRE_DEMANDE, openclaw.AFFAIRE_SESSION):
        assert f'"{source}"' in lecture, source


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
                "source", "resume", "signaux", "nb_ouverts", "nb_pris_en_compte", "nb_clos", "confidentialite",
                "agent", "regle", "nb_retenus", "etat", "traite_par", "traite_le"):
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


def _liste_ts(source, nom):
    """Les chaînes d'un tableau `const NOM = [...]` (ou `NOM: readonly X[] = [...]`) du code du core."""
    declaration = re.search(rf"{nom}[^=]*= \[(.*?)\]", source, re.DOTALL)
    assert declaration is not None, nom
    return re.findall(r'"([A-Za-z_0-9]+)"', declaration.group(1))


def test_les_niveaux_de_confidentialite_qu_un_paquet_peut_porter_sont_ceux_de_m10():
    lecture = _source("opsys-contexte-paquet.ts")

    portes_par_le_core = set(_liste_ts(lecture, "OPSYS_PAQUET_LEVELS"))

    assert portes_par_le_core == {"PUBLIC_INTERNAL", "INTERNAL", "CLIENT_PRIVATE"}
    assert portes_par_le_core <= confidentialite.niveaux_connus()
    # les quatre niveaux fermés ne sortent jamais de M10 : le core les refuse aussi
    for ferme in ("SENSITIVE", "FINANCIAL", "SECRET_REF", "LEGAL_LOCKED"):
        assert ferme in confidentialite.niveaux_connus() and ferme not in portes_par_le_core
        for couche in paquets._COUCHES_ORDRE:
            for agent in ("m01-front-office", "m02-revenue-crm", None):
                assert ferme not in confidentialite.niveaux_admis(couche, agent)


def test_les_etats_d_un_signal_sont_ceux_de_m10_dans_le_meme_ordre():
    lecture = _source("opsys-contexte-paquet.ts")

    assert _liste_ts(lecture, "SIGNAL_STATES") == [
        signaux.ETAT_OUVERT, signaux.ETAT_PRIS_EN_COMPTE, signaux.ETAT_CLOS]


def test_les_niveaux_n_du_core_sont_l_echelle_de_python_dans_l_ordre():
    config = _source("opsys-contexte-config.ts")

    assert _liste_ts(config, "OPSYS_TOOL_LEVELS") == [niveau.value for niveau in Niveau]


def test_le_seuil_du_garde_est_n3_le_premier_niveau_qui_exige_une_validation_humaine():
    garde = _source("opsys-contexte-garde.ts")

    assert 'OPSYS_TOOL_LEVELS.indexOf("N3")' in garde
    assert [niveau.value for niveau in Niveau][3] == "N3"


def test_les_noms_d_outils_que_le_core_accepte_sont_ceux_des_outils_des_departements(departements):
    config = _source("opsys-contexte-config.ts")
    garde = _source("opsys-contexte-garde.ts")
    motif_config = re.search(r"TOOL_PATTERN = /(.*?)/u;", config)
    motif_garde = re.search(r"OPSYS_TOOL_NAME = /(.*?)/u;", garde)
    assert motif_config is not None and motif_garde is not None
    outils = openclaw.tous_les_outils(departements.values())

    for nom in outils:
        assert re.fullmatch(motif_config.group(1), nom), nom  # un niveau peut être écrit pour chaque outil
        assert re.fullmatch(motif_garde.group(1), nom), nom
    for hors_opsys in ("read", "exec", "memory_search", "message", "m11_outil", "m3_", "opsys_"):
        assert not re.fullmatch(motif_garde.group(1), hors_opsys), hors_opsys


def test_le_core_envoie_a_m10_les_arguments_que_ses_outils_declarent(departements):
    moteur = _source("opsys-contexte-engine.ts")
    outils = {o.nom: o for o in departements["m10-memoire"].charger_outils()}

    assert "agent:" in moteur and "cle_session:" in moteur
    assert "agent" in outils[openclaw.OUTIL_PAQUET_CONTEXTE].parametres["properties"]
    assert "agent" not in outils[openclaw.OUTIL_PAQUET_CONTEXTE].parametres["required"]  # absent : vue restrictive
    assert set(outils[openclaw.OUTIL_AFFAIRE_SESSION].parametres["required"]) == {"cle_session"}


def test_la_forme_d_une_affaire_est_la_meme_pour_le_core_et_pour_m10():
    lecture = _source("opsys-contexte-paquet.ts")
    motif = re.search(r"AFFAIRE_ID = /(.*?)/u;", lecture)
    assert motif is not None

    assert motif.group(1) == liaison._AFFAIRE.pattern
    assert motif.group(1) == faits_candidats._AFFAIRE.pattern


def _valeurs(noeud):
    """Toutes les feuilles (texte, nombre, booléen, null) d'un paquet, en profondeur."""
    if isinstance(noeud, dict):
        for valeur in noeud.values():
            yield from _valeurs(valeur)
    elif isinstance(noeud, list):
        for valeur in noeud:
            yield from _valeurs(valeur)
    else:
        yield noeud


def _cas_des_fixtures_du_core():
    """Le cas fictif des fixtures du core (`opsys-contexte.test-support.ts`), rejoué dans M10 : une règle
    validée, un fait consolidé, un WCT, une variance critique ; le paquet est demandé pour `m03-estimation`."""
    evenements, affaires = registre.Registre(), registre.Registre()
    decisions.enregistrer_decision(
        {"decision_id": "REGLE-001", "raison": "Toujours confirmer la longueur des gouttières mesurée sur place.",
         "statut": "validee", "options_ecartees": "Se fier aux photos seules"},
        affaires, "2026-09-01T09:00:00-04:00")
    wct.memoriser_wct({
        "wct_id": "WCT-001", "intervention_id": "INT-001", "lead_id": "LEAD-001", "technicien_id": "TECH-001",
        "horodatage_completion": "2026-09-15T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 95, "ecart_signale": True, "revue_id": None, "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M10"], "devis_id": "DEV-001"}, evenements)
    variance.memoriser_variance({
        "evenement_id": "EVT-001", "wct_id": "WCT-001", "intervention_id": "INT-001", "chantier_id": "CH-001",
        "statut_variance": "evaluee", "signal_critique": True, "seuil_pourcentage": 0.1,
        "horodatage_completion": "2026-09-15T14:05:00-04:00", "lignes": []}, evenements)
    consolidation.consolider_affaire("LEAD-001", "2026-09-15", "2026-09-16T03:00:00-04:00", evenements, affaires)
    return evenements, affaires


def _paquet_de_m10(evenements, affaires, affaire="LEAD-001"):
    return paquets.assembler_paquet_contexte(
        affaire, "2026-09-28T10:15:00+00:00", evenements, affaires, agent="m03-estimation")


def test_les_paquets_de_test_du_core_sont_la_sortie_reelle_de_m10():
    """Si M10 change un champ, un compteur ou un hachage, les fixtures du core (copiées telles quelles) ne
    sont plus sa sortie : ce test rougit au lieu de laisser le core vert contre une forme périmée."""
    fixtures = _source("opsys-contexte.test-support.ts")
    evenements, affaires = _cas_des_fixtures_du_core()
    ouvert = _paquet_de_m10(evenements, affaires)
    signaux.traiter_signal(
        signaux.ACTION_PRISE_EN_COMPTE, "EVT-001", "amina.admin", "admin", "appareil",
        "Lu par l'admin : on vérifie la facture avec le client.", "2026-09-17T08:30:00-04:00", evenements, affaires)
    signaux.traiter_signal(
        signaux.ACTION_CLOTURE, "EVT-001", "amina.admin", "admin", "appareil",
        "Écart expliqué : gouttière refaite, facture corrigée.", "2026-09-18T16:00:00-04:00", evenements, affaires)
    clos = _paquet_de_m10(evenements, affaires)
    vide = _paquet_de_m10(registre.Registre(), registre.Registre(), affaire="LEAD-777")

    for nom, paquet in (("PAQUET_M10", ouvert), ("PAQUET_M10_SIGNAL_CLOS", clos), ("PAQUET_M10_VIDE", vide)):
        bloc = re.search(rf"export const {nom} = \{{(.*?)\n\}};", fixtures, re.DOTALL)
        assert bloc is not None, nom
        for valeur in _valeurs(paquet):
            assert json.dumps(valeur, ensure_ascii=False) in bloc.group(1), (nom, valeur)
