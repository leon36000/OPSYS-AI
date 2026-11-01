"""Grand livre : brouillons des factures FOURNISSEURS et rapprochement CTI/RTI, en pur, sur des registres en mémoire.

La correspondance DÉCLARATIVE catégorie de dépense -> compte de charge du plan versionné (`correspondance_charges`,
version `2026-v2`), son extension par le client et chaque refus au chargement ; la génération depuis l'état courant des
comptes à payer (Dt charge avant taxes / Dt CTI / Dt RTI / Ct comptes fournisseurs), montants relus de la pièce, jamais
recalculés ; les factures ignorées (taxes illisibles, catégorie sans compte) ; l'idempotence par pièce ; le
rapprochement CTI/RTI au cent, avec l'écart par facture ; l'export Beancount équilibré.

Cas de référence (taux versionnés 2026 : TPS 5 %, TVQ 9,975 %, ROUND_HALF_UP au cent) :
- C-4001, carburant, sans PO : 100.00 $ ; TPS 5.00 ; TVQ 9.98 ; 114.98 $ ;
- F-1001, sur PO-1 (60 × 5.00 reçus) : 300.00 $ ; TPS 15.00 ; TVQ 29.93 ; 344.93 $ ;
- O-77, outils, sans PO : 250.00 $ ; TPS 12.50 ; TVQ 24.94 ; 287.44 $.
Fournisseurs, identifiants et montants fictifs (AGENTS.md).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import comptes_a_payer as ap
from m5_financecore import (
    grand_livre,
    grand_livre_beancount,
    plan_comptable,
    taux_fiscaux,
    verdicts_grand_livre,
)
from m5_financecore import registre as registre_module

FICTIF = True
D = Decimal
_M5 = Path(__file__).resolve().parents[1]
_PLAN = _M5 / "contracts" / "plan_comptable_pme_qc.v1.yaml"
H = "2026-10-15T10:00:00-04:00"
SAISIE = "2026-10-08T10:00:00-04:00"
LIVRAISON = "2026-09-29T09:15:00-04:00"
HUMAIN = {"par": "comptable", "role": "finance", "voie": "approbation"}
CATEGORIES = ["carburant", "outils", "location"]
OCTOBRE = {"debut": "2026-10-01", "fin": "2026-10-31"}


@pytest.fixture
def plan():
    base, refus = plan_comptable.charger_plan(_PLAN)
    assert refus is None, refus
    return base


@pytest.fixture(scope="module")
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_M5 / "contracts" / "taux_fiscaux.v1.yaml")
    assert erreurs == []
    return dictionnaire


@pytest.fixture
def reg():
    return registre_module.Registre()


@pytest.fixture
def reg_ap():
    return registre_module.Registre()


def L(compte, debit=None, credit=None):
    return {"compte": compte, "debit": debit, "credit": credit}


def _accepte(couple):
    resultat, refus = couple
    assert refus is None, refus
    return resultat


def _code(couple):
    resultat, refus = couple
    assert resultat is None and refus is not None, resultat
    assert refus["code"] in verdicts_grand_livre.CODES_GL
    return refus["code"]


def _sans_po(reg_ap, taux, *, categorie="carburant", numero="C-4001", montant="100.00", date_facture="2026-10-01",
             fournisseur="Pétro-Nord (fictif)"):
    return _accepte(ap.saisir_facture_sans_po(
        fournisseur_id=fournisseur, categorie=categorie, numero_facture=numero, date_facture=date_facture,
        montant_avant_taxes=montant, total_facture=None, saisi_par="comptable", voie="appareil", horodatage=SAISIE,
        dictionnaire_taux=taux, categories_configurees=CATEGORIES, registre_cible=reg_ap))["facture"][
        "facture_fournisseur_id"]


def _sur_po(reg_ap, taux, *, numero="F-1001", montant="300.00", date_facture="2026-10-02"):
    ligne = {"materiau_id": "gouttiere-5po", "quantite_demandee": "60", "quantite_recue": "60",
             "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
             "prix_unitaire_reception": None, "verdict_prix_reception": "INDETERMINE", "ecart_prix_critique": None}
    entree = _accepte(ap.construire_reception({
        "evenement_id": "evt-1", "po_id": "PO-1", "fournisseur_id": "gentek", "chantier_id": "CH-1",
        "horodatage_reception": LIVRAISON, "verdict_reception": "CONFORME", "statut_po": "received",
        "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": None, "lignes": [ligne]}))
    _accepte(ap.enregistrer_reception(entree, reg_ap))
    return _accepte(ap.saisir_facture_fournisseur(
        po_id="PO-1", fournisseur_id="gentek", numero_facture=numero, date_facture=date_facture,
        montant_avant_taxes=montant, total_facture=None, saisi_par="comptable", voie="appareil", horodatage=SAISIE,
        dictionnaire_taux=taux, registre_cible=reg_ap))["facture"]["facture_fournisseur_id"]


def _trois_factures(reg_ap, taux):
    return {"carburant": _sans_po(reg_ap, taux), "po": _sur_po(reg_ap, taux),
            "outils": _sans_po(reg_ap, taux, categorie="outils", numero="O-77", montant="250.00",
                               date_facture="2026-10-03", fournisseur="Outils Fictifs")}


def _etat(reg):
    return grand_livre.etat_grand_livre(reg.lire())


def _comptabiliser(reg, plan, factures, *, valider=True):
    propositions, ignorees = grand_livre.propositions_factures_fournisseurs(factures, plan)
    idents = []
    for proposition in propositions:
        ident = _accepte(grand_livre.proposer_ecriture(reg, plan, horodatage=H, origine="generation_automatique",
                                                       **proposition))["ecriture"]["ecriture_id"]
        if valider:
            _accepte(grand_livre.valider_ecriture(reg, plan, ecriture_id=ident, humain=HUMAIN, horodatage=H))
        idents.append(ident)
    return idents, ignorees


def _rapprocher(reg, plan, taux, factures, **periode):
    return _accepte(grand_livre.rapprocher(_etat(reg), plan, [], taux, factures_fournisseurs=factures,
                                           **(periode or OCTOBRE)))


def _plan_modifie(tmp_path, avant, apres):
    chemin = tmp_path / "plan.yaml"
    texte = _PLAN.read_text(encoding="utf-8")
    assert avant in texte, avant
    chemin.write_text(texte.replace(avant, apres), encoding="utf-8")
    return plan_comptable.charger_plan(chemin)


# ============================================================================================ la correspondance
def test_la_correspondance_de_base_range_chaque_categorie_connue_dans_une_charge_active(plan):
    assert plan["version"] == "2026-v2"
    correspondance = plan["correspondance_charges"]
    assert correspondance == {"factures_sur_po": "5100", "categories_depense": {
        "carburant": "5400", "materiaux": "5100", "marketing": "5950", "outils": "5500"}}
    for numero in (correspondance["factures_sur_po"], *correspondance["categories_depense"].values()):
        compte = plan["comptes"][numero]
        assert compte["type"] == "charges" and compte["actif"], numero
    for nom in correspondance["categories_depense"]:
        assert ap.lire_categories_depense([nom])[1] is None, "même règle de nom que la liste fermée"
    # Les rôles qu'un brouillon fournisseur mouvemente sont au plan.
    assert (plan["roles"]["tps_cti"], plan["roles"]["tvq_rti"], plan["roles"]["comptes_fournisseurs"]) == (
        "1400", "1410", "2100")


@pytest.mark.parametrize(("avant", "apres"), [
    ('carburant: "5400"', 'carburant: "1010"'),          # un compte d'actif
    ('carburant: "5400"', 'carburant: "2100"'),          # un compte de passif
    ('carburant: "5400"', 'carburant: "9999"'),          # inconnu du plan
    ('carburant: "5400"', "carburant: 5400"),            # un nombre, pas un numéro en texte
    ('carburant: "5400"', 'Carburant: "5400"'),          # nom hors de la règle de la liste fermée
    ('factures_sur_po: "5100"', 'factures_sur_po: "4100"'),  # des produits
    ('factures_sur_po: "5100"', 'factures_inventees: "5100"'),  # clé inconnue
    ('  tps_cti: "1400"\n', ""),                         # rôle CTI absent : le brouillon ne saurait où débiter
])
def test_une_correspondance_invalide_fait_refuser_le_plan_au_chargement(tmp_path, avant, apres):
    assert _code(_plan_modifie(tmp_path, avant, apres)) == "REJ-GL-CORRESPONDANCE-INVALIDE"


def test_un_plan_sans_correspondance_ne_range_aucune_facture(tmp_path, reg_ap, taux):
    texte = _PLAN.read_text(encoding="utf-8")
    chemin = tmp_path / "plan.yaml"
    chemin.write_text(texte[:texte.index("correspondance_charges:")], encoding="utf-8")
    sans = _accepte(plan_comptable.charger_plan(chemin))
    assert sans["correspondance_charges"] == {"factures_sur_po": None, "categories_depense": {}}
    _sans_po(reg_ap, taux)
    propositions, ignorees = grand_livre.propositions_factures_fournisseurs(ap.factures_saisies(reg_ap), sans)
    assert propositions == [] and [i["code"] for i in ignorees] == ["REJ-GL-CATEGORIE-SANS-COMPTE"]


def test_le_client_ajoute_redirige_et_retire_des_categories(plan):
    extension = {
        "comptes_ajoutes": [{"numero": "5450", "nom": "Location d'équipement", "type": "charges"}],
        "correspondance_charges": {"categories_depense": {"location": "5450", "carburant": "5990"},
                                   "factures_sur_po": "5200"},
        "categories_depense_retirees": ["marketing"],
    }
    effectif = _accepte(plan_comptable.appliquer_extension(plan, extension))
    assert effectif["correspondance_charges"] == {"factures_sur_po": "5200", "categories_depense": {
        "carburant": "5990", "materiaux": "5100", "outils": "5500", "location": "5450"}}
    assert effectif["version_effective"].startswith("2026-v2+client.")
    assert plan["correspondance_charges"]["categories_depense"]["carburant"] == "5400", "la base n'est pas modifiée"
    # La correspondance seule suffit à changer la version effective : deux correspondances, deux versions.
    seule = _accepte(plan_comptable.appliquer_extension(plan, {"categories_depense_retirees": ["marketing"]}))
    assert seule["version_effective"].startswith("2026-v2+client.")
    assert seule["version_effective"] != effectif["version_effective"]
    assert _accepte(plan_comptable.appliquer_extension(plan, {"comptes_desactives": ["5600"]}))[
        "correspondance_charges"] == plan["correspondance_charges"]


@pytest.mark.parametrize("extension", [
    {"comptes_desactives": ["5400"]},                                         # carburant viserait un compte inactif
    {"correspondance_charges": {"categories_depense": {"location": "5450"}}},  # compte jamais ajouté
    {"correspondance_charges": {"categories_depense": {"location": "1200"}}},  # stocks : un actif
    {"correspondance_charges": {"factures_sur_po": 5100}},
    {"correspondance_charges": {"autre": {}}},
    {"correspondance_charges": "5400"},
    {"categories_depense_retirees": ["inconnue"]},
    {"categories_depense_retirees": "marketing"},
    {"categories_depense_retirees": ["carburant"],
     "correspondance_charges": {"categories_depense": {"carburant": "5990"}}},
])
def test_une_correspondance_du_client_invalide_est_refusee_en_entier(plan, extension):
    assert _code(plan_comptable.appliquer_extension(plan, extension)) == "REJ-GL-CORRESPONDANCE-INVALIDE"


def test_desactiver_un_compte_vise_se_fait_en_le_redirigeant_dans_la_meme_extension(plan):
    effectif = _accepte(plan_comptable.appliquer_extension(plan, {
        "comptes_desactives": ["5400"],
        "correspondance_charges": {"categories_depense": {"carburant": "5990"}}}))
    assert effectif["correspondance_charges"]["categories_depense"]["carburant"] == "5990"


def test_compte_de_charge_par_categorie_ou_sur_po_jamais_suppose(plan):
    assert plan_comptable.compte_de_charge(plan, po_id=None, categorie="outils") == ("5500", None)
    assert plan_comptable.compte_de_charge(plan, po_id="PO-1", categorie=None) == ("5100", None)
    for categorie in ("location", None, 3):
        numero, refus = plan_comptable.compte_de_charge(plan, po_id=None, categorie=categorie)
        assert numero is None and refus["code"] == "REJ-GL-CATEGORIE-SANS-COMPTE"
    assert "2026-v2" in plan_comptable.compte_de_charge(plan, po_id=None, categorie="location")[1]["detail"]


# ============================================================================================ les brouillons
def test_chaque_facture_fournisseur_saisie_donne_un_brouillon_equilibre_relu_de_la_piece(plan, reg_ap, taux):
    ids = _trois_factures(reg_ap, taux)
    propositions, ignorees = grand_livre.propositions_factures_fournisseurs(ap.factures_saisies(reg_ap), plan)
    assert ignorees == []
    par_piece = {p["piece"]["reference"]: p for p in propositions}
    assert set(par_piece) == set(ids.values())
    carburant = par_piece[ids["carburant"]]
    assert carburant["cle_piece"] == f"auto:facture_fournisseur:{ids['carburant']}:saisie"
    assert (carburant["nature"], carburant["date_effet"]) == ("facture_fournisseur_saisie", "2026-10-01")
    assert carburant["piece"] == {"type": "facture_fournisseur", "reference": ids["carburant"]}
    assert carburant["lignes_brutes"] == [L("5400", "100.00"), L("1400", "5.00"), L("1410", "9.98"),
                                          L("2100", credit="114.98")]
    assert carburant["libelle"] == "Facture fournisseur C-4001 (Pétro-Nord (fictif)) saisie"
    assert par_piece[ids["po"]]["lignes_brutes"] == [L("5100", "300.00"), L("1400", "15.00"), L("1410", "29.93"),
                                                     L("2100", credit="344.93")]
    assert par_piece[ids["outils"]]["lignes_brutes"] == [L("5500", "250.00"), L("1400", "12.50"),
                                                         L("1410", "24.94"), L("2100", credit="287.44")]
    assert [p["date_effet"] for p in propositions] == sorted(p["date_effet"] for p in propositions)


def test_les_montants_viennent_de_la_piece_jamais_d_un_recalcul(plan, reg_ap, taux):
    """Une pièce dont la TVQ (cohérente avec son total) diffère du recalcul aux taux courants garde SES montants."""
    _sans_po(reg_ap, taux)
    [facture] = ap.factures_saisies(reg_ap)
    piece = {**facture, "taxes": [{**t, "montant": D("9.97")} if t["id"] == "tvq_quebec" else t
                                  for t in facture["taxes"]],
             "total_taxes": D("14.97"), "montant_apres_taxes": D("114.97")}
    [proposition], _ = grand_livre.propositions_factures_fournisseurs([piece], plan)
    assert proposition["lignes_brutes"][2] == L("1410", "9.97")
    assert proposition["lignes_brutes"][3] == L("2100", credit="114.97")


def test_une_facture_annulee_n_a_pas_de_brouillon_et_une_corrigee_vaut_sa_correction(plan, reg_ap, taux):
    ids = _trois_factures(reg_ap, taux)
    _accepte(ap.annuler_facture_fournisseur(
        facture_fournisseur_id=ids["outils"], motif="Facture en double (fictif)", annule_par="comptable",
        role="finance", voie="appareil", horodatage=H, registre_cible=reg_ap, revision_attendue=0))
    _accepte(ap.corriger_facture_fournisseur(
        facture_fournisseur_id=ids["carburant"], motif="Montant mal tapé (fictif)", numero_facture=None,
        date_facture=None, montant_avant_taxes="120.00", total_facture=None, corrige_par="comptable", role="finance",
        voie="appareil", horodatage=H, dictionnaire_taux=taux, registre_cible=reg_ap, revision_attendue=0))
    # Même un état ANNULEE passé tel quel est écarté par le statut.
    etats = list(ap._etats_factures(reg_ap.lire()).values())
    propositions, ignorees = grand_livre.propositions_factures_fournisseurs(etats, plan)
    assert ignorees == [] and {p["piece"]["reference"] for p in propositions} == {ids["carburant"], ids["po"]}
    carburant = next(p for p in propositions if p["piece"]["reference"] == ids["carburant"])
    assert carburant["lignes_brutes"] == [L("5400", "120.00"), L("1400", "6.00"), L("1410", "11.97"),
                                          L("2100", credit="137.97")]


@pytest.mark.parametrize("alterer", [
    lambda f: f.update(total_taxes=D("15.00")),                                    # total ≠ somme des taxes
    lambda f: f.update(montant_apres_taxes=D("115.00")),                           # avant + taxes ≠ après
    lambda f: f.update(taxes=[*f["taxes"], {"id": "tvh", "montant": D("1.00")}]),  # taxe inconnue
    lambda f: f.update(taxes=[f["taxes"][0], f["taxes"][0]]),                      # taxe répétée
    lambda f: f.update(taxes=[{**f["taxes"][0], "montant": 5.0}, f["taxes"][1]]),  # un flottant
    lambda f: f.update(taxes=[{**f["taxes"][0], "montant": D("-5.00")}, f["taxes"][1]],
                       total_taxes=D("4.98"), montant_apres_taxes=D("104.98")),    # taxe négative
    lambda f: f.update(taxes=None),
    lambda f: f.update(montant_avant_taxes="100.00"),                              # texte, pas Decimal
    lambda f: f.update(date_facture="01/10/2026"),
])
def test_une_facture_aux_montants_ou_taxes_illisibles_est_ignoree_jamais_completee(plan, reg_ap, taux, alterer):
    _sans_po(reg_ap, taux)
    facture = dict(ap.factures_saisies(reg_ap)[0])
    alterer(facture)
    propositions, ignorees = grand_livre.propositions_factures_fournisseurs([facture], plan)
    assert propositions == []
    assert [(i["facture_fournisseur_id"], i["code"]) for i in ignorees] == [
        (facture["facture_fournisseur_id"], "REJ-GL-SOURCE-ILLISIBLE")]


def test_une_categorie_sans_compte_est_ignoree_avec_son_code(plan, reg_ap, taux):
    ident = _sans_po(reg_ap, taux, categorie="location", numero="L-1")
    _sans_po(reg_ap, taux)
    propositions, ignorees = grand_livre.propositions_factures_fournisseurs(ap.factures_saisies(reg_ap), plan)
    assert len(propositions) == 1 and propositions[0]["lignes_brutes"][0]["compte"] == "5400"
    [ignoree] = ignorees
    assert (ignoree["facture_fournisseur_id"], ignoree["code"]) == (ident, "REJ-GL-CATEGORIE-SANS-COMPTE")
    assert "'location'" in ignoree["detail"]


def test_la_generation_est_idempotente_et_une_correction_apres_coup_est_un_conflit(plan, reg, reg_ap, taux):
    ids = _trois_factures(reg_ap, taux)
    _comptabiliser(reg, plan, ap.factures_saisies(reg_ap), valider=False)
    avant = len(reg.lire())
    for proposition in grand_livre.propositions_factures_fournisseurs(ap.factures_saisies(reg_ap), plan)[0]:
        resultat = _accepte(grand_livre.proposer_ecriture(reg, plan, horodatage=H, origine="generation_automatique",
                                                          **proposition))
        assert resultat["statut"] == "deja_proposee"
    assert len(reg.lire()) == avant, "un rejeu n'écrit rien"
    _accepte(ap.corriger_facture_fournisseur(
        facture_fournisseur_id=ids["po"], motif="Montant mal tapé (fictif)", numero_facture=None, date_facture=None,
        montant_avant_taxes="290.00", total_facture=None, corrige_par="comptable", role="finance", voie="appareil",
        horodatage=H, dictionnaire_taux=taux, registre_cible=reg_ap, revision_attendue=0))
    propositions, _ = grand_livre.propositions_factures_fournisseurs(ap.factures_saisies(reg_ap), plan)
    corrigee = next(p for p in propositions if p["piece"]["reference"] == ids["po"])
    assert _code(grand_livre.proposer_ecriture(reg, plan, horodatage=H, origine="generation_automatique",
                                               **corrigee)) == "REJ-GL-PIECE-CONFLIT"
    assert len(reg.lire()) == avant


# ============================================================================================ balance et rapprochement
def test_validees_la_balance_et_le_rapprochement_cti_rti_sont_exacts_au_cent(plan, reg, reg_ap, taux):
    _trois_factures(reg_ap, taux)
    factures = ap.factures_saisies(reg_ap)
    _comptabiliser(reg, plan, factures)
    balance = _accepte(grand_livre.balance_verification(_etat(reg), plan, "2026-10-31"))
    assert balance["equilibree"] and balance["total_debits"] == balance["total_credits"] == "747.35"
    assert {c["compte"]: (c["solde"], c["cote"]) for c in balance["comptes"]} == {
        "1400": ("32.50", "debiteur"), "1410": ("64.85", "debiteur"), "2100": ("747.35", "crediteur"),
        "5100": ("300.00", "debiteur"), "5400": ("100.00", "debiteur"), "5500": ("250.00", "debiteur")}
    resultat = _rapprocher(reg, plan, taux, factures)
    assert resultat["verdict"] == "CONCORDANT" and resultat["factures_fournisseurs_illisibles"] == []
    assert resultat["intrants"]["tps_cti"] == {
        "compte": "1400", "attendu_factures_fournisseurs": "32.50", "au_grand_livre": "32.50",
        "solde_debiteur_a_la_fin": "32.50", "verdict": "CONCORDANT", "ecarts": [], "ecarts_reste": 0}
    assert resultat["intrants"]["tvq_rti"]["attendu_factures_fournisseurs"] == "64.85"
    assert resultat["intrants"]["tvq_rti"]["au_grand_livre"] == "64.85"
    # Hors période : septembre n'attend rien et ne voit aucun mouvement.
    septembre = _rapprocher(reg, plan, taux, factures, debut="2026-09-01", fin="2026-09-30")
    assert septembre["intrants"]["tps_cti"]["attendu_factures_fournisseurs"] == "0.00"
    assert septembre["verdict"] == "CONCORDANT"


def test_rapprochement_dit_l_ecart_d_une_facture_fournisseur_non_comptabilisee(plan, reg, reg_ap, taux):
    ids = _trois_factures(reg_ap, taux)
    factures = ap.factures_saisies(reg_ap)
    idents, _ = _comptabiliser(reg, plan, factures, valider=False)
    for ident in idents[:2]:  # le brouillon de la facture d'outils (la dernière datée) reste en attente
        _accepte(grand_livre.valider_ecriture(reg, plan, ecriture_id=ident, humain=HUMAIN, horodatage=H))
    resultat = _rapprocher(reg, plan, taux, factures)
    cti = resultat["intrants"]["tps_cti"]
    assert resultat["verdict"] == "ECART" and cti["verdict"] == "ECART"
    assert cti["ecarts"] == [{"facture_fournisseur_id": ids["outils"], "attendu_facture": "12.50",
                              "au_grand_livre": "0.00", "raison": "sans écriture définitive"}]
    assert (cti["attendu_factures_fournisseurs"], cti["au_grand_livre"]) == ("32.50", "20.00")
    assert resultat["brouillons_non_comptabilises"] == 1


def test_rapprochement_voit_une_cti_mal_saisie_une_annulation_et_un_recu_hors_facture(plan, reg, reg_ap, taux):
    ident = _sans_po(reg_ap, taux)
    # Saisie à la main sur la facture fournisseur, CTI d'un cent de trop.
    mal = _accepte(grand_livre.proposer_ecriture(
        reg, plan, cle_piece=f"saisie:facture_fournisseur:{ident}",
        piece={"type": "facture_fournisseur", "reference": ident}, nature="saisie", date_effet="2026-10-01",
        libelle="Carburant (fictif)", lignes_brutes=[L("5400", "99.99"), L("1400", "5.01"), L("1410", "9.98"),
                                                     L("2100", credit="114.98")],
        horodatage=H, origine="saisie"))["ecriture"]["ecriture_id"]
    _accepte(grand_livre.valider_ecriture(reg, plan, ecriture_id=mal, humain=HUMAIN, horodatage=H))
    # Un reçu saisi à la main qui débite la CTI : un écart nommé, jamais absorbé.
    recu = _accepte(grand_livre.proposer_ecriture(
        reg, plan, cle_piece="saisie:recu:R-1", piece={"type": "recu", "reference": "R-1"}, nature="saisie",
        date_effet="2026-10-05", libelle="Stationnement (fictif)",
        lignes_brutes=[L("5990", "10.00"), L("1400", "0.50"), L("1010", credit="10.50")],
        horodatage=H, origine="saisie"))["ecriture"]["ecriture_id"]
    _accepte(grand_livre.valider_ecriture(reg, plan, ecriture_id=recu, humain=HUMAIN, horodatage=H))
    cti = _rapprocher(reg, plan, taux, ap.factures_saisies(reg_ap))["intrants"]["tps_cti"]
    assert cti["ecarts"] == [
        {"facture_fournisseur_id": ident, "attendu_facture": "5.00", "au_grand_livre": "5.01",
         "raison": "montant différent"},
        {"facture_fournisseur_id": None, "raison": "mouvement d'une écriture non rattachée à une facture fournisseur",
         "au_grand_livre": "0.50"}]
    # La facture annulée après coup : son mouvement n'a plus de facture vivante.
    _accepte(ap.annuler_facture_fournisseur(
        facture_fournisseur_id=ident, motif="Erreur de fournisseur (fictif)", annule_par="comptable", role="finance",
        voie="appareil", horodatage=H, registre_cible=reg_ap, revision_attendue=0))
    resultat = _rapprocher(reg, plan, taux, ap.factures_saisies(reg_ap))
    assert resultat["intrants"]["tvq_rti"]["ecarts"] == [
        {"facture_fournisseur_id": ident, "au_grand_livre": "9.98",
         "raison": "mouvement de taxe sans facture fournisseur vivante datée dans la période"}]
    assert resultat["verdict"] == "ECART"


def test_une_facture_fournisseur_illisible_rend_le_rapprochement_en_ecart(plan, reg, reg_ap, taux):
    _sans_po(reg_ap, taux)
    facture = {**ap.factures_saisies(reg_ap)[0], "total_taxes": D("1.00")}
    resultat = _rapprocher(reg, plan, taux, [facture])
    assert resultat["factures_fournisseurs_illisibles"] == [
        {"facture_fournisseur_id": facture["facture_fournisseur_id"], "code": "REJ-GL-SOURCE-ILLISIBLE"}]
    assert resultat["verdict"] == "ECART"
    assert resultat["intrants"]["tps_cti"]["verdict"] == "CONCORDANT", "rien n'est attendu d'une pièce illisible"


def test_export_beancount_des_factures_fournisseurs_equilibre(plan, reg, reg_ap, taux, tmp_path):
    _trois_factures(reg_ap, taux)
    _comptabiliser(reg, plan, ap.factures_saisies(reg_ap))
    texte = grand_livre_beancount.ecrire_fichier_beancount(tmp_path / "ap.beancount", _etat(reg), plan).read_text(
        encoding="utf-8")
    assert "À valider auprès d'un comptable (CPA)" in texte and "version 2026-v2" in texte
    assert "Expenses:C5400-Carburant-Et-Entretien-Des-Vehicules" in texte
    assert "Liabilities:C2100-Comptes-Fournisseurs" in texte and "Assets:C1400-Tps-A-Recevoir-Cti-Credits-De" in texte
    transactions = [bloc for bloc in texte.split("\n\n") if " * " in bloc]
    assert len(transactions) == 3
    for transaction in transactions:
        montants = [D(ligne.split()[-2]) for ligne in transaction.splitlines() if ligne.endswith(" CAD")
                    and ligne.startswith("  ")]
        assert len(montants) == 4 and sum(montants) == 0
