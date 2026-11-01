"""Alimentation du graphe par les événements du bus : brouillon d'arête, confirmation si sensible, minimisation.

Sur le moteur SQL (base migrée) et sur le double. Données fictives.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from opsys.mnemo import codes
from opsys.mnemo.codes import ErreurMnemo
from opsys.mnemo.graphe import GrapheMemoire, GrapheSql, NoeudRef, alimentation

FICTIF = True
T0 = "2026-11-01T12:00:00+00:00"
CLIENT = hashlib.sha256(b"client-fictif").hexdigest()
PROPRIETE = hashlib.sha256(b"propriete-fictive").hexdigest()
LIGNE = "a" * 64
HUMAIN = {"par": "direction.fictive", "mode": "humain", "role": "admin"}


@pytest.fixture(params=["sql", "memoire"])
def moteur(request, session):
    if request.param == "memoire":
        yield GrapheMemoire()
        return
    with session() as cnx:
        yield GrapheSql(cnx)


def client_de_lead(table):
    return lambda lead: table.get(lead)


def wct(**plus):
    return {
        "wct_id": "W-1",
        "intervention_id": "I-1",
        "lead_id": "L-1",
        "technicien_id": "tech-fictif-1",
        "horodatage_completion": "2026-09-15T14:00:00-04:00",
        "ville": "Laval",
        "devis_id": "D-1",
        **plus,
    }


def variance(**plus):
    return {
        "evenement_id": "V-1",
        "wct_id": "W-1",
        "intervention_id": "I-1",
        "chantier_id": None,
        "statut_variance": "evaluee",
        "horodatage_completion": "2026-09-15T14:00:00-04:00",
        "lignes": [
            {
                "materiau": "mat-a",
                "unite": "u",
                "quantite_prevue": "10",
                "quantite_reelle": "12",
                "ecart_pourcentage": "0.2",
                "critique": False,
            },
            {
                "materiau": "mat-b",
                "unite": "u",
                "quantite_prevue": "4",
                "quantite_reelle": "0",
                "ecart_pourcentage": "-1",
                "critique": False,
            },
        ],
        **plus,
    }


def appliquer(moteur, type_evenement, charge, table=None, ligne=LIGNE):
    source = alimentation.source_de(
        type_evenement, charge, None if type_evenement == "m2.profil_propriete_confirme" else ligne
    )
    plan = alimentation.planifier(type_evenement, charge, source_ref=source, client_de_lead=client_de_lead(table or {}))
    return alimentation.appliquer(moteur, plan, type_evenement=type_evenement, source_ref=source, quand=T0)


def test_un_client_associe_ne_cree_qu_un_noeud_pseudonyme(moteur):
    r = appliquer(
        moteur,
        "m2.client_associe",
        {"lead_id": "L-1", "client_id": CLIENT, "horodatage_association": "2026-09-01T10:00:00-04:00"},
    )
    assert r["noeuds"] == 1 and r["aretes_proposees"] == 0
    n = moteur.noeud("client", CLIENT)
    assert n.libelle == f"client·{CLIENT[:8]}"


def test_client_propriete_est_sensible_donc_brouillon_en_attente_d_une_personne(moteur):
    charge = {
        "fait_id": "f" * 64,
        "client_id": CLIENT,
        "propriete_id": PROPRIETE,
        "revision": 1,
        "ville": "Laval",
        "type_batiment": "maison",
        "etages": 2,
        "annee_construction": 1990,
        "nb_photos_liees": 0,
        "nb_mesures_liees": 0,
        "horodatage": "2026-09-10T09:00:00-04:00",
    }
    r = appliquer(moteur, "m2.profil_propriete_confirme", charge)
    assert r["aretes_proposees"] == 1 and r["en_attente_confirmation"] == 1 and r["aretes_confirmees_systeme"] == 0
    [attente] = moteur.en_attente()
    assert attente.type == "possede" and attente.etat == "brouillon" and attente.sensible
    assert attente.source_ref == "bus:m2.profil_propriete_confirme:" + "f" * 64
    assert attente.source_type == "bus:m2.profil_propriete_confirme"
    vide = moteur.voisinage(NoeudRef("client", CLIENT), 1, a_la_date="2026-12-01")
    assert len(vide.noeuds) == 1  # tant qu'une personne n'a pas confirmé, la relation ne répond à aucune question
    moteur.confirmer_arete(attente.arete_id, quand=T0, raison="Vérifié sur le dossier", **HUMAIN)
    plein = moteur.voisinage(NoeudRef("client", CLIENT), 1, a_la_date="2026-12-01")
    assert len(plein.noeuds) == 2
    assert "ville" not in json.dumps(plein.vers_json()) and "Laval" not in json.dumps(plein.vers_json())


def test_une_intervention_est_liee_a_son_client_si_le_client_du_lead_est_connu(moteur):
    r = appliquer(moteur, "m4.travaux_termines", wct(), {"L-1": CLIENT})
    assert r["noeuds"] == 2 and r["aretes_proposees"] == 1 and r["en_attente_confirmation"] == 1
    assert moteur.noeud("intervention", "I-1") is not None
    sans = appliquer(moteur, "m4.travaux_termines", wct(intervention_id="I-2", lead_id="L-9"), {"L-1": CLIENT})
    assert (
        sans["aretes_proposees"] == 0 and sans["ignores"] == ["client_inconnu"] and moteur.noeud("intervention", "I-2")
    )


def test_aucune_donnee_personnelle_ne_passe_de_la_charge_au_graphe(moteur):
    appliquer(moteur, "m4.travaux_termines", wct(), {"L-1": CLIENT})
    appliquer(moteur, "m6.variance_chantier", variance())
    tout = json.dumps(
        moteur.voisinage(
            NoeudRef("intervention", "I-1"), 4, a_la_date="2026-12-01", inclure_brouillons=True
        ).vers_json(),
        ensure_ascii=False,
    )
    for interdit in ("tech-fictif-1", "Laval", "technicien", "L-1", "D-1", "lead", "ville"):
        assert interdit not in tout, interdit


def test_variance_relie_seulement_les_materiaux_reellement_utilises_et_confirme_seule(moteur):
    r = appliquer(moteur, "m6.variance_chantier", variance())
    assert r["aretes_proposees"] == 1 and r["aretes_confirmees_systeme"] == 1 and r["en_attente_confirmation"] == 0
    v = moteur.voisinage(NoeudRef("intervention", "I-1"), 1, a_la_date="2026-12-01")
    assert {n.cle for n, _ in v.noeuds} == {"I-1", "mat-a"}  # mat-b était prévu mais n'a pas été utilisé
    [arete] = v.aretes
    histoire = moteur.pourquoi(arete.arete_id)["historique"]
    assert [h["etat"] for h in histoire] == ["brouillon", "confirmee"] and histoire[-1]["mode"] == "systeme"


def test_une_redelivrance_ne_cree_rien_de_plus(moteur):
    appliquer(moteur, "m4.travaux_termines", wct(), {"L-1": CLIENT})
    avant = moteur.etat()
    r = appliquer(moteur, "m4.travaux_termines", wct(), {"L-1": CLIENT})
    assert r["deja_connues"] == 1 and r["aretes_proposees"] == 0 and moteur.etat() == avant
    appliquer(moteur, "m6.variance_chantier", variance())
    avant = moteur.etat()
    appliquer(moteur, "m6.variance_chantier", variance(evenement_id="V-2"))  # republication de M6 : même état
    assert moteur.etat() == avant


def test_un_identifiant_hors_schema_est_un_refus_nomme_sans_bloquer_les_autres(moteur):
    charge = variance()
    charge["lignes"].append(
        {
            "materiau": "Mat A avec espaces et @",
            "unite": "u",
            "quantite_prevue": "1",
            "quantite_reelle": "2",
            "ecart_pourcentage": "1",
            "critique": False,
        }
    )
    r = appliquer(moteur, "m6.variance_chantier", charge)
    assert r["aretes_proposees"] == 1 and {x["code"] for x in r["refus"]} == {codes.NOEUD_CLE_INVALIDE}
    pas_hex = appliquer(
        moteur,
        "m2.client_associe",
        {"lead_id": "L-1", "client_id": "Jean Tremblay", "horodatage_association": "2026-09-01T10:00:00-04:00"},
    )
    assert pas_hex["noeuds"] == 0 and pas_hex["refus"][0]["code"] == codes.NOEUD_CLE_INVALIDE
    assert moteur.noeud("client", "Jean Tremblay") is None


def test_plafond_de_materiaux_par_evenement(moteur):
    lignes = [
        {
            "materiau": f"mat-{i}",
            "unite": "u",
            "quantite_prevue": "1",
            "quantite_reelle": "1",
            "ecart_pourcentage": "0",
            "critique": False,
        }
        for i in range(alimentation.MATERIAUX_MAX + 10)
    ]
    r = appliquer(moteur, "m6.variance_chantier", variance(lignes=lignes))
    assert r["aretes_proposees"] == alimentation.MATERIAUX_MAX and "lignes_au_dela_du_plafond" in r["ignores"]


def test_evenement_non_alimente_et_champ_manquant_sont_refuses(moteur):
    with pytest.raises(ErreurMnemo, match=codes.ENTREE_INVALIDE):
        alimentation.planifier(
            "m5.rentabilite_chantier", {}, source_ref="registre:evenements:" + LIGNE, client_de_lead=lambda _l: None
        )
    with pytest.raises(ErreurMnemo, match=codes.ENTREE_INVALIDE):
        alimentation.planifier(
            "m4.travaux_termines",
            {"intervention_id": "I-1", "lead_id": "L-1"},
            source_ref="registre:evenements:" + LIGNE,
            client_de_lead=lambda _l: None,
        )
    with pytest.raises(ErreurMnemo, match=codes.ENTREE_INVALIDE):
        alimentation.planifier(
            "m6.variance_chantier",
            variance(lignes="oups"),
            source_ref="registre:evenements:" + LIGNE,
            client_de_lead=lambda _l: None,
        )


def test_une_quantite_illisible_est_notee_pas_devinee(moteur):
    charge = variance()
    charge["lignes"][0]["quantite_reelle"] = "beaucoup"
    r = appliquer(moteur, "m6.variance_chantier", charge)
    assert r["aretes_proposees"] == 0 and r["ignores"] == ["quantite_illisible"]
