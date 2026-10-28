"""PLAN T1.5-d : M5 publie `m5.rentabilite_chantier` quand sa trace `rentabilite` change (la marge réelle
atteint M8 et M10).

Deux étages :

1. `cout_reel.charge_evenement` (module pur) : la liste blanche des champs, sans prix unitaire, taux, ligne de
   matériau ni donnée de client ; un coût partiel ne porte JAMAIS de marge ; le schéma FERMÉ du catalogue le
   refuse aussi (défense en profondeur : même un producteur fautif ne peut pas publier une marge sur un coût
   partiel).
2. `_essayer_cout_reel` par le VRAI bus, sur une base SQLite temporaire migrée : un événement par trace, dans la
   même transaction, jamais pour un rejeu ; un retour à une version antérieure des entrées publie un
   événement DISTINCT (sinon les consommateurs resteraient sur l'état précédent).

Identifiants et montants fictifs (DEFINITION-PRODUIT §1).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as outils_mod
import pytest
import yaml
from m5_financecore import cout_reel
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.evenements.schemas import erreurs_charge
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
_DEPARTEMENT = "m05-financecore"
_M6 = "m06-material-control"
TYPE = "m5.rentabilite_chantier"
MATERIAU = "gouttiere-alu-5po-fictif"
FOURNISSEUR = "gentek-fictif"
COMPLETION = "2026-09-25T16:30:00-04:00"

_CLES = {
    "evenement_id", "devis_id", "chantier_id", "wct_id", "sequence", "version_entrees", "horodatage_completion",
    "verdict", "devise", "cout_reel_complet", "cout_reel_cad", "cout_connu_cad", "marge_reelle_cad",
    "marge_prevue_cad", "ecart_marge_cad", "manque", "prix_definitif",
}


# =========================================================================================
# 1. La charge : liste blanche, pure
# =========================================================================================
def _wct(**surcharges):
    base = {"wct_id": "WCT-1", "intervention_id": "INT-1", "devis_id": "DEVIS-1",
            "horodatage_completion": COMPLETION, "duree_reelle_minutes": 180}
    return {**base, **surcharges}


def _signal(reelle="42.0", statut="evaluee"):
    lignes = [{"materiau": MATERIAU, "unite": "pi", "quantite_prevue": "40.0", "quantite_reelle": reelle,
               "ecart_pourcentage": "0.05", "critique": False}] if statut == "evaluee" else None
    return {"wct_id": "WCT-1", "chantier_id": "CH-1", "statut_variance": statut, "signal_critique": False,
            "horodatage_completion": COMPLETION, "lignes": lignes}


def _prix(prix=8.0):
    return {"materiau_id": MATERIAU, "fournisseur_id": FOURNISSEUR, "prix_unitaire": prix, "devise": "CAD",
            "date_effet": "2026-09-01", "source_document": None, "unite": "pi"}


def _facture(montant="600.00", statut="BROUILLON"):
    return {"facture_id": "fac-DEVIS-1", "statut": statut, "montant_avant_taxes": Decimal(montant)}


def _devis(**surcharges):
    base = {"devis_id": "DEVIS-1", "chantier_id": "CH-1", "cout_total": "480.00", "prix_total": "600.00",
            "taux_marge": "0.25"}
    return {**base, **surcharges}


def _rentabilite(signal="defaut", livre="defaut", taux="50.00", facture="defaut", devis="defaut"):
    cout = cout_reel.calculer_cout_reel(
        _wct(), _signal() if signal == "defaut" else signal, [_prix()] if livre == "defaut" else livre, taux)
    return cout_reel.calculer_rentabilite(
        cout, _facture() if facture == "defaut" else facture, _devis() if devis == "defaut" else devis,
        devis_id="DEVIS-1", chantier_id="CH-1")


def _charge(rentabilite=None, sequence=1):
    return cout_reel.charge_evenement(_rentabilite() if rentabilite is None else rentabilite, sequence, COMPLETION)


def test_la_marge_calculee_sort_en_texte_decimal_avec_tout_ce_qui_l_explique():
    r = _rentabilite()
    charge = _charge(r, sequence=1)

    assert set(charge) == _CLES
    assert charge == {
        "evenement_id": f"m5-rentabilite-DEVIS-1-1-{r['version_entrees'][:16]}",
        "devis_id": "DEVIS-1", "chantier_id": "CH-1", "wct_id": "WCT-1", "sequence": 1,
        "version_entrees": r["version_entrees"], "horodatage_completion": COMPLETION,
        "verdict": "CALCULEE", "devise": "CAD", "prix_definitif": False,
        "cout_reel_complet": True, "cout_reel_cad": "486.00", "cout_connu_cad": "486.00",  # 42 x 8,00 + 3 h x 50,00 $
        "marge_reelle_cad": "114.00", "marge_prevue_cad": "120.00", "ecart_marge_cad": "-6.00", "manque": [],
    }
    assert erreurs_charge(TYPE, charge) == []
    assert not [v for v in charge.values() if isinstance(v, float)]  # jamais un nombre JSON pour un montant


def test_finalite_est_emise_selon_le_statut_et_absence_de_facture():
    charges = []
    for statut, attendu in (("BROUILLON", False), ("ENVOYEE", True), ("PAYEE", True)):
        charge = _charge(_rentabilite(facture=_facture(statut=statut)))
        assert charge["prix_definitif"] is attendu
        assert erreurs_charge(TYPE, charge) == []
        charges.append(charge)

    assert len({charge["version_entrees"] for charge in charges}) == 3  # le statut continue de versionner les entrées

    sans_facture = _charge(_rentabilite(facture=None))
    assert sans_facture["prix_definitif"] is False
    assert sans_facture["marge_reelle_cad"] is None


def test_un_cout_partiel_ne_porte_jamais_de_marge_seulement_ce_qui_manque():
    """Ni prix au livre, ni taux : rien n'est chiffré. Le plancher `cout_connu_cad` n'est pas un total."""
    r = _rentabilite(livre=[], taux=None)
    assert r["verdict"] == "PARTIELLE" and r["marge_partielle_plafond"] is not None  # M5 en garde un plafond...
    charge = _charge(r)

    assert charge["verdict"] == "PARTIELLE" and charge["cout_reel_complet"] is False
    assert charge["cout_reel_cad"] is None  # jamais une somme partielle prise pour un total
    assert charge["cout_connu_cad"] == "0"
    assert charge["marge_reelle_cad"] is None and charge["ecart_marge_cad"] is None
    assert "plafond" not in json.dumps(charge)  # ... qui ne sort JAMAIS de M5
    assert charge["marge_prevue_cad"] == "120.00"  # la marge prévue est celle de M3, elle reste dite
    assert charge["manque"] == ["REJ-COUT-PRIX-NON-DISPONIBLE", "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER"]
    assert erreurs_charge(TYPE, charge) == []


def test_un_cout_partiel_avec_un_seul_manque_donne_le_plancher_pas_le_total():
    r = _rentabilite(signal=_signal(statut="declaration_absente"))  # matériaux réels inconnus, main-d'oeuvre connue
    charge = _charge(r)

    assert charge["manque"] == ["REJ-COUT-MATERIAUX-REELS-ABSENTS"]
    assert charge["cout_connu_cad"] == "150.00" and charge["cout_reel_cad"] is None
    assert charge["marge_reelle_cad"] is None and charge["ecart_marge_cad"] is None
    assert erreurs_charge(TYPE, charge) == []


def test_un_cout_complet_sans_facture_reste_partiel_et_sans_marge():
    r = _rentabilite(facture=None)
    charge = _charge(r)

    assert charge["cout_reel_complet"] is True and charge["cout_reel_cad"] == "486.00"
    assert charge["verdict"] == "PARTIELLE"  # pas de prix facturé : pas de marge
    assert charge["marge_reelle_cad"] is None and charge["ecart_marge_cad"] is None
    assert charge["manque"] == ["REJ-RENTABILITE-FACTURE-ABSENTE"]
    assert erreurs_charge(TYPE, charge) == []


def test_un_devis_sans_cout_prevu_donne_la_marge_reelle_sans_ecart():
    r = _rentabilite(devis={"devis_id": "DEVIS-1", "chantier_id": "CH-1", "prix_total": "600.00"})
    charge = _charge(r)

    assert charge["verdict"] == "CALCULEE" and charge["marge_reelle_cad"] == "114.00"
    assert charge["marge_prevue_cad"] is None and charge["ecart_marge_cad"] is None
    assert charge["manque"] == ["REJ-RENTABILITE-MARGE-PREVUE-ABSENTE"]
    assert erreurs_charge(TYPE, charge) == []


def test_un_chantier_en_perte_porte_une_marge_negative_et_un_zero_sans_signe():
    perte = _charge(_rentabilite(facture=_facture("400.00")))  # 400,00 - 486,00
    assert perte["marge_reelle_cad"] == "-86.00" and perte["ecart_marge_cad"] == "-206.00"
    assert erreurs_charge(TYPE, perte) == []

    nulle = _charge(_rentabilite(facture=_facture("486.00")))
    assert nulle["marge_reelle_cad"] == "0.00" and nulle["ecart_marge_cad"] == "-120.00"  # jamais « -0.00 »


def test_la_charge_ne_contient_ni_prix_unitaire_ni_taux_ni_ligne_ni_donnee_de_client():
    for r in (_rentabilite(), _rentabilite(livre=[], taux=None)):
        charge = _charge(r)
        texte = json.dumps(charge)
        assert set(charge) == _CLES
        for interdit in (MATERIAU, FOURNISSEUR, "8.0", "prix_unitaire", "taux", "quantite", "lignes", "lead", "client",
                         "facture", "nom", "courriel", "telephone", "50.00"):
            assert interdit not in texte, interdit
        assert all(not isinstance(v, (dict,)) for v in charge.values())  # aucune structure imbriquée à fuiter


def test_meme_si_la_rentabilite_est_incoherente_un_cout_partiel_ne_sort_pas_de_marge():
    """Défense en profondeur : `rentabilite` porterait par erreur une marge malgré un coût partiel."""
    r = _rentabilite(livre=[], taux=None)
    r["marge_reelle"], r["ecart_marge"] = Decimal("99.00"), Decimal("-21.00")

    charge = _charge(r)

    assert charge["verdict"] == "PARTIELLE"
    assert charge["marge_reelle_cad"] is None and charge["ecart_marge_cad"] is None
    assert erreurs_charge(TYPE, charge) == []


def test_l_identifiant_est_deterministe_et_change_avec_le_rang_de_la_trace():
    r = _rentabilite()
    assert _charge(r, 1)["evenement_id"] == _charge(r, 1)["evenement_id"]
    assert _charge(r, 1)["evenement_id"] != _charge(r, 2)["evenement_id"]


# -- Le schéma fermé du catalogue refuse ce que le producteur ne doit jamais dire -----------
def test_le_catalogue_refuse_une_marge_sur_un_cout_partiel():
    partiel = _charge(_rentabilite(livre=[], taux=None))
    assert erreurs_charge(TYPE, partiel) == []

    for champ, valeur in (("marge_reelle_cad", "1.00"), ("ecart_marge_cad", "1.00"), ("cout_reel_cad", "100.00")):
        assert erreurs_charge(TYPE, {**partiel, champ: valeur}), champ
    assert erreurs_charge(TYPE, {**partiel, "verdict": "CALCULEE"}), "PARTIELLE ne peut pas devenir CALCULEE sans marge"
    assert erreurs_charge(TYPE, {**partiel, "cout_reel_complet": True}), "un coût complet porte son total"


def test_le_catalogue_refuse_une_calculee_sans_marge_et_un_ecart_sans_ses_deux_marges():
    complete = _charge()
    assert erreurs_charge(TYPE, complete) == []

    assert erreurs_charge(TYPE, {**complete, "marge_reelle_cad": None})
    assert erreurs_charge(TYPE, {**complete, "cout_reel_cad": None})
    assert erreurs_charge(TYPE, {**complete, "cout_reel_complet": False})
    assert erreurs_charge(TYPE, {**complete, "marge_prevue_cad": None})  # un écart sans marge prévue


def test_finalite_est_facultative_pour_historique_et_strictement_booleenne():
    actuelle = _charge()
    historique = {cle: valeur for cle, valeur in actuelle.items() if cle != "prix_definitif"}
    assert erreurs_charge(TYPE, historique) == []  # ancien payload: inconnu, jamais vrai par défaut
    assert erreurs_charge(TYPE, {**actuelle, "prix_definitif": "false"})
    assert erreurs_charge(TYPE, {**actuelle, "prix_definitif": 0})
    assert erreurs_charge(TYPE, {**actuelle, "prix_definitif": None})


def test_le_catalogue_est_ferme_et_refuse_un_champ_de_plus_ou_de_moins_ou_un_montant_json():
    complete = _charge()

    assert erreurs_charge(TYPE, {**complete, "prix_unitaire": "8.00"})
    assert erreurs_charge(TYPE, {**complete, "taux_horaire": "50.00"})
    assert erreurs_charge(TYPE, {**complete, "lead_id": "LEAD-1"})
    for champ in _CLES - {"prix_definitif"}:
        sans = {cle: valeur for cle, valeur in complete.items() if cle != champ}
        assert erreurs_charge(TYPE, sans), champ
    assert erreurs_charge(TYPE, {**complete, "marge_reelle_cad": 114.0})  # un nombre JSON n'est pas un texte décimal
    assert erreurs_charge(TYPE, {**complete, "devise": "USD"})
    assert erreurs_charge(TYPE, {**complete, "sequence": 0})
    assert erreurs_charge(TYPE, {**complete, "manque": ["taux horaire à configurer"]})  # un code, pas une phrase
    assert erreurs_charge(TYPE, {**complete, "manque": ["REJ-COUT-PRIX-AMBIGU", "REJ-COUT-PRIX-AMBIGU"]})


# =========================================================================================
# 2. La publication par le vrai bus
# =========================================================================================
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m5-rentabilite.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils_mod.utiliser_stockage_durable()
    yield url
    stockage.liberer()


@pytest.fixture
def taux_configure(tmp_path, monkeypatch):
    """Un manifeste de test qui porte le taux horaire (50,00 $/h, fictif) : le manifeste livré n'en porte pas."""
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {"taux_horaire_main_d_oeuvre": "50.00"}}), encoding="utf-8")
    monkeypatch.setattr(outils_mod, "_MANIFESTE", manifeste)
    return manifeste


def _deps_bus():
    return {_DEPARTEMENT: charger_departements()[_DEPARTEMENT]}


def _devis_accepte(devis_id="DEVIS-1"):
    return {
        "devis_id": devis_id, "lead_id": "LEAD-1-fictif", "chantier_id": "CHANTIER-1",
        "lignes": [
            {"reference_ligne": f"{devis_id}-L0", "description": "Gouttières 5po aluminium", "quantite": "40",
             "unite": "pi", "prix_unitaire": "10.00", "prix_ligne": "400.00", "reference_besoin_materiau": MATERIAU},
            {"reference_ligne": f"{devis_id}-L1", "description": "Main d'oeuvre installation", "quantite": "1",
             "unite": "forfait", "prix_unitaire": "200.00", "prix_ligne": "200.00", "reference_besoin_materiau": None},
        ],
        "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25",
        "horodatage_acceptation": "2026-09-20T10:00:00-04:00",
    }


def _wct_bus(wct_id="WCT-1", devis_id="DEVIS-1"):
    return {
        "wct_id": wct_id, "intervention_id": f"INT-{wct_id}", "lead_id": "LEAD-1-fictif", "technicien_id": "TECH-1",
        "horodatage_completion": COMPLETION, "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 180, "ecart_signale": False, "revue_id": None, "hash_maillon": f"hash-{wct_id}",
        "consommateurs_cibles": ["M5"], "devis_id": devis_id, "statut": "completed_verified",
    }


def _variance_bus(wct_id="WCT-1", reelle="42.0"):
    return {
        "evenement_id": f"m6-variance-{wct_id}-evaluee", "wct_id": wct_id, "intervention_id": f"INT-{wct_id}",
        "chantier_id": "CHANTIER-1", "statut_variance": "evaluee", "signal_critique": False,
        "seuil_pourcentage": 0.3, "horodatage_completion": COMPLETION,
        "lignes": [{"materiau": MATERIAU, "unite": "pi", "quantite_prevue": "40.0", "quantite_reelle": reelle,
                    "ecart_pourcentage": "0.05", "critique": False}],
    }


def _cascade():
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct_bus())
    charge = _variance_bus()
    evenements.publier("m6.variance_chantier", _M6, charge, evenement_id=charge["evenement_id"])
    _livrer()


def _livrer(instant="2026-09-25T17:00:00-04:00"):
    resume = evenements.repartir(_deps_bus(), maintenant=instant)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    return resume


def _prix_au_livre_m6(prix=8.0):
    with stockage.transaction():
        stockage.maillons(_M6, "livre_prix").append({
            "materiau_id": MATERIAU, "fournisseur_id": FOURNISSEUR, "prix_unitaire": prix, "devise": "CAD",
            "date_effet": "2026-09-01", "source_document": None, "unite": "pi"})


def _traces(devis_id="DEVIS-1"):
    with stockage.transaction():
        return [m for m in stockage.maillons(_DEPARTEMENT, "rentabilite") if m["devis_id"] == devis_id]


def _publies():
    """Les charges `m5.rentabilite_chantier` publiées, dans l'ordre des traces (par `sequence`)."""
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.producteur,
                                    EVENEMENTS_SORTANTS.c.charge)
                             .where(EVENEMENTS_SORTANTS.c.type_evenement == TYPE)).all()
    publies = [(ligne.evenement_id, ligne.producteur, codec.decoder(ligne.charge)) for ligne in lignes]
    return sorted(publies, key=lambda paire: paire[2]["sequence"])


def _essayer(devis_id="DEVIS-1"):
    with stockage.transaction():
        return outils_mod._essayer_cout_reel(devis_id)


def test_m5_declare_publier_la_rentabilite():
    publie = charger_departements()[_DEPARTEMENT].evenements_publie
    assert publie == (TYPE, "m5.cash_libre_constate"), "la marge (T1.5-d), puis le cash libre constaté (T4.19-b)"


def test_une_trace_calculee_publie_la_marge_reelle_dans_la_meme_transaction(base_durable, taux_configure):
    _prix_au_livre_m6()
    _cascade()

    traces = _traces()
    publies = _publies()
    assert len(publies) == len(traces) >= 1, "un événement par trace, ni plus ni moins"
    derniere, (evenement_id, producteur, charge) = traces[-1], publies[-1]
    assert producteur == _DEPARTEMENT and evenement_id == charge["evenement_id"]
    assert charge["sequence"] == len(traces) and charge["version_entrees"] == derniere["version_entrees"]
    assert (charge["devis_id"], charge["chantier_id"], charge["wct_id"]) == ("DEVIS-1", "CHANTIER-1", "WCT-1")
    assert charge["horodatage_completion"] == COMPLETION  # celui du WCT, aucune horloge de M5
    assert charge["verdict"] == "CALCULEE" and derniere["verdict"] == "CALCULEE"
    assert (charge["cout_reel_cad"], charge["marge_reelle_cad"]) == ("486.00", "114.00")
    assert (charge["marge_prevue_cad"], charge["ecart_marge_cad"]) == ("120.00", "-6.00")
    assert charge["manque"] == []
    # Ce que l'événement dit est ce que la trace dit : les mêmes chiffres, jamais un second calcul.
    assert Decimal(charge["marge_reelle_cad"]) == derniere["rentabilite"]["marge_reelle"]
    assert Decimal(charge["ecart_marge_cad"]) == derniere["rentabilite"]["ecart_marge"]
    assert len({p[0] for p in publies}) == len(publies)


def test_un_cout_partiel_publie_ce_qui_manque_et_aucune_marge_pour_chaque_version(base_durable):
    """Le manifeste livré n'a pas de taux et le livre de prix est vide : le coût réel est partiel."""
    _cascade()

    publies = _publies()
    assert publies, "M5 dit aussi ce qu'il ne peut pas chiffrer"
    for _, _, charge in publies:
        assert charge["verdict"] == "PARTIELLE" and charge["cout_reel_complet"] is False
        assert charge["marge_reelle_cad"] is None and charge["ecart_marge_cad"] is None
        assert charge["cout_reel_cad"] is None
        assert erreurs_charge(TYPE, charge) == []
    derniere = publies[-1][2]
    assert derniere["manque"] == ["REJ-COUT-PRIX-NON-DISPONIBLE", "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER"]
    assert derniere["marge_prevue_cad"] == "120.00"


def test_un_rejeu_ou_une_redelivrance_ne_publie_rien_de_plus(base_durable, taux_configure):
    _prix_au_livre_m6()
    _cascade()
    avant = _publies()

    assert _essayer() == {"statut": "deja_tracee"}
    _livrer("2026-09-25T18:00:00-04:00")  # rien à relivrer
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte(),
                       evenement_id="m3-devis-accepte-DEVIS-1-bis")  # double publication du même devis
    _livrer("2026-09-25T19:00:00-04:00")

    assert [p[0] for p in _publies()] == [p[0] for p in avant]
    assert all(p[2]["prix_definitif"] is False for p in avant)  # BROUILLON reste explicitement provisoire au rejeu


def test_un_prix_ajoute_apres_coup_publie_un_nouvel_etat_qui_remplace_le_partiel(base_durable, taux_configure):
    _cascade()  # pas de prix au livre : partiel
    (_, _, partiel) = _publies()[-1]
    assert partiel["verdict"] == "PARTIELLE" and partiel["manque"] == ["REJ-COUT-PRIX-NON-DISPONIBLE"]

    _prix_au_livre_m6()
    assert _essayer() == {"statut": "tracee"}

    publies = _publies()
    (_, _, complet) = publies[-1]
    assert complet["sequence"] == partiel["sequence"] + 1 and complet["verdict"] == "CALCULEE"
    assert complet["marge_reelle_cad"] == "114.00" and complet["manque"] == []
    assert partiel["prix_definitif"] is False and complet["prix_definitif"] is False
    assert publies[-2][2]["marge_reelle_cad"] is None, "l'historique reste : le partiel n'a jamais porté de marge"


def test_un_retour_a_une_version_anterieure_publie_un_evenement_distinct(base_durable, taux_configure):
    """Taux 50 -> 60 -> 50 : la troisième trace a la version de la première. Sans le rang dans l'identifiant, le
    bus avalerait son événement (no-op) et M8 et M10 resteraient sur la marge du taux à 60."""
    _prix_au_livre_m6()
    _cascade()
    depart = len(_publies())
    premier_etat = _publies()[-1][2]
    assert premier_etat["marge_reelle_cad"] == "114.00"

    taux_configure.write_text(yaml.safe_dump({"configuration": {"taux_horaire_main_d_oeuvre": "60.00"}}),
                              encoding="utf-8")
    assert _essayer() == {"statut": "tracee"}
    taux_configure.write_text(yaml.safe_dump({"configuration": {"taux_horaire_main_d_oeuvre": "50.00"}}),
                              encoding="utf-8")
    assert _essayer() == {"statut": "tracee"}

    publies = _publies()
    assert len(publies) == depart + 2
    deuxieme, troisieme = publies[-2][2], publies[-1][2]
    assert deuxieme["marge_reelle_cad"] == "84.00"  # 3 h x 60,00 $ : 30,00 $ de plus de main-d'oeuvre
    assert troisieme["version_entrees"] == premier_etat["version_entrees"], "la même version qu'au départ"
    assert troisieme["evenement_id"] != premier_etat["evenement_id"]
    assert troisieme["sequence"] == depart + 2 and troisieme["marge_reelle_cad"] == "114.00"
    assert deuxieme["prix_definitif"] is False and troisieme["prix_definitif"] is False
    assert len({p[0] for p in publies}) == len(publies)


def test_la_publication_qui_echoue_annule_aussi_la_trace(base_durable, taux_configure, monkeypatch):
    """Même transaction : si l'événement ne peut pas partir (charge non conforme au catalogue), la trace n'existe
    pas non plus. M8 et M10 ne peuvent jamais voir une trace que M5 n'aurait pas dite, ni l'inverse."""
    _prix_au_livre_m6()
    monkeypatch.setattr(cout_reel, "charge_evenement", lambda *args, **kwargs: {"devis_id": "DEVIS-1"})
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct_bus())

    resume = evenements.repartir(_deps_bus(), maintenant="2026-09-25T17:00:00-04:00")

    assert resume["echecs"] >= 1, resume
    assert _traces() == []
    assert _publies() == []


def test_l_evenement_n_ecrit_rien_en_comptabilite(base_durable, taux_configure):
    _prix_au_livre_m6()
    _cascade()

    assert _publies()
    assert list(stockage.maillons(_DEPARTEMENT, "principal")) == []  # le grand livre : aucun mouvement
    assert [m["type_entree"] for m in stockage.maillons(_DEPARTEMENT, "factures")] == ["facture_creee"]


def test_le_catalogue_du_socle_porte_le_type_et_son_schema_est_versionne():
    schema = evenements.schema(TYPE)
    assert schema["$id"] == f"opsys.evenement/v1/{TYPE}"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == _CLES - {"prix_definitif"}
    assert set(schema["properties"]) == _CLES
    fichier = Path(evenements.schemas.__file__).parent / "catalogue" / f"{TYPE}.json"
    assert fichier.is_file()


def test_catalogue_refuse_une_charge_complete_fictive_sans_marges_requises():
    """Le contrat bus complet reste exercé sans déclarer complet un WCT scalaire ambigu."""
    charge = _charge()
    complete = {**charge, "verdict": "CALCULEE", "cout_reel_complet": True,
                "cout_reel_cad": "486.00", "cout_connu_cad": "486.00",
                "marge_reelle_cad": "114.00", "marge_prevue_cad": "120.00",
                "ecart_marge_cad": "-6.00", "manque": []}
    assert erreurs_charge(TYPE, complete) == []
    assert erreurs_charge(TYPE, {**complete, "marge_reelle_cad": None})
    assert erreurs_charge(TYPE, {**complete, "cout_reel_cad": None})
    assert erreurs_charge(TYPE, {**complete, "cout_reel_complet": False})
    assert erreurs_charge(TYPE, {**complete, "marge_prevue_cad": None})
