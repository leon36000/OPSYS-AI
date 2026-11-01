"""M2 -> M3 et M2 -> M4 : le profil de propriété CONFIRMÉ alimente le contexte de site et la préparation d'un chantier.

Bus réel, consommateurs réels. M3 : `m3_construire_contexte_site` reprend le profil du bus seulement s'il est
confirmé, non
ambigu et que l'appelant n'en fournit pas. M4 : bloc `contexte_propriete` HORS verdict (l'empreinte de préparation ne
change
pas). Données fictives.
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
CLIENT = ch.empreinte("client", "cl-1")


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch, (M3, M4))
    m.surveiller(monkeypatch)
    yield m
    im.demonter()


def _contexte(lead="lead-1", **plus):
    with im.stockage.transaction():
        reponse = site.construire_contexte_site(lead, "toiture", "2026-11-02", **plus)
    assert reponse["accepte"] is True, reponse
    return reponse["resultat"]


def _facteur(resultat, nom):
    return next(f for f in resultat["contexte"]["facteurs"] if f["facteur"] == nom)


def _lien(lead="lead-1", client=CLIENT, ident="l1"):
    evenements.publier("m2.client_associe", M2, ch.client_associe(lead_id=lead, client_id=client), evenement_id=ident)


def _profil(propriete="p1", revision=1, client=CLIENT, ident="pr1", **plus):
    evenements.publier(
        "m2.profil_propriete_confirme",
        M2,
        ch.profil_propriete(propriete_id=ch.empreinte("p", propriete), revision=revision, client_id=client, **plus),
        evenement_id=ident,
    )


def test_sans_profil_le_contexte_dit_inconnu_et_n_invente_rien(monde):
    r = _contexte()
    assert _facteur(r, "age")["statut"] == "inconnu" and "profil_propriete_du_bus" not in r


def test_le_profil_confirme_est_repris_avec_sa_source_et_une_nouvelle_version(monde):
    v1 = _contexte()
    _lien()
    _profil(etages=2, annee_construction=1987)
    monde.repartir()
    v2 = _contexte()
    assert v2["profil_propriete_du_bus"] == "repris"
    assert v2["contexte"]["version"] == v1["contexte"]["version"] + 1 and v2["nouvelle_version"] is True
    assert _facteur(v2, "age")["statut"] == "connu" and _facteur(v2, "age")["valeur"] == {"annee_construction": 1987}
    assert _facteur(v2, "hauteur")["valeur"] == {"etages": 2}
    source = _facteur(v2, "age")["sources"][0]
    assert source["type"] == "profil_m2" and source["reference"].endswith("@r1")
    # M3 a aussi publié son contexte (version 2) : le fait n'embarque ni adresse ni contact.
    assert monde.ecritures_hors_propriete() == []


def test_la_revision_la_plus_haute_fait_foi_quel_que_soit_l_ordre_de_livraison(monde):
    _lien()
    _profil(revision=2, ident="pr2", etages=3, annee_construction=2001)
    _profil(revision=1, ident="pr1", etages=2, annee_construction=1987)
    monde.repartir()
    assert _facteur(_contexte(), "age")["valeur"] == {"annee_construction": 2001}


def test_deux_proprietes_confirmees_sont_ambigues_et_rien_n_est_devine(monde):
    _lien()
    _profil("p1", ident="pr1", etages=2, annee_construction=1987)
    _profil("p2", ident="pr2", etages=1, annee_construction=1950)
    monde.repartir()
    r = _contexte()
    assert r["profil_propriete_du_bus"] == "ambigu" and _facteur(r, "age")["statut"] == "inconnu"


def test_un_profil_sans_lien_lead_client_n_est_pas_repris(monde):
    _profil(etages=2, annee_construction=1987)
    monde.repartir()
    assert _facteur(_contexte(), "age")["statut"] == "inconnu"


def test_le_profil_d_un_autre_client_n_est_pas_repris(monde):
    _lien(client=ch.empreinte("client", "autre"))
    _profil(client=CLIENT, etages=2, annee_construction=1987)
    monde.repartir()
    assert _facteur(_contexte(), "age")["statut"] == "inconnu"


def test_le_profil_fourni_par_l_appelant_l_emporte_sur_le_bus(monde):
    _lien()
    _profil(etages=2, annee_construction=1987)
    monde.repartir()
    fourni = {
        "identifiant": "profil-fourni",
        "version": "v1",
        "recu_le": "2026-11-01T09:00:00-04:00",
        "faits": {"age": {"annee_construction": 1999}},
    }
    r = _contexte(profil_propriete=fourni)
    assert _facteur(r, "age")["valeur"] == {"annee_construction": 1999} and "profil_propriete_du_bus" not in r


def test_un_fait_hors_bornes_est_ecarte_pas_tronque(monde):
    _lien()
    _profil(etages=12, annee_construction=1987)
    monde.repartir()
    r = _contexte()
    assert _facteur(r, "hauteur")["statut"] == "inconnu" and _facteur(r, "age")["statut"] == "connu"


def test_profil_pour_contexte_pur():
    liens = [pr3.fait_lien(ch.client_associe(lead_id="l", client_id=CLIENT))]
    profil = pr3.fait_profil(ch.profil_propriete(client_id=CLIENT))
    assert pr3.profil_pour_contexte(liens, [], "l") == (None, pr3.STATUT_ABSENT)
    assert pr3.profil_pour_contexte([], [profil], "l") == (None, pr3.STATUT_ABSENT)
    repris, statut = pr3.profil_pour_contexte(liens, [profil], "l")
    assert statut == pr3.STATUT_REPRIS and repris["faits"] == {
        "hauteur": {"etages": 2},
        "age": {"annee_construction": 1987},
    }
    sans_fait = pr3.fait_profil(ch.profil_propriete(client_id=CLIENT, etages=12, annee_construction=1987))
    sans_fait["annee_construction"] = None
    assert pr3.profil_pour_contexte(liens, [sans_fait], "l") == (None, pr3.STATUT_SANS_FAIT)


# ------------------------------------------------------------------------------------------------ M4
def test_contexte_propriete_de_m4_recu_ambigu_absent():
    lien = cp4.fait_lien(ch.client_associe(lead_id="l", client_id=CLIENT))
    p1 = cp4.fait_profil(ch.profil_propriete(propriete_id=ch.empreinte("p", "a"), client_id=CLIENT))
    p2 = cp4.fait_profil(ch.profil_propriete(propriete_id=ch.empreinte("p", "b"), client_id=CLIENT))
    assert cp4.contexte_du_lead([], [p1], "l")["statut"] == cp4.STATUT_ABSENT
    assert cp4.contexte_du_lead([lien], [], "l")["statut"] == cp4.STATUT_ABSENT
    assert cp4.contexte_du_lead([lien], [p1], "l")["statut"] == cp4.STATUT_RECU
    assert cp4.contexte_du_lead([lien], [p1, p2], "l")["statut"] == cp4.STATUT_AMBIGU
    recu = cp4.contexte_du_lead([lien], [p1], "l")
    assert "adresse" not in recu and "ville" not in recu and recu["etages"] == 2


def test_m4_garde_la_derniere_revision(monde):
    _lien()
    _profil(revision=1, ident="a", etages=2)
    _profil(revision=2, ident="b", etages=3)
    monde.repartir()
    with im.stockage.transaction():
        from opsys import stockage

        liens = list(stockage.maillons(M4, cp4.REGISTRE_LIENS))
        profils = list(stockage.maillons(M4, cp4.REGISTRE_PROFILS))
    assert cp4.contexte_du_lead(liens, profils, "lead-1")["etages"] == 3
