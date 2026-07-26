import sys, hashlib
from pathlib import Path
import pytest
import yaml

_M7 = Path(__file__).resolve().parents[2]
for p in (str(_M7 / "src" / "utm"), str(_M7 / "src" / "content"), str(_M7 / "src" / "workflows")):
    if p not in sys.path:
        sys.path.insert(0, p)
import utm_engine  # noqa: E402

CONTRAT = _M7 / "contracts" / "utm-convention.v1.yaml"

SHA256_UTM_V1 = "ed51e8d81f7979e3f326c1ac10b8c524494b0d5c8a9d9580473e6fd1e6e2be4c"  # GEL 2026-07-26 (D-015)


def _lien_valide():
    return utm_engine.generer_lien_utm(
        "https://opsys-ai.ca/services", "google", "organique", "fenetre-ete-2026"
    )


def _valider(url):
    return utm_engine.valider_lien_utm(url)


def _est_valide(verdicts):
    return not any(v[1] == "fail" for v in verdicts)


# --- Contrat ---
class TestContrat:
    def test_contrat_present(self):
        assert CONTRAT.is_file(), f"Contrat absent : {CONTRAT}"

    def test_contrat_sha256_epingle(self):
        data = CONTRAT.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        assert digest == SHA256_UTM_V1, (
            f"Contrat modifié ! SHA256 attendu={SHA256_UTM_V1}, "
            f"obtenu={digest}. Mettez à jour la constante après revue explicite."
        )

    def test_contrat_structure(self):
        c = yaml.safe_load(CONTRAT.read_text(encoding="utf-8"))
        assert isinstance(c, dict), "Contrat racine dict attendu"
        enums = c.get("enums", {})
        sources = enums.get("utm_source", [])
        mediums = enums.get("utm_medium", [])
        assert len(sources) > 0, "utm_source enum vide"
        assert len(mediums) > 0, "utm_medium enum vide"
        for s in sources:
            assert s == s.lower(), f"utm_source non minuscule: {s}"
            assert all(ord(ch) < 128 for ch in s), f"utm_source accentué: {s}"
        for m in mediums:
            assert m == m.lower(), f"utm_medium non minuscule: {m}"
            assert all(ord(ch) < 128 for ch in m), f"utm_medium accentué: {m}"


# --- Règles U-01..U-12 ---
class TestReglesU:
    # U-01
    def test_u01_positif_https(self):
        verdicts = _valider(_lien_valide())
        assert any(v[0] == "U-01" and v[1] == "ok" for v in verdicts)

    def test_u01_negatif_http_nu(self):
        lien = _lien_valide().replace("https://", "http://")
        verdicts = _valider(lien)
        assert any(v[0] == "U-01" and v[1] == "fail" for v in verdicts)

    # U-02
    def test_u02_positif_source_valide(self):
        verdicts = _valider(_lien_valide())
        assert any(v[0] == "U-02" and v[1] == "ok" for v in verdicts)

    def test_u02_negatif_source_invalide(self):
        lien = _lien_valide().replace("utm_source=google", "utm_source=gogle")
        verdicts = _valider(lien)
        assert any(v[0] == "U-02" and v[1] == "fail" for v in verdicts)

    def test_u02_negatif_source_absente(self):
        lien = "https://opsys-ai.ca/services?utm_medium=organique&utm_campaign=fenetre-ete-2026"
        verdicts = _valider(lien)
        assert any(v[0] == "U-02" and v[1] == "fail" for v in verdicts)

    # U-03
    def test_u03_positif_medium_valide(self):
        verdicts = _valider(_lien_valide())
        assert any(v[0] == "U-03" and v[1] == "ok" for v in verdicts)

    def test_u03_negatif_medium_invalide(self):
        lien = _lien_valide().replace("utm_medium=organique", "utm_medium=email")
        verdicts = _valider(lien)
        assert any(v[0] == "U-03" and v[1] == "fail" for v in verdicts)

    def test_u03_negatif_medium_absent(self):
        lien = "https://opsys-ai.ca/services?utm_source=google&utm_campaign=fenetre-ete-2026"
        verdicts = _valider(lien)
        assert any(v[0] == "U-03" and v[1] == "fail" for v in verdicts)

    # U-04
    def test_u04_positif_campaign_format(self):
        verdicts = _valider(_lien_valide())
        assert any(v[0] == "U-04" and v[1] == "ok" for v in verdicts)

    def test_u04_negatif_campaign_mauvais_format(self):
        lien = _lien_valide().replace("utm_campaign=fenetre-ete-2026", "utm_campaign=Ete2026")
        verdicts = _valider(lien)
        assert any(v[0] == "U-04" and v[1] == "fail" for v in verdicts)

    def test_u04_negatif_campaign_origine_invalide(self):
        lien = _lien_valide().replace("utm_campaign=fenetre-ete-2026", "utm_campaign=inconnu-ete-2026")
        verdicts = _valider(lien)
        assert any(v[0] == "U-04" and v[1] == "fail" for v in verdicts)

    # U-05
    def test_u05_positif_longueur_ok(self):
        verdicts = _valider(_lien_valide())
        assert any(v[0] == "U-05" and v[1] == "ok" for v in verdicts)

    def test_u05_negatif_campaign_trop_long(self):
        slug_long = "a" * 101
        campagne_longue = f"fenetre-{slug_long}-2026"
        lien = utm_engine.generer_lien_utm(
            "https://opsys-ai.ca/services", "google", "organique", campagne_longue
        )
        verdicts = _valider(lien)
        assert any(v[0] == "U-05" and v[1] == "fail" for v in verdicts)

    # U-06
    def test_u06_positif_encodage_correct(self):
        verdicts = _valider(_lien_valide())
        assert any(v[0] == "U-06" and v[1] == "ok" for v in verdicts)

    def test_u06_negatif_encodage_casse(self):
        lien = _lien_valide() + "%zz"
        verdicts = _valider(lien)
        assert any(v[0] == "U-06" and v[1] == "fail" for v in verdicts)

    # U-07
    def test_u07_positif_caracteres_autorises(self):
        verdicts = _valider(_lien_valide())
        assert any(v[0] == "U-07" and v[1] == "ok" for v in verdicts)

    def test_u07_negatif_caractere_interdit(self):
        lien = _lien_valide() + "&utm_content=cr%E9"  # é encodé, OK.  On va plutôt injecter non encodé
        # On manipule l'URL pour avoir un é non encodé dans une valeur
        lien2 = _lien_valide().replace("utm_campaign=fenetre-ete-2026", "utm_campaign=fenetre-été-2026")
        verdicts = _valider(lien2)
        assert any(v[0] == "U-07" and v[1] == "fail" for v in verdicts)

    # U-08
    def test_u08_positif_ordre_canonique(self):
        verdicts = _valider(_lien_valide())
        assert any(v[0] == "U-08" and v[1] == "ok" for v in verdicts)

    def test_u08_negatif_ordre_inverse_warn(self):
        lien = "https://opsys-ai.ca/services?utm_medium=organique&utm_source=google&utm_campaign=fenetre-ete-2026"
        verdicts = _valider(lien)
        regle = next((v for v in verdicts if v[0] == "U-08"), None)
        assert regle is not None
        assert regle[1] == "warn", f"U-08 devrait être warn, obtenu {regle[1]}"

    # U-09
    def test_u09_positif_content_optionnel_valide(self):
        lien = _lien_valide() + "&utm_content=variante-a"
        verdicts = _valider(lien)
        assert any(v[0] == "U-09" and v[1] == "ok" for v in verdicts)

    def test_u09_negatif_content_trop_long(self):
        contenu = "x" * 81
        lien = _lien_valide() + f"&utm_content={contenu}"
        verdicts = _valider(lien)
        assert any(v[0] == "U-09" and v[1] == "fail" for v in verdicts)

    def test_u09_negatif_content_caractere_interdit(self):
        lien = _lien_valide() + "&utm_content=var%20#b"
        verdicts = _valider(lien)
        assert any(v[0] == "U-09" and v[1] == "fail" for v in verdicts)

    # U-10
    def test_u10_positif_pas_de_duplication(self):
        verdicts = _valider(_lien_valide())
        assert any(v[0] == "U-10" and v[1] == "ok" for v in verdicts)

    def test_u10_negatif_source_duplique(self):
        lien = _lien_valide() + "&utm_source=facebook"
        verdicts = _valider(lien)
        assert any(v[0] == "U-10" and v[1] == "fail" for v in verdicts)

    # U-11
    def test_u11_positif_annee_dans_intervalle(self):
        verdicts = _valider(_lien_valide())
        assert any(v[0] == "U-11" and v[1] == "ok" for v in verdicts)

    def test_u11_negatif_annee_avant_2020(self):
        lien = _lien_valide().replace("fenetre-ete-2026", "fenetre-ete-2019")
        verdicts = _valider(lien)
        assert any(v[0] == "U-11" and v[1] == "fail" for v in verdicts)

    def test_u11_negatif_annee_apres_2099(self):
        lien = _lien_valide().replace("fenetre-ete-2026", "fenetre-ete-2100")
        verdicts = _valider(lien)
        assert any(v[0] == "U-11" and v[1] == "fail" for v in verdicts)

    # U-12
    def test_u12_positif_slug_non_vide(self):
        verdicts = _valider(_lien_valide())
        assert any(v[0] == "U-12" and v[1] == "ok" for v in verdicts)

    def test_u12_negatif_slug_vide(self):
        lien = _lien_valide().replace("fenetre-ete-2026", "fenetre--2026")
        verdicts = _valider(lien)
        assert any(v[0] == "U-12" and v[1] == "fail" for v in verdicts)


class TestFailClosed:
    def test_lien_valide_aucun_fail(self):
        verdicts = _valider(_lien_valide())
        assert _est_valide(verdicts), f"Le lien valide a des fails : {verdicts}"

    def test_http_nu_est_invalide(self):
        lien = _lien_valide().replace("https://", "http://")
        verdicts = _valider(lien)
        assert not _est_valide(verdicts), "HTTP nu devrait être invalide"

    def test_source_absente_est_invalide(self):
        lien = "https://opsys-ai.ca/services?utm_medium=organique&utm_campaign=fenetre-ete-2026"
        verdicts = _valider(lien)
        assert not _est_valide(verdicts)

    def test_medium_invalide_est_invalide(self):
        lien = _lien_valide().replace("utm_medium=organique", "utm_medium=email")
        verdicts = _valider(lien)
        assert not _est_valide(verdicts)

    def test_campaign_malformee_est_invalide(self):
        lien = _lien_valide().replace("utm_campaign=fenetre-ete-2026", "utm_campaign=Ete2026")
        verdicts = _valider(lien)
        assert not _est_valide(verdicts)
