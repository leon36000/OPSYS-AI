"""Vérification des cas limites soulevés au round 2 : conteneurs vides et imbriqués."""
import importlib
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
# sys.path reçoit src/, PARENT du paquet : c'est lui qui rend
# « from m2_revenue_crm import ... » résoluble, ici comme dans les sous-processus.
# Ce script tourne seul, hors pytest : le `pythonpath` de pyproject.toml ne s'y applique pas.
# L'import passe donc par `importlib`, après l'insertion.
sys.path.insert(0, str(SRC))
e = importlib.import_module("m2_revenue_crm.encodage")

print("=== (a) conteneurs VIDES de types différents ===")
vides = [("set()", set()), ("frozenset()", frozenset()), ("list []", []),
         ("tuple ()", ()), ("dict {}", {})]
emp = {n: e.empreinte(v) for n, v in vides}
for n, h in emp.items():
    print(f"  {n:14} -> {h[:24]}")
collisions = [(a, b) for i, a in enumerate(emp) for b in list(emp)[i + 1:] if emp[a] == emp[b]]
print("  COLLISIONS entre vides :", collisions or "aucune")

print("\n=== (b) conteneurs IMBRIQUÉS hétérogènes ===")
imbrique = {"x": {"a", "b", "c", "d", "e"}, "y": [3, 1, 2], "z": ({"k": {1, 2}}, frozenset(["q"]))}
code = (
    "import sys; sys.path.insert(0, " + repr(str(SRC)) + "); from m2_revenue_crm import encodage; "
    "print(encodage.empreinte({'x': {'a','b','c','d','e'}, 'y': [3,1,2], "
    "'z': ({'k': {1,2}}, frozenset(['q']))}))"
)
sorties = []
for graine in ("0", "1", "42", "1337", "99991"):
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env={**os.environ, "PYTHONHASHSEED": graine})
    sorties.append(r.stdout.strip())
    print(f"  PYTHONHASHSEED={graine:>6} -> {r.stdout.strip()[:32]}")
print("  déterminisme inter-processus sur structure imbriquée :", len(set(sorties)) == 1)

print("\n=== (c) autres familles de collision à sonder ===")
paires = [
    ("liste imbriquée vs plate", [[1], [2]], [1, 2]),
    ("dict vs set de tuples", {"a": 1}, {("a", 1)}),
    ("str '1' vs int 1", "1", 1),
    ("True vs 1", True, 1),
    ("None vs 'None'", None, "None"),
    ("[] vs [[]]", [], [[]]),
]
for libelle, a, b in paires:
    print(f"  {libelle:26} -> collision : {e.empreinte(a) == e.empreinte(b)}")
