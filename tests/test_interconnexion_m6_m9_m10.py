"""M5 -> M6 (rapprochement PO), M7/M8 -> M9 (signaux de gestion du briefing) et M5 -> M10 (dossiers scellés).

Bus réel, consommateurs réels. Données fictives.
"""

from __future__ import annotations

import json

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m6_material_control import outils as m6
from m6_material_control import rapprochements_recus as rr
from m9_strategic_intelligence import signaux_gestion as sg
from m10_memoire import dossiers_cpa

from opsys import contexte, evenements, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante

FICTIF = True
M5, M6, M7, M8, M9, M10 = (
    "m05-financecore",
    "m06-material-control",
    "m07-marketing",
    "m08-analytics",
    "m09-strategic-intelligence",
    "m10-memoire",
)
ADMIN = IdentiteAppelante("admin.fictif", "admin")


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch)
    m.surveiller(monkeypatch)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictif", "mot-de-passe-admin-1234", ["admin"])
    yield m
    im.demonter()


# ------------------------------------------------------------------------------------------------------ M6
def _attentes_m6():
    with stockage.transaction():
        return [a for a in m6.attentes() if a["type"] == "rapprochement_po_a_voir"]


def test_m6_attente_a_voir_pour_un_ecart_pas_pour_un_rapprochement_concordant(monde):
    evenements.publier("m5.rapprochement_po_constate", M5, ch.rapprochement_po(facture="ff-ok"), evenement_id="r1")
    evenements.publier(
        "m5.rapprochement_po_constate",
        M5,
        ch.rapprochement_po(
            facture="ff-ecart",
            po_id="po-9",
            verdict="ECART",
            sens="FACTURE_SUPERIEURE_AU_RECU",
            ecart_avant_taxes="85.00",
        ),
        evenement_id="r2",
    )
    monde.repartir()
    attentes = _attentes_m6()
    assert [a["id"] for a in attentes] == ["ff-ecart"]
    assert attentes[0]["action_proposee"] == "m5_lister_comptes_a_payer" and "po-9" in attentes[0]["resume"]
    assert "1200" not in json.dumps(attentes) and "85.00" not in json.dumps(attentes)  # aucun montant dans l'attente
    assert monde.ecritures_hors_propriete() == []


def test_m6_le_dernier_etat_d_une_facture_fait_foi_et_leve_l_attente(monde):
    evenements.publier(
        "m5.rapprochement_po_constate",
        M5,
        ch.rapprochement_po(
            facture="ff-1", verdict="ECART", sens="FACTURE_INFERIEURE_AU_RECU", date_reference="2026-10-29"
        ),
        evenement_id="r1",
    )
    monde.repartir()
    assert len(_attentes_m6()) == 1
    evenements.publier(
        "m5.rapprochement_po_constate",
        M5,
        ch.rapprochement_po(facture="ff-1", verdict="CONCORDANT", date_reference="2026-10-31"),
        evenement_id="r2",
    )
    monde.repartir()
    assert _attentes_m6() == []


def test_m6_un_ancien_etat_livre_apres_le_recent_ne_le_remplace_pas(monde):
    evenements.publier(
        "m5.rapprochement_po_constate",
        M5,
        ch.rapprochement_po(facture="ff-1", verdict="CONCORDANT", date_reference="2026-10-31"),
        evenement_id="r2",
    )
    monde.repartir()
    evenements.publier(
        "m5.rapprochement_po_constate",
        M5,
        ch.rapprochement_po(
            facture="ff-1", verdict="ECART", sens="FACTURE_INFERIEURE_AU_RECU", date_reference="2026-10-29"
        ),
        evenement_id="r1",
    )
    monde.repartir()
    assert _attentes_m6() == []


def test_m6_incomplet_est_a_voir_et_sans_facture_non():
    base = ch.rapprochement_po()
    faits = [
        rr.fait({**base, "facture_fournisseur_id": "a", "verdict": "INCOMPLET"}),
        rr.fait({**base, "facture_fournisseur_id": "b", "verdict": "SANS_FACTURE"}),
    ]
    assert [a["id"] for a in rr.attentes(faits)] == ["a"]


# ------------------------------------------------------------------------------------------------------ M9
def _briefing(monde, maintenant="2026-11-02T07:00:00-05:00"):
    capacites = Capacites(monde.departements, stockage.transaction, filtre={M9}, memoire=False)
    with contexte.appele_par_appareil(ADMIN):
        reponse = capacites.appeler("m9_produire_briefing_matin", {"maintenant": maintenant})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def test_m9_briefing_sans_signal_n_a_pas_la_section(monde):
    assert "signaux_de_gestion" not in _briefing(monde)


def test_m9_briefing_porte_les_anomalies_de_m7_et_la_consolidation_de_m8_sans_valeurs(monde):
    evenements.publier(
        "m7.anomalie_depense_detectee",
        M7,
        ch.anomalie_depense(severite="critique", jour_fin="2026-11-01", jour_debut="2026-11-01"),
        evenement_id="a1",
    )
    evenements.publier("m8.fait_consolide", M8, ch.fait_consolide(), evenement_id="f1")
    monde.repartir()
    briefing = _briefing(monde)
    section = briefing["signaux_de_gestion"]
    assert section["anomalies_depense"]["affichees"][0]["severite"] == "critique"
    assert "aucune" in section["anomalies_depense"]["action"]
    derniere = section["derniere_consolidation_m8"]
    assert derniere["mesures"] == 3 and derniere["calculees"] == 2
    assert derniere["non_calculables"] == ["m8_marge_reelle"] and derniere["perimees"] == ["m8_delai_acceptation"]
    assert "12.50" not in json.dumps(section)  # aucune valeur de M8 recopiée
    assert len(json.dumps(briefing, ensure_ascii=False)) <= 6000
    assert monde.ecritures_hors_propriete() == []


def test_m9_anomalie_hors_fenetre_ou_fictive_n_entre_pas(monde):
    evenements.publier(
        "m7.anomalie_depense_detectee",
        M7,
        ch.anomalie_depense(jour_fin="2026-09-01", jour_debut="2026-09-01"),
        evenement_id="a1",
    )
    evenements.publier(
        "m7.anomalie_depense_detectee",
        M7,
        ch.anomalie_depense(anomalie_id="c" * 32, jour_fin="2026-11-01", jour_debut="2026-11-01", fictif=True),
        evenement_id="a2",
    )
    monde.repartir()
    assert "signaux_de_gestion" not in _briefing(monde)


def test_m9_le_briefing_reste_borne_avec_beaucoup_de_signaux(monde):
    for i in range(40):
        evenements.publier(
            "m7.anomalie_depense_detectee",
            M7,
            ch.anomalie_depense(anomalie_id=f"{i:032x}", jour_fin="2026-11-01", jour_debut="2026-11-01"),
            evenement_id=f"a{i}",
        )
    monde.repartir(limite=500)
    briefing = _briefing(monde)
    assert briefing["signaux_de_gestion"]["anomalies_depense"]["total"] == 40
    assert len(briefing["signaux_de_gestion"]["anomalies_depense"]["affichees"]) == sg.ANOMALIES_AFFICHEES
    assert len(json.dumps(briefing, ensure_ascii=False)) <= 6000


def test_m9_consolidation_resume_seulement():
    resume = sg.fait_consolidation(ch.fait_consolide())
    assert "valeur" not in json.dumps(resume) and resume["changements_definition"] == ["m8_taux_acceptation"]


# ----------------------------------------------------------------------------------------------------- M10
def test_m10_memorise_le_dossier_scelle_financial_sans_le_rouvrir(monde):
    evenements.publier("m5.dossier_cpa_scelle", M5, ch.dossier_cpa(), evenement_id="d1")
    monde.repartir()
    (maillon,) = monde.registre(M10, "dossiers_cpa_scelles")
    assert maillon["confidentialite"] == "FINANCIAL" and maillon["producteur"] == M5
    assert maillon["horodatage"] == "2026-10-05T00:00:00+00:00" and "CPA" in maillon["mention"]
    assert maillon["liste_de_controle"] == {"A_FAIRE": 1, "A_VERIFIER": 2, "FAIT": 7}
    assert monde.ecritures_hors_propriete() == []


def test_m10_meme_dossier_sous_un_autre_sceau_est_refuse_et_le_premier_reste(monde):
    evenements.publier("m5.dossier_cpa_scelle", M5, ch.dossier_cpa(), evenement_id="d1")
    monde.repartir()
    evenements.publier("m5.dossier_cpa_scelle", M5, ch.dossier_cpa(scelle=ch.empreinte("autre")), evenement_id="d2")
    monde.repartir(passes=8)
    (maillon,) = monde.registre(M10, "dossiers_cpa_scelles")
    assert maillon["scelle"] == ch.empreinte("dossier", "dossier-2026-09")
    # Contradiction : visible d'un humain (quarantaine après les essais), jamais écrite en silence.
    assert [q["evenement_id"] for q in monde.quarantaines()] == ["d2"]
    assert "SCEAU-CONTRADICTOIRE" in monde.quarantaines()[0]["derniere_erreur"]


def test_m10_hors_forme_refuse_sans_citer_la_valeur():
    assert dossiers_cpa.extraire(ch.dossier_cpa())["fichiers"] == 9
    for charge in (
        {**ch.dossier_cpa(), "fichiers": True},
        {**ch.dossier_cpa(), "statut": "VALIDE"},
        {**ch.dossier_cpa(), "scelle": "xyz"},
        {**ch.dossier_cpa(), "extra": 1},
    ):
        with pytest.raises(dossiers_cpa.ChampRefuse) as exc:
            dossiers_cpa.extraire(charge)
        assert "xyz" not in str(exc.value)
