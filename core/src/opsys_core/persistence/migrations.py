"""Moteur de migrations expand/contract, VALIDATEUR PUREMENT STATIQUE (C05-002).

`validate_migration(plan, sql) -> None` n'ouvre AUCUNE connexion, n'importe
ni `psycopg` ni `connection.py` — c'est le nom même de la fonction
(« validate », pas « apply »/« run ») qui porte cette discipline. Confirmé
par revue d'architecture AVANT code (subagent architecte, Claude Opus 5
natif) : aucune Sortie de cette tâche ne prévoit de table de suivi ni de
connexion réelle, C05-003 (unité de travail transactionnelle) et C05-004
(premier fichier .sql réel) sont les tâches qui exécutent, pas celle-ci.

« Dry-run » et « rollback » (bornes d'implémentation) sont donc rendus
SANS EXÉCUTION :
  - dry-run = `validate_migration` lui-même (verdict sans toucher la base).
  - rollback = `MigrationPlan.reversible` + exigence d'une section de
    retour arrière documentée dans core/migrations/README.md pour toute
    migration destructive future — cf. README pour la convention.

3 cas RED obligatoires (tasks/C05-002.md), chacun un détecteur DÉDIÉ :
  1. bloquer DROP/RENAME/TRUNCATE destructif SAUF si `plan.phase ==
     "contract"` ET `plan.reversible is True` ET le SQL porte un marqueur
     d'autorisation contenant `plan.version` (non copiable-collable d'une
     migration à l'autre) — LISTE BLANCHE par construction (le refus est
     le défaut), jamais une liste noire de verbes qui laisserait passer
     l'inconnu (même discipline que `connection.py::_detecter_cible_non_
     postgresql`, C05-001 : « une liste noire serait fail-open »).
  2. checksum obligatoire, en DEUX gardes séparées (revue d'architecture
     AVANT code : une seule classe d'exception rendrait une mutation du
     contrôle de FORME indétectable, la branche CONTENU lèverait quand
     même) — forme (64 hex minuscules) à la CONSTRUCTION de MigrationPlan
     (fail fast, comme DatabaseConfig C05-001), contenu (`==
     sha256(sql)` RÉEL, pas seulement présent) dans `validate_migration`
     (seul point qui voit `sql`).
  3. idempotence PURE (aucun état de suivi, aucune Sortie de cette tâche
     ne prévoit de table `schema_migrations`) : `validate_migration`
     exige la ré-exécutabilité PAR CONSTRUCTION du SQL (CREATE sans IF
     NOT EXISTS, DROP sans IF EXISTS, INSERT sans ON CONFLICT ⇒ refusés)
     — deux appels successifs avec `(plan, sql)` identiques donnent
     TOUJOURS le même verdict, aucun effet observable (aucun état
     module-level, même discipline que composition.py/provider_registry.py
     C04-004).

RÉVISÉ après revue scellée tour 1 (civ_review, google/kimi-k3/deepseek) :
REJECT de Kimi-K3 (2 objections MAJEURES) + 2 objections mineures
DeepSeek — LES 6 VÉRIFIÉES VRAIES par reproduction directe AVANT
correction (CLAIMS UNVERIFIED, jamais acceptées sur la seule autorité
des reviewers). Corrections apportées :
  a. Idempotence CREATE/DROP redessinée en PAR-INSTRUCTION (découpage
     par ';', heuristique bornée) plutôt qu'un motif fixe CREATE suivi
     immédiatement de (TABLE|INDEX), qui ratait `CREATE UNIQUE INDEX`/`CREATE SEQUENCE`/
     `CREATE SCHEMA`/`CREATE EXTENSION` sans IF NOT EXISTS (Kimi-K3
     MAJEURE, reproduit : aucun match sur "CREATE UNIQUE INDEX idx ON
     t(c);"). Nouvelle règle : toute instruction contenant CREATE doit
     contenir IF NOT EXISTS QUELQUE PART dans CETTE MÊME instruction —
     robuste à l'ordre des modifiers (UNIQUE/CONCURRENTLY/etc.).
  b. INSERT/ON CONFLICT redessiné en PAR-INSTRUCTION pour la même
     raison : un seul ON CONFLICT n'importe où dans le fichier
     blanchissait TOUS les INSERT INTO (Kimi-K3 MAJEURE, reproduit :
     2e INSERT sans ON CONFLICT accepté à tort si le 1er en a un).
  c. Marqueur d'autorisation : passage d'un `in sql` (sous-chaîne) à un
     motif ancré par une lookahead négative sur caractère non-espace —
     ferme la collision par PRÉFIXE de version (Kimi-K3 mineure,
     reproduit : marqueur de "0001" matchait dans le SQL de "0001_
     hotfix").
  d. Checksum : `.match()` + `^...$` remplacé par `.fullmatch()` sans
     ancres — ferme le cas où `$` matche avant un saut de ligne final,
     acceptant à tort 65 caractères (Kimi-K3 mineure, reproduit).
  e. Commentaires `-- ...` retirés AVANT toute détection de mots-clés
     (destructif ET idempotence) — un mot destructif MENTIONNÉ dans un
     commentaire ne doit jamais déclencher un refus (DeepSeek mineure,
     reproduit). Limitation ACCEPTÉE et documentée : les littéraux de
     chaîne ('...') ne sont PAS retirés (parseur SQL complet hors
     périmètre, même discipline que les blocs DO $$...$$).
  f. INSERT ... WHERE NOT EXISTS (forme idempotente alternative sans
     ON CONFLICT) : DÉLIBÉRÉMENT PAS reconnue comme équivalente à ON
     CONFLICT (DeepSeek mineure, reproduit — CONFIRMÉE VRAIE mais
     NON corrigée) — biais conservateur ASSUMÉ : le faux négatif (SQL
     sûr rejeté) est la direction SÛRE du fail-closed, contrairement à
     un faux positif qui laisserait passer du SQL non idempotent.
     Élargir la reconnaissance de formes « prouvant » l'idempotence
     ajouterait de la surface de motif pour un bénéfice de confort,
     pas de sûreté — nommé en clair plutôt que corrigé.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# Vocabulaire de phases FERMÉ — zéro normalisation (.strip()/.lower()
# élargirait silencieusement l'autorisation, revue d'architecture AVANT
# code, point (c)). Recoupé mécaniquement avec core/migrations/README.md
# par test_readme_vocabulaire_phases_bijectif_avec_le_code (PAS test_
# dependency_rules_toml_couvre_migrations_sans_modification, qui ne lit
# jamais le README — dérive documentaire corrigée, revue scellée tour 2,
# Kimi-K3 mineure confirmée vraie).
_VOCABULAIRE_PHASES = frozenset({"expand", "backfill", "switch", "contract"})

# fullmatch() SANS ancres ^/$ — `$` matche aussi juste avant un `\n`
# terminal en Python (comportement documenté), ce qui acceptait à tort
# un checksum de 65 caractères (64 hex + saut de ligne final). Revue
# scellée tour 1, Kimi-K3 mineure, reproduit et confirmé vrai.
_CHECKSUM_RE = re.compile(r"[0-9a-f]{64}")


def _analyser_sql(sql: str) -> tuple[str, str]:
    """Analyse le SQL en UN SEUL passage : retourne `(sql_neutralise,
    commentaires)`.

    `sql_neutralise` a le CONTENU des littéraux de chaîne (`'...'`),
    des identificateurs délimités (`"..."`), des chaînes d'échappement
    PostgreSQL (`E'...'`) ET des commentaires (`--...fin-de-ligne` et
    `/* ... */`, IMBRICABLES) remplacés par des espaces — LONGUEUR ET
    POSITIONS PRÉSERVÉES (jamais une suppression). Utilisé pour TOUTE
    détection de mots-clés (destructif, idempotence) ET pour
    `_decouper_instructions` : un mot-clé qui n'apparaît QUE dans un
    littéral, un identificateur ou un commentaire ne doit JAMAIS
    déclencher, et un `;` à l'intérieur ne doit JAMAIS scinder une
    instruction à tort.

    `commentaires` est la CONCATÉNATION des seuls textes de commentaires
    `--` RÉELS (hors littéraux/identificateurs/blocs) — utilisé
    EXCLUSIVEMENT pour chercher le marqueur d'autorisation, qui est
    destiné à y vivre. Les commentaires BLOC (`/* */`) n'y contribuent
    PAS (limitation ACCEPTÉE : le marqueur doit vivre dans un
    commentaire `--`, jamais un bloc — non testé comme forme valide,
    documenté ici plutôt qu'implicite).

    RÉVISÉ après revue scellée tour 3 (Kimi-K3 REJECT, 3 objections
    MAJEURES) : la version tour 2 (guillemets simples seuls) introduisait
    3 NOUVEAUX fail-open, TOUS confirmés vrais par reproduction directe
    AVANT correction (CLAIMS UNVERIFIED) :
      1. Un identificateur délimité `"it's"` contenant une apostrophe
         basculait `dans_chaine` à tort, neutralisant tout le SQL réel
         qui suivait (ex. `SELECT "it's" FROM t; DROP TABLE x;` → DROP
         invisible). Corrigé : état DÉDIÉ pour `"..."` (`""` = guillemet
         double échappé, même convention que `''` pour les chaînes),
         un `'` À L'INTÉRIEUR d'un identificateur ne bascule plus rien.
      2. `E'it\\'s'` (chaîne d'échappement PostgreSQL, `\\'` = apostrophe
         échappée) désynchronisait la machine (qui ne connaissait que
         l'échappement `''`, pas `\\`), neutralisant le SQL réel après.
         Corrigé : état DÉDIÉ pour `E'...'`/`e'...'`, `\\<caractère>`
         consommé comme une paire échappée AVANT de tester la fermeture.
      3. `/* c -- */ DROP TABLE x;` : le `--` À L'INTÉRIEUR d'un
         commentaire bloc faisait avaler tout le reste de la ligne
         (y compris le SQL réel après le `*/`). Corrigé : état DÉDIÉ
         pour `/* ... */` AVEC compteur de profondeur (PostgreSQL les
         imbrique réellement), fermé sur le `*/` correspondant, jamais
         sur un `--` interne.

    Limitation ACCEPTÉE et documentée (inchangée depuis le tour 1) : le
    dollar-quoting PostgreSQL (`$$...$$`/`$tag$...$tag$`) n'est PAS géré
    — hors périmètre, un parseur SQL complet serait nécessaire (même
    discipline que les autres formes déjà exclues)."""
    neutre: list[str] = []
    commentaires: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]

        # Chaîne d'échappement E'...'/e'...' (PostgreSQL) : \<caractère>
        # est TOUJOURS consommé comme une paire échappée (jamais testé
        # comme fermeture), '' reste aussi un échappement valide en
        # complément (les deux formes sont légales dans une E-string).
        if c in "Ee" and i + 1 < n and sql[i + 1] == "'":
            debut = i
            neutre.append(c)
            neutre.append("'")
            i += 2
            fermee = False
            while i < n:
                cc = sql[i]
                if cc == "\\" and i + 1 < n:
                    suivant = sql[i + 1]
                    neutre.append(" ")
                    neutre.append(suivant if suivant == "\n" else " ")
                    i += 2
                    continue
                if cc == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        neutre.append("  ")
                        i += 2
                        continue
                    neutre.append(cc)
                    i += 1
                    fermee = True
                    break
                neutre.append(cc if cc == "\n" else " ")
                i += 1
            if not fermee:
                raise SqlMalforme(f"chaîne d'échappement E'...' jamais fermée (débute à la position {debut})")
            continue

        # Littéral '...' standard : '' est l'unique échappement
        # (comportement PostgreSQL par défaut, standard_conforming_
        # strings=on — le backslash n'y est PAS spécial, contrairement
        # aux E-strings ci-dessus).
        if c == "'":
            debut = i
            neutre.append(c)
            i += 1
            fermee = False
            while i < n:
                cc = sql[i]
                if cc == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        neutre.append("  ")
                        i += 2
                        continue
                    neutre.append(cc)
                    i += 1
                    fermee = True
                    break
                neutre.append(cc if cc == "\n" else " ")
                i += 1
            if not fermee:
                raise SqlMalforme(f"littéral de chaîne '...' jamais fermé (débute à la position {debut})")
            continue

        # Identificateur délimité "..." : "" est l'échappement, ÉTAT
        # DÉDIÉ (un ' à l'intérieur ne bascule plus vers l'état chaîne).
        if c == '"':
            debut = i
            neutre.append(c)
            i += 1
            fermee = False
            while i < n:
                cc = sql[i]
                if cc == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        neutre.append('""')
                        i += 2
                        continue
                    neutre.append(cc)
                    i += 1
                    fermee = True
                    break
                neutre.append(cc if cc == "\n" else " ")
                i += 1
            if not fermee:
                raise SqlMalforme(f'identificateur délimité "..." jamais fermé (débute à la position {debut})')
            continue

        # Commentaire bloc /* ... */ — IMBRICABLE en PostgreSQL réel,
        # compteur de profondeur : un '--' interne ne le termine JAMAIS,
        # seul le '*/' correspondant le fait.
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            debut = i
            profondeur = 1
            i += 2
            while i < n and profondeur > 0:
                if sql[i] == "/" and i + 1 < n and sql[i + 1] == "*":
                    profondeur += 1
                    i += 2
                    continue
                if sql[i] == "*" and i + 1 < n and sql[i + 1] == "/":
                    profondeur -= 1
                    i += 2
                    continue
                i += 1
            if profondeur > 0:
                raise SqlMalforme(f"commentaire bloc /* ... */ jamais fermé (débute à la position {debut})")
            fin = i
            for k in range(debut, fin):
                neutre.append(sql[k] if sql[k] == "\n" else " ")
            continue

        # Commentaire ligne --...fin-de-ligne (hors chaînes/
        # identificateurs/blocs, déjà exclus par les branches ci-dessus).
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            fin = sql.find("\n", i)
            fin_reel = fin if fin != -1 else n
            commentaires.append(sql[i:fin_reel])
            neutre.append(" " * (fin_reel - i))
            i = fin_reel
            continue

        neutre.append(c)
        i += 1
    return "".join(neutre), "\n".join(commentaires)


def _decouper_instructions(sql_neutralise: str) -> list[str]:
    """Découpage par ';' du SQL DÉJÀ NEUTRALISÉ (`_analyser_sql`) —
    heuristique BORNÉE, pas un parseur SQL complet. Le dollar-quoting
    (`$$...$$`) n'est PAS géré : limitation ACCEPTÉE et documentée, même
    périmètre que les autres formes déjà exclues (irréductible sans
    parseur+exécution SQL réel)."""
    return [i.strip() for i in sql_neutralise.split(";") if i.strip()]


# Token-level, insensible à la casse : `ALTER TABLE t DROP col` est valide
# en PostgreSQL SANS le mot COLUMN — un motif `DROP\s+COLUMN` raterait ce
# cas, `\bDROP\b` non (revue d'architecture AVANT code, point 1).
_MOTIFS_DESTRUCTIFS = re.compile(r"\b(DROP|TRUNCATE|RENAME)\b", re.IGNORECASE)

# search() (pas finditer()) : détection booléenne « au moins une occurrence
# quelque part DANS L'INSTRUCTION COURANTE », jamais une énumération
# multi-match traitée différemment par occurrence — le bug de classe
# « search() en boucle masque les occurrences suivantes » (déjà mesuré
# dans check_module_isolation.py) ne s'applique pas ici, un seul appel
# par instruction découpée, hors boucle interne.
#
# PAR-INSTRUCTION (pas un seul motif global sur tout le fichier) : un
# motif fixe `CREATE\s+(TABLE|INDEX)` ratait `CREATE UNIQUE INDEX`/
# `CREATE SEQUENCE`/`CREATE SCHEMA`/`CREATE EXTENSION` sans IF NOT
# EXISTS, et un seul `ON CONFLICT` n'importe où dans un fichier
# multi-instructions blanchissait TOUS les INSERT INTO — revue scellée
# tour 1, Kimi-K3 MAJEURE ×2, reproduites et confirmées vraies. Règle
# robuste : toute instruction contenant CREATE/DROP/INSERT INTO doit
# porter sa PROPRE clause IF NOT EXISTS/IF EXISTS/ON CONFLICT, ancrée
# à l'instruction découpée, pas au fichier entier.
_MOTIF_CREATE = re.compile(r"\bCREATE\b", re.IGNORECASE)
_MOTIF_IF_NOT_EXISTS = re.compile(r"\bIF\s+NOT\s+EXISTS\b", re.IGNORECASE)
_MOTIF_DROP = re.compile(r"\bDROP\b", re.IGNORECASE)
_MOTIF_IF_EXISTS = re.compile(r"\bIF\s+EXISTS\b", re.IGNORECASE)
_INSERT_INTO = re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)
_ON_CONFLICT = re.compile(r"\bON\s+CONFLICT\b", re.IGNORECASE)


def _marqueur_autorisation(version: str) -> re.Pattern[str]:
    """Marqueur d'autorisation LIÉ à la version — copier un marqueur
    d'une autre migration ne fonctionne jamais (revue d'architecture
    AVANT code, point 1 : « non copiable-collable d'une migration à
    l'autre »). Motif COMPILÉ (pas une chaîne pour `in`) : une
    lookahead négative sur caractère non-espace après la version ferme
    la collision par PRÉFIXE (ex. le marqueur de la version "0001" ne
    doit JAMAIS matcher dans un SQL portant "AUTORISATION-CONTRACT:
    0001_hotfix" — sans cette garde, "0001" est un préfixe valide de
    "0001_hotfix" et le `in` sous-chaîne laissait passer. Revue scellée
    tour 1, Kimi-K3 mineure, reproduit et confirmé vrai)."""
    return re.compile(rf"AUTORISATION-CONTRACT:{re.escape(version)}(?!\S)")


class PhaseInvalide(ValueError):
    """Levée par `MigrationPlan.__post_init__` quand `phase` n'appartient
    pas au vocabulaire fermé — AUCUNE normalisation avant comparaison."""

    def __init__(self, phase: object) -> None:
        super().__init__(
            f"phase {phase!r} hors vocabulaire fermé {sorted(_VOCABULAIRE_PHASES)}"
        )
        self.code = "VALIDATION"


class ReversibleNonBooleen(ValueError):
    """Levée par `MigrationPlan.__post_init__` quand `reversible` n'est
    pas strictement un `bool`. Piège INVERSÉ de C05-001 (`config.py` :
    `bool` est un sous-type d'`int`, exclu pour ne pas être PASSÉ comme
    entier) : ici une valeur non-bool truthy (ex. `reversible="false"`,
    une chaîne non vide) OUVRIRAIT la seule autorisation destructive du
    système si elle n'était pas rejetée explicitement — revue
    d'architecture AVANT code, point 6(a)."""

    def __init__(self, valeur: object) -> None:
        super().__init__(f"reversible doit être un bool strict (reçu {valeur!r})")
        self.code = "VALIDATION"


class SqlMalforme(ValueError):
    """Levée par `_analyser_sql` (donc par `validate_migration`) quand le
    SQL contient un littéral `'...'`, un identificateur `"..."`, une
    chaîne d'échappement `E'...'` ou un commentaire bloc `/* ... */`
    JAMAIS FERMÉ. Refus FAIL-CLOSED plutôt que neutraliser
    silencieusement tout le reste du SQL (qui pourrait contenir un verbe
    destructif RÉEL, invisible derrière la construction non fermée —
    revue scellée C05-002, finding confirmé vrai par mesure directe :
    les 4 formes partageaient ce même angle mort). Un SQL malformé de
    cette façon ne s'exécuterait de toute façon jamais dans PostgreSQL
    réel (erreur de syntaxe) — l'accepter comme « validé » par ce
    moteur serait un faux DONE."""

    def __init__(self, motif: str) -> None:
        super().__init__(f"SQL malformé : {motif}")
        self.code = "VALIDATION"


class ChecksumFormatInvalide(ValueError):
    """Levée par `MigrationPlan.__post_init__` quand `checksum` n'est pas
    EXACTEMENT 64 caractères hexadécimaux minuscules — garde de FORME
    uniquement, distincte de `ChecksumIncorrect` (garde de CONTENU) pour
    qu'une mutation de l'une des deux gardes reste détectable
    séparément. `fullmatch()` (pas `match()` + ancres `^$`) : `$` seul
    matche aussi juste avant un `\\n` terminal en Python."""

    def __init__(self, checksum: object) -> None:
        super().__init__(
            f"checksum doit être exactement 64 caractères hexadécimaux minuscules (reçu {checksum!r})"
        )
        self.code = "VALIDATION"


class ChecksumIncorrect(ValueError):
    """Levée par `validate_migration` quand `plan.checksum` ne correspond
    PAS à `sha256(sql)` réel — garde de CONTENU, vit ici (seul point qui
    voit `sql`), pas dans `MigrationPlan` (qui ne connaît que le
    checksum déclaré, jamais le SQL réel avant l'appel)."""

    def __init__(self) -> None:
        super().__init__("checksum déclaré ne correspond pas au sha256 réel du SQL")
        self.code = "CONFLICT"


class MigrationDestructiveRefusee(ValueError):
    """Levée par `validate_migration` quand le SQL contient un verbe
    destructif (DROP/TRUNCATE/RENAME) sans autorisation explicite
    complète (phase contract + reversible=True + marqueur lié à la
    version). LISTE BLANCHE par construction : le refus est le défaut,
    l'autorisation est l'exception qui doit être prouvée."""

    def __init__(self, motif: str) -> None:
        super().__init__(f"migration destructive refusée : {motif}")
        self.code = "POLICY_DENIED"
        self.motif = motif


class MigrationNonIdempotente(ValueError):
    """Levée par `validate_migration` quand une INSTRUCTION du SQL n'est
    pas ré-exécutable PAR CONSTRUCTION (CREATE sans IF NOT EXISTS, DROP
    sans IF EXISTS, INSERT sans ON CONFLICT — vérifié PAR INSTRUCTION,
    pas globalement sur tout le fichier). Propriété STATIQUE du texte
    SQL — aucune connexion, aucun état de suivi requis."""

    def __init__(self, motif: str) -> None:
        super().__init__(f"migration non idempotente par construction : {motif}")
        self.code = "VALIDATION"
        self.motif = motif


@dataclass(frozen=True)
class MigrationPlan:
    version: str
    phase: str
    checksum: str
    reversible: bool

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version doit être une chaîne non vide")

        if self.phase not in _VOCABULAIRE_PHASES:
            raise PhaseInvalide(self.phase)

        # isinstance(reversible, bool) STRICT — AVANT toute autre garde,
        # même position défensive que le piège bool de C05-001.
        if not isinstance(self.reversible, bool):
            raise ReversibleNonBooleen(self.reversible)

        if not isinstance(self.checksum, str) or _CHECKSUM_RE.fullmatch(self.checksum) is None:
            raise ChecksumFormatInvalide(self.checksum)


def validate_migration(plan: MigrationPlan, sql: str) -> None:
    """Validateur PUREMENT STATIQUE — aucune connexion, aucun état
    module-level, aucun effet observable. Deux appels successifs avec
    `(plan, sql)` identiques donnent TOUJOURS le même verdict (preuve
    d'idempotence par pureté, cas RED 3)."""
    # 1) Contenu du checksum — sur le SQL ORIGINAL (le checksum couvre
    # les octets exacts du fichier, commentaires inclus), AVANT toute
    # autre garde de contenu (fail fast sur l'intégrité du texte SQL).
    checksum_reel = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    if checksum_reel != plan.checksum:
        raise ChecksumIncorrect()

    # Littéraux de chaîne ET commentaires neutralisés AVANT la détection
    # de mots-clés (destructif ET idempotence) en un seul passage — un
    # mot mentionné dans un commentaire OU une valeur littérale n'est
    # jamais un verbe SQL réel (revue scellée tour 1 DeepSeek + tour 2
    # Kimi-K3, toutes deux confirmées vraies). Le marqueur d'autorisation,
    # lui, est volontairement DESTINÉ à vivre dans un commentaire
    # (`-- AUTORISATION-CONTRACT:...`) : sa présence est vérifiée
    # UNIQUEMENT dans les commentaires extraits, jamais dans un littéral
    # de chaîne (revue scellée tour 2, Kimi-K3 mineure confirmée vraie :
    # un marqueur dans une VALEUR, pas un commentaire, autorisait aussi
    # à tort avant ce correctif).
    sql_neutralise, commentaires = _analyser_sql(sql)

    # 2) Destructif : liste blanche — refusé SAUF autorisation complète.
    if _MOTIFS_DESTRUCTIFS.search(sql_neutralise) is not None:
        motif_marqueur = _marqueur_autorisation(plan.version)
        autorise = (
            plan.phase == "contract"
            and plan.reversible is True
            and motif_marqueur.search(commentaires) is not None
        )
        if not autorise:
            raise MigrationDestructiveRefusee(
                "verbe destructif (DROP/TRUNCATE/RENAME) détecté sans "
                "autorisation complète (phase=contract, reversible=True, "
                f"marqueur pour la version {plan.version!r} présent dans un commentaire -- du SQL)"
            )

    # 3) Idempotence par construction — PAR INSTRUCTION (découpage par
    # ';' du SQL NEUTRALISÉ), pas un motif global sur tout le fichier.
    for instruction in _decouper_instructions(sql_neutralise):
        if _MOTIF_CREATE.search(instruction) is not None and _MOTIF_IF_NOT_EXISTS.search(instruction) is None:
            raise MigrationNonIdempotente(f"CREATE sans IF NOT EXISTS : {instruction!r}")
        if _MOTIF_DROP.search(instruction) is not None and _MOTIF_IF_EXISTS.search(instruction) is None:
            raise MigrationNonIdempotente(f"DROP sans IF EXISTS : {instruction!r}")
        if _INSERT_INTO.search(instruction) is not None and _ON_CONFLICT.search(instruction) is None:
            raise MigrationNonIdempotente(f"INSERT INTO sans ON CONFLICT : {instruction!r}")
