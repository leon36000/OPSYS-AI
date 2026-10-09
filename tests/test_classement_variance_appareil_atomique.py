"""Fictif : contrat Cap, SQLite et rétention du classement humain DEVICE."""

from __future__ import annotations

import copy
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from m6_material_control import outils
from sqlalchemy import event, select, update

from opsys import approbations, contexte, fichiers, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS, MUTATIONS_APPLIQUEES

MUTATION = "m6_classer_cause_variance_appareil"
LECTURES = (
    "m6_lister_variances_classables_wct_appareil",
    "m6_lire_historique_classement_variance_appareil",
)
path = (
    Path(__file__).resolve().parents[1]
    / "departments/m06-material-control/tests/test_preuves_pertes_bris_appareil.py"
)
spec = importlib.util.spec_from_file_location("fixture_cap_classement_preuves", path)
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)
monde = fx.monde
spec = importlib.util.spec_from_file_location(
    "fixture_cap_classement", path.with_name("test_classement_variance_appareil.py")
)
cfx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cfx)
META = idempotence.Meta(
    cle="4612b2de-a1c4-4a68-a044-e0ab685025ad",
    appareil="APP-CLASSEMENT-FICTIF",
    horodatage_appareil=fx.fx.DATE,
)


def capacite(limite=6000):
    return Capacites(charger_departements(), stockage.transaction, limite_sortie=limite)


def appeler(cap, arguments, meta=META, acteur=fx.ADMIN):
    with contexte.appele_par_appareil(acteur):
        return cap.appeler(MUTATION, arguments, meta=meta)


def meta(suffixe):
    return idempotence.Meta(
        cle=f"4612b2de-a1c4-4a68-a044-e0ab685025{suffixe:02d}",
        appareil=META.appareil,
        horodatage_appareil=META.horodatage_appareil,
    )


def accepter(response):
    assert response["ok"] and response["resultat"]["accepte"], response
    return response["resultat"]["resultat"]


@pytest.mark.parametrize("nom", LECTURES)
def test_lecture_t0_meta_refuse_avant_claim(monde, nom):
    _, patch = monde
    claims = []
    original = idempotence.reclamer

    def observe(*args):
        claims.append(args)
        return original(*args)

    patch.setattr(idempotence, "reclamer", observe)
    before = fx.fx._tables()
    with contexte.appele_par_appareil(fx.ADMIN):
        r = capacite().appeler(nom, {}, meta=META)
    assert r.get("erreur") == "idempotence_hors_portee_lecture", r
    assert claims == []
    assert before == fx.fx._tables()


@pytest.mark.parametrize("nom", (MUTATION, *LECTURES))
@pytest.mark.parametrize("quota", [800, 5400, 9000])
def test_borne_points_code_enveloppe_entiere_unicode(monde, nom, quota):
    r = {"ok": True, "resultat": {"fictif": ""}}
    def complete(value):
        return {**value, "rejoue": False} if nom == MUTATION else value
    target = min(quota, 5400)
    overhead = len(json.dumps(complete(r), ensure_ascii=False))
    r["resultat"]["fictif"] = "😀" * (target - overhead)
    texte = json.dumps(complete(r), ensure_ascii=False)
    assert len(texte) == target and len(texte.encode()) > target
    before = fx.fx._tables()
    cap = capacite(quota)
    assert cap._tronquer(r, nom) == r
    too_large = {"ok": True, "resultat": {"fictif": r["resultat"]["fictif"] + "é"}}
    refused = cap._tronquer(too_large, nom)
    assert not refused["ok"] and "apercu" not in refused and "tronque" not in refused
    assert before == fx.fx._tables()


def test_reponse_perdue_restart_meme_ack_et_un_seul_effet(monde):
    d = cfx.demande(cfx.preparer())
    before = fx.fx._tables()
    first = appeler(capacite(), d)
    accepter(first)
    after = fx.fx._tables()
    assert {n for n in before if before[n] != after[n]} == {
        "registres_maillons", "approbations", "journal", "mutations_appliquees"
    }
    assert len(after) == 49 and after["artefacts"] == []
    assert len(after["approbations"]) == len(before["approbations"]) + 1
    stockage.liberer()
    replay = appeler(capacite(), d)
    assert replay == {**first, "rejoue": True}
    assert after == fx.fx._tables()


def test_v1_apres_v2_et_append_etranger_confirme_propre_reference(monde):
    a = cfx.fx.preparer(2, prevu=False)
    other = "MAT-AUTRE-CLASSEMENT-FICTIF"
    bon = {"po_id": "PO-AUTRE-CLASSEMENT-FICTIF", "chantier_id": fx.fx.CH,
           "lignes_demandees": [{"materiau_id": other, "quantite_demandee": 100}],
           "horodatage": "2026-01-01T00:00:00Z"}
    rec = {"po_id": bon["po_id"], "chantier_id": fx.fx.CH,
           "lignes_recues": [{"materiau_id": other, "quantite_recue": 100}],
           "horodatage": "2026-01-02T00:00:00Z"}
    reception = executer_atomique(
        next(o for o in outils.outils() if o.nom == "m6_receptionner_commande"),
        {"bon_demande": bon, "reception_po": rec, "catalogue_materiaux": {
            "version": "FICTIF", "unite_monetaire": "CAD",
            "postes": {other: {"cout_unitaire": 2, "libelle": "FICTIF"}}}},
    )
    assert reception["resultat"]["accepte"]
    fx.fx._prevu(lignes=[
        {"materiau_id": fx.fx.MAT, "quantite_estimee": 40, "unite": "pi"},
        {"materiau_id": other, "quantite_estimee": 40, "unite": "pi"},
    ])
    a["formulaire"]["lignes_materiaux"][1]["materiau_id"] = other
    assert cfx.fx.executer(a)["resultat"]["accepte"]
    d = cfx.demande(a)
    cap = capacite()
    first = appeler(cap, d)
    v1 = accepter(first)
    newer = {**d, "classement_attendu": v1["reference"], "cause": "breakage"}
    second = appeler(cap, newer, meta(2))
    v2 = accepter(second)
    assert v2["reference_precedente"] == v1["reference"]
    # Autre objet réellement publié : sa position et son matériau sont relus
    # dans la charge terminale, pas déduits d'un offset de page.
    with stockage.transaction() as cnx:
        charge = stockage.codec.decoder(cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.evenement_id == d["selection"]["reference_variance"]["evenement_id"]
        )).scalar_one())
    position = next(i for i, ligne in enumerate(charge["lignes"]) if ligne["materiau"] != d["selection"]["materiau_id"])
    foreign = copy.deepcopy(d)
    foreign["selection"]["position_ligne"] = position
    foreign["selection"]["materiau_id"] = charge["lignes"][position]["materiau"]
    assert foreign["selection"] != d["selection"]
    third = appeler(cap, foreign, meta(3))
    v3 = accepter(third)
    assert v3["selection"] != v1["selection"]
    before = fx.fx._tables()
    replay = appeler(cap, d)
    assert replay == {**first, "rejoue": True}
    assert replay["resultat"]["resultat"]["reference"] == v1["reference"]
    assert before == fx.fx._tables()
    stale = appeler(cap, newer, meta(4))
    assert not stale["resultat"]["accepte"]
    assert stale["resultat"]["verdict"]["code"] == "REJ-M6-CLASSEMENT-REVISION-PERIMEE"
    after = fx.fx._tables()
    assert {n for n in before if before[n] != after[n]} == {"mutations_appliquees"}


def test_admin_retire_avant_toutes_sources_claim_et_rejeu(monde):
    d = cfx.demande(cfx.preparer())
    first = appeler(capacite(), d)
    accepter(first)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, fx.ADMIN.personne, "admin")
    _, patch = monde
    claims, business = [], []
    original = idempotence.reclamer

    def claim(*args):
        claims.append(1)
        return original(*args)

    def observe(_cnx, _cursor, statement, *_):
        if any(n in statement.lower() for n in ["registres_maillons", "evenements_sortants", "mutations_appliquees"]):
            business.append(statement)

    patch.setattr(idempotence, "reclamer", claim)
    before = fx.fx._tables()
    engine = stockage.moteur()
    event.listen(engine, "before_cursor_execute", observe)
    try:
        refused = appeler(capacite(), d)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert refused.get("erreur") == "REJ-M6-CLASSEMENT-IDENTITE-INVALIDE", refused
    assert refused.get("issue") == "inconnue" and business == claims == []
    assert before == fx.fx._tables()
    with stockage.transaction() as cnx:
        identite.ajouter_role(cnx, fx.ADMIN.personne, "admin")
    restored = fx.fx._tables()
    assert appeler(capacite(), d) == {**first, "rejoue": True}
    assert restored == fx.fx._tables()


@pytest.mark.parametrize("acteur", [
    None, fx.EMP, contexte.IdentiteAppelante("vendeur.fictif", "seller"),
    contexte.IdentiteAppelante(fx.ADMIN.personne, "admin", source="console"),
    contexte.IdentiteAppelante(fx.ADMIN.personne, "admin", source="agent"),
])
def test_autorite_invalide_aucun_claim_approbation(monde, acteur):
    d = cfx.demande(cfx.preparer())
    before = fx.fx._tables()
    r = appeler(capacite(), d, acteur=acteur)
    assert r.get("erreur") == "REJ-M6-CLASSEMENT-IDENTITE-INVALIDE", r
    assert r.get("issue") == "inconnue"
    assert before == fx.fx._tables()


def test_quota_frais_refus_certain_sans_trace_et_rejeu_inconnu(monde):
    d = cfx.demande(cfx.preparer())
    before = fx.fx._tables()
    small = appeler(capacite(800), d, meta(5))
    assert small["ok"] and not small["resultat"]["accepte"], small
    assert small["resultat"]["verdict"]["code"] == "REJ-M6-CLASSEMENT-SORTIE-TROP-VOLUMINEUSE"
    after = fx.fx._tables()
    assert {n for n in before if before[n] != after[n]} == {"mutations_appliquees"}
    first = appeler(capacite(), d)
    accepter(first)
    stable = fx.fx._tables()
    reduced = appeler(capacite(800), d)
    assert reduced.get("issue") == "inconnue" and "apercu" not in reduced, reduced
    assert stable == fx.fx._tables()
    assert appeler(capacite(), d) == {**first, "rejoue": True}
    assert stable == fx.fx._tables()


def test_source_volatile_preclaim_inconnue_puis_rejeu_original(monde):
    d = cfx.demande(cfx.preparer())
    first = appeler(capacite(), d)
    accepter(first)
    ident = d["selection"]["reference_variance"]["evenement_id"]
    with stockage.transaction() as cnx:
        original = cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.evenement_id == ident
        )).scalar_one()
        charge = stockage.codec.decoder(original)
        charge["lignes"][0]["quantite_reelle"] = "999"
        cnx.execute(update(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == ident)
                    .values(charge=stockage.codec.encoder(charge)))
    before = fx.fx._tables()
    refused = appeler(capacite(), d)
    assert refused.get("issue") == "inconnue" and refused.get("erreur", "").startswith("REJ-M6-CLASSEMENT-"), refused
    assert before == fx.fx._tables()
    with stockage.transaction() as cnx:
        cnx.execute(update(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == ident)
                    .values(charge=original))
    stable = fx.fx._tables()
    assert appeler(capacite(), d) == {**first, "rejoue": True}
    assert stable == fx.fx._tables()


def test_rejeu_ne_lit_pas_cas_apres_association_photo(monde):
    a = cfx.fx.preparer(2)
    a["preuves_lignes"][0]["photos"] = [cfx.fx.deposer()]
    assert cfx.fx.executer(a)["resultat"]["accepte"]
    with stockage.transaction():
        p = list(stockage.maillons("m06-material-control", "preuves_pertes_bris"))[0]
    piece = {"reference_mouvement": p["reference_mouvement"],
             "reference_preuve": outils.preuves_pertes_bris_appareil.reference("preuves_pertes_bris", p),
             "positions_photos": [0]}
    d = cfx.demande(a, references_pieces=[piece])
    first = appeler(capacite(), d)
    accepter(first)
    _, patch = monde
    calls = []

    def missing(*_):
        calls.append(1)
        raise ValueError("FICTIF CAS disparu")

    patch.setattr(fichiers, "lire_blob_verifie", missing)
    before = fx.fx._tables()
    assert appeler(capacite(), d) == {**first, "rejoue": True}
    assert calls == [] and before == fx.fx._tables()


@pytest.mark.parametrize("genre", [RuntimeError, ValueError, TypeError, KeyError, stockage.EcritureConcurrente])
def test_panne_post_append_annule_claim_classement_et_trace(monde, genre):
    d = cfx.demande(cfx.preparer())
    _, patch = monde
    original = outils._ajouter_classement_variance

    def fail(m):
        original(m)
        raise genre("CANARY-PANNE-FICTIVE")

    patch.setattr(outils, "_ajouter_classement_variance", fail)
    before = fx.fx._tables()
    with pytest.raises(RuntimeError):
        appeler(capacite(), d)
    assert before == fx.fx._tables()
    patch.setattr(outils, "_ajouter_classement_variance", original)
    first = appeler(capacite(), d)
    accepter(first)
    after = fx.fx._tables()
    assert appeler(capacite(), d) == {**first, "rejoue": True}
    assert after == fx.fx._tables()


@pytest.mark.parametrize("genre", [RuntimeError, ValueError, TypeError, KeyError])
def test_panne_journal_trace_annule_tout_et_meme_uuid_reessaie(monde, genre):
    d = cfx.demande(cfx.preparer())
    _, patch = monde
    original = approbations.journaliser

    def fail(*_, **__):
        raise genre("CANARY-JOURNAL-FICTIF")

    patch.setattr(approbations, "journaliser", fail)
    before = fx.fx._tables()
    with pytest.raises(genre):
        appeler(capacite(), d)
    assert before == fx.fx._tables()
    patch.setattr(approbations, "journaliser", original)
    accepter(appeler(capacite(), d))


def test_refus_post_append_savepoint_pas_trace_et_refus_rejouable(monde):
    d = cfx.demande(cfx.preparer())
    _, patch = monde
    c = outils.classement_variance_appareil
    original = c.verifier_borne
    calls = []

    def reject_after(*a, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise c.Refus("SORTIE-TROP-VOLUMINEUSE")
        return original(*a, **kw)

    patch.setattr(c, "verifier_borne", reject_after)
    before = fx.fx._tables()
    first = appeler(capacite(), d)
    assert first["ok"] and not first["resultat"]["accepte"], first
    after = fx.fx._tables()
    assert calls == [1, 1]
    assert {n for n in before if before[n] != after[n]} == {"mutations_appliquees"}
    assert appeler(capacite(), d) == {**first, "rejoue": True}
    assert calls == [1, 1] and after == fx.fx._tables()


def test_cap_backstop_technique_ne_scelle_pas_append_hors_borne(monde):
    d = cfx.demande(cfx.preparer())
    _, patch = monde
    # Injection explicite d'une panne du pré/postflight backend : Cap protège
    # encore l'append, sa trace et la réclamation extérieure entière.
    patch.setattr(outils.classement_variance_appareil, "verifier_borne", lambda *_a, **_kw: None)
    before = fx.fx._tables()
    with pytest.raises(RuntimeError, match="borne atomique"):
        appeler(capacite(800), d)
    assert before == fx.fx._tables()


@pytest.mark.parametrize("nom", LECTURES)
def test_lecture_actuelle_role_retire_avant_sources_et_claim(monde, nom):
    a = cfx.preparer()
    args = {"wct_id": a["wct_id"]} if nom == LECTURES[0] else {"selection": cfx.selection_sql(a)}
    args |= {"decalage": 0, "limite": 8}
    cap = capacite()
    with contexte.appele_par_appareil(fx.ADMIN):
        first = cap.appeler(nom, args)
    accepter(first)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, fx.ADMIN.personne, "admin")
    _, patch = monde
    calls = []
    original = outils._sources_classement_variance

    def observe(*a):
        calls.append(1)
        return original(*a)

    patch.setattr(outils, "_sources_classement_variance", observe)
    before = fx.fx._tables()
    with contexte.appele_par_appareil(fx.ADMIN):
        refused = cap.appeler(nom, args)
    assert refused.get("erreur") == "REJ-M6-CLASSEMENT-IDENTITE-INVALIDE"
    assert calls == [] and before == fx.fx._tables()


def test_conflit_et_ack_cache_altere_sans_nouvel_effet(monde):
    d = cfx.demande(cfx.preparer())
    first = appeler(capacite(), d)
    accepter(first)
    before = fx.fx._tables()
    conflict = appeler(capacite(), {**d, "cause": "breakage"})
    assert conflict.get("erreur") == "mutation_conflit", conflict
    assert before == fx.fx._tables()
    bad = copy.deepcopy(first)
    bad.pop("rejoue")
    bad["resultat"]["resultat"]["reference"]["hash_maillon"] = "0" * 64
    with stockage.transaction() as cnx:
        cnx.execute(update(MUTATIONS_APPLIQUEES).where(MUTATIONS_APPLIQUEES.c.cle_idempotence == META.cle)
                    .values(reponse=stockage.codec.encoder(bad)))
    altered = fx.fx._tables()
    refused = appeler(capacite(), d)
    assert refused.get("issue") == "inconnue" and refused.get("erreur") == "REJ-M6-CLASSEMENT-REJEU-INCOHERENT", refused
    assert altered == fx.fx._tables()


def test_deux_corrections_concurrentes_attendu_v1_une_seule_trace(monde):
    d = cfx.demande(cfx.preparer())
    v1 = accepter(appeler(capacite(), d))
    barrier = Barrier(2)
    before = fx.fx._tables()

    def corriger(k, cause):
        arguments = {**d, "cause": cause, "classement_attendu": v1["reference"]}
        barrier.wait(timeout=5)
        return appeler(capacite(), arguments, meta(k))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(corriger, 31, "breakage"), executor.submit(corriger, 32, "field_change")]
        answers = [future.result(timeout=10) for future in futures]
    assert sum(r["resultat"]["accepte"] is True for r in answers) == 1
    rejected = next(r for r in answers if not r["resultat"]["accepte"])
    assert rejected["resultat"]["verdict"]["code"] == "REJ-M6-CLASSEMENT-REVISION-PERIMEE"
    after = fx.fx._tables()
    assert len(after["registres_maillons"]) == len(before["registres_maillons"]) + 1
    assert len(after["approbations"]) == len(before["approbations"]) + 1
    assert len(after["journal"]) == len(before["journal"]) + 1
    assert len(after["mutations_appliquees"]) == len(before["mutations_appliquees"]) + 2
    assert after["artefacts"] == []


@pytest.mark.parametrize("nom", (MUTATION, *LECTURES))
def test_sortie_entiere_aucun_artefact(monde, nom):
    before = fx.fx._tables()
    r = capacite(800)._tronquer({"ok": True, "resultat": {"fictif": "é" * 900}}, nom)
    assert not r["ok"] and "apercu" not in r and "tronque" not in r, r
    if nom == MUTATION:
        assert r.get("issue") == "inconnue", r
    else:
        assert r.get("erreur") == "REJ-M6-CLASSEMENT-SORTIE-TROP-VOLUMINEUSE", r
    assert before == fx.fx._tables()
