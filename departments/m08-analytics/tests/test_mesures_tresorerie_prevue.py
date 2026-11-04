"""C5 côté M8 : les trois mesures de trésorerie prévue (module pur `mesures_constats`).

Tests ROUGES avant le code : le type d'entrée `tresorerie_prevue_constatee`, les faits et les trois
mesures n'existent pas encore. Le constat de M5 (`m5.tresorerie_prevue_constatee`) est repris
TEL QUEL : solde minimal prévu et sa semaine, semaines sous le seuil (seuil déclaré en M5,
jamais inventé par M8), écart prévu/réel par semaine échue contre le solde réel du cash
libre. Une prévision absente ou périmée = « non calculable, manque X », jamais 0.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from m8_analytics import cash_libre, mesures_constats
from m8_analytics import mesures_interdepartements as mi
from m8_analytics import operations_recues as op

from opsys.evenements.schemas import erreurs_charge

FICTIF = True
JOUR = "2026-09-29"


def _charge(sequence=1, soldes=("19885.02", "15685.02", "18013.46"), seuil="16000.00",
            statut_alerte="ALERTE"):
    semaines = [
        {"semaine": k + 1, "statut": "CALCULE", "solde_fin_cad": montant}
        for k, montant in enumerate(soldes)
    ]
    minimal = min((Decimal(m) for m in soldes), default=None)
    return {
        "evenement_id": f"m5-tresorerie-prevue-{sequence}-2026-09-29-{'b' * 16}",
        "sequence": sequence,
        "date_reference": "2026-09-29",
        "emise_le": "2026-09-29T07:00:00-04:00",
        "prevision_id": "b" * 64,
        "version_donnees": "b" * 64,
        "devise": "CAD",
        "horizon_semaines": len(soldes),
        "seuil_cad": seuil,
        "statut_alerte": statut_alerte,
        "semaines_sous_seuil": [2] if statut_alerte == "ALERTE" else [],
        "solde_minimal_prevu_cad": format(minimal, "f") if minimal is not None else None,
        "semaine_solde_minimal": 2 if minimal is not None else None,
        "non_calculable_a_partir_de": None,
        "manque": [],
        "soldes_hebdo": semaines,
        "mention": "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision "
        "officielle ou action réelle.",
    }


def _valide(type_evenement, charge):
    assert erreurs_charge(type_evenement, charge) == [], "la donnée de test doit être conforme au catalogue"
    return charge


def _fait_prevision(sequence=1, heure=7, **options):
    return op.fait(
        op.TYPE_TRESORERIE_PREVUE,
        _valide("m5.tresorerie_prevue_constatee", _charge(sequence, **options)),
        f"{JOUR}T{heure:02d}:00:00-04:00",
    )


def _op(definitions, *faits):
    registres = {"chantier": [], "entonnoir": [], "contenus": [], "cash_libre": [], "operations": list(faits)}
    return {m["metric_id"]: m for m in mi.mesurer(registres, definitions)}


@pytest.fixture(scope="module")
def definitions():
    return mi.charger_definitions()


def _mesure(definitions, metric_id, *faits):
    return _op(definitions, *faits)[metric_id]


# ================================================================================================ C5
def test_le_solde_minimal_prevu_est_repris_tel_quel_avec_sa_semaine(definitions):
    m = _mesure(definitions, "m8_solde_minimal_prevu_cad", _fait_prevision())
    assert m["statut"] == "calculee" and m["valeur"] == "15685.02"
    assert m["entrees"]["semaine_solde_minimal"] == 2 and m["entrees"]["horizon_semaines"] == 3
    assert m["unite"] == "CAD"


def test_les_semaines_sous_le_seuil_sont_reprises_telles_quelles(definitions):
    m = _mesure(definitions, "m8_semaines_sous_seuil", _fait_prevision())
    assert m["statut"] == "calculee" and m["valeur"] == "1"
    assert m["entrees"]["semaines"] == [2] and m["unite"] == "semaines"


def test_aucune_prevision_recue_les_trois_mesures_sont_non_calculables(definitions):
    mesures = _op(definitions)
    for metric_id in ("m8_solde_minimal_prevu_cad", "m8_semaines_sous_seuil", "m8_ecart_tresorerie_prevue_reelle_cad"):
        m = mesures[metric_id]
        assert m["statut"] == "non_calculable" and m["valeur"] is None, metric_id
        assert "m5.tresorerie_prevue_constatee" in m["manque"][0]["champ"], metric_id


def test_la_derniere_prevision_publiee_l_emporte_quel_que_soit_l_ordre(definitions):
    vieille = _fait_prevision(sequence=1, heure=7, soldes=("19885.02", "15685.02", "18013.46"))
    nouvelle = _fait_prevision(sequence=2, heure=18, soldes=("19000.00", "19000.00", "19000.00"))
    for ordre in ((vieille, nouvelle), (nouvelle, vieille)):
        m = _mesure(definitions, "m8_solde_minimal_prevu_cad", *ordre)
        assert m["valeur"] == "19000.00"


def test_l_ecart_prevu_reel_compare_la_vieille_prevision_au_reel(definitions):
    vieille = _fait_prevision(sequence=1, heure=7, soldes=("19885.02", "15685.02", "18013.46"))
    nouvelle = _charge(sequence=2, soldes=("19000.00", "19000.00", "19000.00"))
    nouvelle["date_reference"] = "2026-10-13"
    nouvelle["evenement_id"] = "m5-tresorerie-prevue-2-2026-10-13-bbbbbbbbbbbbbbbb"
    nouvelle_fait = op.fait(op.TYPE_TRESORERIE_PREVUE, _valide("m5.tresorerie_prevue_constatee", nouvelle),
                            "2026-10-13T07:00:00-04:00")
    registres = {"chantier": [], "entonnoir": [], "contenus": [],
                 "cash_libre": [_cash_reel()],
                 "operations": [vieille, nouvelle_fait]}
    m = {mesure["metric_id"]: mesure for mesure in mi.mesurer(registres, definitions)}[
        "m8_ecart_tresorerie_prevue_reelle_cad"]
    assert m["statut"] == "calculee" and m["valeur"] == "3885.02"
    assert m["entrees"]["prevision_utilisee"]["solde_prevu_cad"] == "19885.02"
    assert m["entrees"]["reel_utilise"]["solde_reel_cad"] == "16000.00"


def _cash_reel(jour_cash="2026-10-07", solde="16000.00", sequence=1):
    def composante(cid, montant):
        return {"id": cid, "libelle": cid, "statut": "CALCULE", "montant_cad": montant, "plancher_cad": None,
                "source": {"origine": "REGISTRE",
                           "registres": [{"registre": "mouvements", "taille": 3, "tete": "0123456789abcdef"}]},
                "fraicheur": {"derniere_piece": "2026-10-06", "pieces": 1}}
    charge = {
        "evenement_id": f"m5-cash-libre-{sequence}-{jour_cash}-aaaaaaaaaaaaaaaa",
        "sequence": sequence,
        "date_reference": jour_cash,
        "version_donnees": "c" * 64,
        "devise": "CAD",
        "statut": "CALCULE",
        "cash_libre_cad": "15000.00",
        "au_plus_cad": None,
        "en_deficit": False,
        "lecture": "Cash libre fictif.",
        "solde": composante("solde", solde),
        "composantes": [composante(cid, "100.00") for cid in
                        ("taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves")],
        "manque": [],
        "reserves": [],
        "hypotheses": [],
        "mention": "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision "
        "officielle ou action réelle.",
    }
    return cash_libre.fait_constat(_valide("m5.cash_libre_constate", charge))


# ================================================================================================ mutants et bornes C5
def test_le_solde_minimal_non_chiffrable_par_m5_est_non_calculable_jamais_zero(definitions):
    charge = _charge()
    charge["solde_minimal_prevu_cad"] = None
    charge["semaine_solde_minimal"] = None
    charge["manque"] = [{"code": "REJ-PREVISION-VACANCE-DONNEES", "a_partir_de_semaine": 1}]
    charge["non_calculable_a_partir_de"] = 1
    fait = op.fait(op.TYPE_TRESORERIE_PREVUE, _valide("m5.tresorerie_prevue_constatee", charge),
                   f"{JOUR}T07:00:00-04:00")
    m = _mesure(definitions, "m8_solde_minimal_prevu_cad", fait)
    assert m["statut"] == "non_calculable" and m["valeur"] is None
    assert "REJ-PREVISION-VACANCE-DONNEES" in json.dumps(m["manque"], ensure_ascii=False)


def test_les_semaines_sous_seuil_illisibles_sont_non_calculables(definitions):
    # Le catalogue refuse une liste mal typée : le constat illisible vient d'un fait brut rangé sans catalogue
    # (corruption du bus), pas d'une charge valide. Le mutant `not isinstance → rien` meurt ici.
    brut = _charge()
    brut["semaines_sous_seuil"] = ["deux"]
    fait_valide = _fait_prevision()
    fait = dict(fait_valide)
    fait["semaines_sous_seuil"] = ["deux"]
    m = _mesure(definitions, "m8_semaines_sous_seuil", fait)
    assert m["statut"] == "non_calculable" and m["valeur"] is None


def test_le_seuil_non_configure_donne_zero_semaine_et_se_dit(definitions):
    charge = _charge(seuil=None, statut_alerte="SEUIL_A_CONFIGURER")
    charge["semaines_sous_seuil"] = []
    charge["statut_alerte"] = "SEUIL_A_CONFIGURER"
    fait = op.fait(op.TYPE_TRESORERIE_PREVUE, _valide("m5.tresorerie_prevue_constatee", charge),
                   f"{JOUR}T07:00:00-04:00")
    m = _mesure(definitions, "m8_semaines_sous_seuil", fait)
    assert m["statut"] == "calculee" and m["valeur"] == "0"
    assert m["entrees"]["seuil_cad"] is None


def test_l_ecart_est_negatif_quand_la_prevision_depassait_le_reel(definitions):
    vieille = _fait_prevision(sequence=1, heure=7, soldes=("25000.00", "15685.02", "18013.46"))
    nouvelle = _charge(sequence=2, soldes=("19000.00", "19000.00", "19000.00"))
    nouvelle["date_reference"] = "2026-10-13"
    nouvelle["evenement_id"] = "m5-tresorerie-prevue-2-2026-10-13-bbbbbbbbbbbbbbbb"
    faits = [
        vieille,
        op.fait(op.TYPE_TRESORERIE_PREVUE, _valide("m5.tresorerie_prevue_constatee", nouvelle),
                "2026-10-13T07:00:00-04:00"),
    ]
    registres = {"chantier": [], "entonnoir": [], "contenus": [],
                 "cash_libre": [_cash_reel()],
                 "operations": faits}
    m = {mesure["metric_id"]: mesure for mesure in mi.mesurer(registres, definitions)}[
        "m8_ecart_tresorerie_prevue_reelle_cad"]
    assert m["statut"] == "calculee" and m["valeur"] == "9000.00"
    assert m["entrees"]["prevision_utilisee"]["sequence"] == 1  # l'ancienne, jamais la plus récente


def test_l_ecart_exige_le_reel_sans_cash_ni_solde_il_est_non_calculable(definitions):
    registres = {"chantier": [], "entonnoir": [], "contenus": [], "cash_libre": [],
                 "operations": [_fait_prevision()]}
    m = {mesure["metric_id"]: mesure for mesure in mi.mesurer(registres, definitions)}[
        "m8_ecart_tresorerie_prevue_reelle_cad"]
    assert m["statut"] == "non_calculable" and m["valeur"] is None
    assert "m5.cash_libre_constate" in m["manque"][0]["champ"]
    cash = _cash_reel()
    cash["solde"] = dict(cash["solde"], statut="NON_CALCULABLE", montant_cad=None)
    registres_nc = {"chantier": [], "entonnoir": [], "contenus": [], "cash_libre": [cash],
                    "operations": [_fait_prevision()]}
    m2 = {mesure["metric_id"]: mesure for mesure in mi.mesurer(registres_nc, definitions)}[
        "m8_ecart_tresorerie_prevue_reelle_cad"]
    assert m2["statut"] == "non_calculable" and m2["valeur"] is None


def test_l_ecart_semaine_echue_le_jour_meme_du_cash_est_comparee(definitions):
    """Borne figeant `fin_semaine_1 <= jour_reel` : S1 finie le jour du cash compte comme échue."""
    prevision = _charge(sequence=1, soldes=("20000.00", "18000.00"))
    prevision["date_reference"] = "2026-10-01"  # fin S1 = 2026-10-07
    prevision["evenement_id"] = "m5-tresorerie-prevue-1-2026-10-01-bbbbbbbbbbbbbbbb"
    fait = op.fait(op.TYPE_TRESORERIE_PREVUE, _valide("m5.tresorerie_prevue_constatee", prevision),
                   "2026-10-01T07:00:00-04:00")
    registres = {"chantier": [], "entonnoir": [], "contenus": [],
                 "cash_libre": [_cash_reel(jour_cash="2026-10-07", solde="16000.00")],
                 "operations": [fait]}
    m = {mesure["metric_id"]: mesure for mesure in mi.mesurer(registres, definitions)}[
        "m8_ecart_tresorerie_prevue_reelle_cad"]
    assert m["statut"] == "calculee" and m["valeur"] == "4000.00"


def test_l_ecart_sans_ancienne_prevision_echue_est_non_calculable(definitions):
    # S1 [29-09, 05-10] non échue le 30-09 (jour du cash) : la plus récente ne suffit pas.
    cash = _cash_reel(jour_cash="2026-09-30", solde="16000.00")
    registres = {"chantier": [], "entonnoir": [], "contenus": [],
                 "cash_libre": [cash],
                 "operations": [_fait_prevision()]}
    m = {mesure["metric_id"]: mesure for mesure in mi.mesurer(registres, definitions)}[
        "m8_ecart_tresorerie_prevue_reelle_cad"]
    assert m["statut"] == "non_calculable" and m["valeur"] is None


def test_serie_partiellement_non_calculable_seules_les_semaines_chiffrees_comptent(definitions):
    charge = _charge(soldes=("19885.02", "15685.02", "18013.46"))
    charge["soldes_hebdo"][1] = {"semaine": 2, "statut": "NON_CALCULABLE", "solde_fin_cad": None}
    charge["solde_minimal_prevu_cad"] = "18013.46"
    charge["semaine_solde_minimal"] = 3
    charge["non_calculable_a_partir_de"] = 2
    fait = op.fait(op.TYPE_TRESORERIE_PREVUE, _valide("m5.tresorerie_prevue_constatee", charge),
                   f"{JOUR}T07:00:00-04:00")
    m = _mesure(definitions, "m8_solde_minimal_prevu_cad", fait)
    assert m["statut"] == "calculee" and m["valeur"] == "18013.46"


def test_le_fait_ne_garde_que_les_proprietes_fermees_sans_texte_libre():
    brut = _charge()
    charge = dict(brut)
    charge.update({"client": "Client Fictif", "note": "appeler vite"})
    range_ = op.fait(op.TYPE_TRESORERIE_PREVUE, charge, f"{JOUR}T07:00:00-04:00")
    assert "client" not in range_ and "note" not in range_
    texte = json.dumps(range_, ensure_ascii=False)
    for interdit in ("Client Fictif", "appeler vite"):
        assert interdit not in texte


# ================================================================================================ E2E C5
def test_bout_en_bout_prevision_wallboard_et_alerte(definitions):
    """Le constat de M5 traverse le bus jusqu'au wallboard et à l'alerte : solde minimal prévu repris tel quel
    sur sa tuile, semaines sous le seuil comptées, seuil de direction non inventé (seuil à configurer quand M5
    n'en a pas)."""
    from m8_analytics import alertes_metier, catalogue_mesures, fraicheur_mesures, moteur_mesures, wallboards

    catalogue = catalogue_mesures.charger()
    fait = _fait_prevision()
    registres = {"chantier": [], "entonnoir": [], "contenus": [], "cash_libre": [], "operations": [fait]}
    lues = moteur_mesures.lire(registres, catalogue)
    par_id = {m["metric_id"]: m for m in lues}
    assert par_id["m8_solde_minimal_prevu_cad"]["valeur"] == "15685.02"
    assert par_id["m8_semaines_sous_seuil"]["valeur"] == "1"
    fraiches = fraicheur_mesures.lire_mesures_avec_fraicheur(
        lues, catalogue, fraicheur_mesures.lire_maintenant("2026-09-29T12:00:00-04:00"), {})
    etat = wallboards.evaluer(
        wallboards.charger(catalogue)["finance-operations"], fraiches, maintenant="2026-09-29T12:00:00-04:00")
    tuiles = {t["id"]: t for t in etat["tuiles"]}
    assert tuiles["solde-minimal-prevu"]["valeur"] == "15685.02"
    assert tuiles["semaines-sous-seuil"]["valeur"] == "1"
    assert tuiles["ecart-prevu-reel"]["statut_mesure"] == "non_calculable"  # sans cash libre : jamais zéro
    texte = json.dumps(etat, ensure_ascii=False)
    assert "Client Fictif" not in texte and "@example.test" not in texte
    regles = alertes_metier.charger(catalogue)
    tresorerie = next(r for r in regles["regles"] if r["id"] == "ALERTE-TRESORERIE-SOUS-SEUIL")
    assert "m8_solde_minimal_prevu_cad" in tresorerie["mesures_liees"]
    assert "m8_semaines_sous_seuil" in tresorerie["mesures_liees"]
    assert "m8_ecart_tresorerie_prevue_reelle_cad" in tresorerie["mesures_liees"]


# ================================================================================================ tue-mutants C5
def test_une_sequence_booleenne_n_est_pas_un_constat(definitions):
    """`and` ligne 946 : `sequence: True` (bool, sous-classe d'int) est rejeté comme le non-entier."""
    fait = _fait_prevision()
    fait["sequence"] = True
    m = _mesure(definitions, "m8_solde_minimal_prevu_cad", fait)
    assert m["statut"] == "non_calculable" and m["valeur"] is None


def test_a_sequence_egale_le_dernier_publie_l_emporte(definitions):
    """Indice 0 ligne 950 : même séquence, le `publie_le` du bus départage, puis l'ordre de réception."""
    vieux = _fait_prevision(sequence=1, heure=7)
    neuf = _fait_prevision(sequence=1, heure=18)
    m = _mesure(definitions, "m8_solde_minimal_prevu_cad", vieux, neuf)
    assert m["valeur"] == "15685.02"
    assert m["entrees"]["emise_le"] in ("2026-09-29T07:00:00-04:00", "2026-09-29T18:00:00-04:00")
    # Quel que soit l'ordre de livraison, le dernier PUBLIÉ gagne.
    vieux_recu_dernier = dict(vieux)
    m2 = _mesure(definitions, "m8_solde_minimal_prevu_cad", neuf, vieux_recu_dernier)
    assert m2["entrees"]["sequence"] == 1


def test_une_semaine_zero_ou_negative_ne_compte_jamais(definitions):
    """`semaine < 1` ligne 1035 : une ligne de semaine 0 est sautée, pas chiffrée (fait brut, pas de catalogue)."""
    fait = _fait_prevision()
    fait = dict(fait, soldes_hebdo=[*fait["soldes_hebdo"],
                                    {"semaine": 0, "statut": "CALCULE", "solde_fin_cad": "1.00"}])
    serie = mesures_constats._semaines_calculees(fait)
    assert 0 not in serie and serie[1] == Decimal("19885.02")


def test_une_ligne_non_calculee_ou_sans_montant_est_sautee(definitions):
    """`statut != CALCULE or montant is None` : la série ne retient que le chiffré (fait brut, pas de catalogue)."""
    fait = _fait_prevision()
    fait = dict(fait, soldes_hebdo=[{"semaine": 1, "statut": "NON_CALCULABLE", "solde_fin_cad": None},
                                    {"semaine": 2, "statut": "CALCULE", "solde_fin_cad": "mauvais"}])
    serie = mesures_constats._semaines_calculees(fait)
    assert 1 not in serie and 2 not in serie


def test_une_reference_non_jour_ne_donne_pas_de_fin_de_semaine(definitions):
    """Gardes ligne 1044 : semaine 0, semaine non entière et jour illisible → None, jamais une date devinée."""
    assert mesures_constats._fin_semaine("2026-09-29", 0) is None
    assert mesures_constats._fin_semaine("2026-09-29", "1") is None
    assert mesures_constats._fin_semaine("pas-un-jour", 1) is None
    assert mesures_constats._fin_semaine("2026-09-29", 2) == mesures_constats.jour("2026-10-12")


def test_la_semaine_2_finit_13_jours_apres_la_reference(definitions):
    """`7 * semaine - 1` : S2 couvre 14 jours, pas 7 ni 8."""
    assert mesures_constats._fin_semaine("2026-09-29", 1) == mesures_constats.jour("2026-10-05")
    assert mesures_constats._fin_semaine("2026-09-29", 2) == mesures_constats.jour("2026-10-12")


def test_l_ecart_dit_la_semaine_comparee_et_utilise_sa_serie(definitions):
    """Littéral `semaine_comparee: 1` : l'écart compare la S1 de l'ancienne, et le dit."""
    vieille = _fait_prevision(sequence=1, heure=7, soldes=("25000.00", "15685.02", "18013.46"))
    nouvelle = _charge(sequence=2, soldes=("19000.00", "19000.00", "19000.00"))
    nouvelle["date_reference"] = "2026-10-13"
    nouvelle["evenement_id"] = "m5-tresorerie-prevue-2-2026-10-13-bbbbbbbbbbbbbbbb"
    faits = [vieille, op.fait(op.TYPE_TRESORERIE_PREVUE,
                              _valide("m5.tresorerie_prevue_constatee", nouvelle), "2026-10-13T07:00:00-04:00")]
    registres = {"chantier": [], "entonnoir": [], "contenus": [], "cash_libre": [_cash_reel()],
                 "operations": faits}
    m = {mesure["metric_id"]: mesure for mesure in mi.mesurer(registres, definitions)}[
        "m8_ecart_tresorerie_prevue_reelle_cad"]
    assert m["entrees"]["prevision_utilisee"]["semaine_comparee"] == 1
    assert m["entrees"]["prevision_utilisee"]["solde_prevu_cad"] == "25000.00"


def test_l_ecart_ignore_une_prevision_sans_semaine_1_chiffree(definitions):
    """`1 in serie` : une ancienne dont la S1 est non calculable ne sert pas de prévu."""
    prevision = _charge(sequence=1, soldes=("20000.00", "18000.00"))
    prevision["date_reference"] = "2026-10-01"
    prevision["evenement_id"] = "m5-tresorerie-prevue-1-2026-10-01-bbbbbbbbbbbbbbbb"
    prevision["soldes_hebdo"][0] = {"semaine": 1, "statut": "NON_CALCULABLE", "solde_fin_cad": None}
    fait = op.fait(op.TYPE_TRESORERIE_PREVUE, _valide("m5.tresorerie_prevue_constatee", prevision),
                   "2026-10-01T07:00:00-04:00")
    registres = {"chantier": [], "entonnoir": [], "contenus": [],
                 "cash_libre": [_cash_reel(jour_cash="2026-10-07", solde="16000.00")],
                 "operations": [fait]}
    m = {mesure["metric_id"]: mesure for mesure in mi.mesurer(registres, definitions)}[
        "m8_ecart_tresorerie_prevue_reelle_cad"]
    assert m["statut"] == "non_calculable" and m["valeur"] is None


def test_a_anciennes_egales_celle_de_plus_grande_sequence_l_emporte(definitions):
    """Départage lignes 1106-1107 : deux anciennes échues → la plus grande séquence est le prévu."""
    ancienne1 = _charge(sequence=1, soldes=("20000.00", "18000.00"))
    ancienne1["date_reference"] = "2026-10-01"
    ancienne1["evenement_id"] = "m5-tresorerie-prevue-1-2026-10-01-bbbbbbbbbbbbbbbb"
    ancienne2 = _charge(sequence=2, soldes=("21000.00", "18000.00"))
    ancienne2["date_reference"] = "2026-10-01"
    ancienne2["evenement_id"] = "m5-tresorerie-prevue-2-2026-10-01-bbbbbbbbbbbbbbbb"
    faits = [op.fait(op.TYPE_TRESORERIE_PREVUE, _valide("m5.tresorerie_prevue_constatee", ancienne1),
                     "2026-10-01T07:00:00-04:00"),
             op.fait(op.TYPE_TRESORERIE_PREVUE, _valide("m5.tresorerie_prevue_constatee", ancienne2),
                     "2026-10-01T18:00:00-04:00")]
    registres = {"chantier": [], "entonnoir": [], "contenus": [],
                 "cash_libre": [_cash_reel(jour_cash="2026-10-07", solde="16000.00")],
                 "operations": faits}
    m = {mesure["metric_id"]: mesure for mesure in mi.mesurer(registres, definitions)}[
        "m8_ecart_tresorerie_prevue_reelle_cad"]
    assert m["valeur"] == "5000.00" and m["entrees"]["prevision_utilisee"]["sequence"] == 2


def test_une_sequence_texte_n_est_pas_un_constat(definitions):
    """Mutant `and → or` ligne 946 : `sequence: "1"` est rejeté (le mutant l'accepterait)."""
    fait = _fait_prevision()
    fait["sequence"] = "1"
    m = _mesure(definitions, "m8_solde_minimal_prevu_cad", fait)
    assert m["statut"] == "non_calculable" and m["valeur"] is None


def test_a_faits_identiques_le_dernier_recu_l_emporte_par_son_indice(definitions):
    """Mutant `0 → 1` ligne 950 : même séquence, même publication → l'indice de réception départage."""
    premier = _fait_prevision(sequence=1, heure=7)
    second = _fait_prevision(sequence=1, heure=7)
    second = dict(second, solde_minimal_prevu_cad="15000.00")
    m = _mesure(definitions, "m8_solde_minimal_prevu_cad", premier, second)
    assert m["statut"] == "calculee" and m["valeur"] == "15000.00"


def test_le_minimal_exige_montant_et_semaine_entiere_ensemble(definitions):
    """Mutant `or → and` ligne 983 : montant absent OU semaine non entière → non calculable dans les deux cas."""
    sans_montant = _fait_prevision()
    fait1 = dict(sans_montant, solde_minimal_prevu_cad=None)
    assert _mesure(definitions, "m8_solde_minimal_prevu_cad", fait1)["statut"] == "non_calculable"
    sans_semaine = _fait_prevision()
    fait2 = dict(sans_semaine, semaine_solde_minimal="deux")
    assert _mesure(definitions, "m8_solde_minimal_prevu_cad", fait2)["statut"] == "non_calculable"


def test_une_prevision_a_date_illisible_ne_plante_pas_l_ecart(definitions):
    """Mutant `or → and` ligne 1084 : fin de semaine incalculable → la prévision est sautée, pas comparée."""
    fait = _fait_prevision()
    fait = dict(fait, date_reference="pas-un-jour")
    registres = {"chantier": [], "entonnoir": [], "contenus": [],
                 "cash_libre": [_cash_reel(jour_cash="2026-10-07", solde="16000.00")],
                 "operations": [fait]}
    m = {mesure["metric_id"]: mesure for mesure in mi.mesurer(registres, definitions)}[
        "m8_ecart_tresorerie_prevue_reelle_cad"]
    assert m["statut"] == "non_calculable" and m["valeur"] is None


def test_une_ancienne_a_sequence_non_entiere_perd_contre_l_entiere(definitions):
    """Mutants lignes 1106-1107 : `sequence` non entière vaut 0 au départage, elle ne gagne jamais."""
    entiere = _charge(sequence=1, soldes=("20000.00", "18000.00"))
    entiere["date_reference"] = "2026-10-01"
    entiere["evenement_id"] = "m5-tresorerie-prevue-1-2026-10-01-bbbbbbbbbbbbbbbb"
    texte = _charge(sequence=9, soldes=("90000.00", "18000.00"))
    texte["date_reference"] = "2026-10-01"
    texte["evenement_id"] = "m5-tresorerie-prevue-9-2026-10-01-bbbbbbbbbbbbbbbb"
    faits = [op.fait(op.TYPE_TRESORERIE_PREVUE, _valide("m5.tresorerie_prevue_constatee", entiere),
                     "2026-10-01T07:00:00-04:00"),
             op.fait(op.TYPE_TRESORERIE_PREVUE, _valide("m5.tresorerie_prevue_constatee", texte),
                     "2026-10-01T18:00:00-04:00")]
    faits[1]["sequence"] = "neuf"  # corruption du bus après rangement : le départage la déclasse
    registres = {"chantier": [], "entonnoir": [], "contenus": [],
                 "cash_libre": [_cash_reel(jour_cash="2026-10-07", solde="16000.00")],
                 "operations": faits}
    m = {mesure["metric_id"]: mesure for mesure in mi.mesurer(registres, definitions)}[
        "m8_ecart_tresorerie_prevue_reelle_cad"]
    assert m["valeur"] == "4000.00" and m["entrees"]["prevision_utilisee"]["sequence"] == 1


def test_l_indice_de_departage_de_l_ecart_ne_voit_que_l_instant_publie():
    """Mutants équivalents `0 → 1` ligne 1107 : `ordre_publication(f, _)[0]` ne retient que l'instant de
    publication, jamais l'indice de réception — les deux variantes calculent le même écart, prouvé ici."""
    from m8_analytics.mesures_communes import ordre_publication
    fait = _fait_prevision()
    assert ordre_publication(fait, 0)[0] == ordre_publication(fait, 1)[0]
