"""M9 → producteurs M5, M8, M7, M1 et M10 : captures par le port privé, sur de VRAIES données (fictives).

Chaque département est alimenté par ses propres outils ou consommateurs d'événements (`m9_producteurs_b.py`), puis
M9 capture sa lecture par `m9_capturer_producteur` (admin `console` relu en base, `Capacites` filtré sur M9). Ce
fichier établit, lecture par lecture : le verdict, les champs clés de la réponse conservée (aux chemins que le
catalogue devrait déclarer, extraits par `capture_strategique.extraire`), la complétude et la pagination, les refus.

Le catalogue adopte désormais les chemins d'instants, de révisions, de pagination et d'incomplétude proposés, et la
référence en JOUR (`reference_genre="date"`, conservée en `reference_jour`). Les tests vérifient ce comportement :
capture avec le jour de référence, pagination lue en entier sans doublon, PARTIELLE quand le producteur déclare sa
réponse tronquée ou vide (rentabilité, vue exécutive M8, mesures d'un WCT inconnu, paquet M10), refus sans écriture
d'un jour invalide, refus d'identité et producteur absent pour chaque département. Seule la lecture M7 garde une
substitution de catalogue (`proposer`) : sa réponse contient une horloge (`lue_le`), donc aucune révision n'y est
déclarée et la proposition sert à prouver le faux positif de contradiction.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat

from opsys import contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.outils import executer_atomique


def _charger_aide():
    spec = importlib.util.spec_from_file_location("m9_producteurs_b", Path(__file__).with_name("m9_producteurs_b.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


H = _charger_aide()
FICTIF = True
JOUR = "2026-10-28"
PERIODE = {"debut": "2026-09-01", "fin": "2026-09-30"}
PAQUET = {"affaire_id": H.LEAD_ID, "horodatage": "2026-10-01T08:00:00-04:00"}


def recu(n: int = 0) -> str:
    """Instant de réception fourni à M9 (monotone dans un test : n croissant)."""
    return f"{JOUR}T12:00:{n:02d}Z"


# ------------------------------------------------------------------------------------------------- fixtures
@pytest.fixture
def base(tmp_path, monkeypatch):
    H.installer_base(tmp_path, monkeypatch)
    yield tmp_path
    H.desinstaller_base()


@pytest.fixture
def m5(base, monkeypatch):
    """Base + déclarations du propriétaire pour M5 (taux horaire, fiscalité, obligations, prévision, catégories)."""
    H.declarer_m5(base, monkeypatch)
    return base


@pytest.fixture
def proposer(monkeypatch):
    """Applique, pour la durée du test, les chemins proposés à ces lectures du catalogue."""

    def appliquer(*lecture_ids):
        for lecture_id in lecture_ids:
            monkeypatch.setitem(cat.PAR_ID, lecture_id, H.proposition(lecture_id))

    return appliquer


# ----------------------------------------------------------------------------------------- petits outils
def _capture(reponse: dict) -> dict:
    """Le résumé de capture d'un appel accepté par M9 (l'outil a écrit au registre)."""
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["capture"]


def _acceptee(reponse: dict, lecture_id: str) -> dict:
    capture = _capture(reponse)
    assert capture["lecture_id"] == lecture_id
    assert (capture["verdict"], capture["code"], capture["complete"]) == ("ACCEPTEE", None, True), capture
    return capture


def _refusee_avant_ecriture(reponse: dict, code: str) -> None:
    """M9 a refusé AVANT d'écrire : rien n'est conservé (contrairement à un refus du producteur)."""
    assert reponse["ok"] is False and code in reponse["details"], reponse
    assert H.captures_stockees() == []


def _page_ok(index: int = 0) -> dict:
    """La réponse du producteur conservée par la capture `index` : `{"ok": true, "resultat": …}`."""
    page = H.page(index)
    assert page["ok"] is True
    return page


def _jour_reference(index: int = 0) -> str | None:
    """La référence en JOUR (genre `date`) conservée par la capture `index` : aucun fuseau n'est deviné."""
    capture = H.captures_stockees()[index]
    assert capture["reference"] is None
    return capture["reference_jour"]


PARTIELLE = "réponse tronquée ou vide déclarée par le producteur ({})"


def _partielle(reponse: dict, lecture_id: str, marqueur: str) -> dict:
    """Capture ACCEPTEE mais PARTIELLE parce que le PRODUCTEUR déclare sa réponse tronquée ou vide (`incomplets`)."""
    capture = _capture(reponse)
    assert capture["lecture_id"] == lecture_id
    assert (capture["verdict"], capture["code"], capture["complete"]) == ("ACCEPTEE", None, False), capture
    assert capture["raison_incomplete"] == PARTIELLE.format(marqueur)
    return capture


def _verifier_chaine(cap: Capacites) -> None:
    with contexte.appele_par_appareil(H.ADMIN):
        verification = cap.appeler("m9_verifier_captures", {})
    assert verification["ok"] is True and verification["resultat"]["valide"] is True, verification


def _recalculer(captures_index: int, lecture_id: str, arguments: dict, lecture: cat.Lecture | None = None) -> dict:
    """Recalcule, sur la page DÉJÀ conservée, ce que la capture dit avec la lecture du catalogue (ou `lecture`) :
    `instants_metier`, `revisions`, `complete`."""
    capture = H.captures_stockees()[captures_index]
    recalculee = cs.construire(
        lecture or cat.PAR_ID[lecture_id], arguments, capture["pages"], recu_a=capture["recu_a"],
        reference=capture["reference"] or capture["reference_jour"], index=0, hash_precedent=cs.HASH_INITIAL,
    )
    return {"instants": recalculee["instants_metier"], "revisions": recalculee["revisions"],
            "complete": recalculee["complete"], "raison": recalculee["raison_incomplete"]}


IDENTITES_REFUSEES = {
    "agent_sans_identite": None,
    "vendeur": IdentiteAppelante("vendeur.fictif", "seller", source="console"),
    "employe": IdentiteAppelante("employe.fictif", "employee", source="console"),
    "admin_desactive": IdentiteAppelante("ancien.admin", "admin", source="console"),
    "personne_inconnue": IdentiteAppelante("inconnu.fictif", "admin", source="console"),
    "source_inconnue": IdentiteAppelante("admin.fictif", "admin", source="jeton-inconnu"),
    "role_usurpe": IdentiteAppelante("employe.fictif", "admin", source="console"),
}


def _installer_m5(base, mp):
    H.declarer_m5(base, mp)
    H.comptes_a_payer_m5(3)


def _installer_m8(base, mp):
    H.declarer_m5(base, mp)
    H.alimenter_m8()


def _installer_m7(base, mp):
    H.declarer_m5(base, mp)
    H.alimenter_m7()


def _installer_m1(base, mp):
    H.demandes_m1()


def _installer_m10(base, mp):
    H.declarer_m5(base, mp)
    H.alimenter_m10()


# producteur -> (département, lecture, arguments, installateur, marqueurs qui ne doivent jamais fuir)
PRODUCTEURS = {
    "m5": (H.M5, "m5.comptes_a_payer", {}, _installer_m5, ("PO-B1", "gentek-fictif", "344.93")),
    "m8": (H.M8, "m8.mesures_chantier", {"wct_id": H.WCT_ID}, _installer_m8, ("DEVIS-B1", "114.00", "WCT-B1")),
    "m7": (H.M7, "m7.performance_campagnes", PERIODE, _installer_m7, ("automne", "114.00", "LEAD-B1-fictif")),
    "m1": (H.M1, "m1.digest", {"date_reference": "2026-09-28"}, _installer_m1, ("courriel: signal", "Montréal")),
    "m10": (H.M10, "m10.paquet_affaire", PAQUET, _installer_m10, ("DEVIS-B2", "WCT-B1", "Camille")),
}


# ================================================================================ tous les producteurs : refus
@pytest.mark.parametrize("producteur", sorted(PRODUCTEURS))
def test_identite_refusee_avant_toute_lecture_sans_ecriture_ni_fuite(base, monkeypatch, producteur):
    """Agent, vendeur, employé, admin désactivé, inconnu, source inconnue, rôle usurpé : refus de M9 avant la lecture
    du producteur. Aucune capture, aucune fuite de la donnée du producteur, aucune écriture hors journal."""
    departement, lecture, arguments, installer, marqueurs = PRODUCTEURS[producteur]
    installer(base, monkeypatch)
    cap = H.capacites(departement)
    # Témoin : l'admin fictif console est la seule identité qui passe l'identité (M1 : refus du catalogue, plus loin).
    for nom, identite_appelante in IDENTITES_REFUSEES.items():
        avant = H.etat_base()
        reponse = H.capturer(cap, identite_appelante, lecture, dict(arguments), recu(1))
        assert reponse["ok"] is False, (nom, reponse)
        texte = str(reponse)
        assert not any(marqueur in texte for marqueur in marqueurs), (nom, texte)
        assert H.captures_stockees() == [], nom
        apres = H.etat_base()
        modifiees = {table for table in avant if avant[table] != apres[table]}
        assert modifiees <= {"journal", "mutations_appliquees"}, (nom, modifiees)


@pytest.mark.parametrize("producteur", ["m5", "m8", "m7", "m1", "m10"])
def test_producteur_absent_est_une_erreur_conservee_comme_manque(base, monkeypatch, producteur):
    """Le département n'est pas installé : le port répond `producteur_indisponible`, M9 conserve l'ERREUR (un manque se
    prouve) ; la couverture la dit REFUSEE. Aucune donnée n'est lue."""
    departement, lecture, arguments, _installer, _marqueurs = PRODUCTEURS[producteur]
    installes = {k: v for k, v in charger_departements().items() if k != departement}
    cap = Capacites(installes, stockage.transaction, filtre={H.M9}, memoire=False)
    capture = _capture(H.capturer(cap, H.ADMIN, lecture, dict(arguments), recu(1)))
    assert (capture["verdict"], capture["code"], capture["complete"]) == ("ERREUR", "producteur_indisponible", False)
    assert capture["instants_metier"]["nombre"] == 0 and capture["revisions"] == []
    assert H.page(0)["erreur"] == "producteur_indisponible"
    with contexte.appele_par_appareil(H.ADMIN):
        couverture = cap.appeler("m9_couverture_strategique", {"reference": recu(2), "attendues": [lecture]})
    (ligne,) = couverture["resultat"]["lectures"]
    assert ligne["statut"] == "REFUSEE" and ligne["code"] == "producteur_indisponible"


def test_arguments_non_declares_refuses_dont_role_et_autorise_couts(m5):
    """Le catalogue n'autorise que `libres` : `role` et `autorise_couts` (M5) ne passent pas. Ils sont inutiles, car
    l'admin authentifié a, par son rôle, le droit de voir les montants (`acces.resoudre_vue`)."""
    H.comptes_a_payer_m5(3)
    cap = H.capacites(H.M5)
    for supplementaire in ({"role": "admin"}, {"autorise_couts": True}, {"montant": "1.00"}, {"limite": 3}):
        reponse = H.capturer(cap, H.ADMIN, "m5.comptes_a_payer", supplementaire, recu(1))
        _refusee_avant_ecriture(reponse, "REJ-CAPTURE-ARGUMENTS")
    capture = _acceptee(H.capturer(cap, H.ADMIN, "m5.comptes_a_payer", {}, recu(2)), "m5.comptes_a_payer")
    page = _page_ok()
    assert H.valeurs(page, "resultat.resultat.role") == ["admin"]
    assert H.valeurs(page, "resultat.resultat.totaux.attendu_apres_taxes") == ["689.86"]  # montants visibles
    assert capture["pages"] == 1


# ============================================================================================ M5 prévision
def test_m5_prevision_a_des_donnees_reelles_par_le_port(m5):
    """Le producteur répond avec de vraies données (solde, 6 semaines, alerte sous le seuil déclaré)… """
    H.enregistrer_mouvements_m5()
    H.factures_clients_m5()
    H.comptes_a_payer_m5(3)
    lu = H.lire_par_le_port(H.M5, "m5_prevoir_tresorerie", {"aujourd_hui": H.AUJOURD_HUI_M5})
    assert lu["ok"] is True and lu["resultat"]["accepte"] is True
    assert H.valeurs(lu, "resultat.resultat.type") == ["PREVISION_TRESORERIE"]
    assert H.valeurs(lu, "resultat.resultat.solde_initial.montant") == ["20000.00"]
    assert H.valeurs(lu, "resultat.resultat.horizon_semaines") == [6]
    assert len(H.valeurs(lu, "resultat.resultat.semaines[*].solde_fin")) == 6
    assert H.valeurs(lu, "resultat.resultat.alerte.statut") == ["ALERTE"]
    # chemins proposés : instant de la dernière pièce du registre (fuseau explicite) et empreinte de la prévision
    (derniere_piece,) = H.valeurs(lu, "resultat.resultat.solde_initial.fraicheur.derniere_piece")
    assert cs.instant(derniere_piece) is not None
    (prevision_id,) = H.valeurs(lu, "resultat.resultat.prevision_id")
    assert len(prevision_id) == 64
    assert H.valeurs(lu, "resultat.resultat.prochain_depart") == [None]  # 6 semaines : une seule page


def test_m5_prevision_capturee_avec_son_jour_de_reference(m5):
    """`aujourd_hui` est un JOUR (genre `date`) : la capture le garde en `reference_jour` (aucun fuseau deviné,
    `reference` nulle). Instant de la dernière pièce, empreinte de la prévision et alerte du seuil sont conservés."""
    H.enregistrer_mouvements_m5()
    H.factures_clients_m5()
    H.comptes_a_payer_m5(3)
    cap = H.capacites(H.M5)
    assert cat.PAR_ID["m5.prevision_tresorerie"].reference_genre == "date"
    capture = _acceptee(H.capturer(cap, H.ADMIN, "m5.prevision_tresorerie", {"aujourd_hui": H.AUJOURD_HUI_M5},
                                   recu(1)), "m5.prevision_tresorerie")
    assert capture["reference"] is None and capture["pages"] == 1 and _jour_reference() == H.AUJOURD_HUI_M5
    page = _page_ok()
    assert H.valeurs(page, "resultat.resultat.solde_initial.montant") == ["20000.00"]
    assert len(H.valeurs(page, "resultat.resultat.semaines[*].solde_fin")) == 6
    assert H.valeurs(page, "resultat.resultat.alerte.statut") == ["ALERTE"]
    assert capture["instants_metier"] == {"declares": True, "nombre": 1, "invalides": 0,
                                          "min": "2026-09-10T16:00:00Z", "max": "2026-09-10T16:00:00Z"}
    (prevision_id,) = H.valeurs(page, "resultat.resultat.prevision_id")
    assert capture["revisions"] == [prevision_id]
    # sans `aujourd_hui` : arguments invalides du producteur, conservés comme tels
    sans = _capture(H.capturer(cap, H.ADMIN, "m5.prevision_tresorerie", {"horizon_semaines": 6}, recu(2)))
    assert (sans["verdict"], sans["code"]) == ("ERREUR", "arguments_invalides")
    _verifier_chaine(cap)


@pytest.mark.parametrize("lecture_id, argument, installer", [
    ("m5.prevision_tresorerie", "aujourd_hui", H.enregistrer_mouvements_m5),
    ("m5.comptes_a_recevoir", "aujourd_hui", H.factures_clients_m5),
    ("m8.vue_executive", "aujourd_hui", None),
    ("m1.digest", "date_reference", H.demandes_m1),
])
def test_reference_en_jour_invalide_refusee_sans_ecriture(m5, lecture_id, argument, installer):
    """Une référence de genre `date` doit être un jour civil AAAA-MM-JJ valide : un jour impossible, un instant avec
    fuseau, un jour sans zéros ou du texte sont refusés (`REJ-CAPTURE-TEMPS`), rien n'est conservé."""
    if installer is not None:
        installer()
    departement = cat.PAR_ID[lecture_id].departement
    assert cat.PAR_ID[lecture_id].reference_genre == "date"
    cap = H.capacites(departement)
    for invalide in ("2026-13-45", "2026-10-28T10:00:00Z", "2026-9-9", "hier", ""):
        reponse = H.capturer(cap, H.ADMIN, lecture_id, {argument: invalide}, recu(1))
        assert reponse["ok"] is False, (invalide, reponse)
        assert H.captures_stockees() == [], invalide


def test_m5_prevision_pagine_par_depart_et_la_capture_lit_toutes_les_semaines(m5):
    """26 semaines dépassent une page (16) : `prochain_depart` = 16, M9 suit `depart` et lit les deux pages, sans
    semaine manquante ni doublon ; une seule page lue serait PARTIELLE."""
    H.enregistrer_mouvements_m5()
    premiere = H.lire_par_le_port(H.M5, "m5_prevoir_tresorerie", {"aujourd_hui": H.AUJOURD_HUI_M5,
                                                                   "horizon_semaines": 26})
    assert H.valeurs(premiere, "resultat.resultat.total") == [26]
    assert H.valeurs(premiere, "resultat.resultat.affichees") == [16]
    assert H.valeurs(premiere, "resultat.resultat.prochain_depart") == [16]
    cap = H.capacites(H.M5)
    capture = _acceptee(H.capturer(cap, H.ADMIN, "m5.prevision_tresorerie",
                                   {"aujourd_hui": H.AUJOURD_HUI_M5, "horizon_semaines": 26}, recu(1)),
                        "m5.prevision_tresorerie")
    assert capture["pages"] == 2
    stockee = H.captures_stockees()[0]
    semaines = [n for page in stockee["pages"] for n in cs.extraire(page, "resultat.resultat.semaines[*].semaine")]
    assert semaines == list(range(1, 27))
    assert cs.extraire(stockee["pages"][1], "resultat.resultat.prochain_depart") == [None]
    seule = _recalculer(0, "m5.prevision_tresorerie", stockee["arguments"],
                        lecture=cat.PAR_ID["m5.prevision_tresorerie"])
    assert seule["complete"] is True
    une_page = cs.construire(cat.PAR_ID["m5.prevision_tresorerie"], stockee["arguments"], stockee["pages"][:1],
                             recu_a=recu(2), reference=H.AUJOURD_HUI_M5, index=0, hash_precedent=cs.HASH_INITIAL)
    assert une_page["complete"] is False and une_page["raison_incomplete"] == "page suivante non lue"
    _verifier_chaine(cap)


# ====================================================================================== M5 rentabilité
@pytest.fixture
def chantier_m5(m5):
    """DEVIS-B1 / CHANTIER-B1 terminé, prix au livre M6, facture envoyée : coût complet, prix définitif."""
    H.prix_au_livre_m6()
    H.factures_clients_m5(envoyees=((H.FACTURE_ID, H.DEVIS_ID, "2026-09-26T09:30:00-04:00"),), brouillons=())
    H.chantier_termine((H.M5,))
    return m5


def test_m5_rentabilite_chantier_capturee_avec_la_marge_reelle(chantier_m5):
    cap = H.capacites(H.M5)
    capture = _acceptee(H.capturer(cap, H.ADMIN, "m5.rentabilite_chantier", {}, recu(1)), "m5.rentabilite_chantier")
    assert capture["reference"] is None and capture["pages"] == 1
    page = _page_ok()
    assert H.valeurs(page, "resultat.resultat.role") == ["admin"]
    assert H.valeurs(page, "resultat.resultat.nombre") == [1]
    (chantier,) = H.valeurs(page, "resultat.resultat.chantiers[*]")
    assert (chantier["devis_id"], chantier["chantier_id"], chantier["statut"]) == (
        "DEVIS-B1", "CHANTIER-B1", "calculee")
    rentabilite = chantier["rentabilite"]
    assert (rentabilite["verdict"], rentabilite["manque"], rentabilite["cout_reel_complet"]) == ("CALCULEE", [], True)
    assert (rentabilite["cout_total"], rentabilite["marge_reelle"], rentabilite["marge_prevue"]) == (
        "486.00", "114.00", "120.00")
    assert (rentabilite["prix_facture"], rentabilite["statut_facture"]) == ("600.00", "ENVOYEE")
    assert chantier["trace"] == {"a_jour": True}  # vue liste : aucune révision rendue
    assert H.valeurs(page, "resultat.resultat.mention")[0].startswith("Analyse préparatoire IA")
    _verifier_chaine(cap)


def test_m5_rentabilite_ne_declare_aucun_instant_et_la_revision_n_est_rendue_qu_avec_un_filtre(chantier_m5):
    """Aucun instant métier dans la réponse (ni la date du WCT ni celle de la facture). `version_entrees` (empreinte
    des pièces du calcul) n'est rendue qu'en vue détaillée, donc avec `devis_id` ou `chantier_id`."""
    cap = H.capacites(H.M5)
    _acceptee(H.capturer(cap, H.ADMIN, "m5.rentabilite_chantier", {}, recu(1)), "m5.rentabilite_chantier")
    _acceptee(H.capturer(cap, H.ADMIN, "m5.rentabilite_chantier", {"devis_id": H.DEVIS_ID}, recu(2)),
              "m5.rentabilite_chantier")
    chemin = "resultat.resultat.chantiers[*].trace.version_entrees"
    assert H.valeurs(H.page(0), chemin) == []
    (version,) = H.valeurs(H.page(1), chemin)
    assert len(version) == 64 and set(version) <= set("0123456789abcdef")
    detail = H.valeurs(H.page(1), "resultat.resultat.chantiers[*].rentabilite")[0]
    assert "version_entrees" not in detail and detail["marge_reelle"] == "114.00"  # le détail rend plus de champs
    assert _recalculer(1, "m5.rentabilite_chantier", {"devis_id": H.DEVIS_ID})["revisions"] == [version]
    assert _recalculer(0, "m5.rentabilite_chantier", {})["revisions"] == []
    assert _recalculer(0, "m5.rentabilite_chantier", {})["instants"]["declares"] is False
    # par le catalogue substitué : la capture réelle conserve cette révision
    capture = _acceptee(H.capturer(cap, H.ADMIN, "m5.rentabilite_chantier", {"chantier_id": H.CHANTIER_ID}, recu(3)),
                        "m5.rentabilite_chantier")
    assert capture["revisions"] == [version]
    _verifier_chaine(cap)


def test_m5_rentabilite_limite_laisse_un_reste_et_la_capture_est_partielle(chantier_m5):
    """`limite` borne les devis rendus et `reste` dit combien manquent (aucun argument de reprise) : le producteur
    DÉCLARE sa troncature, la capture est PARTIELLE ; sans troncature (`reste` 0) elle est complète."""
    H.publier("m3.devis_accepte", "m03-estimation", H.charge_devis_accepte("DEVIS-B9", "CHANTIER-B9", "LEAD-B9"))
    H.livrer((H.M5,))
    cap = H.capacites(H.M5)
    _acceptee(H.capturer(cap, H.ADMIN, "m5.rentabilite_chantier", {}, recu(1)), "m5.rentabilite_chantier")
    assert H.valeurs(H.page(0), "resultat.resultat.nombre") == [2]
    assert H.valeurs(H.page(0), "resultat.resultat.reste") == [0]
    assert sorted(H.valeurs(H.page(0), "resultat.resultat.chantiers[*].statut")) == [
        "calculee", "en_attente_travaux_termines"]
    _partielle(H.capturer(cap, H.ADMIN, "m5.rentabilite_chantier", {"limite": 1}, recu(2)),
               "m5.rentabilite_chantier", "resultat.resultat.reste")
    assert H.valeurs(H.page(1), "resultat.resultat.reste") == [1]
    assert H.valeurs(H.page(1), "resultat.resultat.affichees") == [1]
    reponse = H.capturer(cap, H.ADMIN, "m5.rentabilite_chantier", {"limite": 1, "decalage": 1}, recu(3))
    assert reponse["ok"] is False and "REJ-CAPTURE-ARGUMENTS" in reponse["details"]
    _verifier_chaine(cap)





def test_m5_rentabilite_devis_inconnu_est_un_refus_conserve(chantier_m5):
    cap = H.capacites(H.M5)
    capture = _capture(H.capturer(cap, H.ADMIN, "m5.rentabilite_chantier", {"devis_id": "DEVIS-INCONNU"}, recu(1)))
    assert (capture["verdict"], capture["code"], capture["complete"]) == (
        "REFUSEE", "REJ-RENTABILITE-CHANTIER-INCONNU", False)
    assert capture["raison_incomplete"] == "réponse refusée ou en erreur : aucun fait reçu"
    assert H.valeurs(H.page(0), "resultat.verdict.code") == ["REJ-RENTABILITE-CHANTIER-INCONNU"]


def test_m5_apres_retrait_du_role_admin_la_lecture_financiere_est_refusee(chantier_m5):
    cap = H.capacites(H.M5)
    _acceptee(H.capturer(cap, H.ADMIN, "m5.rentabilite_chantier", {}, recu(1)), "m5.rentabilite_chantier")
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
    avant = len(H.captures_stockees())
    refus = H.capturer(cap, H.ADMIN, "m5.rentabilite_chantier", {}, recu(2))
    assert refus["ok"] is False and "114.00" not in str(refus)
    assert len(H.captures_stockees()) == avant == 1


# ================================================================================ M5 comptes à recevoir
def test_m5_comptes_a_recevoir_capturee_seules_les_factures_envoyees(m5):
    H.factures_clients_m5()  # 2 envoyées, 1 brouillon
    cap = H.capacites(H.M5)
    capture = _acceptee(H.capturer(cap, H.ADMIN, "m5.comptes_a_recevoir", {}, recu(1)), "m5.comptes_a_recevoir")
    assert capture["reference"] is None
    page = _page_ok()
    assert sorted(H.valeurs(page, "resultat.resultat.factures[*].facture_id")) == ["FACT-B1", "FACT-B2"]
    assert "FACT-B3" not in str(page)  # le brouillon n'est pas à recevoir
    assert H.valeurs(page, "resultat.resultat.nombre") == [2]
    assert H.valeurs(page, "resultat.resultat.total_a_recevoir") == ["1379.70"]
    assert H.valeurs(page, "resultat.resultat.total_complet") == [True]
    assert H.valeurs(page, "resultat.resultat.age") == [None]  # sans aujourd_hui, l'âge n'est jamais deviné
    dates = H.valeurs(page, "resultat.resultat.factures[*].date_envoi")
    assert sorted(dates) == ["2026-09-14T09:30:00-04:00", "2026-09-20T09:30:00-04:00"]
    # instants proposés : la date d'envoi, avec fuseau, de chaque facture ; aucune révision rendue
    proposee = _recalculer(0, "m5.comptes_a_recevoir", {})
    assert proposee["instants"] == {"declares": True, "nombre": 2, "invalides": 0,
                                    "min": "2026-09-14T13:30:00Z", "max": "2026-09-20T13:30:00Z"}
    assert proposee["revisions"] == [] and proposee["complete"] is True
    reelle = _acceptee(H.capturer(cap, H.ADMIN, "m5.comptes_a_recevoir", {}, recu(2)), "m5.comptes_a_recevoir")
    assert reelle["instants_metier"]["min"] == "2026-09-14T13:30:00Z"
    assert reelle["instants_metier"]["max"] == "2026-09-20T13:30:00Z"
    _verifier_chaine(cap)


def test_m5_comptes_a_recevoir_avec_aujourd_hui_capture_l_age_par_tranche(m5):
    """Avec `aujourd_hui` (jour de référence, genre `date`) l'âge par tranche est conservé ; le jour est gardé en
    `reference_jour`, sans fuseau deviné. Le brouillon n'est jamais à recevoir."""
    H.factures_clients_m5()
    cap = H.capacites(H.M5)
    capture = _acceptee(H.capturer(cap, H.ADMIN, "m5.comptes_a_recevoir", {"aujourd_hui": H.AUJOURD_HUI_M5}, recu(1)),
                        "m5.comptes_a_recevoir")
    assert capture["reference"] is None and _jour_reference() == H.AUJOURD_HUI_M5
    page = _page_ok()
    assert H.valeurs(page, "resultat.resultat.age.total_par_tranche") == [
        {"0-30": "1379.70", "31-60": "0", "61-90": "0", "90+": "0"}]
    assert H.valeurs(page, "resultat.resultat.age_non_calcule") == [None]
    assert "FACT-B3" not in str(page)
    assert capture["instants_metier"]["nombre"] == 2  # les dates d'envoi, avec fuseau (les âges sont des jours)
    _verifier_chaine(cap)


# ===================================================================================== M5 comptes à payer
def test_m5_comptes_a_payer_capturee_avec_attendu_facture_et_rapprochement(m5):
    H.comptes_a_payer_m5(3)
    cap = H.capacites(H.M5)
    _acceptee(H.capturer(cap, H.ADMIN, "m5.comptes_a_payer", {}, recu(1)), "m5.comptes_a_payer")
    page = _page_ok()
    assert H.valeurs(page, "resultat.resultat.type") == ["COMPTES_A_PAYER"]
    assert H.valeurs(page, "resultat.resultat.comptes[*].po_id") == ["PO-B1", "PO-B2", "PO-B3"]
    assert H.valeurs(page, "resultat.resultat.comptes[*].rapprochement.verdict") == [
        "CONCORDANT", "CONCORDANT", "SANS_FACTURE"]
    totaux = H.valeurs(page, "resultat.resultat.totaux")[0]
    assert (totaux["nombre_po"], totaux["attendu_apres_taxes"], totaux["facture_apres_taxes"]) == (
        3, "689.86", "344.93")  # somme des PO arrondis un à un : 114.98 + 229.95 + 344.93
    assert totaux["a_payer_apres_taxes"] == "689.86" and totaux["complet"] is True
    assert (H.valeurs(page, "resultat.resultat.total"), H.valeurs(page, "resultat.resultat.reste")) == ([3], [0])
    assert H.valeurs(page, "resultat.resultat.prochain_depart") == [None]
    _verifier_chaine(cap)


def test_m5_comptes_a_payer_instants_derniere_reception_et_couverture(m5):
    H.comptes_a_payer_m5(3)
    cap = H.capacites(H.M5)
    _acceptee(H.capturer(cap, H.ADMIN, "m5.comptes_a_payer", {}, recu(1)), "m5.comptes_a_payer")
    assert H.valeurs(H.page(0), "resultat.resultat.comptes[*].derniere_reception") == [
        "2026-09-15T09:00:00-04:00", "2026-09-16T09:00:00-04:00", "2026-09-17T09:00:00-04:00"]
    reelle = _acceptee(H.capturer(cap, H.ADMIN, "m5.comptes_a_payer", {}, recu(2)), "m5.comptes_a_payer")
    assert reelle["instants_metier"] == {"declares": True, "nombre": 3, "invalides": 0,
                                         "min": "2026-09-15T13:00:00Z", "max": "2026-09-17T13:00:00Z"}
    assert reelle["revisions"] == []  # la liste par PO ne rend aucune révision de facture
    with contexte.appele_par_appareil(H.ADMIN):
        couverture = cap.appeler("m9_couverture_strategique", {
            "reference": recu(3), "connaissance": recu(3), "attendues": ["m5.comptes_a_payer"]})
    (ligne,) = couverture["resultat"]["lectures"]
    assert ligne["statut"] == "PRESENTE" and ligne["dernier_index"] == 1 and ligne["age_s"] > 0
    assert ligne["fraicheur"] == "NON_EVALUEE"  # aucune attente de fraîcheur du propriétaire


def test_m5_comptes_a_payer_pagine_et_la_capture_lit_toutes_les_pages(m5):
    """9 POs : une page est bornée par la limite de sortie (`prochain_depart`). M9 suit `depart` et lit toutes les
    pages : aucun PO manquant, aucun doublon ; une page suivante non lue rendrait la capture PARTIELLE."""
    H.comptes_a_payer_m5(9)
    cap = H.capacites(H.M5)
    premiere = H.lire_par_le_port(H.M5, "m5_lister_comptes_a_payer", {})
    taille_page = len(H.valeurs(premiere, "resultat.resultat.comptes[*].po_id"))
    assert 1 <= taille_page < 9
    assert H.valeurs(premiere, "resultat.resultat.prochain_depart") == [taille_page]
    assert H.valeurs(premiere, "resultat.resultat.reste") == [9 - taille_page]
    complete = _acceptee(H.capturer(cap, H.ADMIN, "m5.comptes_a_payer", {}, recu(1)), "m5.comptes_a_payer")
    assert complete["pages"] == 2
    stockee = H.captures_stockees()[0]
    po_ids = [po for page in stockee["pages"] for po in cs.extraire(page, "resultat.resultat.comptes[*].po_id")]
    assert po_ids == [f"PO-B{rang}" for rang in range(1, 10)]
    assert cs.extraire(stockee["pages"][1], "resultat.resultat.prochain_depart") == [None]
    assert stockee["arguments"] == {}  # l'argument `depart` des pages suivantes n'est pas un argument de la capture
    seule_page = cs.construire(cat.PAR_ID["m5.comptes_a_payer"], {}, stockee["pages"][:1], recu_a=recu(3),
                               reference=None, index=0, hash_precedent=cs.HASH_INITIAL)
    assert seule_page["complete"] is False and seule_page["raison_incomplete"] == "page suivante non lue"
    _verifier_chaine(cap)


def test_lecture_paginee_reste_positif_sur_une_page_intermediaire_n_est_pas_incomplete(m5, monkeypatch):
    """Seule la DERNIÈRE page d'une lecture paginée est jugée par les marqueurs : le `reste` > 0 de la première page
    ne rend pas la capture PARTIELLE si la dernière page est complète. Sans pagination, le même marqueur la rend
    PARTIELLE (une seule page : `reste` > 0)."""
    H.comptes_a_payer_m5(9)
    avec_marqueur = dataclasses.replace(
        cat.PAR_ID["m5.comptes_a_payer"], incomplets=(cat.Marqueur("resultat.resultat.reste", "positif"),))
    monkeypatch.setitem(cat.PAR_ID, "m5.comptes_a_payer", avec_marqueur)
    cap = H.capacites(H.M5)
    capture = _acceptee(H.capturer(cap, H.ADMIN, "m5.comptes_a_payer", {}, recu(1)), "m5.comptes_a_payer")
    assert capture["pages"] == 2
    pages = H.captures_stockees()[0]["pages"]
    assert cs.extraire(pages[0], "resultat.resultat.reste")[0] > 0
    assert cs.extraire(pages[1], "resultat.resultat.reste") == [0]
    sans_pagination = dataclasses.replace(avec_marqueur, pagination=None)
    unique = cs.construire(sans_pagination, {}, pages[:1], recu_a=recu(2), reference=None, index=0,
                           hash_precedent=cs.HASH_INITIAL)
    assert unique["complete"] is False
    assert unique["raison_incomplete"] == PARTIELLE.format("resultat.resultat.reste")


def test_m5_comptes_a_payer_revision_corrections_et_derniere_modification_par_po(m5):
    """Une correction (pièce chaînée) ajoute `corrections` et `derniere_modification` : rendus pour un PO précis, pas
    dans la liste. Les chemins proposés les trouvent et la capture les conserve."""
    H.comptes_a_payer_m5(3)
    H.corriger_facture_m5("PO-B1")
    cap = H.capacites(H.M5)
    liste = _acceptee(H.capturer(cap, H.ADMIN, "m5.comptes_a_payer", {}, recu(1)), "m5.comptes_a_payer")
    detail = _acceptee(H.capturer(cap, H.ADMIN, "m5.comptes_a_payer", {"po_id": "PO-B1"}, recu(2)),
                       "m5.comptes_a_payer")
    assert liste["revisions"] == [] and detail["revisions"] == ["1"]
    page = H.page(1)
    assert H.valeurs(page, "resultat.resultat.comptes[*].factures_saisies[*].statut") == ["CORRIGEE"]
    assert H.valeurs(page, "resultat.resultat.comptes[*].factures_saisies[*].derniere_modification.horodatage") == [
        "2026-09-24T10:00:00-04:00"]
    assert H.valeurs(page, "resultat.resultat.comptes[*].rapprochement.verdict") == ["ECART"]
    assert detail["instants_metier"] == {"declares": True, "nombre": 2, "invalides": 0,
                                         "min": "2026-09-15T13:00:00Z", "max": "2026-09-24T14:00:00Z"}
    _verifier_chaine(cap)


def test_m5_comptes_a_payer_sans_po_capture_les_factures_une_par_ligne(m5):
    H.facture_sans_po_m5()
    cap = H.capacites(H.M5)
    _acceptee(H.capturer(cap, H.ADMIN, "m5.comptes_a_payer", {"sans_po": True}, recu(1)), "m5.comptes_a_payer")
    page = _page_ok()
    assert H.valeurs(page, "resultat.resultat.type") == ["COMPTES_A_PAYER_SANS_PO"]
    assert H.valeurs(page, "resultat.resultat.factures[*].categorie_depense") == ["carburant"]
    assert H.valeurs(page, "resultat.resultat.factures[*].apres_taxes") == ["97.16"]
    assert H.valeurs(page, "resultat.resultat.factures[*].corrections") == []  # jamais corrigée
    assert H.valeurs(page, "resultat.resultat.factures[*].date_facture") == ["2026-09-22"]  # date sans fuseau
    reponse = H.capturer(cap, H.ADMIN, "m5.comptes_a_payer", {"sans_po": True, "po_id": "PO-B1"}, recu(2))
    capture = _capture(reponse)  # incompatible : refus du producteur, conservé
    assert (capture["verdict"], capture["code"]) == ("REFUSEE", "REJ-AP-LISTE-FILTRE-INVALIDE")


# ============================================================================================ M8 analytics
@pytest.fixture
def m8(m5):
    H.alimenter_m8()
    return m5


def test_m8_vue_executive_capturee_entonnoir_marge_reelle_et_cash_libre(m8):
    cap = H.capacites(H.M8)
    capture = _acceptee(H.capturer(cap, H.ADMIN, "m8.vue_executive", {}, recu(1)), "m8.vue_executive")
    assert capture["reference"] is None
    page = _page_ok()
    mesures = {m["metric_id"]: m["valeur"] for m in H.valeurs(page, "resultat.entonnoir.mesures[*]")}
    assert mesures["m8_leads_recus"] == "1" and mesures["m8_devis_envoyes"] == "2"
    assert mesures["m8_devis_acceptes"] == "1" and mesures["m8_taux_acceptation_pct"] == "50.00"
    assert H.valeurs(page, "resultat.entonnoir.devis_en_attente.sans_reponse.devis") == [["DEVIS-B2"]]
    (marge,) = H.valeurs(page, "resultat.marge_reelle.chantiers[*]")
    assert (marge["wct_id"], marge["marge_reelle_cad"], marge["prix_definitif"]) == ("WCT-B1", "114.00", True)
    constat = H.valeurs(page, "resultat.cash_libre.constat")[0]
    assert (constat["sequence"], constat["date_reference"], constat["statut"]) == (1, "2026-09-29", "CALCULE")
    assert constat["cash_libre_cad"] == "12559.40" and constat["composantes"]["solde"] == "20000.00"
    assert H.valeurs(page, "resultat.cash_libre.age.jours") == [None]  # sans aujourd_hui, jamais deviné
    assert H.valeurs(page, "resultat.manques") == [[]]
    # chemins proposés
    proposee = _recalculer(0, "m8.vue_executive", {})
    assert proposee["instants"] == {"declares": True, "nombre": 6, "invalides": 0,
                                    "min": "2026-09-18T13:15:30Z", "max": "2026-09-27T12:00:00Z"}
    assert proposee["revisions"] == ["1"]
    reelle = _acceptee(H.capturer(cap, H.ADMIN, "m8.vue_executive", {}, recu(2)), "m8.vue_executive")
    assert reelle["instants_metier"]["max"] == "2026-09-27T12:00:00Z" and reelle["revisions"] == ["1"]
    _verifier_chaine(cap)


def test_m8_vue_executive_revision_suit_le_constat_du_cash_libre(m8):
    """Un 2e constat (le solde a changé) porte `sequence` 2 : deux captures de la même lecture se distinguent par
    leur révision déclarée, et leurs réponses ne se contredisent pas (révisions différentes)."""
    cap = H.capacites(H.M8)
    premiere = _acceptee(H.capturer(cap, H.ADMIN, "m8.vue_executive", {}, recu(1)), "m8.vue_executive")
    H.enregistrer_mouvements_m5()  # le solde change : un nouveau constat est dû
    with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
        constat = executer_atomique(next(o for o in m5_outils.outils() if o.nom == "m5_constater_cash_libre"),
                                    {"aujourd_hui": "2026-09-30"})
    assert constat["resultat"]["accepte"] is True
    H.livrer((H.M5, H.M8))
    seconde = _acceptee(H.capturer(cap, H.ADMIN, "m8.vue_executive", {}, recu(2)), "m8.vue_executive")
    assert (premiere["revisions"], seconde["revisions"]) == (["1"], ["2"])
    assert premiere["reponse_sha256"] != seconde["reponse_sha256"]
    assert cs.contradictions(H.captures_stockees()) == []


def test_m8_vue_executive_borne_ses_listes_a_trois_et_la_capture_est_partielle(m8):
    """Les devis sans réponse (comme les chantiers et le stock) sont nommés trois à la fois ; `reste` compte les autres
    et aucun argument ne permet de les voir : le producteur DÉCLARE sa troncature, la capture est PARTIELLE."""
    H.devis_sans_reponse_en_plus(("DEVIS-B3", "DEVIS-B4", "DEVIS-B5"))
    cap = H.capacites(H.M8)
    _partielle(H.capturer(cap, H.ADMIN, "m8.vue_executive", {}, recu(1)), "m8.vue_executive",
               "resultat.entonnoir.devis_en_attente.sans_reponse.reste")
    page = _page_ok()
    assert H.valeurs(page, "resultat.entonnoir.devis_en_attente.sans_reponse.n") == [4]
    assert len(H.valeurs(page, "resultat.entonnoir.devis_en_attente.sans_reponse.devis[*]")) == 3
    assert H.valeurs(page, "resultat.entonnoir.devis_en_attente.sans_reponse.reste") == [1]
    # les faits lus restent cités : instants et révision sont conservés malgré la troncature
    stockee = H.captures_stockees()[0]
    assert stockee["instants_metier"]["nombre"] == 6 and stockee["revisions"] == ["1"]
    _verifier_chaine(cap)





def test_m8_vue_executive_avec_aujourd_hui_capture_l_age_du_constat(m8):
    """`aujourd_hui` (jour, genre `date`) est conservé en `reference_jour` ; M8 date le constat du cash libre."""
    cap = H.capacites(H.M8)
    capture = _acceptee(H.capturer(cap, H.ADMIN, "m8.vue_executive", {"aujourd_hui": "2026-09-30"}, recu(1)),
                        "m8.vue_executive")
    assert capture["reference"] is None and _jour_reference() == "2026-09-30"
    assert H.valeurs(_page_ok(), "resultat.cash_libre.age.jours") == [1]
    assert H.valeurs(_page_ok(), "resultat.cash_libre.constat.date_reference") == ["2026-09-29"]


def test_m8_vue_executive_sans_aucun_fait_est_acceptee_et_dit_ses_manques(base):
    """Sans fait reçu, la lecture est ACCEPTEE et complète : seul son contenu dit qu'il n'y a rien (« manque »)."""
    cap = H.capacites(H.M8)
    _acceptee(H.capturer(cap, H.ADMIN, "m8.vue_executive", {}, recu(1)), "m8.vue_executive")
    page = _page_ok()
    assert H.valeurs(page, "resultat.cash_libre.statut") == ["manque"]
    assert H.valeurs(page, "resultat.cash_libre.manque") == [["cash_libre"]]
    assert H.valeurs(page, "resultat.marge_reelle.n_chantiers") == [0]
    assert H.valeurs(page, "resultat.entonnoir.sources[*].n") == [0, 0, 0, 0, 0]
    assert sorted(H.valeurs(page, "resultat.manques[*].champ")) == sorted([
        "cash_libre", "m2.client_associe", "m2.lead_assigne", "m3.devis_accepte", "m3.devis_envoye",
        "m3.devis_sans_reponse"])
    # chemin proposé : `dernier_fait_le` vaut null pour une source sans fait ; M9 compte ces null « invalides »
    proposee = _recalculer(0, "m8.vue_executive", {})["instants"]
    assert (proposee["nombre"], proposee["invalides"], proposee["min"]) == (0, 5, None)


def test_m8_mesures_chantier_capturees_avec_marge_reelle_et_version_des_entrees(m8):
    cap = H.capacites(H.M8)
    _acceptee(H.capturer(cap, H.ADMIN, "m8.mesures_chantier", {"wct_id": H.WCT_ID}, recu(1)), "m8.mesures_chantier")
    page = _page_ok()
    assert H.valeurs(page, "resultat.trouve") == [True]
    assert (H.valeurs(page, "resultat.wct_id"), H.valeurs(page, "resultat.devis_id")) == (["WCT-B1"], ["DEVIS-B1"])
    par_metrique = {m["metric_id"]: m for m in H.valeurs(page, "resultat.mesures[*]")}
    assert par_metrique["m8_ecart_duree_minutes"]["valeur"] == "120.00"
    assert par_metrique["m8_marge_prevue_cad"]["valeur"] == "120.00"
    assert par_metrique["m8_marge_reelle_cad"]["valeur"] == "114.00"
    assert par_metrique["m8_ecart_marge_cad"]["valeur"] == "-6.00"
    assert H.valeurs(page, "resultat.seuils_a_configurer") == [
        ["m8_ecart_duree_pct", "m8_ecart_marge_pct", "m8_ecart_materiaux_max_pct"]]  # aucun seuil déclaré
    (version,) = H.valeurs(page, "resultat.mesures[*].entrees.version_entrees")
    assert len(version) == 64
    assert H.valeurs(page, "resultat.horodatage_completion") == ["2026-09-25T16:30:00-04:00"]
    proposee = _recalculer(0, "m8.mesures_chantier", {"wct_id": H.WCT_ID})
    assert proposee["instants"] == {"declares": True, "nombre": 1, "invalides": 0,
                                    "min": "2026-09-25T20:30:00Z", "max": "2026-09-25T20:30:00Z"}
    assert proposee["revisions"] == [version]
    reelle = _acceptee(H.capturer(cap, H.ADMIN, "m8.mesures_chantier", {"wct_id": H.WCT_ID}, recu(2)),
                       "m8.mesures_chantier")
    assert reelle["revisions"] == [version] and reelle["instants_metier"]["nombre"] == 1
    _verifier_chaine(cap)


def test_m8_mesures_chantier_wct_inconnu_est_partielle(m8):
    """`{"trouve": false, "verdict": "REJ-CHANTIER-INCONNU:…"}` : la réponse est « vide » par déclaration du
    producteur (`trouve` faux), la capture est PARTIELLE ; l'accord du producteur (ACCEPTEE) reste conservé."""
    cap = H.capacites(H.M8)
    capture = _partielle(H.capturer(cap, H.ADMIN, "m8.mesures_chantier", {"wct_id": "WCT-INCONNU"}, recu(1)),
                         "m8.mesures_chantier", "resultat.trouve")
    assert capture["instants_metier"]["nombre"] == 0
    page = _page_ok()
    assert H.valeurs(page, "resultat.trouve") == [False]
    assert H.valeurs(page, "resultat.verdict") == ["REJ-CHANTIER-INCONNU:WCT-INCONNU"]
    connu = _acceptee(H.capturer(cap, H.ADMIN, "m8.mesures_chantier", {"wct_id": H.WCT_ID}, recu(2)),
                      "m8.mesures_chantier")
    assert connu["complete"] is True


# =========================================================================================== M7 marketing
@pytest.fixture
def m7(m5):
    H.alimenter_m7()
    return m5


def test_m7_performance_campagnes_capturee_marge_m5_sans_depense_ni_roi(m7):
    cap = H.capacites(H.M7)
    capture = _acceptee(H.capturer(cap, H.ADMIN, "m7.performance_campagnes", dict(PERIODE), recu(1)),
                        "m7.performance_campagnes")
    assert capture["reference"] is None and capture["pages"] == 1
    page = _page_ok()
    assert H.valeurs(page, "resultat.type") == ["PERFORMANCE_CAMPAGNES"]
    assert H.valeurs(page, "resultat.periode") == [PERIODE]  # écho des arguments, pas un fait du producteur
    (campagne,) = H.valeurs(page, "resultat.campagnes[*]")
    assert (campagne["source"], campagne["campagne"]) == ("google", "automne")
    assert (campagne["leads_associes_observes"], campagne["devis_acceptes"]) == (1, 1)
    assert (campagne["chantiers_marge_constatee"], campagne["marge_constatee_M5_cad"]) == (1, "114.00")
    assert campagne["cout_ads_cad"] is None and campagne["roi"] is None
    assert (campagne["statut_financier"], campagne["couverture"]) == ("INCONNU", "PARTIELLE")
    assert "DEPENSES_NON_BRANCHEES" in campagne["manque"]
    # « complète » pour M9 (une page lue) alors que le producteur dit PARTIELLE : deux notions distinctes
    assert H.valeurs(page, "resultat.couverture") == ["PARTIELLE"]
    _verifier_chaine(cap)


def test_m7_revisions_sont_les_sequences_m5_et_aucun_instant_metier_n_est_declare(m7, proposer):
    cap = H.capacites(H.M7)
    _acceptee(H.capturer(cap, H.ADMIN, "m7.performance_campagnes", dict(PERIODE), recu(1)), "m7.performance_campagnes")
    page = _page_ok()
    sequences = H.valeurs(page, "resultat.source_refs[*].sequence")
    assert sorted(sequences) == [1, 2]  # toutes les rentabilités lues ; la plus haute fait foi pour la marge
    assert H.valeurs(page, "resultat.campagnes[*].source_refs[*].sequence") == [2]
    # `observation_source` : horloge de lecture et date SQL sans fuseau → aucun instant métier utilisable
    source = H.valeurs(page, "resultat.observation_source")[0]
    assert source["definition_temps"] == "dates_metier_faits_disponibles_a_la_lecture"
    assert cs.instant(source["dernier_cree_le_sql"]) is None and cs.instant(source["lue_le"]) is not None
    assert (source["lignes_lues"], source["rang_max"]) == (4, 3)
    proposition_m7 = H.proposition("m7.performance_campagnes")
    assert _recalculer(0, "m7.performance_campagnes", dict(PERIODE), proposition_m7)["revisions"] == ["1", "2"]
    proposer("m7.performance_campagnes")
    reelle = _acceptee(H.capturer(cap, H.ADMIN, "m7.performance_campagnes", dict(PERIODE), recu(2)),
                       "m7.performance_campagnes")
    assert reelle["revisions"] == ["1", "2"] and reelle["instants_metier"]["declares"] is False


def test_m7_la_reponse_contient_une_horloge_donc_deux_lectures_identiques_different(m7, proposer):
    """`observation_source.lue_le` est l'heure de la lecture : deux captures sans aucun fait nouveau ont des empreintes
    différentes. Avec la révision proposée, M9 les jugerait donc CONTRADICTOIRES (même lecture, mêmes arguments, même
    révision, empreintes différentes) : à corriger côté M7 (retirer `lue_le`) avant de déclarer cette révision."""
    cap = H.capacites(H.M7)
    _acceptee(H.capturer(cap, H.ADMIN, "m7.performance_campagnes", dict(PERIODE), recu(1)), "m7.performance_campagnes")
    _acceptee(H.capturer(cap, H.ADMIN, "m7.performance_campagnes", dict(PERIODE), recu(2)), "m7.performance_campagnes")
    premiere, seconde = H.captures_stockees()
    assert premiere["reponse_sha256"] != seconde["reponse_sha256"]
    lues = [H.valeurs(c["pages"][0], "resultat.observation_source.lue_le")[0] for c in (premiere, seconde)]
    assert lues[0] != lues[1]
    sans_horloge = [
        {**c["pages"][0], "resultat": {k: v for k, v in c["pages"][0]["resultat"].items() if k != "observation_source"}}
        for c in (premiere, seconde)]
    assert cs.empreinte(sans_horloge[0]) == cs.empreinte(sans_horloge[1])  # le reste est identique
    assert cs.contradictions(H.captures_stockees()) == []  # catalogue actuel : aucune révision déclarée
    proposition = H.proposition("m7.performance_campagnes")
    a = cs.construire(proposition, PERIODE, premiere["pages"], recu_a=premiere["recu_a"], reference=None, index=0,
                      hash_precedent=cs.HASH_INITIAL)
    b = cs.construire(proposition, PERIODE, seconde["pages"], recu_a=seconde["recu_a"], reference=None, index=1,
                      hash_precedent=a["hash_maillon"])
    assert len(cs.contradictions([a, b])) == 1  # faux positif


def test_m7_periode_hors_cohorte_et_periode_inversee(m7):
    cap = H.capacites(H.M7)
    vide = _capture(H.capturer(cap, H.ADMIN, "m7.performance_campagnes",
                               {"debut": "2026-01-01", "fin": "2026-01-31"}, recu(1)))
    assert vide["verdict"] == "ACCEPTEE" and vide["complete"] is True  # accepté : le contenu dit INCONNUE
    page = H.page(0)
    assert H.valeurs(page, "resultat.couverture") == ["INCONNUE"] and H.valeurs(page, "resultat.campagnes") == [[]]
    assert H.valeurs(page, "resultat.exclusions.associations_hors_cohorte") == [1]
    inversee = _capture(H.capturer(cap, H.ADMIN, "m7.performance_campagnes",
                                   {"debut": "2026-09-30", "fin": "2026-09-01"}, recu(2)))
    assert (inversee["verdict"], inversee["code"], inversee["complete"]) == ("ERREUR", "refus_metier", False)
    assert "PERIODE_INVERSEE" in str(H.page(1))


def test_m7_arguments_requis(m7):
    cap = H.capacites(H.M7)
    capture = _capture(H.capturer(cap, H.ADMIN, "m7.performance_campagnes", {"debut": "2026-09-01"}, recu(1)))
    assert (capture["verdict"], capture["code"]) == ("ERREUR", "arguments_invalides")


# ========================================================================================== M1 front office
def test_m1_digest_a_des_donnees_reelles_par_le_port_mais_aucun_champ_structure(base):
    """Le digest est un TEXTE agrégé (compteurs par canal et type, pour la date de référence)."""
    H.demandes_m1()
    jour_28 = H.lire_par_le_port(H.M1, "m1_produire_digest", {"date_reference": "2026-09-28"})
    jour_29 = H.lire_par_le_port(H.M1, "m1_produire_digest", {"date_reference": "2026-09-29"})
    texte_28, texte_29 = jour_28["resultat"], jour_29["resultat"]
    assert isinstance(texte_28, str) and texte_28.startswith("DIGEST - Période de référence : 2026-09-28")
    assert "- texte: signal: 1" in texte_28 and "- courriel: signal: 1" in texte_28
    assert "- texte: lead_emis: 1" in texte_28 and "- courriel: lead_emis: 1" in texte_28
    assert "- formulaire: signal: 1" in texte_29 and "- formulaire: signal: 0" in texte_28
    assert "- entrées non classées : 0" in texte_28
    assert "Montréal" not in texte_28 and "514" not in texte_28  # aucune donnée de client dans le digest
    assert H.valeurs(jour_28, "resultat.signal") == [] and H.valeurs(jour_28, "resultat.instants") == []


def test_m1_digest_capture_avec_son_jour_de_reference_sans_champ_structure(base):
    """`date_reference` est un JOUR (genre `date`) : le digest (texte) est conservé, le jour en `reference_jour`.
    Le texte n'a ni instant ni révision déclarés. Sans date, M1 refuse et M9 conserve ce refus ; un producteur absent
    est désormais conservé comme ERREUR."""
    H.demandes_m1()
    cap = H.capacites(H.M1)
    assert cat.PAR_ID["m1.digest"].reference_genre == "date"
    capture = _acceptee(H.capturer(cap, H.ADMIN, "m1.digest", {"date_reference": "2026-09-28"}, recu(1)),
                        "m1.digest")
    assert capture["reference"] is None and _jour_reference() == "2026-09-28"
    texte = H.page(0)["resultat"]
    assert texte.startswith("DIGEST - Période de référence : 2026-09-28")
    assert "- courriel: signal: 1" in texte and "- texte: lead_emis: 1" in texte and "- formulaire: signal: 0" in texte
    assert capture["instants_metier"]["declares"] is False and capture["revisions"] == []
    sans_date = _capture(H.capturer(cap, H.ADMIN, "m1.digest", {}, recu(2)))
    assert (sans_date["verdict"], sans_date["code"], sans_date["complete"]) == ("ERREUR", "arguments_invalides", False)
    installes = {k: v for k, v in charger_departements().items() if k != H.M1}
    absent = Capacites(installes, stockage.transaction, filtre={H.M9}, memoire=False)
    manque = _capture(H.capturer(absent, H.ADMIN, "m1.digest", {"date_reference": "2026-09-28"}, recu(3)))
    assert (manque["verdict"], manque["code"], manque["complete"]) == ("ERREUR", "producteur_indisponible", False)
    _verifier_chaine(cap)


def test_m1_digest_date_invalide_est_refusee_par_m1_avant_toute_reference(base):
    """Date non calendaire : M9 la refuse déjà comme référence sans fuseau (la lecture a eu lieu : M1 l'a aussi
    refusée), rien n'est conservé."""
    cap = H.capacites(H.M1)
    refus_port = H.lire_par_le_port(H.M1, "m1_produire_digest", {"date_reference": "2026-02-30"})
    assert refus_port["resultat"]["accepte"] is False
    assert refus_port["resultat"]["verdict"]["code"] == "REJ-DIGEST-DATE-INVALIDE"
    _refusee_avant_ecriture(H.capturer(cap, H.ADMIN, "m1.digest", {"date_reference": "2026-02-30"}, recu(1)),
                            "REJ-CAPTURE-TEMPS")


# =========================================================================================== M10 mémoire
@pytest.fixture
def m10(m5):
    H.alimenter_m10()
    return m5


def test_m10_paquet_affaire_capture_quatre_couches_filtrees_pour_m9(m10):
    """Le paquet est TRONQUÉ par son budget (5 faits sur 7) : capture PARTIELLE, mais les faits rendus sont cités."""
    cap = H.capacites(H.M10)
    capture = _partielle(H.capturer(cap, H.ADMIN, "m10.paquet_affaire", dict(PAQUET), recu(1)), "m10.paquet_affaire",
                         "resultat.couches[*].tronque")
    assert capture["reference"] == "2026-10-01T12:00:00Z"  # l'horodatage demandé, ramené en UTC
    page = _page_ok()
    assert H.valeurs(page, "resultat.affaire_id") == [H.LEAD_ID]
    assert H.valeurs(page, "resultat.affaire") == [
        {"connue": True, "origine": "m1.lead_qualifie", "origine_recue": True, "verdict": None}]
    assert H.valeurs(page, "resultat.couches[*].nom") == [
        "regles_entreprise", "faits_affaire", "evenements_recents", "signaux_non_resolus"]
    # le destinataire est M9 (fixé par le port, jamais par l'appelant) : la vue la plus restrictive lui convient
    assert H.valeurs(page, "resultat.confidentialite.agent") == [H.M9]
    assert H.valeurs(page, "resultat.confidentialite.nb_retenus") == [4]
    sources = H.valeurs(page, "resultat.couches[*].faits[*].source")
    assert sorted(sources) == ["m3.devis_accepte", "m3.devis_envoye", "m3.devis_sans_reponse", "m4.travaux_termines",
                               "m6.variance_chantier"]
    assert H.valeurs(page, "resultat.signaux") == [{"nb_clos": 0, "nb_ouverts": 0, "nb_pris_en_compte": 0}]
    assert H.valeurs(page, "resultat.consolidation.nb_a_consolider") == [2]
    _verifier_chaine(cap)


def test_m10_paquet_ne_fait_sortir_ni_donnee_client_ni_montant(m10):
    """Le contact du lead (CLIENT_PRIVATE), le client associé et la rentabilité (FINANCIAL, 114.00) sont dans les
    registres de M10 ou du bus ; aucun n'atteint la page conservée par M9."""
    cap = H.capacites(H.M10)
    _partielle(H.capturer(cap, H.ADMIN, "m10.paquet_affaire", dict(PAQUET), recu(1)), "m10.paquet_affaire",
               "resultat.couches[*].tronque")
    texte = str(H.captures_stockees())
    for interdit in (*H.CONTACT.values(), "Repentigny", "514", H.CLIENT_ID, "600.00", "480.00", "114.00", "486.00",
                     "marge", "TECH-B1-fictif"):
        assert interdit not in texte, interdit


def test_m10_paquet_instants_des_faits_et_pas_de_revision(m10):
    cap = H.capacites(H.M10)
    _partielle(H.capturer(cap, H.ADMIN, "m10.paquet_affaire", dict(PAQUET), recu(1)), "m10.paquet_affaire",
               "resultat.couches[*].tronque")
    horodatages = H.valeurs(H.page(0), "resultat.couches[*].faits[*].horodatage")
    assert sorted(horodatages) == sorted([
        "2026-09-27T08:00:00-04:00", "2026-09-25T16:30:00-04:00", "2026-09-25T16:30:00-04:00",
        "2026-09-20T10:00:00-04:00", "2026-09-19T15:30:00-04:00"])
    proposee = _recalculer(0, "m10.paquet_affaire", dict(PAQUET))
    assert proposee["instants"] == {"declares": True, "nombre": 5, "invalides": 0,
                                    "min": "2026-09-19T19:30:00Z", "max": "2026-09-27T12:00:00Z"}
    assert proposee["revisions"] == []
    # l'horodatage du paquet est un écho de l'argument, jamais un instant métier
    assert H.valeurs(H.page(0), "resultat.horodatage") == [PAQUET["horodatage"]]
    reelle = _partielle(H.capturer(cap, H.ADMIN, "m10.paquet_affaire", dict(PAQUET), recu(2)), "m10.paquet_affaire",
                        "resultat.couches[*].tronque")
    assert reelle["instants_metier"]["max"] == "2026-09-27T12:00:00Z" and reelle["revisions"] == []


def test_m10_paquet_tronque_par_le_budget_est_partielle_et_ses_faits_sont_cites(m10):
    """Cinq faits par couche au plus : 7 événements, 5 rendus, `nb_omis` 2 et `tronque` vrai. Aucun argument de reprise
    n'existe : la capture est PARTIELLE, et les faits rendus restent cités (instants conservés). Les jours omis sont à
    consolider (`consolidation`)."""
    cap = H.capacites(H.M10)
    capture = _partielle(H.capturer(cap, H.ADMIN, "m10.paquet_affaire", dict(PAQUET), recu(1)), "m10.paquet_affaire",
                         "resultat.couches[*].tronque")
    assert capture["instants_metier"]["nombre"] == 5
    page = _page_ok()
    (evenements,) = [c for c in H.valeurs(page, "resultat.couches[*]") if c["nom"] == "evenements_recents"]
    assert (evenements["nb_total"], evenements["nb_inclus"], evenements["nb_omis"], evenements["tronque"]) == (
        7, 5, 2, True)
    assert len(evenements["faits"]) == 5
    assert H.valeurs(page, "resultat.consolidation.a_consolider[*].jour") == ["2026-09-18", "2026-09-19"]
    reponse = H.capturer(cap, H.ADMIN, "m10.paquet_affaire", {**PAQUET, "budget_caracteres": 8000}, recu(2))
    assert reponse["ok"] is False and "REJ-CAPTURE-ARGUMENTS" in reponse["details"]





def test_m10_affaire_inconnue_est_acceptee_avec_son_verdict_dans_la_page(m10):
    cap = H.capacites(H.M10)
    _acceptee(H.capturer(cap, H.ADMIN, "m10.paquet_affaire",
                         {"affaire_id": "LEAD-INCONNU", "horodatage": PAQUET["horodatage"]}, recu(1)),
              "m10.paquet_affaire")
    page = _page_ok()
    assert H.valeurs(page, "resultat.affaire.verdict") == ["AMONT-AFFAIRE-INCONNUE"]
    assert H.valeurs(page, "resultat.affaire.connue") == [False]
    assert H.valeurs(page, "resultat.couches[*].vide") == [True, True, True, True]
    assert H.valeurs(page, "resultat.confidentialite.nb_retenus") == [0]


def test_m10_affaire_id_invalide_est_une_erreur_conservee_et_horodatage_sans_fuseau_est_refuse(m10):
    cap = H.capacites(H.M10)
    invalide = _capture(H.capturer(cap, H.ADMIN, "m10.paquet_affaire",
                                   {"affaire_id": "n'importe quoi", "horodatage": PAQUET["horodatage"]}, recu(1)))
    assert (invalide["verdict"], invalide["code"], invalide["complete"]) == ("ERREUR", "refus_metier", False)
    for sans_fuseau in ("2026-10-01", "2026-10-01T08:00:00"):
        reponse = H.capturer(cap, H.ADMIN, "m10.paquet_affaire", {**PAQUET, "horodatage": sans_fuseau}, recu(2))
        assert reponse["ok"] is False and "REJ-CAPTURE-TEMPS" in reponse["details"]
    assert len(H.captures_stockees()) == 1


# =================================================================================== les chemins proposés
@pytest.mark.parametrize("lecture_id", sorted(H.PROPOSITIONS))
def test_catalogue_declare_les_chemins_proposes_sauf_les_revisions_de_m7(lecture_id):
    """Le catalogue adopté porte les instants, révisions et la pagination proposés ; seule M7 reste sans révision (sa
    réponse contient une horloge : les deux lectures d'une même donnée diffèrent)."""
    actuelle = cat.PAR_ID[lecture_id]
    proposee = H.proposition(lecture_id)
    assert (proposee.departement, proposee.outil, proposee.libres, proposee.fixes, proposee.reference) == (
        actuelle.departement, actuelle.outil, actuelle.libres, actuelle.fixes, actuelle.reference)
    assert actuelle.instants_metier == proposee.instants_metier
    assert actuelle.pagination == proposee.pagination
    assert actuelle.revisions == (() if lecture_id == "m7.performance_campagnes" else proposee.revisions)
    for chemin in (*proposee.instants_metier, *proposee.revisions):
        assert chemin.startswith("resultat."), chemin
