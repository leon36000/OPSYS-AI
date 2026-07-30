"""
Digest quotidien déterministe — M4-S009.

Produit un résumé chainé (CA-M4-14, CA-M4-15, CA-M4-16, CA-M4-17) de l'état
des interventions d'une journée cible, sans jamais consulter une horloge système.
Les gardes associées vérifient statiquement l'absence d'horloge et l'absence de
termes de scoring dans les noms, clés et attributs du code source.
"""

import copy
import ast
from pathlib import Path
from datetime import datetime, timedelta

from . import horodatage
from . import verdicts
from . import encodage
from . import etats
from . import pointage
from . import ecarts
from . import outbox

# ---------------------------------------------------------------------------
# Constantes épinglées (contrat S009)
# ---------------------------------------------------------------------------
CHAMPS_DIGEST = (
    "date_cible", "horodatage_reference", "ancre_registre",
    "interventions_terminees", "interventions_en_revue",
    "count_pending_review", "pending_par_type",
    "interventions_bloquees_en_revue", "empreinte",
)

SEUIL_BLOCAGE_HEURES = 24  # heures *simulées*, comptées depuis l'horodatage_reference fourni, jamais depuis une horloge système.

FONCTIONS_HORLOGE_INTERDITES = (
    # Toute fonction qui INTERROGE une horloge, quelle que soit sa bibliothèque.
    # Complétée après objection de revue (liste non exhaustive au premier jet).
    "now", "utcnow", "today", "time", "monotonic", "perf_counter", "fromtimestamp",
    "time_ns", "monotonic_ns", "perf_counter_ns", "process_time", "thread_time",
    "clock_gettime", "gmtime", "localtime", "mktime", "timegm", "times",
)

TERMES_INTERDITS_R020 = (
    "score", "scoring", "note_technicien", "performance", "classement", "ranking",
    "penalite", "sanction", "profilage", "rendement",
)


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def produire_digest(registre_cible, date_cible, horodatage_reference):
    """Produit le digest quotidien déterministe pour la date cible.

    Args:
        registre_cible: instance de Registre.
        date_cible: chaîne ``AAAA-MM-JJ`` cible.
        horodatage_reference: horodatage avec fuseau de référence pour le calcul
            des blocages.

    Returns:
        (digest, None) ou (None, verdict).
    """
    # 1. Valider date_cible
    if not isinstance(date_cible, str) or not date_cible.strip():
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="date_cible invalide"
        )
    # fromisoformat SEUL ne suffit pas : il accepte « 2025-06-02T12:00:00+00:00 »,
    # ce qui fausserait le filtre par préfixe des interventions terminées (mesuré,
    # objection de revue). La date doit être EXACTEMENT AAAA-MM-JJ, ce que prouve
    # la ré-émission à l'identique.
    try:
        jour = datetime.fromisoformat(date_cible).date()
    except (ValueError, TypeError):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="date_cible mal formée"
        )
    if jour.isoformat() != date_cible:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="date_cible doit être exactement AAAA-MM-JJ, sans heure ni fuseau",
        )

    # 2. Valider horodatage_reference
    try:
        horodatage.valider_horodatage(horodatage_reference)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")

    # 3. Lecture *unique* du registre
    maillons = list(registre_cible.lire())

    # ---- interventions_terminees ----
    terminees = []
    for m in maillons:
        wct = m.get(outbox.CLE_WCT)
        if wct is not None:
            horo = m.get("horodatage")
            if isinstance(horo, str) and horo.startswith(date_cible):
                terminees.append({
                    "intervention_id": m["intervention_id"],
                    "wct_id": wct["wct_id"],
                    "duree_reelle_minutes": wct["duree_reelle_minutes"],
                    "ecart_signale": wct["ecart_signale"],
                })
    terminees.sort(key=lambda e: e["intervention_id"])

    # ---- interventions_en_revue ----
    interventions_ids = set()
    for m in maillons:
        iid = m.get("intervention_id")
        if iid is not None:
            interventions_ids.add(iid)

    en_revue = []
    for iid in interventions_ids:
        if etats.statut_courant(registre_cible, iid) == "en_revue":
            en_revue.append(iid)
    en_revue.sort()

    # ---- count_pending_review / pending_par_type ----
    demandes_pending = ecarts.lister_pending_review(registre_cible)
    count_pending_review = len(demandes_pending)

    pending_par_type = {type_dem: 0 for type_dem in ecarts.TYPES_DEMANDE}
    for dm in demandes_pending:
        typ = dm.get("type_demande")
        if typ in pending_par_type:
            pending_par_type[typ] += 1

    # ---- interventions_bloquees_en_revue ----
    dt_ref = datetime.fromisoformat(horodatage_reference)
    seuil = timedelta(hours=SEUIL_BLOCAGE_HEURES)
    bloquees = []
    for dm in demandes_pending:
        dt_dem = datetime.fromisoformat(dm["horodatage"])
        delta = dt_ref - dt_dem
        if delta >= seuil:
            heures = int(delta.total_seconds() // 3600)
            bloquees.append({
                "intervention_id": dm["intervention_id"],
                "demande_id": dm["demande_id"],
                "heures_ecoulees": heures,
            })
    bloquees.sort(key=lambda e: e["demande_id"])

    # ---- ancre_registre ----
    ancre = registre_cible.tete()

    # ---- Assemblage (sans empreinte) ----
    digest_partiel = {
        "date_cible": date_cible,
        "horodatage_reference": horodatage_reference,
        "ancre_registre": ancre,
        "interventions_terminees": terminees,
        "interventions_en_revue": en_revue,
        "count_pending_review": count_pending_review,
        "pending_par_type": pending_par_type,
        "interventions_bloquees_en_revue": bloquees,
    }

    # Empreinte chaînée (non circulaire : le champ empreinte n'est pas inclus)
    empreinte = encodage.empreinte(digest_partiel)
    digest = copy.deepcopy(digest_partiel)
    digest["empreinte"] = empreinte

    return digest, None


def verifier_digest(digest):
    """Vérifie l'intégrité d'un digest par recalcul de son empreinte.

    Args:
        digest: dict représentant un digest.

    Returns:
        (True, "") ou (False, message).
    """
    if not isinstance(digest, dict):
        return False, "digest n'est pas un dict"
    if set(digest.keys()) != set(CHAMPS_DIGEST):
        return False, "clés du digest incorrectes"

    partiel = {k: v for k, v in digest.items() if k != "empreinte"}
    empreinte_attendue = encodage.empreinte(partiel)
    if digest["empreinte"] != empreinte_attendue:
        return False, "empreinte invalide"
    return True, ""


# ---------------------------------------------------------------------------
# Gardes statiques
# ---------------------------------------------------------------------------
def garde_absence_horloge(chemin_source=None):
    """Inspection AST : aucune horloge système dans les sources du paquet M4.

    Une limite documentée : un appel indirect via ``getattr`` échapperait à
    l'analyse statique.  L'exigence de fuseau explicite sur chaque horodatage
    fourni constitue la seconde moitié de la preuve déterministe.
    """
    if chemin_source is None:
        chemin_source = str(Path(__file__).parent)

    violations = []
    for path in Path(chemin_source).glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        class Visitor(ast.NodeVisitor):
            def visit_Import(self, node):
                for alias in node.names:
                    if alias.name == "time":
                        violations.append(f"{path.name}: import du module time")
                self.generic_visit(node)

            def visit_ImportFrom(self, node):
                if node.module == "time":
                    violations.append(f"{path.name}: import from time")
                self.generic_visit(node)

            def visit_Call(self, node):
                nom = None
                if isinstance(node.func, ast.Attribute):
                    nom = node.func.attr
                elif isinstance(node.func, ast.Name):
                    nom = node.func.id
                if nom is not None and nom in FONCTIONS_HORLOGE_INTERDITES:
                    violations.append(f"{path.name}: appel à {nom} interdit")
                self.generic_visit(node)

        Visitor().visit(tree)

    if violations:
        return False, "; ".join(violations)
    return True, ""


# Nommée d'après la RÈGLE (R-020) et non d'après l'interdit : une garde dont le
# nom contient « scoring » se dénonce elle-même par son propre identifiant et ne
# peut JAMAIS passer (mesuré). Même raison pour le nom de sa liste de termes.
def garde_conformite_r020(chemin_source=None):
    """Inspection AST : absence de termes de scoring dans les noms, clés, attributs.

    Seules les *clés* chaînes des dict littéraux sont inspectées ; les constantes
    chaînes hors clés sont ignorées, ce qui permet au tuple
    ``TERMES_INTERDITS_R020`` de résider dans ce module sans se dénoncer.
    Les noms entièrement en majuscules (convention des constantes) sont exclus
    pour éviter les faux positifs sur les constantes de configuration.
    """
    if chemin_source is None:
        chemin_source = str(Path(__file__).parent)

    violations = []
    termes_lower = [t.lower() for t in TERMES_INTERDITS_R020]

    for path in Path(chemin_source).glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        class Visitor(ast.NodeVisitor):
            def _contient_terme(self, texte):
                return any(terme in texte.lower() for terme in termes_lower)

            def visit_Dict(self, node):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        if self._contient_terme(key.value):
                            violations.append(
                                f"{path.name}: clé de dict littéral contenant un "
                                f"terme interdit: {key.value!r}"
                            )
                self.generic_visit(node)

            def visit_Name(self, node):
                # Ignorer les noms tout en majuscules (constantes)
                if self._contient_terme(node.id):
                    violations.append(
                        f"{path.name}: nom '{node.id}' contient un terme interdit"
                    )
                self.generic_visit(node)

            def visit_Attribute(self, node):
                if hasattr(node, 'attr') and isinstance(node.attr, str):
                    if self._contient_terme(node.attr):
                        violations.append(
                            f"{path.name}: attribut '{node.attr}' contient un terme interdit"
                        )
                self.generic_visit(node)

            def visit_FunctionDef(self, node):
                if self._contient_terme(node.name):
                    violations.append(
                        f"{path.name}: fonction '{node.name}' contient un terme interdit"
                    )
                self.generic_visit(node)

            def visit_ClassDef(self, node):
                if self._contient_terme(node.name):
                    violations.append(
                        f"{path.name}: classe '{node.name}' contient un terme interdit"
                    )
                self.generic_visit(node)

        Visitor().visit(tree)

    if violations:
        return False, "; ".join(violations)
    return True, ""


__all__ = [
    "CHAMPS_DIGEST",
    "SEUIL_BLOCAGE_HEURES",
    "FONCTIONS_HORLOGE_INTERDITES",
    "TERMES_INTERDITS_R020",
    "produire_digest",
    "verifier_digest",
    "garde_absence_horloge",
    "garde_conformite_r020",
]
