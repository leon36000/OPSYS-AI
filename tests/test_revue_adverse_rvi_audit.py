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


# ------------------------------------------------------------------------------------ lectures croisées déclarées
def _lecteur(racine, code):
    (racine / "src" / "lecteur.py").write_text(code, encoding="utf-8")
    return SimpleNamespace(
        id="m09-fictif", numero=9, racine=racine, module_outils="m9_fictif.outils", dependances=(),
        evenements_publie=(), evenements_consomme=(), charger_outils=lambda: ())


def _non_declarees(racine, code, declarees=()):
    lecteur = _lecteur(racine, code)
    audit = ic.auditer_lectures_croisees({"m09-fictif": lecteur}, list(declarees))
    return [x for x in audit["directes_non_declarees"] if x[0] == "m09-fictif"], audit


def test_une_lecture_directe_par_une_constante_au_nom_quelconque_est_vue(racine):
    code = (
        'from opsys import stockage\nVOISIN = "m04-field-ops"\n\n'
        'def lire():\n    return stockage.maillons(VOISIN, "principal")\n')
    non_declarees, audit = _non_declarees(racine, code)
    assert non_declarees == [("m09-fictif", "m04-field-ops")]
    attendu = "m09-fictif lit directement le registre de m04-field-ops sans que ce soit déclaré"
    assert attendu in ic.problemes_lectures(audit)


def test_une_constante_annotee_et_commentee_est_vue_aussi(racine):
    code = (
        'VOISIN: str = "m06-material-control"  # lecture du livre de prix\n'
        'x = stockage.maillons(VOISIN, "livre_prix")\n')
    assert _non_declarees(racine, code)[0] == [("m09-fictif", "m06-material-control")]


def test_la_lecture_deja_declaree_n_est_pas_un_ecart(racine):
    code = 'VOISIN = "m04-field-ops"\nx = stockage.maillons(VOISIN, "principal")\n'
    declaree = {"lecteur": "m09-fictif", "source": "m04-field-ops", "voie": "registre", "registres": ["principal"]}
    non_declarees, audit = _non_declarees(racine, code, [declaree])
    assert non_declarees == [] and ("m09-fictif", "m04-field-ops") not in audit["directes_disparues"]


def test_le_registre_de_son_propre_departement_et_une_constante_inutilisee_ne_sont_pas_des_ecarts(racine):
    code = 'MOI = "m09-fictif"\nAUTRE = "m04-field-ops"\nx = stockage.maillons(MOI, "principal")\ny = len(AUTRE)\n'
    assert _non_declarees(racine, code)[0] == []
