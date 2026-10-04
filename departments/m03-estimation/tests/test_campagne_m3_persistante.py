"""Régression autonome du reçu durable M3 entre deux interpréteurs Python."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_RACINE = _TESTS.parents[2]
_M3_SRC = _RACINE / "departments/m03-estimation/src"
_OUTILS = _RACINE / "departments/m03-estimation/tests/outils_preuve"
if str(_OUTILS) not in sys.path:
    sys.path.insert(0, str(_OUTILS))

from campagne_m3 import CampagneM3, EmpreinteEntrees, SpecificationExecution  # noqa: E402

_TIMEOUT_SECONDES = 30
_CODE_PYTHON = (
    "from decimal import Decimal\n"
    "from m3_estimation.devis_durable import prix_depuis_cout\n"
    "prix = prix_depuis_cout(Decimal('15.50'), Decimal('0.25'))\n"
    "assert prix == Decimal('19.38')\n"
    "print(prix)\n"
)


def _empreinte_environnement(environnement: dict[str, str]) -> str:
    canon = json.dumps(sorted(environnement.items()), separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def _specification() -> tuple[SpecificationExecution, dict[str, str]]:
    """Spécifie la commande réelle avec le même environnement exact dans les deux processus."""
    environnement = {
        "PYTHONPATH": str(_M3_SRC),
        "PYTHONHASHSEED": "0",
    }
    commande = (sys.executable, "-B", "-c", _CODE_PYTHON)
    specification = SpecificationExecution(
        outil="m3_estimation.devis_durable.prix_depuis_cout",
        scenario="nominal",
        commande=commande,
        argv=commande,
        cwd=str(_RACINE.resolve()),
        python=f"{sys.executable} | {sys.version}",
        environnement_sha256=_empreinte_environnement(environnement),
        options_pytest=(),
        collecte="departments/m03-estimation/src/m3_estimation/devis_durable.py",
        environnement_execution=tuple(sorted(environnement.items())),
    )
    return specification, environnement


def _capturer_sources_m3() -> EmpreinteEntrees:
    """Capture le reçu, son test, le calcul appelé et son import M3 direct."""
    paquet = _M3_SRC / "m3_estimation"
    return EmpreinteEntrees.capturer(
        {
            "departments/m03-estimation/tests/test_campagne_m3_persistante.py": Path(
                __file__
            ).resolve(),
            "outils_preuve/campagne_m3.py": _OUTILS / "campagne_m3.py",
            "m3_estimation/__init__.py": paquet / "__init__.py",
            "m3_estimation/devis_durable.py": paquet / "devis_durable.py",
            "m3_estimation/verdicts.py": paquet / "verdicts.py",
        }
    )


def _executer_phase(phase: str) -> None:
    if phase not in {"premier", "reprise"}:
        raise ValueError(f"phase inconnue: {phase}")

    identifiant = os.environ["M3_CAMPAGNE_RUN_ID"]
    dossier_artefacts = Path(os.environ["M3_CAMPAGNE_PREUVES"])
    campagne = CampagneM3(
        dossier_artefacts=dossier_artefacts,
        identifiant=identifiant,
    )
    specification, environnement = _specification()
    assert campagne.dossier_persistance is not None
    marqueur = campagne.dossier_persistance / "reprise-cross-processus.json"

    acces = campagne.obtenir_ou_lancer_commande(
        specification,
        _capturer_sources_m3,
        environnement=environnement,
    )
    assert acces.recu_durable is not None
    recu = Path(acces.recu_durable)
    assert recu.is_file()
    octets_recu = recu.read_bytes()
    objet = json.loads(octets_recu)
    env_sha256 = _empreinte_environnement(environnement)

    assert objet["schema"] == 2
    assert objet["identifiant_campagne"] == identifiant
    assert objet["cle"] == acces.preuve.cle
    assert objet["specification"]["environnement_sha256"] == env_sha256
    assert objet["commande"] == list(specification.commande)
    assert objet["specification"]["python"].startswith(sys.executable + " | ")
    assert objet["retour"] == acces.preuve.retour == 0
    assert objet["stdout"] == acces.preuve.stdout == "19.38\n"
    assert isinstance(objet["stderr"], str)
    assert objet["entrees_sha256"] == acces.preuve.entrees_sha256
    assert objet["avant"]["sha256"] == acces.preuve.avant.sha256
    assert objet["apres"]["sha256"] == acces.preuve.apres.sha256
    assert acces.preuve.nettoyage_prouve is True

    empreinte_recu = hashlib.sha256(octets_recu).hexdigest()
    if phase == "premier":
        assert not marqueur.exists(), "le marqueur doit être absent avant la première commande"
        assert acces.processus_lance_ici is True
        marqueur.write_text(
            json.dumps(
                {
                    "cle": acces.preuve.cle,
                    "retour": acces.preuve.retour,
                    "recu": recu.name,
                    "recu_sha256_octets": empreinte_recu,
                    "environment_sha256": env_sha256,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    else:
        assert marqueur.is_file(), "la première commande n'a pas persisté son marqueur"
        original = json.loads(marqueur.read_text(encoding="utf-8"))
        assert acces.processus_lance_ici is False
        assert acces.preuve.cle == original["cle"]
        assert acces.preuve.retour == original["retour"] == 0
        assert recu.name == original["recu"]
        assert empreinte_recu == original["recu_sha256_octets"]
        assert original["environment_sha256"] == env_sha256


def test_reprise_exacte_du_meme_outil_sur_deux_processus_python(tmp_path):
    identifiant = f"m3-prix-transprocessus-{uuid.uuid4().hex}"
    dossier_artefacts = tmp_path / "campagnes"
    environnement = os.environ.copy()
    environnement.pop("PYTEST_CURRENT_TEST", None)
    environnement["M3_CAMPAGNE_RUN_ID"] = identifiant
    environnement["M3_CAMPAGNE_PREUVES"] = str(dossier_artefacts)

    for phase in ("premier", "reprise"):
        resultat = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), phase],
            cwd=_RACINE,
            env=environnement,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDES,
            check=False,
        )
        assert resultat.returncode == 0, (
            f"phase {phase!r} en échec (code {resultat.returncode})\n"
            f"stdout:\n{resultat.stdout}\nstderr:\n{resultat.stderr}"
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_campagne_m3_persistante.py {premier|reprise}")
    _executer_phase(sys.argv[1])
