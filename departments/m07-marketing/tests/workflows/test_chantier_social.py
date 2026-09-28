"""Tests RED pour le workflow chantier_social selon ADR M7-S007.

Le module chantier_social n'est pas encore implémenté ; ces tests échouent
donc jusqu'à ce que le contrat soit respecté.
"""

import inspect
from pathlib import Path

import pytest
import yaml
from m7_marketing.content import approval
from m7_marketing.workflows import chantier_social

_M7 = Path(__file__).resolve().parents[2]

FIXTURE_VALIDE = _M7 / "fixtures" / "chantiers" / "residence-quebec-2026" / "chantier.yaml"
TIMESTAMP = "2026-07-25T00:00:00+00:00"
ACTEUR_PROPOSE = "alice"
ACTEUR_APPROUVE = "bob"

# PLAN T4.3 : `_charger_brand` réel est désormais fail-closed (`brand.profil_client`) et refuse
# le gabarit par défaut non configuré (`profile.yaml`, M7-audit.md §2.1) — ces tests portent sur
# l'orchestration chantier -> contenu social, pas sur la configuration de marque (couverte par
# `tests/test_brand_profil_client.py` et `tests/workflows/test_chantier_social.py::...non_autorise`
# ci-dessous, qui patche déjà `_charger_brand` explicitement). Un profil de marque de test valide
# et explicitement fictif est donc injecté par défaut pour tout ce module.
_BRAND_TEST = {
    "name": "TestCo",  # court : évite de dépasser la limite de 100 caractères du titre (S006)
    "tagline": "Tagline de test — jamais une donnée réelle",
    "tone": "professionnel",
    "colors": ["#111111"],
    "langue": "fr",
}


@pytest.fixture(autouse=True)
def _brand_client_test(monkeypatch):
    monkeypatch.setattr(chantier_social, "_charger_brand", lambda: dict(_BRAND_TEST))


def _creer_fixture(
    tmp_path: Path,
    nom_dossier: str,
    contenu_chantier: dict,
) -> Path:
    dossier = tmp_path / nom_dossier
    dossier.mkdir()
    fichier = dossier / "chantier.yaml"
    import yaml

    with open(fichier, "w", encoding="utf-8") as f:
        yaml.dump(contenu_chantier, f, allow_unicode=True, default_flow_style=False)
    return fichier


class TestRefusFixtureSansFictif:
    def test_refus_fixture_sans_fictif(self, tmp_path: Path) -> None:
        """Fixture avec fictif: false -> ValueError mentionnant 'fictif'."""
        contenu = {
            "fictif": False,
            "ville": "Québec",
            "type_travaux": "renovation_totale",
            "date_fin": "2026-06-30",
            "description_factuelle": "Description factuelle valide mais sans engagement.",
            "photos": ["photos/avant.jpg"],
        }
        chemin = _creer_fixture(tmp_path, "chantier-invalide", contenu)
        with pytest.raises(ValueError, match=r".*fictif.*"):
            chantier_social.orchestrer_chantier_vers_social(
                str(chemin),
                TIMESTAMP,
                ACTEUR_PROPOSE,
                ACTEUR_APPROUVE,
            )


class TestChaineCompleteReelle:
    def test_chaine_complete_reelle(self) -> None:
        """Fixture valide -> étapes OK, NotAutorise tracé, métriques."""
        approval.reset()
        resultat = chantier_social.orchestrer_chantier_vers_social(
            str(FIXTURE_VALIDE),
            TIMESTAMP,
            ACTEUR_PROPOSE,
            ACTEUR_APPROUVE,
        )
        assert resultat["chantier_slug"] == "residence-quebec-2026"

        etapes = resultat["etapes"]
        assert len(etapes) == 5
        noms_attendus = ["charge", "compose", "propose", "approuve", "publication"]
        for idx, nom in enumerate(noms_attendus):
            assert etapes[idx]["nom"] == nom

        # Les quatre premières étapes aboutissent normalement.
        for idx in range(4):
            assert etapes[idx]["statut"] == "SUCCES"

        # NEW-PROD-008 : une publication refusée par le gate doit être BLOQUE,
        # jamais SUCCES, même si le détail mentionne NotAutorise.
        assert etapes[4]["statut"] == "BLOQUE"

        detail_pub = etapes[-1]["detail"]
        assert "NotAutorise" in str(detail_pub)

        metriques = resultat["metriques"]
        assert metriques == {
            "chantiers_traites": 1,
            "contenus_proposes": 1,
            "publications_bloquees_gated": 1,
        }


class TestAutoApprobationRefusee:
    def test_auto_approbation_refusee(self) -> None:
        """Même acteur proposant/approuvant -> étape approuve en ECHEC."""
        approval.reset()
        resultat = chantier_social.orchestrer_chantier_vers_social(
            str(FIXTURE_VALIDE),
            TIMESTAMP,
            "alice",
            "alice",
        )
        etapes = resultat["etapes"]
        # On attend que l'étape "approuve" échoue et les suivantes absentes
        assert len(etapes) <= 4
        derniere = etapes[-1]
        assert derniere["nom"] == "approuve"
        assert derniere["statut"] == "ECHEC"
        detail = str(derniere["detail"]).lower()
        assert "auto" in detail or "distinct" in detail

        # Vérifier qu'aucune étape "publication" n'est présente
        noms = [e["nom"] for e in etapes]
        assert "publication" not in noms


class TestGatingFlagOff:
    def test_gating_flag_off(self) -> None:
        """Adaptateur disabled -> étape publication ECHEC AdapterDisabled, métrique 0."""
        approval.reset()
        resultat = chantier_social.orchestrer_chantier_vers_social(
            str(FIXTURE_VALIDE),
            TIMESTAMP,
            ACTEUR_PROPOSE,
            ACTEUR_APPROUVE,
            adapter_config={"enabled": False, "dry_run": True},
        )
        etapes = resultat["etapes"]
        # Vérifier que l'étape publication existe et est en échec
        pub_etape = etapes[-1]
        assert pub_etape["nom"] == "publication"
        assert pub_etape["statut"] == "ECHEC"
        assert "AdapterDisabled" in str(pub_etape["detail"])
        assert resultat["metriques"]["publications_bloquees_gated"] == 0


class TestDeterminisme:
    def test_determinisme(self) -> None:
        """Deux appels identiques -> résultats strictement identiques."""
        approval.reset()
        resultat1 = chantier_social.orchestrer_chantier_vers_social(
            str(FIXTURE_VALIDE),
            TIMESTAMP,
            ACTEUR_PROPOSE,
            ACTEUR_APPROUVE,
        )
        approval.reset()
        resultat2 = chantier_social.orchestrer_chantier_vers_social(
            str(FIXTURE_VALIDE),
            TIMESTAMP,
            ACTEUR_PROPOSE,
            ACTEUR_APPROUVE,
        )
        assert resultat1 == resultat2


class TestZeroReseau:
    def test_zero_reseau(self) -> None:
        """Le code source de chantier_social ne mentionne aucune lib réseau."""
        source = inspect.getsource(chantier_social)
        motifs_interdits = ["urllib", "socket", "http.client", "requests"]
        for motif in motifs_interdits:
            assert motif not in source, (
                f"Le symbole réseau '{motif}' ne doit pas apparaître dans chantier_social"
            )


def test_type_travaux_invalide_rejete(tmp_path):
    """Un type_travaux hors énumération ADR doit être refusé fail-closed (comme fictif)."""
    with open(FIXTURE_VALIDE, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["type_travaux"] = "demolition"
    dossier = tmp_path / "chantier-invalide"
    dossier.mkdir()
    fixture_path = dossier / "chantier.yaml"
    with open(fixture_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)
    with pytest.raises(ValueError, match="type_travaux"):
        chantier_social.orchestrer_chantier_vers_social(
            str(fixture_path), TIMESTAMP, ACTEUR_PROPOSE, ACTEUR_APPROUVE
        )


def test_orchestrer_chantier_vers_social_statut_bloque_quand_non_autorise(
    tmp_path, monkeypatch
):
    """NEW-PROD-008 : une publication refusée par le gate doit être BLOQUE, jamais SUCCES."""
    chantier_dir = tmp_path / "residence-quebec-2026"
    chantier_dir.mkdir()
    chantier_file = chantier_dir / "chantier.yaml"
    chantier_file.write_text(
        yaml.safe_dump(
            {
                "fictif": True,
                "type_travaux": "renovation_totale",
                "ville": "Québec",
                "description_factuelle": "Rénovation complète d'une résidence.",
                "photos": [],
            }
        )
    )

    monkeypatch.setattr(chantier_social, "_charger_brand", lambda: {"nom": "TestBrand"})
    monkeypatch.setattr(
        chantier_social, "build_content_item", lambda *args, **kwargs: {"body": "Corps du post"}
    )

    approval_module = getattr(chantier_social, "approval", approval)
    monkeypatch.setattr(approval_module, "propose", lambda item, *args, **kwargs: item)
    monkeypatch.setattr(approval_module, "approve", lambda item, *args, **kwargs: item)

    class FakeCanal:
        GBP = type("GBP", (), {"value": "GBP"})()

    monkeypatch.setattr(chantier_social, "Canal", FakeCanal)

    class FakeSocialPost:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(chantier_social, "SocialPost", FakeSocialPost)

    class FakeAdapter:
        def __init__(self, config):
            self.config = config

        def publier(self, post):
            raise chantier_social.NotAutorise("publication non autorisée")

    monkeypatch.setattr(chantier_social, "PostizAdapter", FakeAdapter)

    result = chantier_social.orchestrer_chantier_vers_social(
        chemin_chantier=str(chantier_file),
        timestamp="2024-05-20T12:00:00Z",
        acteur_propose="alice",
        acteur_approuve="bob",
    )

    publication_etape = next(e for e in result["etapes"] if e["nom"] == "publication")
    assert publication_etape["statut"] == "BLOQUE"
    assert publication_etape["statut"] != "SUCCES"
    assert result["metriques"]["publications_bloquees_gated"] == 1
