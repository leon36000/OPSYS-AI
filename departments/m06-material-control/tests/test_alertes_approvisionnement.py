"""C9 — alertes manquantes et rappels planifiés : agrégats NEUTRES par article et par équipe DÉCLARÉE (jamais un nom
d'employé), « commande reçue mais stock disparu », rappel de déclaration d'usage manquante, rappel de réception d'un PO
envoyé au-delà du délai habituel DÉCLARÉ du fournisseur.

Rouge-avant : `m6_material_control.alertes_approvisionnement` n'existe pas et `m6_lire_alertes_approvisionnement`
n'est pas déclaré.

Données FICTIVES (`-fictif`), horloge injectée, vrais registres durables.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from m6_material_control import alertes_approvisionnement as alertes

from opsys import stockage
from opsys.outils import Autonomie, Niveau, executer_atomique

_spec = importlib.util.spec_from_file_location(
    "fixture_alertes_approvisionnement", Path(__file__).with_name("test_reservation_outils.py")
)
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)
base, m6 = aide.base, aide.m6

FICTIF = True
GOUTTIERE = aide.GOUTTIERE
VIS = aide.VIS
H_MAINTENANT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
FENETRE = 30
SEUIL = 2


def _mouvement(type_mouvement, materiau=GOUTTIERE, quantite=-1.0, chantier="CH-FICT", wct_id=None):
    mouvement = {
        "index": 0, "type_mouvement": type_mouvement, "chantier_id": chantier, "materiau_id": materiau,
        "quantite": quantite, "cout_unitaire": None, "hash_precedent": "", "hash_maillon": "a" * 64,
    }
    if wct_id is not None:
        mouvement["wct_id"] = wct_id
    return mouvement


def _wct(wct_id, jours=1, equipe=None):
    return {
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "horodatage_completion":
        (H_MAINTENANT - timedelta(days=jours)).isoformat(),
        **({"equipe_id": equipe} if equipe is not None else {}),
    }


def _po(po_id, statut="sent_to_supplier", jours=10, fournisseur="FOURN-FICT"):
    return {"po_id": po_id, "statut": statut, "fournisseur_id": fournisseur,
            "horodatage": (H_MAINTENANT - timedelta(days=jours)).isoformat(), "lignes": []}


def _fournisseur(fournisseur_id="FOURN-FICT", delai=5):
    return {"fournisseur_id": fournisseur_id, "delai_habituel_jours": delai}


def _calculer(mouvements=(), bons_commande=(), fournisseurs=(), wct_recus=(), equipes=None,
              seuil=SEUIL, fenetre=FENETRE, maintenant=H_MAINTENANT):
    return alertes.calculer(
        mouvements=mouvements, bons_commande=bons_commande, fournisseurs=fournisseurs, wct_recus=wct_recus,
        equipes_declarees=equipes, seuil_repetition=seuil, fenetre_jours=fenetre, maintenant=maintenant,
    )


# --------------------------------------------------------------------------------------------- module pur
def test_les_agregats_sont_par_article_et_aucun_nom_d_employe():
    mouvements = [
        _mouvement("PERTE", wct_id="wct-1"), _mouvement("PERTE", wct_id="wct-2"),
        _mouvement("AJUSTEMENT"), _mouvement("AJUSTEMENT"),
    ]
    resultat = alertes.calculer(
        mouvements=mouvements, bons_commande=(), fournisseurs=(), wct_recus=(_wct("wct-1"), _wct("wct-2")),
        equipes_declarees={"eq-fictive"},
        seuil_repetition=2, fenetre_jours=30, maintenant=H_MAINTENANT,
        equipes_par_wct={"wct-1": "eq-fictive", "wct-2": "eq-fictive"},
    )
    types = {a["type"] for a in resultat["alertes"]}
    assert {"items_manquants_repetes_article", "ajustements_frequents_article",
            "items_manquants_repetes_equipe"} <= types
    texte = json.dumps(resultat, ensure_ascii=False)
    for interdit in ("alice", "bruno", "technicien", "employe", "employé"):
        assert interdit not in texte.lower()
    assert all("equipe_id" not in a or a["equipe_id"] == "eq-fictive" for a in resultat["alertes"])


def test_une_equipe_non_declaree_n_est_jamais_regroupee():
    resultat = alertes.calculer(
        mouvements=[_mouvement("PERTE", wct_id="wct-1"), _mouvement("PERTE", wct_id="wct-2")],
        bons_commande=(), fournisseurs=(), wct_recus=(_wct("wct-1"), _wct("wct-2")),
        equipes_declarees={"eq-fictive"},
        seuil_repetition=2, fenetre_jours=30, maintenant=H_MAINTENANT,
        equipes_par_wct={"wct-1": "personne-non-declaree", "wct-2": "personne-non-declaree"},
    )
    assert not [a for a in resultat["alertes"] if a["type"] == "items_manquants_repetes_equipe"]
    non_evaluee = [n for n in resultat["non_evaluees"] if "equipe" in n["type"]]
    assert non_evaluee and "déclar" in non_evaluee[0]["action"].lower()


def test_sans_seuil_declare_aucune_repetition_n_est_inventee_et_le_verdict_dit_quoi_declarer():
    resultat = _calculer(
        mouvements=[_mouvement("PERTE"), _mouvement("PERTE"), _mouvement("AJUSTEMENT")],
        seuil=None,
    )
    assert not [a for a in resultat["alertes"] if "repetes" in a["type"] or "frequents" in a["type"]]
    cles = {n["cle"] for n in resultat["non_evaluees"]}
    assert "configuration.alertes_approvisionnement.seuil_repetition" in cles
    assert all(n["action"] for n in resultat["non_evaluees"])


def test_le_seuil_de_repetition_est_inclus_et_la_fenetre_exclut_les_faits_anciens():
    borne = _calculer(mouvements=[_mouvement("PERTE"), _mouvement("PERTE")])
    assert [a for a in borne["alertes"] if a["type"] == "items_manquants_repetes_article"][0]["compte"] == 2
    sous = _calculer(mouvements=[_mouvement("PERTE")])
    assert not [a for a in sous["alertes"] if a["type"] == "items_manquants_repetes_article"]


def test_commande_recue_mais_stock_disparu():
    mouvements = [
        _mouvement("RECEPTION", quantite=10.0), _mouvement("CONSOMMATION", quantite=-10.0),
    ]
    resultat = _calculer(mouvements=mouvements)
    (alerte,) = [a for a in resultat["alertes"] if a["type"] == "commande_recue_stock_disparu"]
    assert alerte["materiau_id"] == GOUTTIERE and alerte["quantite_recue"] == "10" and alerte["stock_actuel"] == "0"
    encore = _calculer(mouvements=[_mouvement("RECEPTION", quantite=10.0), _mouvement("CONSOMMATION", quantite=-4.0)])
    assert not [a for a in encore["alertes"] if a["type"] == "commande_recue_stock_disparu"]
    jamais_recu = _calculer(mouvements=[_mouvement("CONSOMMATION", quantite=-1.0)])
    assert not [a for a in jamais_recu["alertes"] if a["type"] == "commande_recue_stock_disparu"]


def test_rappel_de_declaration_d_usage_manquante_seulement_pour_un_wct_sans_declaration():
    resultat = _calculer(wct_recus=(_wct("wct-sans-declaration"), _wct("wct-declare")),
                         mouvements=[_mouvement("CONSOMMATION", wct_id="wct-declare")])
    (rappel,) = [a for a in resultat["alertes"] if a["type"] == "declaration_usage_manquante"]
    assert rappel["wct_id"] == "wct-sans-declaration" and rappel["intervention_id"] == "int-wct-sans-declaration"
    assert "jours_depuis_completion" in rappel


def test_les_bornes_de_la_fenetre_sont_incluses_et_la_seconde_en_trop_exclue():
    maintenant = H_MAINTENANT
    assert alertes._borne(maintenant.isoformat(), maintenant, 30) is True, "l'instant même est dans la fenêtre"
    exact = (maintenant - timedelta(days=30)).isoformat()
    assert alertes._borne(exact, maintenant, 30) is True, "la borne est incluse"
    trop_vieux = (maintenant - timedelta(days=30, seconds=1)).isoformat()
    assert alertes._borne(trop_vieux, maintenant, 30) is False
    assert alertes._borne("pas-un-instant", maintenant, 30) is False


def test_un_instant_absent_ou_sans_fuseau_n_evalue_rien_et_le_dit():
    for hostile in (None, "2026-10-20T12:00:00", "hier"):
        resultat = alertes.calculer(mouvements=(), maintenant=hostile)
        assert resultat["alertes"] == [] and resultat["non_evaluees"]


def test_les_comptes_ne_melangent_pas_les_types_et_somment_pertes_et_bris():
    resultat = _calculer(mouvements=[
        _mouvement("PERTE"), _mouvement("BRIS"),
        _mouvement("RECEPTION", quantite=10.0), _mouvement("CONSOMMATION", quantite=-10.0),
    ])
    (manquants,) = [a for a in resultat["alertes"] if a["type"] == "items_manquants_repetes_article"]
    assert manquants["compte"] == 2, "une perte ET un bris comptent deux items manquants"
    assert not [a for a in resultat["alertes"] if a["type"] == "ecarts_repetes_article"]
    zeros = [
        {**_mouvement("VARIANCE_INVENTAIRE", quantite=0.0)},
        {**_mouvement("VARIANCE_INVENTAIRE", quantite=0.0)},
    ]
    assert not [a for a in _calculer(mouvements=zeros)["alertes"] if a["type"] == "ecarts_repetes_article"]


def test_une_equipe_declaree_ne_produit_aucun_manque_a_configurer_et_le_compte_reste_un():
    declared = alertes.calculer(
        mouvements=[_mouvement("PERTE", wct_id="wct-1")],
        wct_recus=(_wct("wct-1"),), equipes_declarees={"eq-fictive"},
        equipes_par_wct={"wct-1": "eq-fictive"}, seuil_repetition=2, fenetre_jours=30, maintenant=H_MAINTENANT,
    )
    assert not [n for n in declared["non_evaluees"] if n["type"].endswith("equipe")]
    assert not [a for a in declared["alertes"] if a["type"] == "items_manquants_repetes_equipe"], (
        "un seul item, seuil 2")
    absent = alertes.calculer(
        mouvements=[_mouvement("PERTE", wct_id="wct-1")], wct_recus=(_wct("wct-1"),),
        equipes_declarees=None, equipes_par_wct={"wct-1": "eq-fictive"},
        seuil_repetition=2, fenetre_jours=30, maintenant=H_MAINTENANT,
    )
    assert [n for n in absent["non_evaluees"] if n["type"].endswith("equipe")]


def test_un_mouvement_de_type_inconnu_ou_non_textuel_ne_change_jamais_le_stock():
    inconnu = _calculer(mouvements=[
        _mouvement("INVENTE", quantite=10.0),
        {"type_mouvement": "RECEPTION", "materiau_id": 3, "quantite": 10.0},
    ])
    assert not [a for a in inconnu["alertes"] if a["type"] == "commande_recue_stock_disparu"]


def test_seule_une_reception_positive_compte_comme_commande_recue():
    for mouvement in (
        _mouvement("CONSOMMATION", quantite=1.0),
        _mouvement("RETOUR", quantite=1.0),
        _mouvement("RECEPTION", quantite=0.0),
    ):
        resultat = _calculer(mouvements=[mouvement])
        assert not [a for a in resultat["alertes"] if a["type"] == "commande_recue_stock_disparu"], mouvement
    demi = _calculer(mouvements=[_mouvement("RECEPTION", quantite=0.5), _mouvement("CONSOMMATION", quantite=-0.5)])
    assert [a for a in demi["alertes"] if a["type"] == "commande_recue_stock_disparu"]


def test_commande_recue_mais_stock_encore_positif_ne_signale_rien_a_la_borne_un():
    resultat = _calculer(mouvements=[_mouvement("RECEPTION", quantite=10.0), _mouvement("CONSOMMATION", quantite=-9.0)])
    assert not [a for a in resultat["alertes"] if a["type"] == "commande_recue_stock_disparu"]


def test_un_wct_sans_identifiant_ou_hors_fenetre_est_ignore():
    vide = _calculer(wct_recus=({"wct_id": "", "intervention_id": "int-vide",
                                 "horodatage_completion": H_MAINTENANT.isoformat()},))
    assert not vide["alertes"]
    ancien = _calculer(wct_recus=(_wct("wct-vieux", jours=31),))
    assert not [a for a in ancien["alertes"] if a["type"] == "declaration_usage_manquante"]
    sans_fuseau = _calculer(wct_recus=({"wct_id": "wct-naif", "intervention_id": "int",
                                        "horodatage_completion": "2026-10-19T12:00:00"},))
    assert not [a for a in sans_fuseau["alertes"] if a["type"] == "declaration_usage_manquante"]


def test_un_po_hors_fenetre_ou_sans_identifiant_est_ignore():
    ancien = _calculer(bons_commande=(_po("PO-VIEUX", jours=31),), fournisseurs=(_fournisseur(delai=5),))
    assert not [a for a in ancien["alertes"] if a["type"] == "reception_po_en_retard"]
    sans_id = _calculer(bons_commande=({"po_id": "", "statut": "sent_to_supplier", "fournisseur_id": "FOURN-FICT",
                                        "horodatage": "2026-10-01T12:00:00+00:00"},),
                        fournisseurs=(_fournisseur(delai=5),))
    assert not [a for a in sans_id["alertes"] if a["type"] == "reception_po_en_retard"]


def test_un_delai_fournisseur_d_un_jour_est_utilisable():
    resultat = _calculer(bons_commande=(_po("PO-DELAI-1", jours=2),), fournisseurs=(_fournisseur(delai=1),))
    (rappel,) = [a for a in resultat["alertes"] if a["type"] == "reception_po_en_retard"]
    assert rappel["delai_habituel_jours"] == 1


def test_la_version_ne_depend_ni_de_l_identifiant_ni_des_dates_et_fait_seize_hexadecimaux():
    contenu = {"alertes": [], "non_evaluees": [], "comptes": {}}
    a = alertes.version_donnees({**contenu, "constat_id": "A", "date_reference": "2026-10-20", "constate_le": "x"})
    b = alertes.version_donnees({**contenu, "constat_id": "B", "date_reference": "2026-10-21", "constate_le": "y"})
    assert a == b and len(a) == 16


def test_l_identifiant_d_un_instantane_se_termine_par_huit_hexadecimaux_et_se_rejoue():
    instantane = alertes.construire_instantane(
        constate_le=H_MAINTENANT.isoformat(), date_reference="2026-10-20", fenetre_jours=30, seuil_repetition=2,
        maintenant=H_MAINTENANT,
    )
    assert len(instantane["constat_id"].rsplit("-", 1)[-1]) == 8
    assert len(instantane["version_donnees"]) == 16


def test_les_variance_non_nulles_sont_comptees_une_fois_et_les_nulles_ignorees():
    resultat = _calculer(mouvements=[
        _mouvement("VARIANCE_INVENTAIRE", quantite=1.0),
        _mouvement("VARIANCE_INVENTAIRE", quantite=-2.0),
        _mouvement("VARIANCE_INVENTAIRE", quantite=0.0),
    ])
    (alerte,) = [a for a in resultat["alertes"] if a["type"] == "ecarts_repetes_article"]
    assert alerte["compte"] == 2


def test_la_cle_de_tri_prend_l_identifiant_present_et_jamais_un_champ_absent():
    assert alertes._cle_article({"type": "t", "materiau_id": "M"}) == ("t", "M", "")
    assert alertes._cle_article({"type": "t", "equipe_id": "E"}) == ("t", "E", "")
    assert alertes._cle_article({"type": "t", "po_id": "P"}) == ("t", "", "P")
    assert alertes._cle_article({"type": "t", "wct_id": "W"}) == ("t", "", "W")


def test_une_fenetre_d_un_jour_est_utilisable():
    resultat = _calculer(wct_recus=(_wct("wct-un-jour", jours=1),), fenetre=1)
    assert [a for a in resultat["alertes"] if a["type"] == "declaration_usage_manquante"]
    hors = _calculer(wct_recus=(_wct("wct-deux-jours", jours=2),), fenetre=1)
    assert not hors["alertes"]


def test_un_mouvement_hors_types_avec_quantite_negative_ne_change_pas_le_stock():
    resultat = _calculer(mouvements=[
        _mouvement("RECEPTION", quantite=10.0), _mouvement("INVENTE", quantite=-10.0),
    ])
    assert not [a for a in resultat["alertes"] if a["type"] == "commande_recue_stock_disparu"]


def test_un_wct_hors_types_avec_une_equipe_ne_declenche_pas_le_manque_de_profil():
    resultat = alertes.calculer(
        mouvements=[_mouvement("CONSOMMATION", wct_id="wct-1")], bons_commande=(), fournisseurs=(),
        wct_recus=(_wct("wct-1"),), equipes_declarees=None, equipes_par_wct={"wct-1": "eq-fictive"},
        seuil_repetition=2, fenetre_jours=30, maintenant=H_MAINTENANT,
    )
    assert not [n for n in resultat["non_evaluees"] if n["type"].endswith("equipe")]


def test_la_quantite_recue_d_une_alerte_ne_compte_que_les_receptions():
    resultat = _calculer(mouvements=[
        _mouvement("RECEPTION", quantite=10.0), _mouvement("RETOUR", quantite=1.0),
        _mouvement("CONSOMMATION", quantite=-11.0),
    ])
    (alerte,) = [a for a in resultat["alertes"] if a["type"] == "commande_recue_stock_disparu"]
    assert alerte["quantite_recue"] == "10" and alerte["stock_actuel"] == "0"


def test_un_wct_complete_le_meme_jour_a_zero_jour_et_non_un():
    resultat = _calculer(wct_recus=({
        "wct_id": "wct-du-jour", "intervention_id": "int-wct-du-jour",
        "horodatage_completion": "2026-10-20T10:00:00+00:00",
    },))
    (rappel,) = [a for a in resultat["alertes"] if a["type"] == "declaration_usage_manquante"]
    assert rappel["jours_depuis_completion"] == 0


def test_rappel_de_reception_au_dela_du_delai_habituel_declare_du_fournisseur():
    resultat = _calculer(bons_commande=(_po("PO-RETARD", jours=10),), fournisseurs=(_fournisseur(delai=5),))
    (rappel,) = [a for a in resultat["alertes"] if a["type"] == "reception_po_en_retard"]
    assert (rappel["po_id"], rappel["fournisseur_id"], rappel["delai_habituel_jours"]) == ("PO-RETARD", "FOURN-FICT", 5)
    assert rappel["jours_depuis_envoi"] == 10
    recu = _calculer(bons_commande=(_po("PO-RECU", statut="received", jours=10),), fournisseurs=(_fournisseur(),))
    assert not [a for a in recu["alertes"] if a["type"] == "reception_po_en_retard"]
    a_la_borne = _calculer(bons_commande=(_po("PO-BORNE", jours=5),), fournisseurs=(_fournisseur(delai=5),))
    assert not [a for a in a_la_borne["alertes"] if a["type"] == "reception_po_en_retard"]
    sans_delai = _calculer(bons_commande=(_po("PO-SANS-DELAI"),), fournisseurs=(
        {"fournisseur_id": "FOURN-FICT", "delai_habituel_jours": None},))
    assert not [a for a in sans_delai["alertes"] if a["type"] == "reception_po_en_retard"]
    assert any("delai_habituel_jours" in n["cle"] for n in sans_delai["non_evaluees"])


def test_sans_fenetre_declaree_les_faits_ne_sont_pas_dates_par_defaut():
    resultat = _calculer(fenetre=None)
    assert any("fenetre_jours" in n["cle"] for n in resultat["non_evaluees"])
    assert not resultat["alertes"]


def test_le_calcul_est_deterministe_et_ne_porte_aucun_prix_ni_texte_de_client():
    mouvements = [_mouvement("PERTE", wct_id="wct-1"), _mouvement("PERTE", wct_id="wct-2")]
    premier = _calculer(mouvements=mouvements)
    second = _calculer(mouvements=mouvements)
    assert premier["alertes"] == second["alertes"]
    texte = json.dumps(premier, ensure_ascii=False).lower()
    for interdit in ("prix", "cout", "client", "adresse", "@"):
        assert interdit not in texte


# --------------------------------------------------------------------------------------------- outil et planification
def test_le_constat_planifie_existant_reste_inactif_par_defaut(base):
    import yaml

    manifeste = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "department.yaml").read_text(encoding="utf-8"))
    constat = next(c for c in manifeste["constats_planifies"] if c["nom"] == "disponibilite")
    assert constat["outil"] == "m6_constater_disponibilite"
    assert "alertes" in constat["description"].lower()


def test_les_deux_schemas_d_outils_restent_fermes_et_bornes(m6):
    ajustement = m6["m6_ajuster_stock"].parametres
    assert ajustement["additionalProperties"] is False and ajustement["required"] == ["ajustement"]
    interne = ajustement["properties"]["ajustement"]
    assert interne["additionalProperties"] is False
    assert interne["properties"]["quantite_apres"]["minimum"] == 0
    lecture = m6["m6_lire_alertes_approvisionnement"].parametres
    assert lecture["additionalProperties"] is False and lecture["required"] == []
    assert lecture["properties"]["decalage"]["minimum"] == 0
    assert lecture["properties"]["limite"]["minimum"] == 1 and lecture["properties"]["limite"]["maximum"] == 100


def test_l_outil_de_lecture_est_n0_agent_seulement(m6):
    outil = m6["m6_lire_alertes_approvisionnement"]
    assert (outil.autonomie, outil.niveau_effectif) == (Autonomie.T0, Niveau.N0)
    assert not outil.roles_appareil


def test_le_constat_ecrit_un_instantane_et_le_rejeu_ne_grandit_pas_le_registre(base, m6, monkeypatch):
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    monkeypatch.setattr(
        aide.m6_outils, "_configuration_alertes", lambda: {"fenetre_jours": 30, "seuil_repetition": 2})
    parametres = {"horodatage": "2026-10-20T12:00:00-04:00"}
    premier = executer_atomique(m6["m6_constater_disponibilite"], parametres)
    assert premier["ok"] is True and premier["resultat"]["accepte"] is True
    taille = len(_maillons("alertes_approvisionnement"))
    assert taille == 1
    second = executer_atomique(m6["m6_constater_disponibilite"], parametres)
    assert second["ok"] is True
    assert len(_maillons("alertes_approvisionnement")) == 1
    lecture = executer_atomique(m6["m6_lire_alertes_approvisionnement"], {})
    assert lecture["ok"] is True and lecture["resultat"]["accepte"] is True
    assert lecture["resultat"]["resultat"]["constate_le"] == "2026-10-20T12:00:00-04:00"


def _maillons(nom):
    with stockage.transaction():
        return list(stockage.maillons(aide._DEPARTEMENT, nom))


def test_l_equipe_par_wct_est_lue_a_la_charge_et_ignore_les_identifiants_invalides(monkeypatch):
    charges = {
        "wct-ok": {"technicien_id": "eq-fictive"},
        "wct-sans-equipe": {"technicien_id": None},
        "wct-equipe-non-textuelle": {"technicien_id": 3},
    }
    monkeypatch.setattr(aide.m6_outils.evenements, "charge_publiee",
                        lambda type_evenement, wct_id: charges.get(wct_id))
    assert aide.m6_outils._equipes_par_wct([
        {"wct_id": "wct-ok"}, {"wct_id": "wct-sans-equipe"}, {"wct_id": "wct-equipe-non-textuelle"},
        {"wct_id": ""}, {"wct_id": 3}, {"wct_id": "wct-inconnu"},
    ]) == {"wct-ok": "eq-fictive"}
    monkeypatch.setattr(aide.m6_outils.evenements, "charge_publiee",
                        lambda type_evenement, wct_id: {"technicien_id": "eq-fictive"})
    assert aide.m6_outils._equipes_par_wct([{"wct_id": ""}, {"wct_id": 3}, {"wct_id": None}]) == {}


def test_les_equipes_declarees_sont_des_identifiants_textuels_ou_rien(monkeypatch):
    monkeypatch.setattr(aide.m6_outils.equipes_entreprise, "charger_equipes", lambda: (None, {"code": "X"}))
    assert aide.m6_outils._equipes_declarees() is None
    monkeypatch.setattr(aide.m6_outils.equipes_entreprise, "charger_equipes",
                        lambda: ({"liste": "pas-une-liste"}, None))
    assert aide.m6_outils._equipes_declarees() is None
    monkeypatch.setattr(aide.m6_outils.equipes_entreprise, "charger_equipes",
                        lambda: ({"liste": [{"id": "eq-fictive"}, {"id": ""}, "x", {"id": 3}]}, None))
    assert aide.m6_outils._equipes_declarees() == {"eq-fictive"}


def test_un_instantane_est_idempotent_par_instant_et_se_chaine_au_precedent(base):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    instant = datetime(2026, 10, 20, 12, 0, tzinfo=ZoneInfo("America/Montreal"))
    with stockage.transaction():
        premier = aide.m6_outils._alertes_instantane(instant)
        second = aide.m6_outils._alertes_instantane(instant)
    assert premier["deja_constate"] is False and second["deja_constate"] is True
    assert len(_maillons("alertes_approvisionnement")) == 1
    suivant = instant + timedelta(hours=12)
    with stockage.transaction():
        troisieme = aide.m6_outils._alertes_instantane(suivant)
    assert troisieme["deja_constate"] is False
    maillons = _maillons("alertes_approvisionnement")
    assert len(maillons) == 2 and maillons[1]["hash_precedent"] == maillons[0]["hash_maillon"]


def test_les_attentes_d_alertes_plafonnent_a_vingt_et_portent_le_bon_identifiant(base):
    alertes_factices = [
        {"type": "items_manquants_repetes_equipe", "equipe_id": "EQ-FICT", "compte": 2, "seuil": 2},
        {"type": "declaration_usage_manquante", "wct_id": "WCT-FICT", "intervention_id": "int",
         "jours_depuis_completion": 1},
        {"type": "reception_po_en_retard", "po_id": "PO-FICT", "fournisseur_id": "FOURN", "jours_depuis_envoi": 9,
         "delai_habituel_jours": 5},
    ] + [
        {"type": "commande_recue_stock_disparu", "materiau_id": f"M-{i}", "quantite_recue": "1", "stock_actuel": "0"}
        for i in range(18)
    ]
    instantane = _instantane_factice(len(alertes_factices), non_evaluees=[{"type": "t", "cle": "k", "action": "a"}])
    instantane["alertes"] = alertes_factices
    instantane["constate_le"] = "2026-10-20T12:00:00-04:00"
    with stockage.transaction():
        stockage.maillons(aide._DEPARTEMENT, "alertes_approvisionnement").append(instantane)
    with stockage.transaction():
        attentes = aide.m6_outils._attentes_alertes()
    alertes_attentes = [a for a in attentes if a["type"] == "alerte_approvisionnement"]
    assert len(alertes_attentes) == 20, "vingt au plus, jamais vingt et une"
    assert all(a["depuis"] == "2026-10-20T12:00:00-04:00" for a in attentes)
    ids = {a["id"] for a in alertes_attentes}
    assert "alerte_approvisionnement:items_manquants_repetes_equipe:EQ-FICT" in ids
    assert "alerte_approvisionnement:declaration_usage_manquante:WCT-FICT" in ids
    assert "alerte_approvisionnement:reception_po_en_retard:PO-FICT" in ids
    assert any(a["type"] == "alertes_a_configurer" for a in attentes)


def test_un_constat_avec_identite_refusee_n_est_jamais_accepte(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_acteur_admin_ou_agent",
                        lambda: (None, {"code": "REJ-IDENTITE-APPAREIL-INVALIDE"}))
    with stockage.transaction():
        reponse = aide.m6_outils.constater_disponibilite("2026-10-20T12:00:00-04:00")
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


def _instantane_factice(nombre_alertes=3, non_evaluees=None, comptes=None):
    return {
        "constat_id": "m6-alertes-fictif", "constate_le": "2026-10-20T12:00:00-04:00",
        "date_reference": "2026-10-20", "version_donnees": "a" * 16,
        "alertes": [{"type": "t", "n": i} for i in range(nombre_alertes)],
        "non_evaluees": non_evaluees if non_evaluees is not None else [],
        "comptes": comptes if comptes is not None else {},
        "hash_precedent": "", "hash_maillon": "b" * 64,
    }


def _lire(m6, arguments=None):
    reponse = executer_atomique(m6["m6_lire_alertes_approvisionnement"], arguments or {})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def test_lire_sans_constat_rend_null_et_jamais_un_tout_va_bien(base, m6):
    lecture = _lire(m6)
    assert lecture["accepte"] is True and lecture["resultat"]["constat"] is None
    assert lecture["resultat"]["tronque"] is False


def test_lire_pagine_au_defaut_vingt_et_dit_la_troncature(base, m6):
    with stockage.transaction():
        stockage.maillons(aide._DEPARTEMENT, "alertes_approvisionnement").append(_instantane_factice(21))
    lecture = _lire(m6)
    assert len(lecture["resultat"]["alertes"]) == 20 and lecture["resultat"]["tronque"] is True
    page = _lire(m6, {"decalage": 1, "limite": 2})["resultat"]
    assert [a["n"] for a in page["alertes"]] == [1, 2] and page["tronque"] is True
    fin = _lire(m6, {"decalage": 20, "limite": 2})["resultat"]
    assert [a["n"] for a in fin["alertes"]] == [20] and fin["tronque"] is False
    exact = _lire(m6, {"decalage": 0, "limite": 21})["resultat"]
    assert len(exact["alertes"]) == 21 and exact["tronque"] is False


def test_lire_rend_les_regles_non_evaluees_et_les_comptes(base, m6):
    with stockage.transaction():
        stockage.maillons(aide._DEPARTEMENT, "alertes_approvisionnement").append(
            _instantane_factice(1, non_evaluees=[{"type": "t", "cle": "k", "action": "a"}], comptes={"t": 1}))
    resultat = _lire(m6)["resultat"]
    assert resultat["non_evaluees"] == [{"type": "t", "cle": "k", "action": "a"}]
    assert resultat["comptes"] == {"t": 1}


def test_lire_refuse_une_pagination_invalide(base, m6):
    for arguments in ({"decalage": -1}, {"decalage": True}, {"decalage": "0"}, {"limite": 0}, {"limite": 101},
                      {"limite": True}, {"limite": "2"}):
        with stockage.transaction():
            lecture = aide.m6_outils.lire_alertes_approvisionnement(**arguments)
        assert lecture["accepte"] is False, arguments
        assert lecture["verdict"]["code"] == "REJ-ALERTES-PAGINATION-INVALIDE", arguments
    assert _lire(m6, {"decalage": 0, "limite": 1})["accepte"] is True
    assert _lire(m6, {"decalage": 0, "limite": 100})["accepte"] is True
