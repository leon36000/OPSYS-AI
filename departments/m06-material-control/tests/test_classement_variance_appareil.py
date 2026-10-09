"""Fictif : publications M4/M6, preuves et SQLite réels; aucun Gateway/téléphone."""

from __future__ import annotations

import copy
import datetime as dt
import importlib.util
from pathlib import Path

import pytest
from m6_material_control import contrats, encodage, outils
from sqlalchemy import select, update

from opsys import contexte, identite, stockage
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS

p = Path(__file__).with_name("test_preuves_pertes_bris_appareil.py")
spec = importlib.util.spec_from_file_location("fixture_classement_m6", p)
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)
monde = fx.monde
ADMIN, EMP = fx.ADMIN, fx.EMP
LISTE = "m6_lister_variances_classables_wct_appareil"
ECRIRE = "m6_classer_cause_variance_appareil"
HISTO = "m6_lire_historique_classement_variance_appareil"
DATE = "2026-10-08T17:00:00+00:00"


def outil(nom):
    value = next((o for o in outils.outils() if o.nom == nom), None)
    assert value is not None, "outil classement de variance absent"
    return value


def executer(nom, args, actor=ADMIN, limite=5400):
    h = contexte.HorodatageAppareil(
        "APP-CLASSEMENT-FICTIF", dt.datetime.fromisoformat(DATE), dt.datetime.fromisoformat(DATE)
    )
    with contexte.appele_par_appareil(actor), contexte.receptionne_de(h), contexte.sortie_bornee(limite):
        return executer_atomique(outil(nom), args)


def preparer():
    args = fx.preparer(2)
    result = fx.executer(args)
    assert result["ok"] and result["resultat"]["accepte"]
    return args


def selection_sql(args):
    with stockage.transaction() as cnx:
        charge = stockage.codec.decoder(
            cnx.execute(
                select(EVENEMENTS_SORTANTS.c.charge).where(
                    EVENEMENTS_SORTANTS.c.evenement_id == f"m6-variance-{args['wct_id']}-evaluee"
                )
            ).scalar_one()
        )
    return {
        "wct_id": args["wct_id"],
        "reference_variance": {
            "type": "m6.variance_chantier",
            "evenement_id": charge["evenement_id"],
            "empreinte_charge": encodage.empreinte(charge),
        },
        "position_ligne": 0,
        "materiau_id": charge["lignes"][0]["materiau"],
    }


def demande(args, **changes):
    return {
        "selection": selection_sql(args),
        "cause": "waste",
        "motif": "FICTIF : cause choisie par admin",
        "classement_attendu": None,
        "references_pieces": [],
        **changes,
    }


def test_declarations_niveaux_roles_et_contexte():
    for nom in [LISTE, ECRIRE, HISTO]:
        o = outil(nom)
        assert o.roles_appareil == frozenset({"admin"})
        assert o.parametres["additionalProperties"] is False
        assert o.autonomie is (Autonomie.T1 if nom == ECRIRE else Autonomie.T0)
        assert o.niveau_effectif is (Niveau.N3 if nom == ECRIRE else Niveau.N0)
    o = outil(ECRIRE)
    assert (o.portee_contexte, o.cible_contexte, o.identite_contexte) == ("affaire", ("selection", "wct_id"), "wct")


def test_liste_publication_terminale_et_49tables_stables(monde):
    args = preparer()
    before = fx.fx._tables()
    r = executer(LISTE, {"wct_id": args["wct_id"], "decalage": 0, "limite": 8})
    assert r["ok"] and r["resultat"]["accepte"]
    dto = r["resultat"]["resultat"]
    assert dto["lignes"][0]["selection"] == selection_sql(args)
    assert dto["lignes"][0]["classement_courant"] is None
    assert len(dto["lignes"][0]["pieces_disponibles_a_selectionner"]) == 2
    assert dto["pagination"]["total"] == 1
    assert before == fx.fx._tables() and len(before) == 49
    assert "cout_unitaire" not in str(dto)


@pytest.mark.parametrize("cause", sorted(contrats.CAUSES_VARIANCE_CHANTIER))
def test_six_causes_explicitement_choisies_sans_autre_effet(monde, cause):
    args = preparer()
    d = demande(args, cause=cause)
    before = fx.fx._tables()
    r = executer(ECRIRE, d)
    assert r["ok"] and r["resultat"]["accepte"]
    ack = r["resultat"]["resultat"]
    assert ack["cause"] == cause and ack["selection"] == d["selection"]
    assert ack["auteur"] == {"personne": ADMIN.personne, "role": "admin", "source": "appareil"}
    assert ack["reference"]["registre"] == "classements_variance"
    assert ack["reference_precedente"] is None
    after = fx.fx._tables()
    assert {n for n in before if before[n] != after[n]} == {"registres_maillons"}


def test_correction_v2_replay_reference_v1_sans_latest_ni_cas(monde):
    args = preparer()
    d = demande(args)
    v1 = executer(ECRIRE, d)["resultat"]
    assert v1["accepte"]
    newer = {**d, "classement_attendu": v1["resultat"]["reference"], "cause": "breakage"}
    v2 = executer(ECRIRE, newer)["resultat"]
    assert v2["accepte"] and v2["resultat"]["reference_precedente"] == v1["resultat"]["reference"]
    before = fx.fx._tables()
    with contexte.appele_par_appareil(ADMIN), stockage.transaction():
        outils.verifier_rejeu_classement_variance_appareil(d, {"ok": True, "resultat": v1})
    assert before == fx.fx._tables()
    conflict = executer(ECRIRE, newer)["resultat"]
    assert not conflict["accepte"] and conflict["verdict"]["code"] == "REJ-M6-CLASSEMENT-REVISION-PERIMEE"
    assert before == fx.fx._tables()
    r = executer(HISTO, {"selection": d["selection"], "decalage": 0, "limite": 8})
    assert [x["cause"] for x in r["resultat"]["resultat"]["historique"]] == ["waste", "breakage"]
    assert before == fx.fx._tables()


@pytest.mark.parametrize(
    "actor",
    [
        EMP,
        contexte.IdentiteAppelante("vendeur.fictif", "seller"),
        contexte.IdentiteAppelante("inconnu.fictif", "admin"),
        contexte.IdentiteAppelante(ADMIN.personne, "admin", source="console"),
    ],
)
def test_autorite_admin_device_avant_sources(monde, actor):
    args = preparer()
    before = fx.fx._tables()
    r = executer(LISTE, {"wct_id": args["wct_id"], "decalage": 0, "limite": 8}, actor)
    assert r["ok"] and r["resultat"]["verdict"]["code"] == "REJ-M6-CLASSEMENT-IDENTITE-INVALIDE"
    assert before == fx.fx._tables()


def test_role_retire_garde_avant_source(monde):
    args = preparer()
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN.personne, "admin")
    _, patch = monde
    calls = []
    patch.setattr(outils, "_wct_publie_par_m4", lambda *_: calls.append(1))
    r = executer(LISTE, {"wct_id": args["wct_id"], "decalage": 0, "limite": 8})
    assert r["resultat"]["verdict"]["code"] == "REJ-M6-CLASSEMENT-IDENTITE-INVALIDE"
    assert calls == []


@pytest.mark.parametrize("change", ["hash", "position", "materiau", "type"])
def test_selection_source_forgee_sans_ecriture(monde, change):
    args = preparer()
    d = demande(args)
    if change == "hash":
        d["selection"]["reference_variance"]["empreinte_charge"] = "0" * 64
    if change == "position":
        d["selection"]["position_ligne"] = 1
    if change == "materiau":
        d["selection"]["materiau_id"] = "AUTRE-FICTIF"
    if change == "type":
        d["selection"]["reference_variance"]["type"] = "m5.facture"
    before = fx.fx._tables()
    r = executer(ECRIRE, d)
    assert r["ok"] and not r["resultat"]["accepte"]
    assert before == fx.fx._tables()


def test_reference_piece_exacte_et_etrangere_refusee(monde):
    args = preparer()
    with stockage.transaction():
        proofs = list(stockage.maillons("m06-material-control", "preuves_pertes_bris"))
    ref = fx.outils.preuves_pertes_bris_appareil.reference("preuves_pertes_bris", proofs[0])
    piece = {"reference_mouvement": proofs[0]["reference_mouvement"], "reference_preuve": ref, "positions_photos": []}
    d = demande(args, references_pieces=[piece])
    r = executer(ECRIRE, d)
    assert r["resultat"]["accepte"] and r["resultat"]["resultat"]["references_pieces"] == [piece]
    bad = copy.deepcopy(d)
    bad["references_pieces"][0]["reference_mouvement"]["hash_maillon"] = "0" * 64
    bad["classement_attendu"] = r["resultat"]["resultat"]["reference"]
    before = fx.fx._tables()
    assert not executer(ECRIRE, bad)["resultat"]["accepte"]
    assert before == fx.fx._tables()


def test_quota_entier_avant_append_et_postwrite_rollback(monde):
    args = preparer()
    d = demande(args)
    before = fx.fx._tables()
    r = executer(ECRIRE, d, limite=800)
    assert not r["resultat"]["accepte"]
    assert before == fx.fx._tables()
    _, patch = monde
    o = outils.classement_variance_appareil
    original = o.verifier_borne
    calls = []

    def reject_after(*a, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise o.Refus("SORTIE-TROP-VOLUMINEUSE")
        return original(*a, **kw)

    patch.setattr(o, "verifier_borne", reject_after)
    assert not executer(ECRIRE, d)["resultat"]["accepte"]
    assert before == fx.fx._tables()


def test_source_json_corrompue_refus_ferme(monde):
    args = preparer()
    with stockage.transaction() as cnx:
        cnx.execute(
            update(EVENEMENTS_SORTANTS)
            .where(EVENEMENTS_SORTANTS.c.evenement_id == f"m6-variance-{args['wct_id']}-evaluee")
            .values(charge="{FICTIF-CORROMPU")
        )
    before = fx.fx._tables()
    r = executer(LISTE, {"wct_id": args["wct_id"], "decalage": 0, "limite": 8})
    assert r["ok"] and r["resultat"]["verdict"]["code"] == "REJ-M6-CLASSEMENT-SOURCE-INVALIDE"
    assert before == fx.fx._tables()


def test_source_chantier_divergent_catalogue_valide_refuse(monde):
    args = preparer()
    with stockage.transaction() as cnx:
        row = cnx.execute(
            select(EVENEMENTS_SORTANTS.c.charge).where(
                EVENEMENTS_SORTANTS.c.evenement_id == f"m6-variance-{args['wct_id']}-evaluee"
            )
        ).scalar_one()
        charge = stockage.codec.decoder(row)
        charge["chantier_id"] = "CHANTIER-ETRANGER-FICTIF"
        cnx.execute(
            update(EVENEMENTS_SORTANTS)
            .where(EVENEMENTS_SORTANTS.c.evenement_id == charge["evenement_id"])
            .values(charge=stockage.codec.encoder(charge))
        )
    before = fx.fx._tables()
    r = executer(LISTE, {"wct_id": args["wct_id"], "decalage": 0, "limite": 8})
    assert r["ok"] and not r["resultat"]["accepte"]
    assert before == fx.fx._tables()


def test_classement_corrompu_type_cause_refus_nominal(monde):
    from opsys.stockage.schema import REGISTRES

    args = preparer()
    assert executer(ECRIRE, demande(args))["resultat"]["accepte"]
    with stockage.transaction() as cnx:
        m = list(stockage.maillons("m06-material-control", "classements_variance"))[0]
        m["cause"] = {"FICTIF": "pas_un_enum"}
        m["hash_maillon"] = encodage.empreinte({k: v for k, v in m.items() if k != "hash_maillon"})
        cnx.execute(
            update(REGISTRES)
            .where(REGISTRES.c.departement == "m06-material-control", REGISTRES.c.registre == "classements_variance")
            .values(maillon=stockage.codec.encoder(m))
        )
    before = fx.fx._tables()
    r = executer(LISTE, {"wct_id": args["wct_id"], "decalage": 0, "limite": 8})
    assert r["ok"] and r["resultat"]["verdict"]["code"] == "REJ-M6-CLASSEMENT-REGISTRE-INVALIDE"
    assert before == fx.fx._tables()


def test_non_critique_perte_reelle_reste_classable(monde):
    _, patch = monde
    original = fx.fx._prevu
    patch.setattr(
        fx.fx, "_prevu", lambda: original(lignes=[{"materiau_id": fx.fx.MAT, "quantite_estimee": 2, "unite": "pi"}])
    )
    args = preparer()
    d = executer(LISTE, {"wct_id": args["wct_id"], "decalage": 0, "limite": 8})["resultat"]["resultat"]
    assert d["lignes"][0]["source_ligne"]["critique"] is False
    assert len(d["lignes"][0]["pieces_disponibles_a_selectionner"]) == 2
    assert executer(ECRIRE, demande(args))["resultat"]["accepte"]


def test_append_autre_objet_ne_perime_pas_revision_metier(monde):
    _, patch = monde
    autre = "Z-MAT-CLASSEMENT-FICTIF"
    original = fx.fx._prevu
    patch.setattr(
        fx.fx,
        "_prevu",
        lambda: original(
            lignes=[
                {"materiau_id": fx.fx.MAT, "quantite_estimee": 40, "unite": "pi"},
                {"materiau_id": autre, "quantite_estimee": 20, "unite": "pi"},
            ]
        ),
    )
    args = fx.preparer(2)
    reception = {
        "po_id": "PO-CLASSEMENT-AUTRE",
        "chantier_id": fx.fx.CH,
        "lignes_demandees": [{"materiau_id": autre, "quantite_demandee": 100}],
        "horodatage": DATE,
    }
    recu = {
        "po_id": reception["po_id"],
        "chantier_id": fx.fx.CH,
        "lignes_recues": [{"materiau_id": autre, "quantite_recue": 100}],
        "horodatage": DATE,
    }
    o = next(o for o in outils.outils() if o.nom == "m6_receptionner_commande")
    assert executer_atomique(
        o,
        {
            "bon_demande": reception,
            "reception_po": recu,
            "catalogue_materiaux": {
                "version": "FICTIF",
                "unite_monetaire": "CAD",
                "postes": {autre: {"cout_unitaire": 2, "libelle": "FICTIF"}},
            },
        },
    )["resultat"]["accepte"]
    args["formulaire"]["lignes_materiaux"][1]["materiau_id"] = autre
    assert fx.executer(args)["resultat"]["accepte"]
    page = executer(LISTE, {"wct_id": args["wct_id"], "decalage": 0, "limite": 8})["resultat"]["resultat"]
    assert len(page["lignes"]) == 2
    a = demande(args, selection=page["lignes"][0]["selection"])
    v1 = executer(ECRIRE, a)["resultat"]
    b = demande(args, selection=page["lignes"][1]["selection"])
    assert executer(ECRIRE, b)["resultat"]["accepte"]
    v2 = executer(ECRIRE, {**a, "cause": "breakage", "classement_attendu": v1["resultat"]["reference"]})
    assert v2["resultat"]["accepte"] and v2["resultat"]["resultat"]["reference"]["index"] == 2


def test_deux_corrections_concurrentes_une_seule_revision(monde):
    from concurrent.futures import ThreadPoolExecutor

    args = preparer()
    d = demande(args)
    first = executer(ECRIRE, d)["resultat"]["resultat"]["reference"]
    body = {**d, "classement_attendu": first, "cause": "breakage"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: executer(ECRIRE, body), range(2)))
    assert sum(r["resultat"]["accepte"] is True for r in replies) == 1
    failed = next(r for r in replies if not r["resultat"]["accepte"])
    assert failed["resultat"]["verdict"]["code"] == "REJ-M6-CLASSEMENT-REVISION-PERIMEE"
    with stockage.transaction():
        assert len(stockage.maillons("m06-material-control", "classements_variance")) == 2


@pytest.mark.parametrize("kind", [TypeError, KeyError, RuntimeError])
def test_panne_apres_append_remonte_technique_et_annule(monde, kind):
    args = preparer()
    _, patch = monde
    original = outils._ajouter_classement_variance

    def panne(m):
        original(m)
        raise kind("FICTIF-pannehors-savepoint")

    patch.setattr(outils, "_ajouter_classement_variance", panne)
    before = fx.fx._tables()
    with pytest.raises(RuntimeError, match="échec technique"):
        executer(ECRIRE, demande(args))
    assert before == fx.fx._tables()


@pytest.mark.parametrize(
    "page", [{"decalage": True}, {"decalage": -1}, {"decalage": 10001}, {"limite": True}, {"limite": 0}, {"limite": 9}]
)
def test_pages_invalides_refusees_sans_effet(monde, page):
    args = preparer()
    before = fx.fx._tables()
    r = executer(LISTE, {"wct_id": args["wct_id"], "decalage": 0, "limite": 8, **page})
    assert not r["ok"] or not r["resultat"]["accepte"]
    assert before == fx.fx._tables()


def test_source_non_finalisee_pas_liste_vide(monde):
    args = fx.preparer(2)
    before = fx.fx._tables()
    r = executer(LISTE, {"wct_id": args["wct_id"], "decalage": 0, "limite": 8})
    assert r["resultat"]["verdict"]["code"] == "REJ-M6-CLASSEMENT-VARIANCE-NON-FINALISEE"
    assert before == fx.fx._tables()


def test_json_registre_classement_corrompu_refus_ferme(monde):
    from opsys.stockage.schema import REGISTRES

    args = preparer()
    assert executer(ECRIRE, demande(args))["resultat"]["accepte"]
    with stockage.transaction() as cnx:
        cnx.execute(
            update(REGISTRES)
            .where(REGISTRES.c.departement == "m06-material-control", REGISTRES.c.registre == "classements_variance")
            .values(maillon="{FICTIF-INVALIDE")
        )
    before = fx.fx._tables()
    r = executer(LISTE, {"wct_id": args["wct_id"], "decalage": 0, "limite": 8})
    assert r["ok"] and r["resultat"]["verdict"]["code"] == "REJ-M6-CLASSEMENT-REGISTRE-INVALIDE"
    assert before == fx.fx._tables()


def test_rejeu_propre_reference_sans_lecture_cas_apres_disparition(monde):
    import base64

    from opsys.stockage.schema import FICHIERS_BLOCS

    args = fx.preparer(1)
    cas = fx.deposer()
    args["preuves_lignes"][0]["photos"] = [cas]
    proof = fx.executer(args)["resultat"]["resultat"]["preuves"][0]
    d = demande(
        args,
        references_pieces=[
            {
                "reference_mouvement": proof["reference_mouvement"],
                "reference_preuve": proof["reference_preuve"],
                "positions_photos": [0],
            }
        ],
    )
    ack = executer(ECRIRE, d)["resultat"]
    assert ack["accepte"]
    with stockage.transaction() as cnx:
        cnx.execute(update(FICHIERS_BLOCS).values(contenu_base64=base64.b64encode(b"FICTIF-corrompu").decode()))
    _, patch = monde

    def interdit(*_):
        raise AssertionError("CAS ne doit pas authentifier un ACK historique")

    patch.setattr(outils.fichiers, "lire_blob_verifie", interdit)
    before = fx.fx._tables()
    with contexte.appele_par_appareil(ADMIN), stockage.transaction():
        outils.verifier_rejeu_classement_variance_appareil(d, {"ok": True, "resultat": ack})
    assert before == fx.fx._tables()


def test_non_critique_sans_perte_bris_hors_perimetre(monde):
    args = fx.preparer(1)
    args["formulaire"]["lignes_materiaux"] = [
        {"type_ligne": "prevu", "materiau_id": fx.fx.MAT, "quantite": 40, "quantite_estimee": 40, "unite": "pi"}
    ]
    args["preuves_lignes"] = []
    assert fx.executer(args)["resultat"]["accepte"]
    before = fx.fx._tables()
    r = executer(LISTE, {"wct_id": args["wct_id"], "decalage": 0, "limite": 8})["resultat"]["resultat"]
    assert r["lignes"] == [] and r["pagination"]["total"] == 0
    bad = executer(ECRIRE, demande(args))["resultat"]
    assert bad["verdict"]["code"] == "REJ-M6-CLASSEMENT-LIGNE-HORS-PERIMETRE"
    assert before == fx.fx._tables()


def test_historique_budget_complet_pagination_sans_fait_coupe(monde):
    import json

    args = preparer()
    d = demande(args, motif="FICTIF " + "é" * 430)
    expected = None
    for _ in range(8):
        r = executer(ECRIRE, {**d, "classement_attendu": expected})["resultat"]
        assert r["accepte"]
        expected = r["resultat"]["reference"]
    before = fx.fx._tables()
    page = executer(HISTO, {"selection": d["selection"], "decalage": 0, "limite": 8})
    dto = page["resultat"]["resultat"]
    assert len(json.dumps(page, ensure_ascii=False)) <= 5400
    assert 0 < len(dto["historique"]) < 8 and dto["pagination"]["borne_atteinte"] is True
    assert all(m["motif"] == d["motif"] for m in dto["historique"])
    assert dto["pagination"]["total"] == 8 and dto["pagination"]["reste"] == 8 - len(dto["historique"])
    nextpage = executer(
        HISTO, {"selection": d["selection"], "decalage": dto["pagination"]["decalage_suivant"], "limite": 8}
    )
    assert nextpage["resultat"]["resultat"]["historique"][0]["reference"]["index"] == len(dto["historique"])
    assert before == fx.fx._tables()


def test_borne_source_10000_10001_apres_copies_compte_lignes_publiques(monde):
    args = preparer()
    with contexte.appele_par_appareil(ADMIN), stockage.transaction():
        _, source = outils.autoriser_classement_variance_appareil(demande(args))
    c = outils.classement_variance_appareil
    poids = 1 + len(source["charge"]["lignes"]) + len(source["principal"]) + len(source["preuves"])
    # Test pur de la borne agrégée après copies : cardinalité admission fournie,
    # snapshots réellement produits, pas une prétention de 10000 écritures SQL.
    assert (
        c.valider_source(source["wct"], source["charge"], source["principal"], source["preuves"], [], 10000 - poids)[
            "charge"
        ]
        == source["charge"]
    )
    with pytest.raises(c.Refus, match="BORNE-SOURCES"):
        c.valider_source(source["wct"], source["charge"], source["principal"], source["preuves"], [], 10001 - poids)
