"""Registre d'autorité (C03-002) — joint la carte des chemins ratifiée
(C00-004, `audit/core-baseline/AUTHORITY-MAP.csv`) à la carte d'autorité
métier ratifiée (chore PR #501, `audit/core-baseline/BUSINESS-AUTHORITY-
MAP-M1-M10.csv`) sur le nom de module, comme amendé dans `tasks/
C03-002.md` (« Implémentation strictement bornée »).

Revue d'architecture AVANT code (subagent `architecte`, Claude Opus 5
natif, 4 questions fermées, 2026-08-11) — chaque décision ci-dessous est
tracée à sa réponse :

1. **Table d'alias EXPLICITE, jamais un algorithme de préfixe.** `"M10-
   memoire".startswith("M1")` vaut `True` — un algorithme par préfixe sur
   les noms COURTS confondrait M1 et M10. La spec elle-même demande une
   table (« valider unicité et **aliases** », `tasks/C03-002.md:61`), déjà
   annoncée comme le périmètre repris par cette tâche (mémoire du chore
   PR #501 : « jointure future via une table d'alias séparée »).
2. **CORE n'a AUCUN chemin résolvable pour ses 6 agrégats métier**
   (identity, policy, approvals, consent, event routing, tool grants).
   `AUTHORITY-MAP.csv` liste 4 chemins CORE (auth, authz, config,
   opsys_core) — 4 candidats, aucun critère non arbitraire pour choisir
   lequel sert quel agrégat. Trois artefacts DÉJÀ MERGÉS interdisent de
   deviner : `CANONICAL-PATH-MAP.json` marque `core.policy_kernel`
   `AMENDMENT_REQUIRED` (ISS-CAND-CA07-0002, décision non prise) ;
   `69-CORE-ARCHITECTURE-DESIGN-v1.0.0.md` distingue explicitement
   « identity » (tenant/principal/session registry) de `core/src/auth`
   (authentication assurance seulement — vérifié : ce dossier ne contient
   que `admin_gate.py`+`totp.py`) ; `planes.py` exclut délibérément TRUST
   (couvre 4 des 6 agrégats CORE) de `CorePlane`. Résolu par une
   SENTINELLE explicite (`status=AMENDMENT_REQUIRED`), jamais une
   supposition.
3. **`owner_of()` retourne le nom LONG** (`M5-financecore`), pas le nom
   court (`M5`) — seul identifiant de module réellement enregistré
   (`registries/modules.yaml`), cohérence interne du record (le
   `write_port` associé référence déjà le nom long), et immunité au piège
   du préfixe pour tout consommateur aval.
4. **La table d'alias est VÉRIFIÉE contre les deux CSV à chaque appel**
   (même discipline que `InventaireDeriveRefuse` dans
   `path_and_authority_map.py`) — un renommage futur de module (CSV muté
   sans que cette table codée en dur ne suive) est refusé nommément
   plutôt que de produire une carte fausse en silence.
5. **La colonne `prohibited_authority` du CSV source** (« Must not own
   M1-M10 business truth », ligne CORE) est PERDUE dans le CSV dérivé
   (`business_authority_map.py` n'écrit que 4 colonnes) — ré-affirmée ici
   comme le fondement de la garde d'unicité ci-dessous (docstring
   `AgregatConflitProprietaire`), pas comme liste séparée à re-vérifier
   (le mécanisme qui l'applique EST la garde d'unicité générale : un
   agrégat déjà attribué à M1-M10 que CORE tenterait de revendiquer serait
   un conflit à deux propriétaires, cas RED #2 ET #3 avec le MÊME
   mécanisme).
6. **`AUTHORITY-MAP.csv` utilisé UNIQUEMENT comme source de ports**,
   filtré aux lignes où `owner == aggregate` (les 10 lignes M1-M10,
   tautologiques par conception de C00-004) — les 4 lignes CORE
   (`owner=CORE, aggregate∈{auth,authz,config,opsys_core}`) ne matchent
   jamais ce filtre et sont donc naturellement exclues, sans branche
   spéciale : `"CORE" not in ports_par_owner_long` déclenche la sentinelle
   du point 2 de façon générique (vaudrait pareil pour un futur M11 sans
   port résolu).
7. **Vérification d'unicité INDÉPENDANTE du chargeur amont** —
   `business_authority_map.py` garantit déjà l'absence de conflit
   deux-owners dans SA sortie (testé), mais ce registre ne présume pas
   que le fichier sur disque est nécessairement le résultat fiable de ce
   générateur (édition manuelle, régression future) : la garde est
   refaite ici, sur les données réellement chargées.

Ne PAS importer `audit/core-baseline/business_authority_map.py` (effet de
bord `sys.path.insert` au niveau module, dépendance non packagée depuis
`opsys-core` distribuable) — les CSV sont lus directement, comme le
demande la spec."""
from __future__ import annotations

import csv
from pathlib import Path

from .model import PREFIXE_NON_RESOLU, AuthorityRecord

# 3 niveaux au-dessus de ce fichier = racine du dépôt (authority -> src ->
# core -> racine). Paramétrable en argument de `construire_registre` pour
# les tests (cf. docstring point 4 : jamais de chemin figé non testable).
_RACINE_DEPOT = Path(__file__).resolve().parents[4]
CHEMIN_CARTE_CHEMINS = _RACINE_DEPOT / "audit" / "core-baseline" / "AUTHORITY-MAP.csv"
CHEMIN_CARTE_METIER = _RACINE_DEPOT / "audit" / "core-baseline" / "BUSINESS-AUTHORITY-MAP-M1-M10.csv"

# Table d'alias nom-court (carte métier) -> nom-long (carte des chemins,
# `registries/modules.yaml`). CORE est identique dans les deux cartes.
# Vérifiée contre les deux CSV réels à CHAQUE appel de
# `construire_registre` — jamais supposée statique (point 4 ci-dessus).
ALIAS_MODULES = {
    "CORE": "CORE",
    "M1": "M1-front-office",
    "M2": "M2-revenue-crm",
    "M3": "M3-estimation",
    "M4": "M4-field-ops",
    "M5": "M5-financecore",
    "M6": "M6-material-control",
    "M7": "M7-marketing",
    "M8": "M8-analytics",
    "M9": "M9-strategic-intelligence",
    "M10": "M10-memoire",
}


class AliasInconnu(Exception):
    """Un owner (nom court) de la carte métier n'a pas d'entrée dans
    `ALIAS_MODULES` — refusé plutôt que d'inventer une correspondance."""


class TableAliasPerimee(Exception):
    """`ALIAS_MODULES` (codée en dur) ne correspond plus aux owners RÉELS
    trouvés dans les deux CSV — un module renommé sans que la table ne
    suive produirait une carte fausse en silence, refusé nommément."""


class AgregatConflitProprietaire(Exception):
    """Deux lignes de la carte métier attribuent le même agrégat à deux
    owners (noms longs) DIFFÉRENTS — invariant fondateur, sourcé
    verbatim sur la ligne CORE du CSV source ratifié (`sources/
    continuity/matrices/RF01-W11-AUTHORITY-MAP-M1-M10.csv`, colonne
    `prohibited_authority` : « Must not create a second business
    authority »). Couvre à la fois le cas RED #3 (« deux writers sur un
    agrégat sont rejetés ») et le cas RED #2 (« Core ne peut pas
    s'enregistrer comme writer métier » — CORE tentant de revendiquer un
    agrégat déjà attribué à M1-M10 EST une instance de ce conflit)."""


class AgregatInconnu(Exception):
    """`owner_of()`/`record_of()` appelé sur un agrégat absent des deux
    cartes ratifiées — refuse plutôt que de deviner un propriétaire."""


def _charger_ports_par_owner_long(chemin: Path) -> dict[str, tuple[str, str]]:
    """Ne garde que les lignes où `owner == aggregate` (les 10 lignes
    M1-M10, tautologiques par conception de C00-004) — les 4 lignes CORE
    (`owner=CORE`, `aggregate` = un chemin de code) ne matchent jamais et
    sont donc exclues sans branche spéciale (point 6 du docstring
    module)."""
    ports: dict[str, tuple[str, str]] = {}
    with chemin.open("r", encoding="utf-8", newline="") as f:
        for ligne in csv.DictReader(f):
            if ligne["owner"] == ligne["aggregate"]:
                ports[ligne["owner"]] = (ligne["read_port"], ligne["write_port"])
    return ports


def _charger_agregats_metier(chemin: Path) -> tuple[tuple[str, str], ...]:
    """Retourne `(aggregate, owner_court)` pour chacune des 63 lignes,
    dans l'ordre du fichier — le CSV dérivé (chore PR #501) garantit déjà
    l'absence de conflit deux-owners dans sa propre sortie ; ce chargeur
    ne fait que LIRE, la vérification d'unicité est refaite indépendamment
    par `construire_registre` (point 7 du docstring module)."""
    with chemin.open("r", encoding="utf-8", newline="") as f:
        return tuple((ligne["aggregate"], ligne["owner"]) for ligne in csv.DictReader(f))


def _verifier_table_alias(alias: dict[str, str], owners_longs_reels: set[str], owners_courts_reels: set[str]) -> None:
    for owner_court in owners_courts_reels:
        if owner_court not in alias:
            raise AliasInconnu(f"owner (nom court) {owner_court!r} absent de la table d'alias {sorted(alias)}")
    # Chaque valeur non-CORE de la table doit référencer un owner long
    # RÉELLEMENT présent parmi les 10 lignes M1-M10 (CORE est exempté :
    # il n'a jamais de ligne owner==aggregate, cf. point 6).
    for owner_court, owner_long in alias.items():
        if owner_court == "CORE":
            continue
        if owner_long not in owners_longs_reels:
            raise TableAliasPerimee(
                f"alias {owner_court!r} -> {owner_long!r} mais {owner_long!r} absent des owners "
                f"réels de la carte des chemins {sorted(owners_longs_reels)}"
            )
    # Chaque owner long réel doit être référencé par au moins un alias —
    # sinon un module existe dans la carte des chemins mais la table
    # d'alias l'ignore (renommage/ajout non répercuté).
    valeurs_alias = set(alias.values())
    for owner_long in owners_longs_reels:
        if owner_long not in valeurs_alias:
            raise TableAliasPerimee(
                f"owner long {owner_long!r} présent dans la carte des chemins mais absent de la table "
                f"d'alias (valeurs actuelles : {sorted(valeurs_alias)})"
            )


class AuthorityRegistry:
    """Registre d'autorité construit — n'expose que des métadonnées
    d'autorité (point « exposer seulement métadonnées d'autorité » de la
    spec), jamais de logique métier M1-M10."""

    def __init__(self, records: tuple[AuthorityRecord, ...]) -> None:
        self._records = records
        self._par_aggregate = {r.aggregate: r for r in records}

    def __len__(self) -> int:
        return len(self._records)

    def records(self) -> tuple[AuthorityRecord, ...]:
        return self._records

    def record_of(self, aggregate: str) -> AuthorityRecord:
        record = self._par_aggregate.get(aggregate)
        if record is None:
            raise AgregatInconnu(f"agrégat non enregistré dans le registre d'autorité : {aggregate!r}")
        return record

    def owner_of(self, aggregate: str) -> str:
        return self.record_of(aggregate).owner


def construire_registre(
    chemin_carte_chemins: Path = CHEMIN_CARTE_CHEMINS,
    chemin_carte_metier: Path = CHEMIN_CARTE_METIER,
    alias: dict[str, str] | None = None,
) -> AuthorityRegistry:
    table_alias = alias if alias is not None else ALIAS_MODULES

    ports_par_owner_long = _charger_ports_par_owner_long(chemin_carte_chemins)
    lignes_metier = _charger_agregats_metier(chemin_carte_metier)

    owners_courts_reels = {owner_court for _, owner_court in lignes_metier}
    _verifier_table_alias(table_alias, set(ports_par_owner_long), owners_courts_reels)

    records: list[AuthorityRecord] = []
    proprietaire_par_aggregat: dict[str, str] = {}

    for aggregate, owner_court in lignes_metier:
        # `_verifier_table_alias` ci-dessus a déjà validé, EXHAUSTIVEMENT,
        # que chaque owner_court de `owners_courts_reels` (= tous les
        # owner_court de `lignes_metier`) est une clé de `table_alias` —
        # mutation-proof a confirmé qu'une garde dupliquée ICI ne peut
        # jamais être atteinte (owner_court absent lèverait déjà plus
        # haut) : `table_alias[owner_court]` est donc une indexation
        # sûre, pas un `.get()` défensif qui masquerait une régression de
        # la garde amont.
        owner_long = table_alias[owner_court]

        proprietaire_existant = proprietaire_par_aggregat.get(aggregate)
        if proprietaire_existant is not None and proprietaire_existant != owner_long:
            raise AgregatConflitProprietaire(
                f"agrégat {aggregate!r} déjà attribué à {proprietaire_existant!r}, "
                f"{owner_long!r} tente également de le revendiquer"
            )
        proprietaire_par_aggregat[aggregate] = owner_long

        if owner_long in ports_par_owner_long:
            read_port, write_port = ports_par_owner_long[owner_long]
            status = "RESOLVED"
        else:
            read_port = write_port = (
                f"{PREFIXE_NON_RESOLU} — aucun chemin ratifié pour un agrégat métier {owner_long} "
                f"(cf. audit/core-baseline/CANONICAL-PATH-MAP.json, AMENDMENT_REQUIRED, ISS-CAND-CA07-0002)"
            )
            status = "AMENDMENT_REQUIRED"

        records.append(AuthorityRecord(
            aggregate=aggregate, owner=owner_long,
            read_port=read_port, write_port=write_port, status=status,
        ))

    return AuthorityRegistry(tuple(records))
