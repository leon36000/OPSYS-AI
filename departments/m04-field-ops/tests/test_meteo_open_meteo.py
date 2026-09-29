"""PLAN T4.13 : l'adaptateur Open-Meteo du port `FournisseurMeteo`, SANS réseau (sockets bloqués, transport fictif).

Open-Meteo est FERMÉ tant que le propriétaire n'a pas décidé d'un forfait commercial (GATE NATHAN) : l'API gratuite est
réservée à un usage non commercial (conditions lues le 2026-09-29). Les réponses sont FICTIVES (`fictif: true`) mais ont
la forme de la documentation (`hourly.time` locale, un tableau par variable, `utc_offset_seconds`, en-tête `Date`).
"""

from __future__ import annotations

import json
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from m4_field_ops import meteo, meteo_http, meteo_open_meteo

FICTIF = True
LIEU = {"latitude_microdegres": 45_800_000, "longitude_microdegres": -73_400_000}
FUSEAU = "America/Toronto"
CLE = "CLE-COMMERCIALE-FICTIVE-0123456789"
ENTETES = {"Date": "Mon, 05 Oct 2026 12:00:00 GMT", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def _sans_reseau(sockets_bloques):
    """Ce module n'ouvre jamais un socket."""


def _horaire(heures=range(24), jour="2026-10-05", **tableaux):
    temps = [f"{jour}T{h:02d}:00" for h in heures]
    n = len(temps)
    base = {
        "temperature_2m": [12.5] * n,
        "precipitation": [0.0] * n,
        "precipitation_probability": [10] * n,
        "wind_speed_10m": [11.2] * n,
        "wind_gusts_10m": [22.4] * n,
        "weather_code": [3] * n,
    }
    base.update(tableaux)
    return {"time": temps, **base}


def _reponse(horaire=None, decalage=-14400, **extra):
    corps = {
        "fictif": True,
        "latitude": 45.8,
        "longitude": -73.4,
        "utc_offset_seconds": decalage,
        "timezone": FUSEAU,
        "hourly": _horaire() if horaire is None else horaire,
        **extra,
    }
    return json.dumps(corps).encode("utf-8")


def _transport(corps, entetes=ENTETES):
    appels = []

    def transport(url, delai):
        appels.append((url, delai))
        return corps, entetes

    transport.appels = appels
    return transport


def _fournisseur(corps=None, entetes=ENTETES, **kwargs):
    transport = _transport(_reponse() if corps is None else corps, entetes)
    fournisseur, verdict = meteo_open_meteo.creer_fournisseur_open_meteo(
        kwargs.pop("forfait", "commercial"),
        kwargs.pop("cle", CLE),
        kwargs.pop("fuseau", FUSEAU),
        transport=transport,
        **kwargs,
    )
    assert verdict is None, verdict
    return fournisseur, transport


def _prevoir(corps=None, entetes=ENTETES, lieu=LIEU, debut="2026-10-05", fin="2026-10-05"):
    fournisseur, transport = _fournisseur(corps, entetes)
    return fournisseur.previsions(lieu, debut, fin), transport


class TestFermeture:
    """Ouvrir Open-Meteo est une décision du propriétaire : sans forfait commercial ni clé, rien ne s'ouvre."""

    @pytest.mark.parametrize("forfait", ["gratuit", "gratuit_non_commercial", "free", "", None, "Commercial", 1, True])
    def test_tout_forfait_autre_que_commercial_est_refuse_avec_la_raison_de_la_licence(self, forfait):
        fournisseur, verdict = meteo_open_meteo.creer_fournisseur_open_meteo(forfait, CLE, FUSEAU)
        assert fournisseur is None and verdict["code"] == meteo.CODE_FOURNISSEUR_FERME
        assert "usage NON commercial" in verdict["detail"] and "décision du propriétaire" in verdict["detail"]

    @pytest.mark.parametrize("cle", [None, "", "   ", 0, 12345, ["x"]])
    def test_une_cle_absente_est_refusee_sans_en_deviner_une(self, cle):
        fournisseur, verdict = meteo_open_meteo.creer_fournisseur_open_meteo("commercial", cle, FUSEAU)
        assert fournisseur is None and verdict["code"] == meteo.CODE_FOURNISSEUR_FERME
        assert "clé d'API" in verdict["detail"] and "jamais dans le profil ni dans le code" in verdict["detail"]

    @pytest.mark.parametrize(("fuseau", "delai"), [("Nulle/Part", 5), ("", 5), (None, 5), (FUSEAU, 0), (FUSEAU, 99)])
    def test_un_fuseau_inconnu_ou_un_delai_hors_bornes_est_refuse(self, fuseau, delai):
        fournisseur, verdict = meteo_open_meteo.creer_fournisseur_open_meteo("commercial", CLE, fuseau, delai)
        assert fournisseur is None and verdict["code"] == meteo.CODE_FOURNISSEUR_FERME

    def test_un_refus_ne_cite_jamais_la_cle(self):
        _, verdict = meteo_open_meteo.creer_fournisseur_open_meteo("gratuit", CLE, FUSEAU)
        assert CLE not in json.dumps(verdict)

    def test_le_forfait_commercial_avec_une_cle_ouvre_un_fournisseur_du_port(self):
        fournisseur, verdict = meteo_open_meteo.creer_fournisseur_open_meteo("commercial", CLE, FUSEAU)
        assert verdict is None and isinstance(fournisseur, meteo.FournisseurMeteo)

    def test_le_descripteur_porte_la_licence_l_attribution_et_jamais_la_cle(self):
        fournisseur, _ = _fournisseur()
        descripteur = fournisseur.descripteur()
        assert descripteur == {
            "fournisseur": "open_meteo",
            "api": "v1/forecast",
            "forfait": "commercial",
            "licence": "https://open-meteo.com/en/licence",
            "attribution": "Weather data by Open-Meteo.com (https://open-meteo.com/), licence CC BY 4.0",
        }
        assert CLE not in json.dumps(descripteur)

    def test_l_hote_est_l_api_commerciale_jamais_l_api_gratuite(self):
        assert meteo_open_meteo.URL_PREVISIONS == "https://customer-api.open-meteo.com/v1/forecast"
        assert meteo_http.HOTE_OPEN_METEO_COMMERCIAL in meteo_http.HOTES_PERMIS
        assert "api.open-meteo.com" not in meteo_http.HOTES_PERMIS


class TestRequete:
    def test_l_url_porte_le_lieu_generalise_les_variables_le_fuseau_les_dates_et_la_cle(self):
        _, transport = _prevoir(debut="2026-10-05", fin="2026-10-06")
        ((url, delai),) = transport.appels
        morceaux = urlsplit(url)
        assert (morceaux.scheme, morceaux.netloc, morceaux.path) == (
            "https",
            "customer-api.open-meteo.com",
            "/v1/forecast",
        )
        requete = {cle: valeurs[0] for cle, valeurs in parse_qs(morceaux.query).items()}
        assert requete == {
            "latitude": "45.800000",
            "longitude": "-73.400000",
            "hourly": (
                "temperature_2m,precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m,weather_code"
            ),
            "wind_speed_unit": "kmh",
            "temperature_unit": "celsius",
            "precipitation_unit": "mm",
            "timezone": "America/Toronto",
            "start_date": "2026-10-05",
            "end_date": "2026-10-06",
            "apikey": CLE,
        }
        assert delai == 5

    def test_un_lieu_plus_precis_que_le_dixieme_de_degre_est_refuse_sans_aucune_requete(self):
        fournisseur, transport = _fournisseur()
        precis = {"latitude_microdegres": 45_741_500, "longitude_microdegres": -73_450_500}
        previsions, verdict = fournisseur.previsions(precis, "2026-10-05", "2026-10-05")
        assert previsions is None and verdict["code"] == meteo.CODE_LIEU_TROP_PRECIS and transport.appels == []

    @pytest.mark.parametrize(
        ("debut", "fin"),
        [
            ("hier", "2026-10-05"),
            ("2026-10-05", "demain"),
            ("2026-10-06", "2026-10-05"),
            ("2026-02-30", "2026-03-01"),
            (None, "2026-10-05"),
        ],
    )
    def test_des_dates_invalides_sont_refusees_sans_requete(self, debut, fin):
        fournisseur, transport = _fournisseur()
        previsions, verdict = fournisseur.previsions(LIEU, debut, fin)
        assert previsions is None and verdict["code"] == "REJ-CONTRAT-INVALIDE" and transport.appels == []


class TestLecture:
    def test_les_points_sont_a_l_heure_locale_avec_le_decalage_de_la_reponse(self):
        (previsions, verdict), _ = _prevoir()
        assert verdict is None and meteo.valider_previsions(previsions) is None
        assert len(previsions["points"]) == 24
        assert previsions["points"][0]["heure"] == "2026-10-05T00:00:00-04:00"
        assert previsions["points"][23]["heure"] == "2026-10-05T23:00:00-04:00"

    def test_le_decalage_hivernal_s_ecrit_moins_cinq_heures(self):
        (previsions, _), _ = _prevoir(_reponse(_horaire(jour="2026-12-05"), decalage=-18000))
        assert previsions["points"][0]["heure"] == "2026-12-05T00:00:00-05:00"

    @pytest.mark.parametrize(
        ("secondes", "texte"), [(0, "+00:00"), (-14400, "-04:00"), (19800, "+05:30"), (-12600, "-03:30")]
    )
    def test_le_decalage_en_texte_iso(self, secondes, texte):
        assert meteo_open_meteo._decalage(secondes) == texte

    def test_les_valeurs_sont_des_decimaux_exacts_et_les_unites_sont_celles_du_port(self):
        (previsions, _), _ = _prevoir()
        point = previsions["points"][0]
        assert point["temperature_c"] == Decimal("12.5") and isinstance(point["temperature_c"], Decimal)
        assert point["vent_kmh"] == Decimal("11.2") and point["rafales_kmh"] == Decimal("22.4")
        assert point["precipitation_mm_h"] == 0 and point["probabilite_precipitation_pct"] == 10
        assert not any(isinstance(v, float) for v in point.values())

    def test_une_valeur_nulle_de_la_source_reste_inconnue_jamais_zero(self):
        horaire = _horaire(
            heures=range(3), precipitation_probability=[None, 30, None], wind_gusts_10m=[None, None, None]
        )
        (previsions, _), _ = _prevoir(_reponse(horaire))
        assert [p["probabilite_precipitation_pct"] for p in previsions["points"]] == [None, 30, None]
        assert all(p["rafales_kmh"] is None for p in previsions["points"])

    @pytest.mark.parametrize(
        ("code", "verglas"),
        [
            (56, True),
            (57, True),
            (66, True),
            (67, True),
            (0, False),
            (3, False),
            (61, False),
            (71, False),
            (95, False),
            (None, None),
            (Decimal("66.0"), True),
        ],
    )
    def test_les_codes_wmo_de_bruine_ou_pluie_verglacante_donnent_verglas_vrai(self, code, verglas):
        horaire = _horaire(heures=[9])
        horaire["weather_code"] = [None if code is None else int(code)]
        (previsions, _), _ = _prevoir(_reponse(horaire))
        assert previsions["points"][0]["verglas"] is verglas

    def test_la_citation_dit_la_source_l_heure_de_reponse_du_serveur_la_licence_et_l_attribution(self):
        (previsions, _), _ = _prevoir()
        assert previsions["citation"] == {
            "source": "open_meteo",
            "emise_le": "2026-10-05T12:00:00+00:00",
            "heure_type": "reponse_http_du_fournisseur",
            "attribution": "Weather data by Open-Meteo.com (https://open-meteo.com/), licence CC BY 4.0",
            "licence": "https://open-meteo.com/en/licence",
            "forfait": "commercial",
        }
        assert CLE not in json.dumps(previsions["citation"])

    def test_l_en_tete_date_est_lu_sans_tenir_compte_de_la_casse_des_noms(self):
        (previsions, verdict), _ = _prevoir(entetes={"date": "Tue, 06 Oct 2026 01:30:00 GMT"})
        assert verdict is None and previsions["citation"]["emise_le"] == "2026-10-06T01:30:00+00:00"

    def test_un_bulletin_est_juge_par_meteo_un_vent_fort_bloque_un_revetement(self):
        horaire = _horaire(wind_speed_10m=[62] * 24, wind_gusts_10m=[80] * 24)
        (previsions, _), _ = _prevoir(_reponse(horaire))
        regles = {
            "seuils": {
                "vent_kmh": {"validation": 25, "blocage": 40},
                "rafales_kmh": {"blocage": 60},
                "pluie_mm_h": {"blocage": 3},
                "gel_c": {"blocage": 0},
                "verglas": {"blocage": True},
                "chaleur_c": {"blocage": 35},
            },
            "sans_objet": [],
        }
        resultat = meteo.evaluer_creneau(regles, previsions, "2026-10-05", 480, 1020)
        assert resultat["statut"] == meteo.STATUT_BLOQUANT
        assert {r["mesure"]: r["statut"] for r in resultat["regles"]}["pluie_mm_h"] == "ok"

    def test_un_bulletin_calme_complet_est_ok_car_toutes_les_mesures_sont_donnees(self):
        (previsions, _), _ = _prevoir()
        regles = {
            "seuils": {
                "vent_kmh": {"blocage": 40},
                "rafales_kmh": {"blocage": 60},
                "pluie_mm_h": {"blocage": 3},
                "pluie_probabilite_pct": {"blocage": 70},
                "gel_c": {"blocage": 0},
                "verglas": {"blocage": True},
                "chaleur_c": {"blocage": 35},
            }
        }
        assert meteo.evaluer_creneau(regles, previsions, "2026-10-05", 480, 1020)["statut"] == meteo.STATUT_OK


class TestPannes:
    @pytest.mark.parametrize(
        ("corps", "morceau"),
        [
            (b"pas du json", "JSON invalide"),
            (json.dumps({"fictif": True}).encode(), "hourly.time et utc_offset_seconds"),
            (_reponse(horaire={"time": []}), "hourly.time et utc_offset_seconds"),
            (_reponse(horaire="x"), "hourly.time et utc_offset_seconds"),
            (_reponse(decalage="-04:00"), "hourly.time et utc_offset_seconds"),
            (_reponse(decalage=True), "hourly.time et utc_offset_seconds"),
            (
                _reponse(horaire=_horaire(heures=range(3), wind_speed_10m=[1, 2])),
                "hourly.wind_speed_10m : un tableau de 3",
            ),
            (
                _reponse(horaire={k: v for k, v in _horaire(heures=range(3)).items() if k != "weather_code"}),
                "hourly.weather_code : un tableau",
            ),
            (_reponse(horaire=_horaire(heures=range(2), temperature_2m=["12", 13])), "hourly.temperature_2m[0]"),
            (_reponse(horaire=_horaire(heures=range(2), precipitation=[True, 0])), "hourly.precipitation[0]"),
            (_reponse(horaire=_horaire(heures=range(2), weather_code=["3", 3])), "hourly.weather_code[0]"),
            (_reponse(horaire={**_horaire(heures=range(2)), "time": ["2026-10-05T00:00", 7]}), "hourly.time[1]"),
            (
                _reponse(horaire={**_horaire(heures=range(2)), "time": ["2026-10-05", "2026-10-05T01:00"]}),
                "hourly.time[0]",
            ),
        ],
    )
    def test_une_reponse_inutilisable_est_un_verdict_reponse_invalide_jamais_un_ok(self, corps, morceau):
        (previsions, verdict), _ = _prevoir(corps)
        assert previsions is None and verdict["code"] == meteo.CODE_REPONSE_INVALIDE
        assert morceau in verdict["detail"] and "Open-Meteo" in verdict["detail"]
        assert CLE not in json.dumps(verdict)

    def test_une_erreur_du_fournisseur_est_un_verdict_indisponible(self):
        corps = json.dumps({"error": True, "reason": "clé invalide (message du fournisseur)"}).encode()
        (previsions, verdict), _ = _prevoir(corps)
        assert previsions is None and verdict["code"] == meteo.CODE_FOURNISSEUR_INDISPONIBLE
        assert "message du fournisseur" not in verdict["detail"], "le message libre du fournisseur n'est pas recopié"

    @pytest.mark.parametrize(
        "entetes",
        [{}, {"Content-Type": "application/json"}, {"Date": "hier"}, {"Date": ""}, {"Date": None}, {"Date": 12345}],
    )
    def test_sans_heure_de_reponse_lisible_la_prevision_n_est_pas_citable_donc_refusee(self, entetes):
        (previsions, verdict), _ = _prevoir(entetes=entetes)
        assert previsions is None and verdict["code"] == meteo.CODE_REPONSE_INVALIDE
        assert "en-tête Date" in verdict["detail"]

    def test_une_heure_de_reponse_sans_fuseau_est_refusee(self):
        (previsions, verdict), _ = _prevoir(entetes={"Date": "Mon, 05 Oct 2026 12:00:00 -0000"})  # « fuseau inconnu »
        assert previsions is None and verdict["code"] == meteo.CODE_REPONSE_INVALIDE
        assert "en-tête Date" in verdict["detail"]

    def test_une_panne_du_transport_est_un_verdict_indisponible_sans_cle_ni_url(self):
        def en_panne(url, delai):
            raise ConnectionResetError(f"reset sur {url}")

        fournisseur, _ = meteo_open_meteo.creer_fournisseur_open_meteo("commercial", CLE, FUSEAU, transport=en_panne)
        previsions, verdict = fournisseur.previsions(LIEU, "2026-10-05", "2026-10-05")
        assert previsions is None and verdict["code"] == meteo.CODE_FOURNISSEUR_INDISPONIBLE
        texte = json.dumps(verdict)
        assert CLE not in texte and "customer-api" not in texte and "apikey" not in texte

    def test_sans_transport_fourni_le_vrai_reseau_bloque_donne_une_erreur_de_test_pas_un_ok(self):
        fournisseur, _ = meteo_open_meteo.creer_fournisseur_open_meteo("commercial", CLE, FUSEAU)
        with pytest.raises(AssertionError, match="accès réseau interdit"):
            fournisseur.previsions(LIEU, "2026-10-05", "2026-10-05")
