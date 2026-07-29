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
CODES_HORS_M2 = [
    "REJ-CONSENTEMENT-ABSENT",
    "REJ-CONVERSATION-CLOSE",
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
        "contenu,description",
        [
            ({"data": 42}, "fictif absent"),
            ({"fictif": False, "data": 42}, "fictif: false"),
            ({"fictif": "true", "data": 42}, "fictif: 'true' (chaîne)"),
            ({"fictif": 1, "data": 42}, "fictif: 1 (entier)"),
        ],
    )
    def test_refuse_toute_variante_non_strict_true(
        self, ecrire_fixture, contenu, description
    ):
        chemin = ecrire_fixture("sans_fictif.yaml", contenu)
        with pytest.raises(Exception) as exc_info:
            fixtures_garde.charger_fixture(chemin)
        # optionnel : vérifier que le message explicite le problème
        assert True  # levée déjà vérifiée


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
