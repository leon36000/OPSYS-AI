"""PLAN T4.20 — le profil admin de l'app (« À voir », « Chiffres », « Chantiers du jour ») lit par la vraie porte
d'appareil (E2E moteur).

DEFINITION-PRODUIT §9.5 : « le propriétaire approuve tout depuis le téléphone » ; « M4 : dispatch du jour, retards,
file de complétion » ; « M5 : trésorerie et cash libre réel » ; « M8 : tableau de bord exécutif ». Les écrans de
`mobile/app/(admin)/` (`admin`, `chiffres`, `chantiers`) appellent huit outils de la portée `admin` ; ce test les
appelle comme l'app, sous le nom nu, avec le rôle `admin`, par la même règle que le core (`PorteAppareil`, relue dans
le fork, appliquée au vrai moteur HTTP MCP sur une base temporaire).

La journée du propriétaire, dans l'ordre où l'app la lirait (les dates sont fictives ; l'instant du serveur est celui
de l'horloge de test) :

1. instance neuve, rien de déclaré : chaque outil dit ce qui manque (vue exécutive « non calculable », trésorerie sans
   solde, horizon de prévision et fréquence fiscale à déclarer), jamais un zéro ;
2. finances déclarées (fréquence TPS/TVQ, obligations, prévision) : solde 20 000,00, réserve 500,00, une facture
   cliente, une réception de M6 : cash libre, prévision semaine par semaine et échéances fiscales, à la cent près ;
   puis les mêmes outils avec une déclaration en moins (paies, délais) : « non calculable, manque X » ;
3. quatre chantiers : A terminé avec un écart de matériaux de 40 % (ni prix au livre de M6 ni taux horaire : la marge
   réelle est « non calculable » et dit pourquoi), E terminé sans histoire (prix et taux déclarés : marge réelle
   calculée), B et C planifiés (un lead v2, un lead v1), D né d'un devis accepté (`a_planifier`) ;
4. ce que l'admin lit ensuite : les interventions et leur préparation volet par volet (`ok`, `manque`,
   `non_verifiable`), le digest du jour, l'accueil « À voir » (attentes des départements, puis la demande de revue N4
   qu'il a lui-même proposée), la vue exécutive.

Ce que ces tests prouvent :
- chaque outil de l'app répond à l'appareil `admin`, sans rien écrire (l'état du moteur est comparé avant et après),
  sans troncature (`Capacites`, 6 000 caractères) ;
- l'employé et le vendeur reçoivent 403 sur ces outils (seul `m4_lister_interventions` est aussi celui de l'employé :
  filtré à SES interventions, jamais tronqué ni élargi) ; la règle est le nom NU ;
- la FORME de chaque réponse est celle de `mobile/src/admin/fixtures/reponses-moteur.json`, que les tests Jest font
  passer par les lecteurs de l'app ; les arguments de chaque appel sont ceux que les constructeurs de l'app produisent ;
- l'app et le serveur parlent la même langue : noms d'outils (dans la portée `admin`), catalogues (statuts
  d'intervention, volets de préparation, composantes du cash libre, unités de l'entonnoir, erreurs passagères).
Ce que ces tests ne prouvent PAS : les écrans (Jest, `mobile/`) ni le core.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import m5_financecore.outils as m5_outils
import m6_material_control.outils as m6_outils
import pytest
import yaml
from harnais_e2e import Moteur, PorteAppareil, Reponse, iso
from harnais_e2e_chantier import (
    MATERIAU_ID,
    AppEmploye,
    Chantier,
    debut_de_journee,
    png_minimal,
    preparer_chantier,
    receptionner_materiel_args,
)
from m4_field_ops import ecarts as ecarts_m4
from m4_field_ops import etats as etats_m4
from m4_field_ops import preparation as preparation_m4
from m5_financecore import calendrier_fiscal, cash_libre, facturation, taux_fiscaux
from m8_analytics import mesures_chantier, nombres

from opsys import cli, evenements, idempotence, openclaw, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique

FICTIF = True
SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
RACINE = Path(__file__).resolve().parents[2]
MOBILE_SRC = RACINE / "mobile" / "src"
FIXTURE_APP = MOBILE_SRC / "admin" / "fixtures" / "reponses-moteur.json"
ENV_REGENERER = "OPSYS_REGENERER_FIXTURES_MOBILE"
LIMITE_TRONCATURE = 6000  # `jetons.LIMITE_SORTIE_DEFAUT`


# -- ce que l'app lit dans son propre code ---------------------------------------------------------------------------
def _source(relatif: str) -> str:
    return (MOBILE_SRC / relatif).read_text(encoding="utf-8")


def _liste_ts(source: str, nom: str) -> list[str]:
    trouve = re.search(rf"export const {nom}: readonly string\[\] = \[(.*?)\];", source, re.DOTALL)
    assert trouve is not None, f"{nom} n'est plus dans l'app"
    return re.findall(r'"([^"]+)"', trouve.group(1))


def _constante_ts(source: str, nom: str) -> str:
    trouve = re.search(rf'export const {nom} = "([^"]+)";', source)
    assert trouve is not None, f"{nom} n'est plus dans l'app"
    return trouve.group(1)


def _outils_de_l_app() -> dict[str, str]:
    outils: dict[str, str] = {}
    for relatif in FICHIERS_DES_OUTILS:
        outils.update(re.findall(r'export const (OUTIL_[A-Z_0-9]+) = "([^"]+)"', _source(relatif)))
    return outils


AUJOURD_HUI = "2026-09-29"  # le jour de référence que l'app passe à M5 (l'heure de l'appareil)
JOUR_DU_DIGEST = "2026-09-21"  # le jour où A se termine
REFERENCE_DU_DIGEST = "2026-09-21T18:00:00-04:00"
SEUIL_DE_STOCK = {MATERIAU_ID: {"seuil_reapprovisionnement": 450, "quantite_cible": 600}}
# Les statuts que « Chantiers du jour » demande, un appel chacun (`m4_lister_interventions` ne se pagine pas et sa
# réponse est tronquée au-delà de 6 000 caractères : un appel par statut borne chaque groupe, et l'historique
# terminé ou annulé n'est jamais demandé). LUS DANS L'APP : le scénario demande exactement ce que l'écran demande.
STATUTS_DU_DISPATCH = tuple(_liste_ts(_source("m4/dispatch.ts"), "STATUTS_DU_DISPATCH"))
_CHEMIN_DE_TEST = re.compile(r"/tmp/pytest-of-[^/]+/pytest-\d+/[^/]+/opsys-home")

PO = "PO-E2E-ADM-1"
FOURNISSEUR = "gentek-fictif"
CONFIGURATION_M5 = {
    "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "2026-06-30"},
    "obligations_declarees": {
        "paies": {"montant": "3000.00", "source": "brouillon de paie (fictif)", "au": "2026-09-25"},
        "das": {"montant": "900.00", "source": "estimation du CPA (fictive)", "au": "2026-09-25"},
        "dettes": {"montant": "400.00", "source": "relevé du prêt camion (fictif)", "au": "2026-09-01"},
    },
    "prevision": {
        "horizon_semaines": 6,
        "seuil_alerte": {"montant": "18000.00", "source": "décision de Nathan (fictive)", "au": "2026-09-25"},
        "delai_encaissement_clients_jours": 30, "delai_paiement_fournisseurs_jours": 30,
        "echeances_obligations": {"paies": "2026-10-09", "das": "2026-10-15", "dettes": "2026-10-31"},
    },
}
# Les outils que l'app appelle (nom nu) : `OUTIL_*` des contrats du profil admin, lus dans leur source.
FICHIERS_DES_OUTILS = ("approbations/chargeur.ts", "m8/vueExecutive.ts", "m5/tresorerie.ts", "m4/dispatch.ts")
OUTILS_ATTENDUS = {
    "m9_lister_demandes_approbation", "m8_lire_vue_executive", "m5_etat_tresorerie", "m5_prevoir_tresorerie",
    "m5_lire_echeances_fiscales", "m4_lister_interventions", "m4_produire_digest", "m4_verifier_preparation",
}
# Les seuls outils que l'app admin partage avec un autre rôle : l'employé lit SES interventions.
PARTAGE_AVEC_L_EMPLOYE = {"m4_lister_interventions"}


# -- les gestes de l'amont (hors porte d'appareil : aucun n'est un geste de l'app admin) ------------------------------
def _declarer_m5(tmp_path: Path, monkeypatch: Any, configuration: dict[str, Any]) -> None:
    """Nathan déclare ses choix dans `department.yaml/configuration` de M5 (relu à chaque appel)."""
    manifeste = tmp_path / "department-m5-admin-e2e.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": configuration}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)


def _declarer_seuil_de_stock(tmp_path: Path, monkeypatch: Any) -> None:
    """Le `department.yaml` de M6 dont seul le bloc de réapprovisionnement change : M6 le relit à chaque appel."""
    reel = yaml.safe_load(m6_outils._MANIFESTE.read_text(encoding="utf-8"))
    reappro = {"articles": SEUIL_DE_STOCK}
    manifeste = {**reel, "configuration": {**reel["configuration"], "reapprovisionnement": reappro}}
    chemin = tmp_path / "department-m6-admin-e2e.yaml"
    chemin.write_text(yaml.safe_dump(manifeste, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(m6_outils, "_MANIFESTE", chemin)


def _prix_au_livre_de_m6(moteur: Moteur, prix: float = 8.0) -> None:
    m6 = {o.nom: o for o in moteur.departements["m06-material-control"].charger_outils()}
    reponse = executer_atomique(m6["m6_enregistrer_prix"], {
        "materiau_id": MATERIAU_ID, "fournisseur_id": FOURNISSEUR, "prix_unitaire": prix, "devise": "CAD",
        "date_effet": "2026-09-01", "source_document": None})
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse


def _preparer_finance(moteur: Moteur) -> None:
    """Le solde, la réserve, la facture cliente envoyée et la réception de M6 (par le vrai bus)."""
    m5 = {o.nom: o for o in moteur.departements["m05-financecore"].charger_outils()}
    for montant, type_mouvement in (("20000.00", "ENCAISSEMENT"), ("500.00", "PROVISION")):
        reponse = executer_atomique(m5["m5_enregistrer_mouvement"], {
            "montant": montant, "type_mouvement": type_mouvement, "horodatage": "2026-09-10T12:00:00-04:00",
            "classe_retention": "STANDARD", "source": "e2e-fictif"})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    taux, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    with stockage.transaction():
        registre_factures = m5_outils._registre_factures(None)
        _, verdict = facturation.creer_facture_brouillon(
            "F-E2E-ADM-1", "CH-E2E-FIN-1", "D-E2E-FIN-1", "C-E2E-FIN-1",
            [{"description": "gouttières (fictif)", "quantite": "1", "unite": "forfait", "prix_unitaire": "5000.00",
              "reference_ligne_devis": "L-1"}], "2026-09-14T09:00:00-04:00", taux, registre_factures)
        assert verdict is None, verdict
        assert facturation.envoyer_facture("F-E2E-ADM-1", "2026-09-14T09:30:00-04:00", registre_factures)[1] is None
        charge = {
            "evenement_id": "evt-e2e-adm-1", "po_id": PO, "fournisseur_id": FOURNISSEUR, "chantier_id": "CH-E2E-FIN-1",
            "horodatage_reception": "2026-09-14T09:00:00-04:00", "verdict_reception": "CONFORME",
            "statut_po": "received", "hash_maillon": "d" * 64, "seuil_ecart_prix_pourcentage": None,
            "lignes": [{"materiau_id": "gouttiere-5po-fictif", "quantite_demandee": "60", "quantite_recue": "60",
                        "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                        "prix_unitaire_reception": None, "verdict_prix_reception": "INDETERMINE",
                        "ecart_prix_critique": None}]}
        evenements.publier("m6.reception_enregistree", "m06-material-control", charge,
                           evenement_id=charge["evenement_id"])
    resume = moteur.drainer_bus(moteur.horloge.maintenant)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume


def _journee_jusqu_a_la_completion(app: AppEmploye) -> Reponse:
    """La journée de `AppEmploye.journee_jusqu_a_la_completion`, geste pour geste. Une seule différence : avec
    plusieurs chantiers dans la même base, « chantiers du jour » les liste tous, pas seulement celui-ci."""
    interventions = {i["intervention_id"] for i in app.chantiers_du_jour().resultat}
    assert app.chantier.intervention_id in interventions
    app.attendre(minutes=1)
    assert app.donner_consentement_gps().metier["accepte"] is True
    app.attendre(minutes=29)
    assert app.en_route().metier["accepte"] is True
    app.attendre(minutes=30)
    assert app.pointer("arrivee").metier["accepte"] is True
    app.attendre(hours=2, minutes=55)
    photo = app.deposer_fichier(png_minimal(largeur=4))
    signature = app.deposer_fichier(png_minimal(largeur=2))
    app.attendre(minutes=5)
    assert app.pointer("depart").metier["accepte"] is True
    app.attendre(minutes=5)
    return app.terminer(photo, signature)


def _chantier_termine(moteur: Moteur, equipe: dict[str, Any], suffixe: str, jour: int, quantite: float) -> Chantier:
    """Un chantier de bout en bout jusqu'à la variance : le matériel arrive, l'employé fait sa journée et
    « Terminer », le bus livre la complétion, l'employé déclare `quantite` pi utilisés, le bus livre la variance."""
    chantier = preparer_chantier(moteur.departements, suffixe=suffixe, technicien="etienne",
                                 debut=debut_de_journee(jour))
    moteur.horloge.maintenant = chantier.debut
    moteur.drainer_bus(moteur.horloge.maintenant)  # le devis accepté est livré à M6 (prévu de matériaux)
    reception = equipe["admin"].appeler(
        "m6_receptionner_commande", receptionner_materiel_args(chantier), cle=f"mut-reception-{suffixe}",
        horodatage_appareil=iso(chantier.debut))
    assert reception.metier["accepte"] is True, reception.metier
    app = AppEmploye(moteur, equipe["employe"], chantier)
    completion = _journee_jusqu_a_la_completion(app)
    wct_id = completion.resultat["wct_id"]
    moteur.drainer_bus(moteur.horloge.maintenant)
    app.attendre(minutes=5)
    assert app.declarer_materiaux(wct_id, quantite).metier["accepte"] is True
    moteur.drainer_bus(moteur.horloge.maintenant)
    return chantier


def _chantier_planifie(moteur: Moteur, suffixe: str, jour: int, version_lead: int) -> Chantier:
    """Un chantier planifié et assigné, jamais commencé : le devis est livré à M6 (réservation) et à M4."""
    chantier = preparer_chantier(moteur.departements, suffixe=suffixe, technicien="etienne",
                                 debut=debut_de_journee(jour), version_lead=version_lead)
    moteur.horloge.maintenant = chantier.debut
    moteur.drainer_bus(moteur.horloge.maintenant)
    return chantier


def _devis_accepte_a_planifier(moteur: Moteur, lead_id: str, devis_id: str) -> None:
    """Un devis accepté que le bus livre à M4 et à M6 SEULS : il naît `a_planifier`. Les autres départements ne le
    lisent pas (un lead inconnu de M2 partirait en quarantaine, légitimement)."""
    evenements.publier(
        "m1.lead_qualifie", "m01-front-office",
        {"lead": {"schema_version": 2, "lead_id": lead_id, "conversation_id": f"sms-{lead_id}",
                  "contact": {"nom": "Client Fictif", "telephone": "+15145550142"}, "service": "gouttieres",
                  "ville": "Repentigny", "urgence_declaree": False, "canal": "texte", "source": "sms"},
         "horodatage": iso(moteur.horloge.maintenant), "signal_id": f"sms:{lead_id}"},
        evenement_id=f"m1-lead-qualifie-{lead_id}")
    evenements.publier(
        "m3.devis_accepte", "m03-estimation",
        {"devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
         "lignes": [{"reference_ligne": f"{devis_id}-L0", "description": "Gouttières (fictif)", "quantite": "40",
                     "unite": "pi", "prix_unitaire": "10.00", "prix_ligne": "400.00",
                     "reference_besoin_materiau": MATERIAU_ID}],
         "cout_total": "300.00", "prix_total": "400.00", "taux_marge": "0.25",
         "horodatage_acceptation": iso(moteur.horloge.maintenant)},
        evenement_id=f"m3-devis-accepte-{devis_id}")
    departements = {nom: moteur.departements[nom] for nom in ("m04-field-ops", "m06-material-control")}
    for _ in range(10):
        resume = evenements.repartir(departements, maintenant=iso(moteur.horloge.maintenant))
        assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
        if resume["livres"] == 0:
            return
    raise AssertionError("le bus n'a pas atteint le repos")


# -- l'enregistreur : ce que l'app envoie et ce que le moteur répond ------------------------------------------------
class Enregistreur:
    """Chaque lecture de l'écran : l'appel (outil et arguments exacts) et l'enveloppe que l'app reçoit (`corps.result`),
    c'est-à-dire ce que `mobile/src/admin/fixtures/reponses-moteur.json` garde et que les tests Jest lisent."""

    def __init__(self, moteur: Moteur, admin: PorteAppareil) -> None:
        self.moteur = moteur
        self.admin = admin
        self.appels: dict[str, dict[str, Any]] = {}
        self.reponses: dict[str, Any] = {}

    def lire(self, nom: str, outil: str, args: dict[str, Any] | None = None, porte: PorteAppareil | None = None,
             ) -> Reponse:
        """Une lecture : HTTP 200, jamais tronquée par le socle, et RIEN d'écrit dans le moteur."""
        args = dict(args or {})
        avant = self.moteur.empreinte_etat()
        reponse = (porte or self.admin).appeler(outil, args)
        assert reponse.statut == 200, (nom, reponse.corps)
        mesure = reponse.mesure
        assert mesure.tronque is False and mesure.octets_texte < LIMITE_TRONCATURE, (nom, mesure)
        assert self.moteur.empreinte_etat() == avant, f"{nom} : lire n'écrit rien"
        assert nom not in self.reponses, nom
        self.appels[nom] = {"outil": outil, "args": args}
        self.reponses[nom] = _normaliser(reponse.enveloppe)
        return reponse


def _normaliser(valeur: Any) -> Any:
    """Le chemin d'un fichier du serveur de test (le message d'un refus le nomme) change à chaque exécution : la fixture
    garde un chemin stable, pour ne pas changer d'un octet à chaque régénération."""
    if isinstance(valeur, dict):
        return {cle: _normaliser(v) for cle, v in valeur.items()}
    if isinstance(valeur, list):
        return [_normaliser(v) for v in valeur]
    if isinstance(valeur, str):
        return _CHEMIN_DE_TEST.sub("/srv/opsys", valeur)
    return valeur


def _forme(valeur: Any) -> Any:
    """La FORME d'une réponse : ses clés et le type de chaque valeur, jamais les valeurs elles-mêmes (une liste est
    décrite par son premier élément). C'est ce que les lecteurs de l'app exigent, et ce qui change quand le serveur
    change de contrat."""
    if isinstance(valeur, dict):
        return {cle: _forme(v) for cle, v in sorted(valeur.items())}
    if isinstance(valeur, list):
        return [_forme(valeur[0])] if valeur else []
    if valeur is None:
        return "null"
    return type(valeur).__name__


def _composantes(cash: dict[str, Any]) -> dict[str, Any]:
    return {c["id"]: c for c in cash["composantes"]}


def _enregistrer_la_journee(moteur: Moteur, equipe: dict[str, Any], tmp_path: Path, monkeypatch: Any,
                            declarer_services: Any) -> Enregistreur:
    admin = equipe["admin"]
    enr = Enregistreur(moteur, admin)
    arguments_m5 = {"aujourd_hui": AUJOURD_HUI}

    # ---- 1. instance neuve : rien de déclaré, rien n'est supposé ------------------------------------------------
    enr.lire("a_voir_vide", "m9_lister_demandes_approbation")
    enr.lire("vue_executive_vide", "m8_lire_vue_executive")
    enr.lire("tresorerie_sans_solde", "m5_etat_tresorerie")
    enr.lire("prevision_horizon_a_declarer", "m5_prevoir_tresorerie", arguments_m5)
    enr.lire("echeances_frequence_a_declarer", "m5_lire_echeances_fiscales", arguments_m5)
    enr.lire("interventions_planifiee_vide", "m4_lister_interventions", {"statut": "planifiee"})
    enr.lire("digest_vide", "m4_produire_digest",
             {"date_cible": JOUR_DU_DIGEST, "horodatage_reference": REFERENCE_DU_DIGEST})
    enr.lire("preparation_inconnue", "m4_verifier_preparation", {"intervention_id": "intervention-fantome"})

    # ---- 2. les finances : déclarées par Nathan, puis avec une déclaration en moins -----------------------------
    _declarer_m5(tmp_path, monkeypatch, CONFIGURATION_M5)
    _preparer_finance(moteur)
    enr.lire("tresorerie", "m5_etat_tresorerie")
    enr.lire("prevision", "m5_prevoir_tresorerie", arguments_m5)
    enr.lire("echeances", "m5_lire_echeances_fiscales", arguments_m5)

    sans_paies = copy_sans(CONFIGURATION_M5, ("obligations_declarees", "paies"))
    _declarer_m5(tmp_path, monkeypatch, sans_paies)
    enr.lire("tresorerie_sans_paies", "m5_etat_tresorerie")
    enr.lire("prevision_sans_paies", "m5_prevoir_tresorerie", arguments_m5)

    prevision = CONFIGURATION_M5["prevision"]
    sans_seuil = {**CONFIGURATION_M5, "prevision": {cle: v for cle, v in prevision.items() if cle != "seuil_alerte"}}
    _declarer_m5(tmp_path, monkeypatch, sans_seuil)
    enr.lire("prevision_sans_seuil", "m5_prevoir_tresorerie", arguments_m5)
    seuil_bas = {"montant": "1000.00", "source": "décision de Nathan (fictive)", "au": "2026-09-25"}
    _declarer_m5(tmp_path, monkeypatch, {**CONFIGURATION_M5, "prevision": {**prevision, "seuil_alerte": seuil_bas}})
    enr.lire("prevision_sans_alerte", "m5_prevoir_tresorerie", arguments_m5)
    remises_anciennes = {**CONFIGURATION_M5["fiscal"], "taxes_remises_jusqu_au": "2026-03-31"}
    _declarer_m5(tmp_path, monkeypatch, {**CONFIGURATION_M5, "fiscal": remises_anciennes})
    enr.lire("echeances_en_retard", "m5_lire_echeances_fiscales", arguments_m5)

    _declarer_m5(tmp_path, monkeypatch, {**CONFIGURATION_M5, "prevision": {**prevision, "horizon_semaines": 26}})
    enr.lire("prevision_longue_page_1", "m5_prevoir_tresorerie", arguments_m5)
    depart = enr.reponses["prevision_longue_page_1"]["resultat"]["resultat"]["prochain_depart"]
    if depart is not None:
        enr.lire("prevision_longue_page_2", "m5_prevoir_tresorerie", {**arguments_m5, "depart": depart})
    _declarer_m5(tmp_path, monkeypatch, CONFIGURATION_M5)

    # ---- 3. les chantiers ------------------------------------------------------------------------------------------
    declarer_services()
    _declarer_seuil_de_stock(tmp_path, monkeypatch)
    # A : ni prix au livre de M6 ni taux horaire dans le manifeste livré, un écart de matériaux de 40 % (56 pi pour 40)
    chantier_a = _chantier_termine(moteur, equipe, "ADM-A", 21, 56.0)
    # E : les prix et le taux horaire sont déclarés, un écart de 5 % (42 pi pour 40) : la marge réelle se calcule
    _prix_au_livre_de_m6(moteur)
    _declarer_m5(tmp_path, monkeypatch, {**CONFIGURATION_M5, "taux_horaire_main_d_oeuvre": "50.00"})
    chantier_e = _chantier_termine(moteur, equipe, "ADM-E", 22, 42.0)
    chantier_b = _chantier_planifie(moteur, "ADM-B", 23, version_lead=2)
    chantier_c = _chantier_planifie(moteur, "ADM-C", 24, version_lead=1)
    moteur.horloge.maintenant = debut_de_journee(25)
    _devis_accepte_a_planifier(moteur, "LEAD-ADM-D-fictif", "DEVIS-ADM-D-fictif")

    # ---- 4. ce que l'admin lit ----------------------------------------------------------------------------------
    for statut in STATUTS_DU_DISPATCH:
        enr.lire(f"interventions_{statut}", "m4_lister_interventions", {"statut": statut})
    enr.lire("digest", "m4_produire_digest",
             {"date_cible": JOUR_DU_DIGEST, "horodatage_reference": REFERENCE_DU_DIGEST})
    interventions = {i["lead_id"]: i["intervention_id"]
                     for statut in STATUTS_DU_DISPATCH for i in enr.reponses[f"interventions_{statut}"]["resultat"]}
    # A (à revoir), B et C (planifiées), D (à planifier) ; E est vérifiée : hors du dispatch
    assert len(interventions) == 4
    enr.lire("preparation_lead_v2", "m4_verifier_preparation", {"intervention_id": interventions[chantier_b.lead_id]})
    enr.lire("preparation_lead_v1", "m4_verifier_preparation", {"intervention_id": interventions[chantier_c.lead_id]})
    enr.lire("preparation_a_planifier", "m4_verifier_preparation",
             {"intervention_id": interventions["LEAD-ADM-D-fictif"]})
    enr.lire("preparation_terminee", "m4_verifier_preparation",
             {"intervention_id": interventions[chantier_a.lead_id]})
    enr.lire("a_voir", "m9_lister_demandes_approbation")
    demande = admin.appeler("m4_resoudre_revue_completion", {
        "intervention_id": chantier_a.intervention_id, "decision": "verifiee",
        "horodatage": iso(moteur.horloge.maintenant),
        "motif": "Bris de 16 pi constaté sur place et photographié : l'écart est expliqué (fictif)."},
        cle="mut-revue-adm-a", horodatage_appareil=iso(moteur.horloge.maintenant))
    assert demande.enveloppe["statut"] == "en_attente_approbation"
    enr.lire("a_voir_avec_demande", "m9_lister_demandes_approbation")
    enr.lire("vue_executive", "m8_lire_vue_executive")
    assert chantier_e.devis_id

    # ---- 5. ce que le serveur refuse : une personne désactivée, un argument hors catalogue ----------------------
    enr.lire("interventions_statut_inconnu", "m4_lister_interventions", {"statut": "inconnu"})
    moteur.creer_personne("sophie", "Sophie Gagnon (fictif)", ["admin", "manager"], monkeypatch)
    gestionnaire = moteur.appairer("sophie", "admin")
    assert cli.main(["personnes", "desactiver", "sophie"]) == 0
    enr.lire("refus_identite_vue_executive", "m8_lire_vue_executive", porte=gestionnaire)
    enr.lire("refus_identite_tresorerie", "m5_etat_tresorerie", porte=gestionnaire)
    enr.lire("refus_identite_interventions", "m4_lister_interventions", {"statut": "planifiee"}, porte=gestionnaire)
    return enr


def copy_sans(configuration: dict[str, Any], chemin: tuple[str, str]) -> dict[str, Any]:
    """La configuration, moins une déclaration (`chemin` : section, clé)."""
    section, cle = chemin
    copie = {nom: dict(valeur) if isinstance(valeur, dict) else valeur for nom, valeur in configuration.items()}
    copie[section] = {k: v for k, v in copie[section].items() if k != cle}
    return copie


@SQLITE_SEULEMENT
def test_les_reponses_du_moteur_ont_la_forme_de_la_fixture_que_l_app_lit(
        moteur, equipe, tmp_path, monkeypatch, declarer_services):
    """Le pont entre les deux langages : `mobile/src/admin/fixtures/reponses-moteur.json` (lue par les tests Jest, qui
    la font passer par les lecteurs de l'app) est la forme EXACTE de ce que le moteur rend aujourd'hui, avec les
    arguments que l'app envoie. Si le serveur change une clé ou un type, ce test échoue ; on relit alors les lecteurs
    de l'app, puis on régénère la fixture
    (`OPSYS_REGENERER_FIXTURES_MOBILE=1 pytest tests/e2e/test_admin_appareil.py -k fixture`)."""
    enr = _enregistrer_la_journee(moteur, equipe, tmp_path, monkeypatch, declarer_services)
    if os.environ.get(ENV_REGENERER) == "1":
        FIXTURE_APP.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_APP.write_text(json.dumps(
            {"fictif": True, "appels": enr.appels, "reponses": enr.reponses}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    # Chacun des huit outils de l'app a été appelé, sous son nom nu, et a répondu à l'appareil admin.
    assert {appel["outil"] for appel in enr.appels.values()} == OUTILS_ATTENDUS
    fixture = json.loads(FIXTURE_APP.read_text(encoding="utf-8"))
    assert fixture["fictif"] is True
    assert set(fixture["reponses"]) == set(enr.reponses) and set(fixture["appels"]) == set(enr.appels)
    for nom, vivante in enr.reponses.items():
        assert _forme(vivante) == _forme(fixture["reponses"][nom]), f"{nom} : la forme du moteur a changé"
        assert enr.appels[nom] == fixture["appels"][nom], nom


# ---------------------------------------------------------------------------------------------------------
# 403 : l'employé et le vendeur n'ont pas les outils du propriétaire ; le nom nu
# ---------------------------------------------------------------------------------------------------------
ARGUMENTS_DES_OUTILS = {
    "m9_lister_demandes_approbation": {},
    "m8_lire_vue_executive": {},
    "m5_etat_tresorerie": {},
    "m5_prevoir_tresorerie": {"aujourd_hui": AUJOURD_HUI},
    "m5_lire_echeances_fiscales": {"aujourd_hui": AUJOURD_HUI},
    "m4_lister_interventions": {"statut": "planifiee"},
    "m4_produire_digest": {"date_cible": JOUR_DU_DIGEST, "horodatage_reference": REFERENCE_DU_DIGEST},
    "m4_verifier_preparation": {"intervention_id": "intervention-fantome"},
}


def _refus_de_la_porte(reponse: Reponse) -> bool:
    message = reponse.corps["error"]["message"]
    return (reponse.statut == 403 and reponse.corps["ok"] is False
            and reponse.corps["error"]["type"] == "tool_call_blocked"
            and ("tool_out_of_scope" in message or "server_unknown" in message))


@SQLITE_SEULEMENT
def test_403_pour_l_employe_et_le_vendeur_sur_les_outils_du_proprietaire_et_pour_tout_nom_qui_n_est_pas_nu(
        moteur, equipe, monkeypatch):
    assert set(ARGUMENTS_DES_OUTILS) == OUTILS_ATTENDUS
    moteur.creer_personne("vendeur.adm", "Vendeur (fictif)", ["seller"], monkeypatch)
    vendeur = moteur.appairer("vendeur.adm", "seller")
    employe = equipe["employe"]
    admin = equipe["admin"]
    avant = moteur.empreinte_etat()

    for outil, args in ARGUMENTS_DES_OUTILS.items():
        assert _refus_de_la_porte(vendeur.appeler(outil, args)), f"le vendeur n'a pas droit à {outil}"
        reponse_employe = employe.appeler(outil, args)
        if outil in PARTAGE_AVEC_L_EMPLOYE:
            assert reponse_employe.statut == 200, outil
        else:
            assert _refus_de_la_porte(reponse_employe), f"l'employé n'a pas droit à {outil}"
        assert admin.appeler(outil, args).statut == 200, f"l'admin passe la porte pour {outil}"

    # La règle est le nom NU (`opsys/roles.json`) : un outil permis, nommé avec son serveur, est refusé, même à l'admin.
    for prefixe in ("m05-financecore.", "m05-financecore__", "mcp__m05-financecore__"):
        for porte in (admin, vendeur, employe):
            refus = porte.appeler(f"{prefixe}m5_etat_tresorerie", {})
            assert _refus_de_la_porte(refus), (prefixe, refus.corps)
    assert _refus_de_la_porte(admin.appeler("M5_ETAT_TRESORERIE", {}))
    # Ni un outil du même département hors de la portée de l'admin (le geste de décision se prend à l'écran des
    # approbations, jamais depuis les écrans de lecture) n'est ouvert par erreur : il n'est pas dans cette liste.
    assert "m9_decider_demande_approbation" not in ARGUMENTS_DES_OUTILS
    assert moteur.empreinte_etat() == avant, "un refus de la porte n'écrit rien, et une lecture non plus"


@SQLITE_SEULEMENT
def test_l_employe_ne_lit_que_ses_interventions_et_l_admin_toutes(moteur, equipe, monkeypatch, declarer_services):
    """`m4_lister_interventions` est le seul outil de l'app admin qui soit aussi celui de l'employé : le serveur le
    filtre à SES interventions (jamais élargi, jamais tronqué). Un autre employé n'en voit aucune."""
    declarer_services()
    chantier = _chantier_planifie(moteur, "ADM-F", 23, version_lead=2)
    moteur.creer_personne("employe.bis", "Employé bis (fictif)", ["employee"], monkeypatch)
    autre = moteur.appairer("employe.bis", "employee")
    args = {"statut": "planifiee"}

    admin = equipe["admin"].appeler("m4_lister_interventions", args)
    assert admin.statut == 200
    assert [i["intervention_id"] for i in admin.resultat] == [chantier.intervention_id]
    lui = equipe["employe"].appeler("m4_lister_interventions", args)
    assert lui.statut == 200
    assert [i["intervention_id"] for i in lui.resultat] == [chantier.intervention_id]
    ailleurs = autre.appeler("m4_lister_interventions", args)
    assert ailleurs.statut == 200 and ailleurs.resultat == []
    assert ailleurs.mesure.tronque is False


# ---------------------------------------------------------------------------------------------------------
# L'app et le serveur parlent la même langue
# ---------------------------------------------------------------------------------------------------------
def _fixture_des_reponses() -> dict[str, Any]:
    return json.loads(FIXTURE_APP.read_text(encoding="utf-8"))["reponses"]


def _valeurs_observees(motif: str, chemin: str) -> set[str]:
    """Les valeurs qu'une clé prend dans les réponses ENREGISTRÉES dont le nom commence par `motif` (`a.b.c` : un chemin
    depuis l'enveloppe, où un outil « couple » ajoute un `resultat` de plus ; `*` : chaque élément d'une liste)."""
    trouvees: set[str] = set()

    def descendre(noeud: Any, morceaux: list[str]) -> None:
        if not morceaux:
            if isinstance(noeud, str):
                trouvees.add(noeud)
            return
        tete, reste = morceaux[0], morceaux[1:]
        if tete == "*":
            for element in noeud if isinstance(noeud, list) else []:
                descendre(element, reste)
        elif isinstance(noeud, dict) and tete in noeud:
            descendre(noeud[tete], reste)

    for nom, enveloppe in _fixture_des_reponses().items():
        if nom.startswith(motif):
            descendre(enveloppe, chemin.split("."))
    return trouvees


def test_les_catalogues_et_les_noms_d_outils_de_l_app_sont_ceux_du_serveur():
    # -- les outils : huit, sous leur nom nu, tous dans la portée `admin` ---------------------------------------
    outils = _outils_de_l_app()
    assert set(outils.values()) == OUTILS_ATTENDUS
    portee_admin = set(openclaw.roles_outils(charger_departements())["admin"])
    assert set(outils.values()) <= portee_admin, "l'app appelle un outil hors de la portée de l'admin"
    assert not any(outil.startswith(("mcp", "M")) or "." in outil or "__" in outil for outil in outils.values())
    # Rien de ce qui décide ou écrit : l'app ne peut pas, faute de les nommer.
    assert not any(mot in outil for outil in outils.values() for mot in ("decider", "resoudre", "proposer", "appliquer",
                                                                          "creer", "enregistrer", "signaler"))

    # -- M4 : le dispatch et la préparation ---------------------------------------------------------------------
    dispatch = _source("m4/dispatch.ts")
    statuts = _liste_ts(dispatch, "STATUTS_DU_DISPATCH")
    assert set(statuts) <= set(etats_m4.ETATS), "un statut du dispatch que le serveur ne connaît pas"
    assert "completed_verified" not in statuts and "annulee" not in statuts, "l'historique n'est jamais demandé"
    assert _liste_ts(dispatch, "STATUTS_PREPARABLES") == list(preparation_m4.STATUTS_PREPARABLES)
    assert _liste_ts(dispatch, "VOLETS_DE_PREPARATION") == list(preparation_m4.VOLETS)
    assert _liste_ts(dispatch, "STATUTS_DE_VOLET") == [
        preparation_m4.STATUT_OK, preparation_m4.STATUT_MANQUE, preparation_m4.STATUT_NON_VERIFIABLE]
    assert _liste_ts(dispatch, "VERDICTS_DE_PREPARATION") == [
        preparation_m4.VERDICT_PRET, preparation_m4.VERDICT_BLOQUE, preparation_m4.VERDICT_NON_VERIFIABLE]
    assert _liste_ts(dispatch, "TYPES_DE_DEMANDE_DE_REVUE") == list(ecarts_m4.TYPES_DEMANDE)

    # -- M5 : trésorerie, prévision, échéances -------------------------------------------------------------------
    tresorerie = _source("m5/tresorerie.ts")
    assert _liste_ts(tresorerie, "COMPOSANTES_DU_CASH_LIBRE") == list(cash_libre._ORDRE_COMPOSANTES)
    assert _liste_ts(tresorerie, "FREQUENCES_FISCALES") == list(calendrier_fiscal._FREQUENCES)
    assert _liste_ts(tresorerie, "VALIDATIONS_CPA") == list(calendrier_fiscal._VALIDATIONS_CPA)
    # Les statuts sans constante dans le serveur (chaînes du code) : le scénario enregistré les produit tous.
    alertes = _valeurs_observees("prevision", "resultat.resultat.alerte.statut")
    assert set(_liste_ts(tresorerie, "STATUTS_ALERTE_PREVISION")) == alertes
    echeances = _valeurs_observees("echeances", "resultat.resultat.echeances.*.statut")
    assert set(_liste_ts(tresorerie, "STATUTS_ECHEANCE")) == echeances
    statuts_composante = {_constante_ts(tresorerie, "STATUT_COMPOSANTE_CALCULEE"),
                          _constante_ts(tresorerie, "STATUT_COMPOSANTE_NON_CALCULABLE")}
    assert statuts_composante == _valeurs_observees("tresorerie", "resultat.cash_libre.composantes.*.statut")
    statuts_semaine = _valeurs_observees("prevision", "resultat.resultat.semaines.*.statut")
    assert statuts_semaine <= {"CALCULE", "NON_CALCULABLE"}

    # -- M8 : l'entonnoir ----------------------------------------------------------------------------------------
    vue = _source("m8/vueExecutive.ts")
    assert _constante_ts(vue, "STATUT_MESURE_CALCULEE") == mesures_chantier.STATUT_CALCULEE
    assert _constante_ts(vue, "STATUT_MESURE_NON_CALCULABLE") == mesures_chantier.STATUT_NON_CALCULABLE
    assert _liste_ts(vue, "STATUTS_SEUIL_EVALUE") == [
        mesures_chantier.SEUIL_FRANCHI, mesures_chantier.SEUIL_NON_FRANCHI]
    assert _liste_ts(vue, "SENS_DE_SEUIL") == [nombres.SENS_AU_DESSUS, nombres.SENS_AU_DESSOUS]
    metriques = yaml.safe_load(
        (RACINE / "departments" / "m08-analytics" / "metrics" / "m8-entonnoir.v1.yaml").read_text(encoding="utf-8"))
    unites = set(_liste_ts(vue, "UNITES_CONNUES"))
    assert unites == {metrique["unite"] for metrique in metriques["metrics"]}
    assert _valeurs_observees("vue_executive", "resultat.entonnoir.mesures.*.unite") <= unites

    # -- le socle : les pannes passagères ne sont jamais un refus -----------------------------------------------------
    assert set(_liste_ts(_source("admin/enveloppe.ts"), "ERREURS_PASSAGERES")) == set(idempotence.ERREURS_PASSAGERES)

