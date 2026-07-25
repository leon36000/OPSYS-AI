"""Tests RED pour le workflow chantier_social selon ADR M7-S007.

Le module chantier_social n'est pas encore implémenté ; ces tests échouent
donc jusqu'à ce que le contrat soit respecté.
"""

import sys
import inspect
import shutil
from pathlib import Path

import pytest

_M7 = Path(__file__).resolve().parents[2]
for p in (
    str(_M7 / "src" / "workflows"),
    str(_M7 / "src" / "content"),
    str(_M7 / "src" / "social"),
):
    if p not in sys.path:
        sys.path.insert(0, p)

import chantier_social  # noqa: E402

import approval  # noqa: E402

FIXTURE_VALIDE = _M7 / "fixtures" / "chantiers" / "residence-quebec-2026" / "chantier.yaml"
TIMESTAMP = "2026-07-25T00:00:00+00:00"
ACTEUR_PROPOSE = "alice"
ACTEUR_APPROUVE = "bob"


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
            chantier_social.orchestrer(
                str(chemin),
                TIMESTAMP,
                ACTEUR_PROPOSE,
                ACTEUR_APPROUVE,
            )


class TestChaineCompleteReelle:
    def test_chaine_complete_reelle(self) -> None:
        """Fixture valide -> étapes OK, NotAutorise tracé, métriques."""
        approval.reset()
        resultat = chantier_social.orchestrer(
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
            assert etapes[idx]["statut"] == "SUCCES"

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
        resultat = chantier_social.orchestrer(
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
        resultat = chantier_social.orchestrer(
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
        resultat1 = chantier_social.orchestrer(
            str(FIXTURE_VALIDE),
            TIMESTAMP,
            ACTEUR_PROPOSE,
            ACTEUR_APPROUVE,
        )
        approval.reset()
        resultat2 = chantier_social.orchestrer(
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
