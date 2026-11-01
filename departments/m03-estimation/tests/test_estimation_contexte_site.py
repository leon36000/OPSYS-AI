"""M3.2 : les hypothèses du contexte de site accompagnent `m3_estimer_projet` (clé sœur `contexte_site`), sans toucher
au prix,
au blocage ni au registre d'estimation. Vrai socle, base SQLite migrée. Données fictives."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "fixture_estimation_stockage", Path(__file__).with_name("test_estimation_stockage.py")
)
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
base_durable = base.base_durable

FICTIF = True
LE = "2026-10-02T10:00:00-04:00"


def _contexte(lead_id="lead-stock-001", **declares):
    reponse = base._appeler(
        "m3_construire_contexte_site",
        {
            "lead_id": lead_id,
            "service": "ravalement",
            "date_reference": "2026-10-15",
            **({"facteurs_declares": declares} if declares else {}),
        },
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]["contexte"]


def _decl(valeur):
    return {"valeur": valeur, "declare_par": "estimateur.fictif", "declare_le": LE}


def _chaine():
    return len(base.registre_production().lire())


def test_sans_empreinte_la_reponse_est_celle_d_avant_sans_cle_contexte_site(base_durable):
    reponse = base._estimer()["resultat"]
    assert reponse["accepte"] is True and "contexte_site" not in reponse


def test_avec_une_empreinte_les_hypotheses_accompagnent_l_estimation_sans_changer_prix_ni_verdict(base_durable):
    contexte = _contexte(pente=_decl({"pente_sur_12": 5}))
    sans = base._estimer()["resultat"]
    avec = base._estimer(contexte_site_empreinte=contexte["empreinte"])["resultat"]
    assert avec["accepte"] is True and avec["contexte_site"]["empreinte"] == contexte["empreinte"]
    assert avec["contexte_site"]["version"] == 1 and avec["contexte_site"]["version_courante"] is True
    natures = {h["facteur"]: h["nature"] for h in avec["contexte_site"]["hypotheses_estimation"]}
    assert natures["pente"] == "donnee_retenue" and natures["hauteur"] == "a_collecter"
    assert "hauteur" in avec["contexte_site"]["inconnus"] and "permis_municipaux" in avec["contexte_site"]["a_verifier"]
    # le prix, le blocage et le contrat gelé sont ceux d'un appel sans contexte
    for cle in ("prix_recommande", "elements_manquants", "signal_relance_m2"):
        assert avec.get(cle) == sans.get(cle), cle
    assert set(avec["estimation"]) == set(sans["estimation"])
    for cle in ("verdict_estimation", "niveau_confiance", "prix_bloque", "intervalle_confiance", "bareme_version"):
        assert avec["estimation"][cle] == sans["estimation"][cle], cle


def test_une_empreinte_inconnue_est_refusee_avant_tout_calcul_et_n_ecrit_rien(base_durable):
    _contexte()
    avant = _chaine()
    reponse = base._estimer(contexte_site_empreinte="f" * 64)["resultat"]
    assert reponse["accepte"] is False and reponse["etape"] == "contexte_site"
    assert reponse["verdict"]["code"] == "REJ-CONTEXTE-INTROUVABLE"
    assert _chaine() == avant


def test_le_contexte_d_un_autre_lead_n_est_pas_reutilisable(base_durable):
    autre = _contexte(lead_id="lead-autre-002")
    avant = _chaine()
    reponse = base._estimer(contexte_site_empreinte=autre["empreinte"])["resultat"]
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-CONTEXTE-INTROUVABLE"
    assert _chaine() == avant


def test_une_ancienne_version_est_acceptee_mais_signalee_non_courante(base_durable):
    v1 = _contexte()
    _contexte(pente=_decl({"pente_sur_12": 7}))
    avec = base._estimer(contexte_site_empreinte=v1["empreinte"])["resultat"]
    assert avec["contexte_site"]["version"] == 1 and avec["contexte_site"]["version_courante"] is False


def test_le_contexte_ne_debloque_aucun_prix_photos_et_echelle_restent_la_seule_garde(base_durable):
    contexte = _contexte(
        hauteur=_decl({"etages": 2}), acces=_decl({"niveau": "libre"}), pente=_decl({"pente_sur_12": 4})
    )
    sans_reference = base._estimer(photos=[base._photo(reference=None)], contexte_site_empreinte=contexte["empreinte"])[
        "resultat"
    ]
    sans_reference_ni_contexte = base._estimer(photos=[base._photo(reference=None)])["resultat"]
    assert sans_reference["accepte"] is True
    assert sans_reference["estimation"]["prix_bloque"] == sans_reference_ni_contexte["estimation"]["prix_bloque"]
    assert (
        sans_reference["estimation"]["verdict_estimation"]
        == sans_reference_ni_contexte["estimation"]["verdict_estimation"]
    )


def test_un_contexte_avec_empreinte_non_textuelle_est_refuse_par_le_schema(base_durable):
    reponse = base._appeler(
        "m3_estimer_projet",
        {
            "contrat": base._contrat(),
            "marqueur": base._marqueur(),
            "photos": [base._photo()],
            "seuils": base.SEUILS,
            "bareme": base.BAREME,
            "quantite": 100,
            "plancher_rentable": 1,
            "contexte_site_empreinte": 12345,
        },
    )
    assert reponse["ok"] is False
