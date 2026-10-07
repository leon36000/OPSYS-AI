"""Contrats Stock admin : HTTP MCP réel, porte Core simulée en Python, SQLite temporaire.

Ces tests préparent T4.23, sans UI ni téléphone. Les réponses viennent des outils M6 réels,
les réservations du vrai bus M3 -> M6. Aucun registre/résultat lu n'est remplacé par un mock.
Les fixtures sont fictives ; l'export optionnel est une preuve externe au dépôt, jamais un cache mobile.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest
from harnais_e2e import Reponse, iso
from m6_material_control.registre import Registre
from tests.e2e.test_briefing_admin_appareil import empreinte_tables
from tests.e2e.test_materiel_pret_appareil import (
    CHANTIER,
    DEVIS,
    GOUTTIERE,
    M6,
    VIS,
    _devis_accepte,
    _livrer_m6,
    _reception,
    _transfert,
)

from opsys import cli, evenements, stockage

FICTIF = True
pytestmark = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
OUTILS = ("m6_lire_disponibilite", "m6_produire_digest")
ENV_EXPORT = "OPSYS_STOCK_FIXTURE_PATH"
RACINE = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def captures_stock():
    """Réponses natives en RAM ; export demandé explicitement, création exclusive sans écraser une preuve."""
    captures = []
    yield captures
    cible = os.environ.get(ENV_EXPORT)
    if cible is None:
        return
    chemins = [
        "tests/e2e/test_stock_admin_appareil.py", "tests/fixtures/harnais_e2e.py",
        "departments/m06-material-control/src/m6_material_control/outils.py",
        "departments/m06-material-control/src/m6_material_control/digest.py",
        "departments/m06-material-control/src/m6_material_control/stock.py",
        "departments/m06-material-control/src/m6_material_control/reservations.py",
        "departments/m06-material-control/src/m6_material_control/emplacements.py",
    ]
    preuve = {
        "fictif": True,
        "provenance": {
            "repo": str(RACINE),
            "trajet": "HTTP MCP réel ; porte Core simulée en Python ; SQLite temporaire ; aucun téléphone",
            "source_sha256": {p: hashlib.sha256((RACINE / p).read_bytes()).hexdigest() for p in chemins},
        },
        "lectures": captures,
    }
    with Path(cible).open("x", encoding="utf-8") as sortie:
        sortie.write(json.dumps(preuve, ensure_ascii=False, indent=2) + "\n")


def _capturer(captures, nom: str, outil: str, args: dict, reponse: Reponse) -> None:
    assert reponse.statut == 200 and reponse.ok, reponse.corps
    assert reponse.mesure.messages_mcp.get("tools/call") == 1
    assert reponse.mesure.tronque is False, "le transport doit garder le contrat métier complet"
    captures.append({"nom": nom, "outil": outil, "args": args, "http_statut": reponse.statut,
                     "corps": reponse.corps})


def test_admin_lit_disponibilite_couple_digest_direct_et_unites_de_la_source(moteur, equipe, captures_stock):
    admin = equipe["admin"]
    _devis_accepte(moteur)
    _livrer_m6(moteur)

    # Une réservation touchant la sélection décrit TOUT son manque, même l'autre article.
    args = {"materiau_ids": [GOUTTIERE]}
    avant = empreinte_tables()
    initiale = admin.appeler(OUTILS[0], args)
    assert initiale.metier["accepte"] is True
    (reservation,) = initiale.resultat["reservations_actives"]
    assert (reservation["devis_id"], reservation["chantier_id"], reservation["statut"]) == (
        DEVIS, CHANTIER, "a_commander")
    assert reservation["lignes_manquantes"] == [
        {"materiau_id": GOUTTIERE, "unite": "pi", "quantite_besoin": "100",
         "quantite_reservee": "0", "quantite_manquante": "100"},
        {"materiau_id": VIS, "unite": "boite", "quantite_besoin": "20",
         "quantite_reservee": "0", "quantite_manquante": "20"},
    ]
    assert [a["materiau_id"] for a in initiale.resultat["articles"]] == [GOUTTIERE]
    assert empreinte_tables() == avant
    _capturer(captures_stock, "reservation_manque_hors_selection_fictif", OUTILS[0], args, initiale)

    assert _reception(moteur, admin, GOUTTIERE, 100.0, "PO-STOCK-fictif-1", "reception-stock-fictif-1").ok
    assert _reception(moteur, admin, VIS, 20.0, "PO-STOCK-fictif-2", "reception-stock-fictif-2").ok
    assert _transfert(moteur, admin, "T-STOCK-fictif", {"type": "inconnu"}, {"type": "rebut"},
                      30.0, "transfert-stock-fictif").metier["accepte"] is True
    comptage = admin.appeler("m6_soumettre_comptage", {"comptage": {
        "chantier_id": "CHANTIER-DEPOT", "materiau_id": GOUTTIERE, "quantite_comptee": 98.0,
        "horodatage": iso(moteur.horloge.maintenant),
    }}, cle="comptage-stock-fictif", horodatage_appareil=iso(moteur.horloge.maintenant))
    assert comptage.metier["accepte"] is True, comptage.corps

    avant = empreinte_tables()
    disponible = admin.appeler(OUTILS[0], args)
    assert disponible.metier["accepte"] is True
    assert set(disponible.metier) == {"accepte", "resultat"}
    assert disponible.resultat == {
        "articles": [{"materiau_id": GOUTTIERE, "stock_theorique": "100", "hors_main": "30",
                      "en_main": "70", "reserve": "70", "disponible": "0",
                      "par_emplacement": {"rebut": "30", "inconnu": "70"}}],
        "tronque": False,
        "reservations_actives": [{"devis_id": DEVIS, "chantier_id": CHANTIER, "statut": "partiel",
                                  "lignes_manquantes": [{"materiau_id": GOUTTIERE, "unite": "pi",
                                                         "quantite_besoin": "100", "quantite_reservee": "70",
                                                         "quantite_manquante": "30"}]}],
        "reservations_tronquees": False,
    }
    _capturer(captures_stock, "disponibilite_fictif", OUTILS[0], args, disponible)

    seuils = {"seuils_reorder": [{"chantier_id": "CHANTIER-DEPOT", "materiau_id": GOUTTIERE,
                                "seuil_quantite": 120.0}]}
    for nom, arguments, reorders in (
        ("digest_sans_seuil_fictif", {}, []),
        ("digest_seuil_fourni_fictif", seuils,
         [{"chantier_id": "CHANTIER-DEPOT", "materiau_id": GOUTTIERE, "quantite_suggeree": 20.0}]),
    ):
        lecture = admin.appeler(OUTILS[1], arguments)
        digest = lecture.metier
        assert {k: v for k, v in digest.items() if k != "hash_digest"} == {
            "type": "DIGEST_MATERIEL", "nb_variances_stock": 1, "nb_reorders_suggeres": len(reorders),
            "variances_significatives": [{"chantier_id": "CHANTIER-DEPOT", "materiau_id": GOUTTIERE,
                                          "verdict_variance": "STOCK_INFERIEUR_AU_THEORIQUE", "ecart": -2.0}],
            "reorders": reorders,
        }
        assert re.fullmatch(r"[0-9a-f]{64}", digest["hash_digest"])
        assert type(digest["variances_significatives"][0]["ecart"]) is float
        if reorders:
            assert type(digest["reorders"][0]["quantite_suggeree"]) is float
        _capturer(captures_stock, nom, OUTILS[1], arguments, lecture)
    assert empreinte_tables() == avant, "les lectures ne changent aucune table, pas même les faits d'audit"
    assert moteur.bilan()["troncatures"] == []


@pytest.mark.parametrize("outil", OUTILS)
def test_employe_hors_portee_stock_ne_contacte_pas_mcp_et_ne_change_rien(moteur, equipe, outil):
    avant = empreinte_tables()
    refuse = equipe["employe"].appeler(outil)
    assert refuse.statut == 403 and refuse.ok is False
    assert refuse.corps["error"]["type"] == "tool_call_blocked"
    assert "tool_out_of_scope" in refuse.corps["error"]["message"]
    assert refuse.mesure.requetes_http == 0
    assert empreinte_tables() == avant


@pytest.mark.parametrize("outil", OUTILS)
def test_appareil_revoque_stock_est_ferme_a_la_porte(moteur, equipe, outil):
    admin = equipe["admin"]
    assert cli.main(["appareils", "revoquer", admin.appareil_id, "--config-dir", str(moteur.config_dir)]) == 0
    avant = empreinte_tables()
    refuse = admin.appeler(outil)
    assert refuse.statut == 403 and refuse.ok is False
    assert "device_unknown" in refuse.corps["error"]["message"]
    assert refuse.mesure.requetes_http == 0
    assert empreinte_tables() == avant


@pytest.mark.parametrize("outil", OUTILS)
def test_admin_desactive_stock_refuse_malgre_fragment_core_ancien(moteur, equipe, outil, captures_stock):
    assert cli.main(["personnes", "desactiver", "nathan"]) == 0
    avant = empreinte_tables()
    refuse = equipe["admin"].appeler(outil)
    assert refuse.statut == 200 and refuse.ok is True, refuse.corps
    assert refuse.metier["accepte"] is False
    assert refuse.metier["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert refuse.mesure.messages_mcp.get("tools/call") == 1
    assert empreinte_tables() == avant
    _capturer(captures_stock, f"refus_admin_desactive_{outil}_fictif", outil, {}, refuse)


@pytest.mark.parametrize("nombre", [15, 16])
def test_stock_limite_articles_sans_total_ni_curseur(moteur, equipe, nombre, captures_stock):
    # Seam de préparation : mouvements fictifs via le registre durable réel, réponse jamais simulée.
    with stockage.transaction():
        registre = Registre(stockage.maillons(M6, "principal"))
        for i in range(nombre):
            _, erreur = registre.ajouter({"type_mouvement": "RECEPTION", "chantier_id": "CH-STOCK-fictif",
                                          "materiau_id": f"mat-fictif-{i:02d}", "quantite": 1.0,
                                          "cout_unitaire": None})
            assert erreur is None
    avant = empreinte_tables()
    lecture = equipe["admin"].appeler(OUTILS[0])
    resultat = lecture.resultat
    assert set(resultat) == {"articles", "tronque", "reservations_actives", "reservations_tronquees"}
    assert [a["materiau_id"] for a in resultat["articles"]] == [f"mat-fictif-{i:02d}" for i in range(15)]
    assert resultat["tronque"] is (nombre == 16)
    assert resultat["reservations_actives"] == [] and resultat["reservations_tronquees"] is False
    assert empreinte_tables() == avant
    _capturer(captures_stock, f"articles_{nombre}_fictif", OUTILS[0], {}, lecture)


@pytest.mark.parametrize("nombre", [10, 11])
def test_stock_limite_reservations_sans_inventer_le_reste(moteur, equipe, nombre, captures_stock):
    for i in range(nombre):
        devis = f"df-fictif-{i:02d}"
        evenements.publier("m3.devis_accepte", "m03-estimation", {
            "devis_id": devis, "lead_id": "lead-fictif", "chantier_id": None,
            "lignes": [{"reference_ligne": f"{devis}-L1", "description": "ligne fictive", "quantite": "1",
                        "unite": "pi", "prix_unitaire": "1.00", "prix_ligne": "1.00",
                        "reference_besoin_materiau": "mat-fictif"}],
            "cout_total": "1.00", "prix_total": "1.00", "taux_marge": "0",
            "horodatage_acceptation": iso(moteur.horloge.maintenant),
        }, evenement_id=f"m3-devis-accepte-{devis}")
    _livrer_m6(moteur)
    avant = empreinte_tables()
    lecture = equipe["admin"].appeler(OUTILS[0])
    resultat = lecture.resultat
    assert set(resultat) == {"articles", "tronque", "reservations_actives", "reservations_tronquees"}
    assert resultat["tronque"] is False
    assert resultat["reservations_tronquees"] is (nombre == 11)
    assert [r["devis_id"] for r in resultat["reservations_actives"]] == [f"df-fictif-{i:02d}" for i in range(10)]
    for reservation in resultat["reservations_actives"]:
        assert reservation["chantier_id"] is None and reservation["statut"] == "a_commander"
        assert reservation["lignes_manquantes"] == [{"materiau_id": "mat-fictif", "unite": "pi",
                                                   "quantite_besoin": "1", "quantite_reservee": "0",
                                                   "quantite_manquante": "1"}]
    assert empreinte_tables() == avant
    _capturer(captures_stock, f"reservations_{nombre}_fictif", OUTILS[0], {}, lecture)
