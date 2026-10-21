"""Registre hermétique de preuves réelles pour une campagne M3.

Une entrée ne représente qu'une invocation effectivement exécutée, avec la fermeture
complète de ses fichiers, ses options et ses empreintes avant/après. Les consommateurs
peuvent explicitement obtenir la même preuve si sa clé est identique; ils ne peuvent
pas présenter cette lecture comme un nouveau processus.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol

_IGNORES = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}


@dataclass(frozen=True)
class EntreeEmpreinte:
    chemin: str
    mode: int
    sha256: str
    est_dossier: bool = False
    lien: str | None = None


@dataclass(frozen=True)
class EmpreinteEntrees:
    entrees: tuple[EntreeEmpreinte, ...]
    sha256: str

    @classmethod
    def capturer(cls, racines: Mapping[str, Path]) -> EmpreinteEntrees:
        entrees: list[EntreeEmpreinte] = []

        def visiter(nom: str, chemin: Path, ancetres: frozenset[Path]) -> None:
            if chemin.name in _IGNORES:
                return
            lien = str(chemin.readlink()) if chemin.is_symlink() else None
            cible = chemin.resolve(strict=True)
            info = cible.stat()
            mode = stat.S_IMODE(info.st_mode)
            if cible.is_dir():
                if cible in ancetres:
                    raise ValueError(f"cycle de répertoire dans la fermeture: {nom}")
                entrees.append(
                    EntreeEmpreinte(nom.rstrip("/") + "/", mode, "", True, lien)
                )
                prochains = ancetres | {cible}
                for enfant in sorted(cible.iterdir(), key=lambda item: item.name):
                    visiter(f"{nom.rstrip('/')}/{enfant.name}", enfant, prochains)
                return
            contenu = cible.read_bytes()
            entrees.append(
                EntreeEmpreinte(
                    nom, mode, hashlib.sha256(contenu).hexdigest(), False, lien
                )
            )

        for nom, chemin in sorted(racines.items()):
            visiter(nom, Path(chemin), frozenset())
        canon = [entree.__dict__ for entree in sorted(entrees, key=lambda item: item.chemin)]
        digest = hashlib.sha256(
            json.dumps(canon, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return cls(tuple(sorted(entrees, key=lambda item: item.chemin)), digest)


def racines_fermeture_m3(racine: Path) -> dict[str, Path]:
    """Fermeture des fichiers copiés ou liés par EnvironnementMutation."""
    racine = Path(racine).resolve(strict=True)
    departements = racine / "departments"
    resultats = {
        "department:m03-estimation": departements / "m03-estimation",
        "src": racine / "src",
        "docs": racine / "docs",
        "pyproject.toml": racine / "pyproject.toml",
        "conftest.py": racine / "conftest.py",
        "fixture:m2_preparation_estimation": racine / "tests/fixtures/m2_preparation_estimation.py",
    }
    for departement in sorted(departements.iterdir(), key=lambda item: item.name):
        if departement.name != "m03-estimation":
            resultats[f"department:{departement.name}"] = departement
    return resultats


@dataclass(frozen=True)
class SpecificationExecution:
    outil: str
    scenario: str
    commande: tuple[str, ...]
    argv: tuple[str, ...]
    cwd: str
    python: str
    environnement_sha256: str
    options_pytest: tuple[str, ...]
    collecte: str
    environnement_execution: tuple[tuple[str, str], ...] | None = field(
        default=None, repr=False, compare=False
    )

    def cle(self, empreinte: EmpreinteEntrees) -> str:
        payload = {
            "outil": self.outil,
            "scenario": self.scenario,
            "commande": self.commande,
            "argv": self.argv,
            "cwd": self.cwd,
            "python": self.python,
            "environnement_sha256": self.environnement_sha256,
            "options_pytest": self.options_pytest,
            "collecte": self.collecte,
            "entrees_sha256": empreinte.sha256,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class ResultatProcessus(Protocol):
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class PreuveExecution:
    cle: str
    specification: SpecificationExecution
    entrees_sha256: str
    avant: EmpreinteEntrees
    apres: EmpreinteEntrees
    commande: tuple[str, ...]
    retour: int
    stdout: str
    stderr: str
    junit: str | None
    secondes: float
    identifiant_campagne: str | None = None

    @property
    def nettoyage_prouve(self) -> bool:
        return self.avant.sha256 == self.apres.sha256

    def vers_objet(self) -> dict[str, object]:
        """Retourne le reçu complet d'une invocation observée, sans réécriture."""
        return {
            "schema": 2,
            "identifiant_campagne": self.identifiant_campagne,
            "cle": self.cle,
            "specification": _specification_objet(self.specification),
            "entrees_sha256": self.entrees_sha256,
            "avant": _empreinte_objet(self.avant),
            "apres": _empreinte_objet(self.apres),
            "commande": list(self.commande),
            "retour": self.retour,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "junit": self.junit,
            "secondes": self.secondes,
            "nettoyage_prouve": self.nettoyage_prouve,
        }

    def ecrire(self, chemin: Path) -> None:
        """Écrit atomiquement sans jamais remplacer un reçu déjà présent."""
        objet = self.vers_objet()
        objet["recu_sha256"] = _sha256_json(objet)
        contenu = json.dumps(objet, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        contenu_octets = contenu.encode("utf-8")
        chemin.parent.mkdir(parents=True, exist_ok=True)
        if chemin.exists():
            if chemin.read_bytes() == contenu_octets:
                return
            raise FileExistsError(f"reçu existant différent: {chemin}")
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=chemin.parent, delete=False
        ) as temporaire:
            temporaire.write(contenu)
            nom_temporaire = temporaire.name
        try:
            try:
                os.link(nom_temporaire, chemin)
            except FileExistsError:
                if chemin.read_bytes() != contenu_octets:
                    raise FileExistsError(
                        f"reçu existant différent: {chemin}"
                    ) from None
        finally:
            Path(nom_temporaire).unlink(missing_ok=True)


def _empreinte_objet(empreinte: EmpreinteEntrees) -> dict[str, object]:
    return {
        "sha256": empreinte.sha256,
        "entrees": [entree.__dict__ for entree in empreinte.entrees],
    }


def _sha256_json(objet: Mapping[str, object]) -> str:
    canon = json.dumps(objet, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _specification_objet(specification: SpecificationExecution) -> dict[str, object]:
    return {
        "outil": specification.outil,
        "scenario": specification.scenario,
        "commande": list(specification.commande),
        "argv": list(specification.argv),
        "cwd": specification.cwd,
        "python": specification.python,
        "environnement_sha256": specification.environnement_sha256,
        "options_pytest": list(specification.options_pytest),
        "collecte": specification.collecte,
    }


@dataclass(frozen=True)
class AccesPreuve:
    preuve: PreuveExecution
    processus_lance_ici: bool
    recu_durable: str | None = None


class CampagneM3:
    """Cache mémoire session, indexé par la vraie entrée et le scénario exact."""

    def __init__(
        self,
        *,
        dossier_artefacts: Path | None = None,
        identifiant: str | None = None,
    ) -> None:
        if (dossier_artefacts is None) != (identifiant is None):
            raise ValueError(
                "la reprise durable exige ensemble un dossier et un identifiant"
            )
        self.identifiant = identifiant or uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.identifiant):
            raise ValueError("identifiant de campagne invalide")
        self.dossier_persistance = (
            Path(dossier_artefacts) / self.identifiant
            if dossier_artefacts is not None
            else None
        )
        self._preuves: dict[str, PreuveExecution] = {}
        self._observations: list[PreuveExecution] = []
        self._executions = 0

    @property
    def nombre_executions(self) -> int:
        return self._executions

    def obtenir_ou_executer(
        self,
        specification: SpecificationExecution,
        capturer: Callable[[], EmpreinteEntrees],
        lancer: Callable[[], ResultatProcessus],
        *,
        commande: Sequence[str],
        junit: Callable[[], str | None] | None = None,
    ) -> AccesPreuve:
        commande = tuple(commande)
        if commande != specification.commande:
            raise AssertionError("la commande exécutée diffère de sa spécification")
        avant = capturer()
        cle = specification.cle(avant)
        precedente = self._preuves.get(cle)
        if precedente is not None:
            if precedente.entrees_sha256 != avant.sha256:
                raise AssertionError("collision de clé de campagne")
            chemin_precedent = self._chemin_durable(cle)
            return AccesPreuve(
                precedente,
                processus_lance_ici=False,
                recu_durable=(
                    str(chemin_precedent)
                    if chemin_precedent is not None and chemin_precedent.is_file()
                    else None
                ),
            )

        chemin_durable = self._chemin_durable(cle)
        if chemin_durable is not None and chemin_durable.exists():
            objet = self.lire_artefact(
                chemin_durable,
                specification,
                avant,
                identifiant_campagne=self.identifiant,
            )
            preuve = self._preuve_depuis_objet(objet, specification)
            self._preuves[cle] = preuve
            self._observations.append(preuve)
            return AccesPreuve(
                preuve,
                processus_lance_ici=False,
                recu_durable=str(chemin_durable),
            )

        depart = time.monotonic()
        resultat = lancer()
        duree = time.monotonic() - depart
        apres = capturer()
        preuve = PreuveExecution(
            cle=cle,
            specification=specification,
            entrees_sha256=avant.sha256,
            avant=avant,
            apres=apres,
            commande=commande,
            retour=resultat.returncode,
            stdout=resultat.stdout,
            stderr=resultat.stderr,
            junit=junit() if junit is not None else None,
            secondes=duree,
            identifiant_campagne=(
                self.identifiant if self.dossier_persistance is not None else None
            ),
        )
        self._executions += 1
        self._observations.append(preuve)
        self._ecrire_durable(proof=preuve)
        if preuve.nettoyage_prouve:
            self._preuves[cle] = preuve
        chemin_durable = self._chemin_durable(cle)
        return AccesPreuve(
            preuve,
            processus_lance_ici=True,
            recu_durable=(
                str(chemin_durable)
                if chemin_durable is not None and chemin_durable.is_file()
                else None
            ),
        )

    def _chemin_durable(self, cle: str) -> Path | None:
        if self.dossier_persistance is None:
            return None
        return self.dossier_persistance / f"{cle}.json"

    def _ecrire_durable(self, *, proof: PreuveExecution) -> None:
        chemin = self._chemin_durable(proof.cle)
        if chemin is not None:
            proof.ecrire(chemin)

    @staticmethod
    def _preuve_depuis_objet(
        objet: Mapping[str, object], specification: SpecificationExecution
    ) -> PreuveExecution:
        def empreinte(nom: str) -> EmpreinteEntrees:
            valeur = objet.get(nom)
            if not isinstance(valeur, dict):
                raise AssertionError("reçu invalide: capture absente")
            entrees_brutes = valeur.get("entrees")
            if not isinstance(entrees_brutes, list):
                raise AssertionError("reçu invalide: entrées absentes")
            entrees: list[EntreeEmpreinte] = []
            for entree in entrees_brutes:
                if not isinstance(entree, dict):
                    raise AssertionError("reçu invalide: entrée mal formée")
                entrees.append(
                    EntreeEmpreinte(
                        chemin=entree["chemin"],
                        mode=entree["mode"],
                        sha256=entree["sha256"],
                        est_dossier=entree["est_dossier"],
                        lien=entree["lien"],
                    )
                )
            sha = valeur.get("sha256")
            if not isinstance(sha, str):
                raise AssertionError("reçu invalide: hash de capture absent")
            return EmpreinteEntrees(tuple(entrees), sha)

        commande_brute = objet.get("commande")
        if not isinstance(commande_brute, list) or not all(
            isinstance(partie, str) for partie in commande_brute
        ):
            raise AssertionError("reçu invalide: commande absente")
        retour = objet.get("retour")
        stdout = objet.get("stdout")
        stderr = objet.get("stderr")
        junit = objet.get("junit")
        secondes = objet.get("secondes")
        cle = objet.get("cle")
        entrees_sha256 = objet.get("entrees_sha256")
        identifiant = objet.get("identifiant_campagne")
        if (
            not isinstance(retour, int)
            or not isinstance(stdout, str)
            or not isinstance(stderr, str)
            or (junit is not None and not isinstance(junit, str))
            or not isinstance(secondes, (int, float))
            or not isinstance(cle, str)
            or not isinstance(entrees_sha256, str)
            or (identifiant is not None and not isinstance(identifiant, str))
        ):
            raise AssertionError("reçu invalide: résultats mal formés")
        return PreuveExecution(
            cle=cle,
            specification=specification,
            entrees_sha256=entrees_sha256,
            avant=empreinte("avant"),
            apres=empreinte("apres"),
            commande=tuple(commande_brute),
            retour=retour,
            stdout=stdout,
            stderr=stderr,
            junit=junit,
            secondes=float(secondes),
            identifiant_campagne=identifiant,
        )

    def obtenir_ou_lancer_commande(
        self,
        specification: SpecificationExecution,
        capturer: Callable[[], EmpreinteEntrees],
        *,
        environnement: Mapping[str, str] | None = None,
        junit: Callable[[], str | None] | None = None,
    ) -> AccesPreuve:
        """Exécute la commande enregistrée avec le cwd et l'environnement enregistrés."""
        if environnement is None:
            env_reel = (
                dict(specification.environnement_execution)
                if specification.environnement_execution is not None
                else dict(os.environ)
            )
        else:
            env_reel = dict(environnement)
        env_canonique = json.dumps(
            sorted(env_reel.items()), separators=(",", ":")
        ).encode("utf-8")
        if hashlib.sha256(env_canonique).hexdigest() != specification.environnement_sha256:
            raise AssertionError("l'environnement exécuté diffère de sa spécification")

        def lancer() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                specification.commande,
                cwd=specification.cwd,
                env=env_reel,
                capture_output=True,
                text=True,
                check=False,
            )

        return self.obtenir_ou_executer(
            specification,
            capturer,
            lancer,
            commande=specification.commande,
            junit=junit,
        )

    def exiger(
        self,
        specification: SpecificationExecution,
        empreinte: EmpreinteEntrees,
    ) -> PreuveExecution:
        cle = specification.cle(empreinte)
        try:
            preuve = self._preuves[cle]
        except KeyError as exc:
            raise AssertionError(
                "aucune preuve exécutée pour cette fermeture et ce scénario"
            ) from exc
        if preuve.entrees_sha256 != empreinte.sha256 or not preuve.nettoyage_prouve:
            raise AssertionError("preuve périmée ou sans nettoyage capturé")
        return preuve

    def ecrire_artefacts(self, dossier: Path) -> Path:
        """Persiste cette campagne dans un sous-dossier unique, sans écrasement."""
        if self.dossier_persistance is not None:
            dossier_campagne = Path(dossier) / self.identifiant
            if dossier_campagne.resolve() != self.dossier_persistance.resolve():
                raise AssertionError("le dossier ne correspond pas au runID persistant")
            for preuve in self._observations:
                self._ecrire_durable(proof=preuve)
            return dossier_campagne
        dossier_campagne = dossier / self.identifiant
        dossier_campagne.mkdir(parents=True, exist_ok=True)
        for index, preuve in enumerate(self._observations, start=1):
            nom = f"run-{index:04}-{preuve.cle}.json"
            preuve.ecrire(dossier_campagne / nom)
        return dossier_campagne

    @staticmethod
    def lire_artefact(
        chemin: Path,
        specification: SpecificationExecution,
        empreinte_actuelle: EmpreinteEntrees,
        *,
        identifiant_campagne: str | None = None,
    ) -> dict[str, object]:
        """Valide un reçu exact; n'invente aucune exécution ou capture manquante."""
        objet = json.loads(chemin.read_text(encoding="utf-8"))
        if not isinstance(objet, dict) or objet.get("schema") != 2:
            raise AssertionError("reçu de campagne invalide")
        recu_sha256 = objet.pop("recu_sha256", None)
        if recu_sha256 != _sha256_json(objet):
            raise AssertionError("intégrité du reçu non valide")
        cle = specification.cle(empreinte_actuelle)
        if objet.get("cle") != cle:
            raise AssertionError("reçu d'une autre fermeture ou commande")
        if objet.get("identifiant_campagne") != identifiant_campagne:
            raise AssertionError("reçu d'une autre campagne")
        if objet.get("specification") != _specification_objet(specification):
            raise AssertionError("spécification du reçu modifiée")
        if objet.get("commande") != list(specification.commande):
            raise AssertionError("commande du reçu modifiée")
        if objet.get("entrees_sha256") != empreinte_actuelle.sha256:
            raise AssertionError("fermeture différente du reçu")
        if (
            not isinstance(objet.get("avant"), dict)
            or objet["avant"].get("sha256") != empreinte_actuelle.sha256
        ):
            raise AssertionError("capture avant différente de la fermeture")
        if (
            not isinstance(objet.get("apres"), dict)
            or objet["apres"].get("sha256") != empreinte_actuelle.sha256
        ):
            raise AssertionError("capture après différente de la fermeture")
        if objet.get("avant") != objet.get("apres"):
            raise AssertionError("reçu sans restauration capturée")
        if objet.get("nettoyage_prouve") is not True:
            raise AssertionError("reçu sans nettoyage prouvé")
        return objet
