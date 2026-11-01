"""Adaptateur IMAP/SMTP (imaplib, smtplib) contre un faux serveur en mémoire : UIDVALIDITY+UID, `UID n:*`, lecture
seule, injection de commande, hôte privé, mot de passe d'application dans le coffre. NON testé contre un vrai serveur
IMAP."""

from __future__ import annotations

import courriel_doubles as dbl
import courriel_qa as qa
import pytest

from opsys.courriel_connecteurs import imap
from opsys.courriel_connecteurs.erreurs import ErreurCourriel
from opsys.courriel_connecteurs.modele import RefMessage
from opsys.courriel_connecteurs.port import encoder_curseur

FICTIF = True


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = qa.preparer(tmp_path, monkeypatch)
    qa.connecter_imap(m)
    return m


@pytest.fixture
def boite(monde):
    return monde.service.fournisseur("imap-paul")


def _tout(boite, dossier="INBOX", curseur=None, limite=3):
    ajouts, pages = [], 0
    while True:
        page = boite.synchroniser(dossier, curseur, limite=limite)
        ajouts += [r.ref for r in page.ajouts]
        curseur, pages = page.curseur, pages + 1
        if page.termine:
            return ajouts, curseur, pages


def test_dossiers_roles_et_noselect(boite):
    dossiers = {d.id: d for d in boite.lister_dossiers()}
    assert dossiers["INBOX"].role == "inbox" and dossiers["Elements envoyes"].role == "sent"
    assert "[Gmail]" not in dossiers  # \Noselect : pas un dossier lisible


def test_amorcage_pagine_incremental_et_bizarrerie_uid_etoile(monde, boite):
    uids = [monde.serveur_imap.ajouter(dbl.courriel_brut(objet=f"m{i}")) for i in range(7)]
    ajouts, curseur, pages = _tout(boite)
    validite = monde.serveur_imap.dossiers["INBOX"]["uidvalidity"]
    assert ajouts == [f"{validite}:{u}" for u in uids] and pages == 3
    # `UID 8:*` renvoie quand même le dernier message (UID 7) : il ne doit PAS ressortir
    ajouts2, curseur2, _ = _tout(boite, curseur=curseur)
    assert ajouts2 == []
    nouveau = monde.serveur_imap.ajouter(dbl.courriel_brut(objet="neuf"))
    ajouts3, _, _ = _tout(boite, curseur=curseur2)
    assert ajouts3 == [f"{validite}:{nouveau}"]


def test_reprise_au_milieu_depuis_le_curseur_seul(monde, boite):
    for i in range(6):
        monde.serveur_imap.ajouter(dbl.courriel_brut(objet=f"m{i}"))
    premiere = boite.synchroniser("INBOX", None, limite=2)
    assert not premiere.termine and len(premiere.ajouts) == 2
    reste, _, _ = _tout(monde.service.fournisseur("imap-paul"), curseur=premiere.curseur, limite=2)
    assert len(reste) == 4 and not set(reste) & {r.ref for r in premiere.ajouts}


def test_uidvalidity_change_curseur_expire(monde, boite):
    monde.serveur_imap.ajouter(dbl.courriel_brut())
    _, curseur, _ = _tout(boite)
    monde.serveur_imap.changer_uidvalidity()
    with pytest.raises(ErreurCourriel) as exc:
        boite.synchroniser("INBOX", curseur)
    assert exc.value.code == "REJ-COURRIEL-CURSEUR-EXPIRE" and exc.value.reprenable


def test_lecture_message_et_uidvalidity_verifiee(monde, boite):
    brut = dbl.courriel_brut(objet="À lire", corps="é à ç")
    uid = monde.serveur_imap.ajouter(brut)
    validite = monde.serveur_imap.dossiers["INBOX"]["uidvalidity"]
    assert boite.lire_message(RefMessage(f"{validite}:{uid}", "INBOX")).octets == brut
    monde.serveur_imap.changer_uidvalidity()
    with pytest.raises(ErreurCourriel) as exc:
        boite.lire_message(RefMessage(f"{validite}:{uid}", "INBOX"))
    assert exc.value.code == "REJ-COURRIEL-CURSEUR-EXPIRE"


def test_lecture_seule_aucune_commande_d_ecriture(monde, boite):
    uid = monde.serveur_imap.ajouter(dbl.courriel_brut())
    validite = monde.serveur_imap.dossiers["INBOX"]["uidvalidity"]
    _tout(boite)
    boite.lire_message(RefMessage(f"{validite}:{uid}", "INBOX"))
    commandes = monde.serveur_imap.commandes
    assert all(c[0] != "uid" or c[1] in {"SEARCH", "FETCH"} for c in commandes)
    assert all(c[2] is True for c in commandes if c[0] == "select")  # SELECT en lecture seule (EXAMINE)
    fetch = [c for c in commandes if c[:2] == ("uid", "FETCH")]
    assert any("BODY.PEEK[]" in c[3] for c in fetch) and not any(c[3] == "RFC822)" or c[3] == "BODY[]" for c in fetch)


def test_taille_demandee_avant_le_telechargement(monde, boite):
    monde.serveur_imap.ajouter(b"Subject: x\r\n\r\n" + b"x" * (32 * 1024 * 1024 + 10))
    uid = max(monde.serveur_imap.dossiers["INBOX"]["messages"])
    validite = monde.serveur_imap.dossiers["INBOX"]["uidvalidity"]
    with pytest.raises(ErreurCourriel) as exc:
        boite.lire_message(RefMessage(f"{validite}:{uid}", "INBOX"))
    assert exc.value.code == "REJ-COURRIEL-MESSAGE-TROP-GROS"
    assert not any(c[:2] == ("uid", "FETCH") and "BODY.PEEK[]" in c[3] for c in monde.serveur_imap.commandes)


def test_mauvais_mot_de_passe_erreur_typee_sans_secret(monde):
    monde.serveur_imap.mot_de_passe = "autre-mot-de-passe-fictif-xyz"
    boite = monde.service.fournisseur("imap-paul")
    with pytest.raises(ErreurCourriel) as exc:
        boite.synchroniser("INBOX", None)
    assert exc.value.code == "REJ-COURRIEL-IMAP-AUTH" and "mot-de-passe-app-fictif" not in str(exc.value)
    monde.service.signaler_erreur("imap-paul", exc.value)
    from opsys import stockage
    from opsys.courriel_connecteurs import comptes

    with stockage.transaction() as cnx:
        vue = comptes.lire(cnx, "imap-paul")
    assert vue["etat"] == "reconnexion_requise" and vue["derniere_erreur_code"] == "REJ-COURRIEL-IMAP-AUTH"


def test_mot_de_passe_jamais_dans_les_commandes_ni_les_journaux(monde, boite):
    monde.serveur_imap.ajouter(dbl.courriel_brut())
    _tout(boite)
    assert "mot-de-passe-app-fictif-0001" not in repr(monde.serveur_imap.commandes)
    from opsys import stockage
    from opsys.courriel_connecteurs import comptes

    with stockage.transaction() as cnx:
        assert "mot-de-passe-app-fictif" not in repr(comptes.journal(cnx)) + repr(comptes.lister(cnx))


def test_connexion_toujours_fermee(monde, boite):
    monde.serveur_imap.ajouter(dbl.courriel_brut())
    _tout(boite)
    boite.lister_dossiers()
    with pytest.raises(ErreurCourriel):
        boite.synchroniser("DOSSIER-INCONNU", None)
    assert monde.serveur_imap.connexions == monde.serveur_imap.fermetures > 0


def test_serveur_injoignable_reprenable(monde, boite):
    monde.serveur_imap.panne_connexion = True
    with pytest.raises(ErreurCourriel) as exc:
        boite.synchroniser("INBOX", None)
    assert exc.value.code == "REJ-COURRIEL-RESEAU" and exc.value.reprenable


@pytest.mark.parametrize("dossier", ['INBOX"\r\nA1 DELETE INBOX', "INBOX\nX", "a\x00b", "", "x" * 300])
def test_injection_de_commande_par_nom_de_dossier_refusee_avant_l_envoi(monde, boite, dossier):
    with pytest.raises(ErreurCourriel) as exc:
        boite.synchroniser(dossier, None)
    assert exc.value.code == "REJ-COURRIEL-ARGUMENT-INVALIDE"
    assert not any(c[0] == "select" for c in monde.serveur_imap.commandes)


def test_nom_de_dossier_avec_guillemets_est_cite_et_echappe(monde, boite):
    monde.serveur_imap.ajouter(dbl.courriel_brut(), dossier='Clients "VIP" \\ test')
    page = boite.synchroniser('Clients "VIP" \\ test', None)
    assert len(page.ajouts) == 1
    assert any(c[0] == "select" and c[1] == '"Clients \\"VIP\\" \\\\ test"' for c in monde.serveur_imap.commandes)


@pytest.mark.parametrize("ref", ["", "1", "a:b", "1:2:3", "-1:5", "0:5", "5:0", "1; DELETE:1", "1:2\r\n"])
def test_reference_de_message_invalide(boite, ref):
    with pytest.raises(ErreurCourriel) as exc:
        boite.lire_message(RefMessage(ref, "INBOX"))
    assert exc.value.code == "REJ-COURRIEL-ARGUMENT-INVALIDE"


@pytest.mark.parametrize(
    "curseur",
    [
        "imap:v1:e30",
        encoder_curseur("imap", {"d": "AUTRE", "v": "1", "u": 1}),
        encoder_curseur("imap", {"d": "INBOX", "v": "abc", "u": 1}),
        encoder_curseur("imap", {"d": "INBOX", "v": "1", "u": -5}),
        encoder_curseur("imap", {"d": "INBOX", "v": "1", "u": "1"}),
        encoder_curseur("gmail", {"p": "h", "h": "1"}),
    ],
)
def test_curseur_imap_falsifie(boite, curseur):
    with pytest.raises(ErreurCourriel) as exc:
        boite.synchroniser("INBOX", curseur)
    assert exc.value.code == "REJ-COURRIEL-CURSEUR-INVALIDE"


@pytest.mark.parametrize(
    "hote",
    [
        "localhost",
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.9",
        "::1",
        "169.254.169.254",
        "serveur.local",
        "interne.internal",
        "a b",
        "",
        "x" * 300,
        "-mauvais.example.test",
    ],
)
def test_hote_prive_ou_invalide_refuse(hote):
    with pytest.raises(ErreurCourriel):
        imap.verifier_hote(hote)


def test_hote_public_accepte():
    assert imap.verifier_hote("imap.example.test") == "imap.example.test"
    assert imap.verifier_hote("8.8.8.8") == "8.8.8.8"


def test_utf7_modifie_decode_pour_l_affichage():
    assert imap.decoder_mutf7("Envoy&AOk-s") == "Envoyés"
    assert imap.decoder_mutf7("A&-B") == "A&B"
    assert imap.decoder_mutf7("&pas-valide!") != ""


# -- pont vers le contrat des originaux courriel ------------------------------------------------------------------
def test_original_imap_conforme_au_contrat_existant_et_stockable(monde, boite):
    from sqlalchemy import select

    from opsys import identite, stockage
    from opsys import reception_courriel_stockage as stockage_originaux
    from opsys.courriel_connecteurs import originaux
    from opsys.stockage.schema import OPSYS_INSTANCE

    brut_imap = dbl.courriel_brut(objet="Original IMAP fictif", corps="Contenu fictif pour l'original")
    uid = monde.serveur_imap.ajouter(brut_imap)
    validite = monde.serveur_imap.dossiers["INBOX"]["uidvalidity"]
    message = boite.lire_message(RefMessage(f"{validite}:{uid}", "INBOX"))
    with stockage.transaction() as cnx:
        instance_id = cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
        identite.creer_personne(
            cnx, "admin.originaux", "Admin originaux fictif", "mot-de-passe-fictif-123456", ["admin"]
        )
    source_id = originaux.source_id_imap("imap.example.test", monde.serveur_imap.utilisateur)
    assert len(source_id) == 64 and "example" not in source_id
    options = dict(instance_id=instance_id, compte_id="imap-paul", source_id=source_id, message_id="abc@example.test")
    original = originaux.original_imap(message, **options)
    assert original.source == brut_imap and original.source_octets == len(brut_imap)
    arguments = originaux.arguments_original_imap(message, **options)
    cle = (("a" * 32), b"k" * 32)
    coordonnees = {k: arguments[k] for k in ("instance_id", "source_id", "compte_id", "boite", "uid_validity", "uid")}

    def autoriser(cnx, coords, operation):
        assert dict(coords) == coordonnees
        return "admin.originaux", "b" * 64

    recu = stockage_originaux.recevoir(
        arguments, source=message.octets, autoriser=autoriser, obtenir_cle=lambda ref: cle
    )
    assert recu["statut"] == "ORIGINAL_STOCKE_INTERNE"
    _, relu = stockage_originaux.lire(coordonnees, autoriser=autoriser, obtenir_cle=lambda ref: cle)
    assert relu.source == brut_imap


def test_original_imap_refuse_reference_non_imap_et_message_trop_gros(monde):
    from opsys.courriel_connecteurs import originaux
    from opsys.courriel_connecteurs.modele import MessageBrut

    options = dict(instance_id="00000000-0000-4000-8000-000000000000", compte_id="imap-paul", source_id="c" * 64)
    with pytest.raises(ErreurCourriel) as exc:
        originaux.original_imap(MessageBrut("18f3a2b4c5d6e7f8", "INBOX", b"x"), **options)  # une référence Gmail
    assert exc.value.code == "REJ-COURRIEL-ARGUMENT-INVALIDE"
    with pytest.raises(ErreurCourriel) as exc:
        originaux.original_imap(MessageBrut("17:5", "INBOX", b"x" * (1024 * 1024 + 1)), **options)
    assert exc.value.code == "REJ-COURRIEL-MESSAGE-INVALIDE"
