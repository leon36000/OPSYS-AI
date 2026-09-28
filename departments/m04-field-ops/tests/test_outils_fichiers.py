"""T1.4-e2 : `m4_deposer_fichier`, `m4_etat_fichier`, et la vérification des références de preuve
par `m4_completer_intervention`. Contrat : `docs/architecture/FICHIERS.md`.

Base SQLite temporaire migrée (`base_durable`, `departments/m04-field-ops/tests/conftest.py`),
outils réels de M4 (`outils()`, adossés au stockage durable) appelés comme en production
(`opsys.outils.executer_atomique`) — même patron que `test_evenements_m4.py`.
"""

from __future__ import annotations

import base64
import hashlib

import pytest
from m4_field_ops.outils import outils

from opsys import idempotence
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer_atomique

FICTIF = True  # tout binaire ci-dessous est fictif (AGENTS.md), construit dans ce fichier.


def _png_minimal() -> bytes:
    """PNG RVB 1x1 réel, même construction que `conftest.py::png_minimal`."""
    import struct
    import zlib

    def chunk(tag: bytes, donnees: bytes) -> bytes:
        return struct.pack(">I", len(donnees)) + tag + donnees + struct.pack(">I", zlib.crc32(tag + donnees))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\xff\xff", 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _jpeg_minimal() -> bytes:
    """SOI + APP0/JFIF + EOI : coquille JPEG syntaxiquement correcte, suffisante pour la
    vérification serveur (octets magiques FF D8 FF)."""
    return b"\xff\xd8" + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\xff\xd9"


def _deposer(par_nom, contenu, type_mime="image/png", empreinte=None):
    """Dépose `contenu` en UN SEUL bloc (0 sur 1) et rend la réponse complète de l'outil."""
    return executer_atomique(par_nom["m4_deposer_fichier"], {
        "empreinte_sha256": empreinte if empreinte is not None else hashlib.sha256(contenu).hexdigest(),
        "taille_octets": len(contenu), "type_mime": type_mime, "index_bloc": 0, "nombre_blocs": 1,
        "bloc_base64": base64.b64encode(contenu).decode("ascii"),
    })


@pytest.fixture
def par_nom():
    return {o.nom: o for o in outils()}


# ------------------------------------------------------------------ m4_deposer_fichier : succès
def test_deposer_fichier_png_un_seul_bloc_complet(base_durable, par_nom):
    contenu = _png_minimal()
    r = _deposer(par_nom, contenu)
    assert r["ok"] is True and r["resultat"]["accepte"] is True
    resultat = r["resultat"]["resultat"]
    assert resultat["complet"] is True
    assert resultat["blocs_recus"] == [0]
    assert resultat["reference"] == f"fichier:sha256:{hashlib.sha256(contenu).hexdigest()}"


def test_deposer_fichier_jpeg_un_seul_bloc_complet(base_durable, par_nom):
    contenu = _jpeg_minimal()
    r = _deposer(par_nom, contenu, type_mime="image/jpeg")
    assert r["resultat"]["accepte"] is True
    assert r["resultat"]["resultat"]["complet"] is True


def test_deposer_fichier_deux_blocs_incomplet_puis_complet(base_durable, par_nom):
    from opsys import fichiers as fichiers_mod

    bloc0 = b"\x89PNG\r\n\x1a\n" + (b"\x00" * (fichiers_mod.TAILLE_BLOC_OCTETS - 8))
    bloc1 = b"\x11" * 1000
    contenu = bloc0 + bloc1
    empreinte = hashlib.sha256(contenu).hexdigest()

    r0 = executer_atomique(par_nom["m4_deposer_fichier"], {
        "empreinte_sha256": empreinte, "taille_octets": len(contenu), "type_mime": "image/png",
        "index_bloc": 0, "nombre_blocs": 2, "bloc_base64": base64.b64encode(bloc0).decode(),
    })
    assert r0["resultat"]["accepte"] is True
    assert r0["resultat"]["resultat"]["complet"] is False
    assert r0["resultat"]["resultat"]["blocs_recus"] == [0]
    assert r0["resultat"]["resultat"]["reference"] is None

    r1 = executer_atomique(par_nom["m4_deposer_fichier"], {
        "empreinte_sha256": empreinte, "taille_octets": len(contenu), "type_mime": "image/png",
        "index_bloc": 1, "nombre_blocs": 2, "bloc_base64": base64.b64encode(bloc1).decode(),
    })
    assert r1["resultat"]["accepte"] is True
    assert r1["resultat"]["resultat"]["complet"] is True
    assert r1["resultat"]["resultat"]["blocs_recus"] == [0, 1]
    assert r1["resultat"]["resultat"]["reference"] == f"fichier:sha256:{empreinte}"


def test_deposer_fichier_renvoyer_le_meme_bloc_est_un_no_op_accepte(base_durable, par_nom):
    contenu = _png_minimal()
    premier = _deposer(par_nom, contenu)
    second = _deposer(par_nom, contenu)
    assert premier["resultat"]["resultat"]["reference"] == second["resultat"]["resultat"]["reference"]


# ------------------------------------------------------------------ m4_deposer_fichier : refus nommés
def test_deposer_fichier_parametres_invalides(base_durable, par_nom):
    r = executer_atomique(par_nom["m4_deposer_fichier"], {
        "empreinte_sha256": "pas-64-hex", "taille_octets": 10, "type_mime": "image/png",
        "index_bloc": 0, "nombre_blocs": 1, "bloc_base64": base64.b64encode(b"0123456789").decode(),
    })
    assert r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-FICHIER-PARAMETRES-INVALIDES"


def test_deposer_fichier_trop_volumineux(base_durable, par_nom):
    from opsys import fichiers as fichiers_mod

    r = executer_atomique(par_nom["m4_deposer_fichier"], {
        "empreinte_sha256": "ab" * 32, "taille_octets": fichiers_mod.TAILLE_MAX_OCTETS + 1,
        "type_mime": "image/png", "index_bloc": 0, "nombre_blocs": 1,
        "bloc_base64": base64.b64encode(b"x").decode(),
    })
    assert r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-FICHIER-TROP-VOLUMINEUX"


def test_deposer_fichier_incoherent_redeclaration_taille_differente(base_durable, par_nom):
    contenu = _png_minimal()
    empreinte = hashlib.sha256(contenu).hexdigest()
    _deposer(par_nom, contenu, empreinte=empreinte)
    r = executer_atomique(par_nom["m4_deposer_fichier"], {
        "empreinte_sha256": empreinte, "taille_octets": len(contenu) + 1, "type_mime": "image/png",
        "index_bloc": 0, "nombre_blocs": 1, "bloc_base64": base64.b64encode(contenu + b"X").decode(),
    })
    assert r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-FICHIER-INCOHERENT"


def test_deposer_fichier_empreinte_discordante(base_durable, par_nom):
    contenu = _png_minimal()
    r = _deposer(par_nom, contenu, empreinte="00" * 32)  # jamais le vrai SHA-256 de contenu
    assert r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-FICHIER-EMPREINTE-DISCORDANTE"


def test_deposer_fichier_type_non_permis(base_durable, par_nom):
    contenu = b"ceci n'est pas une image (fictif, texte de test)"
    r = _deposer(par_nom, contenu, type_mime="image/png")
    assert r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-FICHIER-TYPE-NON-PERMIS"


# ------------------------------------------------------------------ m4_etat_fichier
def test_etat_fichier_jamais_depose(base_durable, par_nom):
    r = executer_atomique(par_nom["m4_etat_fichier"], {"empreinte_sha256": "ab" * 32})
    assert r["resultat"]["accepte"] is True
    assert r["resultat"]["resultat"] == {
        "existe": False, "complet": False, "blocs_recus": [], "reference": None,
    }


def test_etat_fichier_empreinte_mal_formee_refuse(base_durable, par_nom):
    r = executer_atomique(par_nom["m4_etat_fichier"], {"empreinte_sha256": "trop-court"})
    assert r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-FICHIER-PARAMETRES-INVALIDES"


def test_etat_fichier_apres_depot_complet(base_durable, par_nom):
    contenu = _png_minimal()
    empreinte = hashlib.sha256(contenu).hexdigest()
    _deposer(par_nom, contenu, empreinte=empreinte)
    r = executer_atomique(par_nom["m4_etat_fichier"], {"empreinte_sha256": empreinte})
    assert r["resultat"]["resultat"] == {
        "existe": True, "complet": True, "blocs_recus": [0],
        "reference": f"fichier:sha256:{empreinte}",
    }


# ------------------------------------------------------------------ idempotence d'appareil (T1.4-b)
def test_deposer_fichier_idempotence_appareil_meme_cle_rejoue_sans_reexecuter(base_durable):
    """« Chaque bloc est une mutation avec sa propre clé » (PLAN T1.4-e2) : un renvoi du MÊME bloc
    avec la MÊME clé d'idempotence rejoue la réponse enregistrée, sans ré-exécuter — passe par
    `Capacites._appeler_idempotent` (docs/architecture/IDEMPOTENCE.md), pas seulement par
    l'idempotence de contenu de `opsys.fichiers` elle-même.

    `m4_deposer_fichier` est N2 (tâche interne, automatique dans tous les modes, ADR-0009 §4) :
    un appel RÉEL via `Capacites` (comme le ferait le core pour un appareil) s'exécute tout de suite,
    même en mode `ombre`. Le renvoi rend la même réponse, marquée rejouée, sans nouvelle écriture."""
    from opsys import etat

    deps = charger_departements()
    cap = Capacites(deps, etat.session, appelant="m04-field-ops")
    contenu = _png_minimal()
    arguments = {
        "empreinte_sha256": hashlib.sha256(contenu).hexdigest(), "taille_octets": len(contenu),
        "type_mime": "image/png", "index_bloc": 0, "nombre_blocs": 1,
        "bloc_base64": base64.b64encode(contenu).decode("ascii"),
    }
    meta = idempotence.Meta(
        cle="bloc-0-mutation-1-fictif", appareil="tel-employe-fictif",
        horodatage_appareil="2026-09-28T10:00:00-04:00",
    )
    premier = cap.appeler("m4_deposer_fichier", arguments, meta=meta)
    assert premier["ok"] is True and premier["rejoue"] is False
    assert "statut" not in premier, "N2 : jamais mis en attente d'approbation"
    resultat = premier["resultat"]
    assert resultat["accepte"] is True
    assert resultat["resultat"]["complet"] is True
    assert resultat["resultat"]["reference"] == f"fichier:sha256:{arguments['empreinte_sha256']}"
    second = cap.appeler("m4_deposer_fichier", arguments, meta=meta)
    assert second["ok"] is True and second["rejoue"] is True
    assert second["resultat"] == premier["resultat"]


# ------------------------------------------------------------------ m4_completer_intervention : preuves fichier
_SEL = "sel-test-fichiers"
_VILLE = "Montreal"
_FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}
_FIX_GPS = {"latitude": 45.5088, "longitude": -73.5878}
_ATTESTATION = {"fictif": True, "appareil_id": "APP-T1-4-E2"}


def _mener_a_sur_site(par_nom, lead_id):
    """Mène une intervention jusqu'à `sur_site`, pointages arrivée ET départ compris (planifier ->
    consentement GPS -> en_route -> arrivée -> départ) : condition préalable à
    `m4_completer_intervention`, qui a besoin des deux pointages pour calculer une durée réelle
    (FSM, sinon REJ-TRANSITION-ILLEGALE ou REJ-CONTRAT-INVALIDE) — même patron que
    `test_outils_agent.py`."""
    contrat = {
        "lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale",
        "ville": _VILLE, "canal": "telephone",
        "contact": {"nom": "Client", "telephone": "0102030405"}, "urgence_declaree": False,
    }
    marqueur = {
        "readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
        "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32,
    }
    consentement = executer_atomique(par_nom["m4_definir_consentement_gps"], {
        "technicien_id": "T1", "action": "donne", "horodatage": "2025-06-02T07:00:00+00:00",
        "version_politique": "POLITIQUE-geolocalisation-v1-test",
        "preuve": {"fictif": True, "reference": "consentement-test"},
    })
    assert consentement["resultat"]["accepte"] is True, consentement

    plan = executer_atomique(par_nom["m4_planifier_intervention"], {
        "contrat": contrat, "marqueur": marqueur, "horodatage": "2025-06-02T08:00:00+00:00",
        "sel": _SEL, "techniciens_disponibles": ["T1"], "fenetres_disponibles": [_FENETRE],
    })
    assert plan["ok"] is True, plan
    i_id = plan["resultat"]["intervention_id"]

    depart = executer_atomique(par_nom["m4_demarrer_route"], {
        "intervention_id": i_id, "technicien_id": "T1", "horodatage": "2025-06-02T08:30:00+00:00",
    })
    assert depart["resultat"]["accepte"] is True, depart

    import m4_field_ops.cedule as cedule_mod
    token = cedule_mod.tokeniser_ville(_SEL, _VILLE)
    referentiel = {token: {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}
    for action, horo in (("arrivee", "2025-06-02T09:00:00+00:00"), ("depart", "2025-06-02T11:30:00+00:00")):
        r = executer_atomique(par_nom["m4_pointer"], {
            "intervention_id": i_id, "technicien_id": "T1", "action": action, "horodatage": horo,
            "fix_gps": _FIX_GPS, "attestation": _ATTESTATION, "fenetre_travail": _FENETRE,
            "referentiel_villes": referentiel, "ville": _VILLE, "sel": _SEL,
        })
        assert r["resultat"]["accepte"] is True, r
    return i_id


def _completer(par_nom, i_id, photos_apres, signature=None, signature_requise=False):
    return executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": {
            "checklist_complete": True, "photos_apres": photos_apres,
            "notes": "RAS.", "signature": signature,
        },
        "signature_requise": signature_requise,
    })


def test_completer_intervention_reference_forme_invalide_refuse_nomme(base_durable, par_nom):
    i_id = _mener_a_sur_site(par_nom, "L-FICHIER-FORME")
    r = _completer(par_nom, i_id, ["une-chaine-inventee.jpg"])
    assert r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-PREUVE-FICHIER-INTROUVABLE"
    assert "photos_apres[0]" in r["resultat"]["verdict"]["detail"]


def test_completer_intervention_reference_jamais_deposee_refuse_nomme(base_durable, par_nom):
    i_id = _mener_a_sur_site(par_nom, "L-FICHIER-ABSENT")
    reference = f"fichier:sha256:{'cd' * 32}"  # forme valide, jamais déposé
    r = _completer(par_nom, i_id, [reference])
    assert r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-PREUVE-FICHIER-INTROUVABLE"


def test_completer_intervention_reference_incomplete_refuse_nomme(base_durable, par_nom):
    from opsys import fichiers as fichiers_mod

    i_id = _mener_a_sur_site(par_nom, "L-FICHIER-INCOMPLET")
    bloc0 = b"\x89PNG\r\n\x1a\n" + (b"\x00" * (fichiers_mod.TAILLE_BLOC_OCTETS - 8))
    bloc1 = b"\x11" * 1000
    contenu = bloc0 + bloc1
    empreinte = hashlib.sha256(contenu).hexdigest()
    executer_atomique(par_nom["m4_deposer_fichier"], {
        "empreinte_sha256": empreinte, "taille_octets": len(contenu), "type_mime": "image/png",
        "index_bloc": 0, "nombre_blocs": 2, "bloc_base64": base64.b64encode(bloc0).decode(),
    })  # UN SEUL des deux blocs : jamais complet.

    r = _completer(par_nom, i_id, [f"fichier:sha256:{empreinte}"])
    assert r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-PREUVE-FICHIER-INTROUVABLE"


def test_completer_intervention_signature_de_type_jpeg_refusee(base_durable, par_nom):
    """La signature doit être PNG (T1.4-e2 point 3 du PLAN) : une référence JPEG complète et
    valide, mais du mauvais type, reste un refus nommé."""
    i_id = _mener_a_sur_site(par_nom, "L-SIGNATURE-JPEG")
    photo = _deposer(par_nom, _png_minimal())["resultat"]["resultat"]["reference"]
    signature_jpeg = _deposer(par_nom, _jpeg_minimal(), type_mime="image/jpeg")
    signature_ref = signature_jpeg["resultat"]["resultat"]["reference"]

    r = _completer(par_nom, i_id, [photo], signature=signature_ref, signature_requise=True)
    assert r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-PREUVE-FICHIER-INTROUVABLE"
    assert "signature" in r["resultat"]["verdict"]["detail"]


def test_completer_intervention_photo_jpeg_et_signature_png_acceptees(base_durable, par_nom):
    """Chemin heureux complet : photos_apres en JPEG (type image, l'un ou l'autre est permis),
    signature en PNG — les deux réellement déposées et complètes."""
    i_id = _mener_a_sur_site(par_nom, "L-FICHIERS-OK")
    photo = _deposer(par_nom, _jpeg_minimal(), type_mime="image/jpeg")["resultat"]["resultat"]["reference"]
    signature = _deposer(par_nom, _png_minimal())["resultat"]["resultat"]["reference"]

    r = _completer(par_nom, i_id, [photo], signature=signature, signature_requise=True)
    assert r["resultat"]["accepte"] is True, r
    assert r["resultat"]["resultat"]["statut"] == "completed_pending_review"
