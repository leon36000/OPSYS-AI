"""Aide NON COLLECTÉE de `test_m9_producteurs_b.py` : données FICTIVES des producteurs M5, M8, M7, M1 et M10.

Tout est fictif (`FICTIF = True`) : personnes, identifiants, montants. Chaque département est alimenté par ce qu'il
expose lui-même : ses outils (`executer_atomique`, ou `Capacites` + décision d'approbation du socle pour un palier
humain), ses consommateurs d'événements par le VRAI bus (`opsys.evenements.publier` / `repartir`), ou sa fonction
publique de réception. Aucun INSERT SQL, aucune écriture dans le registre d'un autre département. Seule exception,
dite : la configuration du propriétaire (`department.yaml` > `configuration`), que M5 et M8 relisent à chaque appel,
est posée par un manifeste temporaire (`_MANIFESTE`), comme le font les tests de ces départements : le manifeste
livré n'en déclare aucune (GATE NATHAN).

Les événements amont (M1, M2, M3, M4, M6) sont des charges synthétiques validées par le catalogue du bus à la
publication : le département producteur n'est pas installé, c'est la porte d'entrée publique du consommateur.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path

import m1_front_office.outils as m1_outils
import m5_financecore.outils as m5_outils
import m8_analytics.outils as m8_outils
import yaml
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from sqlalchemy import select

from opsys import approbations, contexte, evenements, identite, lecteurs_m9, stockage, taxonomie
from opsys.capacites import Capacites, outils_executables
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.schema import META

FICTIF = True

M9 = "m09-strategic-intelligence"
M1, M5, M7, M8, M10 = "m01-front-office", "m05-financecore", "m07-marketing", "m08-analytics", "m10-memoire"
REGISTRE_CAPTURES = "captures_strategiques"

ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
PERSONNES = (
    ("admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", "admin"),
    ("vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", "seller"),
    ("employe.fictif", "Employé Fictif", "mot-de-passe-employe-12", "employee"),
    ("financeuse", "Une Comptable (fictif)", "mot-de-passe-finance-1234", "finance"),
    ("ancien.admin", "Ancien Admin (fictif)", "mot-de-passe-ancien-123", "admin"),
    ("comptable", "Une Comptable (fictive)", "mot-de-passe-compta-1234", ("finance", "admin")),
)


# --------------------------------------------------------------------------------------------------------- socle
def installer_base(tmp_path: Path, monkeypatch) -> Path:
    """Base SQLite temporaire migrée, personnes fictives, registres durables de M1 et M5. Rend le dossier du test.

    Le nettoyage (`stockage.liberer`, registre M1 en mémoire) est fait par `desinstaller_base`."""
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'm9-producteurs-b.db'}")
    stockage.migrer()
    m5_outils.utiliser_stockage_durable()
    m1_outils.utiliser_stockage_durable()
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    with stockage.transaction() as cnx:
        for personne, nom, secret, role in PERSONNES:
            identite.creer_personne(
                cnx, personne, nom, secret, [role] if isinstance(role, str) else list(role),
                actif=personne != "ancien.admin")
    return tmp_path


def desinstaller_base() -> None:
    """Remet M1 sur son registre en mémoire et libère les moteurs (idempotent)."""
    m1_outils.reinitialiser_registre()
    stockage.liberer()


def capacites(*departements: str) -> Capacites:
    """Le dispatcher de l'appelant M9 : `m9` + les seuls producteurs nommés (filtre), comme le gabarit du socle."""
    return Capacites(charger_departements(), stockage.transaction, filtre={M9, *departements}, memoire=False)


def capturer(cap: Capacites, identite_appelante: IdentiteAppelante | None, lecture: str, arguments: dict,
             horodatage: str) -> dict:
    """Un appel de `m9_capturer_producteur` (sans identité : voie d'un agent, refusée par M9)."""
    appel = {"lecture_id": lecture, "arguments": arguments, "horodatage": horodatage}
    if identite_appelante is None:
        return cap.appeler("m9_capturer_producteur", appel)
    with contexte.appele_par_appareil(identite_appelante):
        return cap.appeler("m9_capturer_producteur", appel)


def lire_par_le_port(departement: str, outil: str, arguments: dict,
                     identite_appelante: IdentiteAppelante | None = ADMIN) -> dict:
    """La réponse BRUTE du dispatcher telle que le port privé de M9 la rend (`lecteurs_m9.construire_lecteur`), même
    contexte d'appel que l'outil de capture (admin authentifié, attribué à M9). Sert à constater la forme d'une
    lecture que la capture refuse ensuite pour une raison propre au catalogue ; ce n'est pas un contournement du port
    (liste blanche, identité relue en base et départements installés restent ceux du port)."""
    lecteur = lecteurs_m9.construire_lecteur(charger_departements(), stockage.transaction)
    with stockage.transaction(), contexte.appele_par_appareil(identite_appelante), contexte.appeler_en_tant_que(
        M9, origine=M9
    ):
        return lecteur(departement, outil, arguments)


def captures_stockees() -> list[dict]:
    """Les captures M9 conservées (registre chaîné `captures_strategiques`), relues par l'API du stockage."""
    with stockage.transaction():
        return list(stockage.maillons(M9, REGISTRE_CAPTURES))


def page(index: int, numero: int = 0) -> dict:
    """La page `numero` de la réponse du producteur conservée par la capture `index`."""
    return captures_stockees()[index]["pages"][numero]


def valeurs(capture_ou_page: dict, chemin: str) -> list:
    """Valeurs trouvées à `chemin` (`a.b[*].c`) : la même extraction que M9 (`capture_strategique.extraire`)."""
    return cs.extraire(capture_ou_page, chemin)


def etat_base() -> dict:
    """Photographie de toutes les tables, pour prouver qu'un refus n'a rien écrit."""
    with stockage.transaction() as cnx:
        return {nom: sorted(map(str, cnx.execute(select(t)).fetchall())) for nom, t in META.tables.items()}


# ---------------------------------------------------------------------------------------------------------- bus
def livrer(departements: tuple[str, ...], maintenant: str = "2026-10-20T18:00:00+00:00", max_tours: int = 6) -> dict:
    """Draine le bus vers les seuls `departements` (consommateurs réels) jusqu'à quiescence. Un événement publié par
    un consommateur (ex. `m5.rentabilite_chantier`) est livré au tour suivant."""
    tous = charger_departements()
    cibles = {dep: tous[dep] for dep in departements}
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    instant = dt.datetime.fromisoformat(maintenant)
    for tour in range(max_tours):
        resume = evenements.repartir(cibles, maintenant=(instant + dt.timedelta(seconds=90 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            break
    assert total["echecs"] == 0 and total["quarantaines"] == 0, total
    return total


def publier(type_evenement: str, producteur: str, charge: dict, evenement_id: str | None = None) -> None:
    with stockage.transaction():
        evenements.publier(type_evenement, producteur, charge, evenement_id=evenement_id)


# ----------------------------------------------------------------------------------------- M5 : FinanceCore
FACTURE_LIGNES = (
    {"description": "Gouttières 5po aluminium (fictif)", "quantite": "40", "unite": "pi", "prix_unitaire": "8.50",
     "reference_ligne_devis": "L1"},
    {"description": "Main d'oeuvre installation (fictif)", "quantite": "1", "unite": "forfait",
     "prix_unitaire": "260.00", "reference_ligne_devis": "L2"},
)
SEUIL_ALERTE = {"montant": "16000.00", "source": "décision de Nathan (fictive)", "au": "2026-09-25"}
CONFIGURATION_M5 = {
    "taux_horaire_main_d_oeuvre": "50.00",
    "categories_depense_sans_po": ["carburant", "outils"],
    "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "2026-06-30"},
    "obligations_declarees": {
        "paies": {"montant": "4200.00", "source": "brouillon de paie du 2026-09-25 (fictif)", "au": "2026-09-25"},
        "das": {"montant": "1350.75", "source": "estimation du CPA (fictive)", "au": "2026-09-25"},
        "dettes": {"montant": "800.00", "source": "relevé du prêt camion (fictif)", "au": "2026-09-01"},
    },
    "prevision": {
        "horizon_semaines": 6, "seuil_alerte": SEUIL_ALERTE, "delai_encaissement_clients_jours": 30,
        "delai_paiement_fournisseurs_jours": 30,
        "echeances_obligations": {"paies": "2026-10-09", "das": "2026-10-15", "dettes": "2026-10-31"},
    },
}
AUJOURD_HUI_M5 = "2026-09-29"
MATERIAU = "gouttiere-alu-5po-fictif"


def declarer_configuration(module, tmp_path: Path, monkeypatch, configuration: dict, nom: str) -> Path:
    """Pose `department.yaml > configuration` (déclarations du propriétaire) dans un manifeste temporaire que le
    département relit à chaque appel. Sans cet appel, le manifeste livré ne déclare rien et le département le dit."""
    manifeste = tmp_path / nom
    manifeste.write_text(yaml.safe_dump({"configuration": configuration}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(module, "_MANIFESTE", manifeste)
    return manifeste


def declarer_m5(tmp_path: Path, monkeypatch, configuration: dict | None = None) -> None:
    declarer_configuration(m5_outils, tmp_path, monkeypatch, configuration or CONFIGURATION_M5, "m5-department.yaml")


def _outil(module, nom: str):
    return next(o for o in module.outils() if o.nom == nom)


def enregistrer_mouvements_m5() -> None:
    """Trois mouvements par l'outil `m5_enregistrer_mouvement` : solde 20000.00, provision 1000.00."""
    outil = _outil(m5_outils, "m5_enregistrer_mouvement")
    for montant, type_mouvement, quand in (
        ("25000.00", "ENCAISSEMENT", "2026-08-01T12:00:00-04:00"),
        ("-5000.00", "DECAISSEMENT", "2026-08-15T12:00:00-04:00"),
        ("1000.00", "PROVISION", "2026-09-10T12:00:00-04:00"),
    ):
        reponse = executer_atomique(outil, {
            "montant": montant, "type_mouvement": type_mouvement, "horodatage": quand,
            "classe_retention": "STANDARD", "source": "m9-producteurs-b (fictif)"})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def factures_clients_m5(envoyees: tuple[tuple[str, str, str], ...] = (
    ("FACT-B1", "DEVIS-B1", "2026-09-14T09:30:00-04:00"), ("FACT-B2", "DEVIS-B2", "2026-09-20T09:30:00-04:00"),
), brouillons: tuple[tuple[str, str], ...] = (("FACT-B3", "DEVIS-B3"),)) -> None:
    """Factures clientes : brouillon par l'outil `m5_creer_facture_brouillon`, envoi par la file d'approbation N4 du
    socle (`Capacites.appeler` puis `approbations.decider` par la personne `financeuse`), comme en production.
    Les `envoyees` (facture, devis, instant d'envoi) deviennent ENVOYEE ; les `brouillons` restent BROUILLON."""
    dep = charger_departements()[M5]
    creer = _outil(m5_outils, "m5_creer_facture_brouillon")
    for facture_id, devis_id, quand in (*envoyees, *((f, d, "2026-09-01T09:00:00-04:00") for f, d in brouillons)):
        reponse = executer_atomique(creer, {
            "facture_id": facture_id, "chantier_id": f"CH-{devis_id}", "devis_id": devis_id,
            "client_id": "CLIENT-B-fictif", "lignes": [dict(ligne) for ligne in FACTURE_LIGNES],
            "horodatage": quand})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    cap = Capacites({M5: dep}, stockage.transaction)
    executables = outils_executables({M5: dep}, stockage.transaction)
    for facture_id, _devis, quand in envoyees:
        demande = cap.appeler("m5_envoyer_facture", {"facture_id": facture_id, "horodatage": quand})
        assert demande["statut"] == "en_attente_approbation", demande
        with stockage.transaction() as cnx:
            approbations.decider(cnx, demande["demande_id"], True, "financeuse", executables, {M5: dep})


def _charge_reception(evenement_id: str, po_id: str, quantite: str, quand: str) -> dict:
    return {
        "evenement_id": evenement_id, "po_id": po_id, "fournisseur_id": "gentek-fictif", "chantier_id": "CH-B1",
        "horodatage_reception": quand, "verdict_reception": "CONFORME", "statut_po": "received",
        "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [{"materiau_id": "gouttiere-5po", "quantite_demandee": quantite, "quantite_recue": quantite,
                    "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                    "prix_unitaire_reception": "5.00", "verdict_prix_reception": "PRIX_CATALOGUE",
                    "ecart_prix_critique": False}],
    }


def comptes_a_payer_m5(nombre_po: int = 3) -> None:
    """`nombre_po` POs reçus (événement `m6.reception_enregistree`, consommé par M5) dont les deux premiers sont
    facturés par la saisie humaine `m5_saisir_facture_fournisseur` (admin authentifié) ; les autres restent « attendu
    non facturé ». Avec plus de ~5 POs la lecture dépasse une page (`BUDGET_SORTIE`) et pagine par `depart`."""
    for rang in range(1, nombre_po + 1):
        evenement = f"m6-reception-PO-B{rang}-{rang:04d}"
        publier("m6.reception_enregistree", "m06-material-control", _charge_reception(
            evenement, f"PO-B{rang}", str(20 * rang), f"2026-09-{14 + rang:02d}T09:00:00-04:00"),
            evenement_id=evenement)
    livrer((M5,))
    saisir = _outil(m5_outils, "m5_saisir_facture_fournisseur")
    for po, numero, jour, montant in (("PO-B1", "F-1001", "2026-09-14", "100.00"),
                                      ("PO-B2", "F-2001", "2026-06-20", "200.00")):
        with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
            reponse = executer_atomique(saisir, {
                "po_id": po, "fournisseur_id": "gentek-fictif", "numero_facture": numero, "date_facture": jour,
                "montant_avant_taxes": montant, "total_facture": None, "horodatage": "2026-09-20T10:00:00-04:00"})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def corriger_facture_m5(po_id: str = "PO-B1", montant_avant_taxes: str = "110.00") -> str:
    """Corrige (pièce chaînée, N4 par la voie directe d'un appareil `finance`+`admin`) la facture fournisseur d'un PO
    lue par la liste des comptes à payer : sa `revision_attendue` est celle LUE (0 : une ligne SAISIE n'en porte pas).
    Rend l'identifiant de la facture corrigée."""
    comptable = IdentiteAppelante("comptable", "admin")
    with contexte.appele_par_appareil(comptable):
        lecture = executer_atomique(_outil(m5_outils, "m5_lister_comptes_a_payer"), {"po_id": po_id})
        facture_id = lecture["resultat"]["resultat"]["comptes"][0]["factures_saisies"][0]["facture_fournisseur_id"]
        reponse = executer_atomique(_outil(m5_outils, "m5_corriger_facture_fournisseur"), {
            "facture_fournisseur_id": facture_id, "motif": "Faute de frappe sur le montant (fictif)",
            "numero_facture": None, "date_facture": None, "montant_avant_taxes": montant_avant_taxes,
            "total_facture": None, "horodatage": "2026-09-24T10:00:00-04:00", "revision_attendue": 0})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return facture_id


def facture_sans_po_m5() -> None:
    """Une facture fournisseur SANS PO (carburant), saisie par l'admin authentifié (catégories déclarées)."""
    with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
        reponse = executer_atomique(_outil(m5_outils, "m5_saisir_facture_sans_po"), {
            "fournisseur_id": "petro-fictif", "categorie": "carburant", "numero_facture": "C-7001",
            "date_facture": "2026-09-22", "montant_avant_taxes": "84.50", "total_facture": None,
            "horodatage": "2026-09-23T10:00:00-04:00"})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


# ------------------------------------------------------------------------------------------ chantier terminé
LEAD_ID = "LEAD-B1-fictif"
CLIENT_ID = "c" * 64
DEVIS_ID = "DEVIS-B1"
CHANTIER_ID = "CHANTIER-B1"
WCT_ID = "WCT-B1"
COMPLETION = "2026-09-25T16:30:00-04:00"
ACCEPTATION = "2026-09-20T10:00:00-04:00"
FACTURE_ID = "FACT-B1"


def prix_au_livre_m6(prix: float = 8.0, date_effet: str = "2026-09-01") -> None:
    """Prix du matériau au livre de prix de M6, par l'outil public `m6_enregistrer_prix` (M5 le lit, jamais M9)."""
    import m6_material_control.outils as m6_outils

    reponse = executer_atomique(_outil(m6_outils, "m6_enregistrer_prix"), {
        "materiau_id": MATERIAU, "fournisseur_id": "gentek-fictif", "prix_unitaire": prix, "devise": "CAD",
        "date_effet": date_effet, "unite": "pi"})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def charge_devis_accepte(devis_id: str = DEVIS_ID, chantier_id: str = CHANTIER_ID, lead_id: str = LEAD_ID) -> dict:
    return {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": chantier_id,
        "lignes": [
            {"reference_ligne": f"{devis_id}-L0", "description": "Gouttières 5po aluminium (fictif)",
             "quantite": "40", "unite": "pi", "prix_unitaire": "10.00", "prix_ligne": "400.00",
             "reference_besoin_materiau": MATERIAU},
            {"reference_ligne": f"{devis_id}-L1", "description": "Main d'oeuvre installation (fictif)",
             "quantite": "1", "unite": "forfait", "prix_unitaire": "200.00", "prix_ligne": "200.00",
             "reference_besoin_materiau": None},
        ],
        "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25", "duree_estimee_minutes": "60",
        "horodatage_acceptation": ACCEPTATION,
    }


def charge_wct(wct_id: str = WCT_ID, devis_id: str = DEVIS_ID, lead_id: str = LEAD_ID) -> dict:
    return {
        "wct_id": wct_id, "intervention_id": f"INT-{wct_id}", "lead_id": lead_id, "technicien_id": "TECH-B1-fictif",
        "horodatage_completion": COMPLETION, "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 180, "ecart_signale": False, "revue_id": None, "hash_maillon": f"hash-{wct_id}",
        "consommateurs_cibles": ["M5", "M6", "M2", "M7", "M8", "M10"], "devis_id": devis_id,
        "statut": "completed_verified",
    }


def charge_variance(wct_id: str = WCT_ID, chantier_id: str = CHANTIER_ID) -> dict:
    return {
        "evenement_id": f"m6-variance-{wct_id}-evaluee", "wct_id": wct_id, "intervention_id": f"INT-{wct_id}",
        "chantier_id": chantier_id, "statut_variance": "evaluee", "signal_critique": False,
        "seuil_pourcentage": 0.3, "horodatage_completion": COMPLETION,
        "lignes": [{"materiau": MATERIAU, "unite": "pi", "quantite_prevue": "40.0", "quantite_reelle": "42.0",
                    "ecart_pourcentage": "0.05", "critique": False}],
    }


def chantier_termine(destinataires: tuple[str, ...], maintenant: str = "2026-09-25T17:00:00-04:00") -> None:
    """Un chantier terminé complet publié sur le bus : devis accepté (M3), travaux terminés (M4), variance (M6).
    Les `destinataires` (M5 pour la rentabilité, M7, M8, M10...) le consomment par leurs consommateurs réels ; la
    rentabilité que M5 publie en retour (`m5.rentabilite_chantier`) est livrée aux autres au tour suivant."""
    publier("m3.devis_accepte", "m03-estimation", charge_devis_accepte())
    publier("m4.travaux_termines", "m04-field-ops", charge_wct())
    charge = charge_variance()
    publier("m6.variance_chantier", "m06-material-control", charge, evenement_id=charge["evenement_id"])
    livrer(destinataires, maintenant=dt.datetime.fromisoformat(maintenant).isoformat())


# ------------------------------------------------------------------------------- amont commercial (M1, M2, M3)
HORODATAGE_LEAD = "2026-09-18T09:15:00-04:00"
HORODATAGE_CLIENT = "2026-09-18T09:15:30-04:00"
HORODATAGE_ASSIGNATION = "2026-09-18T11:00:00-04:00"
ENVOI_A = "2026-09-19T15:00:00-04:00"
ENVOI_B = "2026-09-19T15:30:00-04:00"
CONSTAT_SANS_REPONSE = "2026-09-27T08:00:00-04:00"
DEVIS_SANS_REPONSE = "DEVIS-B2"
CONTACT = {"nom": "Camille Testeur (fictif)", "telephone": "+1 514 555 0142", "courriel": "camille@exemple-fictif.test"}


def charge_lead_qualifie(lead_id: str = LEAD_ID) -> dict:
    lead = {
        "schema_version": 2, "lead_id": lead_id, "conversation_id": "texte-conv-b1", "contact": dict(CONTACT),
        "service": "gouttieres", "ville": "Repentigny", "urgence_declaree": False, "canal": "texte",
        "source": "sms", "utm": {"utm_source": "google"}, "campagne": "automne",
    }
    return {"lead": lead, "horodatage": HORODATAGE_LEAD, "signal_id": "texte:sig-b1"}


def devis_sans_reponse_en_plus(identifiants: tuple[str, ...], lead_id: str = LEAD_ID) -> None:
    """Des devis envoyés puis constatés « sans réponse » de plus (M3 → M8), au-delà des trois que la vue exécutive
    nomme : sert à prouver la troncature déclarée (`reste`)."""
    for devis_id in identifiants:
        publier("m3.devis_envoye", "m03-estimation", {
            "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "horodatage_envoi": ENVOI_B},
            evenement_id=f"m3-devis-envoye-{devis_id}")
        publier("m3.devis_sans_reponse", "m03-estimation", {
            "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "statut": "envoye",
            "horodatage_devis": ENVOI_B, "horodatage_reference": CONSTAT_SANS_REPONSE, "delai_relance_jours": 7},
            evenement_id=f"m3-devis-sans-reponse-{devis_id}")
    livrer((M8,))


def lead_qualifie_m1(lead_id: str = LEAD_ID) -> None:
    """`m1.lead_qualifie`, publié par M1 : le lead est qualifié (contact CLIENT_PRIVATE, jamais gardé tel quel)."""
    publier("m1.lead_qualifie", M1, charge_lead_qualifie(lead_id), evenement_id=f"m1-lead-qualifie-{lead_id}")


def parcours_commercial(lead_id: str = LEAD_ID, utm: dict | None = None) -> None:
    """Lead associé et assigné (M2), deux devis envoyés (M3), l'un sans réponse : de quoi alimenter l'entonnoir."""
    associe = {"lead_id": lead_id, "client_id": CLIENT_ID, "horodatage_association": HORODATAGE_CLIENT}
    if utm is not None:
        associe["utm"] = utm
    publier("m2.client_associe", "m02-revenue-crm", associe, evenement_id=f"m2-client-associe-{lead_id}")
    publier("m2.lead_assigne", "m02-revenue-crm", {
        "lead_id": lead_id, "proprietaire": "Alice Vendeuse (fictif)",
        "horodatage_assignation": HORODATAGE_ASSIGNATION},
        evenement_id=f"m2-lead-assigne-{lead_id}")
    for devis_id, quand in ((DEVIS_ID, ENVOI_A), (DEVIS_SANS_REPONSE, ENVOI_B)):
        publier("m3.devis_envoye", "m03-estimation", {
            "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "horodatage_envoi": quand},
            evenement_id=f"m3-devis-envoye-{devis_id}")
    publier("m3.devis_sans_reponse", "m03-estimation", {
        "devis_id": DEVIS_SANS_REPONSE, "lead_id": lead_id, "chantier_id": None, "statut": "envoye",
        "horodatage_devis": ENVOI_B, "horodatage_reference": CONSTAT_SANS_REPONSE, "delai_relance_jours": 7},
        evenement_id=f"m3-devis-sans-reponse-{DEVIS_SANS_REPONSE}")


# ------------------------------------------------------------------------------------------ M8 : Analytics
def alimenter_m8(avec_cash_libre: bool = True) -> None:
    """Entonnoir complet + chantier terminé, mesurés par M8 à partir de ses consommateurs réels.

    M5 consomme aussi les faits amont : il calcule la rentabilité (taux horaire déclaré, prix au livre de M6) et la
    publie ; M8 la reçoit au tour suivant du bus. Le cash libre est CONSTATÉ par l'outil `m5_constater_cash_libre`
    (admin authentifié), jamais saisi : M8 le reçoit tel quel."""
    prix_au_livre_m6()
    factures_clients_m5(envoyees=((FACTURE_ID, DEVIS_ID, "2026-09-26T09:30:00-04:00"),), brouillons=())
    parcours_commercial()
    chantier_termine((M5, M8))
    if avec_cash_libre:
        enregistrer_mouvements_m5()
        with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
            reponse = executer_atomique(_outil(m5_outils, "m5_constater_cash_libre"), {"aujourd_hui": "2026-09-29"})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
        livrer((M5, M8))


def declarer_m8(tmp_path: Path, monkeypatch, seuils_alerte: dict) -> None:
    declarer_configuration(m8_outils, tmp_path, monkeypatch, {"seuils_alerte": seuils_alerte}, "m8-department.yaml")


# ----------------------------------------------------------------------------------------- M7 : Marketing
def alimenter_m7(utm: dict | None = None) -> None:
    """Un lead associé avec attribution UTM (M2), son devis accepté (M3) et la rentabilité du chantier (M5),
    reçus par les consommateurs réels de M7 (`m2.client_associe`, `m3.devis_accepte`, `m5.rentabilite_chantier`)."""
    utm = utm or {"utm_source": "google", "utm_campaign": "automne"}
    prix_au_livre_m6()
    publier("m2.client_associe", "m02-revenue-crm", {
        "lead_id": LEAD_ID, "client_id": CLIENT_ID, "horodatage_association": HORODATAGE_CLIENT, "utm": utm},
        evenement_id=f"m2-client-associe-{LEAD_ID}")
    chantier_termine((M5, M7))


# ---------------------------------------------------------------------------------------- M1 : Front office
ZONE_DESSERVIE = ("Montréal", "Québec", "Laval", "Repentigny")


def demandes_m1() -> None:
    """Quatre demandes entrantes par l'outil public `m1_traiter_demande_entrante` (jours 28 et 29 septembre) : le
    registre anti-perte reçoit un signal et un lead par demande qualifiée."""
    outil = _outil(m1_outils, "m1_traiter_demande_entrante")
    for conversation, canal, texte, quand in (
        ("conv-b1", "texte", "Gouttières à remplacer à Montréal, téléphone 514-555-0142.", "2026-09-28T09:00:00-04:00"),
        ("conv-b2", "courriel", "Soffite à Laval, téléphone 450-555-0000.", "2026-09-28T11:00:00-04:00"),
        ("conv-b3", "formulaire", "Revêtement à Québec, téléphone 418-555-0100.", "2026-09-29T08:30:00-04:00"),
        ("conv-b4", "texte", "Gouttières à Repentigny, urgent, téléphone 450-555-0199.", "2026-09-29T10:10:00-04:00"),
    ):
        reponse = executer_atomique(outil, {
            "contenu_brut": texte, "canal": canal, "conversation_id": conversation, "signal_id": f"sig-{conversation}",
            "horodatage": quand, "zone_desservie": list(ZONE_DESSERVIE)})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


# -------------------------------------------------------------------------------------------- M10 : Mémoire
AFFAIRE = LEAD_ID


def alimenter_m10(avec_rentabilite: bool = True) -> None:
    """Le fil d'une affaire pour M10, par ses consommateurs réels : lead qualifié (M1), client associé (M2), deux
    devis envoyés dont un sans réponse (M3), devis accepté (M3), travaux terminés (M4) et variance (M6). Avec
    `avec_rentabilite`, M5 calcule aussi la rentabilité (maillon FINANCIAL, jamais rendu dans un paquet)."""
    lead_qualifie_m1()
    parcours_commercial()
    if avec_rentabilite:
        prix_au_livre_m6()
        chantier_termine((M5, M10))
    else:
        chantier_termine((M10,))
    livrer((M10,))


# ------------------------------------------------------------------------------------ chemins PROPOSÉS (M9.1)
_PAGE_DEPART = cat.Pagination("depart", "resultat.resultat.prochain_depart", "resultat.resultat.total")
# `incomplets` (marqueurs de troncature déclarée par le producteur) n'existe que si le catalogue le porte.
INCOMPLETS_DISPONIBLES = hasattr(cat, "Marqueur") and "incomplets" in {f.name for f in dataclasses.fields(cat.Lecture)}


def _incomplets(*specs: tuple[str, str]) -> dict:
    """`incomplets=` proposés : (chemin, genre). Jamais pour une lecture paginée : un marqueur s'applique à CHAQUE page,
    et le `reste` d'une page intermédiaire rendrait la capture incomplète à tort."""
    if not INCOMPLETS_DISPONIBLES:
        return {}
    return {"incomplets": tuple(cat.Marqueur(chemin, genre) for chemin, genre in specs)}

PROPOSITIONS: dict[str, dict] = {
    # Prévision : `fraicheur.derniere_piece` est l'instant de la dernière pièce du registre dont le solde part ;
    # `prevision_id` est l'empreinte des flux et réglages qui l'ont produite. NON CAPTURABLE aujourd'hui : voir la
    # référence `aujourd_hui` (date sans fuseau) dans les tests.
    "m5.prevision_tresorerie": {
        "instants_metier": ("resultat.resultat.solde_initial.fraicheur.derniere_piece",),
        "revisions": ("resultat.resultat.prevision_id",),
        "pagination": _PAGE_DEPART,
    },
    # Rentabilité : aucun instant ; `version_entrees` (empreinte des pièces du calcul) n'est rendue qu'avec un filtre
    # devis_id / chantier_id. Aucune pagination possible : `limite` seulement, `reste` dit ce qui n'est pas rendu.
    "m5.rentabilite_chantier": {
        "revisions": ("resultat.resultat.chantiers[*].trace.version_entrees",),
        **_incomplets(("resultat.resultat.reste", "positif")),
    },
    "m5.comptes_a_recevoir": {"instants_metier": ("resultat.resultat.factures[*].date_envoi",)},
    # À payer : `corrections` (révision d'une facture) et `derniere_modification` sont rendus pour un PO précis
    # (po_id) ou en mode sans_po ; la liste par PO ne les porte pas.
    "m5.comptes_a_payer": {
        "instants_metier": (
            "resultat.resultat.comptes[*].derniere_reception",
            "resultat.resultat.comptes[*].factures_saisies[*].derniere_modification.horodatage",
            "resultat.resultat.factures[*].derniere_modification.horodatage",
        ),
        "revisions": (
            "resultat.resultat.comptes[*].factures_saisies[*].corrections",
            "resultat.resultat.factures[*].corrections",
        ),
        "pagination": _PAGE_DEPART,
    },
    # Vue exécutive : `dernier_fait_le` (par type d'événement reçu) et `horodatage_completion` (WCT) sont des instants
    # déclarés ; `sequence` est le rang du constat du cash libre que M5 a publié.
    "m8.vue_executive": {
        "instants_metier": (
            "resultat.entonnoir.sources[*].dernier_fait_le",
            "resultat.marge_reelle.chantiers[*].horodatage_completion",
        ),
        "revisions": ("resultat.cash_libre.constat.sequence",),
        **_incomplets(
            ("resultat.entonnoir.devis_en_attente.sans_reponse.reste", "positif"),
            ("resultat.entonnoir.devis_en_attente.brouillons_en_retard.reste", "positif"),
            ("resultat.marge_reelle.reste", "positif"),
            ("resultat.stock_a_commander.reste", "positif"),
        ),
    },
    "m8.mesures_chantier": {
        "instants_metier": ("resultat.horodatage_completion",),
        "revisions": ("resultat.mesures[*].entrees.version_entrees",),
    },
    # Performance : `source_refs[*].sequence` est la séquence M5 des rentabilités lues. Aucun instant métier :
    # `observation_source` est une horloge de lecture (`lue_le`) et une date SQL sans fuseau.
    "m7.performance_campagnes": {"revisions": ("resultat.source_refs[*].sequence",)},
    # Digest : un texte, aucun champ structuré.
    "m1.digest": {},
    "m10.paquet_affaire": {
        "instants_metier": ("resultat.couches[*].faits[*].horodatage",),
        **_incomplets(("resultat.couches[*].tronque", "vrai")),
    },
}


def proposition(lecture_id: str) -> cat.Lecture:
    """La lecture du catalogue ACTUEL complétée des chemins proposés (jamais écrite dans le catalogue)."""
    return dataclasses.replace(cat.PAR_ID[lecture_id], **PROPOSITIONS[lecture_id])
