"""D2 : M6 publie, pour M8, CINQ comptes de disponibilité (`m6.disponibilite_constatee`).

Vrais outils, base SQLite migrée, vrais registres durables de M6, vrai bus (outbox). Prouve : les comptes sont ceux de
la
lecture `m6_lire_disponibilite` ; aucun article, quantité, prix ni chantier ne part ; un registre vide donne des zéros
véridiques (`articles_suivis` à 0) ; rejouer ne publie rien de plus, une donnée changée est une version de plus ; une
date
illisible ou un appel hors transaction est refusé sans rien publier. Quantités et identifiants FICTIFS.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from m6_material_control import constat_disponibilite
from sqlalchemy import select

from opsys import stockage
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

_spec = importlib.util.spec_from_file_location(
    "fixture_constat_disponibilite", Path(__file__).with_name("test_reservation_outils.py")
)
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)
base, m6 = aide.base, aide.m6
FICTIF = True
TYPE = "m6.disponibilite_constatee"
JOUR = "2026-10-15"
INSTANT = "2026-10-15T12:00:00-04:00"
PLUS_TARD = "2026-10-15T18:00:00-04:00"
LENDEMAIN = "2026-10-16T12:00:00-04:00"


def _constater(m6, horodatage=INSTANT):
    return executer_atomique(m6["m6_constater_disponibilite"], {"horodatage": horodatage})


def _resultat(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _publies():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge)
            .where(EVENEMENTS_SORTANTS.c.type_evenement == TYPE)
            .order_by(EVENEMENTS_SORTANTS.c.evenement_id)
        ).all()
    return [(i, codec.decoder(c)) for i, c in lignes]


def test_agent_seulement_aucun_droit_d_appareil(m6):
    outil = m6["m6_constater_disponibilite"]
    assert (outil.autonomie, outil.niveau_effectif) == (Autonomie.T1, Niveau.N2) and not outil.roles_appareil


def test_un_registre_vide_donne_des_zeros_veridiques(base, m6):
    _resultat(_constater(m6))
    ((_, charge),) = _publies()
    assert (
        charge["articles_suivis"],
        charge["articles_en_rupture"],
        charge["articles_sur_reserves"],
        charge["reservations_actives"],
        charge["reservations_incompletes"],
    ) == (0, 0, 0, 0, 0)


def test_les_comptes_sont_ceux_de_la_lecture_et_aucun_article_ne_part(base, m6):
    aide._recevoir(m6, aide.GOUTTIERE, 100.0, "PO-DEPOT-1")
    aide._accepter(aide._devis("DEVIS-A", "CH-A", gouttiere="70", vis="20"))
    lecture = aide._outil(m6, "m6_lire_disponibilite", {"materiau_ids": None})["resultat"]
    en_rupture = [a for a in lecture["articles"] if float(a["disponible"]) <= 0]
    retour = _resultat(_constater(m6))
    ((identifiant, charge),) = _publies()
    assert identifiant == retour["evenement_id"] == charge["evenement_id"]
    assert charge["articles_suivis"] == len(lecture["articles"]) == 2
    assert charge["articles_en_rupture"] == len(en_rupture) == 1
    assert charge["reservations_actives"] == 1 == len(lecture["reservations_actives"])
    assert charge["reservations_incompletes"] == 1, "gouttière réservée, vis à commander : partiel"
    assert charge["articles_sur_reserves"] == 0
    texte = json.dumps(charge, ensure_ascii=False)
    for fuite in (aide.GOUTTIERE, aide.VIS, "DEVIS-A", "CH-A", "70", "PO-DEPOT"):
        assert fuite not in texte
    assert set(charge) == {
        "evenement_id",
        "date_reference",
        "version_donnees",
        "articles_suivis",
        "articles_en_rupture",
        "articles_sur_reserves",
        "reservations_actives",
        "reservations_incompletes",
        "constate_le",
    }


def test_une_reservation_prete_n_est_pas_incomplete(base, m6):
    aide._recevoir(m6, aide.GOUTTIERE, 150.0, "PO-DEPOT-1")
    aide._accepter(aide._devis("DEVIS-A", "CH-A", gouttiere="100", vis=None))
    _resultat(_constater(m6))
    ((_, charge),) = _publies()
    assert (charge["reservations_actives"], charge["reservations_incompletes"], charge["articles_en_rupture"]) == (
        1,
        0,
        0,
    )


def test_rejouer_le_meme_constat_ne_publie_rien_un_autre_instant_est_un_evenement_de_plus(base, m6):
    aide._recevoir(m6, aide.GOUTTIERE, 100.0, "PO-DEPOT-1")
    premier = _resultat(_constater(m6))
    assert _resultat(_constater(m6))["evenement_id"] == premier["evenement_id"] and len(_publies()) == 1
    plus_tard = _resultat(_constater(m6, PLUS_TARD))
    assert plus_tard["version_donnees"] == premier["version_donnees"] and plus_tard["date_reference"] == JOUR
    assert plus_tard["evenement_id"] != premier["evenement_id"] and len(_publies()) == 2
    lendemain = _resultat(_constater(m6, LENDEMAIN))
    assert lendemain["date_reference"] == "2026-10-16" and len(_publies()) == 3


def test_un_retour_a_une_version_anterieure_publie_un_evenement_distinct_de_la_premiere(base, m6):
    """A (rien de réservé), B (un devis réserve), A (la réservation est libérée) : trois événements, pas deux."""
    aide._recevoir(m6, aide.GOUTTIERE, 100.0, "PO-DEPOT-1")
    a1 = _resultat(_constater(m6, "2026-10-15T09:00:00-04:00"))
    aide._accepter(aide._devis("DEVIS-A", "CH-A", gouttiere="100", vis=None))
    b = _resultat(_constater(m6, "2026-10-15T10:00:00-04:00"))
    aide._outil(
        m6,
        "m6_liberer_reservation",
        {"devis_id": "DEVIS-A", "motif": "chantier annulé par le client", "horodatage": aide.H_ACTION},
    )
    a2 = _resultat(_constater(m6, "2026-10-15T11:00:00-04:00"))
    assert a1["version_donnees"] == a2["version_donnees"] != b["version_donnees"]
    assert len({a1["evenement_id"], b["evenement_id"], a2["evenement_id"]}) == 3 and len(_publies()) == 3


@pytest.mark.parametrize("horodatage", ["hier", "2026-10-15", "2026-10-15T12:00:00", "", None])
def test_horodatage_illisible_ou_sans_fuseau_refuse_sans_rien_publier(base, m6, horodatage):
    reponse = _constater(m6, horodatage)
    if reponse["ok"] is True:
        assert reponse["resultat"]["accepte"] is False
    assert _publies() == []


def test_hors_transaction_refuse_sans_rien_lire(m6):
    reponse = m6["m6_constater_disponibilite"].fonction(INSTANT)
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-M6-TRANSACTION-REQUISE"


def test_sur_reserve_quand_le_hors_main_depasse_ce_qui_reste(base, m6):
    """Le registre des réservations en retard sur celui des transferts : réservé > en main, compté, jamais masqué."""
    aide._recevoir(m6, aide.GOUTTIERE, 100.0, "PO-DEPOT-1")
    aide._accepter(aide._devis("DEVIS-A", "CH-A", gouttiere="100", vis=None))
    faits_avant = aide._maillons("reservations")
    aide._transferer(m6, "T-REBUT-1", {"type": "inconnu"}, {"type": "rebut"}, 30.0, motif="gouttières bosselées")
    charge = constat_disponibilite.charge_disponibilite(
        aide._maillons("principal"), aide._maillons("emplacements"), faits_avant, JOUR, INSTANT
    )
    assert charge["articles_sur_reserves"] == 1 and charge["articles_en_rupture"] == 1  # disponible = 100 - 30 - 100
    assert charge["articles_suivis"] == 1 and charge["reservations_actives"] == 1
