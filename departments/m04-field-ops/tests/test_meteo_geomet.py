"""PLAN T4.13 : l'adaptateur MSC GeoMet du port `FournisseurMeteo`, SANS réseau (sockets bloqués, transport fictif).

Les réponses sont FICTIVES (`fictif: true`) mais ont la forme d'une réponse réelle de la collection
`citypageweather-realtime`
lue le 2026-09-29 (`lastUpdated`, `hourlyForecastGroup.hourlyForecasts[].timestamp/temperature/wind/lop/condition`,
`geometry.coordinates`). Licence ECCC v2.1.1 : usage commercial permis, attribution obligatoire.
"""

from __future__ import annotations

import json

import pytest
from m4_field_ops import meteo, meteo_geomet, meteo_http

FICTIF = True
LIEU = {"latitude_microdegres": 45_800_000, "longitude_microdegres": -73_400_000}
FUSEAU = "America/Toronto"
DERNIERE_MAJ = "2026-10-05T06:02:44Z"


@pytest.fixture(autouse=True)
def _sans_reseau(sockets_bloques):
    """Ce module n'ouvre jamais un socket."""


def _heure(utc_h, temperature=11, vitesse=10, lop=0, condition="Mainly cloudy", jour="2026-10-05"):
    return {
        "condition": {"en": condition, "fr": "condition fictive"},
        "temperature": {"units": {"en": "C"}, "value": {"en": temperature, "fr": temperature}},
        "lop": {"units": {"en": "%"}, "value": {"en": lop, "fr": lop}},
        "timestamp": f"{jour}T{utc_h:02d}:00:00Z",
        "wind": {"speed": {"units": {"en": "km/h"}, "value": {"en": vitesse, "fr": vitesse}}},
    }


def _localite(identifiant="qc-156", nom="Ville Fictive", coordonnees=(-73.43, 45.81), heures=None, maj=DERNIERE_MAJ):
    propres = {
        "identifier": identifiant,
        "name": {"en": nom, "fr": nom},
        "lastUpdated": maj,
        "warnings": [],
        "hourlyForecastGroup": {"hourlyForecasts": heures},
    }
    if maj is None:
        del propres["lastUpdated"]
    return {
        "type": "Feature",
        "id": identifiant,
        "properties": propres,
        "geometry": {"type": "Point", "coordinates": list(coordonnees)},
    }


def _reponse(*localites):
    corps = {"fictif": True, "type": "FeatureCollection", "features": list(localites), "numberMatched": len(localites)}
    return json.dumps(corps).encode("utf-8")


def _heures_du_jour(**valeurs):
    """Une journée : 04:00 UTC (00:00 locale, EDT) à 03:00 UTC le lendemain."""
    return [_heure(h, **valeurs) for h in range(4, 24)] + [_heure(h, jour="2026-10-06", **valeurs) for h in range(0, 4)]


def _transport(corps, entetes=None):
    appels = []

    def transport(url, delai):
        appels.append((url, delai))
        return corps, entetes or {}

    transport.appels = appels
    return transport


def _fournisseur(corps, **kwargs):
    fournisseur, verdict = meteo_geomet.creer_fournisseur_geomet(FUSEAU, transport=_transport(corps), **kwargs)
    assert verdict is None, verdict
    return fournisseur


def _prevoir(corps, lieu=LIEU):
    fournisseur = _fournisseur(corps)
    return fournisseur.previsions(lieu, "2026-10-05", "2026-10-05"), fournisseur._transport


class TestCreation:
    def test_un_fournisseur_valide_est_du_port_et_aucune_connexion_n_est_ouverte(self):
        fournisseur, verdict = meteo_geomet.creer_fournisseur_geomet(FUSEAU)
        assert verdict is None and isinstance(fournisseur, meteo.FournisseurMeteo)

    def test_le_descripteur_porte_la_licence_et_l_attribution_exigee(self):
        descripteur = _fournisseur(_reponse()).descripteur()
        assert descripteur == {
            "fournisseur": "msc_geomet",
            "api": "citypageweather-realtime",
            "licence": "https://eccc-msc.github.io/open-data/licence/readme_en/",
            "version_licence": "2.1.1",
            "attribution": "Contains information licenced under the Data Server End-use Licence of Environment and "
            "Climate Change Canada.",
        }
        assert all(isinstance(v, str) and v for v in descripteur.values())

    @pytest.mark.parametrize(
        ("fuseau", "delai"),
        [("Nulle/Part", 5), ("", 5), (None, 5), (FUSEAU, 0), (FUSEAU, 31), (FUSEAU, 2.5), (FUSEAU, True)],
    )
    def test_un_fuseau_inconnu_ou_un_delai_hors_bornes_est_refuse(self, fuseau, delai):
        fournisseur, verdict = meteo_geomet.creer_fournisseur_geomet(fuseau, delai)
        assert fournisseur is None and verdict["code"] == "REJ-CONTRAT-INVALIDE" and "MSC GeoMet" in verdict["detail"]


class TestRequete:
    def test_l_url_ne_porte_que_le_lieu_generalise_et_une_marge_de_deux_dixiemes(self):
        _, transport = _prevoir(_reponse(_localite(heures=_heures_du_jour())))
        ((url, delai),) = transport.appels
        assert url == (
            "https://api.weather.gc.ca/collections/citypageweather-realtime/items?f=json&lang=en&limit=20"
            "&bbox=-73.600000,45.600000,-73.200000,46.000000"
        )
        assert delai == 5 and url.startswith("https://" + meteo_http.HOTE_MSC_GEOMET + "/")

    def test_un_lieu_plus_precis_que_le_dixieme_de_degre_est_refuse_sans_aucune_requete(self):
        fournisseur = _fournisseur(_reponse())
        precis = {"latitude_microdegres": 45_741_500, "longitude_microdegres": -73_450_500}
        previsions, verdict = fournisseur.previsions(precis, "2026-10-05", "2026-10-05")
        assert previsions is None and verdict["code"] == meteo.CODE_LIEU_TROP_PRECIS
        assert fournisseur._transport.appels == []

    def test_aucune_coordonnee_fine_n_est_dans_l_url(self):
        precis = meteo.lieu_generalise(45_741_500, -73_450_500)
        _, transport = _prevoir(_reponse(_localite(heures=_heures_du_jour())), lieu=precis)
        url = transport.appels[0][0]
        assert url.endswith("&bbox=-73.700000,45.500000,-73.300000,45.900000")
        assert "45.741500" not in url and "73.450500" not in url

    def test_le_delai_choisi_est_transmis_au_transport(self):
        transport = _transport(_reponse(_localite(heures=_heures_du_jour())))
        fournisseur, _ = meteo_geomet.creer_fournisseur_geomet(FUSEAU, 12, transport)
        fournisseur.previsions(LIEU, "2026-10-05", "2026-10-05")
        assert transport.appels[0][1] == 12


class TestLecture:
    def test_les_heures_utc_deviennent_les_heures_locales_du_chantier(self):
        (previsions, verdict), _ = _prevoir(_reponse(_localite(heures=_heures_du_jour())))
        assert verdict is None and meteo.valider_previsions(previsions) is None
        premiers = [p["heure"] for p in previsions["points"][:3]]
        assert premiers == ["2026-10-05T00:00:00-04:00", "2026-10-05T01:00:00-04:00", "2026-10-05T02:00:00-04:00"]
        assert previsions["points"][-1]["heure"] == "2026-10-05T23:00:00-04:00"

    def test_le_retour_a_l_heure_normale_est_pris_en_compte_et_l_heure_repetee_n_est_gardee_qu_une_fois(self):
        # Le 1er novembre 2026, à 02:00 locales (06:00 UTC), l'heure recule : 01:00 locale existe DEUX fois.
        heures = [_heure(h, jour="2026-11-01") for h in range(4, 10)]  # 04:00Z à 09:00Z
        (previsions, verdict), _ = _prevoir(_reponse(_localite(heures=heures)))
        assert verdict is None and meteo.valider_previsions(previsions) is None
        assert [p["heure"] for p in previsions["points"]] == [
            "2026-11-01T00:00:00-04:00",
            "2026-11-01T01:00:00-04:00",  # 05:00Z : la première 01:00
            "2026-11-01T02:00:00-05:00",
            "2026-11-01T03:00:00-05:00",
            "2026-11-01T04:00:00-05:00",
        ]

    def test_temperature_vent_et_probabilite_sont_lus_les_rafales_et_les_quantites_restent_inconnues(self):
        heures = [_heure(16, temperature=-2, vitesse=45, lop=60)]
        (previsions, _), _ = _prevoir(_reponse(_localite(heures=heures)))
        (point,) = previsions["points"]
        assert point == {
            "heure": "2026-10-05T12:00:00-04:00",
            "temperature_c": -2,
            "vent_kmh": 45,
            "rafales_kmh": None,
            "precipitation_mm_h": None,
            "probabilite_precipitation_pct": 60,
            "verglas": None,
        }

    @pytest.mark.parametrize(
        ("condition", "verglas"),
        [
            ("Freezing rain", True),
            ("Light freezing rain", True),
            ("Ice pellets", True),
            ("FREEZING DRIZZLE", True),
            ("Sunny", None),
            ("Light rain", None),
            ("Snow", None),
            ("", None),
            (None, None),
            (42, None),
        ],
    )
    def test_le_verglas_n_est_vrai_que_si_le_texte_le_dit_jamais_faux(self, condition, verglas):
        heure = _heure(16)
        heure["condition"] = {"en": condition}
        (previsions, _), _ = _prevoir(_reponse(_localite(heures=[heure])))
        assert previsions["points"][0]["verglas"] is verglas

    def test_une_mesure_illisible_reste_inconnue_jamais_zero(self):
        heure = _heure(16)
        heure["temperature"]["value"]["en"] = "M"
        heure["wind"]["speed"]["value"]["en"] = True
        del heure["lop"]
        (previsions, _), _ = _prevoir(_reponse(_localite(heures=[heure])))
        point = previsions["points"][0]
        assert point["temperature_c"] is None and point["vent_kmh"] is None
        assert point["probabilite_precipitation_pct"] is None

    def test_un_horodatage_illisible_ecarte_le_point_seulement(self):
        heures = [
            _heure(16),
            {**_heure(17), "timestamp": "bientôt"},
            {**_heure(18), "timestamp": "2026-10-05T22:00:00"},
            {**_heure(19), "timestamp": None},
        ]
        (previsions, _), _ = _prevoir(_reponse(_localite(heures=heures)))
        assert [p["heure"][11:13] for p in previsions["points"]] == ["12"]

    def test_la_citation_dit_la_source_l_heure_de_mise_a_jour_la_licence_et_l_attribution(self):
        (previsions, _), _ = _prevoir(_reponse(_localite(heures=_heures_du_jour())))
        assert previsions["citation"] == {
            "source": "msc_geomet",
            "emise_le": DERNIERE_MAJ,
            "heure_type": "mise_a_jour_du_fournisseur",
            "attribution": "Contains information licenced under the Data Server End-use Licence of Environment and "
            "Climate Change Canada.",
            "licence": "https://eccc-msc.github.io/open-data/licence/readme_en/",
            "collection": "citypageweather-realtime",
            "page_meteo": "qc-156 (Ville Fictive)",
        }

    def test_la_localite_la_plus_proche_qui_a_une_prevision_horaire_est_choisie(self):
        proche_sans_heures = _localite("qc-001", "Sans Heures", (-73.40, 45.80), heures=[])
        proche = _localite("qc-002", "Proche", (-73.41, 45.81), heures=[_heure(16, temperature=7)])
        loin = _localite("qc-003", "Loin", (-73.20, 45.60), heures=[_heure(16, temperature=99)])
        (previsions, _), _ = _prevoir(_reponse(loin, proche_sans_heures, proche))
        assert previsions["points"][0]["temperature_c"] == 7
        assert previsions["citation"]["page_meteo"] == "qc-002 (Proche)"

    def test_a_distance_egale_l_identifiant_le_plus_petit_l_emporte(self):
        a = _localite("qc-020", "B", (-73.41, 45.81), heures=[_heure(16, temperature=1)])
        b = _localite("qc-010", "A", (-73.41, 45.81), heures=[_heure(16, temperature=2)])
        (previsions, _), _ = _prevoir(_reponse(a, b))
        assert previsions["citation"]["page_meteo"].startswith("qc-010")

    def test_la_longitude_pese_moins_que_la_latitude_dans_le_choix(self):
        # 0,10 degré de longitude (pesé 0,7) est plus près que 0,08 degré de latitude ? non : 0,07 contre 0,08
        est = _localite("qc-100", "Est", (-73.30, 45.80), heures=[_heure(16, temperature=1)])  # 0,10 en longitude
        nord = _localite("qc-200", "Nord", (-73.40, 45.88), heures=[_heure(16, temperature=2)])  # 0,08 en latitude
        (previsions, _), _ = _prevoir(_reponse(est, nord))
        assert previsions["citation"]["page_meteo"].startswith("qc-100")

    def test_un_message_du_fournisseur_ne_change_pas_le_lieu_demande(self):
        (previsions, _), _ = _prevoir(_reponse(_localite(heures=_heures_du_jour())))
        assert "45.8" not in json.dumps(previsions) and "-73.4" not in json.dumps(previsions)

    def test_la_prevision_horaire_sert_a_juger_un_creneau_mais_ne_dit_jamais_ok_sans_rafales_ni_quantites(self):
        heures = [_heure(h, vitesse=10, temperature=12) for h in range(12, 22)]  # 08:00 à 17:00 locales
        (previsions, _), _ = _prevoir(_reponse(_localite(heures=heures)))
        regles = {
            "seuils": {
                "vent_kmh": {"blocage": 40},
                "rafales_kmh": {"blocage": 60},
                "pluie_mm_h": {"blocage": 3},
                "gel_c": {"blocage": 0},
                "verglas": {"blocage": True},
            },
            "sans_objet": ["chaleur"],
        }
        resultat = meteo.evaluer_creneau(regles, previsions, "2026-10-05", 480, 1020)
        par_mesure = {r["mesure"]: r["statut"] for r in resultat["regles"]}
        assert par_mesure == {
            "vent_kmh": "ok",
            "rafales_kmh": "inconnu",
            "pluie_mm_h": "inconnu",
            "gel_c": "ok",
            "verglas": "inconnu",
        }
        assert resultat["statut"] == meteo.STATUT_INCONNU, "MSC seul ne dit jamais ok pour ces mesures"

    def test_un_vent_fort_bloque_meme_si_le_reste_est_inconnu(self):
        heures = [_heure(h, vitesse=55) for h in range(12, 22)]
        (previsions, _), _ = _prevoir(_reponse(_localite(heures=heures)))
        regles = {
            "seuils": {"vent_kmh": {"validation": 30, "blocage": 40}, "rafales_kmh": {"blocage": 60}},
            "sans_objet": ["pluie", "gel", "verglas", "chaleur"],
        }
        assert meteo.evaluer_creneau(regles, previsions, "2026-10-05", 480, 1020)["statut"] == meteo.STATUT_BLOQUANT


class TestPannes:
    @pytest.mark.parametrize(
        ("corps", "morceau"),
        [
            (b"pas du json", "JSON invalide"),
            (json.dumps({"fictif": True}).encode(), "features : une liste est attendue"),
            (json.dumps({"fictif": True, "features": "x"}).encode(), "features : une liste est attendue"),
            (json.dumps({"fictif": True, "features": []}).encode(), "aucune page météo"),
            (_reponse(_localite(heures=[])), "aucune page météo"),
            (_reponse(_localite(heures=None)), "aucune page météo"),
            (_reponse({"type": "Feature"}), "aucune page météo"),
            (_reponse(_localite(heures=[_heure(16)], maj=None)), "lastUpdated"),
            (_reponse(_localite(heures=[_heure(16)], maj="  ")), "lastUpdated"),
            (_reponse(_localite(heures=[{"timestamp": "bientôt"}])), "aucun point horaire lisible"),
            (_reponse(_localite(coordonnees=("x", "y"), heures=[_heure(16)])), "aucune page météo"),
        ],
    )
    def test_une_reponse_inutilisable_est_un_verdict_reponse_invalide_jamais_un_ok(self, corps, morceau):
        (previsions, verdict), _ = _prevoir(corps)
        assert previsions is None and verdict["code"] == meteo.CODE_REPONSE_INVALIDE
        assert morceau in verdict["detail"] and "MSC GeoMet" in verdict["detail"]

    def test_un_liste_racine_ou_un_tableau_n_est_pas_une_reponse(self):
        for corps in (b"[]", b"42", b"null", b'"texte"'):
            (previsions, verdict), _ = _prevoir(corps)
            assert previsions is None and verdict["code"] == meteo.CODE_REPONSE_INVALIDE

    def test_une_panne_du_transport_est_un_verdict_indisponible(self):
        def en_panne(url, delai):
            raise TimeoutError

        fournisseur, _ = meteo_geomet.creer_fournisseur_geomet(FUSEAU, transport=en_panne)
        previsions, verdict = fournisseur.previsions(LIEU, "2026-10-05", "2026-10-05")
        assert previsions is None and verdict["code"] == meteo.CODE_FOURNISSEUR_INDISPONIBLE
        assert "délai dépassé" in verdict["detail"]

    def test_sans_transport_fourni_le_vrai_reseau_bloque_donne_une_erreur_de_test_pas_un_ok(self):
        fournisseur, _ = meteo_geomet.creer_fournisseur_geomet(FUSEAU)
        with pytest.raises(AssertionError, match="accès réseau interdit"):
            fournisseur.previsions(LIEU, "2026-10-05", "2026-10-05")


def test_le_module_ne_reproduit_aucun_avertissement_meteo():
    """La licence ECCC n'autorise à reproduire une alerte que sans en altérer le contenu : ce module ne lit pas
    `warnings`."""
    import ast
    from pathlib import Path

    arbre = ast.parse(Path(meteo_geomet.__file__).read_text(encoding="utf-8"))
    lus = {n.value for n in ast.walk(arbre) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "warnings" not in lus and "warning" not in lus
