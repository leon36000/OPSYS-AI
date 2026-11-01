"""Corpus transverse de sécurité MCP dans le gabarit d'évaluation : la dérive d'outil et la violation de Rule of Two
sont
refusées, avec le bon code, sur les outils réels ; une garde complaisante échoue ; le corpus des départements est
intact.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
from pathlib import Path

import pytest
import yaml

from opsys.departements import charger_departements
from opsys.evaluation import corpus as corpus_dept
from opsys.evaluation import securite_mcp as sm
from opsys.evaluation.cli import ajouter_commandes, executer
from opsys.evaluation.corpus import RefusEvaluation
from opsys.registre_mcp.inventaire import inventaire

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def definitions():
    @contextlib.contextmanager
    def pas_de_base():
        yield None

    return inventaire(charger_departements(RACINE / "departments"), pas_de_base)


@pytest.fixture(scope="module")
def corpus():
    return sm.charger_corpus_mcp()


def test_le_corpus_est_valide_ecrit_a_la_main_et_couvre_les_familles(corpus):
    cas = corpus["cas"]
    assert corpus["fictif"] is True and len(cas) >= 35
    mutations = {c.get("mutation") for c in cas}
    assert {"description_ajout", "description_homoglyphe", "description_invisible", "schema_propriete",
            "schema_requis_retire", "schema_ouvert", "niveau", "renommer"} <= mutations
    codes = {c["attendu"].get("code") for c in cas}
    assert {"REJ-MCP-EMPREINTE-DERIVE", "REJ-MCP-NIVEAU-DERIVE", "REJ-MCP-OUTIL-INCONNU", "REJ-MCP-RULE-OF-TWO",
            "REJ-MCP-SURFACE-NON-FIABLE", "REJ-MCP-EXPOSITION-INVALIDE", None} == codes
    bloquants = [c for c in cas if c["gravite"] == "bloquante"]
    temoins = sum(1 for c in cas if c["attendu"]["decision"] == "autoriser")
    assert len(bloquants) >= 20 and temoins >= 8


def test_sur_les_outils_reels_les_37_cas_passent_et_la_garde_est_qualifiee(corpus, definitions):
    rapport = sm.evaluer(corpus, definitions)
    assert rapport["echecs"] == [] and rapport["reussis"] == rapport["cas"] >= 35
    assert rapport["qualifie"] is True and rapport["score"] == 1.0 and rapport["bloquants_echoues"] == []
    assert len(rapport["empreinte_corpus"]) == 64 and rapport["garde"]["rule_of_two"] is True
    assert rapport == sm.evaluer(corpus, definitions)  # déterministe


def test_une_garde_complaisante_echoue_sur_chaque_cas_bloquant_de_refus(corpus, definitions):
    """Preuve que le corpus mord : un registre scellé sur l'outil DÉJÀ altéré et sans Rule of Two accepte tout ; chaque
    refus bloquant attendu est alors manqué (sauf l'exposition mal formée, refusée avant la garde par l'analyse de
    l'hôte)."""
    par_nom = {d.nom: d for d in definitions}
    manques, attendus = set(), set()
    for cas in corpus["cas"]:
        mutation = cas.get("mutation", "aucune")
        alteree = sm._muter(par_nom[cas["outil"]], mutation, cas.get("valeur"))  # noqa: SLF001
        base = [alteree if d.nom == cas["outil"] else d for d in definitions]
        garde = sm.garde_complaisante(base if alteree.nom == cas["outil"] else [*base, alteree])
        resultat = sm.evaluer_cas(cas, par_nom, garde)
        if cas["gravite"] == "bloquante" and cas["attendu"]["decision"] == "refuser":
            attendus.add(cas["id"])
            if not resultat.reussi:
                manques.add(cas["id"])
    assert len(attendus) >= 18
    assert attendus - {"mcp-exposition-invalide"} == manques


def test_une_garde_sans_rule_of_two_echoue_sur_les_cas_rule_of_two(corpus, definitions):
    from opsys.registre_mcp import registre as reg
    from opsys.registre_mcp.garde import REGISTRE_LIVRE, GardeMCP

    garde = GardeMCP(reg.charger(REGISTRE_LIVRE), surfaces=frozenset({"departement", "contexte", "runtime"}),
                     rule_of_two_active=False, silencieux=True)
    rapport = sm.evaluer(corpus, definitions, garde)
    manques = set(rapport["bloquants_echoues"])
    assert {"mcp-r2-courriel-vers-envoi", "mcp-r2-ingestion-vers-paiement", "mcp-r2-web-vers-publication",
            "mcp-r2-table-alteree", "mcp-r2-approbation-non-humaine", "mcp-surface-ecriture-interne"} <= manques
    assert "mcp-derive-description-ajout" not in manques  # la dérive, elle, reste attrapée par le registre


def test_un_registre_perime_fait_echouer_les_temoins(corpus, definitions):
    import dataclasses

    perime = [dataclasses.replace(d,
                                  description=d.description + " (modifiée)") if d.nom == "m1_filtrer_provenance" else d
              for d in definitions]
    rapport = sm.evaluer(corpus, perime)
    assert "mcp-temoin-lecture" in rapport["bloquants_echoues"] and not rapport["qualifie"]


def test_validation_fermee_du_corpus(corpus):
    def avec(modif):
        copie = copy.deepcopy(corpus)
        modif(copie)
        return copie

    cas_invalides = [
        lambda c: c.update({"surprise": 1}),
        lambda c: c.update({"fictif": False}),
        lambda c: c.update({"schema": "autre"}),
        lambda c: c["cas"][0].update({"champ_inconnu": 1}),
        lambda c: c["cas"][1].update({"id": c["cas"][0]["id"]}),
        lambda c: c["cas"][0].update({"gravite": "grave"}),
        lambda c: c["cas"][0].update({"poids": 9}),
        lambda c: c["cas"][3].update({"mutation": "magie"}),
        lambda c: c["cas"][3]["attendu"].update({"code": "REJ-MCP-INVENTE"}),
        lambda c: c["cas"][0]["attendu"].update({"code": "REJ-MCP-OUTIL-INCONNU"}),  # un témoin n'a pas de code
        lambda c: c["cas"][3]["attendu"].pop("code"),
        lambda c: c["cas"][3].update({"approbation": {"niveau": "N3", "superuser": True}}),
        lambda c: c["cas"][3].update({"table_alteree": {"surface": "web", "liste": []}}),
    ]
    for modif in cas_invalides:
        with pytest.raises(RefusEvaluation) as exc:
            sm.valider_corpus_mcp(avec(modif))
        assert exc.value.code.startswith("REJ-EVAL-CORPUS-")


def test_un_outil_inconnu_du_catalogue_est_un_refus_du_corpus(corpus, definitions):
    mauvais = copy.deepcopy(corpus)
    mauvais["cas"][0]["outil"] = "m1_outil_fantome"
    with pytest.raises(RefusEvaluation) as exc:
        sm.evaluer(mauvais, definitions)
    assert exc.value.code == "REJ-EVAL-CORPUS-OUTIL"


def test_chargement_d_un_fichier_absent_ou_illisible(tmp_path):
    with pytest.raises(RefusEvaluation) as exc:
        sm.charger_corpus_mcp(tmp_path / "absent.yaml")
    assert exc.value.code == "REJ-EVAL-CORPUS-ABSENT"
    (tmp_path / "x.yaml").write_text("a: [")
    with pytest.raises(RefusEvaluation) as exc:
        sm.charger_corpus_mcp(tmp_path / "x.yaml")
    assert exc.value.code == "REJ-EVAL-CORPUS-FORME"


def test_la_table_originale_est_restauree_apres_un_cas_a_table_alteree(corpus, definitions):
    from opsys.registre_mcp import rule_of_two

    avant = dict(rule_of_two.SANS_APPROBATION)
    sm.evaluer(corpus, definitions)
    assert dict(rule_of_two.SANS_APPROBATION) == avant


def test_les_corpus_des_departements_et_leur_empreinte_ne_changent_pas():
    """Le corpus transverse est un fichier à part : les dix corpus par département restent ceux d'avant."""
    departements = charger_departements(RACINE / "departments")
    fichiers = sorted((RACINE / "departments").glob(f"m*/{corpus_dept.FICHIER_CORPUS}"))
    assert len(fichiers) == 10 and sm.FICHIER_CORPUS_MCP not in fichiers
    for f in fichiers:
        corpus_dept.charger_corpus(f)
    assert len(departements) == 10
    assert yaml.safe_load(sm.FICHIER_CORPUS_MCP.read_text(encoding="utf-8"))["schema"] == sm.SCHEMA_CORPUS_MCP


# -- CLI `evaluer securite-mcp` ----------------------------------------------------------------------------------------
def _cli(argv):
    parseur = argparse.ArgumentParser()
    ajouter_commandes(parseur.add_subparsers(dest="commande", required=True))
    return executer(parseur.parse_args(argv))


def test_cli_securite_mcp_ecrit_json_et_markdown_sans_jamais_ecraser(tmp_path, capsys):
    assert _cli(["evaluer", "securite-mcp", "--sortie", str(tmp_path)]) == 0
    sortie = capsys.readouterr().out.splitlines()
    fichiers = [Path(ligne) for ligne in sortie if ligne.endswith((".json", ".md"))]
    assert len(fichiers) == 2 and all(f.exists() for f in fichiers)
    rapport = json.loads(fichiers[0].read_text())
    assert rapport["qualifie"] is True and rapport["schema"] == "opsys.evaluation.securite-mcp.rapport/v1"
    assert _cli(["evaluer", "securite-mcp", "--sortie", str(tmp_path)]) == 2  # REJ-EVAL-SORTIE-EXISTANTE
    assert fichiers[0].read_text() == json.dumps(rapport, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def test_cli_securite_mcp_sort_en_1_quand_un_cas_bloquant_echoue(tmp_path, capsys):
    corpus = sm.charger_corpus_mcp()
    corpus["cas"][0]["outil"] = "m1_emettre_notification"  # témoin « autoriser » sur un N4 intact
    corpus["cas"][3]["attendu"] = {"decision": "autoriser"}  # une dérive attendue comme autorisée : doit échouer
    fichier = tmp_path / "c.yaml"
    fichier.write_text(yaml.safe_dump(corpus, allow_unicode=True), encoding="utf-8")
    assert _cli(["evaluer", "securite-mcp", "--corpus", str(fichier)]) == 1
    assert "NON QUALIFIÉ" in capsys.readouterr().out
