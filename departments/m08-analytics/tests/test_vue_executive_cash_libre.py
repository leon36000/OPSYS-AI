"""PLAN T4.19-b : la vue exécutive montre le DERNIER constat du cash libre que M5 a publié, tel quel, avec son âge.

Ce que ce fichier prouve, par l'outil `m8_lire_vue_executive` (le chemin réel d'un appel) :
- le constat de M5 est repris valeur pour valeur : montants en texte, statut, ce qui manque, réserves, phrase et mention
  de M5 ; M8 ne calcule rien (les gardes statiques sont dans `test_cash_libre.py` et `test_vue_executive.py`) ;
- l'âge vient de la date de l'appelant (`aujourd_hui`), jamais d'une horloge de M8 : sans elle, « non calculable » ; une
  date illisible est refusée AVANT toute lecture, et après le contrôle de l'identité ;
- un constat « non calculable, manque X » passe tel quel (jamais un zéro) et s'ajoute aux manques de la vue ;
- le dernier constat est celui de plus grand rang, quel que soit l'ordre des faits ;
- la borne du socle raccourcit d'abord les listes ; la décomposition du cash libre ne part qu'en dernier recours,
  comptée et dite, et les montants ne partent jamais ;
- lecture pure : rien n'est écrit ni publié, et M5 n'est pas appelé.

Les constats sont des charges fictives conformes au catalogue du socle (chacune est validée par le schéma fermé avant
d'être utilisée). Les tests de la vue sans constat sont dans `test_vue_executive.py`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from m8_analytics import cash_libre, entonnoir, mesures_chantier, vue_executive
from m8_analytics import outils as m8_outils
from m8_analytics.outils import outils
from m8_analytics.registre import RegistreSnapshots
from sqlalchemy import func, select

from opsys import contexte, identite, jetons, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.evenements.schemas import erreurs_charge
from opsys.outils import executer, executer_atomique
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

FICTIF = True  # aucun client réel : des identifiants, des personnes et des montants de test

TYPE = "m5.cash_libre_constate"
_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
_M6 = "m06-material-control"
_ADMIN = IdentiteAppelante("admin.fictif", "admin")
MENTION = (
    "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle ou action "
    "réelle."
)


# ---------------------------------------------------------------------------
# Constats de M5 : des charges fictives, validées par le catalogue avant usage
# ---------------------------------------------------------------------------
_ORDRE = ["taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves"]
_LIBELLES = {
    "solde": "solde", "taxes_a_remettre": "TPS/TVQ à remettre", "paies": "Paies",
    "das": "Déductions à la source (DAS)", "comptes_a_payer": "Comptes à payer", "dettes": "Dettes",
    "reserves": "Réserves critiques",
}
_MONTANTS = {
    "taxes_a_remettre": "1981.69", "paies": "4200.00", "das": "1350.75", "comptes_a_payer": "459.91",
    "dettes": "800.00", "reserves": "1000.00",
}
_DECLARATION = "DECLARATION_PROPRIETAIRE"
_ORIGINES = {"paies": _DECLARATION, "das": _DECLARATION, "dettes": _DECLARATION}
_HYPOTHESES = [
    "crédits de taxes sur intrants : factures fournisseur SAISIES seulement, récupérables à 100 % (à valider)",
    "les comptes à recevoir ne sont PAS ajoutés : leur argent n'est pas au solde",
]


def _composante(cid, montant, *, statut="CALCULE", origine="REGISTRE", piece="2026-09-14", pieces=1):
    registres = [{"registre": "mouvements", "taille": 3, "tete": "0123456789abcdef"}] if origine == "REGISTRE" else []
    return {
        "id": cid, "libelle": _LIBELLES[cid], "statut": statut, "montant_cad": montant, "plancher_cad": None,
        "source": {"origine": origine, "registres": registres},
        "fraicheur": {"derniere_piece": piece, "pieces": pieces},
    }


def _constat(sequence=1, jour="2026-09-29", **surcharges):
    """Le fait rangé par M8 pour un constat calculé (27861.98 $), validé par le catalogue du socle."""
    version = hashlib.sha256(f"version-{sequence}-{jour}".encode()).hexdigest()
    charge = {
        "evenement_id": f"m5-cash-libre-{sequence}-{jour}-{version[:16]}", "sequence": sequence,
        "date_reference": jour, "version_donnees": version, "devise": "CAD", "statut": "CALCULE",
        "cash_libre_cad": "27861.98", "au_plus_cad": None, "en_deficit": False,
        "lecture": "Cash libre : 27861.98 $ (solde moins toutes les obligations ci-dessous). "
                   "Sous réserve : REJ-AP-UNITE-PRIX-NON-CONFIRMEE.",
        "solde": _composante("solde", "37654.33", piece="2026-09-10T12:00:00-04:00", pieces=3),
        "composantes": [_composante(cid, _MONTANTS[cid], origine=_ORIGINES.get(cid, "REGISTRE")) for cid in _ORDRE],
        "manque": [], "reserves": ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"], "hypotheses": list(_HYPOTHESES),
        "mention": MENTION,
    }
    charge.update(surcharges)
    assert erreurs_charge(TYPE, charge) == [], "la donnée de test doit être conforme au catalogue"
    return cash_libre.fait_constat(charge)


def _constat_non_calculable(sequence=1, jour="2026-09-29"):
    composantes = [
        _composante(cid, None, statut="NON_CALCULABLE", origine="AUCUNE", piece=None, pieces=0) if cid == "paies"
        else _composante(cid, _MONTANTS[cid], origine=_ORIGINES.get(cid, "REGISTRE"))
        for cid in _ORDRE
    ]
    return _constat(
        sequence, jour, statut="NON_CALCULABLE", cash_libre_cad=None, au_plus_cad="32061.98", en_deficit=None,
        lecture="Cash libre non calculable : 1 manque(s) (voir manque). Au plus 32061.98 $ : le solde moins ce qui est "
                "connu ; ce qui manque ne peut que le réduire. Ce n'est PAS de l'argent disponible.",
        composantes=composantes, manque=[{"composante": "paies", "code": "REJ-CASH-PAIE-A-DECLARER"}],
    )


# ---------------------------------------------------------------------------
# Faits de l'entonnoir et des chantiers, construits par les vrais constructeurs
# ---------------------------------------------------------------------------
def _lead(lead_id):
    return entonnoir.fait_lead_recu(
        {"lead_id": lead_id, "client_id": "a" * 64, "horodatage_association": "2026-09-29T09:15:00-04:00"}
    )


def _sans_reponse(devis_id):
    return entonnoir.fait_devis_sans_reponse({
        "devis_id": devis_id, "lead_id": "lead-1-fictif", "statut": "envoye",
        "horodatage_devis": "2026-09-29T15:30:00-04:00", "horodatage_reference": "2026-10-08T08:00:00-04:00",
        "delai_relance_jours": 7,
    })


def _wct(wct_id, devis_id):
    return mesures_chantier.fait_wct({
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "devis_id": devis_id, "technicien_id": "tech-fictif",
        "horodatage_completion": "2026-10-05T14:00:00-04:00", "duree_reelle_minutes": 100,
        "statut": "completed_verified",
    })


def _marge(wct_id, devis_id, marge):
    return mesures_chantier.fait_rentabilite({
        "wct_id": wct_id, "devis_id": devis_id, "sequence": 1, "marge_reelle_cad": marge, "verdict": "CALCULEE",
        "cout_reel_complet": True, "manque": [],
    })


def _besoin(materiau, resume=None):
    return {
        "type": "besoin_commande", "id": f"besoin_commande:{materiau}",
        "resume": resume or f"Stock bas : {materiau} — 10 pi en main, sous le seuil de 150 pi (fictif)",
        "niveau": "N2", "depuis": "2026-10-04T12:00:00+00:00",
        "action_proposee": "Décider de commander : M6 n'en crée jamais seul (fictif)",
    }


def _par_nom(faits_cash_libre=None, faits_entonnoir=None, faits_chantier=None):
    return {
        o.nom: o
        for o in outils(
            RegistreSnapshots(), [], faits_chantier if faits_chantier is not None else [],
            faits_entonnoir if faits_entonnoir is not None else [],
            faits_cash_libre_cible=faits_cash_libre if faits_cash_libre is not None else [],
        )
    }


def _lire(par_nom, arguments=None, appelante=None, atomique=False):
    lancer = executer_atomique if atomique else executer
    if appelante is None:
        return lancer(par_nom["m8_lire_vue_executive"], arguments or {})
    with contexte.appele_par_appareil(appelante):
        return lancer(par_nom["m8_lire_vue_executive"], arguments or {})


def _vue(par_nom, arguments=None, appelante=None, atomique=False):
    reponse = _lire(par_nom, arguments, appelante, atomique)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _manques_de_cash_libre(vue):
    return [m for m in vue["manques"] if m["champ"] == "cash_libre"]


class _Faux:
    """Un département de test : il donne sa fonction `attentes()` et compte ses appels. La vue ne doit appeler QUE
    M6, jamais l'outil d'un département (M5 compris : ce qu'il a publié est déjà chez M8)."""

    def __init__(self, identifiant, attentes=()):
        self.id = identifiant
        self._attentes = list(attentes)
        self.appels = 0

    def charger_attentes(self):
        def attentes():
            self.appels += 1
            return list(self._attentes)

        return attentes

    def charger_outils(self):
        raise AssertionError(f"{self.id} : la vue exécutive n'appelle l'outil d'aucun département")


@pytest.fixture
def m6_de_test(monkeypatch):
    def poser(attentes=()):
        m6, m5 = _Faux(_M6, attentes), _Faux("m05-financecore")
        monkeypatch.setattr(m8_outils, "charger_departements", lambda: {_M6: m6, "m05-financecore": m5})
        return m6, m5

    return poser


@pytest.fixture
def base_avec_personnes(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictif", "mot-de-passe-admin-1234", ["admin"])
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-1234", ["employee"])
    yield url
    stockage.liberer()


@pytest.fixture
def lire_vue(base_avec_personnes, m6_de_test):
    """La vue lue comme en production : par l'admin, dans la transaction d'un outil, M6 lisible (aucune attente). Sans
    cela, « M6 illisible » ajoute un manque de plus et la vue frôle la borne du socle : ce n'est pas ce qu'on prouve."""
    m6_de_test()

    def lire(faits_cash_libre=None, arguments=None, **registres):
        return _vue(_par_nom(faits_cash_libre, **registres), arguments, _ADMIN, atomique=True)

    return lire


class _RegistreQuiNeSeLitPas:
    """Un registre qui échoue s'il est lu : prouve qu'un refus arrive AVANT toute lecture."""

    def __iter__(self):
        raise AssertionError("un registre a été lu avant le refus")


# =========================================================================================
# 1. Le constat, tel quel, avec son âge
# =========================================================================================
def test_le_dernier_constat_de_m5_est_montre_tel_quel_avec_son_age(lire_vue):
    vue = lire_vue([_constat()], {"aujourd_hui": "2026-10-02"})

    section = vue["cash_libre"]
    assert set(section) == {"source", "statut", "n_constats_recus", "constat", "age", "non_repris", "a_lire"}
    assert section["statut"] == "lu" and section["source"] == "M5 (m5.cash_libre_constate), repris sans aucun calcul"
    assert section["age"] == {"jours": 3, "aujourd_hui": "2026-10-02"} and section["n_constats_recus"] == 1
    constat = section["constat"]
    assert (constat["sequence"], constat["date_reference"], constat["statut"]) == (1, "2026-09-29", "CALCULE")
    assert (constat["cash_libre_cad"], constat["au_plus_cad"], constat["en_deficit"]) == ("27861.98", None, False)
    assert constat["lecture"].startswith("Cash libre : 27861.98 $") and constat["mention"] == MENTION
    assert constat["manque"] == [] and constat["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    assert list(constat["composantes"].items()) == [
        ("solde", "37654.33"), ("taxes_a_remettre", "1981.69"), ("paies", "4200.00"), ("das", "1350.75"),
        ("comptes_a_payer", "459.91"), ("dettes", "800.00"), ("reserves", "1000.00"),
    ]
    assert _manques_de_cash_libre(vue) == [], "un constat calculé ne crée aucun manque"


def test_la_vue_garde_sa_forme_et_le_reste_de_ses_sections_ne_change_pas_avec_un_constat(lire_vue):
    faits = [_lead("lead-1-fictif"), _sans_reponse("D1")]
    sans = lire_vue(faits_entonnoir=faits)
    avec = lire_vue([_constat()], faits_entonnoir=faits)

    assert set(avec) == set(sans) == {
        "vue", "portee", "entonnoir", "marge_reelle", "stock_a_commander", "cash_libre", "manques"}
    for section in ("vue", "portee", "entonnoir", "marge_reelle", "stock_a_commander"):
        assert avec[section] == sans[section], section
    assert avec["manques"] == [m for m in sans["manques"] if m["champ"] != "cash_libre"]
    assert sans["cash_libre"]["statut"] == "manque" and avec["cash_libre"]["statut"] == "lu"


def test_le_montant_ressort_a_l_identique_dans_la_vue_entiere_sans_arrondi_ni_reformatage(lire_vue):
    """« 27861.980 » (un zéro de trop) et « 37654.330 » : ni `Decimal`, ni `round`, ni reformatage."""
    fait = _constat(cash_libre_cad="27861.980", solde=_composante("solde", "37654.330"))

    texte = json.dumps(lire_vue([fait], {"aujourd_hui": "2026-09-29"}), ensure_ascii=False)

    assert '"cash_libre_cad": "27861.980"' in texte and '"solde": "37654.330"' in texte
    assert "27861.98," not in texte and "37654.33," not in texte


def test_un_deficit_est_montre_negatif_tel_que_m5_l_a_dit():
    fait = _constat(
        cash_libre_cad="-7792.35", en_deficit=True,
        lecture="Cash libre : -7792.35 $ (solde moins toutes les obligations ci-dessous). C'est un déficit : les "
                "obligations connues dépassent le solde. Sous réserve : REJ-AP-UNITE-PRIX-NON-CONFIRMEE.",
    )

    constat = _vue(_par_nom([fait]))["cash_libre"]["constat"]

    assert (constat["cash_libre_cad"], constat["en_deficit"]) == ("-7792.35", True)
    assert "C'est un déficit" in constat["lecture"]


def test_un_constat_non_calculable_passe_tel_quel_et_s_ajoute_aux_manques_de_la_vue_jamais_un_zero(lire_vue):
    vue = lire_vue([_constat_non_calculable()], {"aujourd_hui": "2026-09-30"})

    section = vue["cash_libre"]
    constat = section["constat"]
    assert section["statut"] == "lu", "M8 a bien reçu un constat : c'est M5 qui dit « non calculable »"
    assert constat["statut"] == "NON_CALCULABLE" and constat["cash_libre_cad"] is None
    assert constat["en_deficit"] is None and constat["au_plus_cad"] == "32061.98"
    assert "PAS de l'argent disponible" in constat["lecture"]
    assert constat["manque"] == [{"composante": "paies", "code": "REJ-CASH-PAIE-A-DECLARER"}]
    assert constat["composantes"]["paies"] is None and constat["composantes"]["das"] == "1350.75"
    assert section["age"] == {"jours": 1, "aujourd_hui": "2026-09-30"}
    assert _manques_de_cash_libre(vue) == [{
        "champ": "cash_libre", "source": "M5 (m5.cash_libre_constate)",
        "raison": "M5 a constaté le cash libre « non calculable » le 2026-09-29 : "
                  "manque paies (REJ-CASH-PAIE-A-DECLARER)",
    }]
    texte = json.dumps(vue, ensure_ascii=False)
    assert '"cash_libre_cad": "0' not in texte and '"cash_libre_cad": 0' not in texte


def test_un_constat_non_calculable_plus_recent_remplace_un_constat_calcule_plus_ancien():
    """Le dernier état de M5 fait foi : si une déclaration disparaît, le cash libre d'hier n'est plus dit."""
    faits = [_constat(sequence=1, jour="2026-09-28"), _constat_non_calculable(sequence=2, jour="2026-09-29")]

    vue = _vue(_par_nom(faits))

    assert vue["cash_libre"]["constat"]["statut"] == "NON_CALCULABLE"
    assert vue["cash_libre"]["n_constats_recus"] == 2
    assert "27861.98" not in json.dumps(vue["cash_libre"]["constat"]["cash_libre_cad"])
    assert len(_manques_de_cash_libre(vue)) == 1


@pytest.mark.parametrize("ordre", [(1, 2, 3), (3, 2, 1), (2, 3, 1), (1, 3, 2)])
def test_le_constat_de_plus_grand_rang_fait_foi_quel_que_soit_l_ordre_des_faits(ordre):
    faits = [_constat(sequence=n, jour=f"2026-09-{20 + n}") for n in ordre]

    section = _vue(_par_nom(faits))["cash_libre"]

    assert section["constat"]["sequence"] == 3 and section["constat"]["date_reference"] == "2026-09-23"
    assert section["n_constats_recus"] == 3


# =========================================================================================
# 2. L'âge : la date de l'appelant, jamais une horloge de M8
# =========================================================================================
@pytest.mark.parametrize("aujourd_hui, attendu", [
    ("2026-09-29", 0), ("2026-09-30", 1), ("2026-10-02", 3), ("2026-10-29", 30), ("2027-09-29", 365),
])
def test_l_age_suit_la_date_donnee_par_l_appelant(aujourd_hui, attendu):
    age = _vue(_par_nom([_constat()]), {"aujourd_hui": aujourd_hui})["cash_libre"]["age"]

    assert age == {"jours": attendu, "aujourd_hui": aujourd_hui}


@pytest.mark.parametrize("arguments", [{}, {"aujourd_hui": None}])
def test_sans_aujourd_hui_l_age_est_non_calculable_et_le_montant_est_quand_meme_montre(arguments):
    section = _vue(_par_nom([_constat()]), arguments)["cash_libre"]

    assert section["age"] == {
        "jours": None, "raison": "aujourd_hui non fourni : M8 n'a pas d'horloge, la date vient de l'appelant"}
    assert section["constat"]["cash_libre_cad"] == "27861.98"


def test_un_constat_date_d_apres_aujourd_hui_est_dit_incoherent_jamais_un_age_negatif():
    age = _vue(_par_nom([_constat(jour="2026-10-05")]), {"aujourd_hui": "2026-10-02"})["cash_libre"]["age"]

    assert age["jours"] is None
    assert age["raison"] == "la date de référence du constat (2026-10-05) est postérieure à aujourd_hui"


def test_la_meme_lecture_a_deux_dates_ne_change_que_l_age():
    par_nom = _par_nom([_constat()])

    lundi = _vue(par_nom, {"aujourd_hui": "2026-09-29"})["cash_libre"]
    jeudi = _vue(par_nom, {"aujourd_hui": "2026-10-02"})["cash_libre"]

    assert (lundi["age"]["jours"], jeudi["age"]["jours"]) == (0, 3)
    assert {**lundi, "age": None} == {**jeudi, "age": None}


@pytest.mark.parametrize("brut", [
    "", "hier", "2026-10-2", "02/10/2026", "20261002", "2026-02-30", "2027-02-29", "2026-13-01",
    "2026-10-02T09:00:00-04:00", " 2026-10-02", "2026-10-02\n",
])
def test_une_date_illisible_est_refusee_par_son_code_avant_toute_lecture(brut):
    par_nom = _par_nom(_RegistreQuiNeSeLitPas(), _RegistreQuiNeSeLitPas(), _RegistreQuiNeSeLitPas())

    reponse = _lire(par_nom, {"aujourd_hui": brut})

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert reponse["details"].startswith("REJ-VUE-AUJOURD-HUI-INVALIDE")


@pytest.mark.parametrize("brut", [20261002, 2026.1002, True, ["2026-10-02"], {"jour": "2026-10-02"}])
def test_une_date_qui_n_est_pas_du_texte_est_refusee_par_le_schema_de_l_outil(brut):
    reponse = _lire(_par_nom([_constat()]), {"aujourd_hui": brut})

    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"


def test_le_controle_de_l_identite_passe_avant_celui_de_la_date(base_avec_personnes):
    """Un employé qui envoie une date illisible reçoit le refus d'identité, pas le refus de la date : l'existence du
    contrôle de la date ne se découvre pas sans avoir le droit de lire."""
    par_nom = _par_nom(_RegistreQuiNeSeLitPas(), _RegistreQuiNeSeLitPas(), _RegistreQuiNeSeLitPas())
    employe = IdentiteAppelante("employe.fictif", "employee")

    reponse = _lire(par_nom, {"aujourd_hui": "pas-une-date"}, employe, atomique=True)
    admin = _lire(par_nom, {"aujourd_hui": "pas-une-date"}, _ADMIN, atomique=True)

    assert reponse["ok"] is False and reponse["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE")
    assert admin["ok"] is False and admin["details"].startswith("REJ-VUE-AUJOURD-HUI-INVALIDE")


# =========================================================================================
# 3. La borne : les listes d'abord, la décomposition en dernier recours, les montants jamais
# =========================================================================================
def _situation_chargee():
    faits = [_sans_reponse(f"D{numero}") for numero in range(8)]
    return entonnoir.situation(faits, [], entonnoir.charger_definitions(), {})


def _chantiers(nombre):
    faits = []
    for numero in range(nombre):
        faits += [_wct(f"w{numero}", f"X{numero}"), _marge(f"w{numero}", f"X{numero}", f"{numero + 1}0.00")]
    return faits


def _listes(vue):
    attente = vue["entonnoir"]["devis_en_attente"]
    return [
        len(vue["marge_reelle"]["chantiers"]), len(vue["stock_a_commander"]["articles"]),
        len(attente["sans_reponse"]["devis"]), len(attente["brouillons_en_retard"]["devis"]),
    ]


def _totaux(vue):
    return (
        vue["marge_reelle"]["n_chantiers"], vue["stock_a_commander"]["n_articles"],
        vue["entonnoir"]["devis_en_attente"]["sans_reponse"]["n"],
    )


_ESSENTIEL = ("evenement_id", "sequence", "date_reference", "statut", "cash_libre_cad", "au_plus_cad", "en_deficit",
              "lecture", "manque", "reserves", "mention")


def test_la_decomposition_ne_part_qu_apres_toutes_les_listes_et_les_montants_ne_partent_jamais():
    situation, chantiers = _situation_chargee(), _chantiers(6)
    attentes = [_besoin(f"article-{numero}-fictif") for numero in range(6)]
    faits = [_constat_non_calculable()]

    def assembler(budget=None):
        return vue_executive.assembler(
            situation, chantiers, attentes, None, budget, faits_cash_libre=faits, aujourd_hui="2026-10-02")

    complete = assembler()
    essentiel = {cle: complete["cash_libre"]["constat"][cle] for cle in _ESSENTIEL}
    taille = len(json.dumps(complete, ensure_ascii=False))
    listes_reduites, decomposition_retiree, refus = 0, 0, 0

    for budget in range(taille, 0, -7):  # un pas premier : toutes les tailles de fin de liste sont traversées
        try:
            vue = assembler(budget)
        except ValueError as exc:
            assert f"borne de {budget} caractères" in str(exc)
            refus += 1
            continue
        constat = vue["cash_libre"]["constat"]
        assert len(json.dumps(vue, ensure_ascii=False)) <= budget
        assert {cle: constat[cle] for cle in _ESSENTIEL} == essentiel, "la borne ne touche jamais à l'essentiel"
        assert _totaux(vue) == _totaux(complete), "les totaux ne se réduisent jamais"
        if "composantes_omises" in constat:
            decomposition_retiree += 1
            assert "composantes" not in constat and constat["composantes_omises"] == 7
            assert _listes(vue) == [0, 0, 0, 0], "la décomposition ne part qu'une fois toutes les listes vides"
            assert vue["cash_libre"]["non_repris"].startswith("décomposition, source et fraîcheur")
        else:
            assert len(constat["composantes"]) == 7
            assert vue["cash_libre"]["non_repris"] == "source et fraîcheur de chaque composante, hypothèses"
            listes_reduites += _listes(vue) != _listes(complete)

    assert listes_reduites > 0 and decomposition_retiree > 0 and refus > 0, "les trois régimes ont bien été traversés"


def test_sans_aucune_liste_a_raccourcir_la_decomposition_est_retiree_comptee_et_dite():
    situation = entonnoir.situation([], [], entonnoir.charger_definitions(), {})
    complete = vue_executive.assembler(situation, [], [], None, faits_cash_libre=[_constat()], aujourd_hui="2026-10-02")
    borne = len(json.dumps(complete, ensure_ascii=False)) - 1

    vue = vue_executive.assembler(
        situation, [], [], None, borne, faits_cash_libre=[_constat()], aujourd_hui="2026-10-02")

    constat = vue["cash_libre"]["constat"]
    assert "composantes" not in constat and constat["composantes_omises"] == 7
    assert vue["cash_libre"]["non_repris"].startswith("décomposition, source et fraîcheur de chaque composante")
    assert constat["cash_libre_cad"] == "27861.98" and constat["mention"] == MENTION
    assert len(json.dumps(vue, ensure_ascii=False)) <= borne


def test_une_vue_qui_ne_tient_pas_meme_sans_decomposition_est_un_refus_jamais_une_reponse_coupee():
    situation = entonnoir.situation([], [], entonnoir.charger_definitions(), {})

    with pytest.raises(ValueError, match="dépasse à elle seule la borne de 300 caractères"):
        vue_executive.assembler(situation, [], [], None, 300, faits_cash_libre=[_constat()])


def test_la_vue_d_une_grosse_entreprise_avec_un_constat_tient_sous_la_limite_du_socle_et_garde_le_constat(
        base_avec_personnes, m6_de_test):
    m6_de_test(attentes=[
        _besoin(f"article-numero-{numero:02d}-fictif", resume="Stock bas : " + "x" * 300 + f" ({numero})")
        for numero in range(40)
    ])
    with stockage.transaction():
        chantier = stockage.maillons("m08-analytics", "faits_chantier")
        registre = stockage.maillons("m08-analytics", "faits_entonnoir")
        for fait in _chantiers(60):
            chantier.append(fait)
        registre.append(_lead("lead-1-fictif"))
        for numero in range(40):
            registre.append(_sans_reponse(f"DEVIS-EN-ATTENTE-{numero:02d}"))
        stockage.maillons("m08-analytics", "faits_cash_libre").append(_constat_non_calculable())
    capacites = Capacites(
        charger_departements(_RACINE_DEPARTEMENTS), stockage.transaction, filtre={"m08-analytics"}, memoire=False,
    )

    with contexte.appele_par_appareil(_ADMIN):
        reponse = capacites.appeler("m8_lire_vue_executive", {"aujourd_hui": "2026-10-02"})

    assert reponse["ok"] is True and "tronque" not in reponse, reponse
    assert len(json.dumps(reponse, ensure_ascii=False)) <= jetons.LIMITE_SORTIE_DEFAUT
    vue = reponse["resultat"]
    assert vue["marge_reelle"]["n_chantiers"] == 60 and vue["stock_a_commander"]["n_articles"] == 40
    assert vue["marge_reelle"]["reste"] + vue["stock_a_commander"]["reste"] > 0, "la borne a joué"
    section = vue["cash_libre"]
    assert section["age"] == {"jours": 3, "aujourd_hui": "2026-10-02"}
    assert section["constat"]["statut"] == "NON_CALCULABLE" and section["constat"]["au_plus_cad"] == "32061.98"
    assert len(section["constat"]["composantes"]) == 7 and "composantes_omises" not in section["constat"], (
        "des listes restaient à raccourcir : la décomposition n'a pas dû partir")
    assert len(_manques_de_cash_libre(vue)) == 1


# =========================================================================================
# 4. Lecture pure ; M5 n'est ni appelé ni recalculé
# =========================================================================================
def _etat_des_ecritures():
    with stockage.transaction() as cnx:
        return {
            "registres": cnx.execute(select(func.count()).select_from(REGISTRES)).scalar_one(),
            "sortants": cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one(),
            "recus": cnx.execute(select(func.count()).select_from(EVENEMENTS_RECUS)).scalar_one(),
        }


def test_la_lecture_d_un_constat_n_ecrit_rien_et_ne_publie_rien(base_avec_personnes, m6_de_test):
    m6_de_test()
    with stockage.transaction():
        stockage.maillons("m08-analytics", "faits_cash_libre").append(_constat())
    avant = _etat_des_ecritures()
    par_nom = {o.nom: o for o in outils()}  # le registre durable, comme en production

    premiere = _vue(par_nom, {"aujourd_hui": "2026-10-02"}, _ADMIN, atomique=True)
    seconde = _vue(par_nom, {"aujourd_hui": "2026-10-02"}, _ADMIN, atomique=True)

    assert _etat_des_ecritures() == avant
    assert premiere == seconde and premiere["cash_libre"]["constat"]["cash_libre_cad"] == "27861.98"


def test_la_vue_n_appelle_aucun_outil_de_m5_et_ne_lit_que_l_attente_de_m6(base_avec_personnes, m6_de_test):
    m6, m5 = m6_de_test()

    vue = _vue(_par_nom([_constat()]), {"aujourd_hui": "2026-10-02"}, _ADMIN, atomique=True)

    assert vue["cash_libre"]["statut"] == "lu"
    assert m5.appels == 0 and m6.appels == 1  # `charger_outils()` de M5 lèverait : M8 ne le fait pas


def test_le_constat_du_registre_durable_est_celui_que_la_vue_montre(base_avec_personnes, m6_de_test):
    m6_de_test()
    with stockage.transaction():
        registre = stockage.maillons("m08-analytics", "faits_cash_libre")
        registre.append(_constat(sequence=2, jour="2026-09-29"))
        registre.append(_constat(sequence=1, jour="2026-09-28"))
    par_nom = {o.nom: o for o in outils()}

    section = _vue(par_nom, {"aujourd_hui": "2026-10-01"}, _ADMIN, atomique=True)["cash_libre"]

    assert section["constat"]["sequence"] == 2 and section["n_constats_recus"] == 2
    assert section["age"] == {"jours": 2, "aujourd_hui": "2026-10-01"}


def test_par_capacites_l_admin_lit_le_constat_et_le_refus_de_l_employe_ne_montre_aucun_montant(
        base_avec_personnes, m6_de_test):
    m6_de_test()
    with stockage.transaction():
        stockage.maillons("m08-analytics", "faits_cash_libre").append(_constat())
    capacites = Capacites(
        charger_departements(_RACINE_DEPARTEMENTS), stockage.transaction, filtre={"m08-analytics"}, memoire=False,
    )

    with contexte.appele_par_appareil(IdentiteAppelante("employe.fictif", "employee")):
        refus = capacites.appeler("m8_lire_vue_executive", {})
    with contexte.appele_par_appareil(_ADMIN):
        accepte = capacites.appeler("m8_lire_vue_executive", {"aujourd_hui": "2026-09-30"})

    assert refus["ok"] is False and "REJ-IDENTITE-APPAREIL-INVALIDE" in json.dumps(refus, ensure_ascii=False)
    for montant in ("27861.98", "37654.33", "cash_libre", MENTION):
        assert montant not in json.dumps(refus, ensure_ascii=False), montant
    assert accepte["ok"] is True
    assert accepte["resultat"]["cash_libre"]["constat"]["cash_libre_cad"] == "27861.98"
    assert accepte["resultat"]["cash_libre"]["age"] == {"jours": 1, "aujourd_hui": "2026-09-30"}
