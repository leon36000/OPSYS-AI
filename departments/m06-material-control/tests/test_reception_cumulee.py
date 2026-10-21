"""PLAN T4.15-b (M6.7) : les livraisons d'un PO se CUMULENT — modules purs.

`reception.traiter_reception` juge UNE livraison contre la commande entière : la livraison qui complète un PO déjà
partiel y reste `RECEPTION_INFERIEURE`. `reception.evaluer_cumul` juge ce que le PO a reçu EN TOUT. Ces tests fixent
la règle (décimal exact, une ligne manquante garde le PO partiel), la livraison rangée sur la transition du PO
(`bons_commande.construire_livraison`) et la relecture des livraisons (`livraisons`, `livraisons_sans_detail`,
`livraison_deja_enregistree`). Le parcours par les outils est dans `test_reception_cumulee_outils.py`.

Identifiants et quantités fictifs (`fictif: true` au sens d'AGENTS.md).
"""

from __future__ import annotations

import math

import pytest
from m6_material_control import bons_commande, evenement_reception, fournisseurs, livre_prix, reception
from m6_material_control.registre import Registre

FICTIF = True

COMMANDE = [
    {"materiau_id": "gouttiere-5po", "quantite_demandee": 100.0},
    {"materiau_id": "vis-inox", "quantite_demandee": 20.0},
]


def _livraison(gouttiere, vis):
    return [{"materiau_id": "gouttiere-5po", "quantite_recue": gouttiere},
            {"materiau_id": "vis-inox", "quantite_recue": vis}]


def _verdict(*livraisons):
    cumul = reception.evaluer_cumul(COMMANDE, list(livraisons))
    assert cumul is not None
    return cumul["verdict_reception"]


# ------------------------------------------------------------------------------------- evaluer_cumul
def test_une_seule_livraison_complete_est_conforme():
    assert _verdict(_livraison(100.0, 20.0)) == "CONFORME"


def test_une_seule_livraison_partielle_reste_inferieure():
    assert _verdict(_livraison(40.0, 0.0)) == "RECEPTION_INFERIEURE"


def test_deux_livraisons_qui_completent_donnent_conforme():
    """Le cas du bogue : 40 + 60 gouttières et 0 + 20 vis. Chaque livraison seule est inférieure ; le cumul est
    conforme."""
    assert _verdict(_livraison(40.0, 0.0), _livraison(60.0, 20.0)) == "CONFORME"


def test_trois_livraisons_le_po_reste_partiel_jusqu_a_la_derniere():
    assert _verdict(_livraison(40.0, 0.0)) == "RECEPTION_INFERIEURE"
    assert _verdict(_livraison(40.0, 0.0), _livraison(30.0, 10.0)) == "RECEPTION_INFERIEURE"
    assert _verdict(_livraison(40.0, 0.0), _livraison(30.0, 10.0), _livraison(30.0, 10.0)) == "CONFORME"


def test_une_ligne_qui_manque_garde_le_po_partiel_meme_si_une_autre_est_en_exces():
    """120 gouttières (en excès) et 0 vis (manque) : mixte, donc le PO n'est pas reçu."""
    assert _verdict(_livraison(70.0, 0.0), _livraison(50.0, 0.0)) == "RECEPTION_MIXTE"


def test_sur_reception_cumulee_est_superieure():
    assert _verdict(_livraison(60.0, 20.0), _livraison(60.0, 0.0)) == "RECEPTION_SUPERIEURE"


def test_le_cumul_est_exact_en_decimal_jamais_en_flottant():
    """0,1 + 0,2 vaut 0,30000000000000004 en flottant : un PO de 0,3 ne serait jamais conforme. En décimal exact,
    il l'est, dans n'importe quel ordre."""
    assert math.isclose(0.1 + 0.2, 0.3) and 0.1 + 0.2 != 0.3
    commande = [{"materiau_id": "scellant", "quantite_demandee": 0.3}]
    for ordre in ((0.1, 0.2), (0.2, 0.1)):
        cumul = reception.evaluer_cumul(commande, [[{"materiau_id": "scellant", "quantite_recue": q}] for q in ordre])
        assert cumul["verdict_reception"] == "CONFORME", ordre
        assert cumul["lignes"][0]["quantite_recue_cumulee"] == "0.3" and cumul["lignes"][0]["ecart_cumule"] == "0.0"


def test_le_cumul_porte_les_quantites_et_l_ecart_en_texte_decimal():
    cumul = reception.evaluer_cumul(COMMANDE, [_livraison(40.0, 0.0), _livraison(30.0, 10.0)])

    assert cumul["lignes"] == [
        {"materiau_id": "gouttiere-5po", "quantite_demandee": "100.0", "quantite_recue_cumulee": "70.0",
         "ecart_cumule": "-30.0"},
        {"materiau_id": "vis-inox", "quantite_demandee": "20.0", "quantite_recue_cumulee": "10.0",
         "ecart_cumule": "-10.0"},
    ]


def test_le_cumul_accepte_les_quantites_deja_en_texte_decimal():
    """Les livraisons antérieures reviennent du registre en texte : même résultat qu'en nombre."""
    en_texte = [{"materiau_id": "gouttiere-5po", "quantite_recue": "40.0"},
                {"materiau_id": "vis-inox", "quantite_recue": "0.0"}]
    assert _verdict(en_texte, _livraison(60.0, 20.0)) == "CONFORME"


def test_un_materiau_hors_po_est_ignore_comme_le_fait_traiter_reception():
    hors_po = _livraison(100.0, 20.0) + [{"materiau_id": "inconnu-fictif", "quantite_recue": 999.0}]
    cumul = reception.evaluer_cumul(COMMANDE, [hors_po])
    assert cumul["verdict_reception"] == "CONFORME"
    assert [ligne["materiau_id"] for ligne in cumul["lignes"]] == ["gouttiere-5po", "vis-inox"]


@pytest.mark.parametrize("quantite", [math.nan, math.inf, -math.inf, True, None, "abc", "NaN", [1]])
def test_une_quantite_illisible_rend_none_jamais_un_cumul_devine(quantite):
    assert reception.evaluer_cumul(COMMANDE, [_livraison(quantite, 0.0)]) is None


def test_une_commande_illisible_rend_none():
    assert reception.evaluer_cumul([{"materiau_id": "x", "quantite_demandee": math.nan}], []) is None


def test_sans_aucune_livraison_le_cumul_est_a_zero_et_inferieur():
    cumul = reception.evaluer_cumul(COMMANDE, [])
    assert cumul["verdict_reception"] == "RECEPTION_INFERIEURE"
    assert [ligne["quantite_recue_cumulee"] for ligne in cumul["lignes"]] == ["0", "0"]


def test_traiter_reception_garde_son_verdict_pour_une_livraison_seule():
    """Le contrat gelé de l'accusé ne change pas : le verdict d'une livraison reste jugé contre la commande
    entière."""
    bon = {"po_id": "PO-FICT-1", "chantier_id": "CH-FICT-1", "lignes_demandees": COMMANDE, "horodatage": "h"}
    recue = {"po_id": "PO-FICT-1", "chantier_id": "CH-FICT-1", "horodatage": "h",
             "lignes_recues": _livraison(60.0, 20.0)}
    accuse = reception.traiter_reception(bon, recue, None, Registre())
    assert accuse["verdict_reception"] == "RECEPTION_INFERIEURE"


# --------------------------------------------------------------------------- construire_livraison
def _po(statut="sent_to_supplier"):
    return {"po_id": "PO-FICT-1", "chantier_id": "CH-FICT-1", "fournisseur_id": "gentek", "statut": statut,
            "lignes": [{"materiau_id": "gouttiere-5po", "quantite_demandee": 100.0},
                       {"materiau_id": "vis-inox", "quantite_demandee": 20.0}]}


def _reception(gouttiere=40.0, vis=0.0, horodatage="2026-09-29T09:15:00-04:00", po_id="PO-FICT-1",
               chantier_id="CH-FICT-1"):
    return {"po_id": po_id, "chantier_id": chantier_id, "horodatage": horodatage,
            "lignes_recues": _livraison(gouttiere, vis)}


def test_construire_livraison_range_les_quantites_en_texte_dans_l_ordre_du_po():
    livraison = bons_commande.construire_livraison(_po(), _reception(gouttiere=0.1, vis=0.0))

    assert livraison["lignes"] == [{"materiau_id": "gouttiere-5po", "quantite_recue": "0.1"},
                                   {"materiau_id": "vis-inox", "quantite_recue": "0.0"}]
    assert livraison["horodatage"] == "2026-09-29T09:15:00-04:00"
    assert len(livraison["empreinte"]) == 64


def test_l_empreinte_est_deterministe_et_change_avec_chaque_element():
    base = bons_commande.construire_livraison(_po(), _reception())
    assert bons_commande.construire_livraison(_po(), _reception())["empreinte"] == base["empreinte"]
    variantes = (
        _reception(gouttiere=41.0),
        _reception(vis=1.0),
        _reception(horodatage="2026-09-29T09:16:00-04:00"),
    )
    empreintes = {bons_commande.construire_livraison(_po(), variante)["empreinte"] for variante in variantes}
    assert base["empreinte"] not in empreintes and len(empreintes) == 3


def test_construire_livraison_est_none_quand_rien_n_apparie_le_po():
    assert bons_commande.construire_livraison(_po(), _reception(chantier_id="CH-AUTRE")) is None
    assert bons_commande.construire_livraison(_po(), _reception(po_id="PO-AUTRE")) is None
    sans_vis = {**_reception(), "lignes_recues": [{"materiau_id": "gouttiere-5po", "quantite_recue": 40.0}]}
    assert bons_commande.construire_livraison(_po(), sans_vis) is None


def test_construire_livraison_ignore_un_materiau_hors_po_et_garde_la_derniere_ligne_d_un_doublon():
    reception_po = _reception(gouttiere=10.0, vis=0.0)
    reception_po["lignes_recues"] += [{"materiau_id": "hors-po-fictif", "quantite_recue": 5.0},
                                      {"materiau_id": "gouttiere-5po", "quantite_recue": 25.0}]
    livraison = bons_commande.construire_livraison(_po(), reception_po)
    assert [ligne["quantite_recue"] for ligne in livraison["lignes"]] == ["25.0", "0.0"]


def test_construire_livraison_est_none_pour_une_quantite_illisible():
    assert bons_commande.construire_livraison(_po(), _reception(gouttiere=math.nan)) is None


# ---------------------------------------------------- livraisons, sans détail, rejeu (registre du PO)
def _registre_po_envoye():
    registre_po: list[dict] = []
    registre_fournisseurs: list[dict] = []
    registre_prix: list[dict] = []
    fournisseurs.enregistrer_fournisseur("gentek", "Gentek", "2026-01-01T00:00:00Z", registre_fournisseurs)
    for materiau in ("gouttiere-5po", "vis-inox"):
        livre_prix.enregistrer_prix(materiau, "gentek", 1.0, "CAD", "2026-01-01", registre_prix)
    po, verdict = bons_commande.creer_brouillon(
        "PO-FICT-1", "CH-FICT-1", "gentek", COMMANDE, "2026-01-02T00:00:00Z",
        registre_po, registre_prix, registre_fournisseurs)
    assert verdict is None, verdict
    bons_commande.approuver("PO-FICT-1", "2026-01-03T00:00:00Z", registre_po)
    bons_commande.generer_courriel(
        "PO-FICT-1", "2026-01-04T00:00:00Z", registre_po, registre_fournisseurs, "Entreprise")
    bons_commande.marquer_envoye("PO-FICT-1", "2026-01-05T00:00:00Z", registre_po)
    return registre_po, po


def test_enregistrer_reception_po_range_la_livraison_et_livraisons_la_relit_dans_l_ordre():
    registre_po, po = _registre_po_envoye()
    premiere = bons_commande.construire_livraison(po, _reception(gouttiere=40.0, vis=0.0))
    seconde = bons_commande.construire_livraison(po, _reception(gouttiere=30.0, vis=10.0,
                                                                horodatage="2026-10-06T14:30:00-04:00"))

    bons_commande.enregistrer_reception_po("PO-FICT-1", "RECEPTION_INFERIEURE", "2026-09-29T09:15:00-04:00",
                                           registre_po, livraison=premiere)
    etat, verdict = bons_commande.enregistrer_reception_po(
        "PO-FICT-1", "RECEPTION_INFERIEURE", "2026-10-06T14:30:00-04:00", registre_po, livraison=seconde)

    assert verdict is None and etat["statut"] == "partially_received"
    assert bons_commande.livraisons(registre_po, "PO-FICT-1") == [premiere, seconde]
    assert bons_commande.livraisons_sans_detail(registre_po, "PO-FICT-1") == 0


def test_livraison_deja_enregistree_reconnait_un_rejeu_et_lui_seul():
    registre_po, po = _registre_po_envoye()
    premiere = bons_commande.construire_livraison(po, _reception(gouttiere=40.0, vis=0.0))
    assert bons_commande.livraison_deja_enregistree(registre_po, "PO-FICT-1", premiere) is False

    bons_commande.enregistrer_reception_po("PO-FICT-1", "RECEPTION_INFERIEURE", "2026-09-29T09:15:00-04:00",
                                           registre_po, livraison=premiere)

    assert bons_commande.livraison_deja_enregistree(registre_po, "PO-FICT-1", premiere) is True
    autre = bons_commande.construire_livraison(po, _reception(gouttiere=41.0, vis=0.0))
    assert bons_commande.livraison_deja_enregistree(registre_po, "PO-FICT-1", autre) is False
    assert bons_commande.livraison_deja_enregistree(registre_po, "PO-AUTRE", premiere) is False


def test_une_reception_d_avant_t4_15_b_est_comptee_sans_detail():
    """Une transition de réception sans `livraison` (d'avant) : ses quantités ne se retrouvent nulle part, le
    cumul du PO n'est donc pas fiable."""
    registre_po, po = _registre_po_envoye()
    bons_commande.enregistrer_reception_po("PO-FICT-1", "RECEPTION_INFERIEURE", "2026-09-29T09:15:00-04:00",
                                           registre_po)
    seconde = bons_commande.construire_livraison(po, _reception(gouttiere=30.0, vis=10.0))
    bons_commande.enregistrer_reception_po("PO-FICT-1", "RECEPTION_INFERIEURE", "2026-10-06T14:30:00-04:00",
                                           registre_po, livraison=seconde)

    assert bons_commande.livraisons_sans_detail(registre_po, "PO-FICT-1") == 1
    assert bons_commande.livraisons(registre_po, "PO-FICT-1") == [seconde]


def test_indetermine_n_ecrit_aucune_livraison():
    registre_po, po = _registre_po_envoye()
    livraison = bons_commande.construire_livraison(po, _reception())

    etat, verdict = bons_commande.enregistrer_reception_po(
        "PO-FICT-1", "INDETERMINE", "2026-09-29T09:15:00-04:00", registre_po, livraison=livraison)

    assert verdict is None and etat["statut"] == "sent_to_supplier"
    assert bons_commande.livraisons(registre_po, "PO-FICT-1") == []


def test_verifier_quantites_juge_les_quantites_seules_l_horodatage_est_pour_un_po_persiste():
    """`verifier_quantites` vaut pour toute réception (éphémère comprise) ; l'horodatage, que M5 date, n'est jugé
    que par `verifier_reception`, appelée pour un PO persisté."""
    assert evenement_reception.verifier_quantites(_reception(gouttiere=40.0, vis=0.0)) is None
    negative = evenement_reception.verifier_quantites(_reception(gouttiere=-1.0))
    assert negative["code"] == "REJ-RECEPTION-QUANTITE-INVALIDE"
    sans_fuseau = _reception(horodatage="2026-09-29")
    assert evenement_reception.verifier_quantites(sans_fuseau) is None
    assert evenement_reception.verifier_reception(sans_fuseau)["code"] == "REJ-RECEPTION-HORODATAGE-INVALIDE"
