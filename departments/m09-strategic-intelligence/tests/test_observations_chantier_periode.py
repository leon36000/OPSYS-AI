"""Observations WCT fictives : transport M8/M9 réel, SQL et permissions natifs."""

from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import event, select, update

from opsys import contexte, evenements, identite, stockage
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

_spec = importlib.util.spec_from_file_location(
    "_observations_wct_base", Path(__file__).with_name("test_suivi_decisions.py")
)
b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(b)
installation = b.installation
NOM = "m9_observations_chantier_periode"
DEBUT = "2026-09-28T00:00:00+00:00"
FIN = "2026-09-29T00:00:00+00:00"


def _recevoir(departements, suffixe="a", instant="2026-09-28T14:00:00-04:00", type_travaux="gouttières", tours=2):
    charge = {
        "wct_id": "wct-observation-" + suffixe, "intervention_id": "intervention-" + suffixe,
        "lead_id": "lead-fictif-prive", "technicien_id": b.RESPONSABLE,
        "horodatage_completion": instant, "fix_gps_completion": {},
        "duree_reelle_minutes": 129, "ecart_signale": False, "revue_id": None,
        "hash_maillon": "preuve-wct-fictive", "consommateurs_cibles": ["M8"],
        "devis_id": None, "statut": "completed_verified", "type_travaux": type_travaux,
    }
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="wct-observe-" + suffixe)
    for _ in range(tours):
        resume = evenements.repartir(departements, maintenant="2026-10-20T00:00:00+00:00")
        assert resume["echecs"] == resume["quarantaines"] == 0
    return charge


def _lire(cap, **args):
    return b._lire(cap, NOM, {"debut": DEBUT, "fin": FIN} | args)


def test_lecture_periode_apres_vrai_wct_transporte_et_sans_mutation_sql(installation):
    charge = _recevoir(installation)
    maillons = list(stockage.maillons(b.DEPARTEMENT, "snapshots"))
    assert len(maillons) == 1 and maillons[0]["valeurs"]["m4_wct_id"] == charge["wct_id"]
    publication = evenements.charge_publiee(
        "m8.snapshot_chantier", maillons[0]["valeurs"]["m8_snapshot_evenement_id"]
    )
    assert publication["snapshot"]["valeurs"]["m4_duree_reelle_minutes"] == "129"
    cap = b._capacites(installation)
    assert NOM in cap.index, "LECTURE_OBSERVATIONS_PERIODE_ABSENTE_APRES_TRANSPORT_WCT_M8_M9_NATIF"
    page = _lire(cap)
    assert page["type"] == "OBSERVATIONS_CHANTIER_PERIODE" and page["total"] == 1
    assert page["observations"][0]["maillon"] == maillons[0]
    assert page["observations"][0]["publication"] == publication
    assert page["observations"][0]["nature"] == "source_bus_liee"
    assert page["observations"][0]["authentification_producteur"] == "NON_PROUVEE"
    assert page["rapport_complet"] is False and page["actualite_metier"] == "NON_EVALUEE"



def _sources():
    maillons = list(stockage.maillons(b.DEPARTEMENT, "snapshots"))
    publications = {m["valeurs"]["m8_snapshot_evenement_id"]: evenements.charge_publiee(
        "m8.snapshot_chantier", m["valeurs"]["m8_snapshot_evenement_id"])
        for m in maillons if "m8_snapshot_evenement_id" in m["valeurs"]}
    return deepcopy(maillons), deepcopy(publications)


def _pur(maillons, publications, **args):
    from importlib import import_module
    fonction = import_module("m9_strategic_intelligence.observations_chantier").lister_observations_chantier
    return fonction(maillons, publications, **({"debut": DEBUT, "fin": FIN,
                                               "budget_caracteres": 100_000} | args))


def _ajouter_t1(cap, snapshot, cle="observation-t1-fictive"):
    demande = cap.appeler("m9_etat_consolide", {"snapshot": snapshot})
    assert demande["statut"] == "en_attente_approbation", demande
    decision = b._decider(cap, demande["demande_id"], cle)
    assert decision["resultat"]["resultat"]["statut"] == "executee", decision


def _projection(charge):
    snapshot = deepcopy(charge["snapshot"])
    snapshot["valeurs"].update({"m8_snapshot_evenement_id": charge["evenement_id"],
        "m8_snapshot_index": str(charge["source_m8"]["index"]),
        "m8_snapshot_hash_maillon": charge["source_m8"]["hash_maillon"]})
    return snapshot


def _refus(cap, *, erreur_schema=None, **args):
    avant = b._tables()
    with contexte.appele_par_appareil(b.PROPRIO):
        resultat = cap.appeler(NOM, {"debut": DEBUT, "fin": FIN} | args)
    assert resultat["ok"] is False, resultat
    if erreur_schema is None:
        assert "REJ-" in json.dumps(resultat), resultat
    else:
        assert resultat == erreur_schema, resultat
    assert "tronque" not in resultat and b._tables() == avant
    return resultat


@pytest.mark.parametrize("instant,attendu", [
    ("2026-09-27T20:00:00-04:00", 1),
    ("2026-09-28T23:59:59+00:00", 1),
    ("2026-09-28T20:00:00-04:00", 0),
])
def test_bornes_metier_demi_ouvertes_et_fuseaux(installation, instant, attendu):
    _recevoir(installation, instant=instant)
    maillons, publications = _sources()
    assert _pur(maillons, publications)["total"] == attendu
    assert _lire(b._capacites(installation))["total"] == attendu


def test_wct_distincts_meme_instant_conservent_leurs_preuves(installation):
    _recevoir(installation, "a")
    _recevoir(installation, "b", instant="2026-09-28T18:00:00Z")
    maillons, publications = _sources()
    page = _pur(maillons, publications)
    assert page["total"] == 2
    assert {o["maillon"]["valeurs"]["m4_wct_id"] for o in page["observations"]} == {
        "wct-observation-a", "wct-observation-b"}
    assert [o["publication"]["evenement_id"] for o in page["observations"]] == sorted(publications)
    assert {o["maillon"]["hash_maillon"] for o in page["observations"]} == {m["hash_maillon"] for m in maillons}


def test_generique_hors_periode_exclu_et_compte_globalement(installation):
    _recevoir(installation)
    cap = b._capacites(installation)
    _ajouter_t1(cap, {"module_source": "m05-financecore", "horodatage": "1999-01-01T00:00:00Z",
                      "valeurs": {"m4_wct_id": "faux-wct-generique", "cash": "999"}})
    page = _lire(cap)
    assert page["total"] == 1 and page["snapshots_generiques_non_couverts"] == 1
    assert len(page["observations"]) == 1 and page["rapport_complet"] is False


@pytest.mark.parametrize("cause", ["publication_absente", "projection_differente"])
def test_faux_marqueur_t1_hors_periode_refuse_avant_filtre(installation, cause):
    _recevoir(installation, instant="2026-09-30T12:00:00Z", tours=1)
    [source] = list(stockage.maillons("m08-analytics", "snapshots"))
    charge = evenements.charge_publiee("m8.snapshot_chantier",
                                     "m8-snapshot-chantier-" + source["hash_maillon"])
    forge = _projection(charge)
    if cause == "publication_absente":
        forge["valeurs"]["m8_snapshot_evenement_id"] = "m8-snapshot-chantier-" + "f" * 64
        forge["valeurs"]["m8_snapshot_hash_maillon"] = "f" * 64
    else:
        forge["valeurs"]["m4_duree_reelle_minutes"] = "999"
    cap = b._capacites(installation)
    _ajouter_t1(cap, forge)
    _refus(cap)


@pytest.mark.parametrize("identique", [True, False])
def test_doublon_evenement_ou_wct_chaine_t1_valide_refuse_globalement(installation, identique):
    _recevoir(installation, instant="2026-09-30T12:00:00Z")
    _, publications = _sources()
    charge = deepcopy(next(iter(publications.values())))
    if not identique:
        # Charge cataloguée distincte, même WCT et hors période : pas d'authentification déduite.
        charge["source_m8"]["hash_maillon"] = "e" * 64
        charge["source_m8"]["index"] += 1
        charge["evenement_id"] = "m8-snapshot-chantier-" + "e" * 64
        charge["snapshot"]["horodatage"] = "2026-10-01T12:00:00Z"
        evenements.publier("m8.snapshot_chantier", "m08-analytics", charge,
                           evenement_id=charge["evenement_id"])
    cap = b._capacites(installation)
    _ajouter_t1(cap, _projection(charge))
    from m9_strategic_intelligence.registre import RegistreSnapshots
    assert RegistreSnapshots(list(stockage.maillons(b.DEPARTEMENT, "snapshots"))).valider_chaine()[0]
    _refus(cap)


def test_outbox_native_non_distribuee_projetee_par_t1_ne_prouve_pas_reception(installation):
    _recevoir(installation, tours=1)
    assert list(stockage.maillons(b.DEPARTEMENT, "snapshots")) == []
    [m8] = list(stockage.maillons("m08-analytics", "snapshots"))
    ident = "m8-snapshot-chantier-" + m8["hash_maillon"]
    charge = evenements.charge_publiee("m8.snapshot_chantier", ident)
    assert charge is not None
    with stockage.transaction() as cnx:
        assert cnx.execute(select(EVENEMENTS_RECUS).where(
            EVENEMENTS_RECUS.c.evenement_id == ident,
            EVENEMENTS_RECUS.c.consommateur == b.DEPARTEMENT)).first() is None
    cap = b._capacites(installation)
    _ajouter_t1(cap, _projection(charge))
    page = _lire(cap)
    [observation] = page["observations"]
    assert observation["publication"] == charge
    assert observation["nature"] == "source_bus_liee"
    assert observation["authentification_producteur"] == "NON_PROUVEE"
    assert page["statut"] == "NON_VALIDE" and page["actualite_metier"] == "NON_EVALUEE"


def test_pagination_json_complet_originaux_et_copies_isolees(installation):
    for suffixe in ("a", "b", "c"):
        _recevoir(installation, suffixe)
    maillons, publications = _sources()
    originaux = deepcopy((maillons, publications))
    entier = _pur(maillons, publications)
    budget = len(json.dumps(entier, ensure_ascii=False)) - sum(
        len(json.dumps(o, ensure_ascii=False)) for o in entier["observations"][1:]) + 100
    page = _pur(maillons, publications, budget_caracteres=budget)
    assert 0 < page["affichees"] < page["total"] == 3
    observations = []
    while True:
        assert len(json.dumps(page, ensure_ascii=False)) <= budget
        assert page["affichees"] == len(page["observations"])
        observations.extend(page["observations"])
        if page["prochain_depart"] is None:
            assert page["reste"] == 0
            break
        page = _pur(maillons, publications, depart=page["prochain_depart"],
                    vue_attendue=page["vue"], budget_caracteres=budget)
    assert observations == entier["observations"] and (maillons, publications) == originaux
    observations[0]["publication"]["snapshot"]["valeurs"]["m4_duree_reelle_minutes"] = "999"
    assert (maillons, publications) == originaux


def test_append_generique_hors_periode_invalide_vue_depart_zero(installation):
    _recevoir(installation)
    cap = b._capacites(installation)
    vue = _lire(cap)["vue"]
    _ajouter_t1(cap, {"module_source": "generique-fictif", "horodatage": "1999-01-01T00:00:00Z",
                      "valeurs": {"etat": "fictif"}})
    _refus(cap, vue_attendue=vue)


@pytest.mark.parametrize("args", [
    {"debut": "2026-09-28T00:00:00"}, {"fin": DEBUT}, {"depart": True},
    {"depart": 1}, {"vue_attendue": "A" * 64},
])
def test_parametres_invalides_refuses_sans_mutation(installation, args):
    _recevoir(installation)
    schema = ({"ok": False, "erreur": "arguments_invalides",
               "details": ["depart : type attendu integer"]} if args.get("depart") is True else None)
    _refus(b._capacites(installation), erreur_schema=schema, **args)


@pytest.mark.parametrize("cause", ["employee", "admin_revoque", "inactif"])
def test_sql_courant_avant_ledger_et_bus(installation, monkeypatch, cause):
    cap = b._capacites(installation)
    with stockage.transaction() as cnx:
        if cause == "admin_revoque":
            identite.retirer_role(cnx, b.PROPRIO.personne, "admin")
        elif cause == "inactif":
            identite.activer(cnx, b.PROPRIO.personne, False)
    personne = (contexte.IdentiteAppelante(personne=b.RESPONSABLE, role="employee")
                if cause == "employee" else b.PROPRIO)
    def interdit(*args, **kwargs):
        pytest.fail("Lecture ledger/bus avant vérification du rôle SQL courant")
    monkeypatch.setattr(stockage, "maillons", interdit)
    monkeypatch.setattr(evenements, "charge_publiee", interdit)
    avant = b._tables()
    def interdire_sql_metier(cnx, curseur, instruction, parametres, ctx, plusieurs):
        sql = instruction.lower()
        if sql.lstrip().startswith("select") and any(
            table.name.lower() in sql for table in (REGISTRES, EVENEMENTS_SORTANTS, EVENEMENTS_RECUS)
        ):
            pytest.fail("SQL des preuves exécuté avant refus du rôle courant")
    moteur = stockage.moteur()
    event.listen(moteur, "before_cursor_execute", interdire_sql_metier)
    try:
        with contexte.appele_par_appareil(personne):
            refus = cap.appeler(NOM, {"debut": DEBUT, "fin": FIN})
    finally:
        event.remove(moteur, "before_cursor_execute", interdire_sql_metier)
    assert refus["ok"] is False and b._tables() == avant, refus


def test_chaine_alteree_refuse_avant_publication(installation, monkeypatch):
    _recevoir(installation)
    [maillon], _ = _sources()
    maillon["valeurs"]["m4_duree_reelle_minutes"] = "999"
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).where(REGISTRES.c.departement == b.DEPARTEMENT,
            REGISTRES.c.registre == "snapshots").values(maillon=codec.encoder(maillon)))
    cap = b._capacites(installation)
    def interdit(*args, **kwargs):
        pytest.fail("Publication lue avant rejet de la chaîne altérée")
    monkeypatch.setattr(evenements, "charge_publiee", interdit)
    assert "REJ-SNAPSHOT-CHAINE-INVALIDE" in json.dumps(_refus(cap))


@pytest.mark.parametrize("avec_observation", [False, True])
def test_budget_insuffisant_refuse_base_ou_preuve_sans_tronquer(installation, avec_observation):
    if avec_observation:
        _recevoir(installation, type_travaux="gouttières fictives " * 300)
    maillons, publications = _sources()
    budget = (len(json.dumps(_pur([], {}), ensure_ascii=False)) + 300
              if avec_observation else 100)
    with pytest.raises(ValueError, match="REJ-OBSERVATIONS-BORNE"):
        _pur(maillons, publications, budget_caracteres=budget)


def test_arrivee_tardive_change_periode_passee_et_vue(installation):
    _recevoir(installation, "recent", instant="2026-09-30T12:00:00Z")
    cap = b._capacites(installation)
    avant = _lire(cap)
    assert avant["total"] == 0
    _recevoir(installation, "tardif", instant="2026-09-28T09:00:00Z")
    apres = _lire(cap)
    assert apres["total"] == 1 and apres["vue"] != avant["vue"]
    assert apres["observations"][0]["maillon"]["valeurs"]["m4_wct_id"] == "wct-observation-tardif"
    _refus(cap, vue_attendue=avant["vue"])


def test_tri_instants_reels_ne_suit_pas_ordre_texte(installation):
    _recevoir(installation, "tot", instant="2026-09-28T10:00:00+09:00")
    _recevoir(installation, "tard", instant="2026-09-28T02:00:00Z")
    page = _lire(b._capacites(installation))
    assert [o["maillon"]["valeurs"]["m4_wct_id"] for o in page["observations"]] == [
        "wct-observation-tot", "wct-observation-tard"]


@pytest.mark.parametrize("cause", ["index_bool", "metadata_incomplete", "metadata_extra", "module_source"])
def test_registre_entier_et_transport_stricts_avant_filtre_pur(installation, cause):
    _recevoir(installation, instant="2026-09-30T12:00:00Z")
    maillons, publications = _sources()
    if cause == "index_bool":
        maillons[0]["index"] = False
    elif cause == "metadata_incomplete":
        del maillons[0]["valeurs"]["m8_snapshot_index"]
    elif cause == "metadata_extra":
        maillons[0]["valeurs"]["m8_snapshot_imprevu"] = "fictif"
    else:
        maillons[0]["module_source"] = "m05-financecore"
    with pytest.raises(ValueError, match="REJ-OBSERVATIONS-(REGISTRE|TRANSPORT)"):
        _pur(maillons, publications)


def test_date_generique_non_interpretee_par_lecture_pure(installation):
    _recevoir(installation)
    maillons, publications = _sources()
    # Entrée générique déclarative : la fonction pure ne prétend pas valider sa chaîne.
    maillons.append({"index": 1, "module_source": "generique", "horodatage": "date non exploitable",
                     "valeurs": {"cash": "999"}})
    page = _pur(maillons, publications)
    assert page["total"] == 1 and page["snapshots_generiques_non_couverts"] == 1
