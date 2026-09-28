"""Manifeste d'un département (`departments/<id>/department.yaml`) et son chargement.

Un département est un organe de l'entreprise. Il octroie à ses agents des capacités :
- des outils déterministes ;
- des skills (procédures) ;
- des politiques d'autonomie ;
- des planifications ;
- des budgets de tokens et des KPIs.
Le manifeste est la source unique : le serveur MCP, les profils Hermes et le dashboard en
dérivent.
"""

from __future__ import annotations

import dataclasses
import importlib
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .identite import ROLES, Role
from .outils import Niveau, Outil
from .politiques import valider_mode

SCHEMA = "opsys.departement/v1"
PALIERS = ("local", "rapide", "standard", "fort")
_ID = re.compile(r"^m(0[1-9]|10)-[a-z][a-z0-9-]+$")
_CODE = re.compile(r"^M(10|[1-9])$")
_CRON = re.compile(r"^(\S+\s+){4}\S+$")
_SKILL = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
# Niveaux qu'un département peut configurer dans son bloc `approbations` (ADR-0009 §5). N3 et N4
# seulement : en dessous de N3, une action est automatique et ne crée jamais de demande (ADR-0009
# §4) ; N5 est une frontière FIXE de l'ADR (« la signature de nathan_owner », jamais automatique,
# jamais déléguée) — `DEFAUT_ROLES_NIVEAU` s'applique toujours à N5, aucun manifeste ne peut
# l'élargir ni le restreindre (voir `_politique_approbation`).
_CLES_POLITIQUE = {"n3": Niveau.N3, "n4": Niveau.N4}
# Politique par défaut, fail-closed (ADR-0009 §5) : absente du manifeste, ou un niveau non déclaré,
# retombe sur le rôle le plus restrictif seul.
DEFAUT_ROLES_NIVEAU: frozenset[str] = frozenset({Role.NATHAN_OWNER.value})


@dataclasses.dataclass(frozen=True)
class Planification:
    nom: str
    cron: str
    consigne: str


@dataclasses.dataclass(frozen=True)
class Budget:
    tokens_jour: int
    tokens_mois: int
    alerte_pct: int = 80


@dataclasses.dataclass(frozen=True)
class Kpi:
    id: str
    description: str


@dataclasses.dataclass(frozen=True)
class PolitiqueApprobation:
    """Rôles autorisés à décider (approuver ou refuser) une demande, par niveau N3/N4/N5
    (ADR-0009 §5). `approbations.decider` exige une personne active dont un rôle figure dans
    `roles_pour(niveau)` de SON département ; sinon, refus nommé, rien exécuté.

    Un niveau non couvert par `roles` (bloc absent du manifeste, ou niveau non déclaré dans le
    bloc) retombe sur `DEFAUT_ROLES_NIVEAU` — le rôle le plus restrictif seul (fail-closed).
    """

    roles: Mapping[Niveau, frozenset[str]] = dataclasses.field(default_factory=dict)

    def roles_pour(self, niveau: Niveau) -> frozenset[str]:
        return self.roles.get(niveau, DEFAUT_ROLES_NIVEAU)


POLITIQUE_PAR_DEFAUT = PolitiqueApprobation()


@dataclasses.dataclass(frozen=True)
class Departement:
    id: str
    code: str
    nom: str
    mission: str
    module_outils: str
    mode: str
    dependances: tuple[str, ...]
    modeles: Mapping[str, str]
    skills: tuple[str, ...]
    planifications: tuple[Planification, ...]
    budget: Budget
    memoire_lecture: tuple[str, ...]
    memoire_ecriture: tuple[str, ...]
    kpis: tuple[Kpi, ...]
    racine: Path
    evenements_publie: tuple[str, ...] = ()
    evenements_consomme: tuple[str, ...] = ()
    politique_approbation: PolitiqueApprobation = POLITIQUE_PAR_DEFAUT

    @property
    def prefixe_outils(self) -> str:
        """'m3' pour M3 : préfixe obligatoire des noms d'outils du département."""
        return self.code.lower()

    def roles_autorises(self, niveau: Niveau) -> frozenset[str]:
        """Rôles pouvant décider une demande de ce niveau N dans ce département (ADR-0009 §5)."""
        return self.politique_approbation.roles_pour(niveau)

    @property
    def numero(self) -> int:
        return int(self.code[1:])

    def charger_outils(self) -> tuple[Outil, ...]:
        """Importe `module_outils.OUTILS` et vérifie le préfixe et l'unicité des noms."""
        module = importlib.import_module(self.module_outils)
        fabrique = getattr(module, "outils", None)
        outils = tuple(fabrique() if callable(fabrique) else getattr(module, "OUTILS", ()))
        if not outils:
            raise ValueError(f"{self.id} : {self.module_outils} n'expose ni outils() ni OUTILS")
        vus: set[str] = set()
        for outil in outils:
            if not isinstance(outil, Outil):
                raise TypeError(f"{self.id} : {outil!r} n'est pas un opsys.outils.Outil")
            if outil.departement_code != self.prefixe_outils:
                raise ValueError(
                    f"{self.id} : l'outil {outil.nom} doit commencer par {self.prefixe_outils}_"
                )
            if outil.nom in vus:
                raise ValueError(f"{self.id} : outil en double {outil.nom}")
            vus.add(outil.nom)
        return outils

    def charger_consommateurs(self) -> dict[str, Callable[[Mapping[str, Any]], Any]]:
        """Importe `module_outils.consommateurs()` (fonctions d'événements, ADR-0009 §3).

        Même module que `charger_outils()` (`docs/architecture/DEPARTEMENTS.md`) : un département
        qui ne consomme aucun événement n'a pas besoin de définir `consommateurs`. Absence de la
        fonction : dict vide, jamais une erreur — `evenements.verifier_coherence` signale l'écart
        pour un département qui *déclare* consommer un type sans fournir sa fonction.
        """
        module = importlib.import_module(self.module_outils)
        fabrique = getattr(module, "consommateurs", None)
        if fabrique is None:
            return {}
        consommateurs = fabrique()
        if not isinstance(consommateurs, Mapping):
            raise TypeError(f"{self.id} : {self.module_outils}.consommateurs() doit renvoyer un dict")
        for type_evenement, fonction in consommateurs.items():
            if not isinstance(type_evenement, str) or not callable(fonction):
                raise TypeError(
                    f"{self.id} : consommateurs() doit associer un type (str) à une fonction appelable"
                )
        return dict(consommateurs)

    def charger_attentes(self) -> Callable[[], Sequence[Mapping[str, Any]]] | None:
        """Importe `module_outils.attentes` s'il existe (ADR-0009 §5, PLAN T1.3-a) ; None sinon.

        Même mécanisme que `charger_consommateurs` : fonction optionnelle exposée par le module qui
        définit `outils()`, découverte par `getattr`, jamais déclarée dans le manifeste. Elle n'est
        PAS appelée ici (aucune connexion disponible à ce point) : `approbations.file_proprietaire`
        l'appelle dans la transaction courante, pour que le département puisse lire ses propres
        registres (`opsys.stockage.maillons`). Aucun département de production ne l'implémente
        encore (PLAN T1.3-b/c) ; le mécanisme est exercé par les départements de démonstration des
        tests du socle.
        """
        module = importlib.import_module(self.module_outils)
        fonction = getattr(module, "attentes", None)
        if fonction is not None and not callable(fonction):
            raise TypeError(f"{self.id} : {self.module_outils}.attentes doit être appelable")
        return fonction


def _texte(donnees: Mapping[str, Any], cle: str, contexte: str) -> str:
    valeur = donnees.get(cle)
    if not isinstance(valeur, str) or not valeur.strip():
        raise ValueError(f"{contexte} : champ texte requis manquant ou vide : {cle}")
    return valeur.strip()


def _liste(donnees: Mapping[str, Any], cle: str, contexte: str) -> tuple[str, ...]:
    valeur = donnees.get(cle, [])
    if valeur is None:
        return ()
    if not isinstance(valeur, list) or not all(isinstance(v, str) and v for v in valeur):
        raise ValueError(f"{contexte} : {cle} doit être une liste de chaînes non vides")
    return tuple(valeur)


def _entier_positif(donnees: Mapping[str, Any], cle: str, contexte: str) -> int:
    valeur = donnees.get(cle)
    if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur <= 0:
        raise ValueError(f"{contexte} : {cle} doit être un entier strictement positif")
    return valeur


def _politique_approbation(donnees: Mapping[str, Any], ctx: str) -> PolitiqueApprobation:
    """`approbations: {n3, n4}` (ADR-0009 §5) : rôles autorisés à décider par niveau N.

    Bloc entièrement optionnel ; absent, ou un niveau qu'il ne couvre pas, retombe sur
    `DEFAUT_ROLES_NIVEAU` (fail-closed, ADR-0009 §5). N5 ne se déclare PAS ici : c'est une
    frontière fixe de l'ADR (« la signature de nathan_owner », en plus de l'attestation du
    professionnel, jamais automatique, jamais déléguée) — elle retombe donc toujours sur
    `DEFAUT_ROLES_NIVEAU` (nathan_owner seul), sans exception possible depuis un manifeste.
    """
    brut = donnees.get("approbations")
    if brut is None:
        return POLITIQUE_PAR_DEFAUT
    if not isinstance(brut, Mapping):
        raise ValueError(f"{ctx} : approbations doit être un objet ({{n3, n4}})")
    if "n5" in brut:
        raise ValueError(
            f"{ctx} : approbations.n5 ne se déclare pas dans un manifeste : N5 est fixé système à "
            "nathan_owner seul (ADR-0009 §5 — jamais automatique, jamais délégué à un autre rôle)"
        )
    inconnues = sorted(set(brut) - set(_CLES_POLITIQUE))
    if inconnues:
        raise ValueError(f"{ctx} : approbations : clé(s) inconnue(s) {inconnues} (attendu : n3, n4)")
    roles: dict[Niveau, frozenset[str]] = {}
    for cle, niveau in _CLES_POLITIQUE.items():
        if cle not in brut:
            continue
        valeur = brut[cle]
        if not isinstance(valeur, list) or not valeur or not all(isinstance(r, str) and r for r in valeur):
            raise ValueError(f"{ctx} : approbations.{cle} doit être une liste non vide de rôles")
        ensemble = frozenset(valeur)
        inconnus = sorted(ensemble - ROLES)
        if inconnus:
            raise ValueError(
                f"{ctx} : approbations.{cle} : rôle(s) inconnu(s) {inconnus} (ADR-0009 §5 : {sorted(ROLES)})"
            )
        roles[niveau] = ensemble
    return PolitiqueApprobation(roles=roles)


def lire_manifeste(dossier: Path) -> Departement:
    chemin = dossier / "department.yaml"
    donnees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    ctx = str(chemin)
    if not isinstance(donnees, dict):
        raise ValueError(f"{ctx} : le manifeste doit être un objet YAML")
    if donnees.get("schema") != SCHEMA:
        raise ValueError(f"{ctx} : schema attendu {SCHEMA!r}")

    ident = _texte(donnees, "id", ctx)
    if not _ID.match(ident) or ident != dossier.name:
        raise ValueError(f"{ctx} : id {ident!r} invalide ou différent du dossier {dossier.name!r}")
    code = _texte(donnees, "code", ctx)
    if not _CODE.match(code) or int(code[1:]) != int(ident[1:3]):
        raise ValueError(f"{ctx} : code {code!r} incohérent avec l'id {ident!r}")

    modeles = donnees.get("modeles", {"defaut": "standard"})
    if not isinstance(modeles, dict) or "defaut" not in modeles:
        raise ValueError(f"{ctx} : modeles doit contenir au moins 'defaut'")
    for usage, palier in modeles.items():
        if palier not in PALIERS:
            raise ValueError(f"{ctx} : palier {palier!r} pour {usage!r} (attendu : {PALIERS})")

    skills = _liste(donnees, "skills", ctx)
    for skill in skills:
        if not _SKILL.match(skill):
            raise ValueError(f"{ctx} : nom de skill invalide {skill!r}")
        if not (dossier / "skills" / skill / "SKILL.md").is_file():
            raise ValueError(f"{ctx} : skills/{skill}/SKILL.md introuvable")

    planifications = []
    for brut in donnees.get("planifications", []) or []:
        if not isinstance(brut, dict):
            raise ValueError(f"{ctx} : chaque planification doit être un objet")
        cron = _texte(brut, "cron", ctx)
        if not _CRON.match(cron):
            raise ValueError(f"{ctx} : expression cron invalide {cron!r} (5 champs)")
        planifications.append(
            Planification(nom=_texte(brut, "nom", ctx), cron=cron, consigne=_texte(brut, "consigne", ctx))
        )

    budget_brut = donnees.get("budget")
    if not isinstance(budget_brut, dict):
        raise ValueError(f"{ctx} : budget requis (tokens_jour, tokens_mois)")
    alerte = budget_brut.get("alerte_pct", 80)
    if isinstance(alerte, bool) or not isinstance(alerte, int) or not 1 <= alerte <= 100:
        raise ValueError(f"{ctx} : budget.alerte_pct doit être un entier entre 1 et 100")
    budget = Budget(
        tokens_jour=_entier_positif(budget_brut, "tokens_jour", ctx),
        tokens_mois=_entier_positif(budget_brut, "tokens_mois", ctx),
        alerte_pct=alerte,
    )
    if budget.tokens_mois < budget.tokens_jour:
        raise ValueError(f"{ctx} : budget.tokens_mois doit être >= tokens_jour")

    memoire = donnees.get("memoire", {}) or {}
    evenements = donnees.get("evenements", {}) or {}
    if not isinstance(evenements, dict):
        raise ValueError(f"{ctx} : evenements doit être un objet ({{publie, consomme}})")
    evenements_publie = _liste(evenements, "publie", ctx)
    evenements_consomme = _liste(evenements, "consomme", ctx)
    kpis = []
    for brut in donnees.get("kpis", []) or []:
        if not isinstance(brut, dict):
            raise ValueError(f"{ctx} : chaque KPI doit être un objet")
        kpis.append(Kpi(id=_texte(brut, "id", ctx), description=_texte(brut, "description", ctx)))

    if not (dossier / "SOUL.md").is_file():
        raise ValueError(f"{ctx} : SOUL.md introuvable à côté du manifeste")

    return Departement(
        id=ident,
        code=code,
        nom=_texte(donnees, "nom", ctx),
        mission=_texte(donnees, "mission", ctx),
        module_outils=_texte(donnees, "outils", ctx),
        mode=valider_mode(donnees.get("mode", "ombre")),
        dependances=_liste(donnees, "dependances", ctx),
        modeles=dict(modeles),
        skills=skills,
        planifications=tuple(planifications),
        budget=budget,
        memoire_lecture=_liste(memoire, "lecture", ctx),
        memoire_ecriture=_liste(memoire, "ecriture", ctx),
        kpis=tuple(kpis),
        racine=dossier,
        evenements_publie=evenements_publie,
        evenements_consomme=evenements_consomme,
        politique_approbation=_politique_approbation(donnees, ctx),
    )


def racine_departements() -> Path:
    """Dossier `departments/` du dépôt ou de l'installation (OPSYS_DEPARTMENTS le remplace)."""
    import os

    env = os.environ.get("OPSYS_DEPARTMENTS")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "departments"


def charger_departements(racine: Path | None = None) -> dict[str, Departement]:
    """Charge tous les départements ayant un manifeste, triés par numéro (M1 → M10)."""
    base = racine or racine_departements()
    departements = [lire_manifeste(d) for d in sorted(base.iterdir()) if (d / "department.yaml").is_file()]
    departements.sort(key=lambda d: d.numero)
    return {d.id: d for d in departements}


def dependances_manquantes(departements: Mapping[str, Departement]) -> dict[str, list[str]]:
    """Départements dont une dépendance déclarée n'est pas installée (vide = cohérent)."""
    manquantes = {}
    for dep in departements.values():
        absentes = sorted(set(dep.dependances) - set(departements))
        if absentes:
            manquantes[dep.id] = absentes
    return manquantes


def tous_les_outils(departements: Iterable[Departement]) -> dict[str, tuple[Departement, Outil]]:
    """Index global nom d'outil -> (département, outil), avec contrôle d'unicité."""
    index: dict[str, tuple[Departement, Outil]] = {}
    for dep in departements:
        for outil in dep.charger_outils():
            if outil.nom in index:
                raise ValueError(f"outil {outil.nom} déclaré par deux départements")
            index[outil.nom] = (dep, outil)
    return index


def verifier_attentes(departements: Mapping[str, Departement]) -> list[str]:
    """`opsys verifier` : chaque `attentes()` déclaré (s'il y en a un) doit au moins se charger.

    Même esprit que `evenements.verifier_coherence` : un département cassé est signalé, jamais une
    panne de la commande. `file_proprietaire` retente le même chargement (et l'appel) à l'usage ;
    cette fonction ne fait que le vérifier tôt, en CI.
    """
    problemes: list[str] = []
    for dep in departements.values():
        try:
            dep.charger_attentes()
        except Exception as exc:  # noqa: BLE001 — signalé, jamais une panne de `opsys verifier`
            problemes.append(f"{dep.id} : attentes() illisible ({type(exc).__name__}: {exc})")
    return problemes
