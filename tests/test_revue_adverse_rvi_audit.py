"""Revue adverse rvi : l'audit d'interconnexion peut-il être trompé ?

`producteurs_sans_trace` doit voir un département qui DÉCLARE publier un type dont le nom n'apparaît nulle part dans son
code. Avant correction, un suffixe nu (« accepte », « client_associe ») cherché dans TOUT le socle trouvait toujours une
coïncidence : l'écart était invisible. Départements fictifs ; aucune écriture, aucune base.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opsys.evenements import interconnexion as ic

FICTIF = True


def _dep(racine, publie):
    return SimpleNamespace(
        id="m09-fictif", numero=9, evenements_publie=tuple(publie), evenements_consomme=(), racine=racine,
        charger_consommateurs=lambda: {})


@pytest.fixture
def racine(tmp_path):
    (tmp_path / "src").mkdir()
    return tmp_path


def _sans_trace(racine, publie):
    analyse = ic.analyser({"m09-fictif": _dep(racine, publie)}, {})
    return sorted(e["type"] for e in analyse["producteurs_sans_trace"])


def test_un_code_vide_ne_trouve_pas_de_trace_par_coincidence_avec_le_socle(racine):
    types = ["m3.devis_accepte", "m2.client_associe", "m4.travaux_termines", "m8.fait_consolide"]
    assert _sans_trace(racine, types) == sorted(types)
    assert any("devis_accepte" in p for p in ic.problemes(ic.analyser({"m09-fictif": _dep(racine, types)}, {})))


def test_un_suffixe_nu_dans_le_code_du_producteur_n_est_pas_une_trace(racine):
    (racine / "src" / "autre.py").write_text('STATUT = "accepte"\nCLE = "client_associe"\n', encoding="utf-8")
    assert _sans_trace(racine, ["m3.devis_accepte", "m2.client_associe"]) == ["m2.client_associe", "m3.devis_accepte"]


def test_le_nom_complet_dans_le_code_du_producteur_est_une_trace(racine):
    (racine / "src" / "producteur.py").write_text(
        'TYPE = "m3.devis_accepte"\nAUTRE = \'m2.client_associe\'\n', encoding="utf-8")
    assert _sans_trace(racine, ["m3.devis_accepte", "m2.client_associe"]) == []


def test_un_nom_compose_dans_le_code_du_producteur_reste_une_trace(racine):
    (racine / "src" / "producteur.py").write_text(
        'PREFIXE = "m3"\nTYPE = f"{PREFIXE}.devis_accepte"\n', encoding="utf-8")
    assert _sans_trace(racine, ["m3.devis_accepte"]) == []


def test_un_fichier_du_socle_qui_publie_le_type_reste_une_trace(monkeypatch, racine, tmp_path):
    socle = tmp_path / "socle"
    socle.mkdir()
    (socle / "planificateur.py").write_text(
        'from opsys import evenements\nevenements.publier("m3.devis_accepte", "m03", {})\n', encoding="utf-8")
    monkeypatch.setattr(ic, "_RACINE_SOCLE", socle)
    assert _sans_trace(racine, ["m3.devis_accepte"]) == []


def test_un_fichier_du_socle_qui_ne_fait_que_nommer_le_type_n_est_pas_une_trace(monkeypatch, racine, tmp_path):
    socle = tmp_path / "socle"
    socle.mkdir()
    (socle / "lecteur.py").write_text('TYPE_LU = "m3.devis_accepte"\n', encoding="utf-8")
    monkeypatch.setattr(ic, "_RACINE_SOCLE", socle)
    assert _sans_trace(racine, ["m3.devis_accepte"]) == ["m3.devis_accepte"]
