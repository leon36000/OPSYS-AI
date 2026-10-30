"""M9.3 — m9_rapprocher_metriques sur le vrai M8 (registre de définitions durable, mesures d'un chantier) (fictif)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from m8_analytics import registre_metriques

from opsys import stockage

_TESTS = Path(__file__).resolve().parent


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location(nom, _TESTS / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


H = _charger("m9_producteurs_b")
FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"
M8 = "m08-analytics"


def _recu(n: int) -> str:
    return f"2026-10-28T12:00:{n:02d}Z"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    H.installer_base(tmp_path, monkeypatch)
    H.declarer_m5(tmp_path, monkeypatch)
    H.alimenter_m8()
    yield H.capacites(H.M8)
    H.desinstaller_base()


def _definir(metric_id, unite):
    with stockage.transaction():
        verdict = registre_metriques.enregistrer_definition(
            {
                "metric_id": metric_id,
                "departement_proprietaire": M8,
                "unite": unite,
                "source": "m8_lire_mesures_chantier",
                "fraicheur_attendue_jours": 30,
                "regles_qualite": {"plage_min": None, "plage_max": None},
            },
            stockage.maillons(M8, "definitions_metriques"),
        )
    assert verdict["enregistree"] is True, verdict


def _appel(cap, nom, arguments, identite=H.ADMIN):
    if identite is None:
        return cap.appeler(nom, arguments)
    with H.contexte.appele_par_appareil(identite):
        return cap.appeler(nom, arguments)


def _rapprocher(cap, connaissance=CONNAISSANCE, identite=H.ADMIN):
    return _appel(cap, "m9_rapprocher_metriques", {"connaissance": connaissance}, identite)


def _capturer_mesures(cap, n):
    reponse = H.capturer(cap, H.ADMIN, "m8.mesures_chantier", {"wct_id": H.WCT_ID}, _recu(n))
    assert reponse["ok"] is True and reponse["resultat"]["capture"]["verdict"] == "ACCEPTEE", reponse
    return reponse["resultat"]["capture"]


def _capturer_registre(cap, n):
    reponse = H.capturer(cap, H.ADMIN, "m8.definitions_metriques", {}, _recu(n))
    assert reponse["ok"] is True and reponse["resultat"]["capture"]["verdict"] == "ACCEPTEE", reponse
    assert reponse["resultat"]["capture"]["complete"] is True
    return reponse["resultat"]["capture"]


def test_sans_capture_du_registre_le_rapprochement_est_refuse(monde):
    _capturer_mesures(monde, 1)
    reponse = _rapprocher(monde)
    assert reponse["ok"] is False or reponse["resultat"].get("accepte") is False
    assert "REJ-SEMANTIQUE-REGISTRE-ABSENT" in json.dumps(reponse)


def test_mesures_reelles_face_au_registre_reel(monde):
    mesures = _capturer_mesures(monde, 1)
    page = H.page(mesures["index"])
    par_metrique = {m["metric_id"]: m for m in H.valeurs(page, "resultat.mesures[*]")}
    assert par_metrique["m8_marge_reelle_cad"]["valeur"] == "114.00"
    unite_marge = par_metrique["m8_marge_reelle_cad"]["unite"]
    _definir("m8_marge_reelle_cad", unite_marge)
    _definir("m8_marge_prevue_cad", "minutes")  # unité volontairement divergente de la mesure réelle
    registre = _capturer_registre(monde, 2)
    reponse = _rapprocher(monde)
    assert reponse["ok"] is True, reponse
    res = reponse["resultat"]
    assert res["accepte"] is True and res["definitions_connues"] == 2 and res["registre_capture"] == [registre["index"]]
    assert res["prochain_depart"] is None and sum(res["statuts"].values()) == res["total_observations"]
    statuts = {o["metric_id"]: o["statut"] for o in res["observations"]}
    # L'empreinte de définition portée par la mesure (64 hexadécimaux) et la version entière du registre ne sont pas
    # reliées : M9 ne dit ni « périmée » ni « compatible ». Les métriques absentes du registre n'ont pas de définition.
    assert statuts["m8_marge_reelle_cad"] == "VERSION_NON_COMPARABLE"
    assert statuts["m8_marge_prevue_cad"] == "UNITE_DIVERGENTE"
    assert statuts["m8_ecart_duree_minutes"] == "SANS_DEFINITION"
    assert res["comparables_ensemble"] == 0 and res["agregable"] is False
    assert next(o for o in res["observations"] if o["metric_id"] == "m8_marge_reelle_cad")["valeur"] == "114.00"
    assert all(o["source"].startswith("m8.mesures_chantier#") for o in res["observations"])


def test_connaissance_anterieure_au_registre_le_refuse_et_non_admin_refuse(monde):
    _capturer_mesures(monde, 1)
    _definir("m8_marge_reelle_cad", "CAD")
    _capturer_registre(monde, 2)
    avant = _rapprocher(monde, "2026-10-28T12:00:01Z")  # le registre n'était pas encore connu
    assert "REJ-SEMANTIQUE-REGISTRE-ABSENT" in json.dumps(avant)
    comptable = H.IdentiteAppelante("comptable", "admin")
    assert (
        _rapprocher(monde, identite=H.IdentiteAppelante("vendeur.fictif", "employee", source="appareil"))["ok"] is False
    )
    assert _rapprocher(monde, identite=None)["ok"] is False
    assert comptable.role == "admin"


def test_le_vrai_m8_ne_fournit_aucune_preuve_propre_donc_l_empreinte_reste_non_comparable(monde):
    """Contrat successeur M9.3 sur le vrai producteur : les mesures M8 portent une empreinte de définition mais aucune
    preuve propre, et aucun historique versionné n'est consommé. M9 ne projette aucune liaison : non comparable,
    raison nommée, valeur jamais vérifiée par la preuve de définition."""
    _capturer_mesures(monde, 1)
    _definir("m8_marge_reelle_cad", "CAD")
    registre = _capturer_registre(monde, 2)
    page = H.page(registre["index"])
    assert H.valeurs(page, "resultat.liaisons_versions[*]") == []  # aucune liaison globale chez M8 aujourd'hui
    res = _rapprocher(monde)["resultat"]
    assert res["historique_definitions"] == "NON_CONSOMME"
    marge = next(o for o in res["observations"] if o["metric_id"] == "m8_marge_reelle_cad")
    assert marge["statut"] == "VERSION_NON_COMPARABLE" and marge["raison"] == "HISTORIQUE_ABSENT"
    assert marge["valeur_verifiee"] is False and marge["preuve_definition"] is None


def test_parcours_m8_reel_vers_contrat_successeur_avec_historique_simule(monde):
    """Mesure RÉELLE de M8 (empreinte calculée par M8) face à un historique de définitions SIMULÉ au format du contrat
    successeur (le candidat producteur M8 n'est pas intégré) : A/B/A, historique sans preuve de même empreinte,
    recalcul explicitement lié, collision de modules, révision inconnue."""
    from m9_strategic_intelligence import preuves_definition as pd
    from m9_strategic_intelligence import semantique_metriques as sm

    mesures = _capturer_mesures(monde, 1)
    page = H.page(mesures["index"])
    reelle = next(m for m in H.valeurs(page, "resultat.mesures[*]") if m["metric_id"] == "m8_marge_reelle_cad")
    a = reelle["version_definition"]  # empreinte réelle produite par M8
    assert len(a) == 64 and "preuve_definition" not in reelle
    b = "b" * 64 if a != "b" * 64 else "c" * 64
    cle = {"famille": "finance", "module": "m08", "id": "m8_marge_reelle_cad"}
    homonyme = {"famille": "terrain", "module": "m04", "id": "m8_marge_reelle_cad"}
    publications = [
        {"cle": cle, "revision": 1, "empreinte": a},
        {"cle": homonyme, "revision": 1, "empreinte": b},
        {"cle": cle, "revision": 2, "empreinte": b},
        {"cle": cle, "revision": 3, "empreinte": a},
    ]
    vue = pd.vue_de("dictionnaire", publications)
    pages = [
        {"registre": "dictionnaire", "vue": vue, "total": 4, "depart": 0, "prochain_depart": 2,
         "publications": publications[:2]},
        {"registre": "dictionnaire", "vue": vue, "total": 4, "depart": 2, "prochain_depart": None,
         "publications": publications[2:]},
    ]  # fmt: skip
    historique = pd.assembler_historique(pages)
    catalogue = sm.cataloguer([{"metric_id": "m8_marge_reelle_cad", "unite": reelle["unite"], "version": 1}])
    observation = {k: reelle[k] for k in ("metric_id", "valeur", "unite", "version_definition")}

    def preuve(revision, quelle_cle=cle, empreinte=a):
        return {"registre": "dictionnaire", "cle": quelle_cle, "revision": revision, "empreinte": empreinte}

    statuts = {
        "historique_sans_preuve": sm.classer(observation, catalogue, historique),
        "recalcul_lie": sm.classer(observation | {"preuve_definition": preuve(3)}, catalogue, historique),
        "ancienne_meme_contenu": sm.classer(observation | {"preuve_definition": preuve(1)}, catalogue, historique),
        "homonyme": sm.classer(observation | {"preuve_definition": preuve(1, homonyme)}, catalogue, historique),
        "inconnue": sm.classer(observation | {"preuve_definition": preuve(9)}, catalogue, historique),
    }
    assert statuts["historique_sans_preuve"]["raison"] == "PREUVE_PROPRE_ABSENTE"
    assert statuts["recalcul_lie"]["statut"] == "COMPATIBLE" and statuts["recalcul_lie"]["valeur"] == "114.00"
    assert statuts["ancienne_meme_contenu"]["statut"] == "VERSION_PERIMEE"
    assert statuts["ancienne_meme_contenu"]["meme_contenu_que_la_courante"] is True
    assert statuts["homonyme"]["raison"] == "EMPREINTE_DIFFERENTE_A_CETTE_REVISION"
    assert statuts["inconnue"]["raison"] == "REVISION_INCONNUE"
    assert all(s["valeur_verifiee"] is False for s in statuts.values())
    corrompu = [dict(p) for p in pages]
    corrompu[1] = dict(corrompu[1], publications=[dict(publications[2], empreinte=a), publications[3]])
    with pytest.raises(ValueError, match="REJ-HISTORIQUE-CORROMPU"):
        pd.assembler_historique(corrompu)
