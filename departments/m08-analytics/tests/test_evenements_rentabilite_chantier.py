"""PLAN T1.5-d : la marge réelle de M5 atteint M8 (`m5.rentabilite_chantier`).

M8 range la marge rapportée par M5 dans son registre `faits_chantier` (le fait `rentabilite` que
`mesures_chantier.py` attendait) et remesure le chantier. La métrique « marge réelle » devient calculable
quand M5 l'a chiffrée ; sinon elle reste « non calculable, manque marge_reelle_cad » et dit pourquoi, avec les
codes de M5. Les seuils ne changent pas (vides par défaut : un rappel « seuil à configurer », jamais une alerte
inventée).

Deux étages : des fonctions pures (`fait_rentabilite`, `assembler_faits`, `mesurer_chantier`) et le VRAI bus
(`opsys.evenements.repartir`, manifestes réels, M8 seul abonné, base SQLite temporaire migrée). Les charges de M5
sont synthétiques et fictives, validées par le catalogue du socle à la publication.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
import yaml
from m8_analytics import mesures_chantier as mc
from m8_analytics import outils as m8_outils
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
_MAINTENANT = "2026-09-28T18:00:00+00:00"
_DEFINITIONS = mc.charger_definitions()
_METRIQUES_DE_MARGE = ("m8_marge_reelle_cad", "m8_ecart_marge_cad", "m8_ecart_marge_pct")


# ---------------------------------------------------------------------------
# Pièces : événements de M5, de M4 et de M3 (fictifs, conformes au catalogue)
# ---------------------------------------------------------------------------
def _m5(sequence=1, verdict="CALCULEE", wct_id="wct-m8-1", **surcharges):
    """Charge `m5.rentabilite_chantier` : CALCULEE (marge 114.00 contre 120.00 prévus) ou PARTIELLE (aucune marge)."""
    complete = verdict == "CALCULEE"
    base = {
        "evenement_id": f"m5-rentabilite-devis-m8-1-{sequence}-{sequence:016x}", "devis_id": "devis-m8-1",
        "chantier_id": "ch-1", "wct_id": wct_id, "sequence": sequence, "version_entrees": f"{sequence:064x}",
        "horodatage_completion": "2026-09-28T14:00:00-04:00", "verdict": verdict, "devise": "CAD",
        "cout_reel_complet": complete, "cout_reel_cad": "486.00" if complete else None,
        "cout_connu_cad": "486.00" if complete else "150.00",
        "marge_reelle_cad": "114.00" if complete else None, "marge_prevue_cad": "120.00",
        "ecart_marge_cad": "-6.00" if complete else None,
        "manque": [] if complete else ["REJ-COUT-PRIX-NON-DISPONIBLE", "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER"],
    }
    base.update(surcharges)
    return base


def _wct(**surcharges):
    base = {
        "wct_id": "wct-m8-1", "intervention_id": "int-1", "lead_id": "lead-1", "technicien_id": "tech-fictif-a",
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
        "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None, "hash_maillon": "deadbeef",
        "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"], "devis_id": "devis-m8-1",
        "statut": "completed_verified",
    }
    base.update(surcharges)
    return base


def _devis(**surcharges):
    base = {
        "devis_id": "devis-m8-1", "lead_id": "lead-1", "chantier_id": None,
        "lignes": [{
            "reference_ligne": "devis-m8-1-L0", "description": "Gouttières 5po (fictif)", "quantite": "40",
            "unite": "pi", "prix_unitaire": "15.00", "prix_ligne": "600.00", "reference_besoin_materiau": None,
        }],
        "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25",
        "duree_estimee_minutes": "60", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
    }
    base.update(surcharges)
    return base


PRODUCTEURS = {"m5": "m05-financecore", "wct": "m04-field-ops", "devis": "m03-estimation"}
TYPES = {"m5": "m5.rentabilite_chantier", "wct": "m4.travaux_termines", "devis": "m3.devis_accepte"}


def _publier(piece, charge=None, evenement_id=None):
    fabrique = {"m5": _m5, "wct": _wct, "devis": _devis}[piece]
    charge = fabrique() if charge is None else charge
    if piece == "m5" and evenement_id is None:
        evenement_id = charge["evenement_id"]
    evenements.publier(TYPES[piece], PRODUCTEURS[piece], charge, evenement_id=evenement_id)


# ---------------------------------------------------------------------------
# Étage 1 : fonctions pures
# ---------------------------------------------------------------------------
def test_le_fait_rentabilite_garde_la_marge_de_m5_telle_quelle_et_ses_codes():
    fait = mc.fait_rentabilite(_m5())

    assert fait == {
        "type_entree": "rentabilite", "wct_id": "wct-m8-1", "devis_id": "devis-m8-1", "sequence": 1,
        "verdict": "CALCULEE", "marge_reelle_cad": "114.00", "manque": [],
    }


def test_le_fait_rentabilite_d_un_cout_partiel_n_a_aucune_marge_et_garde_les_codes_de_m5():
    fait = mc.fait_rentabilite(_m5(verdict="PARTIELLE"))

    assert fait["marge_reelle_cad"] is None and fait["verdict"] == "PARTIELLE"
    assert fait["manque"] == ["REJ-COUT-PRIX-NON-DISPONIBLE", "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER"]


def test_meme_une_charge_fautive_ne_donne_pas_de_marge_a_un_cout_partiel():
    """Défense en profondeur : le catalogue refuse déjà cette charge ; M8 ne la croirait pas non plus."""
    fautive = _m5(verdict="PARTIELLE", marge_reelle_cad="999.00")
    assert mc.fait_rentabilite(fautive)["marge_reelle_cad"] is None

    incoherente = _m5(cout_reel_complet=False, marge_reelle_cad="999.00")  # « CALCULEE » sans coût complet
    assert mc.fait_rentabilite(incoherente)["marge_reelle_cad"] is None


def _faits_de(*rentabilites):
    return mc.assembler_faits("wct-m8-1", [
        {"type_entree": "wct", "wct_id": "wct-m8-1", "devis_id": "devis-m8-1", "technicien_id": "t",
         "horodatage_completion": "2026-09-28T14:00:00-04:00", "duree_reelle_minutes": 120,
         "intervention_id": "int-1", "statut": "completed_verified"},
        *[mc.fait_rentabilite(charge) for charge in rentabilites],
    ])


def test_le_plus_grand_sequence_est_l_etat_courant_quel_que_soit_l_ordre_de_reception():
    partiel, complet = _m5(sequence=1, verdict="PARTIELLE"), _m5(sequence=2)

    assert _faits_de(partiel, complet)["rentabilite"]["sequence"] == 2
    assert _faits_de(complet, partiel)["rentabilite"]["sequence"] == 2  # une trace ancienne livrée en retard
    assert _faits_de(complet, partiel)["rentabilite"]["marge_reelle_cad"] == "114.00"


def test_un_fait_sans_sequence_est_remplace_par_le_suivant_comme_avant():
    ancien = {"type_entree": "rentabilite", "wct_id": "wct-m8-1", "marge_reelle_cad": "90.00"}
    plus_recent = {"type_entree": "rentabilite", "wct_id": "wct-m8-1", "marge_reelle_cad": "80.00"}

    faits = mc.assembler_faits("wct-m8-1", [
        {"type_entree": "wct", "wct_id": "wct-m8-1", "devis_id": None}, ancien, plus_recent])

    assert faits["rentabilite"]["marge_reelle_cad"] == "80.00"


def test_la_rentabilite_d_un_autre_chantier_n_est_pas_jointe():
    faits = _faits_de(_m5(wct_id="wct-autre"))
    assert faits["rentabilite"] is None


def _mesures(*rentabilites):
    faits = _faits_de(*rentabilites)
    faits["devis"] = {"type_entree": "devis", "devis_id": "devis-m8-1", "prix_total": "600.00",
                      "cout_total": "480.00", "duree_estimee_minutes": "60"}
    return {m["metric_id"]: m for m in mc.mesurer_chantier(faits, _DEFINITIONS)}


def test_une_marge_chiffree_par_m5_rend_les_trois_mesures_de_marge_calculables():
    mesures = _mesures(_m5())

    assert mesures["m8_marge_reelle_cad"]["valeur"] == "114.00"
    assert mesures["m8_marge_prevue_cad"]["valeur"] == "120.00"
    assert mesures["m8_ecart_marge_cad"]["valeur"] == "-6.00"  # 114 - 120, négatif : marge plus faible que prévu
    assert mesures["m8_ecart_marge_pct"]["valeur"] == "-5.00"  # -6 / 120
    assert {mesures[m]["statut"] for m in _METRIQUES_DE_MARGE} == {"calculee"}


def test_un_cout_partiel_laisse_les_trois_mesures_de_marge_non_calculables_avec_la_raison_de_m5():
    mesures = _mesures(_m5(verdict="PARTIELLE"))

    for metric_id in _METRIQUES_DE_MARGE:
        mesure = mesures[metric_id]
        assert mesure["statut"] == "non_calculable" and mesure["valeur"] is None, metric_id
        assert [m["champ"] for m in mesure["manque"]] == ["marge_reelle_cad"]
        assert mesure["manque"][0]["source"] == "M5 (rentabilité du chantier)"
        assert mesure["manque"][0]["raison"] == (
            "M5 n'a pas chiffré la marge réelle : REJ-COUT-PRIX-NON-DISPONIBLE, REJ-COUT-TAUX-HORAIRE-A-CONFIGURER")
        assert mesure["detail"].startswith("non calculable, manque marge_reelle_cad")
    assert mesures["m8_marge_prevue_cad"]["valeur"] == "120.00"  # ce qui ne dépend pas de M5 reste calculé


def test_sans_fait_de_m5_la_raison_reste_celle_d_avant():
    faits = _faits_de()
    faits["devis"] = None
    mesure = next(m for m in mc.mesurer_chantier(faits, _DEFINITIONS) if m["metric_id"] == "m8_marge_reelle_cad")

    assert mesure["manque"][0]["raison"] == "aucun fait reçu de cette source pour ce chantier"


# ---------------------------------------------------------------------------
# Étage 2 : le vrai bus
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


@pytest.fixture
def configurer(tmp_path, monkeypatch):
    def poser(seuils_alerte):
        manifeste = tmp_path / "department.yaml"
        manifeste.write_text(yaml.safe_dump({"configuration": {"seuils_alerte": seuils_alerte}}), encoding="utf-8")
        monkeypatch.setattr(m8_outils, "_MANIFESTE", manifeste)
    return poser


def _livrer(departements, maintenant=_MAINTENANT):
    resume = evenements.repartir(departements, maintenant=maintenant)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    return resume


def _faits():
    return list(stockage.maillons("m08-analytics", "faits_chantier"))


def _alertes():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m8.alerte_proposee")
            .order_by(EVENEMENTS_SORTANTS.c.cree_le)
        ).mappings().all()
    return [codec.decoder(ligne["charge"]) for ligne in lignes]


def _lire(wct_id="wct-m8-1"):
    par_nom = {o.nom: o for o in m8_outils.outils()}
    reponse = executer_atomique(par_nom["m8_lire_mesures_chantier"], {"wct_id": wct_id})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _par_metrique(resultat):
    return {m["metric_id"]: m for m in resultat["mesures"]}


def test_m8_declare_consommer_la_rentabilite_de_m5():
    dep = charger_departements(_RACINE_DEPARTEMENTS)["m08-analytics"]
    assert "m5.rentabilite_chantier" in dep.evenements_consomme
    assert "m5.rentabilite_chantier" in dep.charger_consommateurs()
    assert "m05-financecore" in dep.dependances


@pytest.mark.parametrize("ordre", list(itertools.permutations(["m5", "wct", "devis"])),
                         ids=lambda ordre: "-".join(ordre))
def test_la_marge_reelle_est_calculee_quel_que_soit_l_ordre_d_arrivee(base_durable, departements, ordre):
    for piece in ordre:
        _publier(piece)
        _livrer(departements)

    resultat = _lire()
    mesures = _par_metrique(resultat)
    assert mesures["m8_marge_reelle_cad"]["valeur"] == "114.00"
    assert mesures["m8_marge_prevue_cad"]["valeur"] == "120.00"
    assert mesures["m8_ecart_marge_cad"]["valeur"] == "-6.00"
    assert mesures["m8_ecart_marge_pct"]["valeur"] == "-5.00"
    assert mesures["m8_ecart_duree_minutes"]["valeur"] == "60.00"  # 120 réelles - 60 estimées : le temps prévu aussi
    assert "marge_reelle_cad" not in [m["champ"] for m in resultat["manques"]]
    assert {mesures[m]["statut"] for m in _METRIQUES_DE_MARGE} == {"calculee"}


def test_le_fait_ecrit_est_celui_que_mesures_chantier_attendait(base_durable, departements):
    _publier("wct")
    _publier("m5")
    _livrer(departements)

    (fait,) = [f for f in _faits() if f["type_entree"] == "rentabilite"]
    # Les trois clés que `mesures_chantier.py` lit : type_entree, wct_id, marge_reelle_cad.
    assert fait["wct_id"] == "wct-m8-1" and fait["marge_reelle_cad"] == "114.00"
    assert set(fait) == {"type_entree", "wct_id", "devis_id", "sequence", "verdict", "marge_reelle_cad", "manque"}
    assert "cout_reel_cad" not in fait and "cout_connu_cad" not in fait  # M8 ne garde pas les coûts de M5


def test_un_cout_partiel_de_m5_laisse_la_marge_non_calculable_et_dit_ce_qui_manque(base_durable, departements):
    _publier("wct")
    _publier("devis")
    _publier("m5", _m5(verdict="PARTIELLE"))
    _livrer(departements)

    resultat = _lire()
    mesures = _par_metrique(resultat)
    for metric_id in _METRIQUES_DE_MARGE:
        assert mesures[metric_id]["statut"] == "non_calculable", metric_id
        assert mesures[metric_id]["manque"] == ["marge_reelle_cad"]
        assert mesures[metric_id]["valeur"] is None  # jamais un zéro, jamais la marge prévue
    raisons = [m["raison"] for m in resultat["manques"] if m["champ"] == "marge_reelle_cad"]
    assert raisons == [
        "M5 n'a pas chiffré la marge réelle : REJ-COUT-PRIX-NON-DISPONIBLE, REJ-COUT-TAUX-HORAIRE-A-CONFIGURER"]
    assert mesures["m8_marge_prevue_cad"]["valeur"] == "120.00"
    assert [a for a in _alertes() if a["metric_id"] in _METRIQUES_DE_MARGE] == []  # non calculée : pas même un rappel


def test_le_partiel_puis_le_complet_rend_la_marge_calculable(base_durable, departements):
    _publier("wct")
    _publier("devis")
    _publier("m5", _m5(sequence=1, verdict="PARTIELLE"))
    _livrer(departements)
    assert _par_metrique(_lire())["m8_marge_reelle_cad"]["statut"] == "non_calculable"

    _publier("m5", _m5(sequence=2))  # M5 a maintenant son prix et son taux
    _livrer(departements, "2026-09-28T18:05:00+00:00")

    assert _par_metrique(_lire())["m8_marge_reelle_cad"]["valeur"] == "114.00"
    assert [(f["sequence"], f["marge_reelle_cad"]) for f in _faits() if f["type_entree"] == "rentabilite"] == [
        (1, None), (2, "114.00")]


def test_le_complet_puis_un_partiel_plus_recent_repasse_la_marge_a_non_calculable(base_durable, departements):
    """Le dernier état de M5 fait foi : si le taux horaire disparaît, la marge d'hier n'est plus dite."""
    _publier("wct")
    _publier("devis")
    _publier("m5", _m5(sequence=1))
    _livrer(departements)
    assert _par_metrique(_lire())["m8_marge_reelle_cad"]["valeur"] == "114.00"

    _publier("m5", _m5(sequence=2, verdict="PARTIELLE"))
    _livrer(departements, "2026-09-28T18:05:00+00:00")

    assert _par_metrique(_lire())["m8_marge_reelle_cad"]["statut"] == "non_calculable"


def test_une_trace_ancienne_livree_apres_une_plus_recente_ne_l_ecrase_pas(base_durable, departements):
    _publier("wct")
    _publier("devis")
    _publier("m5", _m5(sequence=2))
    _livrer(departements)
    _publier("m5", _m5(sequence=1, verdict="PARTIELLE"))  # livrée en retard (réessai)
    _livrer(departements, "2026-09-28T18:05:00+00:00")

    assert _par_metrique(_lire())["m8_marge_reelle_cad"]["valeur"] == "114.00"


def test_une_relivraison_n_ajoute_aucun_fait(base_durable, departements):
    _publier("wct")
    _publier("devis")
    _publier("m5")
    _livrer(departements)
    avant = _faits()

    _publier("m5", _m5(), evenement_id="autre-identifiant-du-meme-etat")  # même wct et même sequence
    resume = _livrer(departements, "2026-09-28T18:05:00+00:00")

    assert resume["echecs"] == 0
    assert _faits() == avant
    assert _livrer(departements, "2026-09-28T18:10:00+00:00")["livres"] == 0


def test_la_rentabilite_recue_avant_son_wct_est_gardee_puis_reprise_a_son_arrivee(base_durable, departements):
    _publier("m5")
    _livrer(departements)
    assert [f["type_entree"] for f in _faits()] == ["rentabilite"]  # rien n'est perdu ni inventé
    assert _lire()["trouve"] is False

    _publier("wct")
    _publier("devis")
    _livrer(departements, "2026-09-28T18:05:00+00:00")

    assert _par_metrique(_lire())["m8_marge_reelle_cad"]["valeur"] == "114.00"


def test_la_rentabilite_d_un_chantier_n_atteint_pas_celle_d_un_autre(base_durable, departements):
    _publier("wct")
    _publier("wct", _wct(wct_id="wct-m8-2", intervention_id="int-2"))
    _publier("devis")
    _publier("m5", _m5(wct_id="wct-m8-2", marge_reelle_cad="80.00", ecart_marge_cad="-40.00"))
    _livrer(departements)

    assert _par_metrique(_lire("wct-m8-2"))["m8_marge_reelle_cad"]["valeur"] == "80.00"
    assert _par_metrique(_lire("wct-m8-1"))["m8_marge_reelle_cad"]["statut"] == "non_calculable"


def test_un_seuil_de_marge_franchi_publie_une_alerte_avec_sa_preuve_chiffree(base_durable, departements, configurer):
    configurer({"m8_ecart_marge_pct": {"sens": "au_dessous", "valeur": -3}})
    _publier("wct")
    _publier("devis")
    _publier("m5")  # écart de -5.00 % : sous le seuil de -3 %
    _livrer(departements)

    franchis = [a for a in _alertes() if a["type_alerte"] == "MESURE-SEUIL-FRANCHI"]
    assert [a["metric_id"] for a in franchis] == ["m8_ecart_marge_pct"]
    alerte = franchis[0]
    assert alerte["a_qui"] == "m05-financecore"
    assert (alerte["preuve"]["valeur"], alerte["preuve"]["seuil"], alerte["preuve"]["sens"]) == (
        "-5.00", "-3.00", "au_dessous")
    assert alerte["preuve"]["wct_id"] == "wct-m8-1"


def test_un_cout_partiel_ne_declenche_aucune_alerte_de_marge_meme_avec_un_seuil(base_durable, departements, configurer):
    configurer({"m8_ecart_marge_pct": {"sens": "au_dessous", "valeur": -3}})
    _publier("wct")
    _publier("devis")
    _publier("m5", _m5(verdict="PARTIELLE"))
    _livrer(departements)

    assert [a for a in _alertes() if a["metric_id"] == "m8_ecart_marge_pct"] == []  # non calculée : pas évaluée


def test_sans_seuil_configure_la_marge_calculee_donne_un_rappel_pas_une_alerte(base_durable, departements):
    """Seuils inchangés : `department.yaml` de M8 n'en fixe aucun."""
    assert m8_outils._seuils_alerte() == {}
    _publier("wct")
    _publier("devis")
    _publier("m5")
    _livrer(departements)

    alertes = [a for a in _alertes() if a["metric_id"] == "m8_ecart_marge_pct"]
    assert [a["type_alerte"] for a in alertes] == ["MESURE-SEUIL-A-CONFIGURER"]
    assert alertes[0]["preuve"] == {"metric_id": "m8_ecart_marge_pct", "manque": "seuil"}
    assert "m8_ecart_marge_pct" in _lire()["seuils_a_configurer"]


def test_les_catalogues_refusent_a_la_publication_une_rentabilite_avec_marge_sur_cout_partiel(base_durable):
    with pytest.raises(evenements.ChargeInvalide):
        evenements.publier("m5.rentabilite_chantier", "m05-financecore",
                           _m5(verdict="PARTIELLE", marge_reelle_cad="1.00"))
