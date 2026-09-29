"""PLAN T4.16 : la mention obligatoire de M5 est un TEST, plus une convention (audit M5 §5).

« Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle ou action réelle.
» (DEFINITION-PRODUIT §7 M5 et §13.3, qui retient cette formulation-là, pas celle de l'addendum.)

Trois preuves :
1. le texte du code est CELUI de la définition produit (lu dans le document, pas recopié) ;
2. le monde est fermé : chaque outil de M5 est classé, analyse ou hors analyse avec sa raison, donc un nouvel outil ne
  peut pas naître sans que la question soit posée ;
3. chaque sortie ACCEPTÉE d'un outil d'analyse porte la mention, telle quelle, que la vue soit complète ou masquée.
  Fictif (AGENTS.md).
"""

from __future__ import annotations

import contextlib
import json
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import analyse, encodage
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique

FICTIF = True
_RACINE_DEPOT = Path(__file__).resolve().parents[3]
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")


# --------------------------------------------------------------------------------------- 1. le texte
def test_la_mention_du_code_est_celle_de_la_definition_produit():
    definition = (_RACINE_DEPOT / "docs" / "produit" / "DEFINITION-PRODUIT.md").read_text(encoding="utf-8")

    assert MENTION == (
        "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle ou action "
        "réelle.")
    assert f"*« {MENTION} »*" in definition, "§7 M5 : la mention obligatoire, mot pour mot"
    assert "Retenir la seconde" in definition and "Préparation IA — validation Nathan/CPA requise" in definition
    assert "Préparation IA" not in MENTION, "la formulation de l'addendum n'est pas retenue (§13.3)"


def test_avec_mention_ajoute_la_cle_sans_toucher_a_l_original_et_ne_se_laisse_pas_remplacer():
    sortie = {"a": 1, "mention": "texte usurpé : tout est officiel"}

    resultat = analyse.avec_mention(sortie)

    assert resultat == {"a": 1, "mention": MENTION} and sortie["mention"] == "texte usurpé : tout est officiel"
    assert resultat is not sortie
    with pytest.raises(TypeError):
        analyse.avec_mention("pas un dictionnaire")


# ------------------------------------------------------------------------------ 2. le monde est fermé
def test_chaque_outil_de_m5_est_classe_analyse_ou_hors_analyse_avec_sa_raison():
    noms = {o.nom for o in m5_outils.outils()}

    assert noms == set(analyse.SORTIES_D_ANALYSE) | set(analyse.SORTIES_HORS_ANALYSE), (
        "un outil de M5 sans classement (ou un classement sans outil) : décider si sa sortie est une analyse")
    assert not set(analyse.SORTIES_D_ANALYSE) & set(analyse.SORTIES_HORS_ANALYSE)
    assert all(isinstance(raison, str) and len(raison) > 20 for raison in analyse.SORTIES_HORS_ANALYSE.values())


def test_les_outils_qui_calculent_ou_proposent_sont_des_analyses():
    attendues = {
        "m5_etat_tresorerie", "m5_lire_echeances_fiscales", "m5_lire_rentabilite_chantier",
        "m5_lister_comptes_a_payer", "m5_saisir_facture_fournisseur",
        # T4.15-c : chacun rend ce que le PO (ou les factures sans PO) doit à cet état, PROPOSÉ, jamais appliqué
        "m5_saisir_facture_sans_po", "m5_corriger_facture_fournisseur", "m5_annuler_facture_fournisseur"}
    assert set(analyse.SORTIES_D_ANALYSE) == attendues
    assert "m5_envoyer_facture" in analyse.SORTIES_HORS_ANALYSE
    assert "m5_enregistrer_paiement_facture" in analyse.SORTIES_HORS_ANALYSE


# --------------------------------------------------------------------- 3. les sorties acceptées la portent
@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-mention.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        # le propriétaire : corriger et annuler sont N4, la voie directe est celle du propriétaire
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345",
                                ["admin", "nathan_owner"])
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {
        "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12},
        "categories_depense_sans_po": ["carburant", "outils"]}}), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    yield url
    stockage.liberer()


@pytest.fixture
def par_nom():
    return {o.nom: o for o in m5_outils.outils()}


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=ADMIN):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _preparer_un_po():
    """Un PO reçu, pour que la saisie d'une facture fournisseur ait de quoi s'appuyer."""
    charge = {"evenement_id": "e-1", "po_id": "PO-1", "fournisseur_id": "gentek", "chantier_id": "CH-1",
              "horodatage_reception": "2026-09-15T09:00:00-04:00", "verdict_reception": "CONFORME",
              "statut_po": "received", "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": 0.15,
              "lignes": [{"materiau_id": "g", "quantite_demandee": "60", "quantite_recue": "60",
                          "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                          "prix_unitaire_reception": "5.00", "verdict_prix_reception": "PRIX_CATALOGUE",
                          "ecart_prix_critique": False}]}
    with stockage.transaction():
        m5_outils._recevoir_reception_enregistree(charge)


def _preparer_une_facture(par_nom):
    """Une facture de 10.00 $ (PO-1), cible de la correction et de l'annulation : son identifiant."""
    reponse = _appeler(par_nom, "m5_saisir_facture_fournisseur", {
        "po_id": "PO-1", "fournisseur_id": "gentek", "numero_facture": "F-0", "date_facture": "2026-09-14",
        "montant_avant_taxes": "10.00", "total_facture": None, "horodatage": "2026-09-20T10:00:00-04:00"})
    assert reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]["facture"]["facture_fournisseur_id"]


def _appels(ident):
    """Un appel ACCEPTÉ par outil d'analyse : `(nom, arguments)`. `ident` : la facture que M5 a déjà saisie."""
    return {
        "m5_etat_tresorerie": {},
        "m5_lire_echeances_fiscales": {"aujourd_hui": "2026-09-29"},
        "m5_lire_rentabilite_chantier": {},
        "m5_lister_comptes_a_payer": {},
        "m5_saisir_facture_fournisseur": {
            "po_id": "PO-1", "fournisseur_id": "gentek", "numero_facture": "F-1", "date_facture": "2026-09-14",
            "montant_avant_taxes": "300.00", "total_facture": None, "horodatage": "2026-09-20T10:00:00-04:00"},
        "m5_saisir_facture_sans_po": {
            "fournisseur_id": "Pétro-Nord (fictif)", "categorie": "carburant", "numero_facture": "C-1",
            "date_facture": "2026-09-14", "montant_avant_taxes": "100.00", "total_facture": None,
            "horodatage": "2026-09-20T10:00:00-04:00"},
        "m5_corriger_facture_fournisseur": {
            "facture_fournisseur_id": ident, "motif": "montant tapé de travers (fictif)", "numero_facture": None,
            "date_facture": None, "montant_avant_taxes": "20.00", "total_facture": None,
            "horodatage": "2026-09-21T10:00:00-04:00"},
        "m5_annuler_facture_fournisseur": {
            "facture_fournisseur_id": ident, "motif": "saisie sous le mauvais PO (fictif)",
            "horodatage": "2026-09-21T10:00:00-04:00"},
    }


def _la_mention(reponse, nom):
    """Où l'outil porte la mention : dans `resultat` pour l'état de trésorerie (forme d'avant, sans `accepte`), dans
    `resultat.resultat` pour les autres (`accepte` vrai)."""
    assert reponse["ok"] is True, reponse
    corps = reponse["resultat"]
    if nom != "m5_etat_tresorerie":
        assert corps["accepte"] is True, (nom, corps)
        corps = corps["resultat"]
    return corps


@pytest.mark.parametrize("nom", sorted(analyse.SORTIES_D_ANALYSE))
def test_chaque_sortie_acceptee_d_un_outil_d_analyse_porte_la_mention(par_nom, nom):
    _preparer_un_po()
    ident = _preparer_une_facture(par_nom)

    reponse = _appeler(par_nom, nom, _appels(ident)[nom])

    corps = _la_mention(reponse, nom)
    assert corps["mention"] == MENTION, nom


@pytest.mark.parametrize("nom", ["m5_etat_tresorerie", "m5_lire_echeances_fiscales", "m5_lister_comptes_a_payer",
                                 "m5_lire_rentabilite_chantier"])
def test_la_vue_masquee_porte_aussi_la_mention(par_nom, nom):
    _preparer_un_po()

    reponse = _appeler(par_nom, nom, {**_appels("apf-inutile")[nom], "autorise_couts": False})

    assert _la_mention(reponse, nom)["mention"] == MENTION, nom


def test_la_mention_est_dans_la_reponse_telle_que_le_modele_la_recoit(par_nom):
    """Pas seulement dans un dictionnaire : dans le JSON de la réponse (montants en texte, mention en clair)."""
    _preparer_un_po()

    texte = json.dumps(_appeler(par_nom, "m5_lister_comptes_a_payer", {}), ensure_ascii=False)

    assert MENTION in texte


def test_les_sorties_hors_analyse_n_ont_pas_a_la_porter_mais_le_classement_dit_pourquoi(par_nom):
    """Un calcul déterministe (taxes) ou l'écriture d'un maillon n'est pas une analyse : le classement en donne la
    raison, et la sortie ne porte pas la mention (elle ne prétend rien)."""
    reponse = _appeler(par_nom, "m5_calculer_taxes_tps_tvq", {"montant_avant_taxes": "100.00"}, None)

    assert reponse["resultat"]["accepte"] is True and "mention" not in json.dumps(reponse)
    assert "taux versionnés" in analyse.SORTIES_HORS_ANALYSE["m5_calculer_taxes_tps_tvq"]


def test_une_sortie_refusee_ne_pretend_a_aucune_analyse(par_nom):
    reponse = _appeler(par_nom, "m5_lire_echeances_fiscales", {"aujourd_hui": "2027-03-01"})

    assert reponse["resultat"]["accepte"] is False and "mention" not in reponse["resultat"]


def test_la_mention_ne_change_ni_un_montant_ni_l_etat_id(par_nom):
    """Ajoutée APRÈS le calcul : l'empreinte de l'état financier est celle du contenu gelé, sans la mention."""
    with stockage.transaction():
        m5_outils._registre_mouvements(None)  # registre vide : rien à sommer
    etat = _appeler(par_nom, "m5_etat_tresorerie", {})["resultat"]
    sans_mention = {cle: etat[cle] for cle in ("type", "role", "solde", "argent_disponible", "taux_utilises")}
    sans_mention = {**sans_mention, "solde": Decimal(sans_mention["solde"]),
                    "argent_disponible": Decimal(sans_mention["argent_disponible"])}
    assert etat["etat_id"] == encodage.empreinte(sans_mention)
