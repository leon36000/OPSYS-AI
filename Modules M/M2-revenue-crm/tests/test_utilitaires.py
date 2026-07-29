import sys
import os
import importlib
import inspect
import subprocess
from pathlib import Path
import pytest
import yaml

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import encodage  # noqa: E402
import horodatage  # noqa: E402
import verdicts  # noqa: E402
import fixtures_garde  # noqa: E402


# ----------------------------------------------------------------------
# 1. encodage.encoder_canonique — injectif, déterministe, inter-processus
# ----------------------------------------------------------------------
class TestEncoderCanonique:
    def test_injectivite_contre_concatenation_directe_ab_x_vs_a_bx(self):
        res1 = encodage.encoder_canonique("AB", "X")
        res2 = encodage.encoder_canonique("A", "BX")
        assert res1 != res2, "Collision par concaténation directe AB+X vs A+BX"

    def test_injectivite_contre_concatenation_directe_espaces(self):
        res1 = encodage.encoder_canonique("A", " BC")
        res2 = encodage.encoder_canonique("A ", "BC")
        assert res1 != res2, "Collision avec espaces A+' BC' vs 'A '+BC"

    def test_determinisme_meme_processus(self):
        v1 = encodage.encoder_canonique("alpha", 123, {"k": "v"})
        v2 = encodage.encoder_canonique("alpha", 123, {"k": "v"})
        assert v1 == v2, "Déterminisme intra-processus violé"

    def test_determinisme_inter_processus(self):
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
        assert (
            len(set(outputs)) == 1
        ), f"Déterminisme inter-processus brisé, sorties divergentes : {outputs}"


# ----------------------------------------------------------------------
# 2. horodatage.valider_horodatage — accepte avec timezone, refuse sinon
# ----------------------------------------------------------------------
class TestValiderHorodatage:
    def test_horodatage_valide_accepte(self):
        entree = "2026-07-26T12:00:00+00:00"
        resultat = horodatage.valider_horodatage(entree)
        assert isinstance(resultat, str)
        # on n'exige pas de normalisation particulière, juste que c'est une chaîne

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
    def test_horodatage_invalide_leve_valueerror_avec_rej_et_sans_details_datetime(
        self, invalide
    ):
        with pytest.raises(ValueError) as exc_info:
            horodatage.valider_horodatage(invalide)
        msg = str(exc_info.value)
        assert "REJ-HORODATAGE-INVALIDE" in msg, (
            f"Message d'erreur attendu contenant REJ-HORODATAGE-INVALIDE pour '{invalide}', "
            f"reçu : {msg}"
        )
        for motif in ("month must be", "Invalid isoformat"):
            assert motif not in msg, (
                f"Message d'erreur expose un détail brut de datetime : '{motif}' dans '{msg}'"
            )
        assert (
            exc_info.value.__cause__ is None
        ), "L'exception ne doit pas chaîner une cause (__cause__ doit être None)"


# ----------------------------------------------------------------------
# 3. verdicts.construire_verdict et est_verdict
# ----------------------------------------------------------------------
CODES_M2 = {
    "REJ-FRONTIERE-VIOLEE",
    "REJ-TRANSITION-ILLEGALE",
    "REJ-OWNER-ABSENT",
    "REJ-ACTION-ABSENTE",
    "REJ-DEVIS-ABSENT",
    "REJ-MOTIF-ABSENT",
    "REJ-ADAPTATEUR-INDISPONIBLE",
    "OK",
}
# REJ-CONVERSATION-CLOSE a été RETIRÉ de cette liste le 2026-07-29 : le cadrage ratifié
# (PRD et architecture) en fait un invariant transversal explicitement repris par M2, donc
# le classer « hors M2 » encodait une croyance fausse. Le test de cohérence
# catalogue↔cadrage empêche désormais ce genre d'écart de réapparaître.
CODES_HORS_M2 = [
    "REJ-CONSENTEMENT-ABSENT",
    "REJ-QUALIF-INSUFFISANTE",
]


class TestVerdictsEstVerdict:
    @pytest.mark.parametrize("code", CODES_M2)
    def test_est_verdict_vrai_pour_codes_m2(self, code):
        assert verdicts.est_verdict(code) is True, f"Le code '{code}' doit être reconnu M2"

    @pytest.mark.parametrize("code", CODES_HORS_M2)
    def test_est_verdict_faux_pour_codes_hors_m2(self, code):
        assert verdicts.est_verdict(code) is False, (
            f"Le code '{code}' ne doit pas être reconnu M2"
        )

    def test_est_verdict_faux_pour_code_inconnu(self):
        assert verdicts.est_verdict("INCONNU") is False


class TestVerdictsConstruireVerdict:
    @pytest.mark.parametrize("code", CODES_M2)
    def test_construire_verdict_accepte_codes_m2(self, code):
        resultat = verdicts.construire_verdict(code, "statut_test", "detail_test")
        assert isinstance(resultat, dict)
        assert resultat.get("code") == code

    @pytest.mark.parametrize("code", CODES_HORS_M2)
    def test_construire_verdict_leve_sur_codes_hors_m2(self, code):
        with pytest.raises(Exception):
            verdicts.construire_verdict(code, "statut", "detail")

    def test_construire_verdict_leve_sur_code_inconnu(self):
        with pytest.raises(Exception):
            verdicts.construire_verdict("INCONNU", "statut", "detail")


# ----------------------------------------------------------------------
# 4. fixtures_garde.charger_fixture — fail-closed sur fictif
# ----------------------------------------------------------------------
class TestFixturesGarde:
    @pytest.fixture
    def ecrire_fixture(self, tmp_path):
        def _ecrire(nom, contenu_dict):
            chemin = tmp_path / nom
            chemin.write_text(yaml.dump(contenu_dict), encoding="utf-8")
            return chemin

        return _ecrire

    def test_accepte_fictif_true(self, ecrire_fixture):
        chemin = ecrire_fixture("avec_fictif.yaml", {"fictif": True, "data": 42})
        doc = fixtures_garde.charger_fixture(chemin)
        assert doc["fictif"] is True

    @pytest.mark.parametrize(
        "contenu",
        [
            {"fictif": False},
            {"fictif": "true"},
            {"fictif": 1},
            {},
        ],
        ids=[
            "marqueur_false",
            "marqueur_chaine_true",
            "marqueur_entier_un",
            "marqueur_absent",
        ],
    )
    def test_refuse_toute_variante_non_strict_true(self, ecrire_fixture, contenu):
        """
        Toute variante non strictement égale à True est refusée : l'exception
        est FixtureNonFictive, son message porte le code stable reconnu par
        verdicts.est_verdict et un détail au-delà du code, et le fichier de
        fixture survit au refus.
        """
        chemin = ecrire_fixture("variante_non_strict_true.yml", contenu)
        with pytest.raises(fixtures_garde.FixtureNonFictive) as exc_info:
            fixtures_garde.charger_fixture(chemin)
        message = str(exc_info.value)
        assert "REJ-FIXTURE-NON-FICTIVE" in message, (
            f"Le message doit contenir le code stable REJ-FIXTURE-NON-FICTIVE, "
            f"obtenu : {message!r}"
        )
        assert verdicts.est_verdict("REJ-FIXTURE-NON-FICTIVE"), (
            "verdicts.est_verdict doit reconnaître REJ-FIXTURE-NON-FICTIVE : "
            "c'est le lien qui rend le catalogue utile à un appelant"
        )
        assert len(message) > len("REJ-FIXTURE-NON-FICTIVE"), (
            f"Le message doit expliquer le refus au-delà du seul code, "
            f"obtenu : {message!r}"
        )
        assert chemin.exists(), (
            f"Le fichier de fixture doit exister encore après le refus : {chemin}"
        )

    @pytest.mark.parametrize(
        "contenu,description",
        [
            ([1, 2, 3], "document liste"),
            ("chaine nue", "document chaîne nue"),
            (None, "document nul"),
        ],
        ids=["document_liste", "document_chaine_nue", "document_nul"],
    )
    def test_refuse_document_non_dictionnaire(
        self, ecrire_fixture, contenu, description
    ):
        """
        Un document YAML qui n'est pas un dictionnaire (liste, chaîne nue,
        document nul) ne peut pas porter la clé « fictif » : le chargement
        doit lever FixtureNonFictive, le message doit porter le code stable
        REJ-FIXTURE-NON-FICTIVE et expliquer le refus, et le fichier doit
        rester en place.
        """
        chemin = ecrire_fixture("fixture_non_dict.yaml", contenu)
        with pytest.raises(fixtures_garde.FixtureNonFictive) as excinfo:
            fixtures_garde.charger_fixture(chemin)
        message = str(excinfo.value)
        assert "REJ-FIXTURE-NON-FICTIVE" in message, (
            f"Cas {description} : le message de refus doit contenir le "
            f"code stable REJ-FIXTURE-NON-FICTIVE, obtenu : {message!r}"
        )
        assert len(message) > len("REJ-FIXTURE-NON-FICTIVE"), (
            f"Cas {description} : le message de refus doit expliquer et "
            f"non se limiter au seul code stable, obtenu : {message!r}"
        )
        assert chemin.exists(), (
            f"Cas {description} : le fichier de fixture doit rester en "
            f"place après le refus : {chemin}"
        )

# ----------------------------------------------------------------------
# 5. Zéro réseau / horloge / LLM dans les sources des modules
# ----------------------------------------------------------------------
class TestModulesSansReseauNiHorlogeNiLLM:
    @pytest.mark.parametrize(
        "module_name",
        ["encodage", "horodatage", "verdicts", "fixtures_garde"],
    )
    def test_source_sans_motifs_interdits(self, module_name):
        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            pytest.fail(f"Module {module_name} introuvable, impossible de vérifier la source")
        source = inspect.getsource(mod)
        motifs_interdits = [
            "urllib",
            "socket",
            "http.client",
            "requests",
            "datetime.now",
            "time.time",
            "openai",
            "litellm",
        ]
        for motif in motifs_interdits:
            assert motif not in source, (
                f"Motif interdit '{motif}' trouvé dans le module {module_name}"
            )


import os
import subprocess
import sys
from pathlib import Path

import pytest

import encodage


# 1. Conteneurs vides de types différents : empreintes toutes distinctes
@pytest.mark.parametrize("c1,c2", [
    (set(), frozenset()),
    (set(), list()),
    (set(), tuple()),
    (set(), dict()),
    (frozenset(), list()),
    (frozenset(), tuple()),
    (frozenset(), dict()),
    (list(), tuple()),
    (list(), dict()),
    (tuple(), dict()),
])
def test_conteneurs_vides_de_types_differents_ne_collisionnent_pas(c1, c2):
    """Vérifie que deux conteneurs vides de types différents n'ont jamais la même empreinte."""
    e1 = encodage.empreinte(c1)
    e2 = encodage.empreinte(c2)
    assert e1 != e2, (
        f"Collision entre {type(c1).__name__} et {type(c2).__name__} : {e1!r} == {e2!r}"
    )


# 2. Déterminisme inter-processus pour une structure imbriquée hétérogène
def test_determinisme_inter_processus_structure_imbriquee():
    """Empreinte déterministe quelle que soit PYTHONHASHSEED pour une structure complexe."""
    structure_literal = '{"x": {"a","b","c","d","e"}, "y": [3,1,2], "z": ({"k": {1,2}}, frozenset(["q"]))}'
    src_dir = Path(__file__).resolve().parents[1] / "src"
    src_dir_str = src_dir.as_posix()
    code = (
        f"import sys\n"
        f"sys.path.insert(0, {src_dir_str!r})\n"
        f"import encodage\n"
        f"print(encodage.empreinte({structure_literal}))"
    )
    graines = ["0", "1", "42", "1337", "99991"]
    sorties = []
    for graine in graines:
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = graine
        res = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, (
            f"Échec subprocess avec PYTHONHASHSEED={graine} : {res.stderr}"
        )
        sorties.append(res.stdout.strip())

    assert sorties, "Aucune sortie collectée (garde-fou de non-vacuité)"
    unique = set(sorties)
    assert len(unique) == 1, (
        f"Les empreintes diffèrent selon PYTHONHASHSEED : {dict(zip(graines, sorties))}"
    )


# 3. Familles de collision classiques
@pytest.mark.parametrize("v1,v2", [
    ([[1], [2]], [1, 2]),
    ({"a": 1}, {("a", 1)}),
    ("1", 1),
    (True, 1),
    (None, "None"),
    ([], [[]]),
])
def test_familles_de_collision_classiques(v1, v2):
    """Chaque paire doit produire des empreintes distinctes (pièges d'égalité Python)."""
    e1 = encodage.empreinte(v1)
    e2 = encodage.empreinte(v2)
    assert e1 != e2, (
        f"Collision inattendue : {v1!r} (type {type(v1).__name__}) et "
        f"{v2!r} (type {type(v2).__name__}) ont la même empreinte {e1!r}"
    )


class TestEncodageRefusTypesNonCanoniques:
    def test_objet_quelconque_refuse(self):
        class TypeNonCanonique:
            pass
        obj = TypeNonCanonique()
        with pytest.raises(TypeError, match="TypeNonCanonique"):
            encodage.encoder_canonique(obj)

    @pytest.mark.parametrize("fabrique", [
        lambda obj: [obj],
        lambda obj: {"a": obj},
        lambda obj: (obj,)
    ])
    def test_valeur_non_supportee_imbriquee_refusee(self, fabrique):
        class ObjetNonCanonique:
            pass
        obj = ObjetNonCanonique()
        structure = fabrique(obj)
        with pytest.raises(TypeError):
            encodage.encoder_canonique(structure)

    def test_types_supportes_toujours_acceptes(self):
        data = {
            "str": "hello",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
            "list": [1, "a"],
            "tuple": (2, "b"),
            "set": {3, 4},
            "frozenset": frozenset([5, 6]),
            "nested": {"inner_list": [7, 8]},
        }
        result = encodage.encoder_canonique(data)
        assert isinstance(result, str), "Résultat doit être une chaîne"
        assert len(result) == 64, "Empreinte SHA-256 a 64 caractères hex"
        assert all(c in "0123456789abcdef" for c in result), "Caractères hexadécimaux attendus"

    def test_refus_explicite_plutot_que_hash_non_reproductible(self):
        class ObjetNonCanonique:
            pass
        a = ObjetNonCanonique()
        b = ObjetNonCanonique()
        with pytest.raises(TypeError):
            encodage.encoder_canonique(a)
        with pytest.raises(TypeError):
            encodage.encoder_canonique(b)


class TestEncodageTypesStandards:
    """Vérifie le support typé explicite des types standards dans l'encodage canonique."""

    @pytest.mark.parametrize(
        "nom_type",
        ["decimal", "datetime", "date", "time", "uuid", "bytes", "bytearray", "complex"],
        ids=["decimal", "datetime", "date", "time", "uuid", "bytes", "bytearray", "complex"],
    )
    def test_types_standards_acceptes(self, nom_type):
        """Chacun des 8 types standards supportés produit une empreinte hexadécimale de 64 caractères."""
        from decimal import Decimal
        from datetime import date, datetime, time
        from uuid import UUID
        valeurs = {
            "decimal": Decimal("1.5"),
            "datetime": datetime(2024, 3, 1, 12, 30, 0),
            "date": date(2024, 3, 1),
            "time": time(12, 30, 0),
            "uuid": UUID("12345678-1234-5678-1234-567812345678"),
            "bytes": b"\x00\x01\xfe\xff",
            "bytearray": bytearray(b"\x00\x01\xfe\xff"),
            "complex": complex(1.5, -2.25),
        }
        empreinte = encodage.empreinte(valeurs[nom_type])
        assert isinstance(empreinte, str) and len(empreinte) == 64 and all(
            c in "0123456789abcdef" for c in empreinte
        ), (
            f"L'empreinte pour le type {nom_type} doit être une chaîne hexadécimale "
            f"de 64 caractères, obtenu : {empreinte!r}."
        )

    def test_injectivite_contre_la_chaine_equivalente(self):
        """La collision de l'ancien repli repr() ne doit plus exister : la valeur typée
        ne partage son empreinte ni avec la chaîne repr(valeur) ni avec la chaîne str(valeur)."""
        from decimal import Decimal
        from datetime import datetime
        from uuid import UUID
        valeurs = [
            Decimal("1.5"),
            UUID("12345678-1234-5678-1234-567812345678"),
            datetime(2024, 3, 1, 12, 30, 0),
        ]
        for v in valeurs:
            empreinte_typee = encodage.empreinte(v)
            empreinte_repr = encodage.empreinte(repr(v))
            empreinte_str = encodage.empreinte(str(v))
            assert empreinte_typee != empreinte_repr, (
                f"Collision injectivité pour {type(v).__name__} : l'empreinte de la valeur "
                f"typée égale celle de la chaîne repr({v!r}) — la balise de type est perdue."
            )
            assert empreinte_typee != empreinte_str, (
                f"Collision injectivité pour {type(v).__name__} : l'empreinte de la valeur "
                f"typée égale celle de la chaîne str({v!r}) — la balise de type est perdue."
            )

    def test_decimal_conserve_lexposant(self):
        """Decimal('1.50') et Decimal('1.5') sont deux valeurs distinctes pour un montant
        et doivent produire deux empreintes différentes."""
        from decimal import Decimal
        empreinte_150 = encodage.empreinte(Decimal("1.50"))
        empreinte_15 = encodage.empreinte(Decimal("1.5"))
        assert empreinte_150 != empreinte_15, (
            "Decimal('1.50') et Decimal('1.5') doivent avoir des empreintes distinctes : "
            "la forme canonique str() conserve l'exposant, toute normalisation qui les "
            "confond est une perte d'information."
        )

    def test_datetime_nest_pas_confondu_avec_date(self):
        """Un datetime à minuit et le date correspondant donnent deux empreintes différentes :
        datetime est une sous-classe de date, son test doit passer avant celui de date."""
        from datetime import date, datetime
        empreinte_datetime = encodage.empreinte(datetime(2024, 3, 1, 0, 0, 0))
        empreinte_date = encodage.empreinte(date(2024, 3, 1))
        assert empreinte_datetime != empreinte_date, (
            "datetime(2024, 3, 1, 0, 0, 0) et date(2024, 3, 1) doivent avoir des empreintes "
            "distinctes : si elles sont égales, le test isinstance(datetime) passe après "
            "celui de date et l'heure est perdue (piège de la sous-classe)."
        )

    def test_type_reellement_non_canonique_toujours_refuse(self):
        """Une classe locale minimale reste refusée par TypeError : le refus n'a pas été affaibli."""
        class ObjetArbitraire:
            """Classe locale minimale sans forme canonique stable."""
            attribut = 1
        with pytest.raises(TypeError, match="Type non supporté"):
            encodage.empreinte(ObjetArbitraire())

    def test_determinisme_inter_processus_types_standards(self):
        """Une structure contenant Decimal, datetime, UUID et bytes produit la même empreinte
        dans tous les processus, quel que soit PYTHONHASHSEED, et dans le processus courant."""
        from decimal import Decimal
        from datetime import datetime
        from uuid import UUID
        src = Path(__file__).resolve().parents[1] / "src"
        script = (
            "import sys\n"
            f"sys.path.insert(0, {str(src)!r})\n"
            "import encodage\n"
            "from decimal import Decimal\n"
            "from datetime import datetime\n"
            "from uuid import UUID\n"
            "structure = {\n"
            "    'montant': Decimal('1.50'),\n"
            "    'quand': datetime(2024, 3, 1, 12, 30, 0),\n"
            "    'identifiant': UUID('12345678-1234-5678-1234-567812345678'),\n"
            "    'brut': b'\\x00\\x01\\xfe\\xff',\n"
            "}\n"
            "print(encodage.empreinte(structure))\n"
        )
        graines = ["0", "1", "42"]
        empreintes = []
        for graine in graines:
            env = dict(os.environ)
            env["PYTHONHASHSEED"] = graine
            resultat = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env=env,
            )
            assert resultat.returncode == 0, (
                f"Le sous-processus (PYTHONHASHSEED={graine}) a échoué avec le code "
                f"{resultat.returncode} : {resultat.stderr}"
            )
            empreintes.append(resultat.stdout.strip())
        assert len(set(empreintes)) == 1, (
            f"Empreintes divergentes entre processus pour PYTHONHASHSEED={graines} : "
            f"{empreintes} — la forme canonique des types standards n'est pas déterministe."
        )
        structure_locale = {
            "montant": Decimal("1.50"),
            "quand": datetime(2024, 3, 1, 12, 30, 0),
            "identifiant": UUID("12345678-1234-5678-1234-567812345678"),
            "brut": b"\x00\x01\xfe\xff",
        }
        empreinte_locale = encodage.empreinte(structure_locale)
        assert empreintes[0] == empreinte_locale, (
            f"L'empreinte du processus courant ({empreinte_locale}) diffère de celle des "
            f"sous-processus ({empreintes[0]}) : le déterminisme inter-processus est rompu."
        )


class TestInjectiviteExhaustive:
    """Garantit l'injectivité permanente du balisage de types de l'encodage canonique.

    Une valeur typée ne doit jamais produire la même empreinte qu'une liste ou
    un tuple littéral de même forme fourni par l'appelant, et aucune paire de
    valeurs distinctes d'un panel hétérogène ne doit partager une empreinte.
    """

    @pytest.mark.parametrize(
        "type_cible, argument_brut, balise, forme_canonique, conteneur",
        [
            ("decimal", "1.5", "__decimal__", "1.5", "liste"),
            ("bytes", b"\xab", "__bytes__", "ab", "liste"),
            ("bytearray", b"\xab", "__bytearray__", "ab", "liste"),
            ("uuid", "12345678-1234-5678-1234-567812345678", "__uuid__", "12345678-1234-5678-1234-567812345678", "liste"),
            ("date", (2026, 7, 29), "__date__", "2026-07-29", "liste"),
            ("datetime", (2026, 7, 29, 12, 30, 0), "__datetime__", "2026-07-29T12:30:00+00:00", "liste"),
            ("time", (9, 15, 0), "__time__", "09:15:00", "liste"),
            ("decimal", "1.5", "__decimal__", "1.5", "tuple"),
            ("complex", (1.0, 2.0), "__complex__", ["1.0", "2.0"], "liste"),
            ("complex", (1.0, 2.0), "__complex__", ["1.0", "2.0"], "tuple"),
            ("complex", (1.0, 2.0), "__complex__", ["1.0", "2.0"], "mixte"),
        ],
        ids=[
            "decimal_vs_liste_meme_forme",
            "bytes_vs_liste_meme_forme",
            "bytearray_vs_liste_meme_forme",
            "uuid_vs_liste_meme_forme",
            "date_vs_liste_meme_forme",
            "datetime_vs_liste_meme_forme",
            "time_vs_liste_meme_forme",
            "decimal_vs_tuple_meme_forme",
            "complex_vs_liste_meme_forme",
            "complex_vs_tuple_meme_forme",
            "complex_vs_mixte_liste_exterieure_tuple_interieur",
        ],
    )
    def test_valeur_typee_ne_collisionne_pas_avec_la_liste_de_meme_forme(
        self, type_cible, argument_brut, balise, forme_canonique, conteneur
    ):
        """Une valeur typée et la valeur littérale de même forme (liste, tuple,
        ou forme mixte liste extérieure / tuple intérieur) doivent produire deux
        formes normalisées distinctes, et donc deux empreintes distinctes.

        Boîte blanche : l'usage de ``encodage._normaliser`` est volontaire et
        documenté — le test prouve que la non-collision provient de la
        normalisation elle-même (balisage récursif des conteneurs), et non d'un
        hasard de hachage. ``forme_canonique`` est une chaîne pour les types
        scalaires, et une séquence pour ``complex`` dont la forme canonique est
        ``[repr(partie_reelle), repr(partie_imaginaire)]``.
        """
        from decimal import Decimal
        from uuid import UUID
        from datetime import date, datetime, time, timezone

        if type_cible == "decimal":
            valeur_typee = Decimal(argument_brut)
        elif type_cible == "bytes":
            valeur_typee = bytes(argument_brut)
        elif type_cible == "bytearray":
            valeur_typee = bytearray(argument_brut)
        elif type_cible == "uuid":
            valeur_typee = UUID(argument_brut)
        elif type_cible == "date":
            valeur_typee = date(*argument_brut)
        elif type_cible == "datetime":
            valeur_typee = datetime(*argument_brut, tzinfo=timezone.utc)
        elif type_cible == "time":
            valeur_typee = time(*argument_brut)
        elif type_cible == "complex":
            valeur_typee = complex(*argument_brut)
        else:
            raise AssertionError(f"type_cible non pris en charge : {type_cible!r}")

        if isinstance(forme_canonique, str):
            contenu_litteral = forme_canonique
        elif conteneur == "liste":
            contenu_litteral = list(forme_canonique)
        else:
            contenu_litteral = tuple(forme_canonique)

        if conteneur == "tuple":
            valeur_litterale = (balise, contenu_litteral)
        elif conteneur in ("liste", "mixte"):
            valeur_litterale = [balise, contenu_litteral]
        else:
            raise AssertionError(f"conteneur non pris en charge : {conteneur!r}")

        forme_typee = encodage._normaliser(valeur_typee)
        forme_litterale = encodage._normaliser(valeur_litterale)
        assert forme_typee != forme_litterale, (
            f"les formes normalisées devraient différer : "
            f"_normaliser({valeur_typee!r}) = {forme_typee!r} contre "
            f"_normaliser({valeur_litterale!r}) = {forme_litterale!r}"
        )

        empreinte_typee = encodage.empreinte(valeur_typee)
        empreinte_litterale = encodage.empreinte(valeur_litterale)
        assert empreinte_typee != empreinte_litterale, (
            f"collision d'empreintes entre la valeur typée {valeur_typee!r} "
            f"et la valeur littérale {valeur_litterale!r} : "
            f"{empreinte_typee} == {empreinte_litterale}"
        )
    def test_panel_heterogene_sans_aucune_collision(self):
        """Aucune paire distincte du panel hétérogène ne doit produire la même
        empreinte ; le nombre de paires comparées doit valoir n*(n-1)/2."""
        import itertools
        from decimal import Decimal
        from uuid import UUID
        from datetime import date, datetime, time, timezone

        panel = {
            "entier_un": 1,
            "decimal_un": Decimal("1"),
            "decimal_un_virgule_zero": Decimal("1.0"),
            "decimal_un_cinq": Decimal("1.5"),
            "flottant_un": 1.0,
            "chaine_un": "1",
            "chaine_balise_decimal": "__decimal__",
            "booleen_vrai": True,
            "booleen_faux": False,
            "valeur_none": None,
            "bytes_ab": b"\xab",
            "bytearray_ab": bytearray(b"\xab"),
            "chaine_hex_ab": "ab",
            "date_fixe": date(2026, 7, 29),
            "datetime_minuit_naif": datetime(2026, 7, 29, 0, 0, 0),
            "datetime_utc_apres_midi": datetime(2026, 7, 29, 12, 30, 0, tzinfo=timezone.utc),
            "time_minuit": time(0, 0, 0),
            "uuid_fixe": UUID("12345678-1234-5678-1234-567812345678"),
            "chaine_uuid": "12345678-1234-5678-1234-567812345678",
            "set_abc": {"a", "b", "c"},
            "frozenset_abc": frozenset({"a", "b", "c"}),
            "liste_abc": ["a", "b", "c"],
            "tuple_abc": ("a", "b", "c"),
            "dict_simple": {"cle": "valeur"},
            "complexe_un_deux": complex(1, 2),
            "liste_forme_decimal": ["__decimal__", "1.5"],
            "liste_vide": [],
            "tuple_vide": (),
            "dict_vide": {},
        }
        assert len(panel) >= 18, (
            f"le panel hétérogène doit contenir au moins 18 valeurs, "
            f"il en contient {len(panel)}"
        )

        empreintes = {
            nom: encodage.empreinte(valeur) for nom, valeur in panel.items()
        }

        collisions = []
        paires_comparees = 0
        for (nom_a, empreinte_a), (nom_b, empreinte_b) in itertools.combinations(
            empreintes.items(), 2
        ):
            paires_comparees += 1
            if empreinte_a == empreinte_b:
                collisions.append((nom_a, nom_b, empreinte_a))

        nombre_valeurs = len(empreintes)
        paires_attendues = nombre_valeurs * (nombre_valeurs - 1) // 2
        assert paires_comparees == paires_attendues, (
            f"nombre de paires réellement comparées ({paires_comparees}) "
            f"différent du nombre attendu n*(n-1)/2 ({paires_attendues}) "
            f"pour n={nombre_valeurs} valeurs"
        )

        assert not collisions, (
            f"{len(collisions)} collision(s) d'empreintes détectée(s) dans le "
            f"panel : "
            + "; ".join(
                f"{nom_a}={panel[nom_a]!r} <-> {nom_b}={panel[nom_b]!r} "
                f"(empreinte commune {empreinte_commune})"
                for nom_a, nom_b, empreinte_commune in collisions
            )
        )


class TestBalisesDisjointes:
    """Garantit que les balises de conteneur et les balises de type standard forment
    deux familles disjointes dans l'encodage canonique.

    Argument d'injectivité vérifié ici : toute valeur fournie par l'appelant est soit
    un scalaire, soit un conteneur ; un conteneur reçoit toujours une balise de
    CONTENEUR, jamais une balise de type standard. Les deux familles étant disjointes,
    aucune valeur littérale ne peut usurper la forme normalisée d'une valeur typée.

    API en boîte blanche utilisée : ``encodage._normaliser`` (fonction interne du
    module d'encodage canonique M2). Pour une valeur typée ou un conteneur, elle
    retourne une liste dont le premier élément est la balise ; pour un scalaire
    (str, int, float, bool, None), elle retourne la valeur telle quelle.
    """

    BALISES_CONTENEUR = frozenset({
        "__dict__",
        "__set__",
        "__frozenset__",
        "__list__",
        "__tuple__",
    })

    BALISES_TYPE_STANDARD = frozenset({
        "__decimal__",
        "__datetime__",
        "__date__",
        "__time__",
        "__uuid__",
        "__bytes__",
        "__bytearray__",
        "__complex__",
    })

    def test_les_deux_familles_de_balises_sont_disjointes(self):
        """Vérifie que l'intersection des deux familles de balises est vide.

        C'est le cœur de l'argument d'injectivité : si une balise appartenait aux
        deux familles, un conteneur littéral pourrait produire la même forme
        normalisée qu'une valeur typée. Le message d'échec liste les balises
        fautives.
        """
        communes = sorted(self.BALISES_CONTENEUR & self.BALISES_TYPE_STANDARD)
        assert not communes, (
            f"Balises présentes dans les deux familles (collision d'encodage "
            f"possible entre conteneur littéral et valeur typée) : {communes}"
        )

    @pytest.mark.parametrize(
        "valeur",
        [
            {"cle": "valeur"},
            {"element"},
            frozenset({"element"}),
            ["element"],
            ("element",),
        ],
        ids=["dict", "set", "frozenset", "list", "tuple"],
    )
    def test_chaque_conteneur_recoit_une_balise_de_conteneur(self, valeur):
        """Vérifie qu'un conteneur non vide est normalisé sous une balise de conteneur.

        ``encodage._normaliser(valeur)[0]`` doit appartenir à ``BALISES_CONTENEUR``
        et ne jamais appartenir à ``BALISES_TYPE_STANDARD`` : c'est la propriété qui
        interdit à une valeur littérale d'usurper la forme d'une valeur typée.
        """
        balise = encodage._normaliser(valeur)[0]
        assert balise in self.BALISES_CONTENEUR, (
            f"Le conteneur {valeur!r} a reçu la balise {balise!r}, "
            f"attendu parmi {sorted(self.BALISES_CONTENEUR)}"
        )
        assert balise not in self.BALISES_TYPE_STANDARD, (
            f"Le conteneur {valeur!r} a reçu la balise de type standard "
            f"{balise!r} : un littéral peut désormais usurper une valeur typée"
        )

    @pytest.mark.parametrize(
        "type_cible, argument_brut, balise_attendue",
        [
            ("decimal", "1.5", "__decimal__"),
            ("datetime", (2026, 7, 29, 12, 30, 0), "__datetime__"),
            ("date", (2026, 7, 29), "__date__"),
            ("time", (9, 15, 0), "__time__"),
            ("uuid", "12345678-1234-5678-1234-567812345678", "__uuid__"),
            ("bytes", b"\xab", "__bytes__"),
            ("bytearray", b"\xab", "__bytearray__"),
            ("complex", (1.0, 2.0), "__complex__"),
        ],
        ids=[
            "decimal",
            "datetime",
            "date",
            "time",
            "uuid",
            "bytes",
            "bytearray",
            "complex",
        ],
    )
    def test_chaque_type_standard_recoit_sa_balise(self, type_cible, argument_brut, balise_attendue):
        """Vérifie que chaque type standard est normalisé sous sa balise exacte.

        Les valeurs typées sont construites dans la méthode (imports locaux
        obligatoires) à partir d'arguments bruts ; ``encodage._normaliser`` doit
        produire une liste dont le premier élément est exactement la balise
        attendue, laquelle ne doit jamais être une balise de conteneur.
        """
        from datetime import date, datetime, time, timezone
        from decimal import Decimal
        from uuid import UUID

        fabriques = {
            "decimal": lambda: Decimal(argument_brut),
            "datetime": lambda: datetime(*argument_brut, tzinfo=timezone.utc),
            "date": lambda: date(*argument_brut),
            "time": lambda: time(*argument_brut),
            "uuid": lambda: UUID(argument_brut),
            "bytes": lambda: argument_brut,
            "bytearray": lambda: bytearray(argument_brut),
            "complex": lambda: complex(*argument_brut),
        }
        valeur = fabriques[type_cible]()
        balise = encodage._normaliser(valeur)[0]
        assert balise == balise_attendue, (
            f"La valeur {valeur!r} (type {type_cible}) a reçu la balise "
            f"{balise!r}, attendu exactement {balise_attendue!r}"
        )
        assert balise not in self.BALISES_CONTENEUR, (
            f"La valeur typée {valeur!r} a reçu la balise de conteneur "
            f"{balise!r} : collision possible avec un conteneur littéral"
        )

    def test_aucune_balise_oubliee(self):
        """Vérifie que chaque balise déclarée est réellement produite par le panel.

        Test d'exhaustivité : sans lui, ajouter une balise dans le code sans
        l'ajouter aux constantes de classe passerait inaperçu. Le panel contient
        13 valeurs écrites en dur, une par balise ; toute balise jamais produite
        est nommée dans le message d'échec.
        """
        from datetime import date, datetime, time, timezone
        from decimal import Decimal
        from uuid import UUID

        panel = [
            {"cle": "valeur"},
            {"element"},
            frozenset({"element"}),
            ["element"],
            ("element",),
            Decimal("1.5"),
            datetime(2026, 7, 29, 12, 30, 0, tzinfo=timezone.utc),
            date(2026, 7, 29),
            time(9, 15, 0),
            UUID("12345678-1234-5678-1234-567812345678"),
            b"\xab",
            bytearray(b"\xab"),
            complex(1.0, 2.0),
        ]
        assert len(panel) == 13, (
            f"Le panel doit contenir exactement 13 valeurs (une par balise), "
            f"il en contient {len(panel)}"
        )
        produites = {encodage._normaliser(valeur)[0] for valeur in panel}
        manquantes = sorted(
            balise
            for balise in self.BALISES_CONTENEUR | self.BALISES_TYPE_STANDARD
            if balise not in produites
        )
        assert not manquantes, (
            f"Balises déclarées dans les constantes mais jamais produites par "
            f"le panel de 13 valeurs : {manquantes}"
        )

    @pytest.mark.parametrize(
        "valeur",
        [
            "chaine",
            42,
            3.14,
            True,
            None,
        ],
        ids=["str", "int", "float", "bool", "none"],
    )
    def test_un_scalaire_nest_pas_balise(self, valeur):
        """Vérifie qu'un scalaire traverse ``encodage._normaliser`` sans balisage.

        Le résultat doit être égal à l'entrée ET du même type exact : ``True == 1``
        en Python, donc l'égalité seule ne suffit pas à distinguer un booléen d'un
        entier ; la comparaison ``type(...) is ...`` lève cette ambiguïté et
        empêche le test de passer par accident.
        """
        normalise = encodage._normaliser(valeur)
        assert normalise == valeur, (
            f"Le scalaire {valeur!r} a été transformé en {normalise!r} : "
            f"un scalaire doit être retourné tel quel, sans balisage"
        )
        assert type(normalise) is type(valeur), (
            f"Le scalaire {valeur!r} (type {type(valeur).__name__}) est ressorti "
            f"avec le type {type(normalise).__name__} : l'égalité seule masquerait "
            f"une confusion bool/int"
        )
        assert not isinstance(normalise, list), (
            f"Le scalaire {valeur!r} a produit la liste balisée {normalise!r} : "
            f"seuls les conteneurs et les valeurs typées sont balisés"
        )


class TestCatalogueCoherentAvecLeCadrage:
    """
    Cale le catalogue de verdicts sur les documents de cadrage ratifiés, dans
    les deux sens : tout identifiant prescrit doit être au catalogue, et tout
    code du catalogue doit être prescrit ou déclaré. Sans ce double sens,
    l'écart corrigé par la chore (identifiant transversal manquant) se
    reproduirait en silence.
    """

    # REJ-0040 est un identifiant de RÈGLE (« zéro LLM »), pas un code de
    # verdict : cité dans le cadrage, il ne doit jamais entrer au catalogue.
    EXCLUSIONS_CADRAGE = frozenset({"REJ-0040"})

    # Échappatoire réservée aux identifiants structurellement inextractibles du
    # cadrage (sans préfixe REJ-, donc invisibles pour l'expression régulière) ;
    # toute autre entrée y serait un vestige.
    ADDITIONS_DECLAREES = frozenset({
        "OK",
    })
    def _identifiants_cites_dans_le_cadrage(self):
        """
        Lit les fichiers Markdown de docs/bmad du module et retourne l'ensemble
        des identifiants de la forme REJ-* qui y sont cités.
        """
        import re

        dossier_docs = Path(__file__).resolve().parents[1] / "docs" / "bmad"
        corpus = "\n".join(
            chemin.read_text(encoding="utf-8")
            for chemin in sorted(dossier_docs.glob("*.md"))
        )
        return set(re.findall(r"REJ-[A-Z0-9-]+", corpus))

    # Le fichier du catalogue est exclu des sources inspectées : il *est* le
    # catalogue et ne s'émet pas lui-même, sinon tout code inventé dans le
    # catalogue s'auto-justifierait par sa seule présence dans ce fichier.
    FICHIER_CATALOGUE = "verdicts.py"

    def _identifiants_emis_par_les_sources(self):
        """
        Retourne le couple (ensemble des identifiants de verdict émis par
        les sources de src/, nombre de fichiers retenus après exclusion).

        Le fichier FICHIER_CATALOGUE est exclu du périmètre : il déclare le
        catalogue au lieu d'émettre des verdicts. Sa présence parmi les
        fichiers lus est vérifiée AVANT exclusion, afin qu'un renommage ne
        fasse pas disparaître l'exclusion en silence.
        """
        import re

        src = Path(__file__).resolve().parents[1] / "src"
        fichiers = sorted(src.glob("*.py"))
        noms_avant_exclusion = {chemin.name for chemin in fichiers}
        assert self.FICHIER_CATALOGUE in noms_avant_exclusion, (
            f"{self.FICHIER_CATALOGUE} introuvable parmi les sources de "
            f"{src} : un renommage du fichier catalogue ferait disparaître "
            "l'exclusion en silence et tout code inventé s'auto-justifierait."
        )
        fichiers = [
            chemin
            for chemin in fichiers
            if chemin.name != self.FICHIER_CATALOGUE
        ]
        codes_emis = set()
        for chemin in fichiers:
            texte = chemin.read_text(encoding="utf-8")
            codes_emis.update(
                re.findall(r"REJ-[A-Z0-9]+(?:-[A-Z0-9]+)*", texte)
            )
        return codes_emis, len(fichiers)
    def test_tout_code_prescrit_par_le_cadrage_est_au_catalogue(self):
        """
        Tout identifiant REJ-* prescrit par les documents ratifiés, hors
        exclusions justifiées, doit figurer dans le catalogue M2.
        """
        extraits = self._identifiants_cites_dans_le_cadrage()
        assert len(extraits) > 0, (
            "Aucun identifiant REJ-* extrait de docs/bmad : le dossier a "
            "probablement été renommé ou déplacé, et le test ne prouverait "
            "plus rien."
        )
        prescrits = extraits - self.EXCLUSIONS_CADRAGE
        manquants = sorted(code for code in prescrits if not verdicts.est_verdict(code))
        assert manquants == [], (
            f"Identifiants prescrits par le cadrage absents du catalogue M2 : "
            f"{manquants}"
        )

    def test_le_catalogue_ne_contient_aucun_code_orphelin(self):
        """
        Un code du catalogue est justifié s'il est cité dans le cadrage, ou
        émis par les sources du module, ou déclaré explicitement comme
        addition. Un code ne satisfaisant aucune de ces trois justifications
        est soit une invention, soit un vestige : il n'a pas sa place au
        catalogue.
        """
        assert len(verdicts.CODES_M2_LIST) > 0, (
            "Le catalogue M2 lu est vide : la recherche d'orphelins serait "
            "vacuellement vraie et le test ne prouverait rien"
        )
        cites = self._identifiants_cites_dans_le_cadrage()
        emis, nombre_fichiers = self._identifiants_emis_par_les_sources()
        assert nombre_fichiers > 0, (
            "Aucun fichier source .py lu : la justification par émission "
            "reposerait sur une lecture vide et le test ne prouverait rien"
        )
        orphelins = sorted(
            code
            for code in verdicts.CODES_M2_LIST
            if code not in cites
            and code not in emis
            and code not in self.ADDITIONS_DECLAREES
        )
        assert orphelins == [], (
            "Codes du catalogue ni cités dans le cadrage, ni émis par les "
            f"sources, ni déclarés comme additions : {orphelins}"
        )
    def test_aucune_addition_declaree_nest_un_vestige(self):
        """
        Garantit que l'échappatoire ADDITIONS_DECLAREES reste auto-nettoyante :
        chaque entrée doit être absente du cadrage, sinon elle est périmée et
        doit être retirée.

        La non-vacuité est assertée parce qu'une échappatoire vide rendrait la
        boucle vacuellement vraie : le test ne prouverait plus rien, et vider
        l'échappatoire devra être une décision explicite, pas un silence. Le
        compteur d'entrées réellement vérifiées, comparé à
        len(ADDITIONS_DECLAREES), sert la même exigence : il prouve que la
        boucle a effectivement parcouru chaque membre au lieu de s'arrêter
        prématurément ou de ne jamais itérer.
        """
        assert self.ADDITIONS_DECLAREES, (
            "ADDITIONS_DECLAREES est vide : le test deviendrait vacuellement "
            "vrai ; vider l'échappatoire doit être une décision explicite, "
            "pas un silence."
        )
        cites = self._identifiants_cites_dans_le_cadrage()
        perimees = []
        entrees_verifiees = 0
        for code in sorted(self.ADDITIONS_DECLAREES):
            entrees_verifiees += 1
            if code in cites:
                perimees.append(code)
        assert entrees_verifiees == len(self.ADDITIONS_DECLAREES), (
            f"Seules {entrees_verifiees} entrées vérifiées sur "
            f"{len(self.ADDITIONS_DECLAREES)} déclarées : la boucle n'a pas "
            "parcouru toute l'échappatoire."
        )
        assert not perimees, (
            f"Entrées périmées dans ADDITIONS_DECLAREES : {perimees} — "
            "elles sont désormais couvertes par le cadrage et doivent être "
            "retirées de l'échappatoire."
        )

    def test_tout_code_emis_par_les_sources_est_au_catalogue(self):
        """
        Troisième axe de la garde de cohérence : tout identifiant REJ- émis
        par les sources du module doit figurer au catalogue, sans quoi un
        appelant validant un verdict authentique contre est_verdict le
        rejetterait à tort.
        """
        src = Path(__file__).resolve().parents[1] / "src"
        codes_emis, nombre_fichiers = self._identifiants_emis_par_les_sources()
        assert nombre_fichiers > 0, (
            f"Aucun fichier source .py lu dans {src} : la garde ne peut pas passer à vide"
        )
        assert len(codes_emis) > 0, (
            f"Aucun identifiant REJ- extrait des {nombre_fichiers} sources de {src}"
        )
        absents = sorted(code for code in codes_emis if not verdicts.est_verdict(code))
        assert not absents, (
            f"Codes émis par les sources de {src} mais absents du catalogue M2 : {absents}"
        )
    def test_construire_verdict_leve_une_exception_dediee(self):
        """
        Un code inconnu doit lever CodeVerdictInconnu, et le message doit
        nommer le code fautif pour rendre le diagnostic immédiat.
        """
        code_inconnu = "REJ-CE-CODE-N-EXISTE-PAS"
        assert not verdicts.est_verdict(code_inconnu), (
            f"Le code de test {code_inconnu!r} ne doit pas exister dans le "
            f"catalogue, sinon ce test ne prouve plus rien."
        )
        with pytest.raises(verdicts.CodeVerdictInconnu) as capture:
            verdicts.construire_verdict(code_inconnu)
        assert code_inconnu in str(capture.value), (
            f"Le message de CodeVerdictInconnu doit contenir le code fautif "
            f"{code_inconnu!r}, obtenu : {capture.value!s}."
        )

    def test_exception_dediee_reste_attrapable_comme_exception(self):
        """
        CodeVerdictInconnu doit hériter d'Exception : les tests existants
        attrapent Exception et doivent rester verts.
        """
        assert issubclass(verdicts.CodeVerdictInconnu, Exception), (
            "CodeVerdictInconnu doit être une sous-classe d'Exception pour "
            "rester attrapable par les tests existants qui font "
            "pytest.raises(Exception)."
        )
