"""Validation fictive et en lecture seule du bundle OCR opt-in."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from opsys import ocr_profil

FICTIF = True


def _record_row(path: str, data: bytes) -> tuple[str, str, str]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
    return path, "sha256=" + digest, str(len(data))


def _wheel_bytes(membres: dict[str, bytes], *, record_edit=None, extra: dict[str, bytes] | None = None) -> bytes:
    entries = dict(membres)
    entries.update(extra or {})
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    rows = [_record_row(path, data) for path, data in entries.items()]
    if record_edit is not None:
        rows = record_edit(rows)
    record_path = "pypdfium2-5.13.0.dist-info/RECORD"
    for row in rows:
        writer.writerow(row)
    writer.writerow((record_path, "", ""))
    entries[record_path] = record.getvalue().encode("utf-8")
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        for path, data in entries.items():
            wheel.writestr(path, data)
    return sortie.getvalue()


def _bundle(tmp_path, monkeypatch, *, omissions=(), extras=None, mode=0o700, model=b"modele-fictif"):
    bundle = tmp_path / "profil-ocr-fictif"
    rasterizer = bundle / "rasterizer"
    tessdata = bundle / "tessdata"
    rasterizer.mkdir(parents=True, mode=0o700)
    tessdata.mkdir(mode=0o700)
    membres = {
        "pypdfium2/__init__.py": b"# pypdfium2 fictif\n",
        "pypdfium2/version.json": b'{"major":5,"minor":13,"patch":0}\n',
        "pypdfium2_raw/__init__.py": b"# raw fictif\n",
        "pypdfium2_raw/version.json": b'{"major":153,"minor":0,"build":7999,"patch":0}\n',
        "pypdfium2_raw/libpdfium.so": "binaire fictif non exécutable".encode(),
        "pypdfium2_cfg/__init__.py": b"# cfg fictif\n",
        "pypdfium2_cli/__init__.py": b"# autre package du wheel, pas extrait\n",
    }
    present = {path: data for path, data in membres.items() if path not in omissions}
    wheel_data = _wheel_bytes(present, extra={"pypdfium2-5.13.0.dist-info/WHEEL": b"wheel fictif"})
    (bundle / "wheel.whl").write_bytes(wheel_data)
    for path, data in present.items():
        if path.startswith(("pypdfium2/", "pypdfium2_raw/", "pypdfium2_cfg/")):
            target = rasterizer / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    for path, data in (extras or {}).items():
        target = rasterizer / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (tessdata / "fra.traineddata").write_bytes(model)
    for path in bundle.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    for path in (bundle, rasterizer, tessdata):
        path.chmod(mode)
    monkeypatch.setattr(ocr_profil, "WHEEL_SHA256", hashlib.sha256(wheel_data).hexdigest())
    monkeypatch.setattr(ocr_profil, "PDFIUM_SHA256", hashlib.sha256(membres["pypdfium2_raw/libpdfium.so"]).hexdigest())
    monkeypatch.setattr(ocr_profil, "MODELE_SHA256", hashlib.sha256(model).hexdigest())
    return bundle, membres


def _refuser(action, *args, **kwargs):
    with pytest.raises(ocr_profil.OCRProfilErreur) as erreur:
        action(*args, **kwargs)
    assert erreur.value.code == "OCR_PROFIL_INDISPONIBLE"
    assert str(erreur.value) == "profil OCR indisponible"
    return erreur.value


def test_bundle_fictif_valide_retourne_seulement_hashs_relatives_rasterizer(tmp_path, monkeypatch):
    bundle, membres = _bundle(tmp_path, monkeypatch)

    mapping = ocr_profil.valider_bundle(bundle)

    assert set(mapping) == {
        "rasterizer/pypdfium2/__init__.py",
        "rasterizer/pypdfium2/version.json",
        "rasterizer/pypdfium2_raw/__init__.py",
        "rasterizer/pypdfium2_raw/version.json",
        "rasterizer/pypdfium2_raw/libpdfium.so",
        "rasterizer/pypdfium2_cfg/__init__.py",
    }
    assert set(mapping.values()) == {hashlib.sha256(membres[key]).hexdigest() for key in mapping_path_keys(mapping)}
    assert not any(key in mapping for key in ("wheel.whl", "tessdata/fra.traineddata"))
    assert (bundle / "rasterizer/pypdfium2_raw/libpdfium.so").read_bytes() == membres["pypdfium2_raw/libpdfium.so"]


def mapping_path_keys(mapping):
    return [key.removeprefix("rasterizer/") for key in mapping]


@pytest.mark.parametrize("mutant", [
    "wheel", "model", "package", "missing-package", "wheel-missing-package", "extra-package", "cache",
])
def test_bundle_altere_incomplet_ou_avec_cache_refuse(tmp_path, monkeypatch, mutant):
    bundle, _ = _bundle(
        tmp_path, monkeypatch,
        omissions=("pypdfium2_cfg/__init__.py",) if mutant == "wheel-missing-package" else (),
    )
    if mutant == "wheel":
        with (bundle / "wheel.whl").open("ab") as fichier:
            fichier.write(b"alteration")
    elif mutant == "model":
        (bundle / "tessdata/fra.traineddata").write_bytes(b"autre modele")
    elif mutant == "package":
        (bundle / "rasterizer/pypdfium2/__init__.py").write_bytes(b"autre contenu")
    elif mutant == "missing-package":
        (bundle / "rasterizer/pypdfium2_cfg/__init__.py").unlink()
    elif mutant == "extra-package":
        (bundle / "rasterizer/pypdfium2/extra.py").write_bytes(b"cache")
    else:
        (bundle / "rasterizer/pypdfium2/__pycache__").mkdir()

    erreur = _refuser(ocr_profil.valider_bundle, bundle)

    assert str(bundle) not in str(erreur)


@pytest.mark.parametrize("defaut", [
    "zip", "record-hash", "record-size", "record-duplicate", "unsafe-name", "record-missing",
])
def test_wheel_record_ferme_et_chemins_surs(tmp_path, monkeypatch, defaut):
    bundle, membres = _bundle(tmp_path, monkeypatch)
    path = "pypdfium2/__init__.py"
    wheel_path = bundle / "wheel.whl"
    if defaut == "zip":
        invalid = b"pas un zip"
        wheel_path.write_bytes(invalid)
        monkeypatch.setattr(ocr_profil, "WHEEL_SHA256", hashlib.sha256(invalid).hexdigest())
    else:
        def edit(rows):
            resultat = list(rows)
            index = next(i for i, row in enumerate(resultat) if row[0] == path)
            item = list(resultat[index])
            if defaut == "record-hash":
                item[1] = "sha256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            elif defaut == "record-size":
                item[2] = str(int(item[2]) + 1)
            elif defaut == "record-duplicate":
                resultat.append(tuple(item))
            elif defaut == "unsafe-name":
                item[0] = "../pypdfium2/__init__.py"
            elif defaut == "record-missing":
                resultat.pop(index)
                return resultat
            resultat[index] = tuple(item)
            return resultat
        wheel_data = _wheel_bytes(
            membres, record_edit=edit, extra={"pypdfium2-5.13.0.dist-info/WHEEL": b"wheel fictif"},
        )
        wheel_path.write_bytes(wheel_data)
        monkeypatch.setattr(ocr_profil, "WHEEL_SHA256", hashlib.sha256(wheel_data).hexdigest())

    _refuser(ocr_profil.valider_bundle, bundle)


@pytest.mark.parametrize("mode", [0o770, 0o707, 0o777])
def test_arbre_inscriptible_par_groupe_ou_autres_refuse(tmp_path, monkeypatch, mode):
    bundle, _ = _bundle(tmp_path, monkeypatch)
    target = bundle / "rasterizer/pypdfium2/__init__.py"
    target.chmod(mode)

    _refuser(ocr_profil.valider_bundle, bundle)


def test_symlink_dans_arbre_et_bundle_symlink_refuses(tmp_path, monkeypatch):
    bundle, _ = _bundle(tmp_path, monkeypatch)
    target = bundle / "rasterizer/pypdfium2/__init__.py"
    original = target.with_suffix(".saved")
    target.rename(original)
    target.symlink_to(original.name)

    _refuser(ocr_profil.valider_bundle, bundle)

    autre = tmp_path / "alias"
    autre.symlink_to(bundle, target_is_directory=True)
    _refuser(ocr_profil.valider_bundle, autre)


@pytest.mark.parametrize("path", ["relative", ".", "/"])
def test_chemin_non_absolu_ou_generique_refuse(path):
    _refuser(ocr_profil.valider_bundle, Path(path))


def test_bundle_layout_suppl_de_modele_et_objet_special_refuses(tmp_path, monkeypatch):
    bundle, _ = _bundle(tmp_path, monkeypatch)
    (bundle / "unexpected").write_text("supplément", encoding="utf-8")
    _refuser(ocr_profil.valider_bundle, bundle)
    (bundle / "unexpected").unlink()
    (bundle / "tessdata/autre.traineddata").write_bytes(b"autre")
    _refuser(ocr_profil.valider_bundle, bundle)
    (bundle / "tessdata/autre.traineddata").unlink()
    os.mkfifo(bundle / "rasterizer/fifo")

    _refuser(ocr_profil.valider_bundle, bundle)


@pytest.mark.parametrize("fichier,plafond,constant", [
    ("wheel.whl", 4 * 1024 * 1024, "WHEEL_SHA256"),
    ("tessdata/fra.traineddata", 2 * 1024 * 1024, "MODELE_SHA256"),
])
def test_borne_de_taille_precede_hash(tmp_path, monkeypatch, fichier, plafond, constant):
    bundle, _ = _bundle(tmp_path, monkeypatch)
    data = b"x" * (plafond + 1)
    (bundle / fichier).write_bytes(data)
    monkeypatch.setattr(ocr_profil, constant, hashlib.sha256(data).hexdigest())

    _refuser(ocr_profil.valider_bundle, bundle)


def test_parent_partage_non_sticky_refuse(tmp_path, monkeypatch):
    parent = tmp_path / "parent-ouvert"
    parent.mkdir(mode=0o777)
    bundle, _ = _bundle(parent, monkeypatch)
    parent.chmod(0o777)

    _refuser(ocr_profil.valider_bundle, bundle)


def test_mount_bundle_seul_chemin_court_accepte_avec_ancetres_surs(monkeypatch):
    vus = []

    def fake_stat(path, *, directory=None):
        vus.append((path, directory))
        return SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o755)

    monkeypatch.setattr(ocr_profil, "_stat", fake_stat)
    ocr_profil._verifier_chaine(Path("/bundle"))

    assert vus == [(Path("/"), True), (Path("/bundle"), True)]


def test_valide_bundle_sous_alias_fixe_bundle_avec_arbre_fictif(tmp_path, monkeypatch):
    bundle, _ = _bundle(tmp_path, monkeypatch)
    réel_entrees = ocr_profil._entrees_reelles
    réel_lire = ocr_profil._lire_fichier

    def traduire(path):
        return bundle / Path(path).relative_to(Path("/bundle"))

    monkeypatch.setattr(ocr_profil, "_verifier_chaine", lambda path: path == Path("/bundle"))
    monkeypatch.setattr(ocr_profil, "_entrees_reelles", lambda path: réel_entrees(traduire(path)))
    monkeypatch.setattr(ocr_profil, "_lire_fichier", lambda path, maximum: réel_lire(traduire(path), maximum))

    mapping = ocr_profil.valider_bundle(Path("/bundle"))

    assert "rasterizer/pypdfium2_raw/libpdfium.so" in mapping


@pytest.mark.parametrize("shape", ["depth", "entries"])
def test_arbre_scan_borne_en_profondeur_et_nombre(tmp_path, monkeypatch, shape):
    bundle, _ = _bundle(tmp_path, monkeypatch)
    if shape == "depth":
        target = bundle / "rasterizer" / ("/".join(["nested"] * 17))
        target.mkdir(parents=True)
    else:
        target = bundle / "rasterizer/pypdfium2"
        for index in range(260):
            (target / f"extra-{index}.txt").touch()

    _refuser(ocr_profil.valider_bundle, bundle)
