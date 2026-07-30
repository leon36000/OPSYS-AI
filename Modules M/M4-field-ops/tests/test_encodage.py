import sys
from pathlib import Path
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m4_field_ops import encodage  # noqa: E402

import pytest
import subprocess
import decimal
import datetime
import uuid
import os


class TestInjectivite:
    """Garantit que l'encodage canonique est injectif, notamment contre les
    collisions par concaténation, et qu'il est déterministe (y compris
    d'un processus à l'autre indépendamment de PYTHONHASHSEED).
    """

    @pytest.mark.parametrize(
        "args1,args2",
        [
            (("ab", "c"), ("a", "bc")),
            (("A", " BC"), ("A ", "BC")),
            (("x", "y", "z"), ("xy", "z")),
        ],
        ids=["ab_c_vs_a_bc", "A_BC_vs_A_BC", "trois_champs"],
    )
    def test_injectivite_concatenation(self, args1, args2):
        """Prouve que deux tuples distincts produisent des encodages différents,
        même lorsqu'une simple concaténation des composants pourrait prêter à
        confusion.
        """
        enc1 = encodage.encoder_canonique(*args1)
        enc2 = encodage.encoder_canonique(*args2)
        assert enc1 != enc2, (
            f"Collision détectée : {args1} et {args2} ont le même encodage"
        )

    def test_determinisme_deux_appels(self):
        """Deux appels successifs avec la même valeur produisent exactement la
        même chaîne canonique.
        """
        valeur = {"liste": [1, 2, 3], "réel": decimal.Decimal("1.5")}
        e1 = encodage.encoder_canonique(valeur)
        e2 = encodage.encoder_canonique(valeur)
        assert e1 == e2, "Le même objet doit générer un encodage identique"

    def test_interprocessus_determinisme(self):
        """Lance trois sous-processus avec des PYTHONHASHSEED différentes et
        vérifie que l'encodage d'une valeur composite (dict, set, Decimal,
        datetime, bytes) reste identique.
        """
        # Script exécuté dans le sous-processus ; il doit modifier sys.path
        # pour atteindre le paquet m4_field_ops de la même manière que le test.
        script = f"""
import sys
from pathlib import Path
_SRC = Path(r'{_SRC.as_posix()}')
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from m4_field_ops import encodage
import decimal, datetime, uuid

valeur = {{
    "ensemble": {{decimal.Decimal("1.1"), 2, 3}},
    "instant": datetime.datetime(2025, 7, 30, 12, 0, 0, tzinfo=datetime.timezone.utc),
    "octets": b'\\x00\\xff\\xab',
    "identifiant": uuid.UUID("12345678-1234-5678-1234-567812345678"),
}}
print(encodage.encoder_canonique(valeur))
"""
        seeds = ["random", "123", "456"]
        sorties = []
        for seed in seeds:
            env = {**os.environ, "PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"}
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env=env,
            )
            assert proc.returncode == 0, (
                f"Échec du sous-processus (seed={seed}): {proc.stderr}"
            )
            sortie = proc.stdout.strip()
            assert sortie, f"Sortie vide pour seed={seed}"
            sorties.append(sortie)
        assert len(set(sorties)) == 1, (
            "Les encodages diffèrent selon PYTHONHASHSEED, "
            "preuve de non-déterminisme inter-processus"
        )


class TestTypesTagues:
    """Vérifie que chaque type standard reçoit la balise attendue et la bonne
    représentation canonique.
    """

    CAS_TYPES = [
        (decimal.Decimal("1.5"), "__decimal__", "1.5", None),
        (
            datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            "__datetime__",
            "2025-01-01T12:00:00+00:00",
            "__date__",
        ),
        (datetime.date(2025, 1, 1), "__date__", "2025-01-01", None),
        (datetime.time(12, 0, 0), "__time__", "12:00:00", None),
        (
            uuid.UUID("12345678-1234-5678-1234-567812345678"),
            "__uuid__",
            "12345678-1234-5678-1234-567812345678",
            None,
        ),
        (b"\xab", "__bytes__", "ab", None),
        (bytearray(b"\xab"), "__bytearray__", "ab", None),
    ]

    @pytest.mark.parametrize(
        "valeur, balise, representation, balise_interdite",
        CAS_TYPES,
        ids=["decimal", "datetime", "date", "time", "uuid", "bytes", "bytearray"],
    )
    def test_forme_taguee(self, valeur, balise, representation, balise_interdite):
        """L'encodage contient la balise et la chaîne canonique propres au type,
        et exclut toute balise concurrente (ex. datetime interdit __date__).
        """
        enc = encodage.encoder_canonique(valeur)
        assert balise in enc, (
            f"Balise {balise} absente de l'encodage de {valeur!r}"
        )
        assert representation in enc, (
            f"Représentation canonique {representation!r} absente de {enc}"
        )
        if balise_interdite:
            assert balise_interdite not in enc, (
                f"Balise interdite {balise_interdite} présente pour "
                f"un objet de type {type(valeur).__name__}"
            )

    def test_complex_forme_taguee(self):
        """Un nombre complexe est balisé __complex__ et les parties réelle
        et imaginaire sont formatées avec un seul chiffre après la virgule
        (ex. '1.0', '2.0').
        """
        v = complex(1, 2)
        enc = encodage.encoder_canonique(v)
        assert "__complex__" in enc, f"Balise __complex__ absente dans {enc}"
        assert "1.0" in enc, "Partie réelle '1.0' non trouvée"
        assert "2.0" in enc, "Partie imaginaire '2.0' non trouvée"


class TestRefus:
    """Garantit qu'un type non explicitement supporté lève TypeError en
    nommant le type fautif, sans recourir à repr() ou à un repli silencieux.
    """

    @staticmethod
    def _lever_typeerror(valeur, nom_attendu):
        with pytest.raises(TypeError, match=nom_attendu):
            encodage.encoder_canonique(valeur)

    def test_object_refuse(self):
        """Un objet nu (object()) est refusé."""
        self._lever_typeerror(object(), "object")

    def test_fonction_refuse(self):
        """Une fonction utilisateur est refusée."""
        def f():
            pass  # proof:allow — donnée de test : objet volontairement non supporté
        self._lever_typeerror(f, "function")

    def test_module_refuse(self):
        """Un module importé est refusé."""
        import os as module_cible
        self._lever_typeerror(module_cible, "module")

    def test_objet_contenant_set_refuse(self):
        """Un objet personnalisé contenant un set est refusé, le message
        d'erreur mentionne le nom de la classe personnalisée.
        """
        class X:
            contenu = {1, 2, 3}
        instance = X()
        self._lever_typeerror(instance, "X")


class TestEmpreinte:
    """Vérifie que l'empreinte sha256 d'une valeur est une chaîne hexadécimale
    de 64 caractères, stable et distincte pour des valeurs différentes.
    """

    def test_empreinte_hex_64(self):
        """L'empreinte est constituée exactement de 64 caractères hexadécimaux."""
        emp = encodage.empreinte("chaîne de test")
        assert len(emp) == 64, f"Longueur {len(emp)} au lieu de 64"
        assert all(c in "0123456789abcdef" for c in emp), (
            "Caractères non hexadécimaux dans l'empreinte"
        )

    def test_empreinte_stable(self):
        """Une même valeur produit la même empreinte lors d'appels successifs."""
        v = {"a": [1, 2, 3], "b": decimal.Decimal("1.5")}
        e1 = encodage.empreinte(v)
        e2 = encodage.empreinte(v)
        assert e1 == e2, "L'empreinte n'est pas stable"

    def test_empreinte_differente(self):
        """Deux valeurs distinctes génèrent deux empreintes différentes."""
        e1 = encodage.empreinte("abc")
        e2 = encodage.empreinte("abd")
        assert e1 != e2, "Deux valeurs différentes ne devraient pas avoir la même empreinte"

class TestInjectiviteNumerique:
    """Cas DISCRIMINANTS du préfixage par longueur : sans lui, la sérialisation
    JSON concaténée confond des tuples numériques distincts — les guillemets
    protègent les chaînes, PAS les nombres. Mutation visée : retrait du
    préfixe len(serial)."""

    def test_collision_numerique_multiargs(self):
        """(1, 2) et (12,) : sans préfixage, '1'+'2' == '12'."""
        assert encodage.encoder_canonique(1, 2) != encodage.encoder_canonique(12), (
            "collision numérique multi-arguments : le préfixage par longueur ne protège plus"
        )

    def test_collision_numerique_triple(self):
        """(1, 23) et (12, 3) : même concaténation brute '123'."""
        assert encodage.encoder_canonique(1, 23) != encodage.encoder_canonique(12, 3), (
            "collision numérique : le préfixage par longueur ne protège plus"
        )


    def test_dict_independant_de_l_ordre_d_insertion(self):
        """DISCRIMINANT pour le tri des clés : deux dicts au même contenu mais
        construits dans des ordres d'insertion opposés doivent donner la même
        forme. Depuis Python 3.7 l'ordre d'insertion est préservé et stable —
        sans tri explicite, la suppression du tri serait invisible à tout test
        n'utilisant qu'un seul ordre d'insertion (leçon des mutations M2-S007)."""
        d1 = {"b": 2, "a": 1, "c": 3}
        d2 = {"c": 3, "a": 1, "b": 2}
        assert encodage.encoder_canonique(d1) == encodage.encoder_canonique(d2), (
            "la forme canonique doit être indépendante de l'ordre d'insertion des clés"
        )


class TestEmpreinteLieeALaForme:
    """L'empreinte doit être DÉRIVÉE de la forme canonique — pas une seconde
    vérité parallèle. Mutation visée : empreinte calculée sur autre chose que
    encoder_canonique (deux implémentations divergeraient en silence)."""

    def test_empreinte_est_sha256_de_la_forme(self):
        """empreinte(*v) == sha256(encoder_canonique(*v)) — le lien exact."""
        import hashlib
        valeurs = ({"b": 2, "a": 1}, [3, 1], "x")
        attendu = hashlib.sha256(
            encodage.encoder_canonique(*valeurs).encode("utf-8")
        ).hexdigest()
        assert encodage.empreinte(*valeurs) == attendu, (
            "l'empreinte doit être le sha256 de la forme canonique, pas une "
            "dérivation parallèle"
        )

