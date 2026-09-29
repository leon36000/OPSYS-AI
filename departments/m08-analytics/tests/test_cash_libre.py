"""PLAN T4.19-b : le cash libre que M5 a constaté, repris tel quel par M8 (`cash_libre.py`, module pur).

Ce que ce fichier prouve, sans base de données :
- le fait rangé est la charge de `m5.cash_libre_constate` TELLE QUE M5 l'a publiée, rien de plus ni de moins ;
- le DERNIER constat est celui de plus grand `sequence`, quel que soit l'ordre de livraison du bus ;
- la section de la vue reprend chaque montant verbatim (aucun calcul, aucun arrondi : un garde statique le verrouille) ;
- un constat « non calculable, manque X » est montré tel quel (chaque manque en « composante : code ») et ajoute
  un manque à la vue qui renvoie à lui, jamais un zéro ;
- sans constat : « manque », comme avant T4.19-b ;
- l'âge du constat n'existe que si l'appelant donne `aujourd_hui` (M8 n'a pas d'horloge) ; une date illisible est
  refusée, jamais corrigée ; un âge négatif est dit incohérent, jamais ramené à zéro ;
- la borne de sortie retire la décomposition en dernier recours, la compte et la dit, sans toucher à l'essentiel.

Les constats sont des charges fictives conformes au catalogue du socle (chacune est validée par le schéma fermé avant
d'être utilisée : les données de test ne mentent pas).
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest
from m8_analytics import cash_libre

from opsys.evenements.schemas import erreurs_charge

FICTIF = True
TYPE = "m5.cash_libre_constate"
_SRC_M8 = Path(__file__).resolve().parents[1] / "src" / "m8_analytics"
MENTION = (
    "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle ou action "
    "réelle."
)
ORDRE = ["taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves"]
LIBELLES = {
    "solde": "solde", "taxes_a_remettre": "TPS/TVQ à remettre", "paies": "Paies",
    "das": "Déductions à la source (DAS)", "comptes_a_payer": "Comptes à payer", "dettes": "Dettes",
    "reserves": "Réserves critiques",
}
HYPOTHESES = [
    "crédits de taxes sur intrants : factures fournisseur SAISIES seulement, récupérables à 100 % (à valider)",
    "les comptes à recevoir ne sont PAS ajoutés : leur argent n'est pas au solde",
]


# --------------------------------------------------------------------------- des charges fictives, validées
def _composante(cid, montant, *, statut="CALCULE", origine="REGISTRE", plancher=None, piece="2026-09-14", pieces=1):
    registres = [{"registre": "mouvements", "taille": 3, "tete": "0123456789abcdef"}] if origine == "REGISTRE" else []
    return {
        "id": cid, "libelle": LIBELLES[cid], "statut": statut, "montant_cad": montant, "plancher_cad": plancher,
        "source": {"origine": origine, "registres": registres},
        "fraicheur": {"derniere_piece": piece, "pieces": pieces},
    }


_MONTANTS = {
    "taxes_a_remettre": "1981.69", "paies": "4200.00", "das": "1350.75", "comptes_a_payer": "459.91",
    "dettes": "800.00", "reserves": "1000.00",
}
_DECLARATION = "DECLARATION_PROPRIETAIRE"
_ORIGINES = {"paies": _DECLARATION, "das": _DECLARATION, "dettes": _DECLARATION}


def _charge(sequence=1, jour="2026-09-29", **surcharges):
    version = hashlib.sha256(f"version-{sequence}-{jour}".encode()).hexdigest()
    charge = {
        "evenement_id": f"m5-cash-libre-{sequence}-{jour}-{version[:16]}", "sequence": sequence,
        "date_reference": jour, "version_donnees": version, "devise": "CAD", "statut": "CALCULE",
        "cash_libre_cad": "27861.98", "au_plus_cad": None, "en_deficit": False,
        "lecture": "Cash libre : 27861.98 $ (solde moins toutes les obligations ci-dessous). "
                   "Sous réserve : REJ-AP-UNITE-PRIX-NON-CONFIRMEE.",
        "solde": _composante("solde", "37654.33", piece="2026-09-10T12:00:00-04:00", pieces=3),
        "composantes": [
            _composante(cid, _MONTANTS[cid], origine=_ORIGINES.get(cid, "REGISTRE")) for cid in ORDRE
        ],
        "manque": [], "reserves": ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"], "hypotheses": list(HYPOTHESES),
        "mention": MENTION,
    }
    charge.update(surcharges)
    assert erreurs_charge(TYPE, charge) == [], "la donnée de test doit être conforme au catalogue"
    return charge


def _charge_non_calculable(sequence=1, jour="2026-09-29", manque=("paies",)):
    codes = {"paies": "REJ-CASH-PAIE-A-DECLARER", "das": "REJ-CASH-DAS-A-DECLARER",
             "dettes": "REJ-CASH-DETTES-A-DECLARER"}
    composantes = [
        _composante(cid, None, statut="NON_CALCULABLE", origine="AUCUNE", piece=None, pieces=0) if cid in manque
        else _composante(cid, _MONTANTS[cid], origine=_ORIGINES.get(cid, "REGISTRE"))
        for cid in ORDRE
    ]
    return _charge(
        sequence, jour, statut="NON_CALCULABLE", cash_libre_cad=None, au_plus_cad="32061.98", en_deficit=None,
        lecture="Cash libre non calculable : 1 manque(s) (voir manque). Au plus 32061.98 $ : le solde moins ce qui est "
                "connu ; ce qui manque ne peut que le réduire. Ce n'est PAS de l'argent disponible.",
        composantes=composantes, manque=[{"composante": c, "code": codes[c]} for c in manque],
    )


def _fait(charge):
    return cash_libre.fait_constat(charge)


# =========================================================================================
# 1. Le fait : la charge de M5, telle quelle
# =========================================================================================
def test_le_fait_est_la_charge_de_m5_telle_quelle_avec_son_type():
    charge = _charge()

    fait = cash_libre.fait_constat(charge)

    assert fait["type_entree"] == "cash_libre_constate"
    assert {cle: valeur for cle, valeur in fait.items() if cle != "type_entree"} == charge
    assert fait["cash_libre_cad"] == "27861.98" and fait["hypotheses"] == HYPOTHESES and fait["mention"] == MENTION
    assert cash_libre.TYPE_CONSTAT == "cash_libre_constate" and cash_libre.EVENEMENT == TYPE


def test_un_fait_non_calculable_garde_son_manque_et_ne_recoit_aucun_zero():
    fait = _fait(_charge_non_calculable())

    assert fait["cash_libre_cad"] is None and fait["statut"] == "NON_CALCULABLE"
    assert fait["manque"] == [{"composante": "paies", "code": "REJ-CASH-PAIE-A-DECLARER"}]
    assert fait["au_plus_cad"] == "32061.98" and fait["en_deficit"] is None


def test_la_cle_d_unicite_est_l_identifiant_de_l_evenement():
    assert cash_libre.cles_unicite() == ("evenement_id",)


# =========================================================================================
# 2. Le DERNIER constat : le plus grand rang de M5, quel que soit l'ordre de livraison
# =========================================================================================
def test_sans_fait_il_n_y_a_pas_de_constat():
    assert cash_libre.constat_courant([]) is None
    assert cash_libre.nombre_de_constats([]) == 0


def test_seuls_les_faits_de_constat_avec_un_identifiant_comptent():
    autres = [
        {"type_entree": "wct", "wct_id": "w1", "evenement_id": "x"}, {"type_entree": "lead_recu", "lead_id": "L1"},
        {"type_entree": "cash_libre_constate", "sequence": 9},   # sans identifiant : pas un fait de M5
        {"type_entree": "cash_libre_constate", "evenement_id": 12, "sequence": 9},
    ]

    assert cash_libre.constat_courant(autres) is None and cash_libre.nombre_de_constats(autres) == 0


@pytest.mark.parametrize("ordre", [(1, 2, 3), (3, 2, 1), (2, 3, 1), (1, 3, 2)])
def test_le_plus_grand_rang_fait_foi_quel_que_soit_l_ordre_de_livraison(ordre):
    faits = [_fait(_charge(sequence=n, jour=f"2026-09-{20 + n}")) for n in ordre]

    courant = cash_libre.constat_courant(faits)

    assert courant["sequence"] == 3 and courant["date_reference"] == "2026-09-23"
    assert cash_libre.nombre_de_constats(faits) == 3


def test_le_rang_prime_sur_la_date_de_reference_le_dernier_publie_est_le_dernier_constat():
    """Un constat dont l'appelant a donné une date plus ancienne (relance tardive) est quand même le dernier publié."""
    recent = _fait(_charge(sequence=1, jour="2026-09-29"))
    tardif = _fait(_charge(sequence=2, jour="2026-09-25"))

    assert cash_libre.constat_courant([recent, tardif])["date_reference"] == "2026-09-25"
    assert cash_libre.constat_courant([tardif, recent])["date_reference"] == "2026-09-25"


def test_a_rang_egal_le_dernier_recu_fait_foi():
    premier = _fait(_charge(sequence=4, jour="2026-09-25"))
    second = {**_fait(_charge(sequence=4, jour="2026-09-26"))}

    assert cash_libre.constat_courant([premier, second])["date_reference"] == "2026-09-26"
    assert cash_libre.constat_courant([second, premier])["date_reference"] == "2026-09-25"


@pytest.mark.parametrize("illisible", [None, "3", 2.5, True, [], {}])
def test_un_rang_illisible_vaut_zero_et_ne_passe_jamais_devant_un_rang_lu(illisible):
    sans_rang = {**_fait(_charge(sequence=1, jour="2026-09-20")), "sequence": illisible}
    lu = _fait(_charge(sequence=1, jour="2026-09-21"))

    assert cash_libre.constat_courant([sans_rang, lu])["date_reference"] == "2026-09-21"
    assert cash_libre.constat_courant([lu, sans_rang])["date_reference"] == "2026-09-21"


def test_une_relivraison_ne_compte_pas_deux_fois_le_meme_constat():
    fait = _fait(_charge())

    assert cash_libre.nombre_de_constats([fait, dict(fait), _fait(_charge(sequence=2))]) == 2


# =========================================================================================
# 3. La date de l'appelant et l'âge : la seule arithmétique du module, sur des dates
# =========================================================================================
def test_aujourd_hui_est_facultatif_et_lu_tel_quel():
    assert cash_libre.lire_aujourd_hui(None) is None
    assert cash_libre.lire_aujourd_hui("2026-10-02") == "2026-10-02"
    assert cash_libre.lire_aujourd_hui("2028-02-29") == "2028-02-29"


@pytest.mark.parametrize("brut", [
    "", "2026-10-2", "2 octobre", "02/10/2026", "20261002", "2026-02-30", "2027-02-29", "2026-13-01",
    "2026-10-02T09:00:00-04:00", " 2026-10-02", "2026-10-02\n", 20261002, 2026.1002, True, ["2026-10-02"],
])
def test_une_date_illisible_est_refusee_avec_son_code_jamais_corrigee(brut):
    with pytest.raises(ValueError, match="REJ-VUE-AUJOURD-HUI-INVALIDE"):
        cash_libre.lire_aujourd_hui(brut)


@pytest.mark.parametrize("reference, aujourd_hui, attendu", [
    ("2026-09-29", "2026-09-29", 0),
    ("2026-09-29", "2026-09-30", 1),
    ("2026-09-29", "2026-10-02", 3),
    ("2026-12-31", "2027-01-02", 2),      # le passage d'une année
    ("2028-02-28", "2028-03-01", 2),      # 2028 est bissextile
    ("2027-02-28", "2027-03-01", 1),      # 2027 ne l'est pas
    ("2026-01-01", "2026-12-31", 364),
    ("2026-10-02", "2026-09-29", -3),     # le constat est daté d'après l'appelant : négatif, l'appelant tranche
])
def test_l_age_est_le_nombre_de_jours_entiers_entre_deux_dates(reference, aujourd_hui, attendu):
    assert cash_libre.age_en_jours(reference, aujourd_hui) == attendu


@pytest.mark.parametrize("reference, aujourd_hui", [
    (None, "2026-10-02"), ("2026-09-29", None), ("hier", "2026-10-02"), ("2026-09-29", "demain"),
    ("2026-02-30", "2026-10-02"), (20260929, "2026-10-02"), ("2026-09-29T10:00:00-04:00", "2026-10-02"),
])
def test_un_age_dont_une_date_est_illisible_n_existe_pas(reference, aujourd_hui):
    assert cash_libre.age_en_jours(reference, aujourd_hui) is None


def test_sans_aujourd_hui_l_age_est_non_calculable_et_dit_pourquoi():
    assert cash_libre.age("2026-09-29", None) == {
        "jours": None, "raison": "aujourd_hui non fourni : M8 n'a pas d'horloge"}


def test_l_age_d_un_constat_du_jour_est_zero_jour_pas_non_calculable():
    assert cash_libre.age("2026-09-29", "2026-09-29") == {"jours": 0, "aujourd_hui": "2026-09-29"}
    assert cash_libre.age("2026-09-29", "2026-10-02") == {"jours": 3, "aujourd_hui": "2026-10-02"}


def test_un_constat_date_d_apres_aujourd_hui_est_incoherent_jamais_un_age_negatif_ni_zero():
    age = cash_libre.age("2026-10-05", "2026-10-02")

    assert age["jours"] is None and age["aujourd_hui"] == "2026-10-02"
    assert age["raison"] == "la date de référence du constat (2026-10-05) est postérieure à aujourd_hui"


def test_une_date_de_reference_illisible_donne_un_age_non_calculable_avec_sa_raison():
    age = cash_libre.age("pas-une-date", "2026-10-02")

    assert age == {
        "jours": None, "aujourd_hui": "2026-10-02", "raison": "la date de référence du constat est illisible"}


# =========================================================================================
# 4. La section : sans constat « manque », avec un constat tel quel
# =========================================================================================
def test_sans_constat_la_section_dit_manque_et_le_manque_est_dit_une_seule_fois():
    manques = []

    section = cash_libre.section([], None, manques)
    cash_libre.section([], None, manques)  # une seconde lecture de la même vue : pas de doublon

    assert section == {
        "source": "M5 (m5.cash_libre_constate)", "statut": "manque", "manque": ["cash_libre"],
        "a_lire": "m5_etat_tresorerie (admin), avec la décomposition du cash libre ; "
                  "m5_constater_cash_libre (admin) le publie à M8",
    }
    assert len(manques) == 1 and manques[0]["champ"] == "cash_libre" and manques[0]["source"] == section["source"]
    assert "n'a publié aucun constat" in manques[0]["raison"]


def test_des_faits_qui_ne_sont_pas_des_constats_donnent_encore_manque():
    section = cash_libre.section([{"type_entree": "lead_recu", "lead_id": "L1"}], "2026-10-02", [])

    assert section["statut"] == "manque" and "constat" not in section


def test_avec_un_constat_calcule_la_section_le_montre_tel_quel_avec_son_age():
    manques = []

    section = cash_libre.section([_fait(_charge())], "2026-10-02", manques)

    assert manques == [], "un constat calculé ne crée aucun manque"
    assert set(section) == {"source", "statut", "n_constats_recus", "constat", "age", "non_repris", "a_lire"}
    assert section["source"] == "M5 (m5.cash_libre_constate)" and section["statut"] == "lu"
    assert section["n_constats_recus"] == 1
    assert section["age"] == {"jours": 3, "aujourd_hui": "2026-10-02"}
    assert section["a_lire"] == "m5_etat_tresorerie (admin)"
    assert section["non_repris"] == "source et fraîcheur de chaque composante, hypothèses"
    constat = section["constat"]
    assert set(constat) == {"sequence", "date_reference", "statut", "cash_libre_cad", "au_plus_cad", "en_deficit",
                            "lecture", "composantes", "manque", "reserves", "mention"}
    assert "evenement_id" not in constat, "le rang et le jour identifient le constat ; l'id reste au fait rangé"
    assert (constat["sequence"], constat["date_reference"], constat["statut"]) == (1, "2026-09-29", "CALCULE")
    assert (constat["cash_libre_cad"], constat["au_plus_cad"], constat["en_deficit"]) == ("27861.98", None, False)
    assert constat["lecture"].startswith("Cash libre : 27861.98 $") and constat["mention"] == MENTION
    assert constat["manque"] == [] and constat["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]


def test_la_decomposition_est_celle_de_m5_le_solde_puis_les_six_obligations_avec_leur_montant_en_texte():
    constat = cash_libre.section([_fait(_charge())], None, [])["constat"]

    assert list(constat["composantes"].items()) == [
        ("solde", "37654.33"), ("taxes_a_remettre", "1981.69"), ("paies", "4200.00"), ("das", "1350.75"),
        ("comptes_a_payer", "459.91"), ("dettes", "800.00"), ("reserves", "1000.00"),
    ]
    assert "planchers_cad" not in constat, "sans plancher, sans clé"


def test_un_plancher_n_est_rendu_que_pour_une_composante_qui_en_a_un():
    composantes = [_composante(cid, _MONTANTS[cid], origine=_ORIGINES.get(cid, "REGISTRE")) for cid in ORDRE]
    composantes[3] = _composante("comptes_a_payer", None, statut="NON_CALCULABLE", plancher="459.91")
    charge = _charge(
        statut="NON_CALCULABLE", cash_libre_cad=None, en_deficit=None, au_plus_cad="27861.98", composantes=composantes,
        manque=[{"composante": "comptes_a_payer", "code": "REJ-CASH-COMPTES-A-PAYER-INCOMPLETS"}],
        lecture="Cash libre non calculable : 1 manque(s). Au plus 27861.98 $ : ce n'est PAS de l'argent disponible.")

    constat = cash_libre.section([_fait(charge)], None, [])["constat"]

    assert constat["composantes"]["comptes_a_payer"] is None and constat["composantes"]["paies"] == "4200.00"
    assert constat["planchers_cad"] == {"comptes_a_payer": "459.91"}
    assert list(constat)[list(constat).index("composantes") + 1] == "planchers_cad", "le plancher suit la décomposition"


def test_chaque_montant_est_repris_verbatim_aucun_calcul_aucun_arrondi_aucune_normalisation():
    """« 27861.980 » (un zéro de trop) ressort à l'identique : ni `Decimal`, ni `round`, ni reformatage."""
    charge = _charge(cash_libre_cad="27861.980", solde=_composante("solde", "37654.330"))

    constat = cash_libre.section([_fait(charge)], None, [])["constat"]

    assert constat["cash_libre_cad"] == "27861.980" and constat["composantes"]["solde"] == "37654.330"


def test_un_deficit_est_montre_tel_quel_negatif_jamais_ramene_a_zero():
    charge = _charge(
        cash_libre_cad="-7792.35", en_deficit=True,
        lecture="Cash libre : -7792.35 $ (solde moins toutes les obligations ci-dessous). C'est un déficit : les "
                "obligations connues dépassent le solde. Sous réserve : REJ-AP-UNITE-PRIX-NON-CONFIRMEE.")

    constat = cash_libre.section([_fait(charge)], None, [])["constat"]

    assert (constat["cash_libre_cad"], constat["en_deficit"]) == ("-7792.35", True)
    assert "C'est un déficit" in constat["lecture"]


def test_un_constat_non_calculable_est_montre_tel_quel_et_ajoute_un_manque_qui_renvoie_a_ses_codes():
    manques = []

    section = cash_libre.section([_fait(_charge_non_calculable())], "2026-09-30", manques)

    constat = section["constat"]
    assert section["statut"] == "lu", "M8 a bien reçu un constat : c'est M5 qui dit « non calculable »"
    assert constat["statut"] == "NON_CALCULABLE" and constat["cash_libre_cad"] is None
    assert constat["au_plus_cad"] == "32061.98" and constat["en_deficit"] is None
    assert "PAS de l'argent disponible" in constat["lecture"]
    assert constat["manque"] == ["paies : REJ-CASH-PAIE-A-DECLARER"]
    assert constat["composantes"]["paies"] is None, "M5 n'a pas pu chiffrer les paies : null, jamais zéro"
    assert constat["composantes"]["das"] == "1350.75"
    assert manques == [{
        "champ": "cash_libre", "source": "M5 (m5.cash_libre_constate)",
        "raison": "M5 a constaté le cash libre « non calculable » le 2026-09-29 : voir cash_libre.constat.manque",
    }]
    assert section["age"] == {"jours": 1, "aujourd_hui": "2026-09-30"}


def test_plusieurs_manques_sont_tous_dits_dans_l_ordre_de_m5_et_le_manque_de_la_vue_n_est_dit_qu_une_fois():
    charge = _charge_non_calculable(manque=("paies", "das", "dettes"))
    manques = []

    section = cash_libre.section([_fait(charge)], None, manques)
    cash_libre.section([_fait(charge)], None, manques)

    assert section["constat"]["manque"] == [
        "paies : REJ-CASH-PAIE-A-DECLARER", "das : REJ-CASH-DAS-A-DECLARER", "dettes : REJ-CASH-DETTES-A-DECLARER"]
    assert len(manques) == 1 and manques[0]["raison"].endswith("voir cash_libre.constat.manque")


def test_une_composante_qui_manque_pour_deux_raisons_donne_deux_entrees_rien_n_est_fusionne():
    charge = _charge_non_calculable()
    charge["manque"] = [
        {"composante": "paies", "code": "REJ-CASH-PAIE-A-DECLARER"},
        {"composante": "paies", "code": "REJ-CASH-DECLARATION-INVALIDE"},
    ]
    assert erreurs_charge(TYPE, charge) == []

    constat = cash_libre.section([_fait(charge)], None, [])["constat"]

    assert constat["manque"] == ["paies : REJ-CASH-PAIE-A-DECLARER", "paies : REJ-CASH-DECLARATION-INVALIDE"]


def test_un_statut_que_m5_n_a_pas_dit_calcule_est_traite_comme_non_calcule_par_prudence():
    fait = {**_fait(_charge()), "statut": "PEUT-ETRE"}
    manques = []

    section = cash_libre.section([fait], None, manques)

    assert section["constat"]["statut"] == "PEUT-ETRE", "repris tel quel, jamais réécrit"
    assert len(manques) == 1 and manques[0]["champ"] == "cash_libre"


def test_la_section_montre_le_dernier_constat_et_compte_ceux_qu_elle_a_recus():
    faits = [_fait(_charge(sequence=n, jour=f"2026-09-{20 + n}")) for n in (2, 1, 3)]

    section = cash_libre.section(faits, "2026-10-01", [])

    assert section["n_constats_recus"] == 3 and section["constat"]["sequence"] == 3
    assert section["age"] == {"jours": 8, "aujourd_hui": "2026-10-01"}, "de 2026-09-23 à 2026-10-01"
    relivre = cash_libre.section([*faits, dict(faits[0])], "2026-10-01", [])
    assert relivre["n_constats_recus"] == 3, "une relivraison du même événement ne compte pas comme un constat de plus"


def test_la_section_ne_modifie_pas_le_fait_range():
    fait = _fait(_charge())
    avant = copy.deepcopy(fait)

    section = cash_libre.section([fait], "2026-10-02", [])
    section["constat"]["composantes"].clear()
    section["constat"]["reserves"].append("REJ-AUTRE")
    section["constat"]["manque"].append("paies : REJ-X")
    cash_libre.reduire(section)

    assert fait == avant


def test_la_section_ne_porte_ni_hypotheses_ni_source_de_composante_et_le_dit():
    section = cash_libre.section([_fait(_charge())], None, [])
    texte = json.dumps(section, ensure_ascii=False)

    for absent in ("crédits de taxes sur intrants", "registre", "tete", "origine", "derniere_piece", "libelle"):
        assert absent not in texte, absent
    assert "hypothèses" in section["non_repris"] and "source" in section["non_repris"]


# =========================================================================================
# 5. La borne : en dernier recours, la décomposition part, comptée et dite
# =========================================================================================
def test_reduire_retire_la_decomposition_la_compte_et_la_dit_sans_toucher_a_l_essentiel():
    section = cash_libre.section([_fait(_charge_non_calculable(manque=("paies", "das")))], "2026-10-02", [])
    essentiel = {cle: valeur for cle, valeur in section["constat"].items() if cle != "composantes"}

    assert cash_libre.reduire(section) is True

    constat = section["constat"]
    assert "composantes" not in constat and constat["composantes_omises"] == 7
    assert {cle: valeur for cle, valeur in constat.items() if cle != "composantes_omises"} == essentiel
    assert "planchers_cad" not in constat
    assert section["non_repris"] == "décomposition, source et fraîcheur de chaque composante, hypothèses"
    assert section["statut"] == "lu" and section["age"] == {"jours": 3, "aujourd_hui": "2026-10-02"}
    assert constat["manque"] and constat["mention"] == MENTION and constat["lecture"]


def test_reduire_ne_fait_rien_de_plus_la_seconde_fois_ni_sur_une_section_manque():
    section = cash_libre.section([_fait(_charge())], None, [])
    assert cash_libre.reduire(section) is True
    apres = copy.deepcopy(section)

    assert cash_libre.reduire(section) is False and section == apres
    manque = cash_libre.section([], None, [])
    assert cash_libre.reduire(manque) is False and "constat" not in manque


def test_reduire_retire_aussi_les_planchers_qui_font_partie_de_la_decomposition_et_garde_au_plus():
    composantes = [_composante(cid, _MONTANTS[cid], origine=_ORIGINES.get(cid, "REGISTRE")) for cid in ORDRE]
    composantes[3] = _composante("comptes_a_payer", None, statut="NON_CALCULABLE", plancher="459.91")
    charge = _charge(
        statut="NON_CALCULABLE", cash_libre_cad=None, en_deficit=None, au_plus_cad="27861.98", composantes=composantes,
        manque=[{"composante": "comptes_a_payer", "code": "REJ-CASH-COMPTES-A-PAYER-INCOMPLETS"}],
        lecture="Cash libre non calculable : 1 manque(s). Au plus 27861.98 $ : ce n'est PAS de l'argent disponible.")
    section = cash_libre.section([_fait(charge)], None, [])
    assert section["constat"]["planchers_cad"] == {"comptes_a_payer": "459.91"}

    assert cash_libre.reduire(section) is True

    constat = section["constat"]
    assert "planchers_cad" not in constat and "composantes" not in constat and constat["composantes_omises"] == 7
    assert constat["au_plus_cad"] == "27861.98" and constat["cash_libre_cad"] is None


def test_la_reduction_raccourcit_vraiment_la_section():
    section = cash_libre.section([_fait(_charge())], None, [])
    avant = len(json.dumps(section, ensure_ascii=False))

    cash_libre.reduire(section)

    assert len(json.dumps(section, ensure_ascii=False)) < avant - 100


# =========================================================================================
# 6. Garde statique : M8 ne calcule aucun montant de M5
# =========================================================================================
def _arbre():
    return ast.parse((_SRC_M8 / "cash_libre.py").read_text(encoding="utf-8"))


def test_le_module_n_a_ni_decimal_ni_float_ni_round_ni_sum_ni_nombres():
    arbre = _arbre()
    noms = {n.id for n in ast.walk(arbre) if isinstance(n, ast.Name)}
    importes = {a.name.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names}
    importes |= {n.module.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module}
    importes |= {a.name for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module is None for a in n.names}

    assert not {"Decimal", "float", "round", "sum", "nombres", "decimal"} & (noms | importes)
    assert "marge_reelle_cad" not in noms
    assert importes == {"__future__", "re", "datetime", "typing"}, "aucun import d'opsys ni d'un autre département"


def test_la_seule_operation_arithmetique_du_module_est_la_soustraction_de_deux_dates_de_l_age():
    arithmetique = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    operations = []
    for fonction in [n for n in ast.walk(_arbre()) if isinstance(n, ast.FunctionDef)]:
        for noeud in ast.walk(fonction):
            if (isinstance(noeud, ast.BinOp) and isinstance(noeud.op, arithmetique)) or isinstance(
                    noeud, ast.AugAssign):
                operations.append((fonction.name, type(getattr(noeud, "op", None)).__name__))

    assert operations == [("age_en_jours", "Sub")]
    assert not [n for n in ast.walk(_arbre()) if isinstance(n, ast.AugAssign)]


def test_le_module_n_appelle_aucune_horloge():
    source = (_SRC_M8 / "cash_libre.py").read_text(encoding="utf-8")

    for horloge in ("now(", "today(", "utcnow(", "time.time", "monotonic", "perf_counter", "strftime"):
        assert horloge not in source, horloge
