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
OWNER_CONSOLE = contexte.IdentiteAppelante(personne="admin.fictif", role="nathan_owner", source="console")


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
        "m5_etat_tresorerie", "m5_lire_echeances_fiscales", "m5_lire_calendrier_obligations",
        "m5_lire_rentabilite_chantier",
        "m5_lister_comptes_a_payer", "m5_saisir_facture_fournisseur",
        # T4.15-c : chacun rend ce que le PO (ou les factures sans PO) doit à cet état, PROPOSÉ, jamais appliqué
        "m5_saisir_facture_sans_po", "m5_corriger_facture_fournisseur", "m5_annuler_facture_fournisseur",
        # T4.16-d : la prévision des flux connus et datés, sous seuil et délais déclarés
        "m5_prevoir_tresorerie",
        # T4.19-b : le cash libre constaté et publié au bus (le même calcul que l'état de trésorerie)
        "m5_constater_cash_libre", "m5_preparer_decision_capital",
        # M5.16 : dossier stratégique préparatoire depuis les sources FinanceCore
        "m5_preparer_dossier_decision_cfo", "m5_preparer_brut_regulier", "m5_preparer_dossier_webras",
        "m5_prevoir_tresorerie_contrats"}
    assert set(analyse.SORTIES_D_ANALYSE) == attendues
    assert "m5_envoyer_facture" in analyse.SORTIES_HORS_ANALYSE
    assert "m5_enregistrer_paiement_facture" in analyse.SORTIES_HORS_ANALYSE
    assert "m5_enregistrer_echeancier_contrat" in analyse.SORTIES_HORS_ANALYSE
    assert "m5_revoquer_echeancier_contrat" in analyse.SORTIES_HORS_ANALYSE


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
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-12345",
                                ["employee"])
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {
        "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12},
        "categories_depense_sans_po": ["carburant", "outils"],
        "prevision": {"horizon_semaines": 6, "delai_encaissement_clients_jours": 30,
                      "delai_paiement_fournisseurs_jours": 30}}}), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    yield url
    stockage.liberer()


@pytest.fixture
def par_nom():
    def lecteur(technicien_id, debut, fin, fuseau):
        return {"ok": True, "resultat": {"accepte": True, "resultat": {
            "technicien_id": technicien_id,
            "periode": {"debut": debut, "fin": fin, "fuseau": fuseau},
            "minutes_regulieres": 60, "ligne_id": "a" * 64, "revision": 1,
            "empreinte_sources": "b" * 64, "couverture_complete": True,
            "classification_reguliere_confirmee": True,
        }}}

    return {o.nom: o for o in m5_outils.outils(lecteur_heures_m4=lecteur)}


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
    """Une facture de 10.00 $ (PO-1), cible de la correction et de l'annulation : son identifiant et sa révision, lus
    sur la facture rendue (statut SAISIE, sans `corrections` : révision 0)."""
    reponse = _appeler(par_nom, "m5_saisir_facture_fournisseur", {
        "po_id": "PO-1", "fournisseur_id": "gentek", "numero_facture": "F-0", "date_facture": "2026-09-14",
        "montant_avant_taxes": "10.00", "total_facture": None, "horodatage": "2026-09-20T10:00:00-04:00"})
    assert reponse["resultat"]["accepte"] is True, reponse
    facture = reponse["resultat"]["resultat"]["facture"]
    assert facture["statut"] == "SAISIE" and "corrections" not in facture, facture
    return facture["facture_fournisseur_id"], 0


def _appels(ident, revision=None):
    """Un appel ACCEPTÉ par outil d'analyse : `(nom, arguments)`. `ident` : la facture que M5 a déjà saisie ;
    `revision` : sa révision lue (correction, annulation)."""
    return {
        "m5_etat_tresorerie": {},
        "m5_lire_echeances_fiscales": {"aujourd_hui": "2026-09-29"},
        "m5_lire_calendrier_obligations": {"aujourd_hui": "2026-09-29"},
        "m5_lire_rentabilite_chantier": {},
        "m5_lister_comptes_a_payer": {},
        "m5_prevoir_tresorerie": {"aujourd_hui": "2026-09-29", "horizon_semaines": 4},
        "m5_constater_cash_libre": {"aujourd_hui": "2026-09-29"},
        "m5_preparer_decision_capital": {
            "actif": "équipement", "prix": "50000.00", "source_prix": "Offre fournisseur Q-52",
            "prix_valide_jusqua": "2026-10-30",
            "aujourd_hui": "2026-09-29",
            "offre_financement": {"source": "Offre prêt P-8", "mise_de_fonds": "8000.00",
                                  "paiement_mensuel": "950.00", "mois": 60},
            "offre_location": {"source": "Offre location L-2", "mise_de_fonds": "2500.00",
                                  "paiement_mensuel": "1100.00", "mois": 48},
        },
        "m5_preparer_dossier_decision_cfo": {
            "aujourd_hui": "2026-09-29", "question_posee": "Question CFO de test fictive",
        },
        "m5_preparer_brut_regulier": {
            "employee_person_id": "employe.fictif", "debut": "2026-09-14", "fin": "2026-09-14",
            "fuseau": "America/Montreal", "politique_arrondi": "centime_demi_superieur",
            "hypothese_arrondi": "Hypothèse de test fictive, non validée", "sources_attendues": None,
        },
        "m5_preparer_dossier_webras": {
            "employee_person_id": "employe.fictif", "debut": "2026-09-14", "fin": "2026-09-14",
            "fuseau": "America/Montreal", "politique_arrondi": "centime_demi_superieur",
            "hypothese_arrondi": "Hypothèse de test fictive, non validée", "sources_attendues": None,
            "date_paie": "2026-09-18", "periodes_annuelles": 26,
            "revenu_imposable_cad": "62.50", "reference_revenu_imposable": "Assiette fictive ASS-001",
        },
        "m5_prevoir_tresorerie_contrats": {"aujourd_hui": "2026-09-29"},
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
            "horodatage": "2026-09-21T10:00:00-04:00", "revision_attendue": revision},
        "m5_annuler_facture_fournisseur": {
            "facture_fournisseur_id": ident, "motif": "saisie sous le mauvais PO (fictif)",
            "horodatage": "2026-09-21T10:00:00-04:00", "revision_attendue": revision},
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
    ident, revision = _preparer_une_facture(par_nom)
    if nom == "m5_preparer_decision_capital":
        _appeler(par_nom, "m5_enregistrer_mouvement", {
            "montant": "100000.00", "type_mouvement": "ENCAISSEMENT",
            "horodatage": "2026-09-28T12:00:00+00:00", "classe_retention": "STANDARD", "source": "relevé bancaire"})
        manifeste = yaml.safe_load(m5_outils._MANIFESTE.read_text(encoding="utf-8"))
        manifeste["configuration"]["fiscal"].update({"taxes_remises_jusqu_au": "2026-06-30"})
        manifeste["configuration"]["obligations_declarees"] = {
            cle: {"montant": "0.00", "source": "registre validé", "au": "2026-09-28"}
            for cle in ("paies", "das", "dettes", "reserves")}
        m5_outils._MANIFESTE.write_text(yaml.safe_dump(manifeste), encoding="utf-8")

    if nom in {"m5_preparer_brut_regulier", "m5_preparer_dossier_webras"}:
        contrat = _appeler(par_nom, "m5_enregistrer_contrat_horaire", {
            "employee_person_id": "employe.fictif", "contrat_id": "PAIE-FICTIF-001",
            "valide_du": "2026-09-01", "valide_jusqu_au": "2026-10-01", "fuseau": "America/Montreal",
            "devise": "CAD", "taux_horaire": "31.25", "source_humaine": "Source fictive RH-1",
            "date_source": "2026-08-31", "revision_attendue": 0, "ligne_id_attendue": "",
            "motif": "Enregistrement initial fictif",
        })
        assert contrat["resultat"]["accepte"] is True, contrat
        arguments = _appels(ident)[nom]
        if nom == "m5_preparer_dossier_webras":
            brut = _appeler(
                par_nom, "m5_preparer_brut_regulier", _appels(ident)["m5_preparer_brut_regulier"], OWNER_CONSOLE,
            )
            assert brut["resultat"]["accepte"] is True, brut
            sources = brut["resultat"]["resultat"]["sources"]
            arguments["sources_attendues"] = {
                "heures_m4": {key: sources["heures_m4"][key] for key in ("ligne_id", "revision", "empreinte_sources")},
                "contrat_m5": {key: sources["contrat_m5"][key] for key in ("contrat_id", "revision", "ligne_id")},
            }
        reponse = _appeler(par_nom, nom, arguments, OWNER_CONSOLE)
    elif nom == "m5_prevoir_tresorerie_contrats":
        reponse = _appeler(par_nom, nom, _appels(ident)[nom], OWNER_CONSOLE)
    else:
        reponse = _appeler(par_nom, nom, _appels(ident, revision)[nom])

    corps = _la_mention(reponse, nom)
    assert corps["mention"] == MENTION, nom
    if nom == "m5_preparer_decision_capital":
        contexte_financier = corps["contexte_financier"]
        assert contexte_financier["cash_libre"]["calculable"] is True
        assert {c["id"] for c in contexte_financier["cash_libre"]["composantes"]} == {
            "taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves",
        }
        assert contexte_financier["comptes_a_recevoir"]["source"]["statut"] == "VERIFIE"
        assert contexte_financier["devis_acceptes"]["source"]["statut"] == "EVENEMENTS_M3_RECUS"
        assert contexte_financier["termes_contractuels_signes"]["statut"] == "NON_DISPONIBLE"
        assert contexte_financier["provenance_des_offres"]["statut"] == "REFERENCE_MANUELLE_NON_VERIFIEE"


def test_decision_capital_refuse_si_paies_ou_derniere_remise_taxes_manquent(par_nom):
    _appeler(par_nom, "m5_enregistrer_mouvement", {
        "montant": "100000.00", "type_mouvement": "ENCAISSEMENT",
        "horodatage": "2026-09-28T12:00:00+00:00", "classe_retention": "STANDARD", "source": "relevé bancaire"})
    manifeste = yaml.safe_load(m5_outils._MANIFESTE.read_text(encoding="utf-8"))
    manifeste["configuration"]["obligations_declarees"] = {
        cle: {"montant": "0.00", "source": "registre validé", "au": "2026-09-28"}
        for cle in ("das", "dettes", "reserves")}
    m5_outils._MANIFESTE.write_text(yaml.safe_dump(manifeste), encoding="utf-8")

    reponse = _appeler(par_nom, "m5_preparer_decision_capital", {
        "actif": "camion", "prix": "95000.00", "source_prix": "Offre concessionnaire C-9",
        "prix_valide_jusqua": "2026-10-30",
        "aujourd_hui": "2026-09-29",
        "offre_financement": {"source": "Offre prêt P-9", "mise_de_fonds": "5000.00",
                              "paiement_mensuel": "1600.00", "mois": 60},
        "offre_location": {"source": "Offre bailleur L-9", "mise_de_fonds": "3000.00",
                           "paiement_mensuel": "1800.00", "mois": 48},
    })

    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-CAPITAL-CASH-LIBRE-NON-CALCULABLE"
    manque = reponse["resultat"]["verdict"]["manque"]
    assert {item["composante"] for item in manque} >= {"paies", "taxes_a_remettre"}


@pytest.mark.parametrize("nom", ["m5_etat_tresorerie", "m5_lire_echeances_fiscales", "m5_lister_comptes_a_payer",
                                 "m5_lire_rentabilite_chantier", "m5_prevoir_tresorerie"])
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
