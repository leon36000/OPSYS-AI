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


# ------------------------------------------------------------------------------------------ consommateur factice
def _avec_handlers(handlers, consomme):
    return SimpleNamespace(
        id="m09-fictif", numero=9, evenements_publie=(), evenements_consomme=tuple(consomme), racine=None,
        charger_consommateurs=lambda: dict(handlers))


def _handler_reel(charge):
    return {"recu": len(charge)}


def test_un_handler_qui_ne_fait_rien_ne_compte_pas_comme_un_consommateur_reel():
    inertes = {
        "m3.devis_accepte": lambda charge: {},
        "m2.client_associe": lambda charge: charge,
        "m4.travaux_termines": lambda charge: None,
    }
    dep = _avec_handlers(inertes, inertes)
    analyse = ic.analyser({"m09-fictif": dep}, {})
    assert sorted(e["type"] for e in analyse["handlers_inertes"]) == sorted(inertes)
    ligne = {x["type"]: x for x in analyse["matrice"]}["m3.devis_accepte"]
    assert ligne["consommateurs"] == []
    problemes = ic.problemes(analyse)
    assert any("m3.devis_accepte" in p and "inerte" in p for p in problemes)
    assert any("m3.devis_accepte" in p and "aucun consommateur réel" in p for p in problemes)


def test_un_vrai_handler_reste_un_consommateur_reel():
    dep = _avec_handlers({"m3.devis_accepte": _handler_reel}, ["m3.devis_accepte"])
    analyse = ic.analyser({"m09-fictif": dep}, {})
    assert analyse["handlers_inertes"] == []
    ligne = {x["type"]: x for x in analyse["matrice"]}["m3.devis_accepte"]
    assert ligne["consommateurs"] == ["m09-fictif"]


def test_un_handler_ferme_sur_une_variable_ou_une_methode_liee_n_est_pas_inerte():
    cible = []

    class Recepteur:
        recus: list = []

        def recevoir(self, charge):
            self.recus.append(charge)

    def fabrique(delegue):
        return lambda charge: delegue(charge)  # le seul nom est une variable libre : il délègue

    for handler in (fabrique(cible.append), Recepteur().recevoir):
        dep = _avec_handlers({"m3.devis_accepte": handler}, ["m3.devis_accepte"])
        assert ic.analyser({"m09-fictif": dep}, {})["handlers_inertes"] == []


def test_aucun_consommateur_reel_du_depot_n_est_inerte():
    from pathlib import Path

    from opsys.departements import charger_departements

    analyse = ic.analyser(charger_departements(Path(__file__).resolve().parents[1] / "departments"))
    assert analyse["handlers_inertes"] == []


# --------------------------------------------------------------------------------------- publication hors espace
def _producteur_m3(racine, code):
    (racine / "src" / "pub.py").write_text(code, encoding="utf-8")
    return SimpleNamespace(
        id="m03-fictif", numero=3, evenements_publie=(), evenements_consomme=(), racine=racine,
        charger_consommateurs=lambda: {})


def _hors_espace(racine, code):
    analyse = ic.analyser({"m03-fictif": _producteur_m3(racine, code)}, {})
    return analyse, [(e["type"], e["ligne"]) for e in analyse["publications_hors_espace"]]


def test_un_departement_qui_publie_dans_l_espace_d_un_autre_est_vu(racine):
    code = (
        "from opsys import evenements\n"
        "TYPE_FORGE = 'm5.dossier_cpa_scelle'\n"
        "def a():\n"
        "    evenements.publier('m5.rapprochement_po_constate', 'm03', {})\n"
        "def b():\n"
        "    evenements.publier(TYPE_FORGE, 'm05-financecore', {})\n"
        "def c():\n"
        "    publier('m2.client_associe', 'm03', {})\n")
    analyse, vus = _hors_espace(racine, code)
    assert vus == [("m5.rapprochement_po_constate", 4), ("m5.dossier_cpa_scelle", 6), ("m2.client_associe", 8)]
    assert any("m03-fictif : publie m5.dossier_cpa_scelle" in p for p in ic.problemes(analyse))


def test_son_propre_espace_opsys_les_commentaires_et_les_noms_non_resolus_ne_sont_pas_des_ecarts(racine):
    code = (
        "from opsys import evenements\n"
        "# evenements.publier('m5.dossier_cpa_scelle', 'x', {})\n"
        "DOC = \"evenements.publier('m5.dossier_cpa_scelle')\"\n"
        "def a(type_evenement):\n"
        "    evenements.publier('m3.devis_accepte', 'm03', {})\n"
        "    evenements.publier('opsys.demo_complete', 'm03', {})\n"
        "    evenements.publier(type_evenement, 'm03', {})\n"
        "    evenements.publier(modele.TYPE, 'm03', {})\n"
        "    evenements.publier()\n"
        "    autre.envoyer('m5.dossier_cpa_scelle')\n")
    assert _hors_espace(racine, code)[1] == []


def test_aucun_departement_du_depot_ne_publie_dans_l_espace_d_un_autre():
    from pathlib import Path

    from opsys.departements import charger_departements

    analyse = ic.analyser(charger_departements(Path(__file__).resolve().parents[1] / "departments"))
    assert analyse["publications_hors_espace"] == []


def test_un_fichier_illisible_ou_un_departement_sans_code_ne_fait_pas_tomber_l_audit(racine):
    (racine / "src" / "casse.py").write_text("def (:\n", encoding="utf-8")
    assert _hors_espace(racine, "x = 1\n")[1] == []
    sans_code = SimpleNamespace(
        id="m03-fictif", numero=3, evenements_publie=(), evenements_consomme=(), racine=None,
        charger_consommateurs=lambda: {})
    assert ic.analyser({"m03-fictif": sans_code}, {})["publications_hors_espace"] == []
