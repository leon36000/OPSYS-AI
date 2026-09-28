"""Facturation client (M5.2) : facture brouillon, verrous d'envoi/paiement, âge des créances."""

import dataclasses
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m5_financecore import facturation, registre, taux_fiscaux  # noqa: E402

HORODATAGE = "2026-08-03T12:00:00+00:00"
_CHEMIN_TAUX_REEL = Path(__file__).resolve().parents[1] / "contracts" / "taux_fiscaux.v1.yaml"


def _dictionnaire_taux_reel():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX_REEL)
    assert erreurs == []
    return dictionnaire


def _lignes(**surcharges_premiere_ligne):
    """Deux lignes fictives : 40 pi de gouttière à 8.50$ + un forfait main d'oeuvre à 260.00$.
    Total avant taxes attendu : 600.00$ (340.00 + 260.00)."""
    premiere = {
        "description": "Gouttières 5po aluminium",
        "quantite": "40",
        "unite": "pi",
        "prix_unitaire": "8.50",
        "reference_ligne_devis": "L1",
    }
    premiere.update(surcharges_premiere_ligne)
    return [
        premiere,
        {
            "description": "Main d'oeuvre installation",
            "quantite": "1",
            "unite": "forfait",
            "prix_unitaire": "260.00",
            "reference_ligne_devis": "L2",
        },
    ]


def _creer(
    facture_id="FACT-001",
    chantier_id="CHANTIER-001",
    devis_id="DEVIS-001",
    client_id="CLIENT-001",
    lignes=None,
    horodatage=HORODATAGE,
    registre_cible=None,
    **kwargs,
):
    if registre_cible is None:
        registre_cible = registre.Registre()
    maillon, verdict = facturation.creer_facture_brouillon(
        facture_id=facture_id,
        chantier_id=chantier_id,
        devis_id=devis_id,
        client_id=client_id,
        lignes=lignes if lignes is not None else _lignes(),
        horodatage=horodatage,
        dictionnaire_taux=_dictionnaire_taux_reel(),
        registre_cible=registre_cible,
        **kwargs,
    )
    return maillon, verdict, registre_cible


# --- LigneFacture / FactureBrouillonV1 : contrat gelé, immuable -------------------------------


def test_ligne_facture_est_un_dataclass_immuable():
    ligne = facturation.LigneFacture(
        description="Test",
        quantite=Decimal("2"),
        unite="pi",
        prix_unitaire=Decimal("10.00"),
        reference_ligne_devis="L1",
        montant=Decimal("20.00"),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        ligne.montant = Decimal("999.00")


def test_facture_brouillon_v1_est_un_dataclass_immuable():
    maillon, verdict, _ = _creer()
    assert verdict is None
    facture = facturation.FactureBrouillonV1(
        facture_id=maillon["facture_id"],
        chantier_id=maillon["chantier_id"],
        devis_id=maillon["devis_id"],
        client_id=maillon["client_id"],
        lignes=(),
        montant_avant_taxes=maillon["montant_avant_taxes"],
        taxes=(),
        total_taxes=maillon["total_taxes"],
        montant_apres_taxes=maillon["montant_apres_taxes"],
        statut=maillon["statut"],
        horodatage=maillon["horodatage"],
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        facture.statut = "PAYEE"


# --- creer_facture_brouillon : recalcule tout, ne fait jamais confiance -----------------------


def test_creer_facture_brouillon_nominal_recalcule_les_totaux_et_les_taxes_sur_le_fichier_reel():
    maillon, verdict, registre_cible = _creer()

    assert verdict is None
    assert maillon["type_entree"] == "facture_creee"
    assert maillon["statut"] == "BROUILLON"
    assert maillon["facture_id"] == "FACT-001"
    assert maillon["chantier_id"] == "CHANTIER-001"
    assert maillon["devis_id"] == "DEVIS-001"
    assert maillon["client_id"] == "CLIENT-001"
    assert maillon["montant_avant_taxes"] == Decimal("600.00")
    assert type(maillon["montant_avant_taxes"]) is Decimal
    assert [t["id"] for t in maillon["taxes"]] == ["tps_federale", "tvq_quebec"]
    assert maillon["taxes"][0]["montant"] == Decimal("30.00")
    assert maillon["taxes"][1]["montant"] == Decimal("59.85")
    assert maillon["total_taxes"] == Decimal("89.85")
    assert maillon["montant_apres_taxes"] == Decimal("689.85")
    assert type(maillon["montant_apres_taxes"]) is Decimal
    assert registre_cible.valider_chaine() == (True, "")
    # deux lignes conservées, montant par ligne recalculé (jamais fourni)
    assert len(maillon["lignes"]) == 2
    assert maillon["lignes"][0]["montant"] == Decimal("340.00")
    assert maillon["lignes"][1]["montant"] == Decimal("260.00")


def test_creer_facture_brouillon_arrondit_un_demi_cent_de_ligne_vers_le_haut():
    """3 x 0.375 $ = 1.125 $ pile : un demi-cent exact. ROUND_HALF_UP (choisi ici) arrondit à
    1.13 $ ; le mode par défaut du module decimal (ROUND_HALF_EVEN) arrondirait à 1.12 $. Même
    mode que M3 (`devis_durable.creer_devis`, `outils.arrondir_au_cent`) : une ligne de facture
    doit arrondir comme la ligne de devis dont elle provient, sinon la facture envoyée peut
    différer du devis accepté d'un cent (PLAN T1.2-d)."""
    maillon, verdict, _ = _creer(lignes=_lignes(quantite="3", prix_unitaire="0.375"))

    assert verdict is None
    assert maillon["lignes"][0]["montant"] == Decimal("1.13")
    # confirme le contraste : sans rounding= explicite, le module decimal arrondirait à 1.12
    assert Decimal("3") * Decimal("0.375") == Decimal("1.125")
    assert Decimal("1.125").quantize(Decimal("0.01")) == Decimal("1.12")


def test_creer_facture_brouillon_accepte_un_montant_fourni_qui_correspond_exactement():
    maillon, verdict, _ = _creer(montant_avant_taxes_fourni="600.00")

    assert verdict is None
    assert maillon["montant_avant_taxes"] == Decimal("600.00")


def test_creer_facture_brouillon_rejette_un_montant_fourni_incoherent():
    maillon, verdict, registre_cible = _creer(montant_avant_taxes_fourni="999.99")

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-MONTANT-INCOHERENT"
    assert registre_cible.lire() == []


def test_creer_facture_brouillon_rejette_un_montant_fourni_non_texte_en_defense_en_profondeur():
    """Le schéma JSON de l'outil bloque déjà un float au premier niveau ; ce test prouve que la
    fonction métier elle-même refuse aussi, indépendamment du schéma (appel direct hors MCP)."""
    maillon, verdict, _ = _creer(montant_avant_taxes_fourni=600.00)

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-MONTANT-INCOHERENT"


@pytest.mark.parametrize("valeur", [None, "", "   "])
def test_creer_facture_brouillon_rejette_devis_id_vide(valeur):
    maillon, verdict, registre_cible = _creer(devis_id=valeur)

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-DEVIS-ID-VIDE"
    assert registre_cible.lire() == []


@pytest.mark.parametrize("valeur", [None, "", "   "])
def test_creer_facture_brouillon_rejette_client_id_vide(valeur):
    maillon, verdict, registre_cible = _creer(client_id=valeur)

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-CLIENT-ID-VIDE"
    assert registre_cible.lire() == []


@pytest.mark.parametrize("valeur", [None, "", "   "])
def test_creer_facture_brouillon_rejette_facture_id_vide(valeur):
    maillon, verdict, registre_cible = _creer(facture_id=valeur)

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-FACTURE-ID-VIDE"
    assert registre_cible.lire() == []


@pytest.mark.parametrize("valeur", [None, "", "   "])
def test_creer_facture_brouillon_rejette_chantier_id_vide(valeur):
    maillon, verdict, registre_cible = _creer(chantier_id=valeur)

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-CHANTIER-ID-VIDE"
    assert registre_cible.lire() == []


def test_creer_facture_brouillon_rejette_une_liste_de_lignes_vide():
    maillon, verdict, registre_cible = _creer(lignes=[])

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-LIGNES-VIDES"
    assert registre_cible.lire() == []


def test_creer_facture_brouillon_rejette_lignes_absentes():
    """Appel direct (hors du raccourci `_creer`, qui substituerait `None` par la fixture par
    défaut) : `lignes=None` doit être refusé exactement comme une liste vide, jamais accepté."""
    registre_cible = registre.Registre()

    maillon, verdict = facturation.creer_facture_brouillon(
        facture_id="FACT-SANS-LIGNES",
        chantier_id="CHANTIER-001",
        devis_id="DEVIS-SANS-LIGNES",
        client_id="CLIENT-001",
        lignes=None,
        horodatage=HORODATAGE,
        dictionnaire_taux=_dictionnaire_taux_reel(),
        registre_cible=registre_cible,
    )

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-LIGNES-VIDES"
    assert registre_cible.lire() == []


def test_creer_facture_brouillon_rejette_une_quantite_non_texte():
    maillon, verdict, registre_cible = _creer(lignes=_lignes(quantite=40.0))

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-LIGNE-INVALIDE"
    assert "texte décimal" in verdict["detail"]
    assert registre_cible.lire() == []


def test_creer_facture_brouillon_rejette_un_prix_unitaire_non_texte():
    maillon, verdict, registre_cible = _creer(lignes=_lignes(prix_unitaire=8.5))

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-LIGNE-INVALIDE"
    assert registre_cible.lire() == []


@pytest.mark.parametrize("quantite", ["0", "-5", "pas-un-nombre"])
def test_creer_facture_brouillon_rejette_une_quantite_invalide(quantite):
    maillon, verdict, _ = _creer(lignes=_lignes(quantite=quantite))

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-LIGNE-INVALIDE"


def test_creer_facture_brouillon_rejette_une_ligne_avec_champ_manquant():
    ligne_incomplete = {
        "description": "Sans référence de devis",
        "quantite": "1",
        "unite": "forfait",
        "prix_unitaire": "10.00",
    }
    maillon, verdict, _ = _creer(lignes=[ligne_incomplete])

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-LIGNE-INVALIDE"


def test_creer_facture_brouillon_rejette_une_ligne_avec_champ_en_trop():
    ligne_avec_extra = {**_lignes()[0], "cout_materiel_interne": "1.00"}
    maillon, verdict, _ = _creer(lignes=[ligne_avec_extra])

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-LIGNE-INVALIDE"


def test_creer_facture_brouillon_rejette_une_description_vide():
    maillon, verdict, _ = _creer(lignes=_lignes(description="   "))

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-LIGNE-INVALIDE"


def test_creer_facture_brouillon_bloque_si_un_taux_fiscal_demande_est_absent():
    maillon, verdict = facturation.creer_facture_brouillon(
        facture_id="FACT-002",
        chantier_id="CHANTIER-002",
        devis_id="DEVIS-002",
        client_id="CLIENT-002",
        lignes=_lignes(),
        horodatage=HORODATAGE,
        dictionnaire_taux={},  # aucun taux déclaré
        registre_cible=registre.Registre(),
    )

    assert maillon is None
    assert verdict["code"] == "REJ-TAUX-INCONNU"


def test_creer_facture_brouillon_est_reproductible():
    """Même entrée, même empreinte (`ligne_id`) : aucun aléa, aucune horloge interne."""
    premier, verdict1, _ = _creer(registre_cible=registre.Registre())
    second, verdict2, _ = _creer(registre_cible=registre.Registre())

    assert verdict1 is None and verdict2 is None
    assert premier["ligne_id"] == second["ligne_id"]


# --- idempotence par devis_id ------------------------------------------------------------------


def test_creer_facture_brouillon_est_idempotente_par_devis_id():
    _, verdict1, registre_cible = _creer(facture_id="FACT-A", devis_id="DEVIS-DUP")
    assert verdict1 is None

    maillon2, verdict2, _ = _creer(facture_id="FACT-B", devis_id="DEVIS-DUP", registre_cible=registre_cible)

    assert maillon2 is None
    assert verdict2["code"] == "REJ-FACTURE-DEVIS-DEJA-FACTURE"
    assert "FACT-A" in verdict2["detail"]
    assert len(registre_cible.lire()) == 1


def test_facture_active_pour_devis_rend_none_si_aucune():
    """PLAN T1.2-d (suite) : fonction publique extraite de `creer_facture_brouillon`, exposée
    pour un appelant qui a seulement besoin de savoir si une facture existe déjà."""
    assert facturation.facture_active_pour_devis(registre.Registre(), "DEVIS-INCONNU") is None


def test_facture_active_pour_devis_retrouve_la_facture_creee():
    maillon, verdict, registre_cible = _creer(facture_id="FACT-A", devis_id="DEVIS-DUP")
    assert verdict is None

    existante = facturation.facture_active_pour_devis(registre_cible, "DEVIS-DUP")

    assert existante is not None
    assert existante["facture_id"] == "FACT-A"
    assert existante["statut"] == "BROUILLON"


def test_creer_facture_brouillon_accepte_un_nouveau_devis_different():
    _, verdict1, registre_cible = _creer(facture_id="FACT-A", devis_id="DEVIS-1")
    maillon2, verdict2, _ = _creer(facture_id="FACT-B", devis_id="DEVIS-2", registre_cible=registre_cible)

    assert verdict1 is None
    assert verdict2 is None
    assert maillon2["facture_id"] == "FACT-B"


def test_creer_facture_brouillon_autorise_un_nouveau_brouillon_apres_annulation():
    """Le mandat ne fournit pas encore de transition vers ANNULEE (hors périmètre T1.1-e) ; ce
    test prouve seulement que la garde d'idempotence lit bien `statut != ANNULEE` — donc
    qu'un futur `annuler_facture` (même patron `transition_facture`) débloquera le devis
    correctement, sans qu'il faille retoucher `creer_facture_brouillon`."""
    _, verdict1, registre_cible = _creer(facture_id="FACT-A", devis_id="DEVIS-ANNULE")
    assert verdict1 is None
    registre_cible.ajouter(
        {
            "type_entree": "transition_facture",
            "facture_id": "FACT-A",
            "statut": "ANNULEE",
            "horodatage": HORODATAGE,
        }
    )

    maillon2, verdict2, _ = _creer(facture_id="FACT-C", devis_id="DEVIS-ANNULE", registre_cible=registre_cible)

    assert verdict2 is None
    assert maillon2["facture_id"] == "FACT-C"


# --- verrou d'envoi : BROUILLON -> ENVOYEE, gardé par le socle (N4, PLAN T1.3-c) ---------------
#
# ADAPTATION (mandat PLAN T1.3-c, point 6) : `envoyer_facture` ne reçoit et ne vérifie plus AUCUN
# maillon d'approbation — la garde sur la FORME d'un maillon F4 (palier, statut, approbateur non
# vide) est retirée, remplacée par la décision réelle du socle (`opsys.approbations.decider`, N4),
# testée à l'échelle du département dans `test_approbations_socle.py`. Les tests qui ne
# vérifiaient QUE cette forme (structure invalide, mauvais palier, non approuvée, approbateur
# vide) sont donc retirés ici : ils n'ont plus de sens pour une fonction qui ne prend plus cet
# argument. Les tests encore pertinents (introuvable, transition illégale) sont conservés,
# adaptés à la nouvelle signature à 3 arguments.


def test_envoyer_facture_nominal_transitionne_et_pose_date_envoi():
    _, verdict_creation, registre_cible = _creer()
    assert verdict_creation is None

    maillon, verdict = facturation.envoyer_facture("FACT-001", "2026-08-10T09:00:00+00:00", registre_cible)

    assert verdict is None
    assert maillon["type_entree"] == "transition_facture"
    assert maillon["statut"] == "ENVOYEE"
    assert maillon["date_envoi"] == "2026-08-10T09:00:00+00:00"
    assert registre_cible.valider_chaine() == (True, "")


def test_envoyer_facture_rejette_une_facture_introuvable():
    maillon, verdict = facturation.envoyer_facture("FACT-INEXISTANTE", HORODATAGE, registre.Registre())

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-INTROUVABLE"


def test_envoyer_facture_rejette_une_facture_deja_envoyee():
    _, _, registre_cible = _creer()
    premier, v1 = facturation.envoyer_facture("FACT-001", HORODATAGE, registre_cible)
    assert v1 is None
    assert premier["statut"] == "ENVOYEE"

    second, v2 = facturation.envoyer_facture("FACT-001", HORODATAGE, registre_cible)

    assert second is None
    assert v2["code"] == "REJ-FACTURE-TRANSITION-ILLEGALE"


# --- factures_par_statut : fonction publique extraite de _etats_courants (PLAN T1.3-c) ---------


def test_factures_par_statut_retrouve_les_brouillon_triees_par_facture_id():
    _, _, registre_cible = _creer(facture_id="FACT-B", devis_id="DEVIS-B")
    _creer(facture_id="FACT-A", devis_id="DEVIS-A", registre_cible=registre_cible)

    brouillon = facturation.factures_par_statut(registre_cible, "BROUILLON")

    assert [f["facture_id"] for f in brouillon] == ["FACT-A", "FACT-B"]


def test_factures_par_statut_exclut_les_autres_statuts():
    _, _, registre_cible = _creer(facture_id="FACT-ENVOYEE", devis_id="DEVIS-ENVOYEE")
    facturation.envoyer_facture("FACT-ENVOYEE", HORODATAGE, registre_cible)
    _creer(facture_id="FACT-BROUILLON", devis_id="DEVIS-BROUILLON", registre_cible=registre_cible)

    assert [f["facture_id"] for f in facturation.factures_par_statut(registre_cible, "BROUILLON")] == [
        "FACT-BROUILLON"
    ]
    assert [f["facture_id"] for f in facturation.factures_par_statut(registre_cible, "ENVOYEE")] == [
        "FACT-ENVOYEE"
    ]


def test_factures_par_statut_rend_un_tuple_vide_si_aucune_correspondance():
    assert facturation.factures_par_statut(registre.Registre(), "PAYEE") == ()


# --- PAYEE : jamais sans approbateur humain non vide, jamais de pont bancaire réel -------------
# (marquer_facture_payee, INCHANGÉE — aucune régression, voir enregistrer_paiement_facture
# plus bas pour la comparaison de montant, PLAN T1.3-c)


def test_marquer_facture_payee_nominal():
    _, _, registre_cible = _creer()
    facturation.envoyer_facture("FACT-001", HORODATAGE, registre_cible)

    maillon, verdict = facturation.marquer_facture_payee(
        "FACT-001", "Nathan", "2026-08-20T10:00:00+00:00", registre_cible
    )

    assert verdict is None
    assert maillon["type_entree"] == "transition_facture"
    assert maillon["statut"] == "PAYEE"
    assert maillon["date_paiement"] == "2026-08-20T10:00:00+00:00"
    assert maillon["approbateur"] == "Nathan"
    assert registre_cible.valider_chaine() == (True, "")


def test_marquer_facture_payee_rejette_une_facture_introuvable():
    maillon, verdict = facturation.marquer_facture_payee("FACT-X", "Nathan", HORODATAGE, registre.Registre())

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-INTROUVABLE"


def test_marquer_facture_payee_rejette_une_facture_encore_brouillon():
    _, _, registre_cible = _creer()

    maillon, verdict = facturation.marquer_facture_payee("FACT-001", "Nathan", HORODATAGE, registre_cible)

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-TRANSITION-ILLEGALE"


def test_marquer_facture_payee_rejette_une_facture_deja_payee():
    _, _, registre_cible = _creer()
    facturation.envoyer_facture("FACT-001", HORODATAGE, registre_cible)
    premier, v1 = facturation.marquer_facture_payee("FACT-001", "Nathan", HORODATAGE, registre_cible)
    assert v1 is None
    assert premier["statut"] == "PAYEE"

    second, v2 = facturation.marquer_facture_payee("FACT-001", "Alice", HORODATAGE, registre_cible)

    assert second is None
    assert v2["code"] == "REJ-FACTURE-TRANSITION-ILLEGALE"


@pytest.mark.parametrize("approbateur", [None, "", "   "])
def test_marquer_facture_payee_exige_un_approbateur_humain_non_vide(approbateur):
    """Même garde que `approbation.approuver` (mandat, tâche 6) : frontière humaine T3."""
    _, _, registre_cible = _creer()
    facturation.envoyer_facture("FACT-001", HORODATAGE, registre_cible)

    maillon, verdict = facturation.marquer_facture_payee("FACT-001", approbateur, HORODATAGE, registre_cible)

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-APPROBATEUR-ABSENT"


def test_marquer_facture_payee_n_ecrit_jamais_dans_le_registre_des_mouvements():
    """LE PIÈGE (mandat + docs/departements/M5-audit.md) : une facture qui devient PAYEE ne doit
    JAMAIS produire d'ENCAISSEMENT. `marquer_facture_payee` ne reçoit même pas de registre des
    mouvements en paramètre — structurellement, aucun chemin de ce module ne peut y écrire. On le
    prouve en gardant un registre des MOUVEMENTS, vide, en vie à côté du cycle complet de la
    facture, et en vérifiant qu'il n'a pas bougé d'un seul maillon."""
    registre_mouvements_temoin = registre.Registre()
    _, _, registre_factures = _creer()

    facturation.envoyer_facture("FACT-001", HORODATAGE, registre_factures)
    maillon_paye, verdict = facturation.marquer_facture_payee(
        "FACT-001", "Nathan", "2026-08-20T10:00:00+00:00", registre_factures
    )

    assert verdict is None
    assert maillon_paye["statut"] == "PAYEE"
    assert registre_mouvements_temoin.lire() == []
    assert registre_mouvements_temoin.taille() == 0
    assert registre_mouvements_temoin.tete() is None
    # Et le registre des factures, lui, ne porte que des entrées de la famille facture_*/transition_facture.
    assert {maillon["type_entree"] for maillon in registre_factures.lire()} <= {
        "facture_creee",
        "transition_facture",
    }
    assert "ENCAISSEMENT" not in str(registre_factures.lire())


# --- enregistrer_paiement_facture : montant comparé PAR LE CODE, jamais fourni sans contrôle ---
# (PLAN T1.3-c point 2 — le socle garde le N5, nathan_owner + attestation ; ce module compare)


def _facture_envoyee_689_85():
    """Facture par défaut (`_lignes()`), montant dû après taxes = 689.85 $ (vérifié par
    `test_creer_facture_brouillon_nominal_recalcule_les_totaux_et_les_taxes_sur_le_fichier_reel`)."""
    _, _, registre_cible = _creer()
    facturation.envoyer_facture("FACT-001", HORODATAGE, registre_cible)
    return registre_cible


def test_enregistrer_paiement_facture_nominal_montant_exact_marque_payee():
    registre_cible = _facture_envoyee_689_85()

    maillon, verdict = facturation.enregistrer_paiement_facture(
        "FACT-001", "689.85", "Nathan", "2026-08-20T10:00:00+00:00", registre_cible
    )

    assert verdict is None
    assert maillon["statut"] == "PAYEE"
    assert maillon["approbateur"] == "Nathan"
    assert maillon["date_paiement"] == "2026-08-20T10:00:00+00:00"
    assert registre_cible.valider_chaine() == (True, "")


def test_enregistrer_paiement_facture_partiel_refuse_sans_marquer_payee():
    registre_cible = _facture_envoyee_689_85()

    maillon, verdict = facturation.enregistrer_paiement_facture(
        "FACT-001", "500.00", "Nathan", HORODATAGE, registre_cible
    )

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-PAIEMENT-PARTIEL"
    assert "500.00" in verdict["detail"] and "689.85" in verdict["detail"]
    # jamais marquée PAYEE sur un paiement partiel : la facture reste ENVOYEE.
    assert facturation._etat_facture(registre_cible, "FACT-001")["statut"] == "ENVOYEE"


def test_enregistrer_paiement_facture_excedent_refuse_sans_marquer_payee():
    registre_cible = _facture_envoyee_689_85()

    maillon, verdict = facturation.enregistrer_paiement_facture(
        "FACT-001", "700.00", "Nathan", HORODATAGE, registre_cible
    )

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-PAIEMENT-ECART"
    assert facturation._etat_facture(registre_cible, "FACT-001")["statut"] == "ENVOYEE"


@pytest.mark.parametrize("montant_paye", ["pas-un-nombre", "0", "-10.00", 689.85])
def test_enregistrer_paiement_facture_rejette_un_montant_invalide(montant_paye):
    registre_cible = _facture_envoyee_689_85()

    maillon, verdict = facturation.enregistrer_paiement_facture(
        "FACT-001", montant_paye, "Nathan", HORODATAGE, registre_cible
    )

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-PAIEMENT-MONTANT-INVALIDE"
    assert facturation._etat_facture(registre_cible, "FACT-001")["statut"] == "ENVOYEE"


def test_enregistrer_paiement_facture_rejette_une_facture_introuvable():
    maillon, verdict = facturation.enregistrer_paiement_facture(
        "FACT-X", "689.85", "Nathan", HORODATAGE, registre.Registre()
    )

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-INTROUVABLE"


def test_enregistrer_paiement_facture_rejette_une_facture_encore_brouillon():
    """Le contrôle de montant ne devance jamais la garde de transition existante
    (ENVOYEE requis) : une facture encore BROUILLON est refusée avant toute comparaison."""
    _, _, registre_cible = _creer()

    maillon, verdict = facturation.enregistrer_paiement_facture(
        "FACT-001", "689.85", "Nathan", HORODATAGE, registre_cible
    )

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-TRANSITION-ILLEGALE"


@pytest.mark.parametrize("approbateur", [None, "", "   "])
def test_enregistrer_paiement_facture_exige_un_approbateur_humain_non_vide(approbateur):
    """Le montant validé, la garde existante de `marquer_facture_payee` s'applique toujours
    (composition, pas réécriture) : approbateur non vide, comportement inchangé."""
    registre_cible = _facture_envoyee_689_85()

    maillon, verdict = facturation.enregistrer_paiement_facture(
        "FACT-001", "689.85", approbateur, HORODATAGE, registre_cible
    )

    assert maillon is None
    assert verdict["code"] == "REJ-FACTURE-APPROBATEUR-ABSENT"


def test_enregistrer_paiement_facture_n_ecrit_jamais_dans_le_registre_des_mouvements():
    registre_mouvements_temoin = registre.Registre()
    registre_cible = _facture_envoyee_689_85()

    maillon, verdict = facturation.enregistrer_paiement_facture(
        "FACT-001", "689.85", "Nathan", HORODATAGE, registre_cible
    )

    assert verdict is None
    assert maillon["statut"] == "PAYEE"
    assert registre_mouvements_temoin.lire() == []


# --- calculer_age_creances -----------------------------------------------------------------------


def _facture_envoyee(registre_cible, facture_id, devis_id, date_envoi):
    _creer(facture_id=facture_id, devis_id=devis_id, horodatage=date_envoi, registre_cible=registre_cible)
    maillon, verdict = facturation.envoyer_facture(facture_id, date_envoi, registre_cible)
    assert verdict is None
    return maillon


@pytest.mark.parametrize(
    "date_envoi,aujourd_hui,tranche_attendue,age_attendu",
    [
        ("2026-08-03T00:00:00+00:00", "2026-08-03", "0-30", 0),
        ("2026-08-03T00:00:00+00:00", "2026-09-02", "0-30", 30),
        ("2026-08-03T00:00:00+00:00", "2026-09-03", "31-60", 31),
        ("2026-08-03T00:00:00+00:00", "2026-10-02", "31-60", 60),
        ("2026-08-03T00:00:00+00:00", "2026-10-03", "61-90", 61),
        ("2026-08-03T00:00:00+00:00", "2026-11-01", "61-90", 90),
        ("2026-08-03T00:00:00+00:00", "2026-11-02", "90+", 91),
        ("2026-08-03T00:00:00+00:00", "2027-08-03", "90+", 365),
    ],
)
def test_calculer_age_creances_classe_dans_la_bonne_tranche(date_envoi, aujourd_hui, tranche_attendue, age_attendu):
    registre_cible = registre.Registre()
    _facture_envoyee(registre_cible, "FACT-AGE", "DEVIS-AGE", date_envoi)

    resultat, verdict = facturation.calculer_age_creances(registre_cible, aujourd_hui)

    assert verdict is None
    for tranche in ("0-30", "31-60", "61-90", "90+"):
        attendu = 1 if tranche == tranche_attendue else 0
        assert len(resultat["tranches"][tranche]) == attendu, resultat["tranches"]
    entree = resultat["tranches"][tranche_attendue][0]
    assert entree["facture_id"] == "FACT-AGE"
    assert entree["age_jours"] == age_attendu
    assert entree["montant_apres_taxes"] == Decimal("689.85")
    assert resultat["total_par_tranche"][tranche_attendue] == Decimal("689.85")


def test_calculer_age_creances_ignore_brouillon_payee_et_annulee():
    registre_cible = registre.Registre()
    _creer(facture_id="FACT-BROUILLON", devis_id="DEVIS-1", registre_cible=registre_cible)
    _facture_envoyee(registre_cible, "FACT-PAYEE", "DEVIS-2", "2026-08-03T00:00:00+00:00")
    facturation.marquer_facture_payee("FACT-PAYEE", "Nathan", "2026-08-10T00:00:00+00:00", registre_cible)
    _creer(facture_id="FACT-ANNULEE", devis_id="DEVIS-3", registre_cible=registre_cible)
    registre_cible.ajouter(
        {
            "type_entree": "transition_facture",
            "facture_id": "FACT-ANNULEE",
            "statut": "ANNULEE",
            "horodatage": HORODATAGE,
        }
    )

    resultat, verdict = facturation.calculer_age_creances(registre_cible, "2026-09-01")

    assert verdict is None
    assert sum(len(v) for v in resultat["tranches"].values()) == 0
    assert resultat["exclues"] == []


def test_calculer_age_creances_exclut_une_facture_envoyee_sans_date_envoi_utilisable():
    """`envoyer_facture` pose toujours `date_envoi` : ce scénario (maillon fabriqué à la main,
    sans passer par le verrou d'envoi) prouve le fail-closed même en cas de donnée corrompue ou
    d'un futur chemin de code qui oublierait de la poser — jamais un classement par défaut."""
    registre_cible = registre.Registre()
    _creer(facture_id="FACT-SANS-DATE", devis_id="DEVIS-1", registre_cible=registre_cible)
    registre_cible.ajouter(
        {
            "type_entree": "transition_facture",
            "facture_id": "FACT-SANS-DATE",
            "statut": "ENVOYEE",
            "horodatage": HORODATAGE,
        }
    )

    resultat, verdict = facturation.calculer_age_creances(registre_cible, "2026-09-01")

    assert verdict is None
    assert sum(len(v) for v in resultat["tranches"].values()) == 0
    assert len(resultat["exclues"]) == 1
    assert resultat["exclues"][0]["facture_id"] == "FACT-SANS-DATE"
    assert resultat["exclues"][0]["verdict"]["code"] == "REJ-CREANCES-DATE-ENVOI-ABSENTE"


def test_calculer_age_creances_exclut_une_date_envoi_non_iso():
    registre_cible = registre.Registre()
    _creer(facture_id="FACT-DATE-INVALIDE", devis_id="DEVIS-1", registre_cible=registre_cible)
    registre_cible.ajouter(
        {
            "type_entree": "transition_facture",
            "facture_id": "FACT-DATE-INVALIDE",
            "statut": "ENVOYEE",
            "date_envoi": "pas-une-date",
            "horodatage": HORODATAGE,
        }
    )

    resultat, verdict = facturation.calculer_age_creances(registre_cible, "2026-09-01")

    assert verdict is None
    assert sum(len(v) for v in resultat["tranches"].values()) == 0
    assert resultat["exclues"][0]["verdict"]["code"] == "REJ-CREANCES-DATE-ENVOI-INVALIDE"


def test_calculer_age_creances_exclut_une_date_envoi_posterieure_a_aujourd_hui():
    registre_cible = registre.Registre()
    _facture_envoyee(registre_cible, "FACT-FUTUR", "DEVIS-1", "2026-09-15T00:00:00+00:00")

    resultat, verdict = facturation.calculer_age_creances(registre_cible, "2026-09-01")

    assert verdict is None
    assert sum(len(v) for v in resultat["tranches"].values()) == 0
    assert resultat["exclues"][0]["verdict"]["code"] == "REJ-CREANCES-DATE-ENVOI-INVALIDE"


@pytest.mark.parametrize("aujourd_hui", [None, "", "pas-une-date", "2026-13-40", 20260901])
def test_calculer_age_creances_rejette_un_aujourd_hui_invalide(aujourd_hui):
    resultat, verdict = facturation.calculer_age_creances(registre.Registre(), aujourd_hui)

    assert resultat is None
    assert verdict["code"] == "REJ-CREANCES-AUJOURDHUI-INVALIDE"


def test_calculer_age_creances_totalise_plusieurs_factures_dans_la_meme_tranche():
    registre_cible = registre.Registre()
    _facture_envoyee(registre_cible, "FACT-1", "DEVIS-1", "2026-08-03T00:00:00+00:00")
    _facture_envoyee(registre_cible, "FACT-2", "DEVIS-2", "2026-08-10T00:00:00+00:00")

    resultat, verdict = facturation.calculer_age_creances(registre_cible, "2026-08-15")

    assert verdict is None
    assert len(resultat["tranches"]["0-30"]) == 2
    assert resultat["total_par_tranche"]["0-30"] == Decimal("689.85") * 2
    assert type(resultat["total_par_tranche"]["0-30"]) is Decimal
