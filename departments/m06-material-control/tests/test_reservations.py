"""PLAN T4.14 (M6.8, M6.4) : réservation du matériel par chantier et « matériel prêt » — module pur `reservations.py`.

Ce que ces tests fixent :
- une réservation naît d'un prévu DÉFINITIF (jamais d'une estimation) et met de côté `min(besoin, disponible)` : jamais
  plus que ce qui est disponible, donc jamais deux chantiers sur la même unité ;
- `pret`, `partiel`, `a_commander` se calculent sur les lignes, et un prévu vide ne dit rien (jamais « prêt » par
  défaut) ;
- pas de double réservation ; libération (annulation) et clôture (matériaux déclarés) ;
- `reconcilier` rétablit `réservé <= en main` (les plus récentes cèdent d'abord) et complète ce qui manque (les plus
  anciennes d'abord), sans jamais rendre le réservé supérieur à l'en main, quoi que fasse le stock ;
- la charge de l'événement est déterministe, une révision par changement, et ne crée aucun bon de commande.

Identifiants et quantités fictifs (`fictif: true` au sens d'AGENTS.md).
"""

from __future__ import annotations

import ast
import random
from decimal import Decimal
from pathlib import Path

import pytest
from m6_material_control import reservations

FICTIF = True
H = "2026-09-30T10:00:00-04:00"


def _prevu(devis_id="DEVIS-FICT-1", lignes=None, chantier_id="CH-FICT-1", **supplement):
    lignes = lignes if lignes is not None else [
        {"materiau_id": "gouttiere-5po", "quantite_estimee": 100.0, "unite": "pi"},
        {"materiau_id": "vis-inox", "quantite_estimee": 20.0, "unite": "boite"}]
    return {"chantier_id": chantier_id, "devis_id": devis_id, "lignes": lignes, **supplement}


def _en_main(gouttiere=0, vis=0):
    return {"gouttiere-5po": Decimal(str(gouttiere)), "vis-inox": Decimal(str(vis))}


def _reserver(maillons, devis_id="DEVIS-FICT-1", prevu=None, en_main=None, declencheur="devis_accepte", **options):
    resultat, verdict = reservations.reserver(
        devis_id, prevu if prevu is not None else _prevu(devis_id), H, declencheur, maillons,
        en_main if en_main is not None else _en_main(), **options)
    if resultat is not None and resultat["fait"] is not None:
        maillons.append(resultat["fait"])
    return resultat, verdict


def _lignes(fait):
    return {ligne["materiau_id"]: (ligne["quantite_besoin"], ligne["quantite_reservee"]) for ligne in fait["lignes"]}


# ------------------------------------------------------------------------------------- statut_pret
@pytest.mark.parametrize("lignes, attendu", [
    ([("100", "100"), ("20", "20")], "pret"),
    ([("100", "120"), ("20", "20")], "pret"),
    ([("100", "0"), ("20", "0")], "a_commander"),
    ([("100", "60"), ("20", "0")], "partiel"),
    ([("100", "100"), ("20", "0")], "partiel"),
    ([("100", "99.999"), ("20", "20")], "partiel"),
    ([("100", "0")], "a_commander"),
    ([("100", "100")], "pret"),
])
def test_statut_pret_se_calcule_sur_les_lignes(lignes, attendu):
    faits = [{"materiau_id": f"m{i}", "quantite_besoin": besoin, "quantite_reservee": reservee}
             for i, (besoin, reservee) in enumerate(lignes)]
    assert reservations.statut_pret(faits) == attendu


# ------------------------------------------------------------------------------------------ reserver
def test_stock_insuffisant_rien_n_est_reserve_le_devis_est_a_commander():
    maillons: list[dict] = []

    resultat, verdict = _reserver(maillons, en_main=_en_main(0, 0))

    assert verdict is None and resultat["statut"] == "creee"
    fait = resultat["fait"]
    assert _lignes(fait) == {"gouttiere-5po": ("100", "0"), "vis-inox": ("20", "0")}
    assert reservations.statut_pret(fait["lignes"]) == "a_commander"
    assert [m["materiau_id"] for m in reservations.lignes_manquantes(fait["lignes"])] == ["gouttiere-5po", "vis-inox"]
    assert (fait["devis_id"], fait["chantier_id"], fait["revision"], fait["actif"]) == (
        "DEVIS-FICT-1", "CH-FICT-1", 1, True)


def test_stock_partiel_reserve_ce_qui_existe_et_dit_ce_qui_manque():
    resultat, _ = _reserver([], en_main=_en_main(60, 0))

    fait = resultat["fait"]
    assert _lignes(fait) == {"gouttiere-5po": ("100", "60"), "vis-inox": ("20", "0")}
    assert reservations.statut_pret(fait["lignes"]) == "partiel"
    assert reservations.lignes_manquantes(fait["lignes"]) == [
        {"materiau_id": "gouttiere-5po", "unite": "pi", "quantite_besoin": "100", "quantite_reservee": "60",
         "quantite_manquante": "40"},
        {"materiau_id": "vis-inox", "unite": "boite", "quantite_besoin": "20", "quantite_reservee": "0",
         "quantite_manquante": "20"},
    ]


def test_stock_suffisant_est_pret_et_ne_reserve_que_le_besoin():
    resultat, _ = _reserver([], en_main=_en_main(500, 20))

    fait = resultat["fait"]
    assert _lignes(fait) == {"gouttiere-5po": ("100", "100"), "vis-inox": ("20", "20")}
    assert reservations.statut_pret(fait["lignes"]) == "pret"
    assert reservations.lignes_manquantes(fait["lignes"]) == []


def test_un_en_main_negatif_ne_reserve_rien_jamais_un_nombre_negatif():
    resultat, _ = _reserver([], en_main=_en_main(-5, -1))
    assert _lignes(resultat["fait"]) == {"gouttiere-5po": ("100", "0"), "vis-inox": ("20", "0")}


def test_pas_de_double_reservation_pour_un_meme_devis():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(500, 500))

    resultat, verdict = _reserver(maillons, en_main=_en_main(500, 500))

    assert verdict is None and resultat == {"statut": "deja_reservee", "fait": None}
    assert len(maillons) == 1
    assert reservations.reserve_par_article(maillons) == {"gouttiere-5po": Decimal("100"), "vis-inox": Decimal("20")}


def test_deux_chantiers_ne_se_partagent_jamais_la_meme_unite():
    """100 gouttières en main. A en veut 70, B en veut 50 : B n'en reçoit que 30, le total réservé reste 100."""
    maillons: list[dict] = []
    en_main = _en_main(100, 100)
    prevu_a = _prevu("DEVIS-A", [{"materiau_id": "gouttiere-5po", "quantite_estimee": 70.0, "unite": "pi"}])
    prevu_b = _prevu("DEVIS-B", [{"materiau_id": "gouttiere-5po", "quantite_estimee": 50.0, "unite": "pi"}])

    a, _ = _reserver(maillons, "DEVIS-A", prevu_a, en_main)
    b, _ = _reserver(maillons, "DEVIS-B", prevu_b, en_main)

    assert _lignes(a["fait"]) == {"gouttiere-5po": ("70", "70")}
    assert _lignes(b["fait"]) == {"gouttiere-5po": ("50", "30")}
    assert reservations.statut_pret(a["fait"]["lignes"]) == "pret"
    assert reservations.statut_pret(b["fait"]["lignes"]) == "partiel"
    assert reservations.reserve_par_article(maillons) == {"gouttiere-5po": Decimal("100")}


def test_le_disponible_tient_compte_de_ce_qui_est_deja_reserve():
    maillons: list[dict] = []
    _reserver(maillons, "DEVIS-A", _prevu("DEVIS-A", [{"materiau_id": "gouttiere-5po", "quantite_estimee": 100.0,
                                                       "unite": "pi"}]), _en_main(100, 0))
    resultat, _ = _reserver(maillons, "DEVIS-B", _prevu("DEVIS-B", [{"materiau_id": "gouttiere-5po",
                                                                     "quantite_estimee": 10.0, "unite": "pi"}]),
                            _en_main(100, 0))
    assert _lignes(resultat["fait"]) == {"gouttiere-5po": ("10", "0")}
    assert reservations.statut_pret(resultat["fait"]["lignes"]) == "a_commander"


def test_une_estimation_ne_reserve_jamais():
    resultat, verdict = _reserver([], prevu=_prevu(source="estimation_m3"))
    assert resultat is None and verdict["code"] == "REJ-RESERVATION-PREVU-PROVISOIRE"


def test_sans_prevu_il_n_y_a_rien_a_reserver():
    resultat, verdict = reservations.reserver("DEVIS-FICT-1", None, H, "devis_accepte", [], _en_main())
    assert resultat is None and verdict["code"] == "REJ-RESERVATION-PREVU-ABSENT"


def test_un_prevu_vide_ne_reserve_rien_et_ne_dit_rien_jamais_pret_par_defaut():
    maillons: list[dict] = []
    resultat, verdict = _reserver(maillons, prevu=_prevu(lignes=[]))
    assert verdict is None and resultat == {"statut": "aucun_besoin_connu", "fait": None}
    assert maillons == [] and reservations.etat("DEVIS-FICT-1", maillons) is None


@pytest.mark.parametrize("arguments, code", [
    ({"devis_id": ""}, "REJ-RESERVATION-DEVIS-VIDE"),
    ({"devis_id": None}, "REJ-RESERVATION-DEVIS-VIDE"),
    ({"horodatage": " "}, "REJ-RESERVATION-HORODATAGE-VIDE"),
    ({"horodatage": None}, "REJ-RESERVATION-HORODATAGE-VIDE"),
    ({"declencheur": "au-hasard"}, "REJ-RESERVATION-DECLENCHEUR-INCONNU"),
])
def test_entrees_invalides_refusees_par_leur_code(arguments, code):
    parametres = {"devis_id": "DEVIS-FICT-1", "horodatage": H, "declencheur": "devis_accepte", **arguments}
    resultat, verdict = reservations.reserver(
        parametres["devis_id"], _prevu(), parametres["horodatage"], parametres["declencheur"], [], _en_main())
    assert resultat is None and verdict["code"] == code


def test_un_article_absent_de_l_en_main_est_un_defaut_de_l_appelant_jamais_un_zero_silencieux():
    with pytest.raises(KeyError):
        reservations.reserver("DEVIS-FICT-1", _prevu(), H, "devis_accepte", [], {"gouttiere-5po": Decimal(5)})


def test_quantites_en_decimal_exact_jamais_en_flottant():
    """0,1 + 0,2 : le besoin est 0,3 et l'en main 0,1 + 0,2. En flottant, 0,30000000000000004 dépasserait le besoin."""
    prevu = _prevu(lignes=[{"materiau_id": "scellant", "quantite_estimee": 0.3, "unite": "tube"}])
    resultat, _ = _reserver([], prevu=prevu, en_main={"scellant": Decimal("0.1") + Decimal("0.2")})
    assert resultat["fait"]["lignes"][0]["quantite_reservee"] == "0.3"
    assert reservations.statut_pret(resultat["fait"]["lignes"]) == "pret"


# ---------------------------------------------------------------------------------------------- liberer
def _liberer(maillons, devis_id="DEVIS-FICT-1", motif="chantier annulé"):
    resultat, verdict = reservations.liberer(devis_id, motif, "nathan", H, maillons)
    if resultat is not None and resultat["fait"] is not None:
        maillons.append(resultat["fait"])
    return resultat, verdict


def test_liberer_rend_le_stock_au_disponible_et_garde_ce_qui_a_ete_libere():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(500, 500))

    resultat, verdict = _liberer(maillons)

    assert verdict is None and resultat["statut"] == "liberee"
    fait = resultat["fait"]
    assert (fait["actif"], fait["evenement"], fait["revision"], fait["motif"], fait["acteur"]) == (
        False, "liberee", 2, "chantier annulé", "nathan")
    assert fait["liberees"] == [{"materiau_id": "gouttiere-5po", "quantite": "100"},
                                {"materiau_id": "vis-inox", "quantite": "20"}]
    assert reservations.reserve_par_article(maillons) == {}
    suivant, _ = _reserver(maillons, "DEVIS-B", _prevu("DEVIS-B"), _en_main(120, 20))
    assert _lignes(suivant["fait"])["gouttiere-5po"] == ("100", "100"), "le stock libéré est de nouveau réservable"


def test_liberer_deux_fois_est_un_rejeu_sans_ecriture():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(500, 500))
    _liberer(maillons)

    resultat, verdict = _liberer(maillons)

    assert verdict is None and resultat == {"statut": "deja_liberee", "fait": None}
    assert len(maillons) == 2


def test_liberer_refuse_sans_motif_et_sans_reservation():
    maillons: list[dict] = []
    _, verdict = reservations.liberer("DEVIS-FICT-1", "raison", "nathan", H, maillons)
    assert verdict["code"] == "REJ-RESERVATION-INTROUVABLE"
    _reserver(maillons, en_main=_en_main(500, 500))
    for motif in ("", "  ", None):
        _, verdict = reservations.liberer("DEVIS-FICT-1", motif, "nathan", H, maillons)
        assert verdict["code"] == "REJ-RESERVATION-MOTIF-VIDE"
    _, verdict = reservations.liberer("DEVIS-FICT-1", "raison", "nathan", "", maillons)
    assert verdict["code"] == "REJ-RESERVATION-HORODATAGE-VIDE"
    assert reservations.etat("DEVIS-FICT-1", maillons)["actif"] is True


def test_apres_liberation_le_bus_ne_re_reserve_pas_mais_un_humain_le_peut():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(500, 500))
    _liberer(maillons)

    bus, _ = _reserver(maillons, en_main=_en_main(500, 500))
    assert bus == {"statut": "deja_traitee", "fait": None}
    assert len(maillons) == 2

    humain, _ = _reserver(maillons, en_main=_en_main(500, 500), declencheur="reservation_manuelle",
                          re_reservation=True)
    assert humain["statut"] == "creee" and humain["fait"]["revision"] == 3
    assert reservations.etat("DEVIS-FICT-1", maillons)["actif"] is True


def test_une_reservation_refaite_apres_liberation_passe_apres_celles_faites_entre_temps():
    """A réserve, B réserve, A libère puis re-réserve : A est une NOUVELLE demande, elle prend le rang après B. Quand du
    stock arrive, B se complète avant A."""
    maillons: list[dict] = []
    ligne = [{"materiau_id": "gouttiere-5po", "quantite_estimee": 50.0, "unite": "pi"}]
    _reserver(maillons, "DEVIS-A", _prevu("DEVIS-A", ligne), _en_main(0, 0))
    _reserver(maillons, "DEVIS-B", _prevu("DEVIS-B", ligne), _en_main(0, 0))
    _liberer(maillons, "DEVIS-A")
    _reserver(maillons, "DEVIS-A", _prevu("DEVIS-A", ligne), _en_main(0, 0), declencheur="reservation_manuelle",
              re_reservation=True)
    etats = reservations.etats(maillons)
    assert etats["DEVIS-B"]["rang"] < etats["DEVIS-A"]["rang"]

    faits = _appliquer(maillons, reservations.reconcilier(["gouttiere-5po"], _en_main(60, 0), maillons, H))

    assert {f["devis_id"]: _lignes(f)["gouttiere-5po"][1] for f in faits} == {"DEVIS-B": "50", "DEVIS-A": "10"}


def test_apres_cloture_plus_rien_ne_se_reserve_meme_a_la_demande_d_un_humain():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(500, 500))
    fait = reservations.cloturer("DEVIS-FICT-1", "WCT-FICT-1", H, maillons)
    maillons.append(fait)

    for re_reservation in (False, True):
        resultat, verdict = _reserver(maillons, en_main=_en_main(500, 500), re_reservation=re_reservation)
        assert resultat is None and verdict["code"] == "REJ-RESERVATION-CLOTUREE"


def test_seules_les_reservations_actives_comptent_meme_si_un_fait_inactif_porte_du_reserve():
    """Garde défensive : un fait inactif (libéré, clôturé) ne retient jamais de stock, quoi que disent ses lignes (un
    registre retouché, un instantané d'un autre âge)."""
    actif = {"type_entree": "reservation", "devis_id": "DEVIS-A", "chantier_id": None, "revision": 1,
             "evenement": "creee", "actif": True, "declencheur": "devis_accepte", "horodatage": H, "acteur": None,
             "motif": None, "lignes": [{"materiau_id": "gouttiere-5po", "unite": "pi", "quantite_besoin": "10",
                                        "quantite_reservee": "10"}]}
    inactif = {**actif, "devis_id": "DEVIS-B", "evenement": "liberee", "actif": False}

    assert reservations.reserve_par_article([actif, inactif]) == {"gouttiere-5po": Decimal(10)}
    assert reservations.reserve_par_article([inactif]) == {}


# ---------------------------------------------------------------------------------------------- cloturer
def test_cloturer_libere_ce_qui_etait_reserve_sans_evenement_de_materiel_pret():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(500, 500))

    fait = reservations.cloturer("DEVIS-FICT-1", "WCT-FICT-1", H, maillons)
    maillons.append(fait)

    assert (fait["actif"], fait["evenement"], fait["motif"], fait["wct_id"]) == (
        False, "cloturee", "materiaux_declares", "WCT-FICT-1")
    assert reservations.reserve_par_article(maillons) == {}


def test_cloturer_sans_reservation_active_ne_fait_rien():
    maillons: list[dict] = []
    assert reservations.cloturer("DEVIS-INCONNU", "WCT-FICT-1", H, maillons) is None
    _reserver(maillons, en_main=_en_main(500, 500))
    _liberer(maillons)
    assert reservations.cloturer("DEVIS-FICT-1", "WCT-FICT-1", H, maillons) is None


# ------------------------------------------------------------------------------------------- reconcilier
def _appliquer(maillons, faits):
    maillons.extend(faits)
    return faits


def test_une_reception_complete_la_reservation_d_un_devis_a_commander():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(0, 0))

    faits = _appliquer(maillons, reservations.reconcilier(
        ["gouttiere-5po", "vis-inox"], _en_main(100, 20), maillons, H))

    assert len(faits) == 1
    assert (faits[0]["evenement"], faits[0]["declencheur"], faits[0]["revision"]) == ("ajustee", "stock_recu", 2)
    assert reservations.statut_pret(faits[0]["lignes"]) == "pret"


def test_une_reception_partielle_donne_partiel_puis_la_suite_donne_pret():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(0, 0))

    premiere = _appliquer(maillons, reservations.reconcilier(
        ["gouttiere-5po", "vis-inox"], _en_main(40, 0), maillons, H))
    seconde = _appliquer(maillons, reservations.reconcilier(
        ["gouttiere-5po", "vis-inox"], _en_main(100, 20), maillons, H))

    assert [reservations.statut_pret(f["lignes"]) for f in (premiere[0], seconde[0])] == ["partiel", "pret"]
    assert [f["revision"] for f in (premiere[0], seconde[0])] == [2, 3]


def test_le_stock_qui_arrive_complete_d_abord_la_reservation_la_plus_ancienne():
    maillons: list[dict] = []
    ligne = [{"materiau_id": "gouttiere-5po", "quantite_estimee": 50.0, "unite": "pi"}]
    _reserver(maillons, "DEVIS-A", _prevu("DEVIS-A", ligne), _en_main(0, 0))
    _reserver(maillons, "DEVIS-B", _prevu("DEVIS-B", ligne), _en_main(0, 0))

    faits = _appliquer(maillons, reservations.reconcilier(["gouttiere-5po"], _en_main(70, 0), maillons, H))

    assert {f["devis_id"]: _lignes(f)["gouttiere-5po"][1] for f in faits} == {"DEVIS-A": "50", "DEVIS-B": "20"}
    assert {f["declencheur"] for f in faits} == {"stock_recu"}
    assert reservations.reserve_par_article(maillons) == {"gouttiere-5po": Decimal(70)}


def test_quand_l_en_main_baisse_les_reservations_les_plus_recentes_cedent_d_abord():
    """A (ancien) et B (récent) réservent 60 et 40 sur 100. Une sortie de stock ramène l'en main à 70 : B cède 30."""
    maillons: list[dict] = []
    ligne_a = [{"materiau_id": "gouttiere-5po", "quantite_estimee": 60.0, "unite": "pi"}]
    ligne_b = [{"materiau_id": "gouttiere-5po", "quantite_estimee": 40.0, "unite": "pi"}]
    _reserver(maillons, "DEVIS-A", _prevu("DEVIS-A", ligne_a), _en_main(100, 0))
    _reserver(maillons, "DEVIS-B", _prevu("DEVIS-B", ligne_b), _en_main(100, 0))

    faits = _appliquer(maillons, reservations.reconcilier(["gouttiere-5po"], _en_main(70, 0), maillons, H))

    assert [f["devis_id"] for f in faits] == ["DEVIS-B"], "A garde ses 60, seul B change"
    assert faits[0]["declencheur"] == "stock_sorti", "B a cédé du stock : la réservation s'éloigne du prêt"
    assert _lignes(faits[0])["gouttiere-5po"] == ("40", "10")
    assert reservations.statut_pret(faits[0]["lignes"]) == "partiel"
    assert reservations.reserve_par_article(maillons) == {"gouttiere-5po": Decimal(70)}


def test_un_en_main_qui_tombe_a_zero_ou_sous_zero_vide_les_reservations_sans_rien_rendre_negatif():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(100, 20))

    faits = _appliquer(maillons, reservations.reconcilier(
        ["gouttiere-5po", "vis-inox"], _en_main(-3, 0), maillons, H))

    assert reservations.reserve_par_article(maillons) == {}
    assert reservations.statut_pret(faits[0]["lignes"]) == "a_commander"


def test_un_seul_fait_par_devis_meme_si_plusieurs_articles_changent():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(0, 0))
    faits = reservations.reconcilier(["gouttiere-5po", "vis-inox"], _en_main(100, 20), maillons, H)
    assert len(faits) == 1 and faits[0]["devis_id"] == "DEVIS-FICT-1"


def test_rien_ne_change_rien_n_est_ecrit():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(100, 20))
    assert reservations.reconcilier(["gouttiere-5po", "vis-inox"], _en_main(100, 20), maillons, H) == []
    assert reservations.reconcilier(["gouttiere-5po"], _en_main(9999, 20), maillons, H) == []
    assert reservations.reconcilier(["autre-article"], {"autre-article": Decimal(5)}, maillons, H) == []


def test_une_reservation_liberee_ou_cloturee_n_est_jamais_completee():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(0, 0))
    _liberer(maillons)
    assert reservations.reconcilier(["gouttiere-5po", "vis-inox"], _en_main(100, 20), maillons, H) == []


def test_reconcilier_exige_l_en_main_de_chaque_article():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(10, 10))
    with pytest.raises(KeyError):
        reservations.reconcilier(["gouttiere-5po"], {}, maillons, H)


def test_le_reserve_ne_depasse_jamais_l_en_main_sur_une_longue_suite_d_evenements():
    """Suite pseudo-aléatoire fixe (graine) : réservations de plusieurs chantiers, libérations, arrivées et sorties de
    stock. Après CHAQUE événement : réservé <= max(en main, 0), aucune ligne n'est réservée au-delà de son besoin ni
    négative, le disponible n'est jamais négatif."""
    hasard = random.Random(4014)
    articles = ["gouttiere-5po", "vis-inox", "scellant"]
    en_main = {a: Decimal(hasard.randint(0, 60)) for a in articles}
    maillons: list[dict] = []
    compteur = 0
    for _ in range(400):
        action = hasard.choice(["reserver", "reserver", "liberer", "arrivee", "sortie", "cloture"])
        touches = set(articles)
        if action == "reserver":
            compteur += 1
            devis = f"DEVIS-SIM-{compteur}"
            choisis = hasard.sample(articles, hasard.randint(1, 3))
            prevu = _prevu(devis, [{"materiau_id": a, "quantite_estimee": float(hasard.randint(1, 50)), "unite": "u"}
                                   for a in choisis])
            resultat, verdict = reservations.reserver(devis, prevu, H, "devis_accepte", maillons, en_main)
            assert verdict is None
            if resultat["fait"] is not None:
                maillons.append(resultat["fait"])
        elif action == "liberer":
            actifs = [e for e in reservations.etats(maillons).values() if e["actif"]]
            if actifs:
                resultat, _ = reservations.liberer(hasard.choice(actifs)["devis_id"], "sim", "nathan", H, maillons)
                maillons.append(resultat["fait"])
        elif action == "cloture":
            actifs = [e for e in reservations.etats(maillons).values() if e["actif"]]
            if actifs:
                maillons.append(reservations.cloturer(hasard.choice(actifs)["devis_id"], "WCT-SIM", H, maillons))
        elif action == "arrivee":
            en_main[hasard.choice(articles)] += hasard.randint(1, 40)
        else:
            article = hasard.choice(articles)
            en_main[article] = max(en_main[article] - hasard.randint(1, 40), Decimal(0))
        maillons.extend(reservations.reconcilier(sorted(touches), en_main, maillons, H))

        reserve = reservations.reserve_par_article(maillons)
        for article in articles:
            assert reserve.get(article, Decimal(0)) <= en_main[article], (action, article, reserve, en_main)
        for reservation in reservations.etats(maillons).values():
            for ligne in reservation["lignes"]:
                assert Decimal(0) <= Decimal(ligne["quantite_reservee"]) <= Decimal(ligne["quantite_besoin"])
    assert compteur > 30 and len(maillons) > 60


# -------------------------------------------------------------------------------------------- l'événement
def test_la_charge_de_l_evenement_dit_le_statut_les_lignes_et_ce_qui_manque():
    resultat, _ = _reserver([], en_main=_en_main(60, 0))

    charge = reservations.charge_materiel_pret(resultat["fait"])

    assert charge["evenement_id"] == "m6-materiel-pret-DEVIS-FICT-1-1"
    assert (charge["devis_id"], charge["chantier_id"], charge["revision"]) == ("DEVIS-FICT-1", "CH-FICT-1", 1)
    assert (charge["statut"], charge["reservation_active"], charge["declencheur"], charge["horodatage"]) == (
        "partiel", True, "devis_accepte", H)
    assert [ligne["quantite_manquante"] for ligne in charge["lignes"]] == ["40", "20"]
    assert [ligne["materiau_id"] for ligne in charge["lignes_manquantes"]] == ["gouttiere-5po", "vis-inox"]


def test_les_lignes_manquantes_sont_exactement_les_lignes_dont_il_manque_quelque_chose():
    resultat, _ = _reserver([], en_main=_en_main(100, 5))
    charge = reservations.charge_materiel_pret(resultat["fait"])
    manquantes = {ligne["materiau_id"] for ligne in charge["lignes"] if Decimal(ligne["quantite_manquante"]) > 0}
    assert manquantes == {ligne["materiau_id"] for ligne in charge["lignes_manquantes"]} == {"vis-inox"}


def test_pret_ne_porte_aucune_ligne_manquante():
    resultat, _ = _reserver([], en_main=_en_main(100, 20))
    charge = reservations.charge_materiel_pret(resultat["fait"])
    assert charge["statut"] == "pret" and charge["lignes_manquantes"] == []


def test_une_reservation_liberee_publie_a_commander_et_n_est_plus_active():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(500, 500))
    resultat, _ = _liberer(maillons)

    charge = reservations.charge_materiel_pret(resultat["fait"])

    assert (charge["statut"], charge["reservation_active"], charge["declencheur"]) == (
        "a_commander", False, "liberation")
    assert len(charge["lignes_manquantes"]) == 2, "rien n'est plus tenu de côté : jamais « prêt »"


def test_chaque_changement_a_son_identifiant_un_retour_a_un_etat_deja_vu_n_est_pas_confondu_avec_le_premier():
    maillons: list[dict] = []
    _reserver(maillons, en_main=_en_main(100, 20))
    _appliquer(maillons, reservations.reconcilier(["gouttiere-5po"], _en_main(40, 20), maillons, H))
    _appliquer(maillons, reservations.reconcilier(["gouttiere-5po"], _en_main(100, 20), maillons, H))

    charges = [reservations.charge_materiel_pret(f) for f in maillons]

    assert [c["statut"] for c in charges] == ["pret", "partiel", "pret"]
    assert [c["evenement_id"] for c in charges] == [
        "m6-materiel-pret-DEVIS-FICT-1-1", "m6-materiel-pret-DEVIS-FICT-1-2", "m6-materiel-pret-DEVIS-FICT-1-3"]


def test_la_charge_est_deterministe():
    a, _ = _reserver([], en_main=_en_main(60, 0))
    b, _ = _reserver([], en_main=_en_main(60, 0))
    assert reservations.charge_materiel_pret(a["fait"]) == reservations.charge_materiel_pret(b["fait"])


def test_la_charge_ne_porte_ni_prix_ni_montant_ni_date_de_chantier():
    resultat, _ = _reserver([], en_main=_en_main(60, 0))
    charge = reservations.charge_materiel_pret(resultat["fait"])
    cles = set(charge) | {cle for ligne in charge["lignes"] for cle in ligne}
    interdites = {"prix", "cout", "montant", "date_execution", "creneau", "duree", "marge"}
    assert not [cle for cle in cles if any(mot in cle for mot in interdites)]


# ------------------------------------------------------------------------------- un module pur, sans PO
def test_le_module_est_pur_et_n_importe_ni_bons_de_commande_ni_opsys():
    """Une réservation dit ce qui manque, elle ne commande jamais (DA-M6-13) : aucun import de `bons_commande` (ni de
    `emplacements`, dont la chaîne d'audit est un autre registre)."""
    source = Path(reservations.__file__).read_text(encoding="utf-8")
    importes = set()
    for noeud in ast.walk(ast.parse(source)):
        if isinstance(noeud, ast.ImportFrom):
            importes.add((noeud.module or "").split(".")[0])
            importes.update(alias.name for alias in noeud.names)
        elif isinstance(noeud, ast.Import):
            importes.update(alias.name.split(".")[0] for alias in noeud.names)
    assert importes.isdisjoint({"opsys", "bons_commande", "emplacements", "datetime", "time", "random", "uuid"})
