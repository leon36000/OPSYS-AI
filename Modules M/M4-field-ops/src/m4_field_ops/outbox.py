"""
Module outbox transactionnel – M4-S008.

Contient le Work Completion Trigger, le seul chemin d'écriture vers l'état
``terminee``, garantissant qu'un seul maillon composite porte à la fois la
transition et le wct.  Fournit également les fonctions de lecture, de vérification
d'invariants, la garde statique d'unicité d'écriture et un consommateur de
référence idempotent.
"""

import copy
import ast
from pathlib import Path
from datetime import datetime

from . import horodatage
from . import verdicts
from . import encodage
from . import etats
from . import pointage

# --------------------------------------------------------------------- constantes
# L'ordre exact des tuples ci-dessous fait partie du contrat Ratifié WorkCompletionTriggerV1.
CONSOMMATEURS_CIBLES = ("M6", "M5", "M2", "M7", "M8", "M10")

CHAMPS_WCT = (
    "wct_id", "intervention_id", "lead_id", "technicien_id", "horodatage_completion",
    "fix_gps_completion", "duree_reelle_minutes", "ecart_signale", "revue_id",
    "hash_maillon", "consommateurs_cibles", "devis_id",
)

CLE_WCT = "wct"

# --------------------------------------------------------------------- helpers
def _extraire_lead_id(registre_cible, intervention_id):
    """Renvoie le ``lead_id`` du maillon d'inscription de l'intervention."""
    for maillon in registre_cible.lire():
        if (maillon.get("type_entree") == etats.TYPE_INSCRIPTION
                and maillon.get("intervention_id") == intervention_id):
            return maillon["lead_id"]
    return None


def _dernier_depart(registre_cible, intervention_id):
    """Renvoie le dernier pointage de départ (technicien_id, horodatage, latitude, longitude)."""
    dernier = None
    for maillon in registre_cible.lire():
        if (maillon.get("type_entree") == pointage.TYPE_POINTAGE
                and maillon.get("intervention_id") == intervention_id
                and maillon.get("action") == "depart"):
            dernier = maillon
    if dernier is None:
        return None
    return (dernier.get("technicien_id"),
            dernier.get("horodatage"),
            dernier.get("latitude"),
            dernier.get("longitude"))


# --------------------------------------------------------------------- API publique
def calculer_duree_reelle(registre_cible, intervention_id):
    """
    Calcule la durée réelle de l'intervention à partir des pointages de terrain.

    Args:
        registre_cible: instance de Registre.
        intervention_id: identifiant de l'intervention.

    Règle DÉTERMINISTE : du PREMIER pointage d'arrivée au DERNIER pointage de
    départ. La règle « exactement une paire » a été écartée après mesure : une
    anomalie de pointage produit LÉGITIMEMENT un second départ (départ incohérent
    -> revue), donc exiger une paire unique rendait toute intervention arbitrée
    IMPOSSIBLE à compléter — le chemin de revue de CA-M4-10 devenait inatteignable.

    Returns:
        (minutes, None) ou (None, code_verdict). Fail-closed : aucune arrivée,
        aucun départ, ou dernier départ ANTÉRIEUR à la première arrivée. Aucune
        valeur conventionnelle n'est jamais substituée.
    """
    pointages = []
    for maillon in registre_cible.lire():
        if (maillon.get("type_entree") == pointage.TYPE_POINTAGE
                and maillon.get("intervention_id") == intervention_id):
            pointages.append(maillon)

    arrivees = [p for p in pointages if p.get("action") == "arrivee"]
    departs = [p for p in pointages if p.get("action") == "depart"]

    if not arrivees or not departs:
        return None, "REJ-CONTRAT-INVALIDE"

    # Premier arrivée / dernier départ : l'ordre du registre est l'ordre
    # d'écriture, et les horodatages sont non décroissants par pointage (CA-M4-07).
    dt_arr = min(datetime.fromisoformat(p["horodatage"]) for p in arrivees)
    dt_dep = max(datetime.fromisoformat(p["horodatage"]) for p in departs)

    if dt_dep < dt_arr:
        return None, "REJ-HORODATAGE-ANTERIEUR"

    minutes = int((dt_dep - dt_arr).total_seconds() // 60)
    return minutes, None


def completer_intervention(intervention_id, horodatage_arg, registre_cible, revue_id=None):
    """
    Réalise la complétion et émet le WCT en une unique écriture.

    Args:
        intervention_id: identifiant de l'intervention à terminer.
        horodatage_arg: horodatage RFC 3339 avec fuseau.
        registre_cible: instance de Registre.
        revue_id: éventuel identifiant de la demande de revue ayant déclenché la complétion.

    Returns:
        (accusé, None) ou (None, verdict).
    """
    # 1. Horodatage valide
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")

    # 2. Statut courant
    courant = etats.statut_courant(registre_cible, intervention_id)
    if courant is None:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail="intervention inexistante",
        )

    # 3. La table des transitions reste l'autorité sur la légalité théorique
    if (courant, "terminee") not in etats.TRANSITIONS_AUTORISEES:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            statut=courant,
            detail=f"{courant} -> terminee",
        )

    # 4. Revue_id (si fourni) doit exister
    if revue_id is not None:
        trouve = False
        for maillon in registre_cible.lire():
            if (maillon.get("type_entree") == pointage.TYPE_DEMANDE_REVUE
                    and maillon.get("demande_id") == revue_id):
                trouve = True
                break
        if not trouve:
            return None, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail="revue introuvable",
            )

    # 5. Durée réelle
    duree_minutes, code_duree = calculer_duree_reelle(registre_cible, intervention_id)
    if duree_minutes is None:
        return None, verdicts.construire_verdict(
            code_duree,
            detail="durée réelle indéterminable",
        )

    # 6. Extraction des données terrain (ne fait pas confiance à l'appelant)
    lead_id = _extraire_lead_id(registre_cible, intervention_id)
    if lead_id is None:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="lead_id introuvable dans le registre",
        )

    depart = _dernier_depart(registre_cible, intervention_id)
    if depart is None:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="pointage de départ absent",
        )
    technicien_id, horodatage_depart, lat, lon = depart

    # 7. Partie transition SEULE (sans le wct)
    partie_transition = {
        "type_entree": etats.TYPE_TRANSITION,
        "intervention_id": intervention_id,
        "statut": "terminee",
        "statut_precedent": courant,
        "horodatage": horodatage_arg,
    }

    # 8. Empreinte de la partie transition (jamais circulaire car le wct n'y figure pas)
    hash_maillon = encodage.empreinte(partie_transition)

    # 9. Identifiant du wct
    wct_id = encodage.empreinte("wct", intervention_id, horodatage_arg)

    # 10. Assemblage du wct
    wct = {
        "wct_id": wct_id,
        "intervention_id": intervention_id,
        "lead_id": lead_id,
        "technicien_id": technicien_id,
        "horodatage_completion": horodatage_depart,
        "fix_gps_completion": {"latitude": lat, "longitude": lon},
        "duree_reelle_minutes": duree_minutes,
        "ecart_signale": revue_id is not None,
        "revue_id": revue_id,
        "hash_maillon": hash_maillon,
        "consommateurs_cibles": list(CONSOMMATEURS_CIBLES),
        "devis_id": None,  # M3 n'existe pas en v1
    }

    # 11. Maillon composite : exactement UN appel à ajouter
    maillon = copy.deepcopy(partie_transition)
    maillon[CLE_WCT] = wct
    ligne_id = registre_cible.ajouter(maillon)

    # 12. Accusé
    accuse = {
        "wct_id": wct_id,
        "intervention_id": intervention_id,
        "ligne_id": ligne_id,
        "statut": "terminee",
        "hash_maillon": hash_maillon,
        "duree_reelle_minutes": duree_minutes,
        "ecart_signale": revue_id is not None,
        "tete_chaine": registre_cible.tete(),
    }
    return accuse, None


def lire_outbox(registre_cible, depuis_index=0):
    """
    Lit les WCT émis depuis un certain index (inclus) du registre.

    Args:
        registre_cible: instance de Registre.
        depuis_index: position de départ dans la liste des maillons.

    Returns:
        Liste de couples (index, wct) – copies profondes.

    Raises:
        ValueError: si depuis_index est négatif.
    """
    if depuis_index < 0:
        raise ValueError("depuis_index négatif")

    resultat = []
    for i, maillon in enumerate(registre_cible.lire()):
        if i < depuis_index:
            continue
        if CLE_WCT in maillon:
            resultat.append((i, copy.deepcopy(maillon[CLE_WCT])))
    return resultat


def verifier_invariants_outbox(registre_cible):
    """
    Vérifie l'intégrité des WCT présents dans le registre.

    Returns:
        (True, "") ou (False, message) en cas d'incohérence.
    """
    for maillon in registre_cible.lire():
        statut = maillon.get("statut")
        wct = maillon.get(CLE_WCT)

        # Tout maillon terminé doit porter un wct
        if statut == "terminee":
            if wct is None:
                return False, f"maillon terminee sans wct (index implicite)"
            if set(wct.keys()) != set(CHAMPS_WCT):
                return False, f"wct avec clés incorrectes: {set(wct.keys())}"
            if wct["consommateurs_cibles"] != list(CONSOMMATEURS_CIBLES):
                return False, "consommateurs_cibles du wct invalides"
            if wct["intervention_id"] != maillon.get("intervention_id"):
                return False, "wct.intervention_id # maillon.intervention_id"

            # Recalcul du hash sur la partie transition (sans wct, ligne_id, precedent_ligne_id)
            partie = {
                k: v for k, v in maillon.items()
                if k not in (CLE_WCT, "ligne_id", "precedent_ligne_id")
            }
            recalcul = encodage.empreinte(partie)
            if wct["hash_maillon"] != recalcul:
                return False, "hash_maillon incohérent"

        # Aucun maillon non-terminé ne doit porter la clé wct
        elif statut != "terminee" and wct is not None:
            return False, f"maillon non-terminee porte un wct (statut={statut})"

    return True, ""


def garde_ecriture_unique(chemin_source=None):
    """
    Vérification statique (par AST) qu'aucun autre module n'écrit le wct
    et que ``completer_intervention`` n'appelle ``ajouter`` qu'une fois.

    Limite connue : un appel indirect (getattr, alias) échapperait à la garde.
    Le refus au runtime de ``transitionner(..., "terminee", ...)`` constitue la
    défense en profondeur.

    Args:
        chemin_source: dossier des sources à analyser (défaut : dossier du module).

    Returns:
        (True, "") ou (False, message)
    """
    if chemin_source is None:
        chemin_source = str(Path(__file__).parent)

    violations = []

    for path in Path(chemin_source).glob("*.py"):
        # Exclure __init__.py pour éviter les faux positifs
        if path.name == "__init__.py":
            continue
        try:
            arbre = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        # Parcours avec pile de fonctions pour savoir si on est dans completer_intervention
        pile_fonctions = []

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                pile_fonctions.append(node.name)
                self.generic_visit(node)
                pile_fonctions.pop()

            def visit_Call(self, node):
                # Vérification des appels à ajouter(...) avec dict contenant CLE_WCT
                if isinstance(node.func, ast.Attribute) and node.func.attr == "ajouter":
                    for arg in node.args:
                        if isinstance(arg, ast.Dict):
                            for key in arg.keys:
                                if isinstance(key, ast.Constant) and key.value == CLE_WCT:
                                    # Où sommes-nous ?
                                    if "completer_intervention" in pile_fonctions:
                                        # On comptera les appels plus tard, pour l'instant on note l'appel
                                        # On ne peut pas compter directement ici car on veut vérifier
                                        # le nombre total d'appels dans la fonction.
                                        pass
                                    else:
                                        violations.append(
                                            f"{path.name}: appel à ajouter avec clé {CLE_WCT} "
                                            f"hors de completer_intervention"
                                        )

                # Vérification des appels à transitionner(..., "terminee", ...)
                nom_fonc = None
                if isinstance(node.func, ast.Attribute):
                    nom_fonc = node.func.attr
                elif isinstance(node.func, ast.Name):
                    nom_fonc = node.func.id
                if nom_fonc == "transitionner":
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and arg.value == "terminee":
                            violations.append(
                                f"{path.name}: appel à transitionner avec 'terminee'"
                            )
                    for kw in node.keywords:
                        if isinstance(kw.value, ast.Constant) and kw.value == "terminee":
                            violations.append(
                                f"{path.name}: appel à transitionner avec keyword 'terminee'"
                            )

                self.generic_visit(node)

        Visitor().visit(arbre)

    # Vérification additionnelle du nombre d'appels à ajouter dans completer_intervention
    # On a besoin de re-parcourir le fichier outbox.py (ou tout fichier contenant la fonction)
    # On va spécifiquement ouvrir le fichier outbox.py pour compter les appels à ajouter.
    own_path = Path(__file__) if chemin_source is None else None
    # Si chemin_source est fourni, trouver le fichier qui contient completer_intervention
    if own_path is None:
        # On cherche outbox.py dans le dossier source
        own_path = Path(chemin_source) / "outbox.py"
    if own_path.exists():
        own_arbre = ast.parse(own_path.read_text(encoding="utf-8"))
        nb_ajout = 0

        class CompteurAjout(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                if node.name == "completer_intervention":
                    # Compter les appels à ajouter dans cette fonction
                    compteur = 0

                    class LocalVisitor(ast.NodeVisitor):
                        def visit_Call(self, inner_node):
                            nonlocal compteur
                            if isinstance(inner_node.func, ast.Attribute) and inner_node.func.attr == "ajouter":
                                compteur += 1
                            self.generic_visit(inner_node)

                    LocalVisitor().visit(node)
                    nonlocal nb_ajout
                    nb_ajout = compteur
                else:
                    self.generic_visit(node)

        CompteurAjout().visit(own_arbre)

        if nb_ajout != 1:
            violations.append(
                f"outbox.py: completer_intervention contient {nb_ajout} appel(s) à ajouter (attendu: 1)"
            )

    if violations:
        return False, "; ".join(violations)
    return True, ""


class ConsommateurReference:
    """
    Consommateur idempotent des WCT, utilisant un curseur de position et un
    ensemble de ``wct_id`` déjà traités.  L'idempotence est assurée par le set,
    pas par le curseur (qui sert uniquement à l'incrément).
    """

    def __init__(self):
        self.curseur = 0
        self.wct_vus = set()
        self.effets = []

    def consommer(self, registre_cible, depuis_index=None):
        """
        Consomme tous les wct émis depuis un certain index.

        Args:
            registre_cible: instance de Registre.
            depuis_index: index de départ (par défaut, reprend au curseur interne).

        Returns:
            Nombre de nouveaux effets appliqués.
        """
        if depuis_index is None:
            depuis_index = self.curseur

        wcts = lire_outbox(registre_cible, depuis_index=depuis_index)
        nouveaux = 0
        for _, wct in wcts:
            if wct["wct_id"] in self.wct_vus:
                continue
            self.wct_vus.add(wct["wct_id"])
            self.effets.append(copy.deepcopy(wct))
            nouveaux += 1

        if wcts:
            dernier_index = max(idx for idx, _ in wcts)
            self.curseur = max(self.curseur, dernier_index + 1)
        return nouveaux


__all__ = [
    "CONSOMMATEURS_CIBLES",
    "CHAMPS_WCT",
    "CLE_WCT",
    "calculer_duree_reelle",
    "completer_intervention",
    "lire_outbox",
    "verifier_invariants_outbox",
    "garde_ecriture_unique",
    "ConsommateurReference",
]
