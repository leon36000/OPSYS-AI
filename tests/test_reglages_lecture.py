"""Réglages de direction (CFG-1) : la couche de lecture UNIQUE et sa précédence — valeur adoptée > fichier > absence.

Prouve : sans rien d'adopté, la valeur du fichier est rendue TELLE QUELLE (même objet : aucun changement de
comportement) ; une valeur adoptée l'emporte sur celle du fichier, une clé du fichier non déclarée reste ; la valeur
du fichier reste valable tant que rien ne la remplace, et revient après un retour arrière ; le réglage non déclaré
par le manifeste du département qui lit n'est jamais servi ; hors transaction, chaîne cassée ou valeur devenue
incompatible avec la déclaration, rien d'adopté n'est servi (on retombe sur le fichier, puis l'absence) ; une
proposition n'est lue par aucun département ; l'état pour la direction dit ce qui manque, d'où vient chaque valeur et
ce que ça bloque. Données fictives.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select, update

from opsys import stockage
from opsys.reglages import lecture, magasin
from opsys.stockage.schema import REGISTRES

_spec = importlib.util.spec_from_file_location("reglages_aide", Path(__file__).with_name("reglages_aide.py"))
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)

FICTIF = True
QUAND = "2026-11-02T15:00:00+00:00"
SEGMENTS = ("configuration", "segments")


@pytest.fixture
def deps(tmp_path, monkeypatch):
    yield aide.installer(tmp_path, monkeypatch)
    stockage.liberer()


def _donnees(departement="m02-revenue-crm", **configuration):
    """Le manifeste réel du département, avec la `configuration` donnée (le fichier du propriétaire)."""
    from opsys.departements import racine_departements

    donnees = yaml.safe_load((racine_departements() / departement / "department.yaml").read_text(encoding="utf-8"))
    donnees["configuration"] = configuration
    return donnees


def _adopter(deps, cle, valeur, **plus):
    reglage = next(r for d in deps.values() for r in d.reglages if r.cle == cle)
    return magasin.adopter(stockage.connexion_courante(), reglage, valeur, par="owner.fictif", role="nathan_owner",
                           approbation_id="demande-1", raison="Décision de départ", quand=QUAND, **plus)


def _revenir(deps, cle):
    reglage = next(r for d in deps.values() for r in d.reglages if r.cle == cle)
    return magasin.revenir(stockage.connexion_courante(), reglage, par="owner.fictif", role="nathan_owner",
                           approbation_id="demande-2", raison="Retour au départ", quand=QUAND)


def test_sans_rien_d_adopte_le_fichier_est_rendu_tel_quel_meme_objet(deps):
    donnees = _donnees(segments={"jours_inactivite_dormant": 45})
    fichier = donnees["configuration"]["segments"]
    with stockage.transaction():
        assert lecture.superposer(donnees, SEGMENTS, fichier) is fichier
        assert lecture.superposer(donnees, ("configuration", "relances"), None) is None
        vide = {}
        assert lecture.superposer(_donnees(), SEGMENTS, vide) is vide


def test_une_valeur_adoptee_l_emporte_sur_celle_du_fichier_et_laisse_le_reste(deps):
    donnees = _donnees(segments={"jours_inactivite_dormant": 45, "cle_du_proprietaire": "intacte"})
    fichier = copy.deepcopy(donnees["configuration"]["segments"])
    with stockage.transaction():
        _adopter(deps, "m2.jours_inactivite_dormant", 30)
        _adopter(deps, "m2.jours_soumission_perimee", 14)
        servi = lecture.superposer(donnees, SEGMENTS, donnees["configuration"]["segments"])
    assert servi == {"jours_inactivite_dormant": 30, "cle_du_proprietaire": "intacte", "jours_soumission_perimee": 14}
    assert donnees["configuration"]["segments"] == fichier, "l'objet du fichier n'est jamais modifié"


def test_la_valeur_du_fichier_reste_valable_tant_que_rien_ne_la_remplace_et_revient_apres_le_retour_arriere(deps):
    donnees = _donnees(relances={"jours_entre_relances": 21})
    chemin = ("configuration", "relances")
    with stockage.transaction():
        assert lecture.superposer(donnees, chemin, donnees["configuration"]["relances"]) == {"jours_entre_relances": 21}
        _adopter(deps, "m2.jours_entre_relances", 7)
        assert lecture.superposer(donnees, chemin, donnees["configuration"]["relances"]) == {"jours_entre_relances": 7}
        _revenir(deps, "m2.jours_entre_relances")
        assert lecture.superposer(donnees, chemin, donnees["configuration"]["relances"]) == {"jours_entre_relances": 21}


def test_un_bloc_vide_ou_absent_du_fichier_est_complete_par_la_valeur_adoptee(deps):
    with stockage.transaction():
        _adopter(deps, "m2.jours_entre_relances", 7)
        assert lecture.superposer(_donnees(), ("configuration", "relances"), None) == {"jours_entre_relances": 7}
        assert lecture.superposer(_donnees(), ("configuration", "relances"), {}) == {"jours_entre_relances": 7}


def test_la_valeur_adoptee_est_rendue_dans_son_type_pour_le_departement(deps):
    with stockage.transaction():
        _adopter(deps, "m2.bandes_valeur_cents", [500000, 1500000, 4000000])
        servi = lecture.superposer(_donnees(), ("configuration", "scoring"), None)
    assert servi == {"bandes_valeur_cents": [500000, 1500000, 4000000]}
    assert all(type(v) is int for v in servi["bandes_valeur_cents"])


def test_m8_la_configuration_entiere_est_completee_au_chemin_imbrique(deps):
    donnees = _donnees("m08-analytics", seuils_alerte={"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 20}},
                       sante={})
    with stockage.transaction():
        _adopter(deps, "m8.bornes_taux_acceptation_pct", {"pire": 20, "cible": "60"})
        servi = lecture.superposer(donnees, ("configuration",), donnees["configuration"])
    assert servi["seuils_alerte"] == donnees["configuration"]["seuils_alerte"]
    assert servi["sante"] == {"bornes": {"m8_taux_acceptation_pct": {"pire": "20", "cible": "60"}}}


def test_un_reglage_non_declare_par_le_manifeste_qui_lit_n_est_jamais_servi(deps):
    donnees = _donnees()
    sans_declaration = {k: v for k, v in donnees.items() if k != "reglages"}
    autre_departement = _donnees("m08-analytics")
    with stockage.transaction():
        _adopter(deps, "m2.jours_entre_relances", 7)
        bloc = ("configuration", "relances")
        assert lecture.superposer(sans_declaration, bloc, None) is None
        assert lecture.superposer(autre_departement, bloc, None) is None
        assert lecture.superposer(None, bloc, None) is None
        assert lecture.superposer("pas un manifeste", bloc, None) is None
        # le manifeste du bon département, lui, le sert
        assert lecture.superposer(donnees, bloc, None) == {"jours_entre_relances": 7}


def test_une_declaration_illisible_dans_le_manifeste_ne_sert_rien(deps):
    donnees = _donnees()
    donnees["reglages"][0]["niveau"] = "N4"
    with stockage.transaction():
        _adopter(deps, "m2.jours_entre_relances", 7)
        assert lecture.superposer(donnees, ("configuration", "relances"), None) is None


def test_une_proposition_n_est_lue_par_aucun_departement(deps):
    with stockage.transaction():
        for bloc in (("configuration", "segments"), ("configuration", "relances"), ("configuration", "scoring")):
            assert lecture.superposer(_donnees(), bloc, None) is None
        assert lecture.adoptees().valeurs == {}


def test_hors_transaction_aucune_valeur_adoptee_n_est_lisible(deps):
    with stockage.transaction():
        _adopter(deps, "m2.jours_entre_relances", 7)
    assert stockage.connexion_courante() is None
    assert lecture.superposer(_donnees(), ("configuration", "relances"), None) is None
    lues = lecture.adoptees()
    assert lues.lisible is False and lues.valeurs == {}


def test_une_chaine_cassee_ne_sert_aucune_valeur_adoptee_meme_les_saines(deps):
    donnees = _donnees(relances={"jours_entre_relances": 21})
    with stockage.transaction() as cnx:
        _adopter(deps, "m2.jours_entre_relances", 7)
        _adopter(deps, "m2.jours_soumission_perimee", 14)
        ligne = cnx.execute(select(REGISTRES.c.maillon).where(
            (REGISTRES.c.departement == magasin.DEPARTEMENT_STOCKAGE) & (REGISTRES.c.rang == 1))).scalar_one()
        maillon = json.loads(ligne)
        maillon["raison"] = "falsifiée"
        cnx.execute(update(REGISTRES).where(
            (REGISTRES.c.departement == magasin.DEPARTEMENT_STOCKAGE) & (REGISTRES.c.rang == 1)).values(
            maillon=json.dumps(maillon, ensure_ascii=False, separators=(",", ":"))))
        fichier = donnees["configuration"]["relances"]
        assert lecture.superposer(donnees, ("configuration", "relances"), fichier) is fichier
        assert lecture.superposer(donnees, SEGMENTS, None) is None
        assert lecture.adoptees().chaine_valide is False
        assert lecture.journal() == []
        assert lecture.etat_des_reglages(deps)["chaine"]["valide"] is False


def test_une_valeur_devenue_incompatible_avec_la_declaration_n_est_plus_servie(deps):
    with stockage.transaction():
        _adopter(deps, "m2.jours_entre_relances", 400)
        donnees = _donnees()
        assert lecture.superposer(donnees, ("configuration", "relances"), None) == {"jours_entre_relances": 400}
        donnees["reglages"][2]["max"] = 365  # la déclaration se resserre depuis l'adoption
        assert lecture.superposer(donnees, ("configuration", "relances"), None) is None


def test_un_bloc_illisible_du_fichier_est_remplace_par_la_valeur_adoptee_et_inchange_sinon(deps):
    donnees = _donnees(segments=5)
    with stockage.transaction():
        assert lecture.superposer(donnees, SEGMENTS, 5) == 5  # rien d'adopté : le département dit « invalide » lui-même
        _adopter(deps, "m2.jours_inactivite_dormant", 30)
        assert lecture.superposer(donnees, SEGMENTS, 5) == {"jours_inactivite_dormant": 30}


@pytest.mark.parametrize("illisible", [5, "texte", ["liste"], {"bornes": 7}, {"bornes": ["x"]}])
def test_un_intermediaire_illisible_du_fichier_est_remplace_par_la_valeur_adoptee_au_chemin_imbrique(deps, illisible):
    donnees = _donnees("m08-analytics", sante=illisible, seuils_alerte={"garde": "intacte"})
    with stockage.transaction():
        assert lecture.superposer(donnees, ("configuration",), donnees["configuration"]) is donnees["configuration"]
        _adopter(deps, "m8.bornes_taux_acceptation_pct", {"pire": 20, "cible": 60})
        servi = lecture.superposer(donnees, ("configuration",), donnees["configuration"])
    assert servi["sante"] == {"bornes": {"m8_taux_acceptation_pct": {"pire": "20", "cible": "60"}}}
    assert servi["seuils_alerte"] == {"garde": "intacte"}


def test_une_base_sans_le_registre_ne_sert_rien_et_ne_casse_pas_la_transaction(tmp_path, monkeypatch):
    from sqlalchemy import text

    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'vide.db'}")
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    stockage.liberer()
    with stockage.transaction() as cnx:
        lues = lecture.adoptees()
        assert lues.lisible is False and lues.valeurs == {} and "non migrée" in lues.detail
        assert lecture.superposer(_donnees(), ("configuration", "relances"), None) is None
        assert cnx.execute(text("select 1")).scalar_one() == 1
    stockage.liberer()


# -- l'état pour la direction ---------------------------------------------------------------------------------
def test_etat_a_la_livraison_tout_manque_avec_proposition_sourcee_et_ce_que_ca_bloque(deps):
    with stockage.transaction():
        etat = lecture.etat_des_reglages(deps)
    # 28 réglages vides (M2, M8 dont six seuils d'alerte, M5, M9) + 2 de M6 (C3) déjà valorisés à department.yaml.
    assert etat["total"] == 34 and etat["manquants"] == 31 and etat["chaine"]["valide"] is True
    par_cle = {r["cle"]: r for r in etat["reglages"]}
    relances = par_cle["m2.jours_entre_relances"]
    assert relances["statut"] == "vide" and relances["manque"] is True and relances["valeur"] is None
    assert relances["proposition"]["valeur"] == 7
    assert relances["proposition"]["etiquette"] == "recommandation, non validée"
    assert "REJ-RELANCES-A-CONFIGURER" in relances["debloque"] and relances["niveau"] == "N3"
    assert relances["bornes"] == {"min": "1", "max": "3650"} and relances["version"] == 0
    assert par_cle["m2.bandes_valeur_cents"]["proposition"] is None
    assert par_cle["m2.bandes_valeur_cents"]["bornes"]["longueur"] == 3
    for cle in ("m6.seuil_variance_chantier_pourcentage", "m6.seuil_ecart_prix_reception_pourcentage"):
        seuil = par_cle[cle]
        assert seuil["statut"] == "fichier" and seuil["manque"] is False and seuil["niveau"] == "N3"
        assert seuil["proposition"]["etiquette"] == "recommandation, non validée"
        assert seuil["proposition"]["valeur"] in ("0.3", "0.15")
    assert all("INDÉTERMINÉ" in r["debloque"] for r in etat["reglages"] if r["cle"].startswith("m8.bornes_"))
    # les six seuils d'alerte métier (C3) disent ce qu'ils débloquent : sans eux, la règle est non évaluée
    seuils = [r for r in etat["reglages"] if r["cle"].startswith("m8.seuil_alerte_")]
    assert len(seuils) == 6 and all("non évaluée" in r["debloque"] or "ALERTE-" in r["debloque"] for r in seuils)
    assert all(r["proposition"] is None for r in etat["reglages"] if r["departement"] == "m08-analytics")


def test_etat_distingue_adopte_fichier_vide_et_fichier_invalide(deps, monkeypatch, tmp_path):
    chemin = aide.manifeste_avec(tmp_path, "m02-revenue-crm", lambda d: d.update(configuration={
        "segments": {"jours_inactivite_dormant": 45, "jours_soumission_perimee": 99999},
        "relances": {}, "scoring": {"bandes_valeur_cents": [3, 2, 1]}}))
    # le lecteur d'état lit le manifeste du dossier du département : on le remplace par la copie modifiée
    racine = tmp_path / "m02-revenue-crm"
    racine.mkdir()
    (racine / "department.yaml").write_text(chemin.read_text(encoding="utf-8"), encoding="utf-8")
    dep = deps["m02-revenue-crm"]
    import dataclasses

    deps_modif = {**deps, "m02-revenue-crm": dataclasses.replace(dep, racine=racine)}
    with stockage.transaction():
        _adopter(deps, "m2.jours_entre_relances", 7)
        etat = lecture.etat_des_reglages(deps_modif, departement="m02-revenue-crm")
    par_cle = {r["cle"]: r for r in etat["reglages"]}
    dormant = par_cle["m2.jours_inactivite_dormant"]
    assert dormant["statut"] == "fichier" and dormant["valeur"] == 45
    assert par_cle["m2.jours_soumission_perimee"]["statut"] == "fichier_invalide"
    assert par_cle["m2.jours_soumission_perimee"]["manque"] is True
    assert par_cle["m2.jours_soumission_perimee"]["valeur_fichier_illisible"] == "99999"
    entre = par_cle["m2.jours_entre_relances"]
    assert entre["statut"] == "adopte" and entre["valeur"] == 7
    assert par_cle["m2.bandes_valeur_cents"]["statut"] == "fichier_invalide"
    assert etat["total"] == 4 and etat["manquants"] == 2


def test_etat_d_un_reglage_adopte_dit_qui_quand_et_la_version(deps):
    with stockage.transaction():
        _adopter(deps, "m2.jours_entre_relances", 7)
        _adopter(deps, "m2.jours_entre_relances", 10)
        etat = lecture.etat_des_reglages(deps, departement="m02-revenue-crm")
    r = next(x for x in etat["reglages"] if x["cle"] == "m2.jours_entre_relances")
    assert (r["statut"], r["valeur"], r["version"], r["adopte_par"], r["adopte_le"]) == (
        "adopte", 10, 2, "owner.fictif", QUAND)
    assert etat["total"] == 4 and etat["manquants"] == 3


def test_le_journal_rend_les_derniers_gestes_du_plus_recent_au_plus_ancien(deps):
    with stockage.transaction():
        for jours in (7, 8, 9):
            _adopter(deps, "m2.jours_entre_relances", jours)
        journal = lecture.journal(limite=2)
    assert [m["nouvelle_valeur"] for m in journal] == [9, 8]
