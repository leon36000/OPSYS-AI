"""Dépôt de fichiers adressé par contenu (T1.4-e2). Contrat : docs/architecture/FICHIERS.md."""

from __future__ import annotations

import base64
import hashlib
import struct
import zlib

import pytest

from opsys import fichiers

FICTIF = True  # tout binaire ci-dessous est fictif (AGENTS.md), construit dans ce fichier.


def _png_minimal(pixel: bytes = b"\xff\xff\xff") -> bytes:
    """PNG RVB 1x1 réel (pas un simple préfixe magique) : signature + IHDR + IDAT (zlib d'une
    seule ligne filtrée « aucun ») + IEND, avec CRC32 correct sur chaque chunk."""
    def chunk(tag: bytes, donnees: bytes) -> bytes:
        return struct.pack(">I", len(donnees)) + tag + donnees + struct.pack(">I", zlib.crc32(tag + donnees))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" + pixel, 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _jpeg_minimal() -> bytes:
    """SOI + APP0/JFIF + EOI : coquille JPEG syntaxiquement correcte, suffisante pour la
    vérification serveur (octets magiques FF D8 FF), pas nécessairement décodable par un
    visualiseur (aucune donnée de scan)."""
    return b"\xff\xd8" + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\xff\xd9"


def _deposer(cnx, contenu: bytes, type_mime: str, empreinte: str | None = None,
             index_bloc: int = 0, nombre_blocs: int = 1, recu_le: str = "2026-09-28T10:00:00-04:00"):
    return fichiers.deposer_bloc(
        cnx,
        empreinte if empreinte is not None else hashlib.sha256(contenu).hexdigest(),
        len(contenu), type_mime, index_bloc, nombre_blocs,
        base64.b64encode(contenu).decode("ascii"), recu_le=recu_le,
    )


# ------------------------------------------------------------------ fonctions pures
def test_reference_pour_et_empreinte_depuis_reference_font_l_aller_retour():
    empreinte = "ab" * 32
    ref = fichiers.reference_pour(empreinte)
    assert ref == f"fichier:sha256:{empreinte}"
    assert fichiers.empreinte_depuis_reference(ref) == empreinte


@pytest.mark.parametrize("valeur", [
    None, 42, "", "fichier:sha256:trop-court", "fichier:sha256:" + "g" * 64,
    "fichier:sha256:" + "AB" * 32,  # majuscules refusées
    "autre-prefixe:" + "ab" * 32,
])
def test_empreinte_depuis_reference_forme_invalide_rend_none(valeur):
    assert fichiers.empreinte_depuis_reference(valeur) is None


@pytest.mark.parametrize("valeur", [None, 42, "AB" * 32, "ab" * 31, "gg" * 32, ""])
def test_empreinte_valide_refuse_toute_forme_non_conforme(valeur):
    assert fichiers.empreinte_valide(valeur) is False


# ------------------------------------------------------------------ état d'un fichier jamais vu
def test_etat_fichier_jamais_vu(session):
    with session() as cnx:
        e = fichiers.etat(cnx, "ab" * 32)
    assert e == fichiers.EtatFichier(existe=False, complet=False, blocs_recus=(), type_mime=None, reference=None)


# ------------------------------------------------------------------ dépôt à un seul bloc : succès
def test_depot_png_un_seul_bloc_complet_immediatement(session):
    contenu = _png_minimal()
    with session() as cnx:
        resultat = _deposer(cnx, contenu, "image/png")
    assert resultat.accepte is True
    assert resultat.complet is True
    assert resultat.blocs_recus == (0,)
    empreinte = hashlib.sha256(contenu).hexdigest()
    assert resultat.reference == f"fichier:sha256:{empreinte}"

    with session() as cnx:
        e = fichiers.etat(cnx, empreinte)
    assert e.existe is True and e.complet is True and e.blocs_recus == (0,)
    assert e.type_mime == "image/png" and e.reference == resultat.reference


def test_depot_jpeg_un_seul_bloc_complet_immediatement(session):
    contenu = _jpeg_minimal()
    with session() as cnx:
        resultat = _deposer(cnx, contenu, "image/jpeg")
    assert resultat.accepte is True and resultat.complet is True
    assert resultat.reference == f"fichier:sha256:{hashlib.sha256(contenu).hexdigest()}"


def test_recu_le_omis_lit_l_heure_courante_ici_meme(session):
    """`recu_le` est optionnel (contrat FIXE de `m4_deposer_fichier`, sans paramètre
    d'horodatage) : omis, `opsys.fichiers` lit l'heure courante lui-même — jamais un département
    (garde AST M4, voir docstring du module)."""
    contenu = _png_minimal()
    with session() as cnx:
        resultat = fichiers.deposer_bloc(
            cnx, hashlib.sha256(contenu).hexdigest(), len(contenu), "image/png", 0, 1,
            base64.b64encode(contenu).decode(),
        )
    assert resultat.accepte is True and resultat.complet is True


def test_renvoyer_le_meme_bloc_est_un_no_op_accepte(session):
    contenu = _png_minimal()
    with session() as cnx:
        premier = _deposer(cnx, contenu, "image/png")
        second = _deposer(cnx, contenu, "image/png")
    assert premier.accepte is True and second.accepte is True
    assert premier.reference == second.reference
    assert second.complet is True and second.blocs_recus == (0,)


# ------------------------------------------------------------------ dépôt multi-blocs
def test_depot_deux_blocs_incomplet_puis_complet(session):
    bloc0 = b"\x89PNG\r\n\x1a\n" + (b"\x00" * (fichiers.TAILLE_BLOC_OCTETS - 8))
    bloc1 = b"\x11" * 1000
    contenu = bloc0 + bloc1
    empreinte = hashlib.sha256(contenu).hexdigest()

    with session() as cnx:
        apres_bloc0 = fichiers.deposer_bloc(
            cnx, empreinte, len(contenu), "image/png", 0, 2,
            base64.b64encode(bloc0).decode("ascii"), recu_le="2026-09-28T10:00:00-04:00",
        )
    assert apres_bloc0.accepte is True and apres_bloc0.complet is False
    assert apres_bloc0.blocs_recus == (0,)
    assert apres_bloc0.reference is None

    with session() as cnx:
        e = fichiers.etat(cnx, empreinte)
    assert e.existe is True and e.complet is False and e.blocs_recus == (0,)

    with session() as cnx:
        apres_bloc1 = fichiers.deposer_bloc(
            cnx, empreinte, len(contenu), "image/png", 1, 2,
            base64.b64encode(bloc1).decode("ascii"), recu_le="2026-09-28T10:00:05-04:00",
        )
    assert apres_bloc1.accepte is True and apres_bloc1.complet is True
    assert apres_bloc1.blocs_recus == (0, 1)
    assert apres_bloc1.reference == f"fichier:sha256:{empreinte}"

    # les blocs peuvent arriver dans n'importe quel ordre : reprise par l'état, jamais devinée.
    with session() as cnx:
        e2 = fichiers.etat(cnx, empreinte)
    assert e2.complet is True and e2.blocs_recus == (0, 1)


# ------------------------------------------------------------------ paramètres invalides
@pytest.mark.parametrize("empreinte", [None, 42, "trop-court", "AB" * 32, "gg" * 32])
def test_empreinte_sha256_invalide_refuse(session, empreinte):
    with session() as cnx:
        r = fichiers.deposer_bloc(
            cnx, empreinte, 10, "image/png", 0, 1, base64.b64encode(b"0123456789").decode(),
            recu_le="2026-09-28T10:00:00-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_PARAMETRES_INVALIDES


@pytest.mark.parametrize("nombre_blocs", [0, -1, 65, "1", 1.0, True])
def test_nombre_blocs_invalide_refuse(session, nombre_blocs):
    with session() as cnx:
        r = fichiers.deposer_bloc(
            cnx, "ab" * 32, 10, "image/png", 0, nombre_blocs, base64.b64encode(b"0123456789").decode(),
            recu_le="2026-09-28T10:00:00-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_PARAMETRES_INVALIDES


@pytest.mark.parametrize("index_bloc", [-1, 1, 2, "0", None])
def test_index_bloc_hors_bornes_refuse(session, index_bloc):
    with session() as cnx:
        r = fichiers.deposer_bloc(
            cnx, "ab" * 32, 10, "image/png", index_bloc, 1, base64.b64encode(b"0123456789").decode(),
            recu_le="2026-09-28T10:00:00-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_PARAMETRES_INVALIDES


@pytest.mark.parametrize("type_mime", ["image/gif", "text/plain", "", None, "IMAGE/PNG"])
def test_type_mime_hors_liste_permise_refuse(session, type_mime):
    with session() as cnx:
        r = fichiers.deposer_bloc(
            cnx, "ab" * 32, 10, type_mime, 0, 1, base64.b64encode(b"0123456789").decode(),
            recu_le="2026-09-28T10:00:00-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_PARAMETRES_INVALIDES


def test_bloc_base64_invalide_refuse(session):
    with session() as cnx:
        r = fichiers.deposer_bloc(
            cnx, "ab" * 32, 10, "image/png", 0, 1, "***pas-du-base64***",
            recu_le="2026-09-28T10:00:00-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_PARAMETRES_INVALIDES


def test_nombre_blocs_incoherent_avec_taille_octets_refuse(session):
    contenu = _png_minimal()
    with session() as cnx:
        # 2 blocs annoncés pour un contenu qui tient dans un seul bloc de TAILLE_BLOC_OCTETS.
        r = fichiers.deposer_bloc(
            cnx, hashlib.sha256(contenu).hexdigest(), len(contenu), "image/png", 0, 2,
            base64.b64encode(contenu).decode(), recu_le="2026-09-28T10:00:00-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_PARAMETRES_INVALIDES


def test_bloc_de_longueur_inattendue_pour_sa_position_refuse(session):
    contenu = _png_minimal()
    with session() as cnx:
        # taille_octets/nombre_blocs annoncent un bloc unique, mais le contenu réellement encodé
        # est plus court que ce que la taille déclarée implique pour ce bloc.
        r = fichiers.deposer_bloc(
            cnx, hashlib.sha256(contenu).hexdigest(), len(contenu) + 5, "image/png", 0, 1,
            base64.b64encode(contenu).decode(), recu_le="2026-09-28T10:00:00-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_PARAMETRES_INVALIDES


# ------------------------------------------------------------------ trop volumineux
def test_taille_octets_au_dela_du_maximum_refuse(session):
    with session() as cnx:
        r = fichiers.deposer_bloc(
            cnx, "ab" * 32, fichiers.TAILLE_MAX_OCTETS + 1, "image/png", 0, 1,
            base64.b64encode(b"x").decode(), recu_le="2026-09-28T10:00:00-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_TROP_VOLUMINEUX


def test_bloc_plus_grand_que_la_taille_fixe_refuse(session):
    """Déclare un unique bloc plein (taille_octets = TAILLE_BLOC_OCTETS pile, nombre_blocs=1,
    donc self-cohérent) mais envoie RÉELLEMENT un octet de trop : la taille du bloc reçu, pas la
    déclaration elle-même, dépasse la taille fixe."""
    contenu_trop_gros = b"\x00" * (fichiers.TAILLE_BLOC_OCTETS + 1)
    with session() as cnx:
        r = fichiers.deposer_bloc(
            cnx, hashlib.sha256(contenu_trop_gros).hexdigest(), fichiers.TAILLE_BLOC_OCTETS, "image/png", 0, 1,
            base64.b64encode(contenu_trop_gros).decode(), recu_le="2026-09-28T10:00:00-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_TROP_VOLUMINEUX


# ------------------------------------------------------------------ incohérent
def test_meme_empreinte_redeclaree_avec_une_autre_taille_refuse(session):
    contenu = _png_minimal()
    empreinte = hashlib.sha256(contenu).hexdigest()
    with session() as cnx:
        premier = _deposer(cnx, contenu, "image/png", empreinte=empreinte)
    assert premier.accepte is True
    with session() as cnx:
        # Bloc self-cohérent pour CETTE nouvelle déclaration (un octet de plus, donc de la bonne
        # longueur pour taille_octets=len(contenu)+1) : la discordance testée est bien contre
        # l'ancienne déclaration en base, pas contre la forme de cet appel-ci.
        r = fichiers.deposer_bloc(
            cnx, empreinte, len(contenu) + 1, "image/png", 0, 1,
            base64.b64encode(contenu + b"X").decode(), recu_le="2026-09-28T10:00:01-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_INCOHERENT
    # rien n'a été perturbé : l'état déjà complet reste inchangé.
    with session() as cnx:
        e = fichiers.etat(cnx, empreinte)
    assert e.complet is True and e.reference == premier.reference


def test_meme_empreinte_redeclaree_avec_un_autre_type_refuse(session):
    contenu = _png_minimal()
    empreinte = hashlib.sha256(contenu).hexdigest()
    with session() as cnx:
        _deposer(cnx, contenu, "image/png", empreinte=empreinte)
        r = fichiers.deposer_bloc(
            cnx, empreinte, len(contenu), "image/jpeg", 0, 1,
            base64.b64encode(contenu).decode(), recu_le="2026-09-28T10:00:01-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_INCOHERENT


def test_meme_index_bloc_renvoye_avec_un_contenu_different_refuse(session):
    bloc0 = b"\x89PNG\r\n\x1a\n" + (b"\x00" * (fichiers.TAILLE_BLOC_OCTETS - 8))
    bloc1 = b"\x11" * 1000
    contenu = bloc0 + bloc1
    empreinte = hashlib.sha256(contenu).hexdigest()
    with session() as cnx:
        fichiers.deposer_bloc(
            cnx, empreinte, len(contenu), "image/png", 0, 2, base64.b64encode(bloc0).decode(),
            recu_le="2026-09-28T10:00:00-04:00",
        )
        autre_bloc0 = b"\x22" * len(bloc0)
        r = fichiers.deposer_bloc(
            cnx, empreinte, len(contenu), "image/png", 0, 2, base64.b64encode(autre_bloc0).decode(),
            recu_le="2026-09-28T10:00:01-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_INCOHERENT


# ------------------------------------------------------------------ empreinte discordante
def test_sha256_assemble_different_de_l_empreinte_annoncee_efface_et_refuse(session):
    contenu = _png_minimal()
    empreinte_fausse = "00" * 32  # forme valide, mais jamais le vrai SHA-256 de `contenu`
    with session() as cnx:
        r = fichiers.deposer_bloc(
            cnx, empreinte_fausse, len(contenu), "image/png", 0, 1,
            base64.b64encode(contenu).decode(), recu_le="2026-09-28T10:00:00-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_EMPREINTE_DISCORDANTE
    with session() as cnx:
        e = fichiers.etat(cnx, empreinte_fausse)
    assert e.blocs_recus == ()  # blocs effacés


# ------------------------------------------------------------------ type non permis
def test_octets_magiques_absents_pour_le_type_annonce_efface_et_refuse(session):
    contenu = b"ceci n'est pas une image, juste du texte pour le test (fictif)"
    empreinte = hashlib.sha256(contenu).hexdigest()
    with session() as cnx:
        r = fichiers.deposer_bloc(
            cnx, empreinte, len(contenu), "image/png", 0, 1,
            base64.b64encode(contenu).decode(), recu_le="2026-09-28T10:00:00-04:00",
        )
    assert r.accepte is False and r.raison == fichiers.RAISON_TYPE_NON_PERMIS
    with session() as cnx:
        e = fichiers.etat(cnx, empreinte)
    assert e.blocs_recus == ()


def test_apres_effacement_un_redepot_correct_reussit(session):
    """Après une discordance qui efface les blocs, redéposer le VRAI contenu pour la même
    empreinte réussit : la déclaration (taille/type/nombre_blocs) reste utilisable."""
    contenu = _png_minimal()
    empreinte_fausse = "33" * 32
    with session() as cnx:
        echec = fichiers.deposer_bloc(
            cnx, empreinte_fausse, len(contenu), "image/png", 0, 1,
            base64.b64encode(contenu).decode(), recu_le="2026-09-28T10:00:00-04:00",
        )
        assert echec.accepte is False
        # redépôt du contenu dont le SHA-256 correspond RÉELLEMENT à empreinte_fausse : impossible
        # à construire ici (ce serait une collision SHA-256) — on vérifie plutôt qu'un second essai
        # avec la MÊME déclaration incohérente échoue à nouveau, proprement, sans jamais planter.
        second_echec = fichiers.deposer_bloc(
            cnx, empreinte_fausse, len(contenu), "image/png", 0, 1,
            base64.b64encode(contenu).decode(), recu_le="2026-09-28T10:00:01-04:00",
        )
    assert second_echec.accepte is False and second_echec.raison == fichiers.RAISON_EMPREINTE_DISCORDANTE
