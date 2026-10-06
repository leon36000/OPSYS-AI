"""PLAN T1.5-d : M5 calcule le coût réel et la rentabilité d'un chantier dans la cascade « travaux terminés »
(DEFINITION-PRODUIT §6), par le VRAI bus, sur une base SQLite temporaire migrée.

Trois pièces arrivent par le bus, dans un ordre quelconque : le devis accepté de M3 (`cout_total`,
`taux_marge`), le WCT de M4 (`duree_reelle_minutes`) et la variance de M6 (`lignes`, matériaux
réellement utilisés). Le livre de prix de M6 est lu à la source, en lecture seule ; le taux horaire vient de
`department.yaml/configuration`. La dernière pièce à arriver produit l'état complet, tracé dans le registre
dérivé `rentabilite`, une fois par version des entrées ; rien n'est écrit en comptabilité.

Seul M5 est routé (comme `test_evenements_m5.py`). Identifiants et montants fictifs (DEFINITION-PRODUIT §1).
"""

from __future__ import annotations

import itertools
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as outils_mod
import pytest
import yaml

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique

FICTIF = True
_DEPARTEMENT = "m05-financecore"
_M6 = "m06-material-control"
_RACINE_M5 = Path(__file__).resolve().parents[1]
MATERIAU = "gouttiere-alu-5po-fictif"
COMPLETION = "2026-09-25T16:30:00-04:00"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m5-cout-reel.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils_mod.utiliser_stockage_durable()
    yield url
    stockage.liberer()


@pytest.fixture
def taux_configure(tmp_path, monkeypatch):
    """Un manifeste de test qui porte le taux horaire (50,00 $/h, fictif) : le manifeste livré n'en porte pas."""
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {"taux_horaire_main_d_oeuvre": "50.00"}}),
                         encoding="utf-8")
    monkeypatch.setattr(outils_mod, "_MANIFESTE", manifeste)
    return manifeste


def _deps_bus():
    return {_DEPARTEMENT: charger_departements()[_DEPARTEMENT]}


def _devis_accepte(devis_id="DEVIS-1", **surcharges):
    """Devis fictif cohérent : coût prévu 480,00 $ (40 pi x 8,00 + 160,00), majoration 25 % -> prix 600,00 $."""
    base = {
        "devis_id": devis_id, "lead_id": "LEAD-1-fictif", "chantier_id": "CHANTIER-1",
        "lignes": [
            {"reference_ligne": f"{devis_id}-L0", "description": "Gouttières 5po aluminium", "quantite": "40",
             "unite": "pi", "prix_unitaire": "10.00", "prix_ligne": "400.00",
             "reference_besoin_materiau": MATERIAU},
            {"reference_ligne": f"{devis_id}-L1", "description": "Main d'oeuvre installation", "quantite": "1",
             "unite": "forfait", "prix_unitaire": "200.00", "prix_ligne": "200.00",
             "reference_besoin_materiau": None},
        ],
        "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25",
        "horodatage_acceptation": "2026-09-20T10:00:00-04:00",
    }
    return {**base, **surcharges}


def _wct(wct_id="WCT-1", devis_id="DEVIS-1", **surcharges):
    base = {
        "wct_id": wct_id, "intervention_id": f"INT-{wct_id}", "lead_id": "LEAD-1-fictif",
        "technicien_id": "TECH-1", "horodatage_completion": COMPLETION,
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2}, "duree_reelle_minutes": 180,
        "ecart_signale": False, "revue_id": None, "hash_maillon": f"hash-{wct_id}",
        "consommateurs_cibles": ["M5"], "devis_id": devis_id, "statut": "completed_verified",
    }
    return {**base, **surcharges}


def _variance(wct_id="WCT-1", statut="evaluee", reelle="42.0", **surcharges):
    base = {
        "evenement_id": f"m6-variance-{wct_id}-{statut}", "wct_id": wct_id, "intervention_id": f"INT-{wct_id}",
        "chantier_id": "CHANTIER-1", "statut_variance": statut,
        "signal_critique": False if statut == "evaluee" else None, "seuil_pourcentage": 0.3,
        "horodatage_completion": COMPLETION,
        "lignes": [{"materiau": MATERIAU, "unite": "pi", "quantite_prevue": "40.0", "quantite_reelle": reelle,
                    "ecart_pourcentage": "0.05", "critique": False}] if statut == "evaluee" else None,
    }
    return {**base, **surcharges}


def _publier(piece):
    """Publie une des trois pièces (`devis`, `wct`, `variance`) sur le bus."""
    if piece == "devis":
        evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    elif piece == "wct":
        evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    else:
        charge = _variance()
        evenements.publier("m6.variance_chantier", _M6, charge, evenement_id=charge["evenement_id"])


def _livrer(instant="2026-09-25T17:00:00-04:00"):
    resume = evenements.repartir(_deps_bus(), maintenant=instant)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume


def _prix_au_livre_m6(prix=8.0, fournisseur="gentek-fictif", materiau=MATERIAU, devise="CAD"):
    """Une entrée du livre de prix de M6, au format de `m6_material_control.livre_prix.enregistrer_prix`."""
    with stockage.transaction():
        stockage.maillons(_M6, "livre_prix").append({
            "materiau_id": materiau, "fournisseur_id": fournisseur, "prix_unitaire": prix, "devise": devise,
            "date_effet": "2026-09-01", "source_document": None})


def _traces(devis_id="DEVIS-1"):
    with stockage.transaction():
        return [m for m in stockage.maillons(_DEPARTEMENT, "rentabilite") if m["devis_id"] == devis_id]


def _registre(departement, nom):
    with stockage.transaction():
        return list(stockage.maillons(departement, nom))


def _codes(trace):
    return [e["code"] for e in trace["rentabilite"]["manque"]]


def _essayer(devis_id="DEVIS-1"):
    with stockage.transaction():
        return outils_mod._essayer_cout_reel(devis_id)


# =========================================================================================
# 1. L'état complet, quel que soit l'ordre d'arrivée des trois pièces
# =========================================================================================
@pytest.mark.parametrize("ordre", list(itertools.permutations(["devis", "wct", "variance"])),
                         ids=lambda ordre: "-".join(ordre))
def test_les_trois_pieces_dans_n_importe_quel_ordre_donnent_le_meme_etat_complet(base_durable, taux_configure, ordre):
    _prix_au_livre_m6()
    for piece in ordre:
        _publier(piece)
        _livrer()

    traces = _traces()
    derniere = traces[-1]
    r = derniere["rentabilite"]
    assert derniere["verdict"] == "CALCULEE" and r["manque"] == []
    assert r["prix_facture"] == Decimal("600.00")
    assert r["cout_reel"]["cout_total"] == Decimal("486.00")  # 42 pi x 8,00 + 180 min x 50,00 $/h
    assert r["marge_reelle"] == Decimal("114.00") and r["marge_reelle_pct_du_prix"] == Decimal("0.1900")
    assert r["marge_prevue"] == Decimal("120.00") and r["ecart_marge"] == Decimal("-6.00")
    assert (derniere["devis_id"], derniere["chantier_id"], derniere["wct_id"]) == ("DEVIS-1", "CHANTIER-1", "WCT-1")
    assert derniere["horodatage"] == COMPLETION  # celui du WCT : aucune horloge
    versions = [t["version_entrees"] for t in traces]
    assert len(versions) == len(set(versions)) <= 3, "une trace par version des entrées, jamais deux fois la même"
    with stockage.transaction():
        assert outils_mod._etat_chantier("DEVIS-1")["rentabilite"]["version_entrees"] == derniere["version_entrees"]


def test_chaque_piece_apporte_ce_qu_elle_sait_la_derniere_complete_l_etat(base_durable, taux_configure):
    _prix_au_livre_m6()
    _publier("devis")
    _livrer()
    assert _traces() == [], "sans WCT : rien à calculer, un statut d'attente"

    _publier("wct")
    _livrer()
    (apres_wct,) = _traces()
    assert apres_wct["verdict"] == "PARTIELLE"
    assert _codes(apres_wct) == ["REJ-COUT-MATERIAUX-REELS-ABSENTS"]  # la variance de M6 n'est pas encore là
    assert apres_wct["rentabilite"]["prix_facture"] == Decimal("600.00")  # la facture brouillon, elle, existe
    assert apres_wct["rentabilite"]["cout_reel"]["cout_total_connu"] == Decimal("150.00")  # la main-d'oeuvre

    _publier("variance")
    _livrer()
    avant, apres = _traces()
    assert avant["version_entrees"] == apres_wct["version_entrees"]
    assert apres["verdict"] == "CALCULEE" and apres["rentabilite"]["marge_reelle"] == Decimal("114.00")


def test_rejeu_et_redelivrance_ne_tracent_rien_de_plus(base_durable, taux_configure):
    _prix_au_livre_m6()
    for piece in ("devis", "wct", "variance"):
        _publier(piece)
    _livrer()
    avant = _traces()

    _livrer("2026-09-25T18:00:00-04:00")  # rien à relivrer
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte(),
                       evenement_id="m3-devis-accepte-DEVIS-1-bis")  # double publication du même devis
    _livrer("2026-09-25T19:00:00-04:00")

    assert _traces() == avant
    assert _essayer() == {"statut": "deja_tracee"}
    assert _traces() == avant


def test_les_statuts_de_la_cascade_sont_rendus_par_les_consommateurs(base_durable, taux_configure):
    """Le résultat que le bus garde pour chaque livraison dit où en est le coût réel."""
    consommateurs = outils_mod.consommateurs()
    with stockage.transaction():
        recu_devis = consommateurs["m3.devis_accepte"](_devis_accepte())
        recu_wct = consommateurs["m4.travaux_termines"](_wct())
        recu_variance = consommateurs["m6.variance_chantier"](_variance())
        rejeu = consommateurs["m6.variance_chantier"](_variance())

    assert recu_devis["cout_reel"] == "en_attente_travaux_termines"
    assert recu_wct["cout_reel"] == "tracee" and recu_wct["statut"] == "facture_creee"
    assert recu_variance["cout_reel"] == "tracee"
    assert rejeu["cout_reel"] == "deja_tracee"


def test_un_wct_sans_devis_ou_inconnu_n_est_jamais_trace(base_durable, taux_configure):
    consommateurs = outils_mod.consommateurs()
    with stockage.transaction():
        sans_devis = consommateurs["m4.travaux_termines"](_wct(wct_id="WCT-SANS-DEVIS", devis_id=None))
        variance_orpheline = consommateurs["m6.variance_chantier"](_variance(wct_id="WCT-INCONNU"))

    assert sans_devis == {"traite": True, "wct_id": "WCT-SANS-DEVIS", "statut": "wct_sans_devis_id"}
    assert variance_orpheline["cout_reel"] == "en_attente_travaux_termines"
    assert _registre(_DEPARTEMENT, "rentabilite") == []


# =========================================================================================
# 2. Rien d'inventé : des manques nommés, un coût partiel dit partiel
# =========================================================================================
def test_sans_prix_au_livre_la_ligne_est_prix_non_disponible_et_le_cout_partiel(base_durable, taux_configure):
    for piece in ("devis", "wct", "variance"):
        _publier(piece)
    _livrer()

    derniere = _traces()[-1]
    r = derniere["rentabilite"]
    assert derniere["verdict"] == "PARTIELLE" and _codes(derniere) == ["REJ-COUT-PRIX-NON-DISPONIBLE"]
    assert r["cout_reel"]["complet"] is False and r["cout_reel"]["cout_total"] is None
    assert r["cout_reel"]["materiaux"]["lignes"][0]["statut"] == "PRIX_NON_DISPONIBLE"
    assert r["cout_reel"]["cout_total_connu"] == Decimal("150.00")
    assert r["marge_reelle"] is None and r["marge_partielle_plafond"] == Decimal("450.00")


def test_taux_horaire_absent_du_manifeste_livre_le_verdict_est_taux_a_configurer(base_durable):
    """Le manifeste LIVRÉ ne porte pas de taux : c'est un chiffre de l'entreprise, jamais inventé ici."""
    livre = yaml.safe_load((_RACINE_M5 / "department.yaml").read_text(encoding="utf-8"))
    assert "taux_horaire_main_d_oeuvre" not in (livre.get("configuration") or {})
    _prix_au_livre_m6()
    for piece in ("devis", "wct", "variance"):
        _publier(piece)
    _livrer()

    derniere = _traces()[-1]
    assert _codes(derniere) == ["REJ-COUT-TAUX-HORAIRE-A-CONFIGURER"]
    r = derniere["rentabilite"]
    assert r["cout_reel"]["materiaux"]["cout_connu"] == Decimal("336.00")  # les matériaux sont chiffrés
    assert r["cout_reel"]["main_d_oeuvre"]["cout"] is None and r["cout_reel"]["cout_total"] is None


@pytest.mark.parametrize(
    "contenu",
    ["configuration: [", "pas un mapping", "configuration:\n  taux_horaire_main_d_oeuvre: 0\n"],
    ids=["yaml_invalide", "racine_textuelle", "taux_nul"],
)
def test_un_manifeste_illisible_ou_un_taux_nul_donne_taux_a_configurer_sans_panne(
        base_durable, tmp_path, monkeypatch, contenu):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(contenu, encoding="utf-8")
    monkeypatch.setattr(outils_mod, "_MANIFESTE", manifeste)
    _prix_au_livre_m6()
    for piece in ("devis", "wct", "variance"):
        _publier(piece)
    _livrer()

    assert _codes(_traces()[-1]) == ["REJ-COUT-TAUX-HORAIRE-A-CONFIGURER"]


def test_manifeste_absent_du_disque_donne_taux_a_configurer_sans_panne(base_durable, tmp_path, monkeypatch):
    monkeypatch.setattr(outils_mod, "_MANIFESTE", tmp_path / "inexistant.yaml")
    with stockage.transaction():
        assert outils_mod._taux_horaire_configure() is None


def test_deux_fournisseurs_aux_prix_differents_le_cout_dit_prix_ambigu(base_durable, taux_configure):
    _prix_au_livre_m6(8.0, "gentek-fictif")
    _prix_au_livre_m6(9.0, "kaycan-fictif")
    for piece in ("devis", "wct", "variance"):
        _publier(piece)
    _livrer()

    derniere = _traces()[-1]
    assert _codes(derniere) == ["REJ-COUT-PRIX-AMBIGU"] and derniere["verdict"] == "PARTIELLE"


def test_devis_ou_wct_recus_avant_t1_5_d_donnent_des_manques_pas_une_panne(base_durable, taux_configure):
    """Les maillons écrits avant ce changement ne portent ni `cout_total` ni `duree_reelle_minutes` : le calcul
    le dit, il n'en devine pas."""
    with stockage.transaction():
        stockage.maillons(_DEPARTEMENT, "devis_recus").append({
            "devis_id": "DEVIS-1", "lead_id": "LEAD-1-fictif", "chantier_id": "CHANTIER-1",
            "lignes": _devis_accepte()["lignes"], "prix_total": "600.00",
            "horodatage_acceptation": "2026-09-20T10:00:00-04:00"})
        stockage.maillons(_DEPARTEMENT, "wct_recus").append({
            "wct_id": "WCT-1", "intervention_id": "INT-WCT-1", "devis_id": "DEVIS-1",
            "horodatage_completion": COMPLETION})
        stockage.maillons(_DEPARTEMENT, "variance_recue").append({
            "wct_id": "WCT-1", "chantier_id": "CHANTIER-1", "statut_variance": "evaluee",
            "signal_critique": False, "horodatage_completion": COMPLETION})
    _prix_au_livre_m6()

    assert _essayer() == {"statut": "tracee"}

    derniere = _traces()[-1]
    assert _codes(derniere) == [
        "REJ-COUT-MATERIAUX-REELS-ABSENTS", "REJ-COUT-TEMPS-POINTE-ABSENT", "REJ-RENTABILITE-FACTURE-ABSENTE",
        "REJ-RENTABILITE-MARGE-PREVUE-ABSENTE"]


def test_un_devis_sans_chantier_est_trace_avec_le_chantier_que_la_variance_de_m6_connait(base_durable, taux_configure):
    """M3 peut accepter un devis avant que M4 planifie (`chantier_id` nul) : pas de facture (attente nommée), mais la
    déclaration de M6 connaît le chantier, et le coût réel se calcule."""
    _prix_au_livre_m6()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte(chantier_id=None))
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    evenements.publier("m6.variance_chantier", _M6, _variance(), evenement_id="m6-variance-WCT-1-evaluee")
    _livrer()

    derniere = _traces()[-1]
    assert derniere["chantier_id"] == "CHANTIER-1"
    assert derniere["rentabilite"]["cout_reel"]["cout_total"] == Decimal("486.00")
    assert derniere["verdict"] == "PARTIELLE" and _codes(derniere) == ["REJ-RENTABILITE-FACTURE-ABSENTE"]
    r = derniere["rentabilite"]
    assert r["marge_reelle"] is None and r["marge_prevue"] == Decimal("120.00")


def test_un_signal_evalue_prime_sur_un_signal_plus_ancien_livre_apres(base_durable, taux_configure):
    """`evaluee` est terminal chez M6 : un réessai qui livre `declaration_absente` APRÈS `evaluee` ne l'écrase pas."""
    _prix_au_livre_m6()
    consommateurs = outils_mod.consommateurs()
    with stockage.transaction():
        consommateurs["m3.devis_accepte"](_devis_accepte())
        consommateurs["m4.travaux_termines"](_wct())
        consommateurs["m6.variance_chantier"](_variance())
        consommateurs["m6.variance_chantier"](_variance(statut="declaration_absente"))

    derniere = _traces()[-1]
    assert derniere["verdict"] == "CALCULEE", "le signal évalué fait foi, pas le dernier arrivé"


def test_un_signal_delirant_ne_bloque_jamais_la_facture_brouillon(base_durable, taux_configure):
    """Le calcul du coût ne peut pas empêcher la création de la facture faite dans la même transaction."""
    with stockage.transaction():
        stockage.maillons(_DEPARTEMENT, "variance_recue").append({
            "wct_id": "WCT-1", "chantier_id": None, "statut_variance": "evaluee", "signal_critique": None,
            "horodatage_completion": COMPLETION, "lignes": [None, 5, "x", {"materiau": 3}]})
    _publier("devis")
    _publier("wct")
    _livrer()

    factures = [m["type_entree"] for m in _registre(_DEPARTEMENT, "factures")]
    assert factures == ["facture_creee"]
    assert _traces()[-1]["verdict"] == "PARTIELLE"
    assert evenements.etat()["quarantaine"] == []


# =========================================================================================
# 3. L'état suit ses entrées : un prix, une facture envoyée, jamais une réécriture
# =========================================================================================
def test_un_prix_ajoute_au_livre_apres_coup_ajoute_une_trace_sans_effacer_la_precedente(base_durable, taux_configure):
    for piece in ("devis", "wct", "variance"):
        _publier(piece)
    _livrer()
    historique = _traces()
    avant = historique[-1]
    assert _codes(avant) == ["REJ-COUT-PRIX-NON-DISPONIBLE"]

    _prix_au_livre_m6()  # M6 saisit le prix plus tard
    assert _essayer() == {"statut": "tracee"}
    assert _essayer() == {"statut": "deja_tracee"}

    traces = _traces()
    assert traces[:len(historique)] == historique, "l'historique n'est jamais réécrit"
    assert len(traces) == len(historique) + 1
    seconde = traces[-1]
    assert seconde["verdict"] == "CALCULEE" and seconde["rentabilite"]["marge_reelle"] == Decimal("114.00")
    assert avant["version_entrees"] != seconde["version_entrees"]


def test_le_taux_change_une_nouvelle_version_l_ancienne_reste(base_durable, taux_configure):
    _prix_au_livre_m6()
    for piece in ("devis", "wct", "variance"):
        _publier(piece)
    _livrer()
    taux_configure.write_text(yaml.safe_dump({"configuration": {"taux_horaire_main_d_oeuvre": "60.00"}}),
                              encoding="utf-8")

    assert _essayer() == {"statut": "tracee"}

    *_, ancienne, nouvelle = _traces()
    assert ancienne["rentabilite"]["cout_reel"]["cout_total"] == Decimal("486.00")
    assert nouvelle["rentabilite"]["cout_reel"]["cout_total"] == Decimal("516.00")  # 42 x 8 + 3 h x 60 $/h


def test_la_facture_envoyee_rend_le_prix_definitif_dans_un_nouvel_etat(base_durable, taux_configure):
    _prix_au_livre_m6()
    for piece in ("devis", "wct", "variance"):
        _publier(piece)
    _livrer()
    avant = _traces()
    assert avant[-1]["rentabilite"]["prix_definitif"] is False
    envoyer = next(o for o in outils_mod.outils() if o.nom == "m5_envoyer_facture")
    reponse = executer_atomique(envoyer, {"facture_id": "fac-DEVIS-1", "horodatage": COMPLETION})
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse

    # La transition trace et publie immédiatement; un rattrapage est désormais un rejeu.
    assert len(_traces()) == len(avant) + 1
    assert _traces()[:len(avant)] == avant
    assert _essayer() == {"statut": "deja_tracee"}
    assert len(_traces()) == len(avant) + 1

    derniere = _traces()[-1]["rentabilite"]
    assert (derniere["statut_facture"], derniere["prix_definitif"]) == ("ENVOYEE", True)
    assert derniere["marge_reelle"] == Decimal("114.00")


# =========================================================================================
# 4. Rien n'est écrit en comptabilité, et le livre de M6 n'est que lu
# =========================================================================================
def test_la_cascade_n_ecrit_ni_le_grand_livre_ni_le_livre_de_prix_ni_les_creances(base_durable, taux_configure):
    _prix_au_livre_m6()
    livre_avant = _registre(_M6, "livre_prix")
    for piece in ("devis", "wct", "variance"):
        _publier(piece)
    _livrer()

    assert _registre(_DEPARTEMENT, "principal") == [], "aucun mouvement : le grand livre n'est jamais touché"
    assert [m["type_entree"] for m in _registre(_DEPARTEMENT, "factures")] == ["facture_creee"]
    assert _registre(_M6, "livre_prix") == livre_avant, "le livre de prix de M6 n'est que lu"
    assert _traces(), "le seul registre écrit est le registre dérivé `rentabilite`"
    with stockage.transaction():
        creances = outils_mod.facturation.comptes_a_recevoir(outils_mod._registre_factures(None))[0]
    assert creances["nombre"] == 0, "un brouillon n'est pas à recevoir"


def test_le_livre_de_prix_est_lu_en_copie_jamais_ecrit(base_durable):
    _prix_au_livre_m6()

    with stockage.transaction():
        lu = outils_mod._livre_de_prix_m6()
        lu[0]["prix_unitaire"] = 0.01  # la copie change, pas le registre
    assert _registre(_M6, "livre_prix")[0]["prix_unitaire"] == 8.0
    assert isinstance(lu, tuple)


def test_le_code_de_m5_n_ecrit_jamais_dans_le_registre_d_un_autre_departement():
    """Garde statique : la seule référence au livre de prix de M6 est `_livre_de_prix_m6`, qui n'itère que."""
    source = Path(outils_mod.__file__).read_text(encoding="utf-8")

    assert source.count("_DEPARTEMENT_LIVRE_DE_PRIX") == 2  # la définition et l'unique lecture
    corps = source.split("def _livre_de_prix_m6", 1)[1].split("\ndef ", 1)[0]
    assert ".append" not in corps and ".extend" not in corps and "for entree in maillons" in corps
    assert "m06-material-control" not in source.replace('_DEPARTEMENT_LIVRE_DE_PRIX = "m06-material-control"', "")
