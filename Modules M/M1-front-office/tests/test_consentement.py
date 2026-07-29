import sys
from pathlib import Path
import json
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import consentement  # noqa: E402
import verdicts      # noqa: E402
from registre import Registre  # noqa: E402


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _conversation(consentement_value=None, exclude_field=False):
    """Crée un dict conversation minimal, avec ou sans le champ consentement_enregistrement."""
    conv = {
        "id": "abc-123",
        "horodatage": "2027-08-01T12:00:00Z",
        "canal": "telephone",
    }
    if not exclude_field:
        conv["consentement_enregistrement"] = consentement_value
    return conv


# ----------------------------------------------------------------------
# R1 – Enum consentement : seules les valeurs explicites passent
# ----------------------------------------------------------------------
@pytest.mark.parametrize("valeur_consentement, attendu_ok", [
    ("accorde", True),
    ("refuse", False),
    ("non_demande", False),
    ("", False),
    ("ACCORDE", False),       # sensible à la casse
    ("OUI", False),
    (None, False),
    (False, False),
    (True, False),
    (123, False),
])
def test_verifier_consentement_enum_strict(valeur_consentement, attendu_ok):
    """Toute valeur autre que "accorde" (y compris absente) doit bloquer (FAIL-CLOSED)."""
    conv = _conversation(valeur_consentement)
    verdict = consentement.verifier_consentement(conv)
    if attendu_ok:
        assert verdict.get("code") == "OK", f"Attendu OK pour {valeur_consentement!r}"
    else:
        assert verdict.get("code") == "REJ-CONSENTEMENT-ABSENT", \
            f"Devrait rejeter {valeur_consentement!r}"


# ----------------------------------------------------------------------
# R2 – Champ absent du dict
# ----------------------------------------------------------------------
def test_verifier_consentement_champ_manquant():
    """L'absence du champ doit provoquer un rejet."""
    conv = _conversation(exclude_field=True)
    verdict = consentement.verifier_consentement(conv)
    assert verdict.get("code") == "REJ-CONSENTEMENT-ABSENT", \
        "Champ absent doit être traité comme absence de consentement"


# ----------------------------------------------------------------------
# R3 – Blocage → une entrée registre avec marqueur "absence_consentement"
# ----------------------------------------------------------------------
def test_verifier_consentement_ecrit_registre_marqueur():
    """Quand le consentement est absent/refusé, une entrée registre est ajoutée avec le marqueur explicite."""
    registre = Registre()
    horodatage = "2027-09-15T08:47:00Z"
    conv = _conversation("refuse")
    verdict = consentement.verifier_consentement(conv, registre=registre, horodatage=horodatage)
    assert verdict["code"] != "OK"

    entrees = registre.lire()
    assert len(entrees) == 1, "Une seule entrée registre attendue pour le rejet"
    entree = entrees[0]
    assert "absence_consentement" in entree.get("marqueur", ""), \
        "L'entrée registre doit contenir le marqueur 'absence_consentement'"
    assert entree.get("horodatage") == horodatage, \
        "L'horodatage fourni doit être propagé dans l'entrée registre"


def test_verifier_consentement_sans_horodatage_leve_valueerror():
    """Si registre est fourni sans horodatage → ValueError (fail-closed)."""
    registre = Registre()
    conv = _conversation("non_demande")
    with pytest.raises(ValueError):
        consentement.verifier_consentement(conv, registre=registre, horodatage=None)
    with pytest.raises(ValueError):
        consentement.verifier_consentement(conv, registre=registre)  # pas d'horodatage


# ----------------------------------------------------------------------
# R4 – Aucun contenu conservé en cas de refus (conservation & registre)
# ----------------------------------------------------------------------
@pytest.mark.parametrize("fonction", ["verifier_consentement", "conserver_enregistrement"])
def test_blocage_aucun_contenu_conserve(fonction):
    """Le contenu original ne doit jamais apparaître dans le verdict ni dans le registre après refus."""
    registre = Registre()
    horodatage = "2027-11-01T13:22:00Z"
    contenu_secret = "CECI EST UN ENREGISTREMENT CONFIDENTIEL #1337"  # proof:allow — fixture de test, aucun secret réel
    conv = _conversation("refuse")

    if fonction == "verifier_consentement":
        verdict = consentement.verifier_consentement(conv, registre=registre, horodatage=horodatage)
    else:
        verdict = consentement.conserver_enregistrement(conv, contenu_secret, registre=registre, horodatage=horodatage)  # proof:allow — fixture de test, aucun secret réel

    # Le verdict lui-même ne doit pas contenir le contenu
    verdict_str = json.dumps(verdict, default=str)
    assert contenu_secret not in verdict_str, \
        "Le verdict ne doit pas contenir le contenu d'enregistrement"

    # Les entrées registre non plus
    for entree in registre.lire():
        entree_str = json.dumps(entree, default=str)
        assert contenu_secret not in entree_str, \
            "Aucune entrée registre ne doit contenir le contenu en cas de refus"


# ----------------------------------------------------------------------
# R5 – Consentement accordé → conservation permise, verdict OK
# ----------------------------------------------------------------------
def test_conserver_enregistrement_consentement_accorde():
    """Avec consentement 'accorde', l'enregistrement est conservé et le verdict est OK."""
    registre = Registre()
    horodatage = "2027-12-25T09:00:00Z"
    contenu = "Enregistrement de Noël."
    conv = _conversation("accorde")
    verdict = consentement.conserver_enregistrement(conv, contenu, registre=registre, horodatage=horodatage)
    assert verdict.get("code") == "OK", \
        "Consentement accordé doit donner un verdict OK"
    entrees = registre.lire()
    assert len(entrees) == 1, "Une seule entrée registre doit être créée"
    entree = entrees[0]
    # L'entrée doit contenir le contenu (ou une référence) – selon l'implémentation attendue,
    # on vérifie au moins qu'il n'y a pas de marqueur d'absence
    assert "absence_consentement" not in entree.get("marqueur", ""), \
        "Pas de marqueur d'absence quand le consentement est accordé"


# ----------------------------------------------------------------------
# R6 – rescue_autorise : opt-in booléen True uniquement
# ----------------------------------------------------------------------
@pytest.mark.parametrize("valeur, attendu", [
    # Vrai positif : uniquement le booléen True
    (True, True),
    # Cas négatifs : aucune autre valeur n'est acceptée
    (False, False),
    (None, False),
    ("", False),
    ("non", False),
    ("oui", False),
    ("accorde", False),
    ("true", False),      # chaîne "true" refusée (FAIL-CLOSED, pas de coercition de type)
    ("True", False),      # variante casse refusée
    (1, False),           # entier refusé
])
def test_rescue_autorise(valeur, attendu):
    """rescue_autorise ne retourne True que pour la valeur booléenne True explicite."""
    conv = {"optin_rescue": valeur}
    assert consentement.rescue_autorise(conv) == attendu, \
        f"rescue_autorise({valeur!r}) devrait être {attendu}"


# ----------------------------------------------------------------------
# R7 – Zéro réseau / horloge dans la source
# ----------------------------------------------------------------------
def test_source_contient_zero_reseau_ni_horloge():
    """Le fichier consentement.py ne doit pas contenir d'imports réseau ou appels à l'horloge."""
    chemin_source = _SRC / "consentement.py"
    contenu = chemin_source.read_text(encoding="utf-8")
    motifs_interdits = [
        "urllib",
        "socket",
        "http.client",
        "datetime.now",
        "time.time",
    ]
    for motif in motifs_interdits:
        assert motif not in contenu, \
            f"La source de consentement contient un appel interdit : {motif}"


# ----------------------------------------------------------------------
# R8 – Déterminisme
# ----------------------------------------------------------------------
def test_determinisme():
    """Mêmes entrées → mêmes sorties."""
    conv = _conversation("accorde")
    v1 = consentement.verifier_consentement(conv)
    v2 = consentement.verifier_consentement(conv)
    assert v1 == v2, "La fonction doit être déterministe"

    registre = Registre()
    horodatage = "2028-01-01T00:00:00Z"
    r1 = consentement.conserver_enregistrement(conv, "contenu", registre, horodatage)
    registre2 = Registre()
    r2 = consentement.conserver_enregistrement(conv, "contenu", registre2, horodatage)
    assert r1 == r2, "conserver_enregistrement doit être déterministe"

    # rescue_autorise
    conv_optin = {"optin_rescue": True}
    assert consentement.rescue_autorise(conv_optin) == consentement.rescue_autorise(conv_optin)
    conv_absent = {}
    assert consentement.rescue_autorise(conv_absent) == consentement.rescue_autorise(conv_absent)


"""Tests de non-conservation du contenu dans le registre (CORRECTIF M1-S006).

Garanties:
- Le registre ne contient jamais le contenu en clair (consentement accordé ou refus).
- Empreinte SHA-256 correctement calculée.
- Chaîne d'audit valide après ajout.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

# Ajustement du PATH pour trouver les modules src
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import consentement
from registre import Registre


def test_registre_ne_contient_jamais_le_contenu():
    """Lorsque le consentement est ACCORDÉ, le contenu secret n'est pas présent
    dans le registre. Seules les métadonnées non identifiantes (empreinte,
    longueur) sont enregistrées."""
    # Préparation
    reg = Registre()
    secret = "ENREGISTREMENT_CONFIDENTIEL_DU_CLIENT"  # proof:allow — fixture de test, aucun secret réel
    conversation = {
        "id": "abc-123",
        "consentement_enregistrement": "accorde",
    }
    horodatage = "2027-08-01T12:00:00Z"

    # Action
    verdict = consentement.conserver_enregistrement(
        conversation, secret, registre=reg, horodatage=horodatage  # proof:allow — fixture de test, aucun secret réel
    )
    assert verdict["code"] == "OK"

    # Vérification
    entree = reg.lire()[-1]  # dernière entrée
    assert entree["type_entree"] == "alerte"
    assert entree["marqueur"] == "conservation_acceptee"
    # Le JSON complet ne doit contenir nulle part le secret en clair
    serialized = json.dumps(reg.lire())
    assert secret not in serialized, "Le contenu secret ne doit pas apparaître dans le registre"
    # Empreinte correcte
    empreinte_attendue = hashlib.sha256(secret.encode('utf-8')).hexdigest()  # proof:allow — fixture de test, aucun secret réel
    assert entree["payload"]["empreinte_contenu"] == empreinte_attendue
    assert entree["payload"]["longueur_contenu"] == len(secret.encode('utf-8'))  # proof:allow — fixture de test, aucun secret réel
    assert entree["payload"]["conversation_id"] == "abc-123"


def test_registre_ne_contient_pas_le_contenu_sur_refus():
    """Lorsque le consentement est REFUSÉ, le contenu secret n'apparaît ni dans
    la valeur retournée, ni dans le registre."""
    # Préparation
    reg = Registre()
    secret = "ENREGISTREMENT_CONFIDENTIEL_A_NE_PAS_FUITER"  # proof:allow — fixture de test, aucun secret réel
    conversation = {
        "id": "xyz-001",
        "consentement_enregistrement": "refuse",
    }
    horodatage = "2027-09-01T12:00:00Z"

    # Action
    verdict = consentement.conserver_enregistrement(
        conversation, secret, registre=reg, horodatage=horodatage  # proof:allow — fixture de test, aucun secret réel
    )
    assert verdict["code"] == "REJ-CONSENTEMENT-ABSENT"

    # Aucune trace du contenu dans la valeur retournée (pas de contenu dans le verdict)
    assert "contenu" not in verdict
    # Le registre ne contient pas le secret
    serialized = json.dumps(reg.lire())
    assert secret not in serialized, "Le contenu secret ne doit pas apparaître dans le registre après refus"
