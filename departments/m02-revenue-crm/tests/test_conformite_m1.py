import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from m2_revenue_crm import encodage, horodatage

_SRC = Path(__file__).resolve().parents[1] / "src"
_PKG = _SRC / "m2_revenue_crm"  # répertoire du paquet, pour les scans de sources


# ----------------------------------------------------------------------
# CA-M2-13 — Empreintes scellées (pas de lecture croisée avec M1)
# ----------------------------------------------------------------------
SHA256_HORODATAGE_ATTENDU = "7168dc81de0d37f0e7160b96e9df14c9a1bf5ef594a791f25745b07d7108e867"
# Gel RESCELLÉ le 2026-07-29 : le catalogue a été aligné sur l'architecture ratifiée
# (REJ-CONVERSATION-CLOSE, invariant transversal, manquait ; quatre identifiants stables
# repris pour l'écart structurel ; REJ-LEAD-DEJA-INGERE ajouté par addendum). Le gel a joué
# son rôle — il a forcé cette décision à être explicite au lieu de passer inaperçue.
# Gel RESCELLÉ une seconde fois le 2026-09-29 (PLAN T1.4-k2, identité authentifiée d'un appel d'appareil) :
# quatre identifiants ajoutés au catalogue (groupe 5) — REJ-IDENTITE-APPAREIL-INVALIDE et
# REJ-IDENTITE-FOURNIE-DIFFERENTE repris de M4 et de M5, REJ-LEAD-NON-ASSIGNE et REJ-OWNER-INCONNU propres à
# M2. Décision journalisée dans docs/bmad/03-ARCHITECTURE.md (addendum T1.4-k2).
# Gel RESCELLÉ une troisième fois le 2026-09-29 (PLAN T4.6, liste des leads et segments M2.11) : deux identifiants
# ajoutés au catalogue (groupe 6) — REJ-SEGMENT-NON-CALCULABLE (un filtre sur un segment sans donnée ou sans seuil,
# avec ce qui manque) et REJ-PAGINATION-INVALIDE (décalage ou limite de page). Décision journalisée dans
# docs/bmad/03-ARCHITECTURE.md (addendum T4.6).
# Gel RESCELLÉ une quatrième fois le 2026-09-29 (PLAN T1.4-m, réassignation d'un lead et republication du fait
# m2.lead_assigne) : cinq identifiants ajoutés au catalogue (groupe 7) — REJ-HUMAIN-REQUIS (la réassignation est une
# décision de personne), REJ-MOTIF-INVALIDE (motif de 10 à 500 caractères), REJ-LEAD-INCONNU,
# REJ-PROPRIETAIRE-INCHANGE et REJ-BUS-INDISPONIBLE (republier hors stockage durable). Décision journalisée dans
# docs/bmad/03-ARCHITECTURE.md (addendum T1.4-m).
# Gel RESCELLÉ une cinquième fois le 2026-09-29 (PLAN T4.9, relances dues, consentement de contact et fréquence
# limitée) : six identifiants ajoutés au catalogue (groupe 8) — REJ-RELANCES-A-CONFIGURER (fréquence maximale absente
# ou invalide), REJ-RELANCE-NON-DUE, REJ-RELANCE-TROP-PROCHE (fréquence limitée, avec la prochaine date permise),
# REJ-CONSENTEMENT-ABSENT, REJ-CONSENTEMENT-RETIRE (STOP) et REJ-CONSENTEMENT-INVALIDE. Décision journalisée dans
# docs/bmad/03-ARCHITECTURE.md (addendum T4.9).
# Sixième rescellage, 2026-10-27 : CRM-04 (dd19e5cf), deux refus de correction des coordonnées
# ajoutés seulement : REJ-CONTACT-CONFLIT et REJ-CONTACT-BACKEND-NON-QUALIFIE. Aucun verdict
# historique modifié. Provenance et deux empreintes : docs/bmad/03-ARCHITECTURE.md, addendum CRM-04.
# Septième rescellage, 2026-10-27 : CRM-03, les quinze refus fermés de l'agenda
# commercial ajoutés par 14540419. Octets historiques inchangés hors ajout;
# décision et empreintes documentées dans l'addendum CRM-03 de l'architecture M2.
SHA256_VERDICTS_ATTENDU = "54e79d529522edf386ada2d998ecad927b2c5a7bdebd4cf87784ede9fc17553e"


class TestCA_M2_13_Empreintes:
    def test_empreinte_horodatage_m2_conforme_au_gel(self):
        chemin = _PKG / "horodatage.py"
        assert chemin.exists(), f"Fichier horodatage.py manquant dans {_PKG}"
        contenu = chemin.read_bytes()
        empreinte = hashlib.sha256(contenu).hexdigest()
        assert empreinte == SHA256_HORODATAGE_ATTENDU, (
            f"Empreinte horodatage.py divergente : attendu {SHA256_HORODATAGE_ATTENDU}, "
            f"calculé {empreinte}"
        )

    def test_empreinte_verdicts_m2_conforme_au_gel(self):
        chemin = _PKG / "verdicts.py"
        assert chemin.exists(), f"Fichier verdicts.py manquant dans {_PKG}"
        contenu = chemin.read_bytes()
        empreinte = hashlib.sha256(contenu).hexdigest()
        assert empreinte == SHA256_VERDICTS_ATTENDU, (
            f"Empreinte verdicts.py divergente : attendu {SHA256_VERDICTS_ATTENDU}, "
            f"calculé {empreinte}"
        )

    def test_aucune_reference_a_un_module_voisin(self):
        base = Path(__file__).resolve().parents[1]
        sources = list(base.glob("src/**/*.py")) + list(base.glob("tests/**/*.py"))
        # Construction dynamique pour eviter toute occurrence litterale des chaines interdites
        interdit = "M1" + "-front" + "-office"
        prefixe_mod = "M" + "1"
        remontee = "." * 2
        inspected = 0
        for chemin_fichier in sources:
            contenu = chemin_fichier.read_text(encoding="utf-8")
            inspected += 1
            assert interdit not in contenu, (
                f"Fichier {chemin_fichier} contient la chaine interdite"
            )
            for ligne in contenu.splitlines():
                stripped = ligne.strip()
                # Import d'un module voisin interdit
                if stripped.startswith(("import ", "from ")) and prefixe_mod in stripped:
                    raise AssertionError(
                        f"Fichier {chemin_fichier} contient un import interdit {prefixe_mod}"
                    )
                # Import relatif parent prohibe
                if stripped.startswith("from " + remontee):
                    raise AssertionError(
                        f"Fichier {chemin_fichier} contient un chemin relatif "
                        + remontee
                        + " interdit"
                    )
        assert inspected >= 4, f"Seulement {inspected} fichiers inspectes, test vide suspect"

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
from m2_revenue_crm import encodage
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
    def test_set_et_liste_ne_collisionnent_pas(self):
        # Différents types ⇒ empreintes différentes
        emp_set = encodage.encoder_canonique({"b", "a", "c"})
        emp_list = encodage.encoder_canonique(["a", "b", "c"])
        assert emp_set != emp_list, (
            "Les empreintes d'un set et d'une liste doivent être distinctes"
        )
        # L’ordre du set n’a aucun impact (canonicité préservée)
        emp_set_alt = encodage.encoder_canonique({"c", "b", "a"})
        assert emp_set == emp_set_alt, (
            "L'encodage d'un set doit être indépendant de son ordre d'insertion"
        )

class TestInjectivite:
    def test_types_distincts_ne_collisionnent_pas(self):
        cas = [
            ({"a"}, ["a"], "set {'a'} vs list ['a']"),
            ({"b", "c"}, ["b", "c"], "set {'b','c'} vs list ['b','c']"),
            ({"a": 1}, [["a", 1]], "dict {'a':1} vs list de couple [['a',1]]"),
            ({"x": "y"}, [["x", "y"]], "dict {'x':'y'} vs list de couple [['x','y']]"),
            ((1, 2), [1, 2], "tuple (1,2) vs list [1,2]"),
            ((3, 4), [3, 4], "tuple (3,4) vs list [3,4]"),
        ]
        for entree1, entree2, desc in cas:
            emp1 = encodage.encoder_canonique(entree1)
            emp2 = encodage.encoder_canonique(entree2)
            assert emp1 != emp2, f"Collision détectée pour {desc} : {emp1}"
