"""C2 — le bon de commande est COMMANDABLE à un vrai fournisseur.

Avant (analyse M6, §1 point 2) : lignes sans unité, pas de date requise, pas de livraison/ramassage, un seul fournisseur
par PO, facteur de perte reçu mais jamais appliqué, courriel réduit à « matériau : quantité ». Maintenant :

  - chaque ligne porte son UNITÉ (égale à celle de la fiche article quand elle existe), sa quantité nette, son facteur
    de perte DÉCLARÉ (jamais inventé, appliqué une seule fois) et la quantité à commander qui en découle ;
  - le PO porte une date requise, un mode (livraison au dépôt, au chantier, ramassage) et, pour le chantier, le lieu ;
  - un besoin se répartit entre fournisseurs : un PO par fournisseur, aucune ligne perdue ni commandée deux fois ;
  - le courriel de M1 est complet (objet « Commande matériaux — PO — ville », unités, date, mode, perte) ;
  - brouillon de PO et courriel sont des tâches internes (N2) ; l'approbation reste N3 et l'envoi une décision humaine.

Vrais outils sur une base SQLite migrée ; identifiants et coordonnées fictifs (AGENTS.md).
"""

from __future__ import annotations

import pytest
from m6_material_control import bons_commande, catalogue_materiaux
from m6_material_control import outils as outils_mod
from m6_material_control.outils import consommateurs, outils

from opsys import stockage
from opsys.outils import Niveau, executer_atomique

FICTIF = True
HORO = "2026-11-02T10:00:00-05:00"
DEPT = "m06-material-control"
GENTEK = "f-gentek-fictif"
KAYCAN = "f-kaycan-fictif"
REV, VIS, SOF = "REV-ALU-FICTIF", "VIS-INOX-FICTIVE", "SOFFITE-FICTIVE"
DEVIS, CHANTIER = "DEVIS-PO-FICTIF", "CH-PO-FICTIF"
CONDITIONS = {"date_requise": "2026-11-10", "mode_livraison": "livraison_chantier",
              "lieu_livraison": "Chantier fictif, 12 rue des Érables, Repentigny", "ville": "Repentigny"}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def m6(base_durable):
    return {o.nom: o for o in outils()}


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _estimation(lignes, devis_id=DEVIS):
    """Une estimation M3 telle que M6 la reçoit : les facteurs de perte sont ceux du barème de M3, ou absents."""
    charge = {
        "devis_id": devis_id, "lead_id": "lead-po-fictif", "estimation_id": "a" * 64, "rang_registre": 1,
        "bareme_version": "2026.1-fictif", "niveau_confiance": 0.8,
        "lignes": lignes, "facteurs_perte_absents": [x["materiau"] for x in lignes if "facteur_perte" not in x],
    }
    with stockage.transaction():
        assert consommateurs()["m3.besoins_materiaux"](charge)["traite"] is True


def _preparer(m6, avec_prix=True, perte_rev="0.08"):
    """Deux fournisseurs, un prévu de trois articles (la perte du revêtement est déclarée, celle de la vis ne l'est
    pas)."""
    _ok(executer_atomique(m6["m6_enregistrer_fournisseur"], {
        "fournisseur_id": GENTEK, "nom": "Gentek (fictif)", "horodatage": HORO,
        "courriel_commande": "commandes@gentek.exemple-fictif.test"}))
    _ok(executer_atomique(m6["m6_enregistrer_fournisseur"], {
        "fournisseur_id": KAYCAN, "nom": "Kaycan (fictif)", "horodatage": HORO,
        "courriel_commande": "commandes@kaycan.exemple-fictif.test"}))
    lignes = [
        {"materiau": "Revêtement alu (fictif)", "sku": REV, "quantite_estimee": "100", "unite": "feuille",
         **({"facteur_perte": perte_rev} if perte_rev else {})},
        {"materiau": "Vis inox (fictif)", "sku": VIS, "quantite_estimee": "4", "unite": "boite"},
        {"materiau": "Soffite (fictif)", "sku": SOF, "quantite_estimee": "30", "unite": "piece",
         "facteur_perte": "0.10"},
    ]
    _estimation(lignes)
    _ok(executer_atomique(m6["m6_enregistrer_besoins_prevus"], {
        "chantier_id": CHANTIER, "devis_id": DEVIS,
        "lignes": [{"materiau_id": REV, "quantite_estimee": 100.0, "unite": "feuille"},
                   {"materiau_id": VIS, "quantite_estimee": 4.0, "unite": "boite"},
                   {"materiau_id": SOF, "quantite_estimee": 30.0, "unite": "piece"}]}))
    if avec_prix:
        for materiau, fournisseur, prix, unite in ((REV, GENTEK, 30.0, "feuille"), (SOF, GENTEK, 12.0, "piece"),
                                                   (VIS, KAYCAN, 9.5, "boite")):
            _ok(executer_atomique(m6["m6_enregistrer_prix"], {
                "materiau_id": materiau, "fournisseur_id": fournisseur, "prix_unitaire": prix, "devise": "CAD",
                "date_effet": "2026-10-01", "unite": unite, "source_document": "grille-fictive.pdf"}))


def _po(m6, po_id="PO-FICTIF-1", fournisseur=GENTEK, **plus):
    arguments = {"po_id": po_id, "devis_id": DEVIS, "fournisseur_id": fournisseur, "horodatage": HORO,
                 **CONDITIONS, **plus}
    return executer_atomique(m6["m6_creer_po_brouillon"], arguments)


def _registre_po():
    with stockage.transaction():
        return list(stockage.maillons(DEPT, "bons_commande"))


def _lire(po_id):
    return bons_commande.lire(_registre_po(), po_id)


def _lignes_par_materiau(po):
    return {ligne["materiau_id"]: ligne for ligne in po["lignes"]}


# =========================================================================================
# 1. La ligne : unité, perte déclarée appliquée une fois, jamais inventée
# =========================================================================================
def test_chaque_ligne_porte_son_unite_sa_quantite_nette_la_perte_declaree_et_la_quantite_a_commander(m6):
    _preparer(m6)

    po = _ok(_po(m6, materiau_ids=[REV, SOF]))["po"]

    lignes = _lignes_par_materiau(po)
    assert set(lignes) == {REV, SOF}
    assert (lignes[REV]["unite"], lignes[REV]["quantite_nette"], lignes[REV]["facteur_perte"]) == ("feuille", 100.0,
                                                                                                   "0.08")
    assert lignes[REV]["quantite_demandee"] == 108.0, "100 x (1 + 0,08), appliqué UNE fois"
    assert lignes[SOF]["quantite_demandee"] == 33.0 and lignes[SOF]["unite"] == "piece"
    assert lignes[REV]["montant_ligne_prevu"] == 3240.0, "le montant prévu suit la quantité à commander (108 x 30 $)"


def test_une_perte_non_declaree_n_est_jamais_inventee(m6):
    _preparer(m6)

    reponse = _ok(_po(m6, po_id="PO-VIS", fournisseur=KAYCAN, materiau_ids=[VIS]))

    ligne = reponse["po"]["lignes"][0]
    assert ligne["facteur_perte"] is None and ligne["quantite_demandee"] == ligne["quantite_nette"] == 4.0
    assert reponse["facteurs_perte_absents"] == [VIS], "le manque est dit à la personne, pas comblé"


def test_la_perte_est_appliquee_une_seule_fois_meme_apres_une_seconde_lecture(m6):
    _preparer(m6)
    _ok(_po(m6, materiau_ids=[REV]))

    relu = _lire("PO-FICTIF-1")

    assert relu["lignes"][0]["quantite_demandee"] == 108.0
    assert bons_commande.construire_bon_demande(relu)["lignes_demandees"] == [
        {"materiau_id": REV, "quantite_demandee": 108.0}], "la réception compare à la quantité brute commandée"


def test_l_unite_de_la_ligne_doit_etre_celle_de_la_fiche_article(m6):
    _preparer(m6)
    with stockage.transaction():
        catalogue_materiaux.enregistrer(
            stockage.maillons(DEPT, "catalogue_materiaux"), materiau_id=REV, nom="Revêtement aluminium fictif",
            unite="boite", actif=True, raison="fiche de test", auteur="admin.fictif", horodatage=HORO,
            revision_attendue=0)

    code = _refus(_po(m6, materiau_ids=[REV]))

    assert code == "REJ-PO-UNITE-INCOHERENTE"
    assert _registre_po() == [], "rien n'est écrit"


def test_une_fiche_article_fournit_la_designation_et_dit_d_ou_vient_l_unite(m6):
    _preparer(m6)
    with stockage.transaction():
        catalogue_materiaux.enregistrer(
            stockage.maillons(DEPT, "catalogue_materiaux"), materiau_id=REV, nom="Revêtement aluminium fictif",
            unite="feuille", actif=True, raison="fiche de test", auteur="admin.fictif", horodatage=HORO,
            revision_attendue=0)

    lignes = _lignes_par_materiau(_ok(_po(m6, materiau_ids=[REV, SOF]))["po"])

    assert lignes[REV]["unite_source"] == "fiche_catalogue"
    assert lignes[REV]["designation"] == "Revêtement aluminium fictif"
    assert lignes[SOF]["unite_source"] == "besoin_prevu", "pas de fiche : l'unité est celle du besoin, et c'est dit"


def test_un_prix_du_livre_dans_une_autre_unite_n_est_pas_applique_et_le_po_ne_s_approuve_pas(m6):
    _preparer(m6, avec_prix=False)
    _ok(executer_atomique(m6["m6_enregistrer_prix"], {
        "materiau_id": REV, "fournisseur_id": GENTEK, "prix_unitaire": 30.0, "devise": "CAD",
        "date_effet": "2026-10-01", "unite": "boite"}))

    ligne = _ok(_po(m6, materiau_ids=[REV]))["po"]["lignes"][0]

    assert ligne["verdict_prix"] == "INDETERMINE" and ligne["prix_unitaire_prevu"] is None
    assert _refus(executer_atomique(m6["m6_approuver_po"], {"po_id": "PO-FICTIF-1", "horodatage": HORO})) \
        == "REJ-PO-PRIX-INDETERMINE"


def test_un_prix_sans_unite_est_applique_mais_dit_non_confirme(m6):
    _preparer(m6, avec_prix=False)
    _ok(executer_atomique(m6["m6_enregistrer_prix"], {
        "materiau_id": REV, "fournisseur_id": GENTEK, "prix_unitaire": 30.0, "devise": "CAD", "date_effet":
        "2026-10-01"}))

    ligne = _ok(_po(m6, materiau_ids=[REV]))["po"]["lignes"][0]

    assert ligne["prix_unitaire_prevu"] == 30.0 and ligne["prix_unite_confirmee"] is False


# =========================================================================================
# 2. Les conditions : date requise, livraison ou ramassage
# =========================================================================================
@pytest.mark.parametrize("plus,code", [
    ({"date_requise": "2026-11-01"}, "REJ-PO-DATE-REQUISE-INVALIDE"),       # avant la création
    ({"date_requise": "10 novembre"}, "REJ-PO-DATE-REQUISE-INVALIDE"),
    ({"date_requise": "2026-02-30"}, "REJ-PO-DATE-REQUISE-INVALIDE"),
    ({"lieu_livraison": None}, "REJ-PO-LIEU-LIVRAISON-REQUIS"),              # livraison au chantier sans lieu
    ({"ville": "Repentigny\nBcc: pirate@example.test"}, "REJ-PO-TEXTE-INVALIDE"),   # injection d'en-tête
    ({"lieu_livraison": "12 rue\rBcc: x"}, "REJ-PO-TEXTE-INVALIDE"),
    ({"notes": "x" * 501}, "REJ-PO-TEXTE-INVALIDE"),
])
def test_les_conditions_invalides_sont_refusees_sans_rien_ecrire(m6, plus, code):
    _preparer(m6)

    assert _refus(_po(m6, materiau_ids=[REV], **plus)) == code
    assert _registre_po() == []


def test_un_mode_inconnu_est_refuse_par_le_schema_et_par_le_domaine(m6):
    _preparer(m6)
    assert _po(m6, materiau_ids=[REV], mode_livraison="drone")["ok"] is False  # schéma de l'outil

    registre: list = []
    fournisseurs = [{"type_entree": "fournisseur_cree", "fournisseur_id": GENTEK, "nom": "Gentek (fictif)"}]
    po, verdict = bons_commande.creer_brouillon(
        "PO-X", CHANTIER, GENTEK, [{"materiau_id": REV, "quantite_nette": 1.0, "unite": "feuille"}], HORO, registre, [],
        fournisseurs, conditions={"date_requise": "2026-11-10", "mode_livraison": "drone"})
    assert po is None and verdict["code"] == "REJ-PO-MODE-LIVRAISON-INVALIDE" and registre == []


def test_le_ramassage_et_le_depot_n_exigent_pas_de_lieu(m6):
    _preparer(m6)
    for mode, po_id in (("ramassage", "PO-RAM"), ("livraison_depot", "PO-DEP")):
        po = _ok(_po(m6, po_id=po_id, mode_livraison=mode, lieu_livraison=None, materiau_ids=[VIS], fournisseur=KAYCAN)
                 if po_id == "PO-RAM" else _po(m6, po_id=po_id, mode_livraison=mode, lieu_livraison=None,
                                                 materiau_ids=[SOF]))["po"]
        assert po["mode_livraison"] == mode and po["date_requise"] == "2026-11-10"


def test_un_po_deja_cree_avec_d_autres_conditions_n_est_pas_ecrase(m6):
    _preparer(m6)
    _ok(_po(m6, materiau_ids=[REV]))
    avant = _registre_po()

    assert _refus(_po(m6, materiau_ids=[REV], date_requise="2026-11-20")) == "REJ-PO-ID-DEJA-UTILISE"
    assert _ok(_po(m6, materiau_ids=[REV]))["po"]["date_requise"] == "2026-11-10", "même contenu : rejeu sans effet"
    assert _registre_po() == avant


# =========================================================================================
# 3. Un besoin, plusieurs fournisseurs : un PO par fournisseur, aucune ligne perdue ni doublée
# =========================================================================================
def _repartir(m6, repartition, **plus):
    return executer_atomique(m6["m6_creer_pos_depuis_besoin"], {
        "devis_id": DEVIS, "horodatage": HORO, **CONDITIONS, "repartition": repartition, **plus})


BONNE_REPARTITION = [
    {"po_id": "PO-GENTEK", "fournisseur_id": GENTEK, "materiau_ids": [REV, SOF]},
    {"po_id": "PO-KAYCAN", "fournisseur_id": KAYCAN, "materiau_ids": [VIS]},
]


def test_un_besoin_donne_un_po_par_fournisseur_avec_toutes_les_lignes_une_fois(m6):
    _preparer(m6)

    reponse = _ok(_repartir(m6, BONNE_REPARTITION))

    assert [p["po_id"] for p in reponse["pos"]] == ["PO-GENTEK", "PO-KAYCAN"]
    gentek, kaycan = _lire("PO-GENTEK"), _lire("PO-KAYCAN")
    assert {x["materiau_id"] for x in gentek["lignes"]} == {REV, SOF} and gentek["fournisseur_id"] == GENTEK
    assert {x["materiau_id"] for x in kaycan["lignes"]} == {VIS} and kaycan["fournisseur_id"] == KAYCAN
    assert gentek["devis_id"] == kaycan["devis_id"] == DEVIS
    assert gentek["statut"] == kaycan["statut"] == "draft"
    assert gentek["lignes"][0]["quantite_demandee"] == 108.0, "la perte déclarée est appliquée dans chaque PO"


@pytest.mark.parametrize("repartition,code", [
    ([BONNE_REPARTITION[0]], "REJ-PO-REPARTITION-INCOMPLETE"),                    # la vis n'est commandée nulle part
    ([BONNE_REPARTITION[0], {**BONNE_REPARTITION[1], "materiau_ids": [VIS, SOF]}], "REJ-PO-REPARTITION-DOUBLE"),
    ([BONNE_REPARTITION[0], {**BONNE_REPARTITION[1], "materiau_ids": [VIS, "INCONNU-FICTIF"]}],
     "REJ-PO-REPARTITION-INCONNUE"),
    ([BONNE_REPARTITION[0], {**BONNE_REPARTITION[1], "fournisseur_id": GENTEK}],
     "REJ-PO-REPARTITION-FOURNISSEUR-DOUBLE"),
    ([BONNE_REPARTITION[0], {**BONNE_REPARTITION[1], "po_id": "PO-GENTEK"}], "REJ-PO-REPARTITION-PO-DOUBLE"),
    ([BONNE_REPARTITION[0], {**BONNE_REPARTITION[1], "fournisseur_id": "f-inconnu-fictif"}],
     "REJ-PO-FOURNISSEUR-INCONNU"),
    ([], "REJ-PO-REPARTITION-INCOMPLETE"),
])
def test_une_repartition_fautive_ne_cree_aucun_po(m6, repartition, code):
    _preparer(m6)

    assert _refus(_repartir(m6, repartition)) == code
    assert _registre_po() == [], "tout ou rien : pas même le premier PO"


def test_rejouer_la_meme_repartition_n_ajoute_rien(m6):
    _preparer(m6)
    _ok(_repartir(m6, BONNE_REPARTITION))
    avant = _registre_po()

    _ok(_repartir(m6, BONNE_REPARTITION))

    assert _registre_po() == avant


# =========================================================================================
# 4. Le courriel que M1 reçoit est complet
# =========================================================================================
def _approuve_et_genere(m6, po_id="PO-GENTEK"):
    _ok(executer_atomique(m6["m6_approuver_po"], {"po_id": po_id, "horodatage": HORO}))
    return _ok(executer_atomique(m6["m6_generer_courriel_po"], {
        "po_id": po_id, "horodatage": HORO, "nom_entreprise": "Atelier Fictif inc."}))["po"]


def test_le_courriel_dit_l_objet_les_unites_la_date_le_mode_la_perte_et_ne_dit_aucun_prix(m6):
    _preparer(m6)
    _ok(_repartir(m6, BONNE_REPARTITION))

    courriel = _approuve_et_genere(m6)["courriel"]

    assert courriel["objet"] == "Commande matériaux — PO-GENTEK — Repentigny"
    assert courriel["destinataire"] == "commandes@gentek.exemple-fictif.test"
    corps = courriel["corps"]
    assert "Revêtement alu (fictif)" in corps or REV in corps
    assert "108 feuille" in corps and "33 piece" in corps
    assert "100 feuille" in corps and "8 %" in corps, "net et perte déclarée visibles, pas seulement le brut"
    assert "Date requise : 2026-11-10" in corps
    assert "Livraison au chantier" in corps and "12 rue des Érables, Repentigny" in corps
    assert "PO-GENTEK" in corps and "Atelier Fictif inc." in corps
    for prive in ("30.0", "3240", "CAD", "$", "prix"):
        assert prive not in corps, f"aucun prix dans le courriel au fournisseur : {prive}"
    assert len(courriel["empreinte"]) == 64


def test_le_courriel_publie_a_m1_est_celui_du_po_et_son_empreinte_est_celle_du_po(m6):
    _preparer(m6)
    _ok(_repartir(m6, BONNE_REPARTITION))
    po = _approuve_et_genere(m6)

    with stockage.transaction() as cnx:
        from sqlalchemy import select

        from opsys.stockage import codec
        from opsys.stockage.schema import EVENEMENTS_SORTANTS
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m6.po_courriel_pret")).all()
    (charge,) = [codec.decoder(x.charge) for x in lignes]
    assert charge["po_id"] == "PO-GENTEK" and charge["objet"] == po["courriel"]["objet"]
    assert charge["corps"] == po["courriel"]["corps"] and charge["empreinte"] == po["courriel"]["empreinte"]


def test_sans_ville_l_objet_n_a_pas_de_tiret_orphelin(m6):
    _preparer(m6)
    _ok(_po(m6, materiau_ids=[VIS], fournisseur=KAYCAN, po_id="PO-VIS", ville=None, mode_livraison="ramassage",
            lieu_livraison=None))

    courriel = _approuve_et_genere(m6, "PO-VIS")["courriel"]

    assert courriel["objet"] == "Commande matériaux — PO-VIS"


def test_un_po_ancien_sans_conditions_ne_s_approuve_ni_ne_s_envoie(m6):
    """Un brouillon d'avant C2 (ni unité, ni date, ni mode) n'est pas commandable : on l'annule et on le refait."""
    _preparer(m6)
    ancien = {"type_entree": "po_cree", "statut": "draft", "po_id": "PO-ANCIEN", "chantier_id": CHANTIER,
              "fournisseur_id": GENTEK, "horodatage": HORO, "montant_total_prevu": 10.0,
              "lignes": [{"materiau_id": REV, "quantite_demandee": 1.0, "verdict_prix": "PRIX_LIVRE",
                          "prix_unitaire_prevu": 10.0, "devise_prevue": "CAD", "montant_ligne_prevu": 10.0}]}
    with stockage.transaction():
        stockage.maillons(DEPT, "bons_commande").append(ancien)

    code = _refus(executer_atomique(m6["m6_approuver_po"], {"po_id": "PO-ANCIEN", "horodatage": HORO}))

    assert code == "REJ-PO-NON-COMMANDABLE"
    assert _lire("PO-ANCIEN")["statut"] == "draft"


# =========================================================================================
# 5. Niveaux d'approbation : brouillon et courriel en N2, approbation N3, envoi humain
# =========================================================================================
def test_les_niveaux_brouillon_courriel_en_n2_approbation_n3_envoi_n4():
    par_nom = {o.nom: o for o in outils()}
    assert par_nom["m6_creer_po_brouillon"].niveau_effectif is Niveau.N2
    assert par_nom["m6_creer_pos_depuis_besoin"].niveau_effectif is Niveau.N2
    assert par_nom["m6_generer_courriel_po"].niveau_effectif is Niveau.N2
    assert par_nom["m6_approuver_po"].niveau_effectif is Niveau.N3
    assert par_nom["m6_annuler_po"].niveau_effectif is Niveau.N3
    assert par_nom["m6_marquer_po_envoye"].niveau_effectif is Niveau.N4


def test_un_agent_prepare_sans_approbation_mais_n_approuve_ni_n_envoie_seul(m6):
    from pathlib import Path

    from opsys.capacites import Capacites
    from opsys.departements import lire_manifeste

    _preparer(m6)  # décor posé par les outils directement (sans file d'approbation)
    racine = Path(outils_mod.__file__).resolve().parents[2]
    appel = Capacites({DEPT: lire_manifeste(racine)}, stockage.transaction, memoire=False).appeler
    cree = appel("m6_creer_po_brouillon", {"po_id": "PO-AGENT", "devis_id": DEVIS, "fournisseur_id": GENTEK,
                                           "horodatage": HORO, **CONDITIONS, "materiau_ids": [REV]})
    assert cree.get("ok") is True and cree["resultat"]["accepte"] is True, cree
    assert "demande_id" not in cree, "N2 : le brouillon se crée sans file d'approbation"
    approbation = appel("m6_approuver_po", {"po_id": "PO-AGENT", "horodatage": HORO})
    assert approbation.get("statut") == "en_attente_approbation", "N3 : l'approbation du PO attend une personne"
    assert _lire("PO-AGENT")["statut"] == "draft"
    envoi = appel("m6_marquer_po_envoye", {"po_id": "PO-AGENT", "horodatage": HORO})
    assert envoi.get("statut") == "en_attente_approbation", "N4 : l'envoi manuel attend une personne"
    assert _lire("PO-AGENT")["statut"] == "draft"


def test_une_repartition_demesuree_est_refusee_avant_tout_calcul(m6):
    _preparer(m6)
    trop = [{"po_id": f"PO-X-{i}", "fournisseur_id": f"f-{i}", "materiau_ids": [REV]} for i in range(21)]
    assert _refus(_repartir(m6, trop)) == "REJ-PO-REPARTITION-TROP-GRANDE"
    longue = [{"po_id": "PO-L", "fournisseur_id": GENTEK, "materiau_ids": [f"M-{i}" for i in range(201)]}]
    assert _refus(_repartir(m6, longue)) == "REJ-PO-REPARTITION-TROP-GRANDE"
    assert _registre_po() == []
