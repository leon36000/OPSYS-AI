"""Oracles fictifs indépendants, sans expected reconstruit par le diagnostic."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json

import pytest

FICTIF = True
JOUR = "2026-09-29"
INSTANT = "2026-09-29T18:00:00+00:00"
VERSION = "1" * 64


def _domaine():
    assert importlib.util.find_spec("m8_analytics.provenance_m5") is not None, "domaine de provenance absent"
    return importlib.import_module("m8_analytics.provenance_m5")


def charge_cash(sequence=1, ident="cash-fictif-1"):
    # Forme issue de test_evenements_cash_libre.py, pas une nouvelle capture producteur.
    def composante(cid):
        return {
            "id": cid,
            "libelle": cid,
            "statut": "CALCULE",
            "montant_cad": "0.00",
            "plancher_cad": None,
            "source": {"origine": "REGISTRE", "registres": []},
            "fraicheur": {"derniere_piece": JOUR, "pieces": 1},
        }

    return {
        "evenement_id": ident,
        "sequence": sequence,
        "date_reference": JOUR,
        "version_donnees": VERSION,
        "devise": "CAD",
        "statut": "CALCULE",
        "cash_libre_cad": "0.00",
        "au_plus_cad": None,
        "en_deficit": False,
        "lecture": "Constat fictif",
        "solde": composante("solde"),
        "composantes": [
            composante(cid) for cid in ("taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves")
        ],
        "manque": [],
        "reserves": [],
        "hypotheses": [],
        "mention": "Préparatoire fictif",
    }


def charge_rent(sequence=1, devis="devis-fictif-a", ident="rent-fictif-1"):
    return {
        "evenement_id": ident,
        "devis_id": devis,
        "chantier_id": "chantier-fictif",
        "wct_id": "wct-fictif",
        "sequence": sequence,
        "version_entrees": VERSION,
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "verdict": "PARTIELLE",
        "devise": "CAD",
        "prix_definitif": False,
        "cout_reel_complet": False,
        "cout_reel_cad": None,
        "cout_connu_cad": "0.00",
        "marge_reelle_cad": None,
        "marge_prevue_cad": None,
        "ecart_marge_cad": None,
        "manque": ["REJ-FICTIF"],
    }


def publication(charge, rent=False):
    return {
        "evenement_id": charge["evenement_id"],
        "type_evenement": "m5.rentabilite_chantier" if rent else "m5.cash_libre_constate",
        "producteur": "m05-financecore",
        "charge": copy.deepcopy(charge),
        "cree_le": INSTANT,
    }


def recu(charge, rent=False, **kw):
    resume = {"enregistre": True, "deja_enregistre": False, "sequence": charge["sequence"]}
    if rent:
        resume.update(wct_id=charge["wct_id"], verdict=charge["verdict"], mesures={"CANARY_FICTIF": 1})
    else:
        resume.update(evenement_id=charge["evenement_id"], date_reference=JOUR, statut="CALCULE")
    r = {
        "evenement_id": charge["evenement_id"],
        "consommateur": "m08-analytics",
        "statut": "traite",
        "tentatives": 1,
        "prochaine_tentative": None,
        "resultat": resume,
    }
    r.update(kw)
    return r


def maillon(charge, rent=False, rang=42):
    if rent:
        fait = {
            "type_entree": "rentabilite",
            "wct_id": "wct-fictif",
            "devis_id": charge["devis_id"],
            "sequence": charge["sequence"],
            "verdict": "PARTIELLE",
            "prix_definitif": False,
            "cout_reel_complet": False,
            "version_entrees": VERSION,
            "marge_reelle_cad": None,
            "manque": ["REJ-FICTIF"],
        }
    else:
        fait = {"type_entree": "cash_libre_constate", **copy.deepcopy(charge)}
    return {"rang": rang, "cree_le": "2026-09-29T18:05:00", "fuseau": "non_persiste", "maillon": fait}


def produire(publications=(), recus=(), maillons=(), *, rent=False, budget=5400, **args):
    arguments = {
        "perimetre": "rentabilite_wct" if rent else "cash_global",
        "wct_id": "wct-fictif" if rent else None,
        "decalage": 0,
        "limite": 1,
    }
    arguments.update(args)
    registre = "faits_chantier" if rent else "faits_cash_libre"
    sources = [
        {
            "table": "evenements_sortants",
            "departement": None,
            "registre": None,
            "lignes": len(publications),
            "empreinte_snapshot_calculee": "1" * 64,
        },
        {
            "table": "evenements_recus",
            "departement": None,
            "registre": None,
            "lignes": len(recus),
            "empreinte_snapshot_calculee": "2" * 64,
        },
        {
            "table": "registres_maillons",
            "departement": "m08-analytics",
            "registre": registre,
            "lignes": len(maillons),
            "empreinte_snapshot_calculee": "3" * 64,
        },
    ]
    return _domaine().produire(publications, recus, maillons, sources, arguments, budget_sortie=budget)


def test_vide_reste_corpus_inconnu_pas_finance_zero():
    v = produire()
    assert v["selection"] == {"publication_courante_id": None, "fact_courant_reference": None, "ambiguite": False}
    assert v["publications"] == [] and v["affichage"]["total_publications"] == 0
    assert v["couverture"]["completude_financiere_entreprise"] is False


def test_cash_lie_exactement_id_recu_projection_et_rang_sql():
    c = charge_cash()
    v = produire([publication(c)], [recu(c)], [maillon(c)])
    row = v["publications"][0]
    assert row["rapprochement"]["etat"] == "RECEPTION_LIEE_ID_EXACT"
    assert row["fait"]["reference"]["rang"] == 42
    assert row["fait"]["enregistrement_SQL"] == {"valeur": "2026-09-29T18:05:00", "fuseau": "non_persiste"}
    assert row["recu_bus"]["resume"] == {
        "enregistre": True,
        "deja_enregistre": False,
        "evenement_id": "cash-fictif-1",
        "wct_id": None,
        "sequence": 1,
        "date_reference": JOUR,
        "statut": "CALCULE",
        "verdict": None,
    }
    assert row["recu_bus"]["horodatage_reception"] is None
    assert "montant_cad" not in json.dumps(v)


@pytest.mark.parametrize("statut", ["ABSENT", "echec", "quarantaine"])
def test_echo_cash_sans_recu_traite_ne_certifie_pas_reception(statut):
    c = charge_cash()
    rs = [] if statut == "ABSENT" else [recu(c, statut=statut, resultat={"CANARY_FICTIF": "privé"})]
    row = produire([publication(c)], rs, [maillon(c)])["publications"][0]
    assert row["rapprochement"]["etat"] == "LIEN_INCONNU"
    assert row["recu_bus"]["resume_coherent"] is None
    assert set(row["recu_bus"]["resume"].values()) == {None}
    assert "CANARY_FICTIF" not in json.dumps(row)


def test_publication_cash_id_override_refuse_meme_si_fait_existe():
    c = charge_cash()
    p = publication(c)
    p["evenement_id"] = "autre-ID-fictif"
    with pytest.raises(_domaine().Refus) as e:
        produire([p], [recu(c)], [maillon(c)])
    assert e.value.verdict["code"] == "REJ-M8-PROVENANCE-SOURCE-INVALIDE"


def test_deux_faits_cash_sont_ambigus_et_pas_dernier_arbitraire():
    c = charge_cash()
    row = produire([publication(c)], [recu(c)], [maillon(c, rang=7), maillon(c, rang=42)])["publications"][0]
    assert row["fait"] is None
    assert row["rapprochement"]["etat"] == "LIEN_AMBIGU"


def test_recu_traite_sans_fait_dit_le_manque():
    c = charge_cash()
    row = produire([publication(c)], [recu(c)])["publications"][0]
    assert row["rapprochement"]["etat"] == "FAIT_ABSENT"
    assert "RECU_TRAITE_SANS_FAIT" in row["rapprochement"]["codes"]


def test_resume_incomplet_ou_contradictoire_ne_donne_pas_lien_cash():
    c = charge_cash()
    for result, want, code in [
        ({"enregistre": True}, None, "RESUME_HISTORIQUE_INCOMPLET"),
        ({**recu(c)["resultat"], "evenement_id": "fictif-different"}, False, "RESUME_DIFFERENT"),
    ]:
        row = produire([publication(c)], [recu(c, resultat=result)], [maillon(c)])["publications"][0]
        assert row["recu_bus"]["resume_coherent"] is want
        assert row["rapprochement"]["etat"] == "LIEN_INCONNU" and code in row["rapprochement"]["codes"]


def test_rentabilite_correspondance_n_est_jamais_identite_du_bus():
    c = charge_rent()
    row = produire([publication(c, True)], [recu(c, True)], [maillon(c, True)], rent=True)["publications"][0]
    assert row["rapprochement"]["etat"] == "CORRESPONDANCE_DE_PROJECTION"
    assert row["fait"]["evenement_id_persiste"] is None
    assert "CANARY_FICTIF" not in json.dumps(row)


def test_rentabilite_plusieurs_devis_n_a_pas_tete_globale():
    a = charge_rent(8, "devis-fictif-a", "id-a")
    b = charge_rent(1, "devis-fictif-b", "id-b")
    v = produire([publication(a, True), publication(b, True)], rent=True, limite=8)
    assert v["selection"] == {"publication_courante_id": None, "fact_courant_reference": None, "ambiguite": True}
    assert all(r["publication"]["courante_pour_devis"] is True for r in v["publications"])


def test_collisions_cle_receiver_restent_ambigues_meme_projection_identique():
    c = charge_rent()
    d = {**c, "evenement_id": "autre-publication-fictive"}
    v = produire(
        [publication(c, True), publication(d, True)],
        [recu(c, True), recu(d, True)],
        [maillon(c, True)],
        rent=True,
        limite=8,
    )
    assert v["selection"]["ambiguite"] is True
    assert all(r["rapprochement"]["etat"] == "LIEN_AMBIGU" for r in v["publications"])


def test_fait_historique_sans_sequence_version_reste_inconnu():
    c = charge_rent()
    m = maillon(c, True)
    for k in ("sequence", "version_entrees", "prix_definitif", "cout_reel_complet"):
        m["maillon"].pop(k)
    row = produire([publication(c, True)], [recu(c, True)], [m], rent=True)["publications"][0]
    assert row["rapprochement"]["etat"] == "LIEN_INCONNU"
    assert row["fait"]["sequence"] is None and row["fait"]["version"] is None
    assert "SEQUENCE_HISTORIQUE_ABSENTE" in row["rapprochement"]["codes"]


@pytest.mark.parametrize(
    "mutation",
    [
        {"decalage": True},
        {"limite": False},
        {"limite": 9},
        {"decalage": -1},
        {"wct_id": "cash-ne-doit-pas-avoir-wct"},
        {"role": "admin"},
    ],
)
def test_corps_ferme_et_entiers_stricts(mutation):
    with pytest.raises(_domaine().Refus) as e:
        produire(**mutation)
    assert e.value.verdict["code"] == "REJ-M8-PROVENANCE-ARGUMENTS-INVALIDES"


def test_budget_entier_refuse_premiere_ligne_plutot_que_coupe():
    c = charge_cash()
    with pytest.raises(_domaine().Refus) as e:
        produire([publication(c)], budget=550)
    assert e.value.verdict["code"] == "REJ-M8-PROVENANCE-SORTIE-TROP-VOLUMINEUSE"


def test_page_courante_reste_et_offset_hors_total_sans_clamp():
    cs = [charge_cash(i, f"cash-{i}") for i in range(1, 4)]
    v = produire([publication(c) for c in cs], limite=1)
    assert v["publications"][0]["publication"]["sequence"] == 3
    assert v["affichage"] == {
        "decalage": 0,
        "limite": 1,
        "total_publications": 3,
        "affiches": 1,
        "reste": 2,
        "prochain_decalage": 1,
    }
    assert produire([publication(c) for c in cs], decalage=10000)["publications"] == []


@pytest.mark.parametrize("lieu,valeur", [("publication", []), ("resume", {}), ("recu", []), ("fuseau", [])])
def test_json_valide_type_inattendu_refuse_sans_exception_brute(lieu, valeur):
    c = charge_cash()
    p, r, m = publication(c), recu(c), maillon(c)
    if lieu == "publication":
        p["charge"]["statut"] = valeur
    elif lieu == "resume":
        r["resultat"]["statut"] = valeur
    elif lieu == "recu":
        r["statut"] = valeur
    else:
        m["fuseau"] = valeur
    with pytest.raises(_domaine().Refus):
        produire([p], [r], [m])


@pytest.mark.parametrize("alteration", ["id", "producteur", "sequence_bool", "date_naive", "version"])
def test_enveloppe_source_corrompue_ne_devient_pas_un_lien(alteration):
    c = charge_cash()
    p = publication(c)
    if alteration == "id":
        p["evenement_id"] = "autre-fictif"
    elif alteration == "producteur":
        p["producteur"] = "m08-analytics"
    elif alteration == "sequence_bool":
        p["charge"]["sequence"] = True
    elif alteration == "date_naive":
        p["cree_le"] = "2026-09-29T18:00:00"
    else:
        p["charge"]["version_donnees"] = "inconnue"
    with pytest.raises(_domaine().Refus, match="SOURCE-INVALIDE"):
        produire([p])


def test_fact_cash_montant_modifie_est_divergent_pas_reception_exacte():
    c = charge_cash()
    m = maillon(c)
    m["maillon"]["cash_libre_cad"] = "123.45"
    row = produire([publication(c)], [recu(c)], [m])["publications"][0]
    assert row["rapprochement"]["etat"] == "FAITS_DIVERGENTS"
    assert "123.45" not in json.dumps(row)


def test_lecture_ne_modifie_aucun_objet_source_ni_zero_false():
    c = charge_cash()
    p, r, m = [publication(c)], [recu(c)], [maillon(c)]
    avant = copy.deepcopy((p, r, m))
    dto = produire(p, r, m)
    dto["sources"][0]["lignes"] = 999
    assert (p, r, m) == avant
    assert dto["publications"][0]["recu_bus"]["resume"]["deja_enregistre"] is False


def test_plafond_sources_compte_avant_validation_et_page():
    with pytest.raises(_domaine().Refus, match="BUDGET-SOURCE-DEPASSE"):
        produire([None] * 10001, decalage=10000)


def test_orphelin_et_tri_sequence_non_rang_sans_reception_inventee():
    c1, c2, orphelin = charge_cash(1, "cash-a"), charge_cash(2, "cash-b"), charge_cash(3, "cash-c")
    dto = produire([publication(c1), publication(c2)], (), [maillon(c1, rang=8), maillon(orphelin, rang=2)])
    assert dto["publications"][0]["publication"]["reference"]["evenement_id"] == "cash-b"
    assert dto["couverture"]["orphelins_faits"] == 1
    assert dto["selection"]["publication_courante_id"] == "cash-b"
    assert dto["selection"]["fact_courant_reference"] is None


def test_fait_fort_sequence3_reste_lie_en_presence_du_legacy_sans_sequence():
    c = charge_rent(sequence=3)
    fort, faible = maillon(c, True, rang=42), maillon(c, True, rang=7)
    for k in ("devis_id", "sequence", "version_entrees", "prix_definitif", "cout_reel_complet"):
        faible["maillon"].pop(k)
    v = produire([publication(c, True)], [recu(c, True)], [faible, fort], rent=True)
    assert v["publications"][0]["rapprochement"]["etat"] == "CORRESPONDANCE_DE_PROJECTION"
    assert v["publications"][0]["fait"]["reference"]["rang"] == 42
    assert v["selection"] == {
        "publication_courante_id": c["evenement_id"],
        "fact_courant_reference": {"departement": "m08-analytics", "registre": "faits_chantier", "rang": 42},
        "ambiguite": False,
    }


def test_deux_faits_forts_ambigus_ne_suppriment_pas_la_publication_source_courante():
    c = charge_rent(sequence=3)
    v = produire(
        [publication(c, True)], [recu(c, True)], [maillon(c, True, rang=7), maillon(c, True, rang=42)], rent=True
    )
    assert v["publications"][0]["rapprochement"]["etat"] == "LIEN_AMBIGU"
    assert v["selection"] == {
        "publication_courante_id": c["evenement_id"],
        "fact_courant_reference": None,
        "ambiguite": False,
    }


def test_faibles_legacy_seuls_restent_inconnus_sans_tie_source():
    c = charge_rent(sequence=3)
    faibles = [maillon(c, True, rang=r) for r in (7, 42)]
    for m in faibles:
        m["maillon"].pop("sequence")
    v = produire([publication(c, True)], (), faibles, rent=True)
    row = v["publications"][0]
    assert row["rapprochement"]["etat"] == "LIEN_INCONNU"
    assert "SEQUENCE_HISTORIQUE_ABSENTE" in row["rapprochement"]["codes"]
    assert row["fait"] is None
    assert v["selection"]["publication_courante_id"] == c["evenement_id"]
    assert v["selection"]["ambiguite"] is False


@pytest.mark.parametrize(
    "champ,native,corrompu",
    [("en_deficit", False, 0), ("en_deficit", True, 1), ("pieces", 1, 1.0), ("pieces", 1, True)],
)
def test_types_json_distincts_cash_ne_deviennent_pas_projection_exacte(champ, native, corrompu):
    c = charge_cash()
    if champ == "en_deficit":
        c[champ] = native
    m = maillon(c)
    if champ == "en_deficit":
        m["maillon"][champ] = corrompu
    else:
        m["maillon"]["solde"]["fraicheur"][champ] = corrompu
    row = produire([publication(c)], [recu(c)], [m])["publications"][0]
    assert row["rapprochement"]["etat"] == "FAITS_DIVERGENTS"
    assert "PROJECTION_DIFFERENTE" in row["rapprochement"]["codes"]
