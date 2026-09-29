"""PLAN T4.19-b : le constat du cash libre de M5 atteint M8 (`m5.cash_libre_constate`).

M8 range chaque constat TEL QUE M5 l'a publié dans son registre `faits_cash_libre` (un fait par événement,
idempotent), et la vue exécutive montre le dernier. Les fonctions pures (`cash_libre.fait_constat`, `constat_courant`,
`section`) sont dans `test_cash_libre.py` ; ici, le VRAI bus (`opsys.evenements.repartir`, manifestes réels, M8 seul
abonné, base SQLite temporaire migrée). Les charges de M5 sont synthétiques et fictives, validées par le catalogue du
socle à la publication. Le bout en bout (M5 calcule et publie avec ses vrais outils, M8 le montre) est dans
`tests/test_cascade_cash_libre_m5_m8.py`.

Ce que ce fichier prouve :
- les manifestes sont cohérents (M5 publie, M8 consomme, le type est au catalogue, `verifier_coherence` est vide) ;
- le fait rangé est la charge de M5 telle quelle, et le résumé du reçu que le bus range ne porte aucun montant ;
- une relivraison, un rejeu et une double publication n'ajoutent jamais un second fait ;
- un constat « non calculable » passe tel quel (jamais un zéro), et le dernier constat fait foi quel que soit l'ordre ;
- M8 ne publie rien en recevant un constat ; le catalogue refuse à la publication un constat qui porte un
  renseignement personnel ou qui déguise un « non calculable » en montant.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import pytest
from m8_analytics import outils as m8_outils
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.evenements.schemas import erreurs_charge
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

FICTIF = True
TYPE = "m5.cash_libre_constate"
_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
_MAINTENANT = "2026-09-29T18:00:00+00:00"
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


def _composante(cid, montant, *, statut="CALCULE", origine="REGISTRE", piece="2026-09-14", pieces=1):
    registres = [{"registre": "mouvements", "taille": 3, "tete": "0123456789abcdef"}] if origine == "REGISTRE" else []
    return {
        "id": cid, "libelle": _LIBELLES[cid], "statut": statut, "montant_cad": montant, "plancher_cad": None,
        "source": {"origine": origine, "registres": registres},
        "fraicheur": {"derniere_piece": piece, "pieces": pieces},
    }


def _charge(sequence=1, jour="2026-09-29", version=None, **surcharges):
    """Charge `m5.cash_libre_constate` d'un cash libre calculé de 27861.98 $, conforme au catalogue."""
    version = version or hashlib.sha256(f"version-{sequence}-{jour}".encode()).hexdigest()
    charge = {
        "evenement_id": f"m5-cash-libre-{sequence}-{jour}-{version[:16]}", "sequence": sequence,
        "date_reference": jour, "version_donnees": version, "devise": "CAD", "statut": "CALCULE",
        "cash_libre_cad": "27861.98", "au_plus_cad": None, "en_deficit": False,
        "lecture": "Cash libre : 27861.98 $ (solde moins toutes les obligations ci-dessous). "
                   "Sous réserve : REJ-AP-UNITE-PRIX-NON-CONFIRMEE.",
        "solde": _composante("solde", "37654.33", piece="2026-09-10T12:00:00-04:00", pieces=3),
        "composantes": [_composante(cid, _MONTANTS[cid], origine=_ORIGINES.get(cid, "REGISTRE")) for cid in _ORDRE],
        "manque": [], "reserves": ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"],
        "hypotheses": [
            "crédits de taxes sur intrants : factures fournisseur SAISIES seulement, récupérables à 100 % (à valider)",
            "les comptes à recevoir ne sont PAS ajoutés : leur argent n'est pas au solde",
        ],
        "mention": MENTION,
    }
    charge.update(surcharges)
    return charge


def _charge_valide(*arguments, **surcharges):
    charge = _charge(*arguments, **surcharges)
    assert erreurs_charge(TYPE, charge) == [], "la donnée de test doit être conforme au catalogue"
    return charge


def _charge_non_calculable(sequence=1, jour="2026-09-29"):
    composantes = [
        _composante(cid, None, statut="NON_CALCULABLE", origine="AUCUNE", piece=None, pieces=0) if cid == "paies"
        else _composante(cid, _MONTANTS[cid], origine=_ORIGINES.get(cid, "REGISTRE"))
        for cid in _ORDRE
    ]
    return _charge_valide(
        sequence, jour, statut="NON_CALCULABLE", cash_libre_cad=None, au_plus_cad="32061.98", en_deficit=None,
        lecture="Cash libre non calculable : 1 manque(s) (voir manque). Au plus 32061.98 $ : le solde moins ce qui est "
                "connu ; ce qui manque ne peut que le réduire. Ce n'est PAS de l'argent disponible.",
        composantes=composantes, manque=[{"composante": "paies", "code": "REJ-CASH-PAIE-A-DECLARER"}],
    )


def _publier(charge, evenement_id=None):
    evenements.publier(
        TYPE, "m05-financecore", charge, evenement_id=charge["evenement_id"] if evenement_id is None else evenement_id
    )


# ---------------------------------------------------------------------------
# Le vrai bus : base migrée, manifestes réels, M8 seul abonné
# ---------------------------------------------------------------------------
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def departements():
    """Manifestes réels ; M8 seul reçoit les événements (les autres ont leurs propres tests)."""
    return {"m08-analytics": charger_departements(_RACINE_DEPARTEMENTS)["m08-analytics"]}


def _livrer(departements, maintenant=_MAINTENANT):
    resume = evenements.repartir(departements, maintenant=maintenant)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    return resume


def _faits():
    return list(stockage.maillons("m08-analytics", "faits_cash_libre"))


def _recus():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_RECUS).order_by(EVENEMENTS_RECUS.c.evenement_id)).mappings().all()
    return [{**ligne, "resultat": codec.decoder(ligne["resultat"])} for ligne in lignes]


def _sortants():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS).order_by(EVENEMENTS_SORTANTS.c.cree_le)).mappings().all()
    return [dict(ligne) for ligne in lignes]


class _Faux:
    """M6 de test : aucune attente à la file du propriétaire. M5 ne doit jamais être appelé par la vue."""

    def __init__(self, identifiant):
        self.id = identifiant
        self.appels = 0

    def charger_attentes(self):
        def attentes():
            self.appels += 1
            return []

        return attentes

    def charger_outils(self):
        raise AssertionError(f"{self.id} : la vue exécutive n'appelle l'outil d'aucun département")


@pytest.fixture
def m5_et_m6_de_test(monkeypatch):
    m6, m5 = _Faux("m06-material-control"), _Faux("m05-financecore")
    monkeypatch.setattr(
        m8_outils, "charger_departements", lambda: {"m06-material-control": m6, "m05-financecore": m5}
    )
    return m5, m6


def _vue(aujourd_hui=None):
    par_nom = {o.nom: o for o in m8_outils.outils()}
    arguments = {} if aujourd_hui is None else {"aujourd_hui": aujourd_hui}
    reponse = executer_atomique(par_nom["m8_lire_vue_executive"], arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


# =========================================================================================
# 1. Les manifestes : M5 publie, M8 consomme, le catalogue connaît le type
# =========================================================================================
def test_m8_declare_consommer_le_constat_de_m5_et_m5_declare_le_publier():
    tous = charger_departements(_RACINE_DEPARTEMENTS)
    m8, m5 = tous["m08-analytics"], tous["m05-financecore"]

    assert TYPE in m8.evenements_consomme and TYPE in m8.charger_consommateurs()
    assert TYPE in m5.evenements_publie and "m05-financecore" in m8.dependances
    assert TYPE in evenements.types_connus()
    assert evenements.verifier_coherence(tous) == []


def test_m8_est_le_seul_consommateur_du_constat_du_cash_libre():
    tous = charger_departements(_RACINE_DEPARTEMENTS)

    assert sorted(dep_id for dep_id, dep in tous.items() if TYPE in dep.evenements_consomme) == ["m08-analytics"]
    assert sorted(dep_id for dep_id, dep in tous.items() if TYPE in dep.evenements_publie) == ["m05-financecore"]


def test_le_registre_des_constats_est_declare_a_la_memoire_de_m8():
    manifeste = charger_departements(_RACINE_DEPARTEMENTS)["m08-analytics"]

    assert "faits_cash_libre" in manifeste.memoire_lecture and "faits_cash_libre" in manifeste.memoire_ecriture


# =========================================================================================
# 2. Le fait rangé et le résumé du reçu
# =========================================================================================
def test_le_constat_publie_est_range_tel_quel_par_m8_avec_son_type(base_durable, departements):
    charge = _charge_valide()
    _publier(charge)
    _livrer(departements)

    assert _faits() == [{"type_entree": "cash_libre_constate", **charge}]


def test_le_resume_du_recu_ne_porte_que_l_identite_du_constat_jamais_un_montant(base_durable, departements):
    charge = _charge_valide()
    _publier(charge)
    _livrer(departements)

    (recu,) = _recus()

    assert recu["statut"] == "traite" and recu["consommateur"] == "m08-analytics"
    assert recu["resultat"] == {
        "enregistre": True, "deja_enregistre": False, "evenement_id": charge["evenement_id"], "sequence": 1,
        "date_reference": "2026-09-29", "statut": "CALCULE",
    }
    brut = json.dumps(recu["resultat"], ensure_ascii=False)
    for absent in ("27861.98", "37654.33", "cash_libre_cad", MENTION, "REJ-AP-UNITE"):
        assert absent not in brut, absent


def test_aucun_renseignement_personnel_n_est_range_le_fait_a_exactement_les_cles_du_catalogue(
        base_durable, departements):
    charge = _charge_valide()
    _publier(charge)
    _livrer(departements)

    (fait,) = _faits()

    assert set(fait) == {"type_entree", *charge}
    assert set(fait) - {"type_entree"} == set(evenements.schema(TYPE)["properties"])


def test_m8_ne_publie_rien_en_recevant_un_constat(base_durable, departements):
    _publier(_charge_valide())
    _livrer(departements)

    assert [ligne["type_evenement"] for ligne in _sortants()] == [TYPE]


# =========================================================================================
# 3. Idempotence : relivraison, rejeu, double publication
# =========================================================================================
def test_une_relivraison_du_meme_constat_sous_un_autre_identifiant_de_bus_n_ajoute_aucun_fait(
        base_durable, departements):
    charge = _charge_valide()
    _publier(charge)
    _livrer(departements)
    avant = _faits()

    _publier(charge, evenement_id="autre-identifiant-de-bus-du-meme-constat")
    resume = _livrer(departements, "2026-09-29T18:05:00+00:00")

    assert resume["livres"] == 1
    assert _faits() == avant
    assert [r["resultat"]["deja_enregistre"] for r in _recus() if r["evenement_id"] != charge["evenement_id"]] == [True]
    assert _livrer(departements, "2026-09-29T18:10:00+00:00")["livres"] == 0


def test_publier_deux_fois_le_meme_evenement_est_un_no_op_et_un_rejeu_ne_livre_rien(base_durable, departements):
    charge = _charge_valide()
    _publier(charge)
    _publier(charge)

    assert len(_sortants()) == 1
    assert _livrer(departements)["livres"] == 1
    assert len(_faits()) == 1
    assert _livrer(departements, "2026-09-29T18:05:00+00:00")["livres"] == 0
    assert len(_faits()) == 1 and len(_recus()) == 1


# =========================================================================================
# 4. Un constat « non calculable » passe tel quel ; le dernier constat fait foi
# =========================================================================================
def test_un_constat_non_calculable_est_range_tel_quel_sans_aucun_zero_et_la_vue_le_dit(
        base_durable, departements, m5_et_m6_de_test):
    charge = _charge_non_calculable()
    _publier(charge)
    _livrer(departements)

    (fait,) = _faits()
    vue = _vue("2026-09-30")

    assert (fait["statut"], fait["cash_libre_cad"], fait["en_deficit"]) == ("NON_CALCULABLE", None, None)
    assert fait["au_plus_cad"] == "32061.98"
    assert fait["manque"] == [{"composante": "paies", "code": "REJ-CASH-PAIE-A-DECLARER"}]
    constat = vue["cash_libre"]["constat"]
    assert constat["statut"] == "NON_CALCULABLE" and constat["cash_libre_cad"] is None
    assert constat["composantes"]["paies"] is None and constat["composantes"]["das"] == "1350.75"
    assert vue["cash_libre"]["age"] == {"jours": 1, "aujourd_hui": "2026-09-30"}
    assert [m["raison"] for m in vue["manques"] if m["champ"] == "cash_libre"] == [
        "M5 a constaté le cash libre « non calculable » le 2026-09-29 : manque paies (REJ-CASH-PAIE-A-DECLARER)"]


def test_apres_livraison_la_vue_montre_le_montant_de_m5_tel_quel_sans_appeler_m5(
        base_durable, departements, m5_et_m6_de_test):
    m5, m6 = m5_et_m6_de_test
    _publier(_charge_valide())
    _livrer(departements)

    vue = _vue("2026-10-02")

    assert vue["cash_libre"]["statut"] == "lu"
    assert vue["cash_libre"]["constat"]["cash_libre_cad"] == "27861.98"
    assert vue["cash_libre"]["age"] == {"jours": 3, "aujourd_hui": "2026-10-02"}
    assert [m for m in vue["manques"] if m["champ"] == "cash_libre"] == []
    assert m5.appels == 0 and m6.appels == 1


def test_avant_tout_constat_la_vue_dit_manque(base_durable, m5_et_m6_de_test):
    vue = _vue("2026-10-02")

    assert vue["cash_libre"]["statut"] == "manque" and "constat" not in vue["cash_libre"]
    assert len([m for m in vue["manques"] if m["champ"] == "cash_libre"]) == 1


@pytest.mark.parametrize("ordre", list(itertools.permutations([1, 2, 3])), ids=lambda o: "-".join(map(str, o)))
def test_le_dernier_constat_est_montre_quel_que_soit_l_ordre_de_livraison(
        base_durable, departements, m5_et_m6_de_test, ordre):
    for rang in ordre:
        _publier(_charge_valide(sequence=rang, jour=f"2026-09-{20 + rang}"))
        _livrer(departements)

    section = _vue("2026-10-01")["cash_libre"]

    assert len(_faits()) == 3
    assert section["constat"]["sequence"] == 3 and section["constat"]["date_reference"] == "2026-09-23"
    assert section["n_constats_recus"] == 3 and section["age"] == {"jours": 8, "aujourd_hui": "2026-10-01"}


def test_deux_versions_du_meme_jour_sont_deux_faits_et_la_plus_recente_est_montree(
        base_durable, departements, m5_et_m6_de_test):
    _publier(_charge_valide(sequence=1, jour="2026-09-29"))
    _publier(_charge_valide(sequence=2, jour="2026-09-29", cash_libre_cad="26000.00"))
    _livrer(departements)

    section = _vue("2026-09-29")["cash_libre"]

    assert [f["cash_libre_cad"] for f in _faits()] == ["27861.98", "26000.00"]
    assert section["constat"]["cash_libre_cad"] == "26000.00" and section["age"]["jours"] == 0


def test_un_retour_a_des_donnees_anterieures_est_un_nouveau_constat_pas_un_doublon(
        base_durable, departements, m5_et_m6_de_test):
    """A, puis B, puis A' (les données de A) : trois rangs, trois faits, et le dernier est celui d'aujourd'hui."""
    version_a = hashlib.sha256(b"donnees-a").hexdigest()
    version_b = hashlib.sha256(b"donnees-b").hexdigest()
    _publier(_charge_valide(sequence=1, jour="2026-09-27", version=version_a))
    _publier(_charge_valide(sequence=2, jour="2026-09-28", version=version_b, cash_libre_cad="26000.00"))
    _publier(_charge_valide(sequence=3, jour="2026-09-29", version=version_a))
    _livrer(departements)

    section = _vue("2026-09-29")["cash_libre"]

    assert len(_faits()) == 3
    assert section["constat"]["sequence"] == 3 and section["constat"]["cash_libre_cad"] == "27861.98"


def test_un_constat_calcule_plus_recent_remplace_un_constat_non_calculable_plus_ancien(
        base_durable, departements, m5_et_m6_de_test):
    _publier(_charge_non_calculable(sequence=1, jour="2026-09-28"))
    _publier(_charge_valide(sequence=2, jour="2026-09-29"))
    _livrer(departements)

    vue = _vue("2026-09-29")

    assert vue["cash_libre"]["constat"]["statut"] == "CALCULE"
    assert [m for m in vue["manques"] if m["champ"] == "cash_libre"] == []


# =========================================================================================
# 5. Le catalogue garde la porte : ni renseignement personnel, ni « non calculable » déguisé en montant
# =========================================================================================
def _refuse(charge, message):
    with pytest.raises(evenements.ChargeInvalide) as refus:
        _publier(charge)
    assert message in str(refus.value)
    assert _sortants() == [], "un constat refusé n'écrit rien"


def test_un_champ_de_plus_est_refuse_a_la_racine_et_dans_chaque_composante(base_durable):
    _refuse(_charge(nom_employe="Personne Fictive"), "nom_employe")
    dans_solde = _charge()
    dans_solde["solde"] = {**dans_solde["solde"], "employe": "Personne Fictive"}
    _refuse(dans_solde, "employe")
    dans_source = _charge()
    dans_source["composantes"][1]["source"] = {**dans_source["composantes"][1]["source"], "beneficiaire": "X"}
    _refuse(dans_source, "beneficiaire")


@pytest.mark.parametrize("surcharges", [
    {"statut": "CALCULE", "cash_libre_cad": None},                           # « calculé » sans montant
    {"statut": "NON_CALCULABLE", "cash_libre_cad": "0.00"},                  # un zéro déguisé en montant
    {"statut": "NON_CALCULABLE", "cash_libre_cad": None, "manque": []},      # non calculable sans dire quoi
    {"statut": "PEUT-ETRE"},                                                 # un statut que M5 ne dit pas
    {"mention": "Analyse IA."},                                              # la mention obligatoire, altérée
    {"cash_libre_cad": 27861.98},                                            # un flottant, jamais du texte
    {"sequence": 0},                                                         # un rang qui n'en est pas un
])
def test_le_catalogue_refuse_un_constat_incoherent_avant_qu_il_n_atteigne_m8(base_durable, surcharges):
    with pytest.raises(evenements.ChargeInvalide):
        _publier(_charge(**surcharges))
    assert _sortants() == []
