"""Fictif : frontières Cap/DEVICE/SQLite, approbation humaine et idempotence réelle."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from m6_material_control import outils

from opsys import contexte, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES

path = (
    Path(__file__).resolve().parents[1] / "departments/m06-material-control/tests/test_preuves_pertes_bris_appareil.py"
)
spec = importlib.util.spec_from_file_location("fixture_cap_preuves", path)
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)
monde = fx.monde
KEY = "4612b2de-a1c4-4a68-a044-e0ab685025ad"
META = idempotence.Meta(cle=KEY, appareil="APP-PREUVES-FICTIF", horodatage_appareil=fx.fx.DATE)


def appeler(cap, a, actor=fx.EMP):
    with contexte.appele_par_appareil(actor):
        return cap.appeler(fx.NOM, a, meta=META)


def capacite(limite=6000):
    return Capacites(charger_departements(), stockage.transaction, limite_sortie=limite)


def test_cap_quota800_preflight_aucun_stock_cas_artefact(monde):
    _, patch = monde
    a = fx.preparer()
    a["preuves_lignes"][0]["photos"] = [fx.deposer()]
    calls = []
    original = outils.fichiers.lire_blob_verifie

    def observe(*args):
        calls.append(args)
        return original(*args)

    patch.setattr(outils.fichiers, "lire_blob_verifie", observe)
    before = fx.fx._tables()
    r = appeler(capacite(800), a)
    after = fx.fx._tables()
    assert r["ok"] and not r["resultat"]["accepte"], r
    assert r["resultat"]["verdict"]["code"] == "REJ-M6-PREUVES-SORTIE-TROP-VOLUMINEUSE"
    assert calls == [] and before[REGISTRES.name] == after[REGISTRES.name] and after["artefacts"] == []
    assert set(n for n in before if before[n] != after[n]) <= {"mutations_appliquees"}


def test_role_retire_avant_rejeu_ne_lit_plus_wct_claim(monde):
    _, patch = monde
    a = fx.preparer()
    cap = capacite()
    r = appeler(cap, a)
    assert r["ok"] and r["resultat"]["accepte"], r
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, fx.EMP.personne, "employee")
    calls = []
    patch.setattr(outils, "_wct_publie_par_m4", lambda *a: calls.append(a))
    old = fx.fx._tables()
    refusal = appeler(cap, a)
    assert not refusal["ok"] and refusal["erreur"] == "REJ-M6-PREUVES-IDENTITE-INVALIDE", refusal
    assert calls == [] and old == fx.fx._tables()


def test_employee_foreign_refuse_avant_claim_approval(monde):
    a = fx.preparer()
    old = fx.fx._tables()
    r = appeler(capacite(), a, contexte.IdentiteAppelante("autre.fictif", "employee"))
    assert not r["ok"] and r["erreur"] == "REJ-M6-PREUVES-INTERVENTION-NON-ASSIGNEE", r
    assert old == fx.fx._tables()


def test_rejeu_quota_reduit_issue_inconnue_meme_uuid(monde):
    a = fx.preparer()
    cap = capacite()
    r = appeler(cap, a)
    assert r["ok"] and r["resultat"]["accepte"]
    old = fx.fx._tables()
    lower = appeler(capacite(800), a)
    assert not lower["ok"] and lower["erreur"] == "confirmation_transport_indisponible"
    assert lower["issue"] == "inconnue" and "apercu" not in lower
    assert old == fx.fx._tables()
    again = appeler(cap, a)
    assert again["rejoue"] and again["resultat"] == r["resultat"] and old == fx.fx._tables()


def test_panne_technique_post_writer_annule_claim_et_metier(monde):
    _, patch = monde
    a = fx.preparer()

    def failure(_):
        raise RuntimeError("CANARY-PANNE-FICTIVE")

    patch.setattr(outils, "_ajouter_preuve", failure)
    before = fx.fx._tables()
    with pytest.raises(RuntimeError, match="échec technique"):
        appeler(capacite(), a)
    assert before == fx.fx._tables()


def test_refus_postwriter_savepoint_annule_cascades(monde):
    _, patch = monde
    from m6_material_control import preuves_pertes_bris_appareil as p

    a = fx.preparer()

    def reject(*_):
        raise p.Refus("LIAISON-INCOHERENTE")

    patch.setattr(p, "lier_ajouts", reject)
    before = fx.fx._tables()
    r = appeler(capacite(), a)
    after = fx.fx._tables()
    assert r["ok"] and r["resultat"]["verdict"]["code"] == "REJ-M6-PREUVES-LIAISON-INCOHERENTE"
    assert (
        before[REGISTRES.name] == after[REGISTRES.name]
        and before[EVENEMENTS_SORTANTS.name] == after[EVENEMENTS_SORTANTS.name]
    )
    assert set(n for n in before if before[n] != after[n]) <= {"mutations_appliquees"}


def test_conflit_et_close_reopen_sans_double_effet(monde):
    a = fx.preparer()
    cap = capacite()
    r = appeler(cap, a)
    assert r["ok"] and r["resultat"]["accepte"]
    old = fx.fx._tables()
    stocking = dict(a, preuves_lignes=[dict(a["preuves_lignes"][0], note="FICTIF autre note"), a["preuves_lignes"][1]])
    conflict = appeler(cap, stocking)
    assert conflict["erreur"] == "mutation_conflit" and old == fx.fx._tables()
    stockage.liberer()
    replay = appeler(capacite(), a)
    assert replay["rejoue"] and replay["resultat"] == r["resultat"] and old == fx.fx._tables()


def test_panne_technique_meme_uuid_reessaie_une_seule_ecriture(monde):
    _, patch = monde
    a = fx.preparer(1)
    original = outils._ajouter_preuve

    def panne(_):
        raise RuntimeError("FICTIF-panne-append")

    patch.setattr(outils, "_ajouter_preuve", panne)
    cap = capacite()
    before = fx.fx._tables()
    with pytest.raises(RuntimeError):
        appeler(cap, a)
    assert before == fx.fx._tables()
    patch.setattr(outils, "_ajouter_preuve", original)
    accepted = appeler(cap, a)
    assert accepted["resultat"]["accepte"] and not accepted["rejoue"]
    final = fx.fx._tables()
    replay = appeler(cap, a)
    assert replay["rejoue"] and replay["resultat"] == accepted["resultat"] and final == fx.fx._tables()


def test_borne_prevu10001_avant_claim(monde):
    _, patch = monde
    a = fx.preparer(1)
    patch.setattr(outils, "_besoins_prevus_de_l_appel", lambda _: [{"devis_id": "FICTIF"}] * 10001)
    before = fx.fx._tables()
    r = appeler(capacite(), a)
    assert not r["ok"] and r["erreur"] == "REJ-M6-PREUVES-BORNE-SOURCES"
    assert before == fx.fx._tables()


def test_borne_source_copiee_agregee_m4_m6_avant_effet(monde):
    _, patch = monde
    a = fx.preparer(1)
    actual = outils._besoins_prevus_de_l_appel

    # La copie du prévu seule reste sous10000 ; M4+WCT+principal la font dépasser.
    def copies(_):
        return list(actual(None)) + [{"devis_id": "FICTIF-ETRANGER"}] * 9997

    patch.setattr(outils, "_besoins_prevus_de_l_appel", copies)
    before = fx.fx._tables()
    r = appeler(capacite(), a)
    assert not r["ok"] and r["erreur"] == "REJ-M6-PREUVES-BORNE-SOURCES"
    assert before == fx.fx._tables()


def test_lecture_t0_avec_meta_mutation_refusee_sans_recu(monde):
    a = fx.preparer(1)
    cap = capacite()
    before = fx.fx._tables()
    with contexte.appele_par_appareil(fx.ADMIN):
        r = cap.appeler(fx.LECTURE, {"wct_id": a["wct_id"], "decalage": 0, "limite": 8}, meta=META)
    assert not r["ok"] and r["erreur"] == "idempotence_hors_portee_lecture", r
    assert before == fx.fx._tables()


@pytest.mark.parametrize("genre", [ValueError, TypeError, KeyError])
def test_exception_technique_type_metier_postwriter_ne_cache_pas_claim(monde, genre):
    _, patch = monde
    a = fx.preparer(1)

    def failure(_):
        raise genre("CANARY-TECHNIQUE-FICTIVE")

    patch.setattr(outils, "_ajouter_preuve", failure)
    before = fx.fx._tables()
    with pytest.raises(RuntimeError, match="échec technique"):
        appeler(capacite(), a)
    assert before == fx.fx._tables()


def test_refus_schema_preuves_ne_retransmet_pas_note_brute(monde):
    a = fx.preparer(1)
    a["CANARY-NOTE-FICTIVE"] = "n" * 501
    before = fx.fx._tables()
    r = appeler(capacite(), a)
    assert not r["ok"] and r["erreur"] == "arguments_invalides", r
    assert "CANARY" not in str(r)
    after = fx.fx._tables()
    assert set(n for n in before if before[n] != after[n]) <= {"mutations_appliquees"}


def test_cle_commise_body_malforme_conflit_pas_nouveau_refus(monde):
    a = fx.preparer(1)
    cap = capacite()
    r = appeler(cap, a)
    assert r["resultat"]["accepte"]
    autre = dict(
        a, formulaire=dict(a["formulaire"], lignes_materiaux=[dict(a["formulaire"]["lignes_materiaux"][0], quantite=0)])
    )
    old = fx.fx._tables()
    conflict = appeler(cap, autre)
    assert conflict["erreur"] == "mutation_conflit", conflict
    assert old == fx.fx._tables()
