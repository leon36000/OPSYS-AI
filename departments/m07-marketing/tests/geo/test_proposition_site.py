"""Propositions de changement de site : liste blanche, original intact, contrôles existants, diff exact."""

from __future__ import annotations

import copy
import json
import os

import pytest
from m7_marketing import journal_chaine
from m7_marketing.geo import proposition_site as ps
from m7_marketing.site import service as site_service

REVISION = "2026-11-02"
HORO = "2026-11-02T12:00:00Z"


@pytest.fixture(scope="module")
def demo():
    schema, actifs, refus = site_service.resoudre_schema(None, "revetements-horizon-fictif")
    assert refus is None
    return schema, actifs


def titre(page_id="services", fr="Services de revêtement et de gouttières à Laval", en="Siding and gutter services "
                                                                                       "in Laval"):
    return {"op": "remplacer_texte", "cible": "page.titre", "id": page_id, "valeur": {"fr-CA": fr, "en-CA": en}}


def proposer(demo, ops, **kw):
    schema, actifs = demo
    journal = kw.pop("journal", [])
    kw.setdefault("controle_marques", None)
    return ps.proposer(schema, actifs, ops, REVISION, journal, par="agent", horodatage=HORO, **kw), journal


def codes(r):
    return [x["code"] for x in r["refus"]]


def test_proposition_acceptee_diff_exact_original_intact_et_revision_avancee(demo):
    schema, _ = demo
    avant = copy.deepcopy(schema)
    r, journal = proposer(demo, [titre()], recommandation_id="GEO-02:abc")
    assert r["accepte"] and r["etat"] == "BROUILLON" and r["qa_conforme"] is True and r["deja_propose"] is False
    assert schema == avant  # l'original n'est jamais muté
    indice = next(i for i, p in enumerate(schema["pages"]) if p["id"] == "services")
    assert r["diff"] == [
        {"chemin": f"$.pages[{indice}].titre.fr-CA", "avant": avant["pages"][indice]["titre"]["fr-CA"],
         "apres": "Services de revêtement et de gouttières à Laval"},
        {"chemin": f"$.pages[{indice}].titre.en-CA", "avant": avant["pages"][indice]["titre"]["en-CA"],
         "apres": "Siding and gutter services in Laval"}]
    propose = r["schema_propose"]
    assert propose["revision"]["date"] == REVISION and avant["revision"]["date"] < REVISION
    assert propose["pages"][indice]["titre"]["fr-CA"].startswith("Services de revêtement")
    autres = copy.deepcopy(propose)
    autres["pages"][indice]["titre"] = avant["pages"][indice]["titre"]
    autres["revision"] = avant["revision"]
    assert autres == avant  # rien d'autre n'a changé
    assert r["empreinte_base"] == ps.empreinte_schema(schema)
    assert r["empreinte_resultat"] == ps.empreinte_schema(propose)
    assert "m7_preparer_paquet_site" in r["suite"] and "m7_demander_publication_site" in r["suite"]
    assert "N3" in r["suite"]
    assert r["recommandation_id"] == "GEO-02:abc"
    assert journal_chaine.integre(journal) and journal[0]["type"] == ps.M_CREEE and journal[0]["par"] == "agent"


def test_rejouer_la_meme_proposition_est_idempotent_et_retiree_elle_est_refusee(demo):
    journal: list = []
    a, _ = proposer(demo, [titre()], journal=journal)
    b, _ = proposer(demo, [titre()], journal=journal)
    assert b["proposition_id"] == a["proposition_id"] and b["deja_propose"] is True and len(journal) == 1
    autre, _ = proposer(demo, [titre(fr="Services de gouttières et de revêtement à Laval")], journal=journal)
    assert autre["proposition_id"] != a["proposition_id"] and len(journal) == 2
    assert ps.retirer(journal, a["proposition_id"], "agent", "remplacée", HORO)["deja_retiree"] is False
    assert ps.retirer(journal, a["proposition_id"], "agent", "encore", HORO)["deja_retiree"] is True
    refus, _ = proposer(demo, [titre()], journal=journal)
    assert not refus["accepte"] and codes(refus) == ["REJ-GEO-PROPOSITION-ETAT"]
    assert ps.etats(journal)[a["proposition_id"]]["etat"] == "RETIREE"
    assert ps.retirer(journal, "prop-inconnue", "agent", "x",
        HORO)["refus"][0]["code"] == "REJ-GEO-PROPOSITION-INCONNUE"


@pytest.mark.parametrize("cible", ["entreprise.nom", "entreprise.nap", "charte.fond", "temoignage.texte",
    "legal.responsable_rp",
                                   "page.sections", "service.image", "domaine", "page.slug", "page.titre_nav",
                                       "faq.reponse"])
def test_un_chemin_hors_liste_blanche_est_refuse(demo, cible):
    op = {"op": "remplacer_texte", "cible": cible, "id": "services", "valeur": {"fr-CA": "x" * 60, "en-CA": "y" * 60}}
    r, journal = proposer(demo, [op])
    assert not r["accepte"] and codes(r) == ["REJ-GEO-PROPOSITION-OPERATION"] and journal == []


@pytest.mark.parametrize("op", [
    {"op": "supprimer", "cible": "page.titre", "id": "services"},
    {"op": "remplacer_texte"}, "texte", None,
    {"op": "remplacer_texte", "cible": "page.titre", "id": "services", "valeur": {"fr-CA": "seul le français"}},
    {"op": "remplacer_texte", "cible": "page.titre", "id": "services",
     "valeur": {"fr-CA": "a", "en-CA": "b", "es-CA": "c"}},
    {"op": "remplacer_texte", "cible": "page.titre", "id": "services", "valeur": {"fr-CA": "", "en-CA": "b"}},
    {"op": "remplacer_texte", "cible": "page.titre", "id": "services", "valeur": {"fr-CA": "x" * 2001, "en-CA": "b"}},
    {"op": "remplacer_texte", "cible": "page.titre", "id": "services", "valeur": {"fr-CA": 5, "en-CA": "b"}},
    {"op": "remplacer_texte", "cible": "service.description", "id": "gouttieres",
     "valeur": {"fr-CA": "un texte au lieu d'une liste", "en-CA": ["ok"]}},
    {"op": "ajouter_faq", "id": "faq-x", "valeur": {"question": {"fr-CA": "q", "en-CA": "q"}}},
    {"op": "remplacer_texte", "cible": "page.titre", "id": "services", "valeur": {"fr-CA": "a", "en-CA": "b"},
        "extra": 1},
])
def test_operations_mal_formees_refusees_sans_rien_ecrire(demo, op):
    r, journal = proposer(demo, [op])
    assert not r["accepte"] and codes(r)[0].startswith("REJ-GEO-PROPOSITION") and journal == []


def test_cible_inconnue_et_faq_en_double_refusees(demo):
    r, _ = proposer(demo, [titre("page-inexistante")])
    assert codes(r) == ["REJ-GEO-PROPOSITION-CIBLE"]
    schema, _ = demo
    existante = schema["faq"][0]["id"]
    op = {"op": "ajouter_faq", "id": existante, "valeur": {"question": {"fr-CA": "Question ?", "en-CA": "Question?"},
                                                           "reponse": {"fr-CA": "Réponse.", "en-CA": "Answer."}}}
    r, _ = proposer(demo, [op])
    assert codes(r) == ["REJ-GEO-PROPOSITION-CIBLE"]


def test_bornes_du_nombre_d_operations(demo):
    for ops in ([], [titre()] * (ps.OPERATIONS_MAX + 1), "pas une liste", None):
        r, _ = proposer(demo, ops)
        assert codes(r) == ["REJ-GEO-PROPOSITION-OPERATION"]
    r, _ = proposer(demo, [titre()] * ps.OPERATIONS_MAX)  # 20 opérations identiques : permises (la dernière gagne)
    assert r["accepte"]
    gros = titre(fr="é" * 1900)
    r, _ = proposer(demo, [gros] * 20)
    assert codes(r) == ["REJ-GEO-PROPOSITION-OPERATION"]  # plus de 60 000 octets


def test_la_garde_de_contenu_refuse_un_prix_une_promesse_chiffree_et_une_exageration(demo):
    for texte in ("Gouttières installées pour 4999 $ garanties", "Le meilleur service du Québec garanti",
                  "Installation en 48 heures garantie"):
        r, journal = proposer(demo, [titre(fr=texte, en="Gutters installed")])
        assert not r["accepte"] and any(c.startswith("REJ-SITE-") for c in codes(r)) and journal == []


def test_une_description_trop_courte_est_refusee_par_le_validateur_de_structure(demo):
    op = {"op": "remplacer_texte", "cible": "page.description", "id": "services",
          "valeur": {"fr-CA": "Trop court.", "en-CA": "Too short."}}
    r, _ = proposer(demo, [op])
    assert not r["accepte"] and all(c.startswith("REJ-SITE-SCHEMA") for c in codes(r))


def test_schema_de_base_invalide_refuse_avant_tout(demo):
    schema, actifs = demo
    casse = copy.deepcopy(schema)
    casse["schema"] = "autre/v9"
    r = ps.proposer(casse, actifs, [titre()], REVISION, [], par="a", horodatage=HORO)
    assert not r["accepte"] and codes(r) == ["REJ-SITE-SCHEMA-VERSION"]


def test_revision_anterieure_ou_illisible_refusee(demo):
    schema, actifs = demo
    for date_revision in ("2026-10-30", "pas-une-date", None, 5):
        r = ps.proposer(schema, actifs, [titre()], date_revision, [], par="a", horodatage=HORO)
        assert codes(r) == ["REJ-GEO-PROPOSITION-REVISION"]
    assert ps.proposer(schema, actifs, [titre()], schema["revision"]["date"], [], par="a", horodatage=HORO)["accepte"]


def test_service_description_en_paragraphes_et_ajout_de_faq(demo):
    ops = [
        {"op": "remplacer_texte", "cible": "service.resume", "id": "gouttieres",
         "valeur": {"fr-CA": "Installation de gouttières sans joint et nettoyage à Laval.",
                    "en-CA": "Seamless gutter installation and cleaning in Laval."}},
        {"op": "remplacer_texte", "cible": "service.description", "id": "gouttieres",
         "valeur": {"fr-CA": ["Nous posons des gouttières sans joint.", "Nous nettoyons aussi les descentes."],
                    "en-CA": ["We install seamless gutters.", "We also clean the downspouts."]}},
        {"op": "ajouter_faq", "id": "faq-nettoyage",
         "valeur": {"question": {"fr-CA": "Nettoyez-vous les gouttières ?", "en-CA": "Do you clean gutters?"},
                    "reponse": {"fr-CA": "Oui, sur demande, selon la saison.", "en-CA": "Yes, on request, depending "
                                                                                        "on the season."}}},
    ]
    r, _ = proposer(demo, ops)
    assert r["accepte"], r
    assert r["diff"][-1]["chemin"].startswith("$.faq[") and r["diff"][-1]["avant"] is None
    assert r["diff"][-1]["apres"]["id"] == "faq-nettoyage"
    assert len(r["schema_propose"]["faq"]) == len(demo[0]["faq"]) + 1
    assert len(demo[0]["faq"]) == 3  # l'original garde ses trois entrées


def test_controle_de_marques_refus_mentions_et_avertissement_quand_il_manque(demo):
    r, _ = proposer(demo, [titre()])
    assert r["avertissements"] == ["controle_marques_non_applique"]

    appels = []

    def refuse(texte):
        appels.append(texte)
        return {"accepte": False, "refus": [{"code": "REJ-VEILLE-MARQUE-CONCURRENT", "chemin": "$.texte",
            "detail": "x"}],
                "mentions": []}

    r, journal = proposer(demo, [titre()], controle_marques=refuse)
    assert not r["accepte"] and codes(r) == ["REJ-VEILLE-MARQUE-CONCURRENT"] * len(appels) and journal == []
    assert sorted(appels) == sorted(set(appels)) and len(appels) == 2  # chaque texte proposé est contrôlé une fois

    def comparatif(texte):
        return {"accepte": True, "refus": [], "mentions": ["Publicité comparative : À valider auprès d'un "
                                                           "professionnel qualifié (avocat)."]}

    r, _ = proposer(demo, [titre()], controle_marques=comparatif)
    assert r["accepte"] and r["avertissements"] == ["Publicité comparative : À valider auprès d'un professionnel "
                                                    "qualifié (avocat)."]


def test_aucun_fichier_n_est_ecrit_par_une_proposition(demo, tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    avant = sorted(str(p) for p in tmp_path.rglob("*"))
    r, _ = proposer(demo, [titre()])
    assert r["accepte"] and sorted(str(p) for p in tmp_path.rglob("*")) == avant
    assert not os.path.exists(tmp_path / "home")


def test_lecture_liste_detail_et_integrite(demo):
    journal: list = []
    a, _ = proposer(demo, [titre()], journal=journal)
    b, _ = proposer(demo, [titre(fr="Services de gouttières et de revêtement à Laval")], journal=journal)
    ps.retirer(journal, b["proposition_id"], "agent", "non", HORO)
    liste = ps.lire(journal)
    assert liste["total"] == 2 and liste["integrite"]["journal_intact"]
    assert liste["propositions"][0]["etat"] == "BROUILLON"
    assert ps.lire(journal, etat="RETIREE")["total"] == 1
    detail = ps.lire(journal, a["proposition_id"])["proposition"]
    assert detail["operations"] == [titre()] and detail["empreinte_base"] == a["empreinte_base"]
    assert ps.lire(journal, "prop-x")["refus"][0]["code"] == "REJ-GEO-PROPOSITION-INCONNUE"
    journal[0] = {**journal[0], "site_id": "falsifie"}  # altération du journal
    assert ps.lire(journal)["refus"][0]["code"] == "REJ-GEO-PROPOSITION-JOURNAL"
    r, _ = proposer(demo, [titre()], journal=journal)
    assert codes(r) == ["REJ-GEO-PROPOSITION-JOURNAL"]


def test_les_operations_conservees_ne_contiennent_pas_de_schema_complet(demo):
    journal: list = []
    proposer(demo, [titre()], journal=journal)
    assert len(json.dumps(journal)) < 3000  # ops + empreintes, jamais le schéma entier
