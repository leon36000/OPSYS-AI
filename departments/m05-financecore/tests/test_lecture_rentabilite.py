"""PLAN T1.5-d : `m5_lire_rentabilite_chantier`, la lecture du coût réel et de la rentabilité par l'admin.

Même règle d'accès que `m5_etat_tresorerie` (T1.4-k2) : pour un appel d'appareil, l'identité confirmée en base
(`admin` seulement), la vue vient du rôle authentifié, un argument ne peut que la restreindre, le refus est rendu
AVANT toute lecture et sans écriture. Rien du calcul ne se passe en argument : tout est lu à la source.

L'état est produit par le VRAI bus (devis, WCT, variance), le livre de prix de M6 lu en lecture seule, le taux
horaire pris d'un manifeste de test. Fictif (AGENTS.md).
"""

from __future__ import annotations

import contextlib
import json

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import validation
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION
from sqlalchemy import select

from opsys import contexte, evenements, identite, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.schema import META

FICTIF = True
_DEPARTEMENT = "m05-financecore"
MATERIAU = "gouttiere-alu-5po-fictif"
COMPLETION = "2026-09-25T16:30:00-04:00"
LIMITE_TRONCATURE = 6000  # `jetons.LIMITE_SORTIE_DEFAUT` : au-delà, le core rend un aperçu, pas la réponse

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")


@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m5-lecture-rentabilite.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {"taux_horaire_main_d_oeuvre": "50.00"}}),
                         encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])
    yield url
    stockage.liberer()


@pytest.fixture
def par_nom():
    return {o.nom: o for o in m5_outils.outils()}


def _devis_accepte(devis_id, chantier_id):
    return {
        "devis_id": devis_id, "lead_id": f"LEAD-{devis_id}-fictif", "chantier_id": chantier_id,
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


def _wct(wct_id, devis_id):
    return {
        "wct_id": wct_id, "intervention_id": f"INT-{wct_id}", "lead_id": f"LEAD-{devis_id}-fictif",
        "technicien_id": "TECH-1", "horodatage_completion": COMPLETION,
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2}, "duree_reelle_minutes": 180,
        "ecart_signale": False, "revue_id": None, "hash_maillon": f"hash-{wct_id}",
        "consommateurs_cibles": ["M5"], "devis_id": devis_id, "statut": "completed_verified",
    }


def _variance(wct_id, chantier_id):
    return {
        "evenement_id": f"m6-variance-{wct_id}-evaluee", "wct_id": wct_id, "intervention_id": f"INT-{wct_id}",
        "chantier_id": chantier_id, "statut_variance": "evaluee", "signal_critique": False,
        "seuil_pourcentage": 0.3, "horodatage_completion": COMPLETION,
        "lignes": [{"materiau": MATERIAU, "unite": "pi", "quantite_prevue": "40.0", "quantite_reelle": "42.0",
                    "ecart_pourcentage": "0.05", "critique": False}],
    }


def _livrer(instant="2026-09-25T17:00:00-04:00"):
    resume = evenements.repartir({_DEPARTEMENT: charger_departements()[_DEPARTEMENT]}, maintenant=instant)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume


def _prix_au_livre(prix=8.0, fournisseur="gentek-fictif"):
    with stockage.transaction():
        stockage.maillons("m06-material-control", "livre_prix").append({
            "materiau_id": MATERIAU, "fournisseur_id": fournisseur, "prix_unitaire": prix, "devise": "CAD",
            "date_effet": "2026-09-01", "source_document": None, "unite": "pi"})


@pytest.fixture
def chantier_complet():
    """DEVIS-1 / CHANTIER-1 : les trois pièces reçues, prix au livre, taux configuré -> coût complet."""
    _prix_au_livre()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte("DEVIS-1", "CHANTIER-1"))
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct("WCT-1", "DEVIS-1"))
    charge = _variance("WCT-1", "CHANTIER-1")
    evenements.publier("m6.variance_chantier", "m06-material-control", charge, evenement_id=charge["evenement_id"])
    _livrer()


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        yield


def _appeler(par_nom, arguments, identite_appelante=ADMIN):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom["m5_lire_rentabilite_chantier"], arguments)


def _lire(par_nom, arguments=None, identite_appelante=ADMIN):
    """Le contenu d'une lecture accordée : `{"ok", "resultat": {"accepte": vrai, "resultat": <la vue>}}`."""
    reponse = _appeler(par_nom, arguments or {}, identite_appelante)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _code(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _instantane_base():
    with stockage.transaction() as cnx:
        return {nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
                for nom, table in META.tables.items()}


# =========================================================================================
# 1. L'admin lit le détail d'un chantier : tout vient de la source
# =========================================================================================
def test_l_admin_lit_le_cout_reel_et_la_marge_d_un_devis(par_nom, chantier_complet):
    vue = _lire(par_nom, {"devis_id": "DEVIS-1"})

    assert vue["role"] == "admin" and (vue["nombre"], vue["affichees"], vue["reste"]) == (1, 1, 0)
    (chantier,) = vue["chantiers"]
    assert (chantier["devis_id"], chantier["chantier_id"], chantier["statut"]) == ("DEVIS-1", "CHANTIER-1", "calculee")
    r = chantier["rentabilite"]
    assert r["verdict"] == "CALCULEE" and r["manque"] == []
    assert r["prix_facture"] == "600.00" and r["statut_facture"] == "BROUILLON" and r["prix_definitif"] is False
    assert r["cout_reel"]["cout_total"] == "486.00" and r["cout_reel"]["complet"] is True
    assert r["cout_reel"]["materiaux"]["lignes"][0]["cout"] == "336.00"
    assert r["cout_reel"]["main_d_oeuvre"] == {
        "statut": "complet", "minutes": 180, "taux_horaire": "50.00", "cout": "150.00"}
    assert r["marge_reelle"] == "114.00" and r["marge_reelle_pct_du_prix"] == "0.1900"
    assert r["marge_prevue"] == "120.00" and r["marge_prevue_pct_du_prix"] == "0.2000"
    assert r["ecart_marge"] == "-6.00" and r["ecart_marge_points"] == "-0.0100" and r["en_perte"] is False
    assert r["taux_marge_devis"] == "0.25"
    assert "version_entrees" not in r and chantier["trace"]["a_jour"] is True
    assert len(chantier["trace"]["version_entrees"]) == 64


def test_le_detail_dit_ses_hypotheses_et_son_arrondi(par_nom, chantier_complet):
    (chantier,) = _lire(par_nom, {"devis_id": "DEVIS-1"})["chantiers"]

    cout = chantier["rentabilite"]["cout_reel"]
    assert "ROUND_HALF_UP" in cout["arrondi"]
    assert len(cout["hypotheses"]) == 3 and "effectif" in " ".join(cout["hypotheses"])


def test_le_detail_d_un_chantier_tient_dans_la_limite_de_troncature_du_core(par_nom, chantier_complet):
    reponse = _appeler(par_nom, {"devis_id": "DEVIS-1"})

    assert len(json.dumps(reponse, ensure_ascii=False)) < LIMITE_TRONCATURE


def test_lecture_par_chantier_id_et_filtre_inconnu(par_nom, chantier_complet):
    (par_chantier,) = _lire(par_nom, {"chantier_id": "CHANTIER-1"})["chantiers"]
    (par_devis,) = _lire(par_nom, {"devis_id": "DEVIS-1", "chantier_id": "CHANTIER-1"})["chantiers"]
    assert par_chantier == par_devis

    for arguments in ({"devis_id": "DEVIS-INCONNU"}, {"chantier_id": "CHANTIER-INCONNU"},
                      {"devis_id": "DEVIS-1", "chantier_id": "CHANTIER-AUTRE"}):
        reponse = _appeler(par_nom, arguments)
        assert _code(reponse) == "REJ-RENTABILITE-CHANTIER-INCONNU", arguments
        assert "REJ-RENTABILITE-CHANTIER-INCONNU" in validation.CODES_M5


def test_sans_filtre_une_ligne_par_devis_et_les_attentes_sans_aucun_montant(par_nom, chantier_complet):
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte("DEVIS-2", "CHANTIER-2"))
    _livrer("2026-09-25T18:00:00-04:00")  # DEVIS-2 : le WCT n'est pas encore arrivé

    vue = _lire(par_nom)

    assert (vue["nombre"], vue["affichees"], vue["reste"]) == (2, 2, 0)
    deux, un = vue["chantiers"]  # le plus récemment reçu d'abord
    assert un["devis_id"] == "DEVIS-1" and un["rentabilite"]["marge_reelle"] == "114.00"
    assert set(un["rentabilite"]) == {
        "verdict", "statut_facture", "prix_facture", "cout_reel_complet", "cout_total",
        "cout_total_connu", "marge_reelle", "marge_prevue", "ecart_marge", "manque"}
    assert un["trace"] == {"a_jour": True}  # l'empreinte n'est rendue que pour un chantier précis
    assert deux == {"devis_id": "DEVIS-2", "chantier_id": "CHANTIER-2", "statut": "en_attente_travaux_termines"}


def test_sans_aucun_devis_recu_la_liste_est_vide(par_nom):
    assert _lire(par_nom) == {
        "role": "admin", "nombre": 0, "affichees": 0, "reste": 0, "chantiers": [], "mention": MENTION}


def _cinq_devis_en_attente_de_travaux():
    for numero in range(1, 6):
        evenements.publier("m3.devis_accepte", "m03-estimation",
                           _devis_accepte(f"DEVIS-{numero}", f"CHANTIER-{numero}"))
    _livrer()


def test_la_liste_est_bornee_le_plus_recent_d_abord_et_dit_ce_qui_reste(par_nom):
    _cinq_devis_en_attente_de_travaux()

    vue = _lire(par_nom, {"limite": 2})

    assert (vue["nombre"], vue["affichees"], vue["reste"]) == (5, 2, 3)
    assert [c["devis_id"] for c in vue["chantiers"]] == ["DEVIS-5", "DEVIS-4"]
    tout = _lire(par_nom)
    assert [c["devis_id"] for c in tout["chantiers"]] == [f"DEVIS-{n}" for n in (5, 4, 3, 2, 1)]


@pytest.mark.parametrize("limite", [0, -1, 13, True, 2.5])
def test_une_limite_invalide_est_un_refus_nomme_avant_toute_lecture(par_nom, monkeypatch, limite):
    with monkeypatch.context() as remplacement:
        remplacement.setattr(m5_outils, "_sources_cout_reel", lambda: pytest.fail("lecture avant le refus"))
        with _appareil(ADMIN), stockage.transaction():
            reponse = m5_outils.lire_rentabilite_chantier(limite=limite)

    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-RENTABILITE-LIMITE-INVALIDE"


def test_la_liste_du_maximum_de_chantiers_partiels_tient_dans_la_limite_de_troncature_du_core(par_nom):
    """Le pire cas : `limite` au maximum, chaque chantier partiel avec plusieurs codes de manque."""
    for numero in range(1, 21):
        devis, wct = f"DEVIS-{numero}", f"WCT-{numero}"
        evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte(devis, f"CHANTIER-{numero}"))
        evenements.publier("m4.travaux_termines", "m04-field-ops", _wct(wct, devis))
        charge = _variance(wct, f"CHANTIER-{numero}")
        evenements.publier("m6.variance_chantier", "m06-material-control", charge,
                           evenement_id=charge["evenement_id"])
    _livrer()  # ni prix au livre de M6 : chaque chantier est partiel

    reponse = _appeler(par_nom, {"limite": m5_outils._LIMITE_LECTURE_MAX})

    vue = reponse["resultat"]["resultat"]
    assert (vue["nombre"], vue["affichees"], vue["reste"]) == (20, 12, 8)
    assert all(c["rentabilite"]["verdict"] == "PARTIELLE" for c in vue["chantiers"])
    assert len(json.dumps(reponse, ensure_ascii=False)) < LIMITE_TRONCATURE


def test_la_liste_lit_chaque_source_une_seule_fois_pas_une_fois_par_devis(par_nom, monkeypatch):
    """Une liste de N chantiers relit N fois chaque registre si `_etat_chantier` lit à chaque appel : quadratique."""
    _cinq_devis_en_attente_de_travaux()
    lectures = []
    original = m5_outils._sources_cout_reel

    def _compte():
        lectures.append(1)
        return original()

    with monkeypatch.context() as remplacement:
        remplacement.setattr(m5_outils, "_sources_cout_reel", _compte)
        assert _lire(par_nom)["nombre"] == 5

    assert lectures == [1]


def test_un_cout_partiel_est_rendu_partiel_avec_la_liste_de_ce_qui_manque(par_nom):
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte("DEVIS-1", "CHANTIER-1"))
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct("WCT-1", "DEVIS-1"))
    charge = _variance("WCT-1", "CHANTIER-1")
    evenements.publier("m6.variance_chantier", "m06-material-control", charge, evenement_id=charge["evenement_id"])
    _livrer()  # ni prix au livre de M6, et taux de test configuré

    (chantier,) = _lire(par_nom, {"devis_id": "DEVIS-1"})["chantiers"]

    r = chantier["rentabilite"]
    assert r["verdict"] == "PARTIELLE" and r["cout_reel"]["complet"] is False
    assert [e["code"] for e in r["manque"]] == ["REJ-COUT-PRIX-NON-DISPONIBLE", "REJ-COUT-TEMPS-POINTE-ABSENT"]
    assert r["manque"][0]["materiau"] == MATERIAU
    assert r["marge_reelle"] is None and r["cout_reel"]["cout_total"] is None
    assert r["marge_partielle_plafond"] == "600.00" and r["cout_reel"]["cout_total_connu"] == "0"


def test_la_lecture_montre_l_etat_d_aujourd_hui_et_dit_quand_la_trace_est_en_retard(par_nom, chantier_complet):
    (avant,) = _lire(par_nom, {"devis_id": "DEVIS-1"})["chantiers"]
    assert avant["trace"]["a_jour"] is True

    _prix_au_livre(prix=9.0, fournisseur="gentek-fictif")  # M6 corrige le prix (même fournisseur : remplace)
    (apres,) = _lire(par_nom, {"devis_id": "DEVIS-1"})["chantiers"]

    assert apres["rentabilite"]["cout_reel"]["materiaux"]["lignes"][0]["cout"] == "378.00"  # 42 x 9,00
    assert apres["trace"]["a_jour"] is False and apres["trace"]["version_entrees"] != avant["trace"]["version_entrees"]
    with stockage.transaction():
        m5_outils._essayer_cout_reel("DEVIS-1")  # la prochaine cascade trace le nouvel état
    (rattrape,) = _lire(par_nom, {"devis_id": "DEVIS-1"})["chantiers"]
    assert rattrape["trace"]["a_jour"] is True
    assert rattrape["trace"]["version_entrees"] == apres["trace"]["version_entrees"]


def test_la_lecture_n_ecrit_rien_meme_quand_la_trace_est_en_retard(par_nom, chantier_complet):
    _prix_au_livre(prix=9.0)
    avant = _instantane_base()

    _lire(par_nom, {"devis_id": "DEVIS-1"})
    _lire(par_nom)
    _lire(par_nom, {"chantier_id": "CHANTIER-1"})
    _appeler(par_nom, {"devis_id": "DEVIS-INCONNU"})

    assert _instantane_base() == avant


# =========================================================================================
# 2. Personne, rôle, droit de voir les coûts : la règle de `m5_etat_tresorerie`
# =========================================================================================
def test_l_outil_est_de_portee_admin_seulement_et_de_niveau_lecture(par_nom):
    outil = par_nom["m5_lire_rentabilite_chantier"]

    assert outil.roles_appareil == frozenset({"admin"})
    assert outil.autonomie.name == "T0" and not outil.frontiere_humaine


@pytest.mark.parametrize("appelante", [MARC, VENDEUR], ids=["employe", "vendeur"])
@pytest.mark.parametrize("arguments", [{}, {"devis_id": "DEVIS-1"}, {"autorise_couts": True},
                                       {"autorise_couts": False}, {"role": "admin", "autorise_couts": True}],
                         ids=["rien", "un_devis", "veut_les_couts", "vue_sans_montant", "se_dit_admin"])
def test_employe_et_vendeur_n_obtiennent_rien_le_refus_precede_toute_lecture(
        par_nom, chantier_complet, monkeypatch, appelante, arguments):
    avant = _instantane_base()

    def _interdit(*_args, **_kwargs):
        raise AssertionError("une pièce a été lue avant le refus")

    with monkeypatch.context() as remplacement:
        remplacement.setattr(m5_outils, "_etat_chantier", _interdit)
        remplacement.setattr(m5_outils, "_livre_de_prix_m6", _interdit)
        reponse = _appeler(par_nom, arguments, appelante)

    assert _code(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert "486.00" not in str(reponse) and "114.00" not in str(reponse)
    assert _instantane_base() == avant


def test_une_identite_non_confirmee_en_base_est_refusee(par_nom, chantier_complet):
    fantome = contexte.IdentiteAppelante(personne="fantome.fictif", role="admin")
    with stockage.transaction() as cnx:
        identite.activer(cnx, "admin.fictif", False)

    assert _code(_appeler(par_nom, {}, fantome)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _code(_appeler(par_nom, {}, ADMIN)) == "REJ-IDENTITE-APPAREIL-INVALIDE"  # désactivée depuis l'appairage


def test_sans_le_droit_de_voir_les_couts_aucun_montant_ne_sort(par_nom, chantier_complet):
    vue = _lire(par_nom, {"devis_id": "DEVIS-1", "autorise_couts": False})

    (chantier,) = vue["chantiers"]
    assert chantier["rentabilite"] == {
        "devis_id": "DEVIS-1", "chantier_id": "CHANTIER-1", "verdict": "PARTIELLE", "statut_facture": "BROUILLON",
        "cout_reel_complet": False, "manque": ["REJ-COUT-TEMPS-POINTE-ABSENT"], "montants_masques": True}
    texte = json.dumps(vue)
    for chiffre in ("486.00", "336.00", "150.00", "114.00", "120.00", "600.00", "50.00", "gentek"):
        assert chiffre not in texte, chiffre


def test_la_vue_masquee_ne_cite_pas_le_detail_d_un_manque_qui_nommerait_un_prix_fournisseur(par_nom):
    _prix_au_livre(8.0, "gentek-fictif")
    _prix_au_livre(9.0, "kaycan-fictif")
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte("DEVIS-1", "CHANTIER-1"))
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct("WCT-1", "DEVIS-1"))
    charge = _variance("WCT-1", "CHANTIER-1")
    evenements.publier("m6.variance_chantier", "m06-material-control", charge, evenement_id=charge["evenement_id"])
    _livrer()

    complet = json.dumps(_lire(par_nom, {"devis_id": "DEVIS-1"}))
    masque = json.dumps(_lire(par_nom, {"devis_id": "DEVIS-1", "autorise_couts": False}))

    assert "kaycan-fictif" in complet and "9.0" in complet  # l'admin voit pourquoi le prix est ambigu
    assert "kaycan" not in masque and "9.0" not in masque and "REJ-COUT-PRIX-AMBIGU" in masque


def test_l_admin_ne_peut_pas_se_dire_un_autre_role(par_nom, chantier_complet):
    for role in ("employee", "seller", "nathan_owner"):
        assert _code(_appeler(par_nom, {"role": role}, ADMIN)) == "REJ-IDENTITE-FOURNIE-DIFFERENTE"

    assert _lire(par_nom, {"role": "admin"})["role"] == "admin"


def test_sans_appareil_autorise_couts_est_obligatoire_et_explicite(par_nom, chantier_complet):
    assert _code(_appeler(par_nom, {}, identite_appelante=None)) == "REJ-AUTORISE-COUTS-REQUIS"
    # « true » en texte est refusé par le schéma, avant même la fonction
    assert _appeler(par_nom, {"autorise_couts": "true"}, identite_appelante=None)["erreur"] == "arguments_invalides"

    vue = _lire(par_nom, {"autorise_couts": True, "role": "gestionnaire"}, identite_appelante=None)
    assert vue["role"] == "gestionnaire" and vue["chantiers"][0]["rentabilite"]["marge_reelle"] is None
    assert vue["chantiers"][0]["rentabilite"]["cout_total_connu"] == "336.00"
    sans_montant = _lire(par_nom, {"autorise_couts": False}, identite_appelante=None)
    assert sans_montant["chantiers"][0]["rentabilite"]["montants_masques"] is True


# =========================================================================================
# 3. Aucun montant, prix, taux, durée ni quantité ne se passe en argument
# =========================================================================================
@pytest.mark.parametrize("argument", [
    {"cout_total": "1.00"}, {"prix_facture": "9999.00"}, {"taux_horaire": 1}, {"taux_horaire_main_d_oeuvre": "1.00"},
    {"duree_reelle_minutes": 1}, {"quantite_reelle": "1"}, {"lignes": []}, {"livre_de_prix": []},
    {"marge_reelle": "1.00"}, {"mouvements_historique": []},
], ids=lambda argument: next(iter(argument)))
def test_l_outil_refuse_tout_argument_qui_porterait_une_piece_du_calcul(par_nom, chantier_complet, argument):
    avant = _instantane_base()

    reponse = _appeler(par_nom, argument)

    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    assert _instantane_base() == avant


@pytest.mark.parametrize("argument", [{"chantier_id": 7}, {"devis_id": ["DEVIS-1"]}, {"autorise_couts": "oui"},
                                      {"role": 3}, {"limite": "vingt"}])
def test_les_arguments_de_choix_ont_leur_type(par_nom, chantier_complet, argument):
    assert _appeler(par_nom, argument)["erreur"] == "arguments_invalides"


def test_la_description_de_l_outil_dit_qu_il_lit_sans_ecrire_et_reste_dans_la_limite():
    outil = next(o for o in m5_outils.outils() if o.nom == "m5_lire_rentabilite_chantier")

    assert "Lecture pure" in outil.description and len(outil.description) <= 1024
    assert set(outil.parametres["properties"]) == {"chantier_id", "devis_id", "limite", "role", "autorise_couts"}
    assert outil.parametres["additionalProperties"] is False


def test_un_second_wct_pour_le_meme_devis_rend_le_cout_partiel_jamais_le_total_d_un_chantier_plus_long(
        par_nom, chantier_complet):
    with stockage.transaction():
        stockage.maillons(_DEPARTEMENT, "wct_recus").append({
            "wct_id": "WCT-2", "intervention_id": "INT-WCT-2", "devis_id": "DEVIS-1",
            "horodatage_completion": "2026-09-26T16:30:00-04:00", "duree_reelle_minutes": 120})

    (chantier,) = _lire(par_nom, {"devis_id": "DEVIS-1"})["chantiers"]

    r = chantier["rentabilite"]
    assert r["verdict"] == "PARTIELLE" and r["cout_reel"]["complet"] is False
    assert [e["code"] for e in r["manque"]] == ["REJ-COUT-TEMPS-POINTE-ABSENT", "REJ-COUT-PLUSIEURS-WCT"]
    assert "WCT-2" in r["manque"][1]["detail"]
    assert r["marge_reelle"] is None and r["cout_reel"]["cout_total"] is None
    assert r["cout_reel"]["cout_total_connu"] == "336.00"  # matériaux connus du premier WCT uniquement


def test_vue_partielle_masque_tous_les_montants_et_prix_fournisseur(par_nom, chantier_complet):
    """La protection d'accès reste exercée lorsque le WCT scalaire est ambigu."""
    vue = _lire(par_nom, {"devis_id": "DEVIS-1", "autorise_couts": False})
    (chantier,) = vue["chantiers"]
    assert chantier["rentabilite"]["verdict"] == "PARTIELLE"
    assert chantier["rentabilite"]["montants_masques"] is True
    texte = json.dumps(vue)
    for confidentiel in ("336.00", "600.00", "50.00", "gentek"):
        assert confidentiel not in texte
