"""Diagnostic M8 : admission courante et lectures sans effet, en SQLite fictif.

Le contexte d'identité est injecté pour ces tests du socle ; il ne constitue
pas une preuve d'authentification Gateway DEVICE.
"""
from __future__ import annotations

import importlib
import json

import pytest
from sqlalchemy import inspect, text

from opsys import contexte, idempotence, identite, jetons, liaison_cibles, openclaw, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.evenements import bus
from opsys.outils import Autonomie, Niveau

module_maillons = importlib.import_module("opsys.stockage.maillons")

NOM = "m8_lire_provenance_m5_appareil"
ACTEUR = "admin-provenance-m8-fictif"
LECTURE = {"perimetre": "cash_global", "wct_id": None, "decalage": 0, "limite": 1}
DETAIL = "Le diagnostic ne satisfait pas son contrat ; aucun détail partiel n’est transmis."


def _cap(limite=5400):
    return Capacites(charger_departements(), stockage.transaction, memoire=False, limite_sortie=limite)


def _cap_garde(limite=5400):
    """Vrai composant Cap, sans catalogue métier pour les tests du seul cadre de sortie."""
    return Capacites({}, stockage.transaction, memoire=False, limite_sortie=limite)


def _tables(cnx):
    noms = inspect(cnx).get_table_names()
    assert len(noms) == 49  # Aucun DDL ajouté par ce diagnostic.
    return {nom: sorted(map(tuple, cnx.execute(text(
        'SELECT * FROM "' + nom.replace('"', '""') + '"',
    )).all()), key=repr) for nom in noms}


def _personne(cnx, role="admin"):
    identite.creer_personne(cnx, ACTEUR, "Provenance fictive", "mot-de-passe-fictif-12345", [role])


def _identite(role="admin", source="appareil"):
    return contexte.IdentiteAppelante(ACTEUR, role, source=source)


def _sources_interdites(monkeypatch):
    from m8_analytics import outils

    def interdite(*_args, **_kwargs):
        pytest.fail("Une source métier a été lue avant le refus d'admission ou d'arguments.")

    # Contrat des deux nouveaux lecteurs : injection négative, pas source simulée positive.
    for module, nom in [(bus, "copier_publications_et_recus"),
                        (module_maillons, "copier_maillons_avec_metadonnees"),
                        (outils, "copier_publications_et_recus"),
                        (outils, "copier_maillons_avec_metadonnees")]:
        monkeypatch.setattr(module, nom, interdite, raising=False)


def test_catalogue_m8_ferme_role_admin_n0_et_schema_quatre_arguments():
    cap = _cap()
    roles = openclaw.roles_outils(cap.departements)
    assert {nom for nom in roles["admin"] if nom.startswith("m8_")} == {
        "m8_lire_mesures_chantier", "m8_performance_equipe", "m8_lire_vue_executive",
        "m8_lire_mesures_contenus", "m8_lire_provenance_m5_appareil",
    }
    assert NOM not in roles["employee"] and NOM not in roles["seller"]
    dept, outil = cap.index[NOM]
    assert dept.id == "m08-analytics"
    assert outil.autonomie is Autonomie.T0 and outil.niveau_effectif is Niveau.N0
    assert outil.roles_appareil == frozenset({"admin"})
    assert outil.portee_contexte == "globale" and not outil.frontiere_humaine
    assert NOM not in liaison_cibles.OUTILS_CIBLES
    assert outil.parametres == {
        "type": "object", "additionalProperties": False,
        "properties": {
            "perimetre": {"type": "string", "enum": ["cash_global", "rentabilite_wct"]},
            "wct_id": {"type": ["string", "null"], "minLength": 1, "maxLength": 256},
            "decalage": {"type": "integer", "minimum": 0, "maximum": 10000},
            "limite": {"type": "integer", "minimum": 1, "maximum": 8},
        },
        "required": ["perimetre", "wct_id", "decalage", "limite"],
    }


@pytest.mark.parametrize("acteur", [None, _identite(source="console"),
                                    _identite("employee"), _identite("seller")])
def test_identite_absente_console_et_roles_non_admin_refuses_avant_sources(session, monkeypatch, acteur):
    with session() as cnx:
        _personne(cnx)
        avant = _tables(cnx)
    _sources_interdites(monkeypatch)
    with contexte.appele_par_appareil(acteur):
        reponse = _cap().appeler(NOM, LECTURE)
    assert reponse.get("ok") is False and reponse.get("erreur") == "hors_portee_role", reponse
    with session() as cnx:
        assert _tables(cnx) == avant


@pytest.mark.parametrize("modification", ["role_retire", "personne_inactive", "personne_absente"])
def test_autorite_sql_relue_a_chaque_page_meme_instance_cap(session, monkeypatch, modification):
    with session() as cnx:
        _personne(cnx)
    cap = _cap()
    if modification != "personne_absente":
        with contexte.appele_par_appareil(_identite()):
            initiale = cap.appeler(NOM, LECTURE)
        assert initiale.get("ok") is True and initiale["resultat"]["accepte"] is True, initiale
    with session() as cnx:
        if modification == "role_retire":
            identite.retirer_role(cnx, ACTEUR, "admin")
        elif modification == "personne_inactive":
            identite.activer(cnx, ACTEUR, False)
        avant = _tables(cnx)
    _sources_interdites(monkeypatch)
    acteur = _identite() if modification != "personne_absente" else contexte.IdentiteAppelante(
        "personne-provenance-inconnue-fictive", "admin", source="appareil",
    )
    with contexte.appele_par_appareil(acteur):
        reponse = cap.appeler(NOM, LECTURE)
    assert reponse == {"ok": True, "resultat": {"accepte": False, "verdict": {
        "code": "REJ-M8-PROVENANCE-IDENTITE-INVALIDE", "detail": DETAIL,
    }}}
    with session() as cnx:
        assert _tables(cnx) == avant


@pytest.mark.parametrize("arguments", [
    None, [], [["perimetre", "cash_global"]], "cash_global",
    {**LECTURE, "perimetre": "autre"}, {**LECTURE, "wct_id": "WCT-fictif"},
    {**LECTURE, "perimetre": "rentabilite_wct", "wct_id": None},
    {**LECTURE, "perimetre": "rentabilite_wct", "wct_id": "   "},
    {**LECTURE, "perimetre": "rentabilite_wct", "wct_id": "x\n"},
    {**LECTURE, "perimetre": "rentabilite_wct", "wct_id": "\ud800"},
    {**LECTURE, "perimetre": "rentabilite_wct", "wct_id": "x" * 257},
    {**LECTURE, "decalage": True}, {**LECTURE, "decalage": -1},
    {**LECTURE, "decalage": 10001}, {**LECTURE, "limite": False},
    {**LECTURE, "limite": 0}, {**LECTURE, "limite": 9},
    {**LECTURE, "source": "appareil"}, {**LECTURE, "appareil": "DEVICE-FICTIF"},
    {cle: valeur for cle, valeur in LECTURE.items() if cle != "limite"},
])
def test_arguments_entierement_fermes_avant_sources_et_claim(session, monkeypatch, arguments):
    with session() as cnx:
        _personne(cnx)
        avant = _tables(cnx)
    _sources_interdites(monkeypatch)
    with contexte.appele_par_appareil(_identite()):
        reponse = _cap().appeler(NOM, arguments)
    assert reponse == {"ok": True, "resultat": {"accepte": False, "verdict": {
        "code": "REJ-M8-PROVENANCE-ARGUMENTS-INVALIDES", "detail": DETAIL,
    }}}
    with session() as cnx:
        assert _tables(cnx) == avant


@pytest.mark.parametrize("extras,erreur", [
    ({"meta": idempotence.Meta("00000000-0000-4000-8000-000000000008", "DEVICE-FICTIF",
                               "2026-10-09T10:00:00.000-04:00")}, "idempotence_hors_portee_lecture"),
    ({"ticket_memoire": "ticket-client-fictif"}, "ticket_hors_portee_provenance_m8"),
    ({"ticket_cible": object()}, "ticket_hors_portee_provenance_m8"),
])
def test_meta_mutation_et_tickets_refuses_sans_claim_ni_trace(session, monkeypatch, extras, erreur):
    with session() as cnx:
        _personne(cnx)
        avant = _tables(cnx)
    _sources_interdites(monkeypatch)
    with contexte.appele_par_appareil(_identite()):
        reponse = _cap().appeler(NOM, LECTURE, **extras)
    assert reponse.get("ok") is False and reponse.get("erreur") == erreur, reponse
    with session() as cnx:
        assert _tables(cnx) == avant


def test_lecture_vide_pure_repetee_apres_reouverture_sql(session):
    with session() as cnx:
        _personne(cnx)
        avant = _tables(cnx)
    with contexte.appele_par_appareil(_identite()):
        premiere = _cap().appeler(NOM, LECTURE)
    assert premiere.get("ok") is True and premiere["resultat"]["accepte"] is True, premiere
    dto = premiere["resultat"]["resultat"]
    assert set(dto) == {"type", "version_schema", "perimetre", "wct_id", "portee", "sources",
                        "selection", "publications", "affichage", "couverture"}
    assert dto["type"] == "DIAGNOSTIC_RECEPTION_M5" and dto["version_schema"] == 1
    assert dto["publications"] == []
    assert dto["selection"] == {"publication_courante_id": None, "fact_courant_reference": None,
                               "ambiguite": False}
    assert dto["affichage"] == {"decalage": 0, "limite": 1, "total_publications": 0,
                               "affiches": 0, "reste": 0, "prochain_decalage": None}
    assert dto["couverture"]["completude_financiere_entreprise"] is False
    assert dto["couverture"]["horodatage_reception"] == "non_persiste"
    assert len(json.dumps(premiere, ensure_ascii=False)) <= 5400
    with session() as cnx:
        assert _tables(cnx) == avant
    stockage.liberer()  # Réouverture SQL, distincte d'un redémarrage de processus.
    with contexte.appele_par_appareil(_identite()):
        suivante = _cap().appeler(NOM, LECTURE)
    assert suivante == premiere
    with session() as cnx:
        assert _tables(cnx) == avant


@pytest.mark.parametrize("quota", [40, 550, 800])
def test_quota_reduit_refuse_sans_diagnostic_partiel_ni_artefact(session, quota):
    with session() as cnx:
        _personne(cnx)
        avant = _tables(cnx)
    with contexte.appele_par_appareil(_identite()):
        reponse = _cap(quota).appeler(NOM, LECTURE)
    assert reponse == {"ok": True, "resultat": {"accepte": False, "verdict": {
        "code": "REJ-M8-PROVENANCE-SORTIE-TROP-VOLUMINEUSE", "detail": DETAIL,
    }}}
    with session() as cnx:
        assert _tables(cnx) == avant


def test_garde_nommee_ne_transmet_jamais_un_cadre_surdimensionne_a_artefacts(session, monkeypatch):
    def interdit(*_args, **_kwargs):
        pytest.fail("Le diagnostic N0 ne doit pas passer au stockage d'artefacts.")

    monkeypatch.setattr(jetons, "tronquer", interdit)
    cadre = {"ok": True, "resultat": {"accepte": True, "resultat": {"marqueur_fictif": "x" * 6000}}}
    with session():
        reponse = _cap_garde()._tronquer(cadre, NOM)
    assert reponse == {"ok": True, "resultat": {"accepte": False, "verdict": {
        "code": "REJ-M8-PROVENANCE-SORTIE-TROP-VOLUMINEUSE", "detail": DETAIL,
    }}}


def test_garde_nommee_preserve_refus_constant_sans_artefact_meme_au_quota40(session):
    refus = {"ok": True, "resultat": {"accepte": False, "verdict": {
        "code": "REJ-M8-PROVENANCE-REGISTRE-INVALIDE", "detail": DETAIL,
    }}}
    with session():
        assert _cap_garde(40)._tronquer(refus, NOM) == refus


@pytest.mark.parametrize("invalide", ["nan", "inf", "surrogate", "cycle", "encoder_recursion", "objet"])
def test_garde_nommee_refuse_encodage_non_json_sans_artefact(session, monkeypatch, invalide):
    valeurs = {"nan": float("nan"), "inf": float("inf"), "surrogate": "\ud800", "objet": object()}
    if invalide == "cycle":
        valeur = {}
        valeur["cycle_fictif"] = valeur
    elif invalide == "encoder_recursion":
        valeur = None
    else:
        valeur = valeurs[invalide]

    def interdit(*_args, **_kwargs):
        pytest.fail("Un encodage refusé ne doit jamais créer d'artefact.")

    monkeypatch.setattr(jetons, "tronquer", interdit)
    cadre = {"ok": True, "resultat": {"accepte": True, "resultat": {"invalide_fictif": valeur}}}
    with session() as cnx:
        avant = _tables(cnx)
        cap = _cap_garde()
        if invalide == "encoder_recursion":
            def encodeur_indisponible(*_args, **_kwargs):
                raise RecursionError("panne encodeur fictive")

            monkeypatch.setattr(json, "dumps", encodeur_indisponible)
        reponse = cap._tronquer(cadre, NOM)
        assert _tables(cnx) == avant
    assert reponse == {"ok": False, "erreur": "provenance_m8_indisponible", "details": DETAIL}


@pytest.mark.parametrize("cadre", [
    {"ok": False, "erreur": "ValueError", "details": "CANARY_PRIVATE_FICTIF"},
    {"ok": True, "resultat": {"accepte": False, "verdict": {
        "code": ["CANARY_PRIVATE_FICTIF"], "detail": DETAIL,
    }}},
    {"ok": True, "resultat": {"accepte": False, "verdict": {
        "code": "REJ-M8-PROVENANCE-SOURCE-INVALIDE", "detail": "CANARY_PRIVATE_FICTIF",
    }}},
])
def test_garde_nommee_ne_transmet_pas_un_detail_technique_ou_verdict_malforme(session, cadre):
    with session():
        reponse = _cap_garde(40)._tronquer(cadre, NOM)
    assert reponse == {"ok": False, "erreur": "provenance_m8_indisponible", "details": DETAIL}
    assert "CANARY_PRIVATE_FICTIF" not in json.dumps(reponse, ensure_ascii=False)
