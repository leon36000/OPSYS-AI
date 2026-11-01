"""Revue adverse rvi : un second lien lead -> client ne redirige pas le profil de propriété vers un autre client.

M2 établit UN client par lead (premier lien). M5 garde le premier lien ; M7 refuse (quarantaine visible) un lien
contradictoire. M3 et M4 rangeaient les deux et lisaient le DERNIER : un événement rejoué ou forgé avec un autre
`client_id` leur faisait lire le profil de propriété (étages, année de construction) d'un AUTRE client.
Données fictives.
"""

from __future__ import annotations

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m3_estimation import outils_site_vision as site
from m3_estimation import profils_recus as pr3
from m4_field_ops import contexte_propriete as cp4

from opsys import evenements

FICTIF = True
M2, M3, M4 = "m02-revenue-crm", "m03-estimation", "m04-field-ops"
CLIENT_A = ch.empreinte("client", "cl-a")
CLIENT_B = ch.empreinte("client", "cl-b")


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch, (M3, M4))
    m.surveiller(monkeypatch)
    yield m
    im.demonter()


def _publier_liens_et_profils():
    evenements.publier("m2.client_associe", M2, ch.client_associe(lead_id="lead-1", client_id=CLIENT_A),
                       evenement_id="l1")
    evenements.publier("m2.client_associe", M2, ch.client_associe(lead_id="lead-1", client_id=CLIENT_B),
                       evenement_id="l2")
    for ident, client, propriete, etages, annee in (
            ("p-a", CLIENT_A, "pa", 2, 1987), ("p-b", CLIENT_B, "pb", 6, 1950)):
        evenements.publier(
            "m2.profil_propriete_confirme", M2,
            ch.profil_propriete(propriete_id=ch.empreinte("p", propriete), client_id=client, etages=etages,
                                annee_construction=annee),
            evenement_id=ident)


def _contexte_m3(lead="lead-1"):
    with im.stockage.transaction():
        reponse = site.construire_contexte_site(lead, "toiture", "2026-11-02")
    assert reponse["accepte"] is True, reponse
    return {f["facteur"]: f for f in reponse["resultat"]["contexte"]["facteurs"]}


def test_m3_un_second_lien_contradictoire_ne_redirige_pas_vers_le_profil_d_un_autre_client(monde):
    _publier_liens_et_profils()
    monde.repartir()
    facteurs = _contexte_m3()
    assert facteurs["age"]["valeur"] == {"annee_construction": 1987}, "profil d'un AUTRE client lu"
    assert facteurs["hauteur"]["valeur"] == {"etages": 2}


def test_m3_le_lien_contradictoire_est_refuse_visiblement_en_quarantaine_et_le_premier_reste(monde):
    _publier_liens_et_profils()
    monde.repartir()
    liens = [m for m in monde.registre(M3, pr3.REGISTRE_LIENS) if m.get("type_entree") == pr3.TYPE_LIEN]
    assert [m["client_id"] for m in liens] == [CLIENT_A]
    quarantaine = [q for q in monde.quarantaines() if q["consommateur"] == M3]
    assert [q["evenement_id"] for q in quarantaine] == ["l2"]
    assert "CONFLIT_FAIT_M2_CLIENT_ASSOCIE" in quarantaine[0]["derniere_erreur"]


def test_m4_un_second_lien_contradictoire_ne_redirige_pas_vers_le_profil_d_un_autre_client(monde):
    _publier_liens_et_profils()
    monde.repartir()
    liens = monde.registre(M4, cp4.REGISTRE_LIENS)
    profils = monde.registre(M4, cp4.REGISTRE_PROFILS)
    contexte = cp4.contexte_du_lead(liens, profils, "lead-1")
    assert contexte["statut"] == cp4.STATUT_RECU and contexte["etages"] == 2 and contexte["annee_construction"] == 1987
    assert [m["client_id"] for m in liens if m.get("type_entree") == cp4.TYPE_LIEN] == [CLIENT_A]


def test_le_meme_lien_rejoue_sous_un_autre_identifiant_reste_un_deja_recu_sans_quarantaine(monde):
    evenements.publier("m2.client_associe", M2, ch.client_associe(lead_id="lead-1", client_id=CLIENT_A),
                       evenement_id="l1")
    evenements.publier("m2.client_associe", M2, ch.client_associe(lead_id="lead-1", client_id=CLIENT_A),
                       evenement_id="l1-bis")
    resume = monde.repartir()
    assert resume["quarantaines"] == 0 and resume["echecs"] == 0
    assert len([m for m in monde.registre(M3, pr3.REGISTRE_LIENS)]) == 1


def test_deux_leads_de_deux_clients_gardent_chacun_leur_lien(monde):
    evenements.publier("m2.client_associe", M2, ch.client_associe(lead_id="lead-1", client_id=CLIENT_A),
                       evenement_id="l1")
    evenements.publier("m2.client_associe", M2, ch.client_associe(lead_id="lead-2", client_id=CLIENT_B),
                       evenement_id="l2")
    assert monde.repartir()["quarantaines"] == 0


def test_pures_le_premier_lien_fait_foi_pour_les_registres_deja_contradictoires():
    """Registre déjà pollué (deux liens pour un lead) : le PREMIER fait foi, comme chez M5."""
    liens = [{"type_entree": pr3.TYPE_LIEN, "lead_id": "l", "client_id": CLIENT_A},
             {"type_entree": pr3.TYPE_LIEN, "lead_id": "l", "client_id": CLIENT_B}]
    profils = [pr3.fait_profil(ch.profil_propriete(propriete_id=ch.empreinte("p", "pa"), client_id=CLIENT_A,
                                                   etages=2, annee_construction=1987)),
               pr3.fait_profil(ch.profil_propriete(propriete_id=ch.empreinte("p", "pb"), client_id=CLIENT_B,
                                                   etages=6, annee_construction=1950))]
    profil, statut = pr3.profil_pour_contexte(liens, profils, "l")
    assert statut == pr3.STATUT_REPRIS and profil["faits"]["age"] == {"annee_construction": 1987}
    liens4 = [{**x, "type_entree": cp4.TYPE_LIEN} for x in liens]
    profils4 = [cp4.fait_profil(ch.profil_propriete(propriete_id=ch.empreinte("p", "pa"), client_id=CLIENT_A,
                                                     etages=2, annee_construction=1987)),
                cp4.fait_profil(ch.profil_propriete(propriete_id=ch.empreinte("p", "pb"), client_id=CLIENT_B,
                                                     etages=6, annee_construction=1950))]
    assert cp4.contexte_du_lead(liens4, profils4, "l")["annee_construction"] == 1987
