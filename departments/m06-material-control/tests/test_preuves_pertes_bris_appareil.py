"""Fictif : vraie complétion M4, réception M6, CAS et SQLite ; pas HTTP/téléphone."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import importlib.util
from pathlib import Path

import pytest
from m6_material_control import outils

from opsys import contexte, fichiers, stockage
from opsys.outils import Autonomie, Niveau, executer_atomique

NOM = "m6_declarer_materiaux_avec_preuves_appareil"
LECTURE = "m6_lire_preuves_pertes_wct_appareil"
FICTIF = True
p = Path(__file__).with_name("test_contexte_materiaux_appareil.py")
spec = importlib.util.spec_from_file_location("fixture_preuves_m6", p)
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)
monde = fx.monde
EMP, ADMIN = fx.EMP, fx.ADMIN


def outil(nom=NOM):
    o = next((o for o in outils.outils() if o.nom == nom), None)
    assert o is not None, "nouvelle façade preuves absente"
    return o


def deposer(data=b"\x89PNG\r\n\x1a\nFICTIF-preuves"):
    h = hashlib.sha256(data).hexdigest()
    with stockage.transaction() as cnx:
        r = fichiers.deposer_bloc(cnx, h, len(data), "image/png", 0, 1, base64.b64encode(data).decode())
        assert r.accepte
    return fichiers.reference_pour(h)


def preparer(n=2, prevu=True):
    i, w = fx._seed(fx.DEVI)
    # Livraison réelle au consommateur enregistré de M6 : les tests de rollback
    # doivent annuler une nouvelle publication de variance, pas un appel sans WCT reçu.
    from opsys import evenements
    with stockage.transaction():
        charge = evenements.charge_publiee("m4.travaux_termines", w)
        assert charge is not None
        reception = outils.consommateurs()["m4.travaux_termines"](charge)
        assert reception["statut_variance"] == "prevu_absent"
    if prevu:
        fx._prevu()
    bon = {
        "po_id": "PO-PREUVES-FICTIF",
        "chantier_id": fx.CH,
        "lignes_demandees": [{"materiau_id": fx.MAT, "quantite_demandee": 100}],
        "horodatage": "2026-01-01T00:00:00Z",
    }
    rec = {
        "po_id": bon["po_id"],
        "chantier_id": fx.CH,
        "lignes_recues": [{"materiau_id": fx.MAT, "quantite_recue": 100}],
        "horodatage": "2026-01-02T00:00:00Z",
    }
    r = executer_atomique(
        next(o for o in outils.outils() if o.nom == "m6_receptionner_commande"),
        {
            "bon_demande": bon,
            "reception_po": rec,
            "catalogue_materiaux": {
                "version": "FICTIF",
                "unite_monetaire": "CAD",
                "postes": {fx.MAT: {"cout_unitaire": 2, "libelle": "FICTIF"}},
            },
        },
    )
    assert r["ok"] and r["resultat"]["accepte"], r
    lignes = [{"type_ligne": "perte", "materiau_id": fx.MAT, "quantite": 1, "unite": "pi"} for _ in range(n)]
    a = {
        "wct_id": w,
        "formulaire": {"wct_id": w, "intervention_id": i, "chantier_id": fx.CH, "lignes_materiaux": lignes},
        "preuves_lignes": [{"position_ligne": k, "note": "FICTIF note de perte", "photos": []} for k in range(n)],
    }
    return a


def executer(args, actor=EMP):
    h = contexte.HorodatageAppareil(
        "APP-PREUVES-FICTIF", dt.datetime.fromisoformat(fx.DATE), dt.datetime.fromisoformat("2026-10-08T00:00:00+00:00")
    )
    with contexte.appele_par_appareil(actor), contexte.receptionne_de(h):
        return executer_atomique(outil(), args)


def test_declarations_fermees_et_roles():
    o = outil()
    assert o.autonomie is Autonomie.T1 and o.niveau_effectif is Niveau.N3
    assert o.roles_appareil == frozenset({"employee", "admin"})
    assert set(o.parametres["required"]) == {"wct_id", "formulaire", "preuves_lignes"}
    assert o.parametres["additionalProperties"] is False
    lecteur = outil(LECTURE)
    assert lecteur.autonomie is Autonomie.T0 and lecteur.niveau_effectif is Niveau.N0
    assert lecteur.roles_appareil == frozenset({"admin"})


def test_deux_pertes_identiques_references_reelles_distinctes(monde):
    a = preparer()
    before = fx._tables()
    r = executer(a)
    assert r["ok"] and r["resultat"]["accepte"], r
    ack = r["resultat"]
    assert ack["resultat"]["lignes_declarees"] == a["formulaire"]["lignes_materiaux"]
    with stockage.transaction():
        mov = list(stockage.maillons("m06-material-control", "principal"))
        proofs = list(stockage.maillons("m06-material-control", "preuves_pertes_bris"))
    refs = ack["resultat"]["preuves"]
    assert len(refs) == len(proofs) == 2
    assert refs[0]["reference_mouvement"]["index"] != refs[1]["reference_mouvement"]["index"]
    for k, ref in enumerate(refs):
        assert ref["position_ligne"] == k
        assert ref["reference_mouvement"]["hash_maillon"] == mov[ref["reference_mouvement"]["index"]]["hash_maillon"]
        assert ref["reference_preuve"]["hash_maillon"] == proofs[k]["hash_maillon"]
    after = fx._tables()
    assert len(before) == len(after) == 49 and after["artefacts"] == []
    assert "cout_unitaire" not in str(ack) and "Personne" not in str(ack)


def test_derniere_photo_absente_aucun_metier(monde):
    a = preparer()
    a["preuves_lignes"][0]["photos"] = [deposer()]
    a["preuves_lignes"][1]["photos"] = ["fichier:sha256:" + "0" * 64]
    before = fx._tables()
    r = executer(a)
    assert r["ok"] and not r["resultat"]["accepte"], r
    assert r["resultat"]["verdict"]["code"] == "REJ-M6-PREUVES-PHOTO-INDISPONIBLE"
    assert before == fx._tables()


def lire(a, actor=ADMIN, **page):
    before = fx._tables()
    with contexte.appele_par_appareil(actor):
        r = executer_atomique(outil(LECTURE), {"wct_id": a["wct_id"], "decalage": 0, "limite": 8, **page})
    assert before == fx._tables() and len(before) == 49
    return r


def test_lecture_notes_photos_et_page_courante(monde):
    a = preparer()
    a["preuves_lignes"][0]["photos"] = [deposer()]
    r = executer(a)
    assert r["resultat"]["accepte"]
    page = lire(a, limite=1)["resultat"]
    assert page["total"] == 2 and page["decalage_suivant"] == 1
    item = page["pertes_bris"][0]
    assert item["unite"] is None and item["quantite"] == "-1"
    assert item["preuve"]["etat"] == "photos_declarees"
    assert item["preuve"]["photos"][0]["etat_actuel"] == "disponible"
    second = lire(a, decalage=1, limite=1)["resultat"]
    assert second["pertes_bris"][0]["preuve"]["etat"] == "note_seule"
    assert second["decalage_suivant"] is None
    assert lire(a, decalage=2)["resultat"]["pertes_bris"] == []


def test_helper_initial_un_cas_revalidation_zero_cas_et_retrait_role(monde):
    _, patch = monde
    from opsys import identite

    a = preparer(1)
    a["preuves_lignes"][0]["photos"] = [deposer()]
    r = executer(a)
    ref = r["resultat"]["resultat"]["preuves"][0]["reference_preuve"]
    sel = {"index": ref["index"], "hash_maillon": ref["hash_maillon"]}
    calls = []
    original = fichiers.lire_blob_verifie

    def observe(*args):
        calls.append(args)
        return original(*args)

    patch.setattr(fichiers, "lire_blob_verifie", observe)
    old = fx._tables()
    with contexte.appele_par_appareil(ADMIN):
        initial = outils.autoriser_et_lire_photo(a["wct_id"], sel, 0)
        reval = outils.revalider_autorite_photo(a["wct_id"], sel, 0)
    assert initial["accepte"] and isinstance(initial["octets"], bytes)
    assert reval["accepte"] and "octets" not in reval and reval["autorite"] == initial["autorite"]
    assert len(calls) == 1 and old == fx._tables()
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN.personne, "admin")
    reads = []
    patch.setattr(outils, "_snapshots_preuves", lambda: reads.append(1))
    old = fx._tables()
    with contexte.appele_par_appareil(ADMIN):
        refused = outils.revalider_autorite_photo(a["wct_id"], sel, 0)
    assert refused["verdict"]["code"] == "REJ-M6-PREUVES-IDENTITE-INVALIDE"
    assert len(calls) == 1 and reads == [] and old == fx._tables()


def test_photo_corrompue_actuellement_indisponible_sans_perdre_note(monde):
    from sqlalchemy import update

    from opsys.stockage.schema import FICHIERS_BLOCS

    a = preparer(1)
    refcas = deposer()
    a["preuves_lignes"][0]["photos"] = [refcas]
    r = executer(a)
    assert r["resultat"]["accepte"]
    with stockage.transaction() as cnx:
        cnx.execute(
            update(FICHIERS_BLOCS)
            .where(FICHIERS_BLOCS.c.empreinte_sha256 == fichiers.empreinte_depuis_reference(refcas))
            .values(contenu_base64=base64.b64encode(b"CORROMPU-FICTIF").decode())
        )
    vue = lire(a)["resultat"]["pertes_bris"][0]["preuve"]
    assert vue["note"] == a["preuves_lignes"][0]["note"] and vue["photos"][0]["etat_actuel"] == "indisponible"
    sel = {k: vue["reference"][k] for k in ("index", "hash_maillon")}
    with contexte.appele_par_appareil(ADMIN):
        refusal = outils.autoriser_et_lire_photo(a["wct_id"], sel, 0)
    assert refusal["verdict"]["code"] == "REJ-M6-PREUVES-PHOTO-INDISPONIBLE"


def test_ancien_mouvement_sans_preuve_inconnu_non_zero(monde):
    a = preparer(1)
    with contexte.appele_par_appareil(EMP):
        r = executer_atomique(
            next(o for o in outils.outils() if o.nom == "m6_declarer_materiaux_utilises"),
            {"wct_id": a["wct_id"], "formulaire": a["formulaire"]},
        )
    assert r["resultat"]["accepte"]
    vue = lire(a)["resultat"]["pertes_bris"][0]["preuve"]
    assert vue == {
        "etat": "absente",
        "reference": None,
        "position_ligne": None,
        "note": None,
        "enregistre_le": None,
        "horodatage_appareil_declare": None,
        "photos": [],
    }


@pytest.mark.parametrize("acteur", [EMP, None, contexte.IdentiteAppelante("vendeur.fictif", "seller")])
def test_lecture_admin_actuel_uniquement(monde, acteur):
    a = preparer(1)
    r = lire(a, actor=acteur)
    assert r["resultat"]["verdict"]["code"] == "REJ-M6-PREUVES-IDENTITE-INVALIDE"


def test_borne5400_ack_entier_avant_cas_stock(monde):
    _, patch = monde
    a = preparer(8)
    for ligne in a["formulaire"]["lignes_materiaux"]:
        ligne["unite"] = "u" * 256
    a["preuves_lignes"][0]["photos"] = [deposer()]
    calls = []
    original = outils._photo_verifiee

    def observe(ref):
        calls.append(ref)
        return original(ref)

    patch.setattr(outils, "_photo_verifiee", observe)
    old = fx._tables()
    r = executer(a)
    assert r["resultat"]["verdict"]["code"] == "REJ-M6-PREUVES-SORTIE-TROP-VOLUMINEUSE", r
    assert calls == [] and old == fx._tables()


def test_postflight_refus_quota_apres_writer_annule_tout(monde):
    _, patch = monde
    from m6_material_control import preuves_pertes_bris_appareil as p

    a = preparer(1)
    calls = []
    original = outils._postflight_preuves

    def postflight(ack):
        calls.append(ack)
        if len(calls) == 2:
            raise p.Refus("SORTIE-TROP-VOLUMINEUSE")
        return original(ack)

    patch.setattr(outils, "_postflight_preuves", postflight)
    old = fx._tables()
    r = executer(a)
    assert len(calls) == 2 and r["resultat"]["verdict"]["code"] == "REJ-M6-PREUVES-SORTIE-TROP-VOLUMINEUSE"
    assert old == fx._tables()


def test_borne_sources10000_apres_copies():
    from m6_material_control import preuves_pertes_bris_appareil as p

    with pytest.raises(p.Refus) as exc:
        p.valider_snapshots([None] * 10001, [])
    assert exc.value.suffixe == "BORNE-SOURCES"


def test_source_m4_malformee_refus_nominal_sans_canary(monde):
    from sqlalchemy import update

    from opsys.stockage.schema import REGISTRES

    a = preparer(1)
    with stockage.transaction() as cnx:
        cnx.execute(
            update(REGISTRES)
            .where(REGISTRES.c.departement == "m04-field-ops", REGISTRES.c.rang == 0)
            .values(maillon="CANARY-SOURCE-M4-PRIVEE-FICTIVE")
        )
    before = fx._tables()
    r = executer(a)
    assert r["ok"] and r["resultat"]["verdict"]["code"] == "REJ-M6-PREUVES-SOURCE-INVALIDE", r
    assert "CANARY" not in str(r) and before == fx._tables()


@pytest.mark.parametrize("quantite", [2**53, 1e20])
def test_nombre_ack_hors_codec_mobile_refuse_avant_stock(monde, quantite):
    a = preparer(1)
    a["formulaire"]["lignes_materiaux"][0]["quantite"] = quantite
    before = fx._tables()
    r = executer(a)
    assert r["ok"] and r["resultat"]["verdict"]["code"] == "REJ-M6-PREUVES-PROJECTION-INVALIDE", r
    assert before == fx._tables()


def test_revalidation_source_chantier_reaffectee_stop_sans_cas(monde):
    _, patch = monde
    a = preparer(1, prevu=False)
    a["preuves_lignes"][0]["photos"] = [deposer()]
    r = executer(a, actor=ADMIN)
    ref = r["resultat"]["resultat"]["preuves"][0]["reference_preuve"]
    sel = {k: ref[k] for k in ("index", "hash_maillon")}
    with contexte.appele_par_appareil(ADMIN):
        initial = outils.autoriser_et_lire_photo(a["wct_id"], sel, 0)
    assert initial["accepte"]
    fx._prevu(chantier="CHANTIER-REAFFECTE-FICTIF")
    calls = []
    patch.setattr(fichiers, "lire_blob_verifie", lambda *a: calls.append(a))
    before = fx._tables()
    with contexte.appele_par_appareil(ADMIN):
        refused = outils.revalider_autorite_photo(a["wct_id"], sel, 0)
    assert refused["verdict"]["code"] == "REJ-M6-PREUVES-LIAISON-INCOHERENTE", refused
    assert calls == [] and before == fx._tables()


def test_quantite_max_safe_positive_et_perte_negative_native(monde):
    a = preparer(1)
    a["formulaire"]["lignes_materiaux"][0]["quantite"] = 2**53 - 1
    r = executer(a)
    assert r["ok"] and r["resultat"]["accepte"], r
    assert r["resultat"]["resultat"]["lignes_declarees"][0]["quantite"] == 2**53 - 1
    with stockage.transaction():
        m = list(stockage.maillons("m06-material-control", "principal"))[-1]
    assert m["quantite"] == -(2**53 - 1)


def test_quantite_negative_formulaire_historique_refusee(monde):
    a = preparer(1)
    a["formulaire"]["lignes_materiaux"][0]["quantite"] = -(2**53 - 1)
    before = fx._tables()
    r = executer(a)
    assert not r["resultat"]["accepte"] and before == fx._tables()


@pytest.mark.parametrize("nom", ["autoriser_et_lire_photo", "revalider_autorite_photo"])
def test_helper_factory_non_canonique_et_transaction_ancienne_refusees(monde, nom):
    from contextlib import contextmanager

    _, patch = monde
    calls = []
    patch.setattr(outils, "_selection_photo", lambda *args: calls.append(args))
    fn = getattr(outils, nom)

    @contextmanager
    def mauvaise():
        with stockage.moteur().begin() as cnx:
            yield cnx

    with contexte.appele_par_appareil(ADMIN):
        with pytest.raises(RuntimeError, match="connexion photo non canonique"):
            fn("WCT-FICTIF", {"index": 0, "hash_maillon": "0" * 64}, 0, cnx_factory=mauvaise)
        with stockage.transaction(), pytest.raises(RuntimeError, match="transaction fraîche"):
            fn("WCT-FICTIF", {"index": 0, "hash_maillon": "0" * 64}, 0)
    assert calls == []
