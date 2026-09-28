import inspect
import json
from pathlib import Path

import pytest
import yaml
from m7_marketing.ads import intelligence as ads_intel
from m7_marketing.attribution import attribution_engine
from m7_marketing.roi import roi_engine

# ensure module paths are discoverable
ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"

# ----------------------------------------------------------------------
# helpers – charge les sorties réelles S013 & S014
# ----------------------------------------------------------------------
FIXTURES_DIR = ROOT / "fixtures"
CONTRACTS_DIR = ROOT / "contracts"
CALENDRIER_PATH = ROOT / "data" / "saisons" / "calendrier-quebec.v1.yaml"
MATOMO_PATH = FIXTURES_DIR / "matomo" / "visites.v1.yaml"
CRM_PATH = FIXTURES_DIR / "crm" / "leads.v1.yaml"
MAPPING_PATH = CONTRACTS_DIR / "roi-mapping.v1.yaml"
ADS_FIXTURES_DIR = FIXTURES_DIR / "ads"


def _load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _build_real_attribution():
    """Retourne le dict rapport d'attribution S013 réel."""
    visites, leads = attribution_engine.charger_et_valider_fixtures(
        str(MATOMO_PATH), str(CRM_PATH)
    )
    rapport = attribution_engine.attribuer(visites, leads, fenetre_jours=30)
    return rapport


def _build_real_ads():
    """Retourne le dict rapport S014 réel pour date_reference 2026-07-15."""
    return ads_intel.generate_report(
        str(ADS_FIXTURES_DIR),
        str(CALENDRIER_PATH),
        "2026-07-15"
    )


@pytest.fixture(scope="module")
def rapport_attribution():
    return _build_real_attribution()


@pytest.fixture(scope="module")
def rapport_ads():
    return _build_real_ads()


@pytest.fixture(scope="module")
def mapping():
    return _load_yaml(MAPPING_PATH)


@pytest.fixture(scope="module")
def calendrier():
    return _load_yaml(CALENDRIER_PATH)


DATE_REF = "2026-07-15"


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------
class TestValidateurMapping:
    def test_mapping_valide(self, mapping):
        """Le mapping de production passe la validation sans exception."""
        roi_engine.valider_mapping(mapping)

    def test_mapping_tronque_leve_valueerror(self):
        """Un mapping sans la clé 'mappings' lève ValueError."""
        with pytest.raises(ValueError):
            roi_engine.valider_mapping({"schema_version": 1})


class TestJointureComplete:
    """Cas RED (a) : jointure complète S013↔S014 pour une fenêtre,
    coût par lead numérique exact."""

    def test_jointure_locale_festive(self):
        # Rapports artificiels garantissant une jointure propre. Le canal est "google"
        # (utm_source BRUT, tel que produit réellement par attribution_engine.attribuer),
        # jamais "google_ads" (le nom de la plateforme ads) : utiliser directement le nom de
        # plateforme ici masquerait la jointure canal->plateforme (R9 §1.1) que roi_engine
        # doit désormais faire via CANAL_VERS_PLATEFORME_ADS.
        rapport_attr = {
            "par_canal": [
                {"canal": "google", "leads_derniere_touche": 2}
            ],
            "leads_totaux": 2,
            "leads_non_attribuables": 0
        }
        rapport_ads = {
            "plateformes": [
                {
                    "plateforme": "google_ads",
                    "campagnes": [
                        {
                            "campagne": "camp-jointe",
                            "cout": 100,
                            "fenetre_id": "fw-locale"
                        }
                    ]
                }
            ]
        }
        mapping_local = {
            "mappings": [
                {
                    "fenetre_id": "fw-locale",
                    "utm_campaigns": ["camp-jointe"],
                    "plateforme_ads": "google_ads"
                }
            ]
        }
        calendrier_local = {
            "fenetres": [
                {
                    "fenetre_id": "fw-locale",
                    "mois_debut": 6,
                    "mois_fin": 8
                }
            ]
        }

        result = roi_engine.consolider_roi(
            rapport_attr,
            rapport_ads,
            mapping_local,
            calendrier_local,
            "2026-07-15"
        )

        canaux = result["par_canal"]
        assert len(canaux) == 1
        canal = canaux[0]
        assert canal["canal"] == "google"
        assert canal["leads_derniere_touche"] == 2
        assert canal["cout_ads"] == 100
        assert canal["cout_par_lead"] == 50.0
        assert "donnees_insuffisantes" not in canal
        # devise CAD dans le rapport (pas de signe mais l'ADR impose CAD)
        # nous vérifions que la valeur est numérique
        assert isinstance(canal["cout_par_lead"], (int, float))


class TestCoutIndisponible:
    """Cas RED (b) : canal avec leads mais sans coût ads joignable."""

    def test_cout_indisponible(self):
        rapport_attr = {
            "par_canal": [
                {"canal": "google", "leads_derniere_touche": 3}
            ]
        }
        rapport_ads = {
            "plateformes": []  # aucune plateforme renseignée
        }
        mapping_local = {
            "mappings": []
        }
        calendrier_local = {"fenetres": []}

        result = roi_engine.consolider_roi(
            rapport_attr,
            rapport_ads,
            mapping_local,
            calendrier_local,
            "2026-07-15"
        )
        canaux = result["par_canal"]
        assert len(canaux) == 1
        canal = canaux[0]
        assert canal["canal"] == "google"
        assert "cout_par_lead" not in canal
        assert canal["donnees_insuffisantes"]["raison"] == "cout_indisponible"


class TestZeroLeads:
    """Cas RED (d) variante: ads sans leads → zero_leads, jamais de division."""

    def test_zero_leads(self):
        rapport_attr = {
            "par_canal": [
                {"canal": "google", "leads_derniere_touche": 0}
            ]
        }
        rapport_ads = {
            "plateformes": [
                {
                    "plateforme": "google_ads",
                    "campagnes": [
                        {"campagne": "c1", "cout": 200, "fenetre_id": "fw-x"}
                    ]
                }
            ]
        }
        mapping_local = {
            "mappings": [
                {
                    "fenetre_id": "fw-x",
                    "utm_campaigns": ["c1"],
                    "plateforme_ads": "google_ads"
                }
            ]
        }
        calendrier_local = {"fenetres": [{"fenetre_id": "fw-x", "mois_debut": 1, "mois_fin": 12}]}

        result = roi_engine.consolider_roi(
            rapport_attr,
            rapport_ads,
            mapping_local,
            calendrier_local,
            "2026-07-15"
        )
        canal = result["par_canal"][0]
        assert "cout_par_lead" not in canal
        assert canal["donnees_insuffisantes"]["raison"] == "zero_leads"


class TestSansPont:
    """Cas RED (c) : campagne UTM hors mapping → sans_pont, jamais agrégée dans un coût."""

    def test_sans_pont(self):
        rapport_attr = {
            "par_canal": [
                {"canal": "google", "leads_derniere_touche": 5}
            ]
        }
        rapport_ads = {
            "plateformes": [
                {
                    "plateforme": "google_ads",
                    "campagnes": [
                        {"campagne": "camp-hors-mapping", "cout": 300, "fenetre_id": "fw-z"}
                    ]
                }
            ]
        }
        # mapping ne contient pas cette campagne
        mapping_local = {
            "mappings": []
        }
        calendrier_local = {"fenetres": [{"fenetre_id": "fw-z", "mois_debut": 1, "mois_fin": 12}]}

        result = roi_engine.consolider_roi(
            rapport_attr,
            rapport_ads,
            mapping_local,
            calendrier_local,
            "2026-07-15"
        )
        # La campagne est sans_pont → aucun canal ne doit contenir son coût
        canaux = result["par_canal"]
        # le canal "google" doit être présent mais avec état sans_pont ou sans coût
        # selon l'ADR : la campagne est classée sans_pont, son cout reste donnees_insuffisantes: mapping_absent
        canal = canaux[0]
        assert canal["donnees_insuffisantes"]["raison"] == "mapping_absent"
        assert "cout_par_lead" not in canal


class TestSnapshotDeterministe:
    """Cas RED (d) : deux appels identiques → snapshot_id identique, modification → différent."""

    def test_snapshot_identique(self, rapport_attribution, rapport_ads, mapping, calendrier):
        args = (rapport_attribution, rapport_ads, mapping, calendrier, DATE_REF)
        result1 = roi_engine.consolider_roi(*args)
        result2 = roi_engine.consolider_roi(*args)
        assert result1["snapshot_id"] == result2["snapshot_id"]

    def test_snapshot_different_si_modification(self, rapport_attribution, rapport_ads, mapping, calendrier):
        args = (rapport_attribution, rapport_ads, mapping, calendrier, DATE_REF)
        result1 = roi_engine.consolider_roi(*args)
        # modifie la date de référence
        args_mod = (rapport_attribution, rapport_ads, mapping, calendrier, "2026-08-15")
        result2 = roi_engine.consolider_roi(*args_mod)
        assert result1["snapshot_id"] != result2["snapshot_id"]


class TestDigestFenetres:
    """Cas RED (e) : fenêtres du calendrier sans campagne liée → contient 'aucune_campagne_liee'."""

    def test_digest_fenetres_reelles(self, rapport_attribution, rapport_ads, mapping, calendrier):
        result = roi_engine.consolider_roi(
            rapport_attribution,
            rapport_ads,
            mapping,
            calendrier,
            DATE_REF
        )
        fenetres = result["par_fenetre"]
        fen_ids = [f["fenetre_id"] for f in fenetres]
        # Toutes les fenêtres du calendrier doivent apparaître
        calendrier_ids = [f["id"] for f in calendrier["fenetres_marketing"]]
        assert set(fen_ids) == set(calendrier_ids)

        # Vérifie le digest de celles sans campagne liée (fw-transition-hiver-printemps, fw-preparation-hivernale)
        for f in fenetres:
            if f["fenetre_id"] in ("fw-transition-hiver-printemps", "fw-preparation-hivernale"):
                assert "aucune_campagne_liee" in f["digest_fr"]

        # Celles avec campagne ne contiennent pas cette chaîne
        for f in fenetres:
            if f["fenetre_id"] in ("fw-haute-saison-estivale", "fw-creux-hivernal"):
                assert "aucune_campagne_liee" not in f["digest_fr"]

        # nb_leads_attribues n'est plus un 0 codé en dur (R9 §1.2) : fw-haute-saison-estivale
        # a un lead réel (l-001, dernière touche google/fenetre-fw-haute-saison-estivale-2026),
        # fw-creux-hivernal a une campagne liée mais aucun lead ne l'a touchée dans la fenêtre
        # d'attribution de 30 jours (0 réel, mesuré — pas une valeur par défaut).
        par_fid = {f["fenetre_id"]: f for f in fenetres}
        assert par_fid["fw-haute-saison-estivale"]["nb_leads_attribues"] == 1
        assert par_fid["fw-creux-hivernal"]["nb_leads_attribues"] == 0
        assert "donnees_insuffisantes" not in par_fid["fw-haute-saison-estivale"]
        assert "donnees_insuffisantes" not in par_fid["fw-creux-hivernal"]


class TestJointureReelleCanalReel:
    """Cas RED explicite demandé par la mission : rejoue le pipeline attribution
    RÉELLE -> roi_engine (jamais des dicts à la main) pour le canal 'google', afin
    d'empêcher toute régression sur la jointure canal->plateforme (R9 §1.1)."""

    def test_canal_google_a_un_cout_par_lead_reel_non_fabrique(
        self, rapport_attribution, rapport_ads, mapping, calendrier
    ):
        # rapport_attribution/rapport_ads viennent des fixtures FIXTURES/ADS_FIXTURES_DIR
        # (moteurs réels), jamais construits à la main : c'est exactement le scénario que
        # les anciens tests synthétiques (canal="google_ads") masquaient.
        assert "google" in rapport_attribution["par_canal"], (
            "précondition : attribution_engine doit produire le canal brut 'google'"
        )
        result = roi_engine.consolider_roi(
            rapport_attribution, rapport_ads, mapping, calendrier, DATE_REF
        )
        canal_google = next(c for c in result["par_canal"] if c["canal"] == "google")
        assert "donnees_insuffisantes" not in canal_google, (
            f"la jointure canal->plateforme doit réussir pour 'google' : {canal_google}"
        )
        assert isinstance(canal_google["cout_par_lead"], (int, float))
        assert canal_google["cout_par_lead"] > 0
        # Valeur exacte dérivée des fixtures réelles (google_ads.yaml : 800 + 650 = 1450 CAD
        # de coût joignable, pour 1 lead en dernière touche réel — l-001) : verrouille la
        # non-régression au lieu de se contenter d'un simple type numérique.
        assert canal_google["cout_par_lead"] == pytest.approx(1450.0)

    def test_canal_sans_plateforme_ads_connue_reste_donnees_insuffisantes(
        self, rapport_attribution, rapport_ads, mapping, calendrier
    ):
        """Un canal organique sans plateforme ads mappée (ex. 'infolettre') ne doit
        JAMAIS fabriquer un coût : fail-closed, jamais une valeur inventée."""
        result = roi_engine.consolider_roi(
            rapport_attribution, rapport_ads, mapping, calendrier, DATE_REF
        )
        canal_infolettre = next(
            (c for c in result["par_canal"] if c["canal"] == "infolettre"), None
        )
        assert canal_infolettre is not None
        assert "cout_par_lead" not in canal_infolettre
        assert "donnees_insuffisantes" in canal_infolettre


class TestLienCampagneLeadAbsent:
    """nb_leads_attribues ne doit jamais retomber silencieusement à 0 quand le lien
    fenêtre->campagnes est totalement absent du mapping (R9 §1.2) : refus explicite."""

    def test_fenetre_sans_entree_mapping_refuse_explicitement(self):
        rapport_attr = {
            "par_canal": [],
            "par_campagne": {
                "une-campagne-quelconque-2026": {"leads_derniere_touche": 7}
            },
        }
        rapport_ads = {"plateformes": []}
        mapping_local = {"mappings": []}  # aucun lien fenêtre->campagnes déclaré
        calendrier_local = {
            "fenetres": [{"fenetre_id": "fw-sans-lien", "mois_debut": 1, "mois_fin": 12}]
        }

        result = roi_engine.consolider_roi(
            rapport_attr, rapport_ads, mapping_local, calendrier_local, "2026-07-15"
        )
        fenetre = result["par_fenetre"][0]
        assert fenetre["fenetre_id"] == "fw-sans-lien"
        assert "nb_leads_attribues" not in fenetre, (
            "un lien manquant ne doit jamais produire un nb_leads_attribues fabriqué (même à 0)"
        )
        assert fenetre["donnees_insuffisantes"]["raison"] == "lien_campagne_lead_absent"

    def test_fenetre_avec_lien_mais_sans_lead_touche_est_un_vrai_zero(self):
        """À l'inverse : un lien DÉCLARÉ mais dont aucune campagne n'a encore été
        touchée par un lead donne un 0 réel (mesuré), pas un refus."""
        rapport_attr = {"par_canal": [], "par_campagne": {}}
        rapport_ads = {"plateformes": []}
        mapping_local = {
            "mappings": [
                {
                    "fenetre_id": "fw-liee",
                    "utm_campaigns": ["contenu-jamais-touchee-2026"],
                    "plateforme_ads": "google_ads",
                }
            ]
        }
        calendrier_local = {
            "fenetres": [{"fenetre_id": "fw-liee", "mois_debut": 1, "mois_fin": 12}]
        }

        result = roi_engine.consolider_roi(
            rapport_attr, rapport_ads, mapping_local, calendrier_local, "2026-07-15"
        )
        fenetre = result["par_fenetre"][0]
        assert fenetre["nb_leads_attribues"] == 0
        assert "donnees_insuffisantes" not in fenetre


class TestRefsSha:
    """refs doit contenir trois sha256 (64 caractères hex)."""

    def test_refs_sha(self, rapport_attribution, rapport_ads, mapping, calendrier):
        result = roi_engine.consolider_roi(
            rapport_attribution,
            rapport_ads,
            mapping,
            calendrier,
            DATE_REF
        )
        refs = result["refs"]
        # Vérifie que les trois clés existent
        # selon la spec S015 : "sha256 des fixtures S013, S014 et du contrat UTM S012"
        assert "fixture_matomo" in refs or "attribution" in refs
        # L'ADR dit : refs (sha256 des fixtures S013, S014 et du contrat UTM S012)
        # donc 3 sha256 pour les fichiers d'entrée.
        # Le test vérifie simplement la présence de 3 chaînes hex de 64 chars
        hashes = [v for v in refs.values() if isinstance(v, str) and len(v) == 64]
        assert len(hashes) == 3
        for h in hashes:
            int(h, 16)  # doit être convertible en hex


class TestZeroReseauHorloge:
    """Pas d'import réseau/horloge, pas de score/inf/NaN dans le JSON final."""

    def test_imports_prohibés(self):
        source = inspect.getsource(roi_engine)
        interdits = [
            "urllib", "socket", "http.client", "requests", "httpx",
            "datetime.now", "time.time"
        ]
        for mot in interdits:
            assert mot not in source, f"Import interdit trouvé: {mot}"

    def test_json_sans_score_ni_infini(self, rapport_attribution, rapport_ads, mapping, calendrier):
        result = roi_engine.consolider_roi(
            rapport_attribution,
            rapport_ads,
            mapping,
            calendrier,
            DATE_REF
        )
        json_str = json.dumps(result, allow_nan=False)
        # Pas de NaN/Infinity (si allow_nan=False lève une exception, on pourrait aussi vérifier le dict)
        assert "score" not in json_str.lower()
        # Vérifie aussi dans les dicts qu'il n'y a pas de float infini
        def check_no_inf(obj):
            if isinstance(obj, float):
                assert not (obj == float('inf') or obj == float('-inf'))
            elif isinstance(obj, dict):
                for v in obj.values():
                    check_no_inf(v)
            elif isinstance(obj, list):
                for v in obj:
                    check_no_inf(v)
        check_no_inf(result)
