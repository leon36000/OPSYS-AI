"""C1 — le COÛT DE SORTIE se résout au niveau de l'ARTICLE, jamais par un refus de toute la déclaration.

Défaut F1 (analyse M6, reproduit sur la ligne ea631e4bc) : `m6_declarer_materiaux_utilises` refusait en entier
(`REJ-COUT-UNITAIRE-INTROUVABLE`) dès qu'une ligne concernait un article jamais reçu SOUS CE CHANTIER. Étaient donc
impossibles : la sortie du dépôt vers un autre chantier, l'achat sur place d'un article inédit et l'article non prévu
inédit. Ce que l'employé a réellement utilisé n'a pas à attendre un prix.

Règle (ordre, chaque source est DITE sur le mouvement, `origine_cout`) :
  1. la dernière RÉCEPTION de l'article sous CE chantier        -> RECEPTION_CHANTIER ;
  2. à défaut, la dernière RÉCEPTION de l'article ailleurs      -> RECEPTION_ARTICLE (dépôt, autre chantier) ;
  3. à défaut, le livre de prix de M6 : prix en vigueur par fournisseur, dans l'unité de la ligne, daté au plus tard
     du jour du WCT ; un seul prix distinct -> LIVRE_PRIX, marqué SOURCE_DECLAREE (document cité) ou
     FALLBACK_PRICE_BOOK (aucun document) ;
  4. sinon, le coût est INCONNU (`cout_unitaire: None`, motif dit) : la déclaration est ACCEPTÉE et l'admin voit ce
     qu'il faut déclarer. Un prix sans source n'est jamais « validé ».

Tous les tests passent par les VRAIS outils sur une base SQLite migrée. Données fictives (AGENTS.md).
"""

from __future__ import annotations

import contextlib
import json

import pytest
from m6_material_control import outils as outils_mod
from m6_material_control import registre as registre_module
from m6_material_control.outils import outils
from sqlalchemy import func, select

from opsys import contexte, evenements, identite, stockage
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True

MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
INT = "int-article-fictif"
CHANTIER = "CH-ART-FICTIF"
DEPOT = "CHANTIER-DEPOT-FICTIF"
AUTRE_CHANTIER = "CH-AUTRE-FICTIF"
MAT = "REV-ALU-FICTIF"
UNITE = "feuille"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def m6(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
    return {o.nom: o for o in outils()}


# -- aides ----------------------------------------------------------------------------------------------
def _publier_wct(wct_id="wct-art", devis_id=None, horodatage="2026-11-02T10:00:00-05:00"):
    charge = {
        "wct_id": wct_id, "intervention_id": INT, "lead_id": "lead-fictif", "technicien_id": "marc.fictif",
        "horodatage_completion": horodatage, "fix_gps_completion": {"latitude": 45.5, "longitude": -73.5},
        "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None, "hash_maillon": "a" * 16,
        "consommateurs_cibles": ["M6"], "devis_id": devis_id, "statut": "completed_pending_review",
    }
    with stockage.transaction():
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id=wct_id)


def _receptionner(m6, chantier_id, quantite=100.0, cout=5.0, materiau_id=MAT, po="PO-FICTIF"):
    reponse = executer_atomique(m6["m6_receptionner_commande"], {
        "bon_demande": {"po_id": f"{po}-{chantier_id}", "chantier_id": chantier_id,
                        "lignes_demandees": [{"materiau_id": materiau_id, "quantite_demandee": quantite}],
                        "horodatage": "2026-10-01T00:00:00Z"},
        "reception_po": {"po_id": f"{po}-{chantier_id}", "chantier_id": chantier_id,
                         "lignes_recues": [{"materiau_id": materiau_id, "quantite_recue": quantite}],
                         "horodatage": "2026-10-02T00:00:00Z"},
        "catalogue_materiaux": {"version": "v1", "unite_monetaire": "CAD",
                                "postes": {materiau_id: {"cout_unitaire": cout, "libelle": materiau_id}}},
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def _prix(m6, fournisseur="f-un", prix=7.5, unite=UNITE, source="facture-fictive-12.pdf", date_effet="2026-10-01",
          materiau_id=MAT):
    arguments = {"materiau_id": materiau_id, "fournisseur_id": fournisseur, "prix_unitaire": prix, "devise": "CAD",
                 "date_effet": date_effet}
    if unite is not None:
        arguments["unite"] = unite
    if source is not None:
        arguments["source_document"] = source
    reponse = executer_atomique(m6["m6_enregistrer_prix"], arguments)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def _ligne(type_ligne="prevu", quantite=10.0, materiau_id=MAT, unite=UNITE):
    base = {"type_ligne": type_ligne, "materiau_id": materiau_id, "quantite": quantite, "unite": unite}
    if type_ligne == "prevu":
        base["quantite_estimee"] = quantite
    if type_ligne == "achat_terrain":
        base.update(photo_fournie=True, recu_fourni=False)
    return base


def _declarer(m6, lignes, chantier_id=CHANTIER, wct_id="wct-art", identite_appelante=None):
    formulaire = {"wct_id": wct_id, "intervention_id": INT, "chantier_id": chantier_id, "lignes_materiaux": lignes}
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        return executer_atomique(m6["m6_declarer_materiaux_utilises"], {"wct_id": wct_id, "formulaire": formulaire})


def _accepte(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _mouvements(wct_id="wct-art"):
    with stockage.transaction():
        return [m for m in stockage.maillons("m06-material-control", "principal") if m.get("wct_id") == wct_id]


def _tous_mouvements():
    with stockage.transaction():
        return list(stockage.maillons("m06-material-control", "principal"))


def _consommation(materiau_id=MAT, wct_id="wct-art"):
    (m,) = [m for m in _mouvements(wct_id) if m["materiau_id"] == materiau_id and m["type_mouvement"] == "CONSOMMATION"]
    return m


def _attentes():
    with stockage.transaction():
        return outils_mod.attentes()


def _compte_sortants():
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one()


# =========================================================================================
# 1. Les trois impossibilités de F1 sont levées
# =========================================================================================
def test_la_sortie_du_depot_vers_un_autre_chantier_est_acceptee_au_cout_de_reception_de_l_article(m6):
    _publier_wct()
    _receptionner(m6, DEPOT, cout=5.0)

    _accepte(_declarer(m6, [_ligne()]))

    m = _consommation()
    assert (m["chantier_id"], m["quantite"], m["cout_unitaire"]) == (CHANTIER, -10.0, 5.0)
    assert m["origine_cout"]["source"] == "RECEPTION_ARTICLE"
    reception = [x for x in _tous_mouvements() if x["type_mouvement"] == "RECEPTION"][0]
    assert m["origine_cout"]["reference"] == reception["hash_maillon"], "la réception citée est vérifiable"


def test_l_achat_sur_place_d_un_article_inedit_est_accepte_avec_un_cout_inconnu_dit(m6):
    _publier_wct()
    avant = _compte_sortants()

    _accepte(_declarer(m6, [_ligne("achat_terrain", 3.0, materiau_id="SCELLANT-INEDIT-FICTIF", unite="tube")]))

    m = _consommation("SCELLANT-INEDIT-FICTIF")
    assert m["cout_unitaire"] is None
    assert m["origine_cout"] == {"source": "INCONNU", "motif": "AUCUN_PRIX", "marquage": None}
    assert _compte_sortants() >= avant  # la variance reste calculée sur les quantités (aucun prix requis)


def test_l_article_non_prevu_inedit_est_accepte_et_les_autres_lignes_ne_sont_pas_bloquees(m6):
    _publier_wct()
    _receptionner(m6, CHANTIER, cout=6.0)

    _accepte(_declarer(m6, [_ligne(quantite=8.0), _ligne("non_prevu", 2.0, materiau_id="VIS-INEDITE-FICTIVE",
                                                         unite="boite")]))

    assert _consommation(MAT)["origine_cout"]["source"] == "RECEPTION_CHANTIER"
    assert _consommation("VIS-INEDITE-FICTIVE")["origine_cout"]["source"] == "INCONNU"
    assert {m["materiau_id"] for m in _mouvements()} == {MAT, "VIS-INEDITE-FICTIVE"}


# =========================================================================================
# 2. L'ordre des sources est celui qui est dit
# =========================================================================================
def test_la_reception_du_chantier_l_emporte_sur_celle_du_depot_et_sur_le_livre_de_prix(m6):
    _publier_wct()
    _receptionner(m6, DEPOT, cout=5.0)
    _receptionner(m6, CHANTIER, cout=6.0, po="PO-CH")
    _prix(m6, prix=9.99)

    _accepte(_declarer(m6, [_ligne()]))

    m = _consommation()
    assert m["cout_unitaire"] == 6.0 and m["origine_cout"]["source"] == "RECEPTION_CHANTIER"


def test_a_defaut_de_reception_le_livre_de_prix_sert_avec_sa_source_dite(m6):
    _publier_wct()
    _prix(m6, prix=7.5, source="facture-fictive-12.pdf")

    _accepte(_declarer(m6, [_ligne()]))

    m = _consommation()
    assert m["cout_unitaire"] == 7.5
    assert m["origine_cout"]["source"] == "LIVRE_PRIX"
    assert m["origine_cout"]["marquage"] == "SOURCE_DECLAREE"
    assert m["origine_cout"]["prix"] == [
        {"fournisseur_id": "f-un", "source_document": "facture-fictive-12.pdf", "date_effet": "2026-10-01"}]


def test_un_prix_du_livre_sans_source_est_marque_et_ne_devient_jamais_valide(m6):
    _publier_wct()
    _prix(m6, prix=7.5, source=None)

    _accepte(_declarer(m6, [_ligne()]))

    m = _consommation()
    assert m["cout_unitaire"] == 7.5
    assert m["origine_cout"]["marquage"] == "FALLBACK_PRICE_BOOK"
    texte = json.dumps(m, ensure_ascii=False).lower()
    assert "valid" not in texte, "un coût sans source n'est jamais présenté comme validé"


def test_le_dernier_prix_ecrit_d_un_fournisseur_fait_foi(m6):
    _publier_wct()
    _prix(m6, prix=7.5)
    _prix(m6, prix=8.25, date_effet="2026-10-15", source="facture-fictive-13.pdf")

    _accepte(_declarer(m6, [_ligne()]))

    assert _consommation()["cout_unitaire"] == 8.25


# =========================================================================================
# 3. Un prix inutilisable n'est jamais utilisé « quand même »
# =========================================================================================
@pytest.mark.parametrize("unite_du_prix", ["boite", None])
def test_un_prix_dans_une_autre_unite_ou_sans_unite_confirmee_n_est_pas_utilise(m6, unite_du_prix):
    _publier_wct()
    _prix(m6, prix=7.5, unite=unite_du_prix)

    _accepte(_declarer(m6, [_ligne()]))

    m = _consommation()
    assert m["cout_unitaire"] is None
    assert m["origine_cout"] == {"source": "INCONNU", "motif": "UNITE_NON_CONFIRMEE", "marquage": None}


def test_deux_fournisseurs_a_des_prix_differents_ne_donnent_aucun_cout_et_au_meme_prix_un_cout(m6):
    _publier_wct()
    _prix(m6, fournisseur="f-un", prix=7.5)
    _prix(m6, fournisseur="f-deux", prix=9.0)

    _accepte(_declarer(m6, [_ligne()]))
    m = _consommation()
    assert m["cout_unitaire"] is None and m["origine_cout"]["motif"] == "PRIX_AMBIGU"

    _publier_wct("wct-meme-prix")
    _prix(m6, fournisseur="f-deux", prix=7.5, source=None)  # f-deux s'aligne : un seul prix distinct
    _accepte(_declarer(m6, [_ligne()], wct_id="wct-meme-prix"))
    m = _consommation(wct_id="wct-meme-prix")
    assert m["cout_unitaire"] == 7.5 and m["origine_cout"]["marquage"] == "FALLBACK_PRICE_BOOK"
    assert {p["fournisseur_id"] for p in m["origine_cout"]["prix"]} == {"f-un", "f-deux"}


def test_un_prix_date_apres_le_jour_du_wct_n_est_pas_applicable(m6):
    _publier_wct(horodatage="2026-11-02T10:00:00-05:00")
    _prix(m6, prix=7.5, date_effet="2026-11-03")

    _accepte(_declarer(m6, [_ligne()]))

    m = _consommation()
    assert m["cout_unitaire"] is None and m["origine_cout"]["source"] == "INCONNU"


def test_un_prix_d_un_autre_article_n_est_jamais_emprunte(m6):
    _publier_wct()
    _prix(m6, prix=7.5, materiau_id="AUTRE-ARTICLE-FICTIF")
    _receptionner(m6, DEPOT, cout=5.0, materiau_id="AUTRE-ARTICLE-FICTIF")

    _accepte(_declarer(m6, [_ligne()]))

    assert _consommation()["cout_unitaire"] is None


def test_une_reception_au_prix_indetermine_ne_donne_pas_de_cout(m6):
    """Une réception sans prix résolu (`cout_unitaire` nul) ne peut pas servir de coût de sortie."""
    _publier_wct()
    reponse = executer_atomique(m6["m6_receptionner_commande"], {
        "bon_demande": {"po_id": "PO-SANS-PRIX", "chantier_id": DEPOT,
                        "lignes_demandees": [{"materiau_id": MAT, "quantite_demandee": 50.0}],
                        "horodatage": "2026-10-01T00:00:00Z"},
        "reception_po": {"po_id": "PO-SANS-PRIX", "chantier_id": DEPOT,
                         "lignes_recues": [{"materiau_id": MAT, "quantite_recue": 50.0}],
                         "horodatage": "2026-10-02T00:00:00Z"},
    })
    assert reponse["ok"] is True
    assert [m["cout_unitaire"] for m in _tous_mouvements() if m["type_mouvement"] == "RECEPTION"] == [None]

    _accepte(_declarer(m6, [_ligne()]))

    assert _consommation()["cout_unitaire"] is None


def test_une_livraison_de_zero_ne_remplace_pas_le_prix_de_la_vraie_livraison(m6):
    """Un PO livré en deux fois écrit une ligne à zéro pour l'article déjà arrivé : son prix n'est pas un prix payé."""
    _publier_wct()
    _receptionner(m6, DEPOT, cout=5.0, quantite=100.0)
    _receptionner(m6, DEPOT, cout=9.0, quantite=0.0, po="PO-ZERO")

    _accepte(_declarer(m6, [_ligne()]))

    m = _consommation()
    assert m["cout_unitaire"] == 5.0 and m["origine_cout"]["source"] == "RECEPTION_ARTICLE"


# =========================================================================================
# 4. Ce que cela change pour le stock, l'admin et l'employé
# =========================================================================================
def test_l_inedit_rend_le_stock_negatif_et_l_admin_voit_quoi_declarer(m6):
    _publier_wct()

    _accepte(_declarer(m6, [_ligne("achat_terrain", 3.0, materiau_id="SCELLANT-INEDIT-FICTIF", unite="tube")]))

    attentes = _attentes()
    types = {a["type"] for a in attentes}
    assert "stock_negatif" in types, "un stock négatif est dit à l'admin même sans seuil configuré"
    cout = [a for a in attentes if a["type"] == "cout_sortie_inconnu"]
    assert len(cout) == 1 and cout[0]["id"] == "cout_sortie_inconnu:SCELLANT-INEDIT-FICTIF"
    assert "m6_enregistrer_prix" in cout[0]["action_proposee"] and "tube" in cout[0]["resume"]
    assert "SCELLANT-INEDIT-FICTIF" in cout[0]["resume"]


def test_declarer_ensuite_un_prix_fait_disparaitre_l_attente_sans_reecrire_le_mouvement(m6):
    _publier_wct()
    _accepte(_declarer(m6, [_ligne("achat_terrain", 3.0, materiau_id="SCELLANT-INEDIT-FICTIF", unite="tube")]))
    avant = _tous_mouvements()
    assert any(a["type"] == "cout_sortie_inconnu" for a in _attentes())

    _prix(m6, prix=12.0, unite="tube", materiau_id="SCELLANT-INEDIT-FICTIF")

    assert not any(a["type"] == "cout_sortie_inconnu" for a in _attentes())
    assert _tous_mouvements() == avant, "l'historique n'est jamais réécrit : le coût d'alors reste inconnu"


def test_l_employe_ne_voit_aucun_cout_ni_aucune_origine_de_cout(m6):
    _publier_wct()
    _receptionner(m6, DEPOT, cout=5.0)

    reponse = _declarer(m6, [_ligne()], chantier_id=INT,
                        identite_appelante=MARC)  # un employé : chantier = intervention

    _accepte(reponse)
    texte = json.dumps(reponse, ensure_ascii=False).lower()
    for interdit in ("cout", "prix", "origine", "5.0", "fournisseur"):
        assert interdit not in texte, (interdit, texte)


def test_la_chaine_reste_valide_et_l_origine_du_cout_est_infalsifiable(m6):
    _publier_wct()
    _receptionner(m6, DEPOT, cout=5.0)
    _accepte(_declarer(m6, [_ligne(), _ligne("non_prevu", 1.0, materiau_id="VIS-INEDITE-FICTIVE", unite="boite")]))
    maillons = _tous_mouvements()
    assert registre_module.Registre(maillons=maillons).valider_chaine()[0] is True

    falsifie = json.loads(json.dumps(maillons))
    cible = next(m for m in falsifie if m.get("origine_cout", {}).get("source") == "RECEPTION_ARTICLE")
    cible["origine_cout"]["source"] = "RECEPTION_CHANTIER"  # mauvaise dimension : le coût change de source
    assert registre_module.Registre(maillons=falsifie).valider_chaine()[0] is False


def test_une_declaration_rejouee_n_ecrit_rien_de_plus(m6):
    _publier_wct()
    _receptionner(m6, DEPOT, cout=5.0)
    _accepte(_declarer(m6, [_ligne()]))
    avant = _tous_mouvements()

    rejeu = _declarer(m6, [_ligne()])

    assert rejeu["resultat"]["accepte"] is False
    assert rejeu["resultat"]["verdict"]["code"] == "REJ-DECLARATION-DEJA-SOUMISE"
    assert _tous_mouvements() == avant


def test_un_refus_de_forme_n_ecrit_rien_meme_si_d_autres_lignes_sont_resolues(m6):
    _publier_wct()
    _receptionner(m6, DEPOT, cout=5.0)
    avant = _tous_mouvements()
    mauvaise = _ligne("non_prevu", 1.0, materiau_id="VIS-INEDITE-FICTIVE", unite="boite")
    mauvaise["quantite"] = -1.0

    reponse = _declarer(m6, [_ligne(), mauvaise])

    assert reponse["resultat"]["accepte"] is False
    assert _tous_mouvements() == avant


def test_les_lectures_de_pertes_et_de_reappro_acceptent_un_mouvement_a_cout_inconnu(m6):
    """Trois validateurs de forme relisent le registre des mouvements : ils doivent connaître `origine_cout`."""
    from m6_material_control import pertes_appareil, preuves_pertes_bris_appareil, reapprovisionnement_appareil

    _publier_wct()
    _receptionner(m6, DEPOT, cout=5.0)
    _accepte(_declarer(m6, [_ligne(), _ligne("perte", 1.0, materiau_id="VIS-INEDITE-FICTIVE", unite="boite")]))
    maillons = _tous_mouvements()
    assert any("origine_cout" in m for m in maillons)

    pertes_appareil._mouvements(maillons)
    reapprovisionnement_appareil._principal(maillons, [])
    preuves_pertes_bris_appareil.valider_snapshots(maillons, [])


# =========================================================================================
# 5. Le refus d'avant n'existe plus (le test qui le figeait est remplacé par ceux-ci)
# =========================================================================================
def test_aucun_chemin_de_la_declaration_ne_refuse_plus_pour_un_cout_introuvable(m6):
    _publier_wct()

    reponse = _declarer(m6, [_ligne(), _ligne("achat_terrain", 1.0, materiau_id="X-FICTIF", unite="tube")])

    resultat = _accepte(reponse)
    assert "REJ-COUT-UNITAIRE-INTROUVABLE" not in json.dumps(resultat)
