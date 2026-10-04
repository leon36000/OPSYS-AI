"""Accès explicite aux invocations réelles partagées par les gardes M3.

Cette façade lance les outils de preuve contre des copies isolées des sources M3,
conserve les captures avant/après et réutilise un reçu seulement quand la campagne,
les entrées, la commande et l’environnement correspondent. Les scénarios nominaux,
rouges, sans garde et non compilables gardent leurs preuves distinctes. Un résultat
de campagne décrit uniquement les outils et sources capturés; il ne constitue pas
une preuve d’intégration ou de mutation sur un déploiement réel.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from _environnement_mutation import EnvironnementMutation
from adaptateur_campagne import executer_preuve, specification_outil
from campagne_m3 import AccesPreuve, CampagneM3


class CampagneGardes:
    """Lance chaque combinaison outil/scénario au plus une fois par session pytest."""

    def __init__(self, racine: Path, dossier_artefacts: Path) -> None:
        self.racine = racine.resolve(strict=True)
        self.m3 = self.racine / "departments/m03-estimation"
        self.tests = self.m3 / "tests"
        self.outils = self.tests / "outils_preuve"
        self.outils_mutation = sorted(self.outils.glob("muter_*.py"))
        self.enumerateur = self.outils / "enumerer_gardes.py"
        self.module_nominal = sorted(
            outil.stem.removeprefix("muter_") for outil in self.outils_mutation
        )[0]
        self.dossier_artefacts = dossier_artefacts
        identifiant = os.environ.get("M3_CAMPAGNE_RUN_ID")
        self.campagne = CampagneM3(
            dossier_artefacts=dossier_artefacts if identifiant else None,
            identifiant=identifiant,
        )
        dossier_scenarios = (
            self.campagne.dossier_persistance / "scenarios"
            if self.campagne.dossier_persistance is not None
            else None
        )
        self.rouge = EnvironnementMutation(
            self.racine,
            dossier=(dossier_scenarios / "rouge" if dossier_scenarios else None),
        )
        test_rouge = (
            self.rouge.dossier_tests / "test_epreuve_garde_suite_rouge.py"
        )
        test_rouge.write_text(
            "def test_epreuve_deliberement_rouge():\n"
            '    assert False, "épreuve volontairement rouge des gardes"\n',
            encoding="utf-8",
        )
        self.rouge.sceller()
        self.sans_garde = EnvironnementMutation(
            self.racine,
            dossier=(
                dossier_scenarios / "sans-garde" if dossier_scenarios else None
            ),
        )
        self.sans_garde.sceller()
        self.non_compilable: EnvironnementMutation | None = None

    def fermer(self) -> None:
        try:
            if self.campagne.nombre_executions:
                self.campagne.ecrire_artefacts(self.dossier_artefacts)
        finally:
            self.rouge.nettoyer()
            self.sans_garde.nettoyer()
            if self.non_compilable is not None:
                self.non_compilable.nettoyer()

    def environnement_nominal(self) -> dict[str, str]:
        """Child environment stable across pytest nodes for reusable nominal proofs."""
        environnement = dict(os.environ)
        racine_campagne = (
            self.campagne.dossier_persistance
            or self.dossier_artefacts.resolve() / "campagne-volatile"
        )
        environnement["OPSYS_HOME"] = str(racine_campagne / "opsys-home-enfant")
        environnement["_"] = sys.executable
        return environnement

    def nominal(
        self,
        outil: Path,
        *,
        environnement: dict[str, str] | None = None,
    ) -> AccesPreuve:
        if environnement is None:
            environnement = self.environnement_nominal()
        arguments = (self.module_nominal,) if outil == self.enumerateur else ()
        specification = specification_outil(
            outil,
            self.racine,
            "nominal",
            arguments=arguments,
            environnement=environnement,
        )
        return executer_preuve(
            self.campagne,
            specification,
            self.racine,
            environnement=environnement,
        )

    def suite_rouge(self, outil: Path) -> AccesPreuve:
        arguments = (self.module_nominal,) if outil == self.enumerateur else ()
        specification = specification_outil(
            outil,
            self.rouge.dossier,
            "suite-rouge",
            arguments=arguments,
        )
        return executer_preuve(
            self.campagne,
            specification,
            self.racine,
            racine_scenario=self.rouge.dossier,
        )

    def sans_garde_preuve(self) -> AccesPreuve:
        chemin = self.sans_garde.dossier_source / "epreuve_module_sans_garde.py"
        if not chemin.exists():
            chemin.write_text(
                "def valeur_epreuve():\n    return 1\n", encoding="utf-8"
            )
        self.sans_garde.sceller()
        specification = specification_outil(
            self.enumerateur,
            self.sans_garde.dossier,
            "module-sans-garde",
            arguments=(chemin.stem,),
        )
        return executer_preuve(
            self.campagne,
            specification,
            self.racine,
            racine_scenario=self.sans_garde.dossier,
        )

    def non_compilable_preuve(self, sabotageur) -> tuple[AccesPreuve, bytes]:
        if self.non_compilable is None:
            dossier_scenarios = (
                self.campagne.dossier_persistance / "scenarios"
                if self.campagne.dossier_persistance is not None
                else None
            )
            self.non_compilable = EnvironnementMutation(
                self.racine,
                dossier=(
                    dossier_scenarios / "non-compilable"
                    if dossier_scenarios
                    else None
                ),
            )
        module = self.outils_mutation[0].stem.removeprefix("muter_")
        cible = self.non_compilable.dossier_source / f"{module}.py"
        outil = self.non_compilable.dossier_tests / "outils_preuve" / "epreuve_mutation_non_compilable.py"
        if not outil.exists():
            shutil.copyfile(self.outils_mutation[0], outil)
            source = sabotageur(
                outil.read_text(encoding="utf-8"), cible.read_text(encoding="utf-8")
            )
            if source is None:
                raise AssertionError(
                    "aucune ancre unique ne permet le sabotage non-compilable"
                )
            outil.write_text(source, encoding="utf-8")
        self.non_compilable.sceller()
        contenu = outil.read_bytes()
        specification = specification_outil(
            outil,
            self.non_compilable.dossier,
            "mutant-non-compilable",
        )
        acces = executer_preuve(
            self.campagne,
            specification,
            self.racine,
            racine_scenario=self.non_compilable.dossier,
            outil_sabote=outil,
        )
        return acces, contenu
