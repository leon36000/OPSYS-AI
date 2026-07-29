# -*- coding: utf-8 -*-
"""Preuves de M2-S001 (fichier dédié : accents préservés, rejouable)."""
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path("/media/pc1/Storage/Repo/OPSYS-AI/Modules M/M2-revenue-crm")
sys.path.insert(0, str(RACINE / "src"))
import encodage, horodatage, verdicts, fixtures_garde  # noqa: E402

print("=== injectivité (les collisions mesurées dans M1 ne se reproduisent pas) ===")
for a, b in ((("AB", "X"), ("A", "BX")), (("A", " BC"), ("A ", "BC"))):
    print(f"  {a} vs {b} -> différents : {encodage.encoder_canonique(*a) != encodage.encoder_canonique(*b)}")

print("\n=== déterminisme INTER-PROCESSUS (PYTHONHASHSEED) ===")
code = (
    "import sys; sys.path.insert(0, %r); import encodage; "
    "print(encodage.encoder_canonique({'x': {'a','b','c','d','e'}, 'y': [3,1,2]}, 'acteur'))"
    % str(RACINE / "src")
)
sorties = []
for graine in ("0", "1", "42", "1337"):
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env={**os.environ, "PYTHONHASHSEED": graine})
    sorties.append(r.stdout.strip())
    print(f"  PYTHONHASHSEED={graine:>4} -> {r.stdout.strip()[:32]}")
print("  les 4 graines donnent le MÊME identifiant :", len(set(sorties)) == 1)

print("\n=== horodatage : refus uniforme, aucune fuite d'erreur datetime ===")
for mauvais in ("2026-13-45", "pas une date", "", "2026-07-26", None, 42):
    try:
        horodatage.valider_horodatage(mauvais)
        print(f"  {mauvais!r:16} -> ACCEPTÉ (défaut)")
    except Exception as e:
        fuite = any(x in str(e) for x in ("month must be", "Invalid isoformat", "day is out"))
        print(f"  {mauvais!r:16} -> {type(e).__name__}: {str(e)[:38]:40} fuite={fuite} cause={e.__cause__ is not None}")
print("  valide :", horodatage.valider_horodatage("2026-07-26T12:00:00+00:00"))

print("\n=== verdicts : catalogue fermé ===")
print("  est_verdict('REJ-FRONTIERE-VIOLEE') :", verdicts.est_verdict("REJ-FRONTIERE-VIOLEE"))
print("  est_verdict('CODE-INVENTE')        :", verdicts.est_verdict("CODE-INVENTE"))
try:
    verdicts.construire_verdict("CODE-INVENTE")
    print("  construire_verdict hors catalogue -> ACCEPTÉ (défaut)")
except Exception as e:
    print("  construire_verdict hors catalogue ->", type(e).__name__)

print("\n=== fixtures : fail-closed sur le marqueur fictif ===")
import tempfile
with tempfile.TemporaryDirectory() as d:
    for val, libelle in (("true", "fictif: true"), ("false", "fictif: false"),
                         ('"true"', 'fictif: "true"'), ("1", "fictif: 1"), (None, "champ absent")):
        f = Path(d) / "fx.yaml"
        f.write_text("cas: []\n" if val is None else f"fictif: {val}\ncas: []\n", encoding="utf-8")
        try:
            fixtures_garde.charger_fixture(str(f))
            print(f"  {libelle:18} -> ACCEPTÉE")
        except Exception as e:
            print(f"  {libelle:18} -> REFUSÉE ({str(e)[:34]})")

print("\n=== absence de couplage inter-modules ===")
for f in sorted((RACINE / "src").glob("*.py")) + sorted((RACINE / "tests").glob("*.py")):
    s = f.read_text(encoding="utf-8")
    assert "M1" + "-front-office" not in s, f"couplage détecté dans {f.name}"
print("  aucun fichier de src/ ni de tests/ ne référence le module voisin : OK")
