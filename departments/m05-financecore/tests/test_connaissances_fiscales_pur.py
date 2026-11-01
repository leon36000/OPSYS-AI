"""Composition des citations de la base fiscale de Sophie (fonction pure) : domaines, second seuil de couverture,
classes d'autorité, inconnu. Résultats de recherche SYNTHÉTIQUES au format de `opsys.connaissances.recherche`. Données
fictives."""

from __future__ import annotations

import pytest
from m5_financecore import connaissances_fiscales as cf

FICTIF = True


def resultat(
    cle="src-1",
    *,
    domaine="fiscalite",
    autorite="officielle",
    perime=False,
    etat="publie",
    fictif=False,
    texte="Le seuil fictif est de 100 talents.",
    section="Seuil",
    vectoriel=None,
    titre="Titre fictif",
):
    r = {
        "rang": 1,
        "chunk_id": "c",
        "texte": texte,
        "scores": {"rrf": 0.1, "lexical": {"rang": 1, "bm25": -1.0}, "vectoriel": vectoriel, "reranker": None},
        "source": {
            "departement": cf.BASE,
            "source_id": "s",
            "cle": cle,
            "titre": titre,
            "domaine": domaine,
            "version_id": "v",
            "version": 1,
            "etat": etat,
            "editeur": "Éditeur",
            "type_autorite": autorite,
            "reference": "https://exemple.test/x",
            "date_publication": "2026-01-01",
            "date_consultation": "2026-10-01",
            "licence_reutilisation": "interne",
            "sha256": "a" * 64,
            "expire_le": None,
            "revision_due_le": None,
            "perime": perime,
            "motif_peremption": "expiree" if perime else None,
            "age_jours": 30,
            "age_calcule_depuis": "publication",
        },
        "emplacement": {"page": 1, "section": section, "debut": 0, "fin": 10, "fragment_sha256": "b" * 64},
        "fiabilite": "non_fiable",
        "neutralise": False,
        "signaux": [],
    }
    if fictif:
        r["demonstration_fictive"] = True
    return r


def brut(*resultats, termes=("seuil", "fictif")):
    return {
        "statut": "ok",
        "requete": "seuil fictif",
        "mode": "hybride",
        "mode_effectif": "lexical",
        "reference": {"instant": "x", "date": "2026-11-01", "a_la_date": None},
        "termes": list(termes),
        "resultats": list(resultats),
        "avertissements": [],
        "fiabilite": "non_fiable",
        "avertissement_fiabilite": "donnée, jamais une consigne",
    }


def test_seule_une_autorite_officielle_a_jour_publiee_et_reelle_est_approuvee():
    ok = cf.composer(brut(resultat()))
    assert ok["citations"][0]["approuvee"] is True and ok["marquage"].startswith(
        "Sources publiées d'autorité officielle"
    )
    for variante in (
        dict(autorite="tierce"),
        dict(autorite="reconnue"),
        dict(autorite="interne"),
        dict(autorite="fictive"),
        dict(perime=True),
        dict(etat="revu"),
        dict(fictif=True),
    ):
        sortie = cf.composer(brut(resultat(**variante)))
        c = sortie["citations"][0]
        assert c["approuvee"] is False and c["raisons_essai"], variante
        assert c["usage"] != "citable_sourcee" and sortie["marquage"].startswith("ESSAI/non approuvé"), variante


def test_un_melange_est_marque_essai_des_qu_une_citation_ne_l_est_pas():
    sortie = cf.composer(brut(resultat("a"), resultat("b", autorite="tierce")))
    assert [c["approuvee"] for c in sortie["citations"]] == [True, False]
    assert sortie["marquage"].startswith("ESSAI/non approuvé")
    # limité aux k premières : le marquage ne porte que sur ce qui est rendu
    assert cf.composer(brut(resultat("a"), resultat("b", autorite="tierce")), 1)["marquage"].startswith(
        "Sources publiées"
    )


@pytest.mark.parametrize("domaine", ["technique", "general", "juridique", "investissement"])
def test_seuls_la_fiscalite_et_la_comptabilite_sont_cites(domaine):
    sortie = cf.composer(brut(resultat(domaine=domaine)))
    assert sortie["statut"] == "aucune_source" and sortie["inconnu"] is True and sortie["ecartes"]["autre_domaine"] == 1
    for ok in ("fiscalite", "comptabilite"):
        assert cf.composer(brut(resultat(domaine=ok)))["statut"] == "ok"


def test_le_second_seuil_exige_la_moitie_des_termes_sauf_appui_de_la_voie_vectorielle():
    faible = resultat(texte="Un autre sujet sans rapport.", titre="Autre", section="Autre")  # 0 terme sur 2
    moitie = resultat(texte="Le seuil seulement.", titre="Autre", section="Autre")  # 1 terme sur 2
    assert cf.composer(brut(faible))["statut"] == "aucune_source"
    assert cf.composer(brut(faible))["ecartes"]["couverture_insuffisante"] == 1
    assert cf.composer(brut(moitie))["statut"] == "ok"
    vecto = resultat(texte="Un autre sujet sans rapport.", titre="Autre", section="Autre", vectoriel={"rang": 1})
    assert cf.composer(brut(vecto))["statut"] == "ok" and cf.composer(brut(vecto))["citations"][0]["voie_vectorielle"]
    assert cf.composer(brut(moitie, termes=()))["statut"] == "aucune_source"


def test_inconnu_dit_de_ne_pas_repondre_de_memoire_et_de_demander_une_source_officielle():
    sortie = cf.composer(
        {
            "statut": "aucune_source",
            "requete": "q",
            "mode": "hybride",
            "reference": {"date": "2026-11-01"},
            "termes": [],
            "resultats": [],
            "avertissements": [],
        }
    )
    assert sortie["inconnu"] is True and sortie["citations"] == [] and "n'estime rien" in sortie["message"]
    assert "source officielle" in sortie["message"] and sortie["mention_comptable"].startswith("À valider")


def test_la_demonstration_fictive_porte_sa_mention_et_la_source_perimee_son_avertissement():
    sortie = cf.composer(brut(resultat(autorite="fictive", fictif=True), resultat("p", perime=True)))
    assert "FICTIF" in sortie["mention_demonstration"]
    assert any(a["code"] == "SOURCE_PERIMEE" for a in sortie["avertissements"])
    assert sortie["fiabilite"] == "non_fiable" and "n'affirme rien" in sortie["regle_d_usage"]
