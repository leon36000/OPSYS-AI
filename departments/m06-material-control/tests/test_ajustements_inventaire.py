"""C10 — ajustements d'inventaire audités : `m6_ajuster_stock` (N3), motif TYPÉ, avant/après stockés, preuve CAS
facultative, seuil d'approbation DÉCLARÉ, chaîne de l'existant inchangée.

Rouge-avant : `m6_material_control.ajustements` n'existe pas et l'outil `m6_ajuster_stock` n'est pas déclaré. Les
tests ci-dessous décrivent d'abord le comportement attendu.

Vrais outils, base SQLite migrée, vrais registres durables de M6 ; quantités et identifiants FICTIFS.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

from m6_material_control import ajustements
from sqlalchemy import select

from opsys import stockage
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

_spec = importlib.util.spec_from_file_location(
    "fixture_ajustements_inventaire", Path(__file__).with_name("test_reservation_outils.py")
)
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)
base, m6 = aide.base, aide.m6

FICTIF = True
GOUTTIERE = aide.GOUTTIERE
H_ADJUST = "2026-10-08T10:00:00-04:00"
PREUVE = "fichier:sha256:" + "a" * 64


def _demande(**remplacements):
    demande = {
        "ajustement_id": "AJUST-FICT-1",
        "materiau_id": GOUTTIERE,
        "motif": "erreur_saisie",
        "quantite_apres": 8,
        "preuve": PREUVE,
        "horodatage": H_ADJUST,
        "acteur": "nathan-fictif",
    }
    demande.update(remplacements)
    return demande


def _valider(demande=None, stock_avant="10", seuil="5"):
    normalisee, verdict = ajustements.valider_demande(demande or _demande())
    assert verdict is None, verdict
    qualify, verdict = ajustements.qualifier(normalisee, Decimal(stock_avant), seuil)
    assert verdict is None, verdict
    return qualify


def _outil(nom, arguments):
    outil = next(o for o in aide.m6_outils.outils() if o.nom == nom)
    reponse = executer_atomique(outil, arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _maillons(nom="principal"):
    with stockage.transaction():
        return list(stockage.maillons(aide._DEPARTEMENT, nom))


def _stock(materiau=GOUTTIERE):
    resultat = _outil("m6_lire_disponibilite", {"materiau_ids": [materiau]})["resultat"]
    return resultat["articles"][0]


def _ligne_inventaire(identifiant, materiau, quantite, emplacement):
    ligne = _demande(
        ajustement_id=identifiant,
        materiau_id=materiau,
        motif="inventaire_physique",
        quantite_apres=quantite,
        emplacement=emplacement,
    )
    ligne.pop("acteur")  # L'acteur est toujours repris de l'identité d'appel, jamais du payload.
    return ligne


def _lot(ajustements):
    outil = next(o for o in aide.m6_outils.outils() if o.nom == "m6_clore_inventaire_physique")
    return executer_atomique(outil, {"ajustements": ajustements})


def _localiser(materiau, quantite, emplacement, transfert_id):
    return _outil("m6_transferer_stock", {
        "transfert_id": transfert_id,
        "materiau_id": materiau,
        "quantite": quantite,
        "de": {"type": "inconnu"},
        "vers": emplacement,
        "motif": "ranger pour inventaire fictif",
        "horodatage": H_ADJUST,
    })


# --------------------------------------------------------------------------------------------- module pur
def test_les_six_motifs_types_sont_acceptes_et_aucun_autre():
    assert set(ajustements.MOTIFS_AJUSTEMENT) == {
        "correction", "stock_retrouve", "retour_fournisseur", "erreur_saisie", "inventaire_physique", "annulation",
    }
    for motif in ajustements.MOTIFS_AJUSTEMENT:
        normalisee, verdict = ajustements.valider_demande(_demande(motif=motif))
        assert verdict is None and normalisee["motif"] == motif
    for hostile in ("vol", "perte", "", "Correction", None, 3):
        _, verdict = ajustements.valider_demande(_demande(motif=hostile))
        assert verdict is not None and verdict["code"] == "REJ-AJUSTEMENT-MOTIF-INVALIDE", hostile


def test_un_identifiant_non_textuel_est_refuse_sans_lever():
    for hostile in (3, True, None, ["AJUST-FICT-1"]):
        _, verdict = ajustements.valider_demande(_demande(ajustement_id=hostile))
        assert verdict is not None and verdict["code"] == "REJ-AJUSTEMENT-STRUCTURE-INVALIDE", hostile


def test_un_motif_absent_est_refuse_avant_toute_ecriture():
    demande = _demande()
    del demande["motif"]
    _, verdict = ajustements.valider_demande(demande)
    assert verdict["code"] == "REJ-AJUSTEMENT-STRUCTURE-INVALIDE"


def test_quantite_apres_negative_non_finie_ou_booleenne_refusee():
    for hostile in (-1, -0.01, float("nan"), float("inf"), True, "8", None, 10**40):
        _, verdict = ajustements.valider_demande(_demande(quantite_apres=hostile))
        assert verdict is not None and verdict["code"] == "REJ-AJUSTEMENT-QUANTITE-INVALIDE", hostile


def test_preuve_cas_facultative_mais_mal_formee_refusee():
    normalisee, verdict = ajustements.valider_demande({**_demande(), "preuve": None})
    assert verdict is None and normalisee["preuve"] is None
    normalisee, verdict = ajustements.valider_demande({k: v for k, v in _demande().items() if k != "preuve"})
    assert verdict is None and normalisee["preuve"] is None
    for hostile in ("", "photo.jpg", "fichier:sha256:abc", "fichier:sha256:" + "G" * 64, 3):
        _, verdict = ajustements.valider_demande(_demande(preuve=hostile))
        assert verdict is not None and verdict["code"] == "REJ-AJUSTEMENT-PREUVE-INVALIDE", hostile


def test_avant_apres_et_delta_sont_exacts_et_jamais_inverses():
    qualify = _valider(stock_avant="10.5", seuil="5")
    assert (qualify["quantite_avant"], qualify["quantite_apres"], qualify["delta"]) == ("10.5", "8", "-2.5")
    assert Decimal(qualify["delta"]) == Decimal("-2.5")
    hausse = _valider(_demande(quantite_apres=12), stock_avant="10.5", seuil="5")
    assert (hausse["quantite_avant"], hausse["quantite_apres"], hausse["delta"]) == ("10.5", "12", "1.5")


def test_le_seuil_est_inclus_et_depasse_strictement():
    sous = _valider(_demande(quantite_apres=8), stock_avant="10", seuil="2")
    assert (sous["niveau_approbation"], sous["motif_approbation"]) == ("N3", "sous_seuil")
    egal = _valider(_demande(quantite_apres=8), stock_avant="10", seuil="2")
    assert egal["delta"] == "-2" and egal["niveau_approbation"] == "N3"
    au_dela = _valider(_demande(quantite_apres=7.99), stock_avant="10", seuil="2")
    assert (au_dela["niveau_approbation"], au_dela["motif_approbation"]) == ("N4", "seuil_depasse")


def test_seuil_absent_ou_illisible_escalade_en_n4_jamais_un_defaut():
    for seuil in (None, "beaucoup", -1, 0, float("nan")):
        qualify = _valider(seuil=seuil)
        assert (qualify["niveau_approbation"], qualify["motif_approbation"]) == ("N4", "seuil_absent"), seuil
        assert qualify["seuil"] is None


def test_zero_et_quarante_caracteres_sont_acceptes_quarante_et_un_refuse():
    zero, verdict = ajustements.valider_demande(_demande(quantite_apres=0))
    assert verdict is None and zero["quantite_apres"] == "0"
    quarante, verdict = ajustements.valider_demande(_demande(quantite_apres=10**39))
    assert verdict is None and len(quarante["quantite_apres"]) == 40
    _, verdict = ajustements.valider_demande(_demande(quantite_apres=10**40))
    assert verdict["code"] == "REJ-AJUSTEMENT-QUANTITE-INVALIDE"


def test_un_seuil_inferieur_a_un_est_utilisable_et_la_borne_reste_incluse():
    sous = _valider(_demande(quantite_apres=Decimal("10.2")), stock_avant="10", seuil="0.5")
    assert (sous["niveau_approbation"], sous["motif_approbation"]) == ("N3", "sous_seuil")
    au_dela = _valider(_demande(quantite_apres=Decimal("10.6")), stock_avant="10", seuil="0.5")
    assert au_dela["niveau_approbation"] == "N4"


def test_construire_transfert_seulement_pour_un_ecart_non_nul_et_un_lieu_nomme():
    sans_lieu = _valider(_demande(quantite_apres=8), stock_avant="10", seuil="5")
    assert ajustements.construire_transfert(sans_lieu) is None
    inconnu = _valider({**_demande(quantite_apres=8), "emplacement": {"type": "inconnu"}}, stock_avant="10", seuil="5")
    assert ajustements.construire_transfert(inconnu) is None
    depot = {**_demande(quantite_apres=8), "emplacement": {"type": "depot"}}
    aucun = _valider(depot, stock_avant="8", seuil="5")
    assert aucun["delta"] == "0" and ajustements.construire_transfert(aucun) is None
    hausse = _valider(depot, stock_avant="7.5", seuil="5")
    transfert = ajustements.construire_transfert(hausse)
    assert transfert["de"] == {"type": "inconnu", "reference": None}
    assert transfert["vers"] == {"type": "depot", "reference": None}
    assert Decimal(str(transfert["quantite"])) == Decimal("0.5")
    baisse = _valider(depot, stock_avant="9", seuil="5")
    transfert = ajustements.construire_transfert(baisse)
    assert transfert["de"] == {"type": "depot", "reference": None}
    assert transfert["vers"] == {"type": "inconnu", "reference": None}
    assert Decimal(str(transfert["quantite"])) == Decimal("1")


def test_deja_enregistre_ignore_un_maillon_mal_forme_sans_lever():
    assert ajustements.deja_enregistre("A", [{"type_mouvement": "AJUSTEMENT", "ajustement": "pas-un-objet"}]) is None
    assert ajustements.deja_enregistre("A", [{"type_mouvement": "RECEPTION", "ajustement": "x"}]) is None
    mouvement = {"type_mouvement": "AJUSTEMENT", "ajustement": {"ajustement_id": "A"}}
    assert ajustements.deja_enregistre("A", [mouvement]) is mouvement
    assert ajustements.deja_enregistre("B", [mouvement]) is None


def test_aucun_ecart_ne_produit_aucune_ecriture():
    qualify = _valider(_demande(quantite_apres=10), stock_avant="10", seuil="5")
    assert qualify["aucun_ecart"] is True and qualify["delta"] == "0"


def test_un_emplacement_est_normalise_et_une_reference_manquante_refusee():
    normalisee, verdict = ajustements.valider_demande(
        {**_demande(), "emplacement": {"type": "camion", "reference": "CAM-FICTIF-1"}}
    )
    assert verdict is None and normalisee["emplacement"] == {"type": "camion", "reference": "CAM-FICTIF-1"}
    _, verdict = ajustements.valider_demande({**_demande(), "emplacement": {"type": "camion"}})
    assert verdict is not None and verdict["code"] == "REJ-EMPLACEMENT-REFERENCE-MANQUANTE"


def test_une_unite_invalide_est_refusee_par_ajouter_et_ajouter_lot():
    from m6_material_control.registre import Registre

    base = {"type_mouvement": "RECEPTION", "chantier_id": "CH-FICT", "materiau_id": GOUTTIERE,
            "quantite": 1.0, "cout_unitaire": 2.0}
    for unite in ("", "   ", 3):
        for methode in ("ajouter", "ajouter_lot"):
            registre = Registre()
            if methode == "ajouter":
                _, erreur = registre.ajouter({**base, "unite": unite})
            else:
                _, erreur = registre.ajouter_lot([{**base, "unite": unite}])
            assert erreur == "REJ-MOUVEMENT-UNITE-INVALIDE", (methode, unite)


def test_une_chaine_alteree_est_refusee_et_non_acceptee():
    from m6_material_control.registre import Registre

    registre = Registre()
    registre.ajouter({"type_mouvement": "RECEPTION", "chantier_id": "CH-FICT", "materiau_id": GOUTTIERE,
                      "quantite": 1.0, "cout_unitaire": 2.0})
    registre.ajouter({"type_mouvement": "CONSOMMATION", "chantier_id": "CH-FICT", "materiau_id": GOUTTIERE,
                      "quantite": -0.5, "cout_unitaire": 2.0})
    maillons = registre.lire()
    maillons[1]["hash_precedent"] = "0" * 64
    valide, detail = Registre(maillons=maillons).valider_chaine()
    assert valide is False and detail == "maillon invalide à l'index 1"


def test_une_origine_cout_valide_reste_acceptee_et_un_objet_non_dict_refuse():
    """La garde d'origine de coût de `registre.py` n'est pas modifiée par C10 : un mouvement légitime passe, un
    origine mal formée est refusée (aucune écriture)."""
    from m6_material_control.registre import Registre

    valide = Registre()
    maillon, erreur = valide.ajouter({
        "type_mouvement": "CONSOMMATION", "chantier_id": "CH-FICT", "materiau_id": GOUTTIERE,
        "quantite": -1.0, "cout_unitaire": 2.0, "origine_cout": {"source": "RECEPTION_ARTICLE"},
    })
    assert erreur is None and maillon["origine_cout"] == {"source": "RECEPTION_ARTICLE"}
    invalide = Registre()
    _, erreur = invalide.ajouter({
        "type_mouvement": "CONSOMMATION", "chantier_id": "CH-FICT", "materiau_id": GOUTTIERE,
        "quantite": -1.0, "cout_unitaire": 2.0, "origine_cout": "RECEPTION_ARTICLE",
    })
    assert erreur == "REJ-MOUVEMENT-ORIGINE-COUT-INVALIDE"


def test_le_seuil_d_ajustement_est_lu_et_reste_fail_closed(monkeypatch, tmp_path):
    manifeste = tmp_path / "department.yaml"
    monkeypatch.setattr(aide.m6_outils, "_MANIFESTE", manifeste)
    manifeste.write_text("configuration: {}\n", encoding="utf-8")
    assert aide.m6_outils._seuil_ajustement_stock() is None
    for brut, attendu in (("2.5", Decimal("2.5")), (2.5, Decimal("2.5")), ("0.5", Decimal("0.5")), ("0", None),
                          (-1, None), ("abc", None), (True, None), ("", None)):
        manifeste.write_text(
            f"configuration:\n  seuil_ajustement_stock_quantite: {brut!r}\n", encoding="utf-8")
        assert aide.m6_outils._seuil_ajustement_stock() == attendu, brut


def test_les_reglages_d_alertes_sont_lus_et_les_valeurs_invalides_ignorees(monkeypatch, tmp_path):
    manifeste = tmp_path / "department.yaml"
    monkeypatch.setattr(aide.m6_outils, "_MANIFESTE", manifeste)
    manifeste.write_text("configuration: {}\n", encoding="utf-8")
    assert aide.m6_outils._configuration_alertes() == {"fenetre_jours": None, "seuil_repetition": None}
    manifeste.write_text(
        "configuration:\n  alertes_approvisionnement:\n    fenetre_jours: 30\n    seuil_repetition: '3'\n",
        encoding="utf-8")
    assert aide.m6_outils._configuration_alertes() == {"fenetre_jours": 30, "seuil_repetition": 3}
    manifeste.write_text(
        "configuration:\n  alertes_approvisionnement:\n    fenetre_jours: 1\n    seuil_repetition: 2\n",
        encoding="utf-8")
    assert aide.m6_outils._configuration_alertes() == {"fenetre_jours": 1, "seuil_repetition": 2}
    for bloc in ("fenetre_jours: 0", "seuil_repetition: true", "fenetre_jours: beaucoup", "seuil_repetition: 1"):
        manifeste.write_text(f"configuration:\n  alertes_approvisionnement:\n    {bloc}\n", encoding="utf-8")
        lues = aide.m6_outils._configuration_alertes()
        assert None in lues.values(), bloc
    assert aide.m6_outils._entier_declare("30", 1) == 30
    assert aide.m6_outils._entier_declare("x", 1) is None
    assert aide.m6_outils._entier_declare(True, 1) is None
    assert aide.m6_outils._entier_declare(1, 2) is None
    assert aide.m6_outils._entier_declare(2, 2) == 2


# --------------------------------------------------------------------------------------------- outil durable
def test_l_outil_est_n3_agent_seulement(m6):
    outil = m6["m6_ajuster_stock"]
    assert (outil.autonomie, outil.niveau_effectif) == (Autonomie.T1, Niveau.N3)
    assert not outil.roles_appareil and not outil.frontiere_humaine


def test_ajuster_change_le_stock_et_garde_acteur_motif_avant_apres(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("5"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    reponse = _outil("m6_ajuster_stock", {"ajustement": _demande()})
    assert reponse["accepte"] is True and reponse["statut"] == "enregistre"
    audit = reponse["ajustement"]
    assert (audit["quantite_avant"], audit["quantite_apres"], audit["delta"]) == ("10", "8", "-2")
    assert audit["motif"] == "erreur_saisie" and audit["acteur"] == "agent"
    assert audit["preuve"] == PREUVE and audit["niveau_approbation"] == "N3"
    assert _stock()["stock_theorique"] == "8"
    mouvements = _maillons()
    assert [m["type_mouvement"] for m in mouvements] == ["RECEPTION", "AJUSTEMENT"]
    assert mouvements[-1]["ajustement"]["quantite_avant"] == "10"
    with stockage.transaction():
        assert ajustements.verifier_chaine(mouvements) == (True, "")


def test_le_rejeu_est_idempotent_et_un_meme_id_avec_un_autre_geste_est_refuse(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("5"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    premier = _outil("m6_ajuster_stock", {"ajustement": _demande()})
    taille = len(_maillons())
    rejeu = _outil("m6_ajuster_stock", {"ajustement": _demande()})
    assert rejeu["accepte"] is True and rejeu["statut"] == "deja_enregistre"
    assert rejeu["ajustement"] == premier["ajustement"]
    assert len(_maillons()) == taille
    conflit = _outil("m6_ajuster_stock", {"ajustement": _demande(quantite_apres=7)})
    assert conflit["accepte"] is False and conflit["verdict"]["code"] == "REJ-AJUSTEMENT-ID-DEJA-UTILISE"
    assert len(_maillons()) == taille


def test_un_motif_inconnu_refuse_sans_ecriture(base, m6):
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    taille = len(_maillons())
    reponse = _outil("m6_ajuster_stock", {"ajustement": _demande(motif="vol")})
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-AJUSTEMENT-MOTIF-INVALIDE"
    assert len(_maillons()) == taille


def test_au_dela_du_seuil_sans_approbation_admin_refuse_sans_ecriture(base, m6, monkeypatch):
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("1"))
    taille = len(_maillons())
    reponse = _outil("m6_ajuster_stock", {"ajustement": _demande(quantite_apres=5)})
    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-AJUSTEMENT-APPROBATION-ADMIN-REQUISE"
    assert len(_maillons()) == taille


def test_au_dela_du_seuil_une_approbation_admin_passe(base, m6, monkeypatch):
    from opsys import contexte

    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("1"))
    monkeypatch.setattr(
        aide.m6_outils.approbations, "approbateur_en_cours",
        lambda cnx, outil, departement, roles=None: contexte.IdentiteAppelante("admin-fictif", "admin"),
    )
    reponse = _outil("m6_ajuster_stock", {"ajustement": _demande(quantite_apres=5)})
    assert reponse["accepte"] is True
    assert reponse["ajustement"]["niveau_approbation"] == "N4"
    assert _stock()["stock_theorique"] == "5"


def test_hors_transaction_refuse_sans_rien_lire(m6):
    reponse = m6["m6_ajuster_stock"].fonction(_demande())
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-M6-TRANSACTION-REQUISE"


def test_les_empreintes_des_maillons_anterieurs_ne_bougent_pas(base, m6):
    """Un maillon à l'ANCIENNE forme (huit clés, sans extension) reste valide tel quel : la chaîne d'avant
    l'ajustement se rejoue à l'identique, et l'ajout d'un AJUSTEMENT ne réécrit aucun maillon."""
    from m6_material_control import encodage, registre

    ancien = registre.Registre()
    from opsys.stockage import maillons as maillons_durables
    ancien._maillons = maillons_durables(aide._DEPARTEMENT, "principal")
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    avant = [(m["index"], m["hash_maillon"]) for m in ancien.lire()]
    assert ajustements.verifier_chaine(ancien.lire()) == (True, "")
    _outil("m6_ajuster_stock", {"ajustement": _demande()})
    apres = [(m["index"], m["hash_maillon"]) for m in ancien.lire()]
    assert apres[: len(avant)] == avant
    # Un maillon historique construit SANS les champs d'extension garde exactement son empreinte.
    mouvement = {
        "type_mouvement": "RECEPTION", "chantier_id": "CH-FICT", "materiau_id": GOUTTIERE,
        "quantite": 1.0, "cout_unitaire": 2.5,
    }
    neuf = registre.Registre()
    maillon, erreur = neuf.ajouter(mouvement)
    assert erreur is None
    attendu = encodage.empreinte(0, "RECEPTION", "CH-FICT", GOUTTIERE, 1.0, 2.5, "")
    assert maillon["hash_maillon"] == attendu and "ajustement" not in maillon


def test_un_no_op_est_accepte_et_ne_cree_aucun_maillon(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("5"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    taille = len(_maillons())
    reponse = _outil("m6_ajuster_stock", {"ajustement": _demande(quantite_apres=10)})
    assert reponse["accepte"] is True and reponse["statut"] == "aucun_ecart"
    assert len(_maillons()) == taille


def test_un_lieu_sans_stock_part_de_zero_et_non_d_un(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("5"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    reponse = _outil("m6_ajuster_stock", {"ajustement": {
        **_demande(quantite_apres=2), "emplacement": {"type": "camion", "reference": "CAM-FICT-1"},
    }})
    assert reponse["ajustement"]["quantite_avant"] == "0" and reponse["ajustement"]["delta"] == "2"


def test_une_identite_refusee_n_est_jamais_acceptee(base, m6, monkeypatch):
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    monkeypatch.setattr(aide.m6_outils, "_acteur_admin_ou_agent",
                        lambda: (None, {"code": "REJ-IDENTITE-APPAREIL-INVALIDE"}))
    reponse = _outil("m6_ajuster_stock", {"ajustement": _demande()})
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


def test_un_qualifier_en_erreur_n_est_jamais_accepte(base, m6, monkeypatch):
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    monkeypatch.setattr(aide.m6_outils.ajustements, "qualifier", lambda *a: (None, {"code": "REJ-X"}))
    reponse = _outil("m6_ajuster_stock", {"ajustement": _demande()})
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-X"


def test_un_registre_qui_refuse_n_est_jamais_accepte(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("5"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")

    class RegistreQuiRefuse:
        def lire(self):
            return _maillons()

        def ajouter(self, mouvement):
            return None, "REJ-MOUVEMENT-TYPE-INVALIDE"

    monkeypatch.setattr(aide.m6_outils, "_registre_de_l_appel", lambda historique: RegistreQuiRefuse())
    reponse = _outil("m6_ajuster_stock", {"ajustement": _demande()})
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-MOUVEMENT-TYPE-INVALIDE"


def test_un_transfert_qui_refuse_annule_l_ajustement_annonce(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("100"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    monkeypatch.setattr(aide.m6_outils.emplacements, "construire_transfert",
                        lambda *a, **k: (None, {"code": "REJ-TRANSFERT-STOCK-INSUFFISANT"}))
    reponse = _outil("m6_ajuster_stock", {"ajustement": {
        **_demande(quantite_apres=8), "emplacement": {"type": "camion", "reference": "CAM-FICT-1"},
    }})
    assert reponse["accepte"] is False


def test_un_ajustement_par_emplacement_corrige_le_lieu_et_le_total(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("5"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    _outil("m6_transferer_stock", {
        "transfert_id": "T-DEPOT-FICT-1", "materiau_id": GOUTTIERE, "quantite": 10.0,
        "de": {"type": "inconnu"}, "vers": {"type": "depot"}, "motif": "ranger au dépôt", "horodatage": H_ADJUST,
    })
    reponse = _outil("m6_ajuster_stock", {"ajustement": {
        **_demande(quantite_apres=8), "emplacement": {"type": "depot"},
    }})
    assert reponse["accepte"] is True
    assert reponse["ajustement"]["emplacement"] == {"type": "depot", "reference": None}
    assert (reponse["ajustement"]["quantite_avant"], reponse["ajustement"]["quantite_apres"]) == ("10", "8")
    assert reponse["repartition"]["depot"] == "8" and reponse["repartition"]["inconnu"] == "0"
    assert _stock()["stock_theorique"] == "8"
    assert len(_maillons("emplacements")) == 2


def test_l_ajustement_ne_porte_aucun_texte_libre_de_client(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("5"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-1")
    _outil("m6_ajuster_stock", {"ajustement": _demande()})
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(REGISTRES.c.maillon).where(
            REGISTRES.c.departement == aide._DEPARTEMENT, REGISTRES.c.registre == "principal")).all()
    texte = " ".join(codec.decoder(ligne.maillon).__repr__() for ligne in lignes)
    for interdit in ("client", "adresse", "telephone", "@"):
        assert interdit not in texte.lower()


def test_un_lot_inventaire_multi_articles_et_multi_emplacements_rejouable(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("5"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-LOT-GOUTTIERE")
    aide._recevoir(m6, aide.VIS, 20.0, "PO-LOT-VIS")
    _localiser(GOUTTIERE, 6.0, {"type": "depot"}, "T-LOT-G-D")
    _localiser(GOUTTIERE, 4.0, {"type": "camion", "reference": "CAM-FICT-1"}, "T-LOT-G-C")
    _localiser(aide.VIS, 12.0, {"type": "depot"}, "T-LOT-V-D")
    _localiser(aide.VIS, 8.0, {"type": "camion", "reference": "CAM-FICT-1"}, "T-LOT-V-C")
    lignes = [
        _ligne_inventaire("AJUST-LOT-G-D", GOUTTIERE, 5.0, {"type": "depot"}),
        _ligne_inventaire("AJUST-LOT-G-C", GOUTTIERE, 5.0, {"type": "camion", "reference": "CAM-FICT-1"}),
        _ligne_inventaire("AJUST-LOT-V-D", aide.VIS, 10.0, {"type": "depot"}),
        _ligne_inventaire("AJUST-LOT-V-C", aide.VIS, 10.0, {"type": "camion", "reference": "CAM-FICT-1"}),
    ]

    premier = _lot(lignes)

    assert premier["ok"] is True, premier
    assert premier["resultat"]["accepte"] is True
    assert [ligne["ajustement"]["delta"] for ligne in premier["resultat"]["ajustements"]] == ["-1", "1", "-2", "2"]
    assert _stock(GOUTTIERE)["stock_theorique"] == "10"
    assert _stock(GOUTTIERE)["par_emplacement"] == {
        "depot": "5", "camion:CAM-FICT-1": "5", "inconnu": "0",
    }
    assert _stock(aide.VIS)["stock_theorique"] == "20"
    assert _stock(aide.VIS)["par_emplacement"] == {
        "depot": "10", "camion:CAM-FICT-1": "10", "inconnu": "0",
    }
    principal = _maillons()
    emplacements_avant_rejeu = _maillons("emplacements")
    assert [m["ajustement"]["ajustement_id"] for m in principal if "ajustement" in m] == [
        "AJUST-LOT-G-D", "AJUST-LOT-G-C", "AJUST-LOT-V-D", "AJUST-LOT-V-C",
    ]
    assert ajustements.verifier_chaine(principal) == (True, "")

    rejoue = _lot(lignes)

    assert rejoue["ok"] is True and rejoue["resultat"]["accepte"] is True
    assert all(ligne["statut"] == "deja_enregistre" for ligne in rejoue["resultat"]["ajustements"])
    assert _maillons() == principal
    assert _maillons("emplacements") == emplacements_avant_rejeu

    conflit = _lot([{**lignes[0], "quantite_apres": 4}, *lignes[1:]])
    assert conflit["ok"] is True and conflit["resultat"]["accepte"] is False
    assert conflit["resultat"]["verdict"]["code"] == "REJ-AJUSTEMENT-ID-DEJA-UTILISE"
    assert _maillons() == principal
    assert _maillons("emplacements") == emplacements_avant_rejeu

    # Une autre opération légitime change ensuite l'état du même emplacement. Le rejeu ancien
    # doit rester un no-op et ne pas ramener le comptage physique précédent.
    _outil("m6_ajuster_stock", {"ajustement": _demande(
        ajustement_id="AJUST-CONCURRENT-FICTIF", motif="correction", quantite_apres=4,
        emplacement={"type": "depot"},
    )})
    principal_apres_concurrent = _maillons()
    emplacements_apres_concurrent = _maillons("emplacements")
    assert _stock(GOUTTIERE)["par_emplacement"]["depot"] == "4"

    rejoue_apres_concurrent = _lot(lignes)

    assert rejoue_apres_concurrent["ok"] is True
    assert all(ligne["statut"] == "deja_enregistre"
               for ligne in rejoue_apres_concurrent["resultat"]["ajustements"])
    assert _maillons() == principal_apres_concurrent
    assert _maillons("emplacements") == emplacements_apres_concurrent
    assert _stock(GOUTTIERE)["par_emplacement"]["depot"] == "4"


def test_un_lot_ne_publie_que_l_etat_final_des_reservations(base, m6, monkeypatch):
    """Deux comptages locaux inverses sont atomiques : M4 ne reçoit aucun état intermédiaire du lot."""
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("5"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-LOT-RESERVATION-FICTIF")
    _localiser(GOUTTIERE, 5.0, {"type": "depot"}, "T-LOT-RESERVATION-DEPOT-FICTIF")
    _localiser(
        GOUTTIERE, 5.0, {"type": "camion", "reference": "CAM-LOT-FICTIF"},
        "T-LOT-RESERVATION-CAMION-FICTIF",
    )
    aide._accepter(aide._devis("DEVIS-LOT-RESERVATION-FICTIF", "CH-LOT-RESERVATION-FICTIF", "10", None))
    evenements_initiaux = aide._publies("DEVIS-LOT-RESERVATION-FICTIF")
    assert len(evenements_initiaux) == 1 and evenements_initiaux[0]["statut"] == "pret"

    # La première ligne ferait tomber le stock total et la réservation à 7; la seconde le
    # rétablit à 10. Aucun de ces états intermédiaires n'est visible hors de la transaction.
    lot = _lot([
        _ligne_inventaire("AJUST-LOT-RESERVATION-DEPOT", GOUTTIERE, 2.0, {"type": "depot"}),
        _ligne_inventaire(
            "AJUST-LOT-RESERVATION-CAMION", GOUTTIERE, 8.0,
            {"type": "camion", "reference": "CAM-LOT-FICTIF"},
        ),
    ])

    assert lot["ok"] is True and lot["resultat"]["accepte"] is True, lot
    assert _stock()["en_main"] == "10" and _stock()["reserve"] == "10"
    assert aide._publies("DEVIS-LOT-RESERVATION-FICTIF") == evenements_initiaux
    assert len(_maillons("reservations")) == 1

    # Une baisse qui reste après le lot doit, elle, produire exactement un événement final.
    lot_baisse = _lot([
        _ligne_inventaire("AJUST-LOT-RESERVATION-DEPOT-2", GOUTTIERE, 1.0, {"type": "depot"}),
        _ligne_inventaire(
            "AJUST-LOT-RESERVATION-CAMION-2", GOUTTIERE, 7.0,
            {"type": "camion", "reference": "CAM-LOT-FICTIF"},
        ),
        {
            **_ligne_inventaire("AJUST-LOT-RESERVATION-VIS-SANS-ECART", aide.VIS, 0.0, None),
            "horodatage": "2026-10-08T11:00:00-04:00",
        },
    ])
    evenements_finaux = aide._publies("DEVIS-LOT-RESERVATION-FICTIF")
    assert lot_baisse["ok"] is True and lot_baisse["resultat"]["accepte"] is True
    assert len(evenements_finaux) == 2
    assert (evenements_finaux[-1]["statut"], evenements_finaux[-1]["revision"]) == ("partiel", 2)
    assert evenements_finaux[-1]["lignes"][0]["quantite_reservee"] == "8"
    assert evenements_finaux[-1]["horodatage"] == H_ADJUST
    assert lot_baisse["resultat"]["evenements_materiel_pret"] == [evenements_finaux[-1]["evenement_id"]]
    assert _stock()["en_main"] == "8" and _stock()["reserve"] == "8"


def test_un_refus_n4_tardif_annule_tout_le_lot(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("1"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-LOT-REFUS-GOUTTIERE")
    aide._recevoir(m6, aide.VIS, 20.0, "PO-LOT-REFUS-VIS")
    _localiser(GOUTTIERE, 10.0, {"type": "depot"}, "T-LOT-REFUS-G")
    _localiser(aide.VIS, 20.0, {"type": "depot"}, "T-LOT-REFUS-V")
    principal_avant = _maillons()
    emplacements_avant = _maillons("emplacements")

    reponse = _lot([
        _ligne_inventaire("AJUST-LOT-AVANT-REFUS", GOUTTIERE, 9.5, {"type": "depot"}),
        _ligne_inventaire("AJUST-LOT-N4-REFUSE", aide.VIS, 17.0, {"type": "depot"}),
    ])

    assert reponse["ok"] is False, reponse
    assert _maillons() == principal_avant
    assert _maillons("emplacements") == emplacements_avant
    assert _stock(GOUTTIERE)["stock_theorique"] == "10"
    assert _stock(aide.VIS)["stock_theorique"] == "20"


def test_une_approbation_admin_n4_est_liee_au_nom_du_lot_complet(base, m6, monkeypatch):
    from opsys import contexte

    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("1"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-LOT-APPROBATION")
    appels = []

    def approbateur(cnx, outil, departement, roles=None):
        appels.append((outil, departement, roles))
        return contexte.IdentiteAppelante("admin-fictif", "admin")

    monkeypatch.setattr(aide.m6_outils.approbations, "approbateur_en_cours", approbateur)
    reponse = _lot([_ligne_inventaire("AJUST-LOT-N4", GOUTTIERE, 7.0, {"type": "depot"})])

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True
    assert appels == [("m6_clore_inventaire_physique", aide._DEPARTEMENT, None)]
    assert reponse["resultat"]["ajustements"][0]["ajustement"]["niveau_approbation"] == "N4"


def test_le_lot_garde_le_niveau_et_la_garde_d_appareil_de_l_ajustement_individuel(base, m6, monkeypatch):
    from m6_material_control import acces

    individuel, lot = m6["m6_ajuster_stock"], m6["m6_clore_inventaire_physique"]
    assert (lot.autonomie, lot.niveau_effectif, lot.roles_appareil, lot.frontiere_humaine) == (
        individuel.autonomie, individuel.niveau_effectif, individuel.roles_appareil, individuel.frontiere_humaine,
    )
    monkeypatch.setattr(
        aide.m6_outils, "_declarant_appareil", lambda: (acces.Acteur("employe-fictif", "employee"), None)
    )
    avant = (_maillons(), _maillons("emplacements"))

    reponse = _lot([_ligne_inventaire("AJUST-LOT-EMPLOYE", GOUTTIERE, 0, {"type": "depot"})])

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert (_maillons(), _maillons("emplacements")) == avant


def test_un_lot_refuse_un_article_emplacement_duplique_avant_toute_ecriture(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("5"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-LOT-CIBLE-DUPLIQUE")
    avant = (_maillons(), _maillons("emplacements"))

    reponse = _lot([
        _ligne_inventaire("AJUST-LOT-DUPLIQUE-A", GOUTTIERE, 9.0, {"type": "depot"}),
        _ligne_inventaire("AJUST-LOT-DUPLIQUE-B", GOUTTIERE, 8.0, {"type": "depot"}),
    ])

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-AJUSTEMENT-CIBLE-DUPLIQUE-LOT"
    assert (_maillons(), _maillons("emplacements")) == avant


def test_un_lot_ne_melange_pas_stock_total_et_comptage_local_du_meme_article(base, m6):
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-LOT-MODES")
    avant = (_maillons(), _maillons("emplacements"))

    reponse = _lot([
        _ligne_inventaire("AJUST-LOT-GLOBAL", GOUTTIERE, 9.0, None),
        _ligne_inventaire("AJUST-LOT-LOCAL", GOUTTIERE, 8.0, {"type": "depot"}),
    ])

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-AJUSTEMENT-MODE-CIBLE-DUPLIQUE-LOT"
    assert (_maillons(), _maillons("emplacements")) == avant


def test_un_lot_hors_borne_est_annule_avant_confirmation_tronquee(base, m6, monkeypatch):
    from opsys import contexte

    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("5"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-LOT-SORTIE-BORNE")
    principal_avant = _maillons()
    emplacements_avant = _maillons("emplacements")
    monkeypatch.setattr(contexte, "limite_sortie", lambda: 200)

    reponse = _lot([_ligne_inventaire("AJUST-LOT-SORTIE-BORNE", GOUTTIERE, 8.0, None)])

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert reponse["details"].startswith("REJ-AJUSTEMENT-LOT-SORTIE-TROP-VOLUMINEUSE:")
    assert _maillons() == principal_avant
    assert _maillons("emplacements") == emplacements_avant
    assert _stock(GOUTTIERE)["stock_theorique"] == "10"


def test_lot_de_cinquante_lignes_ne_commit_pas_si_l_accuse_complet_depasse_la_borne(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("5"))
    materiaux = [f"MAT-FICT-{index:02}" for index in range(50)]
    for index, materiau in enumerate(materiaux):
        aide._recevoir(m6, materiau, 1.0, f"PO-LOT-BORNE-{index:02}")
    principal_avant = _maillons()
    emplacements_avant = _maillons("emplacements")
    lignes = [
        _ligne_inventaire(f"AJUST-LOT-BORNE-{index:02}", materiau, 0, None)
        for index, materiau in enumerate(materiaux)
    ]

    reponse = _lot(lignes)

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert reponse["details"].startswith("REJ-AJUSTEMENT-LOT-SORTIE-TROP-VOLUMINEUSE:")
    assert _maillons() == principal_avant
    assert _maillons("emplacements") == emplacements_avant
    assert all(_stock(materiau)["stock_theorique"] == "1" for materiau in materiaux)


def test_borne_sortie_est_scoped_reentrant_et_isolee_entre_threads():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from opsys import contexte

    assert contexte.limite_sortie() is None
    with contexte.sortie_bornee(5400):
        assert contexte.limite_sortie() == 5400
        with contexte.sortie_bornee(1200):
            assert contexte.limite_sortie() == 1200
        assert contexte.limite_sortie() == 5400
        barriere = Barrier(2)

        def limite_dans_thread(limite):
            with contexte.sortie_bornee(limite):
                barriere.wait(timeout=2)
                return contexte.limite_sortie()

        with ThreadPoolExecutor(max_workers=2) as pool:
            resultats = list(pool.map(limite_dans_thread, (100, 200)))
        assert resultats == [100, 200]
    assert contexte.limite_sortie() is None

    import pytest
    with pytest.raises(RuntimeError, match="fictif"), contexte.sortie_bornee(300):
        raise RuntimeError("fictif")
    assert contexte.limite_sortie() is None
