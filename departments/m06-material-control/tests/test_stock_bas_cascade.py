"""Stock bas et besoin de commande à « travaux terminés » (M6.15, PLAN T1.5-d), par le registre durable
et le vrai bus (DEFINITION-PRODUIT.md §6, ligne M6 : « ajuste le stock, signale le stock bas, crée le
besoin de commande »).

Ce que ce fichier prouve, de bout en bout côté M6 :
- la déclaration de matériaux utilisés, qui sort du stock, évalue chaque article touché contre SON seuil
  (`department.yaml/configuration/reapprovisionnement/articles`, lu à chaque appel) ;
- sous le seuil : un constat `besoin_commande` au registre `besoins_commande`, idempotent par article et
  événement déclencheur, et une attente pour l'admin (`attentes()`, lue par `approbations.file_proprietaire`
  comme par l'app admin) ;
- article sans paramètres, ou aux paramètres invalides : « seuil non configuré », jamais un seuil deviné, et
  la déclaration de l'employé n'en est jamais refusée ;
- JAMAIS de bon de commande, de fournisseur, de prix, d'événement ni de mouvement créé par ce chemin ;
- l'attente est l'état d'AUJOURD'HUI : une réception qui reconstitue le stock, ou un seuil renseigné après
  coup, la fait disparaître ou apparaître sans attendre le chantier suivant.

Base SQLite temporaire migrée (ADR-0009). La configuration de test est un `department.yaml` de remplacement
(`_MANIFESTE`), comme `test_evenements_m6.py` : le vrai manifeste est laissé vide à dessein (aucun seuil
inventé) et un test le garde. Fixtures fictives : les identifiants portent « fictif ».
"""

from __future__ import annotations

import ast
from pathlib import Path

import m6_material_control.outils as outils_mod
import pytest
import yaml
from m6_material_control.outils import outils
from sqlalchemy import select

from opsys import approbations, departements, evenements, stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

_DEPT = "m06-material-control"
GOUTTIERE = "gouttiere-alu-5po-fictif"
VIS = "vis-inox-fictif"
JOINT = "joint-silicone-fictif"
CHANTIER = "CH-STOCK-BAS-fictif"
ARTICLES = {
    GOUTTIERE: {"seuil_reapprovisionnement": 150, "quantite_cible": 300},
    VIS: {"seuil_reapprovisionnement": 10, "quantite_cible": 20},
}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def m6():
    return {o.nom: o for o in outils()}


def _configurer(monkeypatch, tmp_path, articles=None, *, bloc=None):
    """Remplace le manifeste lu par M6 : le seuil de variance reste (il sert à la même transaction), le
    bloc de réapprovisionnement est celui du test (`articles`), ou brut (`bloc`), ou absent (les deux None)."""
    configuration = {"seuil_variance_chantier_pourcentage": 0.3}
    if bloc is not None:
        configuration["reapprovisionnement"] = bloc
    elif articles is not None:
        configuration["reapprovisionnement"] = {"articles": articles}
    chemin = tmp_path / "department-m6.yaml"
    chemin.write_text(
        yaml.safe_dump({"schema": "opsys.departement/v1", "configuration": configuration}, allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(outils_mod, "_MANIFESTE", chemin)


def _wct_charge(wct_id, intervention_id, devis_id="DEVIS-STOCK-fictif", **plus):
    base = {
        "wct_id": wct_id, "intervention_id": intervention_id, "lead_id": "lead-fictif",
        "technicien_id": "t1", "horodatage_completion": "2026-09-15T12:00:00+00:00",
        "fix_gps_completion": {"latitude": 45.5, "longitude": -73.5},
        "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None,
        "hash_maillon": "a" * 16, "consommateurs_cibles": ["M6"], "devis_id": devis_id,
        "statut": "completed_pending_review",
    }
    return {**base, **plus}


def _publier_wct(wct_id, intervention_id="int-fictif", **plus):
    """Ce que M4 fait en complétant : publie `m4.travaux_termines` avec `evenement_id = wct_id`."""
    with stockage.transaction():
        evenements.publier(
            "m4.travaux_termines", "m04-field-ops", _wct_charge(wct_id, intervention_id, **plus),
            evenement_id=wct_id,
        )


def _receptionner(m6, materiau_id, quantite, po_id, chantier_id=CHANTIER):
    reponse = executer_atomique(m6["m6_receptionner_commande"], {
        "bon_demande": {
            "po_id": po_id, "chantier_id": chantier_id,
            "lignes_demandees": [{"materiau_id": materiau_id, "quantite_demandee": quantite}],
            "horodatage": "2026-09-01T00:00:00Z",
        },
        "reception_po": {
            "po_id": po_id, "chantier_id": chantier_id,
            "lignes_recues": [{"materiau_id": materiau_id, "quantite_recue": quantite}],
            "horodatage": "2026-09-02T00:00:00Z",
        },
        "catalogue_materiaux": {
            "version": "v1-fictif", "unite_monetaire": "CAD",
            "postes": {materiau_id: {"cout_unitaire": 5.0, "libelle": materiau_id}},
        },
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _ligne(type_ligne, materiau_id, quantite, unite="pi"):
    ligne = {"type_ligne": type_ligne, "materiau_id": materiau_id, "quantite": quantite, "unite": unite}
    if type_ligne == "prevu":
        ligne["quantite_estimee"] = quantite
    return ligne


def _declarer(m6, wct_id, lignes, intervention_id="int-fictif", chantier_id=CHANTIER, publier=True):
    if publier:
        _publier_wct(wct_id, intervention_id)
    reponse = executer_atomique(m6["m6_declarer_materiaux_utilises"], {
        "wct_id": wct_id,
        "formulaire": {"wct_id": wct_id, "intervention_id": intervention_id, "chantier_id": chantier_id,
                       "lignes_materiaux": lignes},
    })
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _constats():
    with stockage.transaction():
        return list(stockage.maillons(_DEPT, "besoins_commande"))


def _attentes():
    with stockage.transaction():
        return outils_mod.attentes()


def _registre(nom):
    with stockage.transaction():
        return list(stockage.maillons(_DEPT, nom))


def _types_publies():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.type_evenement)).all()
    return {ligne.type_evenement for ligne in lignes}


# -- la règle, de la déclaration au constat ------------------------------------------------------------
def test_declaration_qui_laisse_le_stock_sous_le_seuil_cree_un_besoin_de_commande(
    base_durable, m6, monkeypatch, tmp_path
):
    _configurer(monkeypatch, tmp_path, ARTICLES)
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")

    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 56.0)])  # 200 - 56 = 144 < 150

    assert _constats() == [{
        "type_entree": "besoin_commande", "constat_id": f"besoin_commande:{GOUTTIERE}:wct-1",
        "materiau_id": GOUTTIERE, "evenement_declencheur": "wct-1", "chantier_id": CHANTIER, "unite": "pi",
        "horodatage": "2026-09-15T12:00:00+00:00", "stock_theorique": "144.0",
        "seuil_reapprovisionnement": "150", "quantite_cible": "300", "quantite_a_commander": "156.0",
        "stock_negatif": False,
    }]
    (attente,) = _attentes()
    assert attente["type"] == "besoin_commande" and attente["niveau"] == "N2"
    assert attente["id"] == f"besoin_commande:{GOUTTIERE}"
    assert attente["depuis"] == "2026-09-15T12:00:00+00:00"
    assert "144.0 pi en main, sous le seuil de 150 pi" in attente["resume"]
    assert "besoin de commande : 156.0 pi pour atteindre 300 pi" in attente["resume"]


def test_stock_au_dessus_du_seuil_ou_egal_au_seuil_ne_signale_rien(base_durable, m6, monkeypatch, tmp_path):
    _configurer(monkeypatch, tmp_path, ARTICLES)
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")
    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 42.0)])  # 158 >= 150
    _receptionner(m6, GOUTTIERE, 200.0, "PO-2-fictif", chantier_id="CH-AUTRE-fictif")
    _declarer(m6, "wct-2", [_ligne("prevu", GOUTTIERE, 208.0)], chantier_id="CH-AUTRE-fictif")  # 150 == seuil

    assert _constats() == []
    assert _attentes() == []


def test_la_reponse_de_l_employe_n_apprend_rien_du_stock_ni_du_besoin(base_durable, m6, monkeypatch, tmp_path):
    _configurer(monkeypatch, tmp_path, ARTICLES)
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")

    reponse = _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 56.0)])

    assert set(reponse) == {"accepte", "resultat", "registre"}
    assert "besoin" not in str(reponse).lower() and "seuil" not in str(reponse).lower()


def test_plusieurs_articles_touches_un_constat_par_article_a_dire_et_un_seul_pour_deux_lignes(
    base_durable, m6, monkeypatch, tmp_path
):
    _configurer(monkeypatch, tmp_path, {
        GOUTTIERE: {"seuil_reapprovisionnement": 50, "quantite_cible": 100}, VIS: ARTICLES[VIS]})
    for materiau_id in (GOUTTIERE, VIS, JOINT):
        _receptionner(m6, materiau_id, 100.0, f"PO-{materiau_id}")

    _declarer(m6, "wct-1", [
        _ligne("prevu", GOUTTIERE, 70.0), _ligne("perte", GOUTTIERE, 3.0),  # 27 < 50 : deux lignes, un article
        _ligne("prevu", VIS, 5.0),  # 95 >= 10
        _ligne("non_prevu", JOINT, 5.0),  # aucun paramètre
    ])

    par_id = {c["constat_id"]: c for c in _constats()}
    assert set(par_id) == {f"besoin_commande:{GOUTTIERE}:wct-1", f"seuil_a_configurer:{JOINT}:wct-1"}
    besoin = par_id[f"besoin_commande:{GOUTTIERE}:wct-1"]
    assert (besoin["stock_theorique"], besoin["quantite_a_commander"]) == ("27.0", "73.0")
    assert par_id[f"seuil_a_configurer:{JOINT}:wct-1"]["motif"] == "seuil_absent"
    assert {a["type"] for a in _attentes()} == {"besoin_commande", "seuil_a_configurer"}


def test_un_retour_qui_ne_suffit_pas_a_rehausser_le_stock_est_constate_comme_les_autres(
    base_durable, m6, monkeypatch, tmp_path
):
    _configurer(monkeypatch, tmp_path, ARTICLES)
    _receptionner(m6, GOUTTIERE, 100.0, "PO-1-fictif")

    _declarer(m6, "wct-1", [_ligne("retour", GOUTTIERE, 5.0)])  # 105 < 150 : l'article est touché

    (constat,) = _constats()
    assert constat["type_entree"] == "besoin_commande" and constat["stock_theorique"] == "105.0"
    assert constat["quantite_a_commander"] == "195.0"


def test_le_stock_de_l_article_compte_tous_les_lieux(base_durable, m6, monkeypatch, tmp_path):
    _configurer(monkeypatch, tmp_path, ARTICLES)
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")
    _receptionner(m6, GOUTTIERE, 30.0, "PO-2-fictif", chantier_id="DEPOT-fictif")

    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 90.0)])  # 200 - 90 + 30 = 140 < 150

    (constat,) = _constats()
    assert constat["stock_theorique"] == "140.0" and constat["chantier_id"] == CHANTIER


def test_stock_theorique_negatif_est_signale_sans_quantite_a_commander(base_durable, m6, monkeypatch, tmp_path):
    _configurer(monkeypatch, tmp_path, ARTICLES)
    _receptionner(m6, GOUTTIERE, 40.0, "PO-1-fictif")

    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 56.0)])  # 40 - 56 = -16 : la déclaration est acceptée

    (constat,) = _constats()
    assert constat["stock_negatif"] is True and constat["quantite_a_commander"] is None
    (attente,) = _attentes()
    assert "stock théorique négatif (-16.0 pi)" in attente["resume"] and "besoin de commande :" not in attente["resume"]


# -- seuil non configuré : visible, jamais deviné -------------------------------------------------------
def test_article_sans_seuil_est_signale_non_configure_sans_jamais_evaluer_de_seuil(
    base_durable, m6, monkeypatch, tmp_path
):
    _configurer(monkeypatch, tmp_path, {})
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")

    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 199.0)])  # stock 1 : aucun seuil ne permet de le juger bas

    (constat,) = _constats()
    assert constat["type_entree"] == "seuil_a_configurer" and constat["motif"] == "seuil_absent"
    assert "seuil_reapprovisionnement" not in constat and "quantite_a_commander" not in constat
    (attente,) = _attentes()
    assert attente["type"] == "seuil_a_configurer" and attente["id"] == "seuils-reapprovisionnement"
    assert GOUTTIERE in attente["resume"] and "non configuré" in attente["resume"]
    assert "quantite_cible" in attente["action_proposee"]


def test_bloc_de_configuration_absent_du_manifeste_vaut_aucun_seuil(base_durable, m6, monkeypatch, tmp_path):
    _configurer(monkeypatch, tmp_path)  # aucun bloc `reapprovisionnement`
    assert outils_mod._articles_reapprovisionnement() == {}
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")

    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 10.0)])

    assert [c["type_entree"] for c in _constats()] == ["seuil_a_configurer"]


@pytest.mark.parametrize(("entree", "code"), [
    ({"seuil_reapprovisionnement": 0, "quantite_cible": 300}, "REJ-REAPPRO-SEUIL-INVALIDE"),
    ({"seuil_reapprovisionnement": 150, "quantite_cible": 100}, "REJ-REAPPRO-CIBLE-INVALIDE"),
    ({"seuil_reapprovisionnement": 150}, "REJ-REAPPRO-ARTICLE-INVALIDE"),
])
def test_configuration_invalide_est_signalee_avec_son_code_et_ne_refuse_jamais_la_declaration(
    base_durable, m6, monkeypatch, tmp_path, entree, code
):
    _configurer(monkeypatch, tmp_path, {GOUTTIERE: entree})
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")

    reponse = _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 56.0)])

    assert reponse["accepte"] is True  # le fait terrain est enregistré, quoi que dise la configuration
    (constat,) = _constats()
    assert (constat["type_entree"], constat["motif"], constat["code"]) == (
        "seuil_a_configurer", "configuration_invalide", code)
    (attente,) = _attentes()
    assert f"{GOUTTIERE} (invalide)" in attente["resume"]


@pytest.mark.parametrize("bloc", [["pas", "un", "dictionnaire"], {"articles": ["liste"]}, "texte"])
def test_bloc_illisible_est_signale_et_ne_refuse_pas_la_declaration(base_durable, m6, monkeypatch, tmp_path, bloc):
    _configurer(monkeypatch, tmp_path, bloc=bloc)
    assert outils_mod._articles_reapprovisionnement() is None
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")

    reponse = _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 56.0)])

    assert reponse["accepte"] is True
    (constat,) = _constats()
    assert constat["motif"] == "configuration_invalide" and constat["code"] == "REJ-REAPPRO-CONFIGURATION-ILLISIBLE"


def test_le_manifeste_reel_n_invente_aucun_seuil():
    assert outils_mod._articles_reapprovisionnement() == {}
    donnees = yaml.safe_load(outils_mod._MANIFESTE.read_text(encoding="utf-8"))
    assert donnees["configuration"]["reapprovisionnement"] == {"articles": {}}


# -- idempotence ---------------------------------------------------------------------------------------
def test_le_constat_est_idempotent_par_article_et_evenement_declencheur(base_durable, m6, monkeypatch, tmp_path):
    _configurer(monkeypatch, tmp_path, ARTICLES)
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")
    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 56.0)])
    lignes = [_ligne("prevu", GOUTTIERE, 56.0)]

    with stockage.transaction():
        deuxieme = outils_mod._constater_stock_des_articles("wct-1", "2026-09-15T12:00:00+00:00", CHANTIER, lignes)
        autre_evenement = outils_mod._constater_stock_des_articles(
            "wct-2", "2026-09-16T12:00:00+00:00", CHANTIER, lignes)

    assert deuxieme == []  # même article, même événement : aucun doublon
    assert [c["constat_id"] for c in autre_evenement] == [f"besoin_commande:{GOUTTIERE}:wct-2"]
    assert len(_constats()) == 2
    (attente,) = _attentes()  # un article, une attente, même constaté deux fois
    assert attente["id"] == f"besoin_commande:{GOUTTIERE}" and attente["depuis"] == "2026-09-16T12:00:00+00:00"


def test_une_seconde_declaration_du_meme_wct_est_refusee_et_ne_constate_rien_de_plus(
    base_durable, m6, monkeypatch, tmp_path
):
    _configurer(monkeypatch, tmp_path, ARTICLES)
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")
    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 56.0)])

    reponse = executer_atomique(m6["m6_declarer_materiaux_utilises"], {
        "wct_id": "wct-1",
        "formulaire": {"wct_id": "wct-1", "intervention_id": "int-fictif", "chantier_id": CHANTIER,
                       "lignes_materiaux": [_ligne("prevu", GOUTTIERE, 1.0)]}})

    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-DECLARATION-DEJA-SOUMISE"
    assert len(_constats()) == 1


def test_hors_transaction_rien_n_est_ecrit_ni_devine(monkeypatch, tmp_path):
    _configurer(monkeypatch, tmp_path, ARTICLES)

    assert outils_mod._constater_stock_des_articles(
        "wct-1", "2026-09-15T12:00:00+00:00", CHANTIER, [_ligne("prevu", GOUTTIERE, 56.0)]) == []


# -- l'état d'aujourd'hui, pas un état figé --------------------------------------------------------------
def test_une_reception_qui_reconstitue_le_stock_efface_le_besoin_sans_nouvelle_declaration(
    base_durable, m6, monkeypatch, tmp_path
):
    _configurer(monkeypatch, tmp_path, ARTICLES)
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")
    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 56.0)])
    assert [a["type"] for a in _attentes()] == ["besoin_commande"]

    _receptionner(m6, GOUTTIERE, 156.0, "PO-2-fictif", chantier_id="DEPOT-fictif")  # 300 en main

    assert _attentes() == []
    assert len(_constats()) == 1  # le constat, lui, reste : l'audit ne s'efface pas


def test_un_seuil_renseigne_apres_coup_transforme_le_signal_a_configurer_en_besoin(
    base_durable, m6, monkeypatch, tmp_path
):
    _configurer(monkeypatch, tmp_path, {})
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")
    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 56.0)])
    assert [a["type"] for a in _attentes()] == ["seuil_a_configurer"]

    _configurer(monkeypatch, tmp_path, ARTICLES)  # Nathan renseigne le seuil

    (attente,) = _attentes()
    assert attente["type"] == "besoin_commande" and "144.0 pi en main" in attente["resume"]
    assert len(_constats()) == 1  # aucun nouveau constat : l'attente est recalculée, rien n'est écrit


def test_lire_les_attentes_n_ecrit_rien(base_durable, m6, monkeypatch, tmp_path):
    _configurer(monkeypatch, tmp_path, ARTICLES)
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")
    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 56.0)])
    avant = (_constats(), _registre("principal"), _registre("bons_commande"))

    _attentes()
    _attentes()

    assert (_constats(), _registre("principal"), _registre("bons_commande")) == avant


# -- constater n'est jamais commander ---------------------------------------------------------------------
def test_aucun_bon_de_commande_ni_fournisseur_ni_prix_ni_evenement_n_est_cree(
    base_durable, m6, monkeypatch, tmp_path
):
    _configurer(monkeypatch, tmp_path, ARTICLES)
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")
    _publier_wct("wct-1")  # ce que M4 a déjà publié ; M6 ne l'a pas encore consommé (aucun événement de M6)
    evenements_avant = _types_publies()

    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 56.0)], publier=False)

    assert len(_constats()) == 1
    for registre in ("bons_commande", "fournisseurs", "livre_prix", "besoins_prevus"):
        assert _registre(registre) == [], registre
    assert _types_publies() == evenements_avant == {"m4.travaux_termines"}  # aucun événement de commande
    assert {m["type_mouvement"] for m in _registre("principal")} == {"RECEPTION", "CONSOMMATION"}


def test_les_fonctions_du_chemin_n_appellent_aucune_creation_de_po_ni_envoi_ni_paiement():
    arbre = ast.parse(Path(outils_mod.__file__).read_text(encoding="utf-8"))
    fonctions = {
        noeud.name: noeud for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.FunctionDef) and noeud.name in {"_constater_stock_des_articles", "attentes",
                                                                 "_articles_reapprovisionnement"}
    }
    assert set(fonctions) == {"_constater_stock_des_articles", "attentes", "_articles_reapprovisionnement"}
    interdits = {"bons_commande", "creer_po_brouillon", "creer_brouillon", "approuver", "marquer_envoye",
                 "generer_courriel", "livre_prix", "fournisseurs", "publier"}
    for nom, fonction in fonctions.items():
        utilises = set()
        for noeud in ast.walk(fonction):
            if isinstance(noeud, ast.Name):
                utilises.add(noeud.id)
            elif isinstance(noeud, ast.Attribute):
                utilises.add(noeud.attr)
        assert not (utilises & interdits), (nom, utilises & interdits)


# -- par le vrai bus et la vraie file de l'admin ---------------------------------------------------------
@pytest.fixture
def dep_m6():
    return {_DEPT: departements.charger_departements()[_DEPT]}


def _devis_accepte(devis_id, chantier_id, materiau_id, quantite):
    evenements.publier("m3.devis_accepte", "m03-estimation", {
        "devis_id": devis_id, "lead_id": "lead-fictif", "chantier_id": chantier_id,
        "lignes": [{"reference_ligne": f"{devis_id}-L1", "description": "ligne de test (fictif)",
                    "quantite": quantite, "unite": "pi", "prix_unitaire": "10.00", "prix_ligne": "10.00",
                    "reference_besoin_materiau": materiau_id}],
        "cout_total": "100.00", "prix_total": "135.00", "taux_marge": "0.35",
        "horodatage_acceptation": "2026-09-01T10:00:00-04:00"}, evenement_id=f"m3-devis-accepte-{devis_id}")


def _livrer(dep_m6):
    resume = evenements.repartir(dep_m6, maintenant="2026-09-15T13:00:00+00:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    return resume


def _charges_publiees(type_evenement):
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == type_evenement).order_by(EVENEMENTS_SORTANTS.c.cree_le)
        ).mappings().all()
    return [codec.decoder(ligne["charge"]) for ligne in lignes]


def test_cascade_par_le_bus_le_besoin_arrive_dans_la_file_de_l_admin(
    base_durable, m6, dep_m6, monkeypatch, tmp_path
):
    _configurer(monkeypatch, tmp_path, ARTICLES)
    _devis_accepte("DEVIS-STOCK-fictif", CHANTIER, GOUTTIERE, "40")
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")
    _publier_wct("wct-1")
    _livrer(dep_m6)  # M6 reçoit le devis accepté (prévu) puis le WCT : « declaration_absente »
    assert _charges_publiees("m6.variance_chantier")[-1]["statut_variance"] == "declaration_absente"
    assert _constats() == []  # rien n'a encore sorti de stock : rien à évaluer

    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 56.0)], publier=False)  # +40 % : écart critique
    _livrer(dep_m6)

    variance = _charges_publiees("m6.variance_chantier")[-1]
    assert (variance["statut_variance"], variance["signal_critique"]) == ("evaluee", True)
    (constat,) = _constats()
    assert constat["evenement_declencheur"] == "wct-1" and constat["quantite_a_commander"] == "156.0"
    with stockage.transaction() as cnx:
        file = approbations.file_proprietaire(cnx, dep_m6)
        attentes, illisibles = approbations.attentes_departements(cnx, dep_m6)
    assert illisibles == []
    assert [(a["type"], a["departement"]) for a in file] == [("besoin_commande", _DEPT)]
    assert attentes == file and set(file[0]) == {*approbations.CHAMPS_ATTENTE, "departement"}


def test_declaration_avant_la_livraison_du_wct_evalue_quand_meme_et_la_livraison_ne_double_rien(
    base_durable, m6, dep_m6, monkeypatch, tmp_path
):
    """Le formulaire peut arriver avant que le bus ait livré la complétion à M6 : le stock est évalué à la
    déclaration (sa seule cause), et la livraison tardive de `m4.travaux_termines` n'y touche pas."""
    _configurer(monkeypatch, tmp_path, ARTICLES)
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")
    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 56.0)])
    avant = _constats()
    assert len(avant) == 1

    _livrer(dep_m6)
    _livrer(dep_m6)

    assert _constats() == avant
    assert [a["type"] for a in _attentes()] == ["besoin_commande"]


def test_seuil_non_configure_par_le_bus_arrive_dans_la_file_de_l_admin(
    base_durable, m6, dep_m6, monkeypatch, tmp_path
):
    _configurer(monkeypatch, tmp_path, {})
    _receptionner(m6, GOUTTIERE, 200.0, "PO-1-fictif")
    _declarer(m6, "wct-1", [_ligne("prevu", GOUTTIERE, 42.0)])
    _livrer(dep_m6)

    with stockage.transaction() as cnx:
        file = approbations.file_proprietaire(cnx, dep_m6)

    assert [(a["type"], a["departement"]) for a in file] == [("seuil_a_configurer", _DEPT)]
    assert GOUTTIERE in file[0]["resume"]
