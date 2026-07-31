#!/usr/bin/env python3
"""Énumération MÉCANIQUE des gardes — aucune exclusion, et le ROUGE est QUALIFIÉ.

Chaque `if` dont le corps produit un rejet est neutralisé UN PAR UN ; la suite doit virer
au ROUGE. Une garde qui reste verte est NUE : rien ne la tient.

Trois propriétés, chacune née d'une objection de revue mesurée (historique complet dans
les messages de commit de la branche) :

1. AUCUNE EXCLUSION. La neutralisation se fait par les bornes du nœud `ast.If`, jamais
   par recherche de texte : `if rejet is not None:` apparaît deux fois dans le module et
   un remplacement textuel ne peut pas les distinguer — la garde était alors SAUTÉE, et
   la conclusion « aucune garde nue » reposait sur une exclusion.

2. TOTAL VENTILÉ, ET RECONNAISSANCE STRUCTURELLE. Le compte distingue trois choses :
   les gardes qui REJETTENT directement dans leur propre corps, celles qui ENGLOBENT un
   `if` rejetant (`if reference is not None:`), et les DÉCISIONS DE BLOCAGE qui ne
   rejettent pas mais retournent une qualification bloquante (`if elements_manquants:`
   rend `prix_bloque: True`). Un total non ventilé n'était pas réconciliable avec le diff
   par un relecteur ; et une version antérieure classait la décision de blocage comme une
   garde de rejet parce que le TEXTE de son `return` contenait le mot « verdict » — une
   heuristique de sous-chaîne, jamais une preuve. La reconnaissance est désormais
   STRUCTURELLE : un rejet est un `return` dont le premier élément est la constante
   `None` (le contrat du module est `(qualification, None)` en succès et `(None, verdict)`
   en rejet), ou un appel à `construire_verdict`. Un blocage est un `return` d'un dict
   littéral portant `prix_bloque` à vrai. Aucune comparaison de texte ne subsiste.

3. ROUGE QUALIFIÉ. Un ROUGE peut venir d'un PLANTAGE et non d'un refus : neuf gardes sur
   dix-neuf ne tenaient que par l'exception qu'elles devaient éviter, alors que
   l'architecture exige « un verdict de rejet dédié plutôt qu'un plantage ». Le script
   exige donc qu'AU MOINS UN test en échec échoue par un signal NOMMÉ — `Failed`
   (pytest.fail), `AssertionError`, ou une assertion réécrite par pytest.
   « Au moins un » et non « tous » : neutraliser une garde qui protège un accès indexé
   fait NÉCESSAIREMENT planter le code aval ; l'exiger absent serait exiger l'impossible.
   Ce qui est exigible, c'est qu'un test NOMME la disparition au lieu de la subir.
"""
import ast, pathlib, re, shutil, subprocess, sys

RACINE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
MODULE = sys.argv[2] if len(sys.argv) > 2 else "qualite_photos"
SRC = RACINE / f"Modules M/M3-estimation/src/m3_estimation/{MODULE}.py"
TESTS = RACINE / "Modules M/M3-estimation/tests"
original = SRC.read_text(encoding="utf-8")
lignes = original.split("\n")

# Signaux d'un échec NOMMÉ : pytest.fail lève `Failed` ; une assertion échoue soit en
# `AssertionError`, soit — quand pytest a RÉÉCRIT l'assertion — en une ligne qui
# commence par le mot `assert` suivi de l'expression évaluée (« assert True is False »).
# Ce troisième cas a d'abord été classé à tort comme plantage par ce script ; mesuré en
# neutralisant la garde L163 et en lisant la sortie --tb=line. Tout le reste est une
# exception SUBIE, pas un refus prononcé.
NOMMES = ("Failed", "AssertionError", "assert")
# Avec --tb=line, chaque échec produit « chemin:ligne: TypeDException: message ».
MOTIF_ECHEC = re.compile(r"^.*?:\d+: (\w+)", re.MULTILINE)


ARBRE = ast.parse(original)
# Fabriques de rejet du module : toute fonction dont le corps construit un verdict.
# Une garde peut déléguer son rejet à une telle fabrique (`return _rejet_champ_photo(...)`),
# et la reconnaissance doit traverser cette indirection — sinon neuf gardes disparaissent
# du compte. La résolution se fait sur le GRAPHE d'appel, jamais sur le nom écrit.
FABRIQUES = {f.name for f in ast.walk(ARBRE) if isinstance(f, ast.FunctionDef)
             and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "construire_verdict" for n in ast.walk(f))}


def _est_rejet(noeud_return):
    """Ce `return` produit-il un REJET, structurellement ?

    Le contrat du module est `(qualification, None)` en succès et `(None, verdict)` en
    rejet : un rejet se reconnaît donc à un tuple dont le PREMIER élément est la
    constante `None`. Un appel direct à `construire_verdict` compte aussi.
    """
    v = noeud_return.value
    if v is None:
        return False
    if isinstance(v, ast.Tuple) and v.elts:
        premier = v.elts[0]
        if isinstance(premier, ast.Constant) and premier.value is None:
            return True
    for n in ast.walk(v):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Attribute) and n.func.attr == "construire_verdict":
                return True
            if isinstance(n.func, ast.Name) and n.func.id in FABRIQUES:
                return True
    return False


def _est_blocage(noeud_return):
    """Ce `return` produit-il une DÉCISION DE BLOCAGE (pas un rejet) ?

    Une qualification bloquante est un dict littéral portant `prix_bloque` à vrai. Ce
    n'est PAS un rejet : les entrées étaient valides, c'est leur contenu qui bloque.
    """
    for n in ast.walk(noeud_return):
        if isinstance(n, ast.Dict):
            for cle, val in zip(n.keys, n.values):
                if (isinstance(cle, ast.Constant) and cle.value == "prix_bloque"
                        and isinstance(val, ast.Constant) and val.value is True):
                    return True
    return False


def _corps_propre(noeud):
    """Les `return` du corps PROPRE du `if`, hors `if` imbriqués."""
    for enfant in noeud.body:
        if isinstance(enfant, ast.If):
            continue
        for n in ast.walk(enfant):
            if isinstance(n, ast.Return):
                yield n


def rejette_directement(noeud):
    """Le corps propre de ce `if` produit-il un rejet ?"""
    return any(_est_rejet(r) for r in _corps_propre(noeud))


def bloque_directement(noeud):
    """Le corps propre de ce `if` produit-il une décision de blocage ?"""
    return any(_est_blocage(r) for r in _corps_propre(noeud))


tous = [n for n in ast.walk(ARBRE) if isinstance(n, ast.If)]
directes = [n for n in tous if rejette_directement(n)]
blocages = [n for n in tous if n not in directes and bloque_directement(n)]
englobantes = [n for n in tous if n not in directes and n not in blocages and any(
    rejette_directement(d) for d in ast.walk(n) if isinstance(d, ast.If) and d is not n)]
gardes = sorted(directes + englobantes + blocages, key=lambda n: n.lineno)
genre = {}
for n in gardes:
    genre[id(n)] = ("rejet" if n in directes else
                    "englobante" if n in englobantes else "blocage")
print(f"contrôles neutralisés = {len(gardes)} = {len(directes)} gardes de REJET "
      f"+ {len(englobantes)} englobante(s) (L{[n.lineno for n in englobantes]}) "
      f"+ {len(blocages)} décision(s) de BLOCAGE (L{[n.lineno for n in blocages]})")


def neutraliser(noeud):
    """Remplace l'EN-TÊTE du `if` (potentiellement multi-lignes) par `if False:`.

    Bornes prises sur le nœud : de sa première ligne à celle qui précède son corps.
    Le corps est conservé — il devient mort, ce qui est l'effet recherché.
    """
    debut, fin = noeud.lineno - 1, noeud.body[0].lineno - 1
    indent = " " * (len(lignes[debut]) - len(lignes[debut].lstrip()))
    return "\n".join(lignes[:debut] + [indent + "if False:"] + lignes[fin:])


nues, sans_effet, par_plantage = [], [], []
try:
    for i, garde in enumerate(gardes, 1):
        mutant = neutraliser(garde)
        if mutant == original:
            sans_effet.append(garde.lineno)
            continue
        try:
            compile(mutant, str(SRC), "exec")
        except SyntaxError as e:
            sans_effet.append(garde.lineno)
            print(f"  [{i:02d}] L{garde.lineno:<4} NON COMPILABLE : {e.msg}")
            continue
        SRC.write_text(mutant, encoding="utf-8")
        for c in SRC.parent.rglob("__pycache__"):
            shutil.rmtree(c, ignore_errors=True)
        r = subprocess.run([sys.executable, "-B", "-m", "pytest", str(TESTS), "-q",
                            "-p", "no:cacheprovider", "--color=no", "--tb=line"],
                           capture_output=True, text=True, cwd=RACINE)
        if r.returncode == 0:
            etat = "VERT (NUE)"
            nues.append(garde.lineno)
        else:
            types = set(MOTIF_ECHEC.findall(r.stdout))
            nommes = types & set(NOMMES)
            if nommes:
                etat = f"ROUGE par REFUS NOMMÉ ({sorted(nommes)[0]})"
            else:
                brut = sorted(types)[0] if types else "inconnu"
                etat = f"ROUGE par PLANTAGE SEUL ({brut})"
                par_plantage.append((garde.lineno, brut))
        cond = ast.get_source_segment(original, garde.test)[:46]
        print(f"  [{i:02d}] L{garde.lineno:<4} {genre[id(garde)]:<11} {cond:<48} -> {etat}")
finally:
    SRC.write_text(original, encoding="utf-8")
    for c in SRC.parent.rglob("__pycache__"):
        shutil.rmtree(c, ignore_errors=True)

print(f"\ncontroles={len(gardes)}  nus={len(nues)}  sans effet={len(sans_effet)}  "
      f"tenues par plantage SEUL={len(par_plantage)} {par_plantage}  "
      f"ancres ambiguës=0 (bornes AST)")
assert SRC.read_text(encoding="utf-8") == original, "source non restaurée"
sys.exit(1 if (nues or sans_effet or par_plantage) else 0)
