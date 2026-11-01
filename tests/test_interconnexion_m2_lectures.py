"""M2 reçoit M7 (conversions hors ligne), M5 (relances de créance) et M3 (contexte de site) et les LIT sans rien
écraser.

Bus réel et consommateurs réels de M2 ; le lead est ingéré par le vrai outil de M2. Prouve : le contrat du lead n'est
jamais
réécrit, `source_connue` du score ne s'allume que pour une source NORMALISÉE de CE lead, la relance de créance avertit
sans
supprimer, le coach dit le contexte de site. Données fictives.
"""

from __future__ import annotations

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m2_revenue_crm import faits_interconnexion as fi
from m2_revenue_crm import liste_leads, outils, outils_ventes, relances, scoring_faits

from opsys import evenements

FICTIF = True
M2, M3, M5, M7 = "m02-revenue-crm", "m03-estimation", "m05-financecore", "m07-marketing"
HORO = "2026-10-20T09:00:00-04:00"
MAINTENANT = "2026-11-02T10:00:00-05:00"


def _contrat(lead_id, **plus):
    base = {
        "lead_id": lead_id,
        "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": f"Client {lead_id}", "telephone": "418-555-0199", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale",
        "ville": "Québec",
        "urgence_declaree": False,
        "canal": "telephone",
    }
    base.update(plus)
    return base


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch, (M2, M3, M5, M7))
    m.surveiller(monkeypatch)
    yield m
    im.demonter()


def _ingerer(lead_id, **plus):
    reponse = outils.ingerer_lead(_contrat(lead_id, **plus), HORO)
    assert reponse["accepte"] is True, reponse


def _faits_score(lead_id):
    with im.stockage.transaction():
        contexte_score, absent = outils_ventes._contexte_score(MAINTENANT)
        assert absent is None
        return scoring_faits.faits_du_lead(contexte_score, lead_id)


def _contrat_range(lead_id):
    with im.stockage.transaction():
        fiche = liste_leads.fiches_des_leads(outils._obtenir_registre().lire())[lead_id]
    return dict(fiche.contrat)


def test_conversion_normalisee_allume_source_connue_sans_reecrire_le_contrat(monde):
    _ingerer("lead-a")
    assert _faits_score("lead-a")["source_connue"] is False
    contrat_avant = _contrat_range("lead-a")
    evenements.publier(
        "m7.conversion_hors_ligne_importee",
        M7,
        ch.conversion_hors_ligne(lead_id="lead-a", source="google"),
        evenement_id="c1",
    )
    monde.repartir()
    assert _faits_score("lead-a")["source_connue"] is True
    assert _contrat_range("lead-a") == contrat_avant  # lecture : le contrat de M2 n'est jamais réécrit
    assert monde.ecritures_hors_propriete() == []


def test_conversion_sans_source_normalisee_n_allume_rien(monde):
    _ingerer("lead-b")
    evenements.publier(
        "m7.conversion_hors_ligne_importee",
        M7,
        ch.conversion_hors_ligne(lead_id="lead-b", source=None),
        evenement_id="c1",
    )
    monde.repartir()
    assert _faits_score("lead-b")["source_connue"] is False


def test_conversion_d_un_autre_lead_n_allume_rien_pour_celui_ci(monde):
    _ingerer("lead-c")
    _ingerer("lead-d")
    evenements.publier(
        "m7.conversion_hors_ligne_importee",
        M7,
        ch.conversion_hors_ligne(lead_id="lead-d", source="meta"),
        evenement_id="c1",
    )
    monde.repartir()
    assert _faits_score("lead-c")["source_connue"] is False and _faits_score("lead-d")["source_connue"] is True


def test_conversion_d_un_lead_inconnu_est_rangee_sans_effet_ni_quarantaine(monde):
    evenements.publier(
        "m7.conversion_hors_ligne_importee", M7, ch.conversion_hors_ligne(lead_id="lead-fantome"), evenement_id="c1"
    )
    resume = monde.repartir()
    assert resume["quarantaines"] == 0 and monde.taille(M2, fi.REGISTRE_CONVERSIONS) == 1


def test_la_source_du_contrat_reste_prioritaire(monde):
    _ingerer("lead-e", source="formulaire-web")
    assert _faits_score("lead-e")["source_connue"] is True  # déjà connue du contrat : rien à changer


def test_coach_dit_le_contexte_de_site_la_creance_et_la_conversion_sans_inventer(monde):
    _ingerer("lead-f")
    client_id = outils.clients.client_de_lead(outils._obtenir_registre(), "lead-f")
    assert client_id
    evenements.publier("m3.contexte_site_pret", M3, ch.contexte_site(lead_id="lead-f"), evenement_id="s1")
    evenements.publier("m5.creance_relance_preparee", M5, ch.creance_relance(client_id=client_id), evenement_id="r1")
    evenements.publier(
        "m7.conversion_hors_ligne_importee", M7, ch.conversion_hors_ligne(lead_id="lead-f"), evenement_id="c1"
    )
    monde.repartir()
    with im.stockage.transaction():
        dossier, refus = outils_ventes._dossier_coach(outils._obtenir_registre(), "lead-f", MAINTENANT)
    assert refus is None
    genres = {f["genre"] for f in dossier["faits"]}
    assert {"creance", "contexte_site", "conversion_hors_ligne"} <= genres
    texte = " ".join(str(f) for f in dossier["faits"])
    assert "niveau 1" in texte and "1 facteur(s) connu(s)" in texte and "1 à vérifier" in texte
    assert "n'établit aucune causalité" in texte and "Rien n'est comblé" in texte
    assert "4500" not in texte  # aucun montant de créance ni valeur de conversion dans le dossier du coach


def test_contexte_site_garde_les_versions_et_la_derniere_fait_foi(monde):
    evenements.publier("m3.contexte_site_pret", M3, ch.contexte_site(lead_id="lead-g", version=1), evenement_id="s1")
    evenements.publier(
        "m3.contexte_site_pret",
        M3,
        ch.contexte_site(
            lead_id="lead-g",
            version=2,
            inconnus=[],
            a_verifier=[],
            facteurs=[{"facteur": "type_batiment", "statut": "connu", "valeur": "x"}],
        ),
        evenement_id="s2",
    )
    monde.repartir()
    with im.stockage.transaction():
        derniere = fi.contexte_site_du_lead(list(im.stockage.maillons(M2, fi.REGISTRE_CONTEXTES_SITE)), "lead-g")
    assert derniere["version"] == 2 and derniere["a_verifier"] == 0


# ------------------------------------------------------------------------------------------------ fonctions pures
def test_creances_par_client_garde_la_plus_avancee():
    faits = [
        fi.fait_creance(ch.creance_relance(relance_id="r1", niveau=1)),
        fi.fait_creance(ch.creance_relance(relance_id="r2", niveau=3, jours_retard=40)),
        fi.fait_creance(ch.creance_relance(relance_id="r3", niveau=2, client_id="autre")),
    ]
    par_client = fi.creances_par_client(faits)
    assert par_client["client-fictif-1"]["niveau"] == 3 and par_client["autre"]["niveau"] == 2


def test_item_de_relance_porte_la_creance_seulement_quand_elle_existe():
    creance = fi.fait_creance(ch.creance_relance(niveau=2))
    evaluation = {"lead_id": "l", "statut": "qualifie", "proprietaire": "p"}
    segment = {"segment": "quote_stale", "donnee": {"devis_id": "d", "horodatage_devis": HORO, "seuil_jours": 14}}
    commun = dict(
        instant=relances.segments.instant_utc(MAINTENANT),
        jours_entre=7,
        leads_de_la_personne=frozenset({"l"}),
        devis_par_id={},
        consentements_contact=[],
        retraits=[],
        preparees=[],
    )
    sans = relances._item(evaluation, "relance_devis_sans_reponse", segment, **commun)
    avec = relances._item(evaluation, "relance_devis_sans_reponse", segment, creance=creance, **commun)
    assert "creance_en_retard" not in sans
    assert avec["creance_en_retard"] == {"niveau": 2, "jours_retard": 12, "relance_id": "relance-fictive-1"}
    assert {
        k: v for k, v in avec.items() if k != "creance_en_retard"
    } == sans  # rien d'autre ne change : jamais bloquée
