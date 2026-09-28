import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m5_financecore import approbation, contrats, registre

HORODATAGE = "2026-08-03T12:00:00+00:00"


def _preuve(methode="MFA_TOTP", horodatage=HORODATAGE, identifiant_approbateur="EMP-001"):
    """Preuve structurée valide (méthode, horodatage ISO+fuseau, identifiant
    d'approbateur) — jamais une chaîne libre, cf. REJ-PREUVE-STRUCTURE-INVALIDE."""
    return json.dumps(
        {
            "methode": methode,
            "horodatage": horodatage,
            "identifiant_approbateur": identifiant_approbateur,
        }
    )


def _creer_demande(demande_id="DEM-001", palier="F0", registre_cible=None):
    if registre_cible is None:
        registre_cible = registre.Registre()
    maillon, verdict = approbation.creer_demande(
        demande_id,
        palier,
        "Virement fournisseur 5000$",
        registre_cible,
        HORODATAGE,
    )
    assert verdict is None
    return maillon, registre_cible


def test_palier_approbation_contient_exactement_les_huit_valeurs_attendues():
    assert set(contrats.PALIER_APPROBATION) == {
        "F0",
        "F1",
        "F2",
        "F3",
        "F4",
        "F5",
        "F6",
        "F7",
    }
    assert len(contrats.PALIER_APPROBATION) == 8


def test_statut_approbation_contient_exactement_les_trois_valeurs_attendues():
    assert set(contrats.STATUT_APPROBATION) == {
        "EN_ATTENTE",
        "APPROUVE",
        "REFUSE",
    }
    assert len(contrats.STATUT_APPROBATION) == 3


def test_creer_demande_rejette_un_palier_hors_enumeration():
    registre_cible = registre.Registre()

    maillon, verdict = approbation.creer_demande(
        "DEM-001",
        "F8",
        "Virement fournisseur 5000$",
        registre_cible,
        HORODATAGE,
    )

    assert maillon is None
    assert verdict["code"] == "REJ-PALIER-INVALIDE"
    assert registre_cible.lire() == []


def test_creer_demande_ecrit_un_maillon_en_attente_complet():
    maillon, registre_cible = _creer_demande()

    assert maillon["type_entree"] == "demande_creee"
    assert maillon["demande_id"] == "DEM-001"
    assert maillon["palier"] == "F0"
    assert maillon["action"] == "Virement fournisseur 5000$"
    assert maillon["statut"] == "EN_ATTENTE"
    assert maillon["approbateur"] is None
    assert maillon["preuve"] is None
    assert maillon["horodatage"] == HORODATAGE
    assert maillon["precedent_ligne_id"] is None
    assert maillon["ligne_id"] == registre_cible.tete()
    assert registre_cible.lire() == [maillon]


def test_creer_demande_rejette_un_demande_id_deja_cree():
    _, registre_cible = _creer_demande()

    maillon, verdict = approbation.creer_demande(
        "DEM-001",
        "F1",
        "Autre action",
        registre_cible,
        HORODATAGE,
    )

    assert maillon is None
    assert verdict["code"] == "REJ-DEMANDE-DEJA-CREEE"
    assert len(registre_cible.lire()) == 1


def test_deux_demandes_distinctes_sur_le_meme_registre_restent_independantes():
    registre_cible = registre.Registre()
    premier, verdict_premier = approbation.creer_demande(
        "DEM-001",
        "F0",
        "Action 1",
        registre_cible,
        HORODATAGE,
    )
    second, verdict_second = approbation.creer_demande(
        "DEM-002",
        "F7",
        "Action 2",
        registre_cible,
        HORODATAGE,
    )

    assert verdict_premier is None
    assert verdict_second is None
    assert premier["demande_id"] == "DEM-001"
    assert second["demande_id"] == "DEM-002"
    assert approbation.statut_courant(registre_cible, "DEM-001") == "EN_ATTENTE"
    assert approbation.statut_courant(registre_cible, "DEM-002") == "EN_ATTENTE"


def test_statut_courant_retourne_none_pour_une_demande_jamais_creee():
    registre_cible = registre.Registre()

    assert approbation.statut_courant(registre_cible, "DEM-INEXISTANTE") is None


def test_statut_courant_ignore_un_dict_fabrique_hors_de_la_chaine_reelle():
    registre_cible = registre.Registre()
    faux_maillon = {
        "type_entree": "transition_approbation",
        "demande_id": "DEM-FABRIQUEE",
        "statut": "APPROUVE",
        "approbateur": "Alice",
        "horodatage": HORODATAGE,
    }

    assert faux_maillon["statut"] == "APPROUVE"
    assert approbation.statut_courant(registre_cible, "DEM-FABRIQUEE") is None


def test_approuver_rejette_une_demande_inexistante():
    registre_cible = registre.Registre()

    maillon, verdict = approbation.approuver(
        "DEM-INEXISTANTE",
        "Alice",
        registre_cible,
        HORODATAGE,
    )

    assert maillon is None
    assert verdict["code"] == "REJ-DEMANDE-INTROUVABLE"


def test_approuver_rejette_une_demande_deja_approuvee():
    _, registre_cible = _creer_demande()
    maillon, verdict = approbation.approuver(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
    )
    assert verdict is None
    assert maillon["statut"] == "APPROUVE"

    second_maillon, second_verdict = approbation.approuver(
        "DEM-001",
        "Bob",
        registre_cible,
        HORODATAGE,
    )

    assert second_maillon is None
    assert second_verdict["code"] == "REJ-TRANSITION-ILLEGALE"


def test_approuver_rejette_une_demande_deja_refusee():
    _, registre_cible = _creer_demande()
    maillon, verdict = approbation.refuser(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
    )
    assert verdict is None
    assert maillon["statut"] == "REFUSE"

    second_maillon, second_verdict = approbation.approuver(
        "DEM-001",
        "Bob",
        registre_cible,
        HORODATAGE,
    )

    assert second_maillon is None
    assert second_verdict["code"] == "REJ-TRANSITION-ILLEGALE"


def test_approuver_exige_un_approbateur_non_vide_aux_paliers_f0_a_f5():
    for palier in ("F0", "F1", "F2", "F3", "F4", "F5"):
        for approbateur in (None, "", "   "):
            demande_id = f"DEM-{palier}-{repr(approbateur)}"
            _, registre_cible = _creer_demande(demande_id, palier)

            maillon, verdict = approbation.approuver(
                demande_id,
                approbateur,
                registre_cible,
                HORODATAGE,
            )

            assert maillon is None
            assert verdict["code"] == "REJ-APPROBATEUR-ABSENT"
            assert approbation.statut_courant(registre_cible, demande_id) == "EN_ATTENTE"


def test_approuver_f6_exige_une_preuve_non_vide():
    _, registre_cible = _creer_demande(palier="F6")

    maillon, verdict = approbation.approuver(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
        preuve=None,
    )

    assert maillon is None
    assert verdict["code"] == "REJ-PREUVE-ABSENTE"


def test_approuver_f7_rejette_une_preuve_vide():
    _, registre_cible = _creer_demande(palier="F7")

    maillon, verdict = approbation.approuver(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
        preuve="   ",
    )

    assert maillon is None
    assert verdict["code"] == "REJ-PREUVE-ABSENTE"


def test_approuver_aux_paliers_f0_a_f5_ignore_la_preuve_et_met_a_jour_le_statut():
    for palier in ("F0", "F1", "F2", "F3", "F4", "F5"):
        demande_id = f"DEM-{palier}"
        _, registre_cible = _creer_demande(demande_id, palier)

        maillon, verdict = approbation.approuver(
            demande_id,
            "Alice",
            registre_cible,
            HORODATAGE,
            preuve="preuve ignoree",
        )

        assert verdict is None
        assert maillon["type_entree"] == "transition_approbation"
        assert maillon["demande_id"] == demande_id
        assert maillon["statut"] == "APPROUVE"
        assert maillon["approbateur"] == "Alice"
        assert maillon["preuve"] is None
        assert approbation.statut_courant(registre_cible, demande_id) == "APPROUVE"


def test_approuver_f6_enregistre_la_preuve_fournie():
    _, registre_cible = _creer_demande(palier="F6")
    preuve = _preuve(methode="MFA_TOTP", identifiant_approbateur="EMP-COMITE-001")

    maillon, verdict = approbation.approuver(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
        preuve=preuve,
    )

    assert verdict is None
    assert maillon["statut"] == "APPROUVE"
    assert maillon["approbateur"] == "Alice"
    assert maillon["preuve"] == preuve
    assert approbation.statut_courant(registre_cible, "DEM-001") == "APPROUVE"


def test_approuver_f7_enregistre_la_preuve_fournie():
    _, registre_cible = _creer_demande(palier="F7")
    preuve = _preuve(methode="SIGNATURE_CPA", identifiant_approbateur="CPA-DIRECTION-001")

    maillon, verdict = approbation.approuver(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
        preuve=preuve,
    )

    assert verdict is None
    assert maillon["statut"] == "APPROUVE"
    assert maillon["approbateur"] == "Alice"
    assert maillon["preuve"] == preuve
    assert approbation.statut_courant(registre_cible, "DEM-001") == "APPROUVE"


def test_approuver_f6_rejette_une_preuve_en_chaine_libre_non_structuree():
    """Bug NEW-PROD corrigé : « PV-COMITE-F6-001 » (une chaîne libre) prouvait
    n'importe quoi. La transition doit être refusée sans structure vérifiable."""
    _, registre_cible = _creer_demande(palier="F6")

    maillon, verdict = approbation.approuver(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
        preuve="PV-COMITE-F6-001",
    )

    assert maillon is None
    assert verdict["code"] == "REJ-PREUVE-STRUCTURE-INVALIDE"
    assert approbation.statut_courant(registre_cible, "DEM-001") == "EN_ATTENTE"


def test_approuver_f7_rejette_une_preuve_json_a_qui_il_manque_l_horodatage():
    _, registre_cible = _creer_demande(palier="F7")
    preuve = json.dumps({"methode": "SIGNATURE_CPA", "identifiant_approbateur": "CPA-001"})

    maillon, verdict = approbation.approuver(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
        preuve=preuve,
    )

    assert maillon is None
    assert verdict["code"] == "REJ-PREUVE-STRUCTURE-INVALIDE"


def test_approuver_f6_rejette_une_preuve_a_l_horodatage_non_iso_avec_fuseau():
    _, registre_cible = _creer_demande(palier="F6")
    preuve = _preuve(horodatage="2026-08-03T12:00:00")  # sans fuseau

    maillon, verdict = approbation.approuver(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
        preuve=preuve,
    )

    assert maillon is None
    assert verdict["code"] == "REJ-PREUVE-STRUCTURE-INVALIDE"


def test_approuver_f6_rejette_une_preuve_avec_une_cle_en_trop():
    _, registre_cible = _creer_demande(palier="F6")
    preuve = json.dumps(
        {
            "methode": "MFA_TOTP",
            "horodatage": HORODATAGE,
            "identifiant_approbateur": "EMP-001",
            "fournisseur": "un-vendeur-invente",
        }
    )

    maillon, verdict = approbation.approuver(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
        preuve=preuve,
    )

    assert maillon is None
    assert verdict["code"] == "REJ-PREUVE-STRUCTURE-INVALIDE"


def test_approuver_ne_permet_jamais_une_double_approbation_f6():
    _, registre_cible = _creer_demande(palier="F6")
    premier, premier_verdict = approbation.approuver(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
        preuve=_preuve(),
    )
    assert premier_verdict is None
    assert premier["statut"] == "APPROUVE"

    second, second_verdict = approbation.approuver(
        "DEM-001",
        "Bob",
        registre_cible,
        HORODATAGE,
        preuve=_preuve(),
    )

    assert second is None
    assert second_verdict["code"] == "REJ-TRANSITION-ILLEGALE"
    assert approbation.statut_courant(registre_cible, "DEM-001") == "APPROUVE"


def test_refuser_rejette_une_demande_inexistante():
    registre_cible = registre.Registre()

    maillon, verdict = approbation.refuser(
        "DEM-INEXISTANTE",
        "Alice",
        registre_cible,
        HORODATAGE,
    )

    assert maillon is None
    assert verdict["code"] == "REJ-DEMANDE-INTROUVABLE"


def test_refuser_rejette_une_demande_deja_approuvee():
    _, registre_cible = _creer_demande()
    maillon, verdict = approbation.approuver(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
    )
    assert verdict is None
    assert maillon["statut"] == "APPROUVE"

    refus, verdict_refus = approbation.refuser(
        "DEM-001",
        "Bob",
        registre_cible,
        HORODATAGE,
    )

    assert refus is None
    assert verdict_refus["code"] == "REJ-TRANSITION-ILLEGALE"


def test_refuser_rejette_une_demande_deja_refusee():
    _, registre_cible = _creer_demande()
    premier, premier_verdict = approbation.refuser(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
    )
    assert premier_verdict is None
    assert premier["statut"] == "REFUSE"

    second, second_verdict = approbation.refuser(
        "DEM-001",
        "Bob",
        registre_cible,
        HORODATAGE,
    )

    assert second is None
    assert second_verdict["code"] == "REJ-TRANSITION-ILLEGALE"


def test_refuser_exige_un_approbateur_non_vide_a_tous_les_paliers():
    for palier in ("F0", "F6", "F7"):
        for approbateur in (None, "", "   "):
            demande_id = f"DEM-REFUS-{palier}-{repr(approbateur)}"
            _, registre_cible = _creer_demande(demande_id, palier)

            maillon, verdict = approbation.refuser(
                demande_id,
                approbateur,
                registre_cible,
                HORODATAGE,
            )

            assert maillon is None
            assert verdict["code"] == "REJ-APPROBATEUR-ABSENT"
            assert approbation.statut_courant(registre_cible, demande_id) == "EN_ATTENTE"


def test_refuser_f6_ne_exige_pas_de_preuve():
    _, registre_cible = _creer_demande(palier="F6")

    maillon, verdict = approbation.refuser(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
    )

    assert verdict is None
    assert maillon["type_entree"] == "transition_approbation"
    assert maillon["statut"] == "REFUSE"
    assert maillon["approbateur"] == "Alice"
    assert maillon["preuve"] is None
    assert approbation.statut_courant(registre_cible, "DEM-001") == "REFUSE"


def test_refuser_f0_met_la_demande_en_etat_terminal_refuse():
    _, registre_cible = _creer_demande(palier="F0")

    maillon, verdict = approbation.refuser(
        "DEM-001",
        "Alice",
        registre_cible,
        HORODATAGE,
    )

    assert verdict is None
    assert maillon["demande_id"] == "DEM-001"
    assert maillon["statut"] == "REFUSE"
    assert approbation.statut_courant(registre_cible, "DEM-001") == "REFUSE"
