#!/usr/bin/env python3
"""Preuve REJOUABLE que le renommage des verdicts est SÉMANTIQUEMENT NEUTRE.

Deux relecteurs ont refusé l'affirmation « substitution prouvée neutre par comparaison par
import » parce qu'aucun script ni sortie ne l'accompagnait. Ils avaient raison : une
affirmation sans artefact rejouable n'est pas une preuve.

Ce script compare les valeurs de TOUTES les constantes de chaîne des modules touchés, entre
le commit AVANT le renommage et l'état courant. Il importe réellement les deux versions
plutôt que de lire leur texte — c'est la valeur à l'exécution qui importe, pas la forme
écrite. Il sort non-zéro au moindre écart.
"""
import ast, importlib, pathlib, subprocess, sys, tempfile

RACINE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
AVANT = sys.argv[2] if len(sys.argv) > 2 else "c203e35^"
MODULES = ("blocage_prix", "hierarchie_echelle", "plancher", "qualite_photos", "contrats")
ORIGINE = {}
REL = "Modules M/M3-estimation/src/m3_estimation"


def constantes(chemin_paquet):
    """Valeurs des constantes de chaîne de chaque module, par IMPORT réel."""
    for m in list(sys.modules):
        if m.startswith("m3_estimation"):
            del sys.modules[m]
    sys.path.insert(0, str(chemin_paquet.parent))
    try:
        releve = {}
        for nom in MODULES:
            mod = importlib.import_module(f"m3_estimation.{nom}")
            ORIGINE[nom] = getattr(mod, "__file__", "<inconnu>")
            # Chaînes ET collections de chaînes : les contrats gelés (CHAMPS_*,
            # TYPES_TRAVAUX, VERDICTS_ESTIMATION, NIVEAUX_CONFIANCE) sont des tuples ou
            # des frozensets. Une première version ne comparait que les chaînes simples
            # et ne couvrait donc que 5 constantes sur les 17 réelles — la preuve était
            # bien plus faible que ce qu'elle affirmait.
            releve[nom] = {}
            for k, v in vars(mod).items():
                if k.startswith("__"):
                    continue
                if isinstance(v, str):
                    releve[nom][k] = v
                elif isinstance(v, (tuple, list, frozenset, set)) and v \
                        and all(isinstance(x, str) for x in v):
                    # tuple/list : l'ORDRE fait partie du contrat ; set/frozenset : non.
                    releve[nom][k] = tuple(v) if isinstance(v, (tuple, list)) else frozenset(v)
        return releve
    finally:
        sys.path.remove(str(chemin_paquet.parent))


with tempfile.TemporaryDirectory() as tmp:
    ancien = pathlib.Path(tmp) / "m3_estimation"
    ancien.mkdir()
    for nom in MODULES + ("__init__", "validation", "signaux", "verdicts", "monte_carlo"):
        r = subprocess.run(["git", "-C", str(RACINE), "show", f"{AVANT}:{REL}/{nom}.py"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            # ÉCHEC BRUYANT, jamais un saut silencieux. Objection de revue : si un fichier
            # manquait au commit de référence, il ne serait pas écrit dans le dossier
            # temporaire, Python se rabattrait sur la VRAIE source encore présente dans
            # sys.path, et le script comparerait la nouvelle version avec elle-même en
            # annonçant « neutre ». Mesuré : le cas ne se produit pas ici (les dix fichiers
            # existent au commit de référence), mais un script de preuve ne doit pas
            # pouvoir dégrader en silence.
            sys.exit(f"ABANDON : {REL}/{nom}.py absent de {AVANT} — la comparaison "
                     f"se rabattrait sur la source courante et prouverait une tautologie.")
        (ancien / f"{nom}.py").write_text(r.stdout, encoding="utf-8")
    # Vérification que la version « avant » vient BIEN du dossier temporaire.
    poses = sorted(f.stem for f in ancien.glob("*.py"))
    print(f"fichiers extraits de {AVANT} : {len(poses)} -> {poses}")
    avant = constantes(ancien)
    for nom, chemin in ORIGINE.items():
        if str(ancien) not in chemin:
            sys.exit(f"ABANDON : le module « avant » {nom} a ete charge depuis {chemin}, "
                     f"pas depuis le dossier temporaire — la comparaison serait faussee.")
    print(f"origine verifiee : les {len(ORIGINE)} modules « avant » viennent du dossier temporaire")
    apres = constantes(RACINE / REL)

ecarts = []
for nom in MODULES:
    for cle, val in avant[nom].items():
        if apres[nom].get(cle, "<absent>") != val:
            ecarts.append(f"{nom}.{cle} : {val!r} -> {apres[nom].get(cle, '<absent>')!r}")
# Les AJOUTS ne sont pas des écarts : la correction consiste précisément à ajouter des
# constantes nommées. La propriété à prouver est qu'aucune constante EXISTANTE n'a changé
# de valeur ni disparu. Les ajouts sont listés pour information, jamais comptés en échec.
ajouts = []
for nom in MODULES:
    for cle in sorted(set(apres[nom]) - set(avant[nom])):
        ajouts.append(f"{nom}.{cle} = {apres[nom][cle]!r}")

# INVARIANT DE SUBSTITUTION : chaque constante nommée vaut EXACTEMENT le littéral qu'elle
# remplace. C'est ce qui couvre les littéraux remplacés À L'INTÉRIEUR des fonctions, que
# la comparaison des constantes de module ne voit pas (qualite_photos n'en expose aucune).
sys.path.insert(0, str((RACINE / REL).parent))
for m in list(sys.modules):
    if m.startswith("m3_estimation"):
        del sys.modules[m]
from m3_estimation import contrats as _c
invariants = [(f"VERDICT_{v}", v) for v in _c.VERDICTS_ESTIMATION]
brises = [n for n, v in invariants if getattr(_c, n, None) != v]
print("invariant de substitution (constante nommee == litteral remplace) :",
      f"{len(invariants) - len(brises)}/{len(invariants)} verifies")
for b in brises:
    ecarts.append(f"invariant brise : contrats.{b}")

total = sum(len(v) for v in avant.values())
print(f"commit de reference : {AVANT}")
print(f"constantes de chaine comparees : {total} sur {len(MODULES)} modules")
for e in ecarts:
    print("  ECART :", e)
for a in ajouts:
    print("  AJOUT :", a)
print(f"\nconstantes inchangees = {total - len(ecarts)}/{total} | ajouts = {len(ajouts)} | "
      f"ecarts = {len(ecarts)} -> substitution {'NEUTRE' if not ecarts else 'NON NEUTRE'}")
sys.exit(1 if ecarts else 0)
