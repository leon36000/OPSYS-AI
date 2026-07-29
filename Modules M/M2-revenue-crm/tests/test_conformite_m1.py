import sys
import os
import hashlib
import importlib
import inspect
import subprocess
from pathlib import Path
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import encodage  # noqa: E402
import horodatage  # noqa: E402
import verdicts  # noqa: E402

# ----------------------------------------------------------------------
# CA-M2-13 — Empreintes scellées (pas de lecture croisée avec M1)
# ----------------------------------------------------------------------
SHA256_HORODATAGE_ATTENDU = "7168dc81de0d37f0e7160b96e9df14c9a1bf5ef594a791f25745b07d7108e867"
SHA256_VERDICTS_ATTENDU = "fd5320a3dccf1a441519e99ed96240fca9f93bb55d3d0503bdd2fd529c3124fd"


class TestCA_M2_13_Empreintes:
    def test_empreinte_horodatage_m2_conforme_au_gel(self):
        chemin = _SRC / "horodatage.py"
        assert chemin.exists(), f"Fichier horodatage.py manquant dans {_SRC}"
        contenu = chemin.read_bytes()
        empreinte = hashlib.sha256(contenu).hexdigest()
        assert empreinte == SHA256_HORODATAGE_ATTENDU, (
            f"Empreinte horodatage.py divergente : attendu {SHA256_HORODATAGE_ATTENDU}, "
            f"calculé {empreinte}"
        )

    def test_empreinte_verdicts_m2_conforme_au_gel(self):
        chemin = _SRC / "verdicts.py"
        assert chemin.exists(), f"Fichier verdicts.py manquant dans {_SRC}"
        contenu = chemin.read_bytes()
        empreinte = hashlib.sha256(contenu).hexdigest()
        assert empreinte == SHA256_VERDICTS_ATTENDU, (
            f"Empreinte verdicts.py divergente : attendu {SHA256_VERDICTS_ATTENDU}, "
            f"calculé {empreinte}"
        )

    def test_aucune_reference_a_un_module_voisin(self):
        contenu = Path(__file__).read_text(encoding="utf-8")
        # Construction dynamique pour éviter toute occurrence littérale de la chaîne interdite
        interdit = "M1" + "-" + "front" + "-" + "office"
        assert interdit not in contenu, (
            "Le fichier de test M2 ne doit contenir aucune chaîne interdite"
        )
        # Vérification supplémentaire : pas d’accès relatif (..) visant un module interdit
        prefixe_mod = "M" + "1"
        for ligne in contenu.splitlines():
            if ".." in ligne and prefixe_mod in ligne:
                raise AssertionError(
                    "Le fichier de test M2 ne doit pas contenir de chemin relatif "
                    "pointant vers un module interdit"
                )

# ----------------------------------------------------------------------
# CA-M2-14 — Suite de cas d'abus héritée de M1, rejouée contre M2
# ----------------------------------------------------------------------
class TestCA_M2_14_Abus:
    # 1. Collisions par concaténation directe (identique à test_utilitaires)
    def test_collision_concatenation_ab_x_vs_a_bx(self):
        v1 = encodage.encoder_canonique("AB", "X")
        v2 = encodage.encoder_canonique("A", "BX")
        assert v1 != v2, "Collision AB+X vs A+BX doit être évitée"

    def test_collision_concatenation_avec_espaces(self):
        v1 = encodage.encoder_canonique("A", " BC")
        v2 = encodage.encoder_canonique("A ", "BC")
        assert v1 != v2, "Collision 'A'+' BC' vs 'A '+'BC' doit être évitée"

    # 2. Horodatages invalides (mêmes cas que test_utilitaires)
    @pytest.mark.parametrize(
        "invalide",
        [
            "2026-13-45",
            "pas une date",
            "",
            "2026-07-26",
            None,
            42,
        ],
    )
    def test_horodatage_invalide_leve_rej_sans_details_datetime(self, invalide):
        with pytest.raises(ValueError) as exc_info:
            horodatage.valider_horodatage(invalide)
        msg = str(exc_info.value)
        assert "REJ-HORODATAGE-INVALIDE" in msg
        for motif in ("month must be", "Invalid isoformat"):
            assert motif not in msg
        assert exc_info.value.__cause__ is None

    # 3. Déterminisme inter-processus (avec set et dict)
    def test_determinisme_inter_processus_avec_set_et_dict(self):
        code = f"""
import sys
sys.path.insert(0, r'{_SRC}')
import encodage
donnees = {{'set': {{'a', 'b'}}, 'dict': {{'k': 'v'}}}}
print(encodage.encoder_canonique(donnees))
"""
        seeds = ["0", "1", "42"]
        outputs = []
        for s in seeds:
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = s
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
            )
            outputs.append(proc.stdout.strip())
        assert len(set(outputs)) == 1, (
            f"Déterminisme inter-processus échoué : sorties divergentes {outputs}"
        )

    # 4. Cas set non ordonné (indépendant de l'ordre de création)
    def test_set_encodage_deterministe_independant_ordre(self):
        v1 = encodage.encoder_canonique({"b", "a", "c"})
        v2 = encodage.encoder_canonique({"a", "b", "c"})
        assert v1 == v2, "L'encodage d'un set ne doit pas dépendre de l'ordre de création"

    def test_dict_encodage_deterministe_independant_ordre_cles(self):
        v1 = encodage.encoder_canonique({"c": 1, "a": 2})
        v2 = encodage.encoder_canonique({"a": 2, "c": 1})
        assert v1 == v2, "L'encodage d'un dict ne doit pas dépendre de l'ordre des clés"

    # 5. Cohérence supplémentaire : séquence et set produisent même résultat si trié
    def test_set_et_liste_triee_produisent_meme_encodage(self):
        # suppose que l'encodage accepte un set comme un argument unique,
        # et qu'il le traite de manière canonique (triée)
        v_set = encodage.encoder_canonique({"b", "a", "c"})
        v_liste = encodage.encoder_canonique(["a", "b", "c"])
        # Les deux doivent être égaux si l'encodage canonique traite le set comme une liste triée
        assert v_set == v_liste, (
            "L'encodage d'un set doit être identique à celui de sa liste triée"
        )
