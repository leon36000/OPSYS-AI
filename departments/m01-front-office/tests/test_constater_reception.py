"""M1-H : `m1_constater_reception` publie le constat agrégé sur le VRAI registre et le VRAI bus.

Aucun contact, aucun texte, aucun identifiant de lead dans la charge ; le rejeu sur le même registre est un no-op.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from m1_front_office import outils as outils_m1

from opsys import stockage
from opsys.capacites import Capacites
from opsys.departements import lire_manifeste
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

M1 = Path(__file__).resolve().parents[1]
DATE_REF = "2031-01-20"


@pytest.fixture
def instance(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils_m1.utiliser_stockage_durable()
    yield
    outils_m1.reinitialiser_registre()
    stockage.liberer()


def _ajouter(lignes):
    with stockage.transaction():
        reg = outils_m1._obtenir_registre()
        for ligne in lignes:
            reg.ajouter(ligne)


def _signal(jour, conversation="sms-secret-514-555-0142"):
    return {"type_entree": "signal", "canal": "sms", "conversation_id": conversation,
            "signal_id": f"{conversation}:{jour}", "horodatage": f"2031-01-{jour:02d}T08:00:00-05:00",
            "contenu_filtre": "Client fictif au 514-555-0142, ne jamais recopier ce texte."}


def _lead(jour, service="gouttieres", ville="Laval"):
    return {"type_entree": "lead_emis", "canal": "sms", "conversation_id": "sms-secret-514-555-0142",
            "signal_id": "sms:a", "horodatage": f"2031-01-{jour:02d}T08:05:00-05:00",
            "lead": {"lead_id": "a" * 64, "service": service, "ville": ville}}


def _transfert(tid, jour, heure="09:00"):
    return {"type_entree": "transfert", "evenement": "ouvert", "transfert_id": tid,
            "type_transfert": "plainte", "niveau": "N4", "categories": ["insatisfaction"], "canal": "sms",
            "conversation_id": "sms-secret-514-555-0142", "signal_id": "sms:a", "signaux": ["sms:a"],
            "horodatage": f"2031-01-{jour:02d}T{heure}:00-05:00"}


def _close(tid, jour, heure="09:10"):
    return {"type_entree": "transfert", "evenement": "clos", "transfert_id": tid,
            "horodatage": f"2031-01-{jour:02d}T{heure}:00-05:00", "issue": "contact_reussi",
            "clos_par": "personne.fictive", "role": "admin", "voie": "appareil",
            "motif": "Contact réussi, déclaré par une personne."}


def _capacites():
    return Capacites({"m01-front-office": lire_manifeste(M1)}, stockage.transaction, memoire=False)


def _evenements():
    with stockage.transaction() as cnx:
        return [dict(x) for x in cnx.execute(EVENEMENTS_SORTANTS.select().where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m1.reception_constatee")).mappings()]


def test_le_constat_publie_des_comptes_sans_aucune_donnee_personnelle(instance):
    _ajouter([_signal(15), _lead(15), _transfert("tr-1", 15), _close("tr-1", 15)])
    r = _capacites().appeler("m1_constater_reception", {"date_reference": DATE_REF, "jours": 6})
    assert r["ok"] is True and r["resultat"]["accepte"] is True, r
    resultat = r["resultat"]["resultat"]
    assert resultat["publie"] is True and resultat["evenement_id"].startswith("m1-reception-2031-01-20-6-")
    assert len(resultat["evenement_id"].rsplit("-", 1)[-1]) == 16
    assert resultat["delai_premiere_prise_en_charge_s"]["median_s"] == 600
    assert resultat["leads_par_service"]["comptes"] == {"gouttieres": 1}
    assert resultat["hors_zone"]["statut"] == "NON_EVALUEE"
    assert resultat["photos_recues_pct"]["statut"] == "NON_EVALUEE"
    (evenement,) = _evenements()
    charge = codec.decoder(evenement["charge"])
    assert charge == {k: v for k, v in resultat.items() if k != "publie"}
    texte = json.dumps(charge, ensure_ascii=False)
    for interdit in ("514-555-0142", "Client fictif", "sms-secret", "a" * 64):
        assert interdit not in texte


def test_rejouer_le_meme_constat_ne_publie_rien_de_plus(instance):
    _ajouter([_signal(15), _lead(15)])
    capacites = _capacites()
    premier = capacites.appeler("m1_constater_reception", {"date_reference": DATE_REF, "jours": 6})
    second = capacites.appeler("m1_constater_reception", {"date_reference": DATE_REF, "jours": 6})
    assert premier["resultat"]["resultat"]["evenement_id"] == second["resultat"]["resultat"]["evenement_id"]
    assert len(_evenements()) == 1


def test_le_schema_de_l_outil_est_ferme(instance):
    capacites = _capacites()
    outil = capacites.index["m1_constater_reception"][1]
    assert outil.parametres["additionalProperties"] is False
    assert outil.parametres["properties"]["jours"]["type"] == "integer"


def test_une_periode_invalide_est_refusee_avant_lecture(instance):
    reponse = _capacites().appeler("m1_constater_reception", {"date_reference": DATE_REF, "jours": 0})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-M1-RECEPTION-PERIODE"
    assert _evenements() == []
