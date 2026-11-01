"""Dépôt sûr de l'ingestion d'onboarding : nom seul, liens refusés, types fermés, archive ZIP gardée, dédoublonnage
exact, idempotence par clé de mutation, quotas. Chaque refus a son cas négatif ; les fichiers sont fictifs."""

from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path

import ingestion_onboarding_qa as qa
import pytest
from sqlalchemy import select, text

from opsys import stockage
from opsys.ingestion_onboarding import codes, depot, service, taches
from opsys.ingestion_onboarding.codes import IngestionErreur
from opsys.stockage.schema import INGESTION_DOCUMENTS, INGESTION_TACHES

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
PDF = qa.pdf_texte("FACTURE\nNuméro : X-1\nDocument fictif")


@pytest.fixture
def instance(tmp_path, monkeypatch):
    return qa.preparer_instance(tmp_path, monkeypatch, fournisseur=False)


def _code(fonction, *args, **kwargs) -> str:
    with pytest.raises(IngestionErreur) as exc:
        fonction(*args, **kwargs)
    return exc.value.code


def _zip(membres, *, infos=()):
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as archive:
        for nom, octets in membres.items():
            archive.writestr(nom, octets)
        for info, octets in infos:
            archive.writestr(info, octets)
    return sortie.getvalue()


def _deposer(nom, octets, mutation="m-1"):
    qa.deposer_fichier(nom, octets)
    with stockage.transaction() as cnx:
        return service.deposer(cnx, "nathan", nom=nom, mutation_id=mutation)


# ------------------------------------------------------------------------------------------ lecture par nom
@pytest.mark.parametrize("nom", ["../evasion.pdf", "/etc/passwd.pdf", "sous/dossier.pdf", "fichier.exe", "", ".x.pdf",
                                 "a..b.pdf", 42, "nom\x00.pdf"])
def test_seul_un_nom_de_la_liste_fermee_est_lu(instance, nom):
    assert _code(depot.lire_depose, nom) == "REJ-ING-NOM-INVALIDE"


def test_fichier_absent_lien_symbolique_dossier_lien_trop_gros_vide(instance, tmp_path, monkeypatch):
    dossier = depot.dossier_depot()
    assert _code(depot.lire_depose, "absent.pdf") == "REJ-ING-FICHIER-ABSENT"
    cible = tmp_path / "hors-depot.pdf"
    cible.write_bytes(PDF)
    os.symlink(cible, dossier / "lien.pdf")
    assert _code(depot.lire_depose, "lien.pdf") == "REJ-ING-FICHIER-ABSENT"
    (dossier / "vide.pdf").write_bytes(b"")
    assert _code(depot.lire_depose, "vide.pdf") == "REJ-ING-FICHIER-VIDE"
    monkeypatch.setattr(depot, "SOURCE_MAX", 16)
    (dossier / "gros.pdf").write_bytes(PDF)
    assert _code(depot.lire_depose, "gros.pdf") == "REJ-ING-FICHIER-TROP-GROS"
    reel = tmp_path / "vrai-depot"
    reel.mkdir()
    lien_dossier = tmp_path / "depot-lien"
    os.symlink(reel, lien_dossier)
    assert _code(depot.lire_depose, "x.pdf", dossier=lien_dossier) == "REJ-ING-DOSSIER-INVALIDE"
    assert _code(depot.lire_depose, "x.pdf", dossier=tmp_path / "inexistant") == "REJ-ING-DOSSIER-INVALIDE"


def test_un_fichier_ordinaire_est_lu(instance):
    qa.deposer_fichier("facture.pdf", PDF)
    assert depot.lire_depose("facture.pdf") == PDF


# ------------------------------------------------------------------------------------------------- types
@pytest.mark.parametrize(("nom", "octets", "attendu"), [
    ("f.pdf", PDF, ("pdf", None)),
    ("f.PDF", PDF, ("pdf", None)),
    ("p.png", b"\x89PNG\r\n\x1a\n" + b"0" * 8, ("png", None)),
    ("p.jpeg", b"\xff\xd8\xff\xe0" + b"0" * 8, ("jpeg", None)),
    ("t.txt", "Facture fictive éàç\n".encode("cp1252"), ("txt", None)),
    ("c.csv", "\ufeffNom,Courriel\n".encode("utf-8"), ("csv", None)),
    ("c.csv", "Nom\n".encode("utf-16"), ("csv", None)),
    ("faux.pdf", b"du texte", (None, "REJ-ING-TYPE-INCOHERENT")),
    ("pdf.txt", PDF[:5] + b"\x00\x01", (None, "REJ-ING-TYPE-INCOHERENT")),
    ("x.xlsx", _zip({"autre.txt": b"x"}), (None, "REJ-ING-TYPE-INCOHERENT")),
    ("x.exe", b"MZ", (None, "REJ-ING-TYPE-NON-ACCEPTE")),
    ("sans_extension", b"x", (None, "REJ-ING-TYPE-NON-ACCEPTE")),
])
def test_signature_et_extension_doivent_concorder(nom, octets, attendu):
    type_detecte, refus = depot.detecter_type(nom, octets)
    assert (type_detecte, refus and refus["code"]) == attendu


def test_un_xlsx_minimal_est_reconnu():
    classeur = _zip({"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<workbook/>"})
    assert depot.detecter_type("clients.xlsx", classeur) == ("xlsx", None)


# ----------------------------------------------------------------------------------------------- archive
def _lien(nom):
    info = zipfile.ZipInfo(nom)
    info.create_system = 3
    info.external_attr = (0o120777 << 16)
    return info, b"/etc/passwd"


@pytest.mark.parametrize(("membres", "infos", "code"), [
    ({"../evasion.txt": b"x"}, (), "REJ-ING-ZIP-TRAVERSEE"),
    ({"a/../../evasion.txt": b"x"}, (), "REJ-ING-ZIP-TRAVERSEE"),
    ({"/absolu.txt": b"x"}, (), "REJ-ING-ZIP-TRAVERSEE"),
    ({"dos\\windows.txt": b"x"}, (), "REJ-ING-ZIP-TRAVERSEE"),
    ({"C:/disque.txt": b"x"}, (), "REJ-ING-ZIP-TRAVERSEE"),
    ({}, (_lien("lien.txt"),), "REJ-ING-ZIP-LIEN"),
    ({"Facture.txt": b"x", "facture.TXT": b"y"}, (), "REJ-ING-ZIP-NOM-REPETE"),
    ({"bombe.txt": b"0" * (2 * 1024 * 1024)}, (), "REJ-ING-ZIP-BOMBE"),
])
def test_une_archive_hostile_est_refusee_en_entier(membres, infos, code):
    assert _code(depot.deplier, "depot.zip", _zip(membres, infos=infos)) == code


def test_bornes_de_l_archive_nombre_et_total(monkeypatch):
    monkeypatch.setattr(depot, "MEMBRES_MAX", 2)
    assert _code(depot.deplier, "d.zip", _zip({"a.txt": b"a", "b.txt": b"b", "c.txt": b"c"})) == "REJ-ING-ZIP-BOMBE"
    monkeypatch.setattr(depot, "MEMBRES_MAX", 500)
    monkeypatch.setattr(depot, "TOTAL_DECOMPRESSE_MAX", 10)
    assert _code(depot.deplier, "d.zip", _zip({"a.txt": b"a" * 6, "b.txt": b"b" * 6})) == "REJ-ING-ZIP-BOMBE"


def test_archive_illisible_ou_qui_n_en_est_pas_une():
    assert _code(depot.deplier, "d.zip", b"PK\x03\x04 tronquee") == "REJ-ING-ZIP-ILLISIBLE"
    assert _code(depot.deplier, "d.zip", b"pas une archive") == "REJ-ING-TYPE-INCOHERENT"


def _marquer_chiffre(archive: bytes, nom: bytes) -> bytes:
    """Pose le drapeau « chiffré » (bit 0) d'un membre, dans l'en-tête local et le répertoire central."""
    octets = bytearray(archive)
    for signature, decalage_drapeau, decalage_nom in ((b"PK\x03\x04", 6, 30), (b"PK\x01\x02", 8, 46)):
        position = octets.find(signature)
        while position != -1:
            if octets[position + decalage_nom:position + decalage_nom + len(nom)] == nom:
                octets[position + decalage_drapeau] |= 0x1
            position = octets.find(signature, position + 4)
    return bytes(octets)


def test_les_refus_de_membre_n_empechent_pas_les_autres(monkeypatch):
    archive = _marquer_chiffre(_zip({
        "bon.txt": b"FACTURE fictive", "imbrique.zip": _zip({"x.txt": b"x"}), "outil.exe": b"MZ",
        "__MACOSX/._bon.txt": b"\x00", "dossier/.DS_Store": b"\x00", "chiffre.txt": b"contenu"}), b"chiffre.txt")
    membres, resume = depot.deplier("depot.zip", archive)
    assert {m.nom: (m.type_detecte, m.refus and m.refus["code"]) for m in membres} == {
        "bon.txt": ("txt", None), "imbrique.zip": (None, "REJ-ING-ZIP-IMBRIQUE"),
        "outil.exe": (None, "REJ-ING-TYPE-NON-ACCEPTE"), "chiffre.txt": (None, "REJ-ING-ZIP-CHIFFRE")}
    assert resume == {"type_source": "zip", "ignores": 2}
    monkeypatch.setattr(depot, "MEMBRE_MAX", 4)
    [gros] = depot.deplier("d.zip", _zip({"gros.txt": b"12345"}))[0]
    assert gros.refus["code"] == "REJ-ING-FICHIER-TROP-GROS" and gros.octets is None


# --------------------------------------------------------------------------------------------- service
def test_depot_dedoublonne_exactement_dans_le_lot_et_entre_les_lots(instance):
    archive = _zip({"a.txt": b"FACTURE A fictive", "copie/a.txt": b"FACTURE A fictive", "b.txt": b"FACTURE B"})
    lot = _deposer("depot.zip", archive)
    assert lot["compteurs"]["documents"] == {"EN_ATTENTE": 2, "DOUBLON": 1}
    assert lot["compteurs"]["taches"] == {"EN_ATTENTE": 2 * len(taches.ETAPES)}
    second = _deposer("seul.txt", b"FACTURE B", mutation="m-2")
    assert second["compteurs"]["documents"] == {"DOUBLON": 1} and second["statut"] == "TERMINE"
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(INGESTION_DOCUMENTS).order_by(INGESTION_DOCUMENTS.c.cree_le)).mappings().all()
    originaux = {ligne["sha256"]: ligne["document_id"] for ligne in lignes if ligne["chiffre"] is not None}
    for ligne in lignes:
        if ligne["statut"] == "DOUBLON":
            assert ligne["doublon_de"] == originaux[ligne["sha256"]] and ligne["chiffre"] is None


def test_le_contenu_est_chiffre_au_repos(instance):
    _deposer("a.txt", b"FACTURE CONTENU-SECRET-FICTIF")
    brut = Path(stockage.url_base().removeprefix("sqlite:///")).read_bytes()
    assert b"CONTENU-SECRET-FICTIF" not in brut


def test_meme_cle_meme_fichier_rejoue_autre_fichier_refuse(instance):
    premier = _deposer("a.txt", b"FACTURE fictive")
    rejeu = _deposer("a.txt", b"FACTURE fictive")
    assert rejeu["rejeu"] is True and rejeu["lot_id"] == premier["lot_id"]
    qa.deposer_fichier("a.txt", b"FACTURE autre")
    with stockage.transaction() as cnx:
        assert _code(service.deposer, cnx, "nathan", nom="a.txt", mutation_id="m-1") == "REJ-ING-MUTATION-CONFLIT"
        assert _code(service.deposer, cnx, "nathan", nom="a.txt", mutation_id="clé invalide") == \
            "REJ-ING-MUTATION-INVALIDE"
        assert _code(service.deposer, cnx, "", nom="a.txt", mutation_id="m-9") == "REJ-ING-ACTEUR-INVALIDE"


def test_quotas_de_lots_de_documents_et_d_octets(instance, monkeypatch):
    monkeypatch.setitem(taches.QUOTAS, "lots_en_cours", 1)
    _deposer("a.txt", b"FACTURE a")
    qa.deposer_fichier("b.txt", b"FACTURE b")
    with stockage.transaction() as cnx:
        assert _code(service.deposer, cnx, "nathan", nom="b.txt", mutation_id="m-2") == "REJ-ING-QUOTA-LOTS"
    monkeypatch.setitem(taches.QUOTAS, "lots_en_cours", 8)
    monkeypatch.setitem(taches.QUOTAS, "documents_par_lot", 1)
    qa.deposer_fichier("deux.zip", _zip({"x.txt": b"x", "y.txt": b"y"}))
    with stockage.transaction() as cnx:
        assert _code(service.deposer, cnx, "nathan", nom="deux.zip", mutation_id="m-3") == "REJ-ING-QUOTA-DOCUMENTS"
    monkeypatch.setitem(taches.QUOTAS, "documents_par_lot", 500)
    monkeypatch.setitem(taches.QUOTAS, "octets_par_lot", 4)
    with stockage.transaction() as cnx:
        assert _code(service.deposer, cnx, "nathan", nom="b.txt", mutation_id="m-4") == "REJ-ING-QUOTA-OCTETS"
    monkeypatch.setitem(taches.QUOTAS, "octets_par_lot", 64)
    monkeypatch.setitem(taches.QUOTAS, "documents_total", 1)
    with stockage.transaction() as cnx:
        assert _code(service.deposer, cnx, "nathan", nom="b.txt", mutation_id="m-5") == "REJ-ING-QUOTA-OCTETS"


def test_archive_vide_et_cle_absente_ne_creent_rien(instance, monkeypatch):
    qa.deposer_fichier("vide.zip", _zip({}))
    with stockage.transaction() as cnx:
        assert _code(service.deposer, cnx, "nathan", nom="vide.zip", mutation_id="m-1") == "REJ-ING-LOT-VIDE"
    monkeypatch.delenv("OPSYS_INGESTION_CLE")
    qa.deposer_fichier("a.txt", b"FACTURE a")
    with stockage.transaction() as cnx:
        assert _code(service.deposer, cnx, "nathan", nom="a.txt", mutation_id="m-2") == "REJ-ING-CLE-INDISPONIBLE"
        assert cnx.execute(select(INGESTION_TACHES)).first() is None


def test_le_journal_est_append_only(instance):
    _deposer("a.txt", b"FACTURE a")
    with pytest.raises(Exception, match="immuable"), stockage.transaction() as cnx:
        cnx.execute(text("UPDATE ingestion_journal SET evenement = 'efface'"))
    with pytest.raises(Exception, match="immuable"), stockage.transaction() as cnx:
        cnx.execute(text("DELETE FROM ingestion_journal"))


def test_la_retrogradation_est_refusee_quand_des_donnees_existent(instance):
    from alembic import command

    _deposer("a.txt", b"FACTURE a")
    config = stockage._config()
    with stockage.moteur().begin() as cnx, pytest.raises(RuntimeError, match="rétrogradation refusée"):
        config.attributes["connection"] = cnx
        command.downgrade(config, "0037")


def test_la_retrogradation_sur_tables_vides_retire_tout(tmp_path, monkeypatch):
    from alembic import command

    url = f"sqlite:///{tmp_path / 'vide.db'}"
    stockage.migrer(url)
    config = stockage._config()
    with stockage.moteur(url).begin() as cnx:
        config.attributes["connection"] = cnx
        command.downgrade(config, "0037")
    with stockage.moteur(url).connect() as cnx:
        tables = {r[0] for r in cnx.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert not {t for t in tables if t.startswith("ingestion_")}
    assert stockage.revision_courante(url) == "0037"


def test_le_catalogue_des_codes_est_ferme_et_documente():
    doc = (RACINE / "docs" / "architecture" / "INGESTION-ONBOARDING.md").read_text(encoding="utf-8")
    for code in codes.CODES_ING:
        assert f"`{code}`" in doc, code
    assert len(set(codes.CODES_ING)) == len(codes.CODES_ING)
    with pytest.raises(ValueError):
        codes.construire_verdict("REJ-ING-INVENTE")
    sources = "\n".join(p.read_text(encoding="utf-8") for p in (RACINE / "src/opsys/ingestion_onboarding").glob("*.py"))
    utilises = set(re.findall(r'"(REJ-ING-[A-Z-]+)"', sources))
    assert utilises <= set(codes.CODES_ING), utilises - set(codes.CODES_ING)
