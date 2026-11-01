"""Exports mbox en lecture seule : séparateurs, désécapage mboxrd, reprise par curseur, nom seul, liens, bornes de
taille, bombes de décompression `.mbox.gz`, fichier modifié. Fichiers fictifs écrits dans un dossier temporaire."""

from __future__ import annotations

import gzip
import os

import courriel_doubles as dbl
import pytest

from opsys.courriel_connecteurs import normalisation
from opsys.courriel_connecteurs.erreurs import ErreurCourriel
from opsys.courriel_connecteurs.mbox import FournisseurMbox, LimitesMbox
from opsys.courriel_connecteurs.modele import MessageBrut, RefMessage
from opsys.courriel_connecteurs.port import encoder_curseur

FICTIF = True


def _sep(i: int) -> bytes:
    return f"From {1000 + i}@xxx Mon Mar 01 00:00:0{i % 10} +0000 2021\n".encode()


def _mbox(messages: list[bytes]) -> bytes:
    sortie = b""
    for i, m in enumerate(messages):
        sortie += _sep(i) + m.replace(b"\r\n", b"\n").rstrip(b"\n") + b"\n\n"
    return sortie


def _brut(i: int, corps: str = "corps") -> bytes:
    return dbl.courriel_brut(objet=f"message {i}", corps=f"{corps} {i}", message_id=f"<m{i}@example.test>")


@pytest.fixture
def imports(tmp_path):
    dossier = tmp_path / "imports"
    dossier.mkdir()
    return dossier


def _ecrire(imports, nom, octets):
    (imports / nom).write_bytes(octets)
    return nom


def _tout(f, curseur=None, limite=2):
    refs, pages = [], 0
    while True:
        page = f.synchroniser(f._nom, curseur, limite=limite)
        refs += list(page.ajouts)
        curseur, pages = page.curseur, pages + 1
        if page.termine:
            return refs, curseur, pages


def test_lecture_pagination_et_contenu(imports):
    nom = _ecrire(imports, "export.mbox", _mbox([_brut(i) for i in range(5)]))
    f = FournisseurMbox(nom, dossier=imports)
    refs, curseur, pages = _tout(f)
    assert len(refs) == 5 and pages == 3
    objets = [normalisation.normaliser(f.lire_message(r)).objet for r in refs]
    assert objets == [f"message {i}" for i in range(5)]
    assert f.lister_boites()[0].fournisseur == "mbox" and f.lister_dossiers()[0].id == nom


def test_reprise_par_curseur_dans_un_nouvel_objet(imports):
    nom = _ecrire(imports, "export.mbox", _mbox([_brut(i) for i in range(5)]))
    premiere = FournisseurMbox(nom, dossier=imports).synchroniser(nom, None, limite=2)
    assert not premiere.termine
    reste, _, _ = _tout(FournisseurMbox(nom, dossier=imports), curseur=premiere.curseur)
    f = FournisseurMbox(nom, dossier=imports)
    assert [normalisation.normaliser(f.lire_message(r)).objet for r in list(premiere.ajouts) + reste] == [
        f"message {i}" for i in range(5)
    ]


def test_ligne_from_dans_le_corps_ne_coupe_pas_et_mboxrd_desecape(imports):
    corps = "Bonjour\n\nFrom le début, je dis que\n>From ceci est échappé\n>>From deux fois\nfin"
    nom = _ecrire(
        imports,
        "e.mbox",
        _sep(0)
        + b"Subject: a\nFrom: x@example.test\nTo: y@example.test\n\n"
        + corps.replace("\n>From", "\n>From").encode()
        + b"\n\n"
        + _sep(1)
        + b"Subject: b\n\nautre\n\n",
    )
    f = FournisseurMbox(nom, dossier=imports)
    refs, _, _ = _tout(f)
    assert len(refs) == 2
    texte = f.lire_message(refs[0]).octets.decode()
    assert "\nFrom le début" in texte and "\nFrom ceci est échappé" in texte and "\n>From deux fois" in texte


def test_style_takeout_crlf_et_asctime(imports):
    contenu = (
        b"From 1693445670000@xxx Mon Mar 01 00:00:00 +0000 2021\r\nSubject: un\r\n\r\ncorps\r\n\r\n"
        b"From user@host Tue Mar  2 10:11:12 2021\r\nSubject: deux\r\n\r\ncorps2\r\n"
    )
    nom = _ecrire(imports, "t.mbox", contenu)
    f = FournisseurMbox(nom, dossier=imports)
    refs, _, _ = _tout(f)
    assert [normalisation.normaliser(f.lire_message(r)).objet for r in refs] == ["un", "deux"]


def test_fichier_vide_et_fichier_sans_separateur(imports):
    assert _tout(FournisseurMbox(_ecrire(imports, "v.mbox", b""), dossier=imports))[0] == []
    f = FournisseurMbox(_ecrire(imports, "x.mbox", b"ceci n'est pas une boite mbox\n"), dossier=imports)
    with pytest.raises(ErreurCourriel) as exc:
        f.synchroniser("x.mbox", None)
    assert exc.value.code == "REJ-COURRIEL-MBOX-FORMAT"


@pytest.mark.parametrize(
    "nom",
    [
        "../export.mbox",
        "/etc/passwd",
        "a/b.mbox",
        "export.txt",
        "export.mbox.zip",
        ".mbox",
        "x\x00.mbox",
        "..mbox",
        "a b/../c.mbox",
        "",
        None,
        5,
        "e" * 200 + ".mbox",
    ],
)
def test_nom_invalide_refuse(imports, nom):
    with pytest.raises(ErreurCourriel) as exc:
        FournisseurMbox(nom, dossier=imports)
    assert exc.value.code == "REJ-COURRIEL-MBOX-NOM-INVALIDE"


def test_absent_lien_symbolique_et_dossier_refuses(imports, tmp_path):
    with pytest.raises(ErreurCourriel) as exc:
        FournisseurMbox("absent.mbox", dossier=imports)
    assert exc.value.code == "REJ-COURRIEL-MBOX-ABSENT"
    secret = tmp_path / "secret.mbox"
    secret.write_bytes(_mbox([_brut(1)]))
    os.symlink(secret, imports / "lien.mbox")
    with pytest.raises(ErreurCourriel) as exc:
        FournisseurMbox("lien.mbox", dossier=imports)
    assert exc.value.code == "REJ-COURRIEL-MBOX-ABSENT"
    (imports / "repertoire.mbox").mkdir()
    with pytest.raises(ErreurCourriel) as exc:
        FournisseurMbox("repertoire.mbox", dossier=imports)
    assert exc.value.code == "REJ-COURRIEL-MBOX-ABSENT"
    lien_dossier = tmp_path / "lien-dossier"
    os.symlink(imports, lien_dossier)
    _ecrire(imports, "ok.mbox", _mbox([_brut(1)]))
    with pytest.raises(ErreurCourriel):
        FournisseurMbox("ok.mbox", dossier=lien_dossier)


def test_fichier_trop_gros_refuse(imports):
    nom = _ecrire(imports, "gros.mbox", _mbox([_brut(i) for i in range(5)]))
    with pytest.raises(ErreurCourriel) as exc:
        FournisseurMbox(nom, dossier=imports, limites=LimitesMbox(fichier_max=100))
    assert exc.value.code == "REJ-COURRIEL-MBOX-TROP-GROS"


def test_message_trop_gros_reference_mais_jamais_charge(imports):
    enorme = b"Subject: gros\n\n" + b"x" * 5000 + b"\n"
    nom = _ecrire(imports, "m.mbox", _sep(0) + enorme + b"\n" + _sep(1) + b"Subject: petit\n\nok\n\n")
    f = FournisseurMbox(nom, dossier=imports, limites=LimitesMbox(message_max=1000))
    refs, _, _ = _tout(f)
    assert len(refs) == 2
    with pytest.raises(ErreurCourriel) as exc:
        f.lire_message(refs[0])
    assert exc.value.code == "REJ-COURRIEL-MESSAGE-TROP-GROS"
    assert f.lire_message(refs[1]).octets.startswith(b"Subject: petit")


def test_ligne_geante_sans_fin_de_ligne_bornee(imports):
    nom = _ecrire(
        imports,
        "l.mbox",
        _sep(0) + b"Subject: s\n\n" + b"A" * (3 * 1024 * 1024) + b"\n\n" + _sep(1) + b"Subject: t\n\nok\n",
    )
    f = FournisseurMbox(nom, dossier=imports, limites=LimitesMbox(message_max=1024 * 1024))
    refs, _, _ = _tout(f)
    assert len(refs) == 2


def test_trop_de_messages(imports):
    nom = _ecrire(imports, "n.mbox", _mbox([_brut(i) for i in range(6)]))
    f = FournisseurMbox(nom, dossier=imports, limites=LimitesMbox(messages_max=4))
    with pytest.raises(ErreurCourriel) as exc:
        _tout(f, limite=10)
    assert exc.value.code == "REJ-COURRIEL-MBOX-TROP-GROS"


# -- .mbox.gz : bombes de décompression
# ---------------------------------------------------------------------------------
def test_gzip_valide_lu_et_repris(imports):
    nom = _ecrire(imports, "e.mbox.gz", gzip.compress(_mbox([_brut(i) for i in range(5)])))
    f = FournisseurMbox(nom, dossier=imports)
    premiere = f.synchroniser(nom, None, limite=2)
    reste, _, _ = _tout(FournisseurMbox(nom, dossier=imports), curseur=premiere.curseur)
    objets = [normalisation.normaliser(f.lire_message(r)).objet for r in list(premiere.ajouts) + reste]
    assert objets == [f"message {i}" for i in range(5)]


def test_bombe_de_decompression_par_ratio(imports):
    bombe = gzip.compress(_sep(0) + b"Subject: bombe\n\n" + b"\x00" * (20 * 1024 * 1024), 9)
    assert len(bombe) < 100_000
    nom = _ecrire(imports, "b.mbox.gz", bombe)
    f = FournisseurMbox(
        nom, dossier=imports, limites=LimitesMbox(ratio_seuil=64 * 1024, ratio_max=50, message_max=10**9)
    )
    with pytest.raises(ErreurCourriel) as exc:
        _tout(f)
    assert exc.value.code == "REJ-COURRIEL-MBOX-BOMBE"


def test_bombe_de_decompression_par_taille_totale(imports):
    nom = _ecrire(imports, "b.mbox.gz", gzip.compress(_mbox([_brut(i, "x" * 2000) for i in range(50)])))
    f = FournisseurMbox(nom, dossier=imports, limites=LimitesMbox(decompresse_max=20_000, ratio_max=10**9))
    with pytest.raises(ErreurCourriel) as exc:
        _tout(f)
    assert exc.value.code == "REJ-COURRIEL-MBOX-BOMBE"


def test_gzip_corrompu_refuse_proprement(imports):
    brut = gzip.compress(_mbox([_brut(i) for i in range(3)]))
    nom = _ecrire(imports, "c.mbox.gz", brut[:40] + b"\xff" * 30 + brut[70:])
    with pytest.raises(ErreurCourriel) as exc:
        _tout(FournisseurMbox(nom, dossier=imports))
    assert exc.value.code == "REJ-COURRIEL-MBOX-FORMAT"


def test_gzip_compresse_trop_gros(imports):
    nom = _ecrire(imports, "g.mbox.gz", gzip.compress(_mbox([_brut(1)])))
    with pytest.raises(ErreurCourriel) as exc:
        FournisseurMbox(nom, dossier=imports, limites=LimitesMbox(compresse_max=10))
    assert exc.value.code == "REJ-COURRIEL-MBOX-TROP-GROS"


# -- curseur --------------------------------------------------------------------------------------
def test_fichier_modifie_depuis_le_curseur_perime(imports):
    nom = _ecrire(imports, "e.mbox", _mbox([_brut(i) for i in range(4)]))
    f = FournisseurMbox(nom, dossier=imports)
    page = f.synchroniser(nom, None, limite=2)
    (imports / nom).write_bytes(_mbox([_brut(i) for i in range(9)]))
    with pytest.raises(ErreurCourriel) as exc:
        f.synchroniser(nom, page.curseur)
    assert exc.value.code == "REJ-COURRIEL-CURSEUR-EXPIRE"


@pytest.mark.parametrize(
    "donnees",
    [
        {"o": -1, "s": 5, "n": 0},
        {"o": "1", "s": 5, "n": 0},
        {"o": 3, "s": "x", "n": 0},
        {"o": 3, "s": 5},
        {"o": 0, "s": 5, "n": -1},
    ],
)
def test_curseur_mbox_mal_forme(imports, donnees):
    nom = _ecrire(imports, "e.mbox", _mbox([_brut(1)]))
    with pytest.raises(ErreurCourriel) as exc:
        FournisseurMbox(nom, dossier=imports).synchroniser(nom, encoder_curseur("mbox", donnees))
    assert exc.value.code == "REJ-COURRIEL-CURSEUR-INVALIDE"


def test_decalage_qui_ne_tombe_pas_sur_un_message(imports):
    contenu = _mbox([_brut(i) for i in range(3)])
    nom = _ecrire(imports, "e.mbox", contenu)
    with pytest.raises(ErreurCourriel) as exc:
        FournisseurMbox(nom, dossier=imports).synchroniser(
            nom, encoder_curseur("mbox", {"o": 25, "s": len(contenu), "n": 0})
        )
    assert exc.value.code == "REJ-COURRIEL-CURSEUR-INVALIDE"


def test_dossier_autre_que_le_fichier_et_reference_invalide(imports):
    nom = _ecrire(imports, "e.mbox", _mbox([_brut(1)]))
    f = FournisseurMbox(nom, dossier=imports)
    with pytest.raises(ErreurCourriel):
        f.synchroniser("autre.mbox", None)
    for ref in ("x", "1:2:3", "-1:4", "1:-4", "../x"):
        with pytest.raises(ErreurCourriel):
            f.lire_message(RefMessage(ref, nom))


# -- lecture seule --------------------------------------------------------------------------------
def test_aucune_ecriture_dans_le_dossier_et_envoi_refuse(imports):
    contenu = _mbox([_brut(i) for i in range(3)])
    nom = _ecrire(imports, "e.mbox", contenu)
    avant = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in imports.iterdir()}
    f = FournisseurMbox(nom, dossier=imports)
    _tout(f)
    for r in _tout(f)[0]:
        f.lire_message(r)
    assert {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in imports.iterdir()} == avant
    with pytest.raises(ErreurCourriel) as exc:
        f.envoyer_brouillon(object(), object())
    assert exc.value.code == "REJ-COURRIEL-ENVOI-NON-SUPPORTE"


def test_nom_de_piece_d_un_export_ne_sert_jamais_de_chemin(imports, tmp_path):
    brut = dbl.courriel_brut(pieces=[("../../../../tmp/evil.sh", "text/plain", b"echo pwn\n")])
    nom = _ecrire(imports, "e.mbox", _mbox([brut]))
    f = FournisseurMbox(nom, dossier=imports)
    (ref,) = _tout(f)[0]
    m = normalisation.normaliser(MessageBrut(ref.ref, ref.dossier, f.lire_message(ref).octets))
    assert m.pieces_jointes[0].nom == "evil.sh" and m.pieces_jointes[0].dangereux
    assert not (tmp_path / "evil.sh").exists() and not os.path.exists("/tmp/evil.sh")
