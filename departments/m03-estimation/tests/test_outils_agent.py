"""Capacités d'agent de M3 : contrat des outils et chaîne d'estimation composée (PLAN T2.3).

`estimer_projet` (et donc l'outil `m3_estimer_projet`) appelle désormais l'orchestrateur complet
(`estimation.orchestrer_estimation`, testé en détail par `test_estimation.py`) : ces tests
vérifient le CÂBLAGE agent (schéma JSON, forme réelle du contrat rendu à l'appelant) — jamais la
logique métier elle-même, déjà couverte ailleurs. La forme a changé par rapport à l'ancien
`estimer_projet` ad hoc : `contrat`/`marqueur` sont désormais des entrées requises,
`type_travaux` vit DANS `contrat`, et la réponse porte `estimation` (le contrat gelé EstimationV1,
avec `intervalle_confiance`, jamais `intervalle`) plutôt que des champs épars — `docs/departements/
M3-audit.md` §0/§4 phase 1, point 2 : « les 9 tests actuels de test_outils_agent.py sont adaptés à
la forme réelle du contrat, jamais affaiblis »."""

from __future__ import annotations

from pathlib import Path

from m3_estimation import contrats
from m3_estimation.outils import outils

from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, executer

SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
BAREME = {
    "version": "2026.1",
    "unite": "pi2",
    "postes": {"ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}},
}


def _photo(i, reference=None, largeur=3000, angle="face"):
    return {"photo_id": f"p{i}", "resolution_largeur": largeur, "resolution_hauteur": 2000,
            "eclairage": 7, "angle": angle, "reference_echelle": reference}


def _contrat(**surcharges):
    contrat = {
        "lead_id": "lead-agent-001",
        "conversation_id": "conv-agent-001",
        "type_travaux": "ravalement",
        "ville": "Quebec",
        "canal": "formulaire_web",
        "contact": {"nom": "Durand", "telephone": "5145550000"},
        "urgence_declaree": False,
    }
    contrat.update(surcharges)
    return contrat


def _marqueur(**surcharges):
    marqueur = {
        "readiness_ok": True,
        "lead_id": "lead-agent-001",
        "hash_tete_registre": "f" * 64,
        "horodatage": "2026-09-28T10:00:00-04:00",
        "empreinte": "a" * 64,
    }
    marqueur.update(surcharges)
    return marqueur


def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert noms[0] == "m3_estimer_projet"
    assert all(nom.startswith("m3_") for nom in noms)


def test_estimer_projet_autonomie_t1_car_il_ecrit_desormais_au_registre():
    """`m3_estimer_projet` écrit maintenant au registre durable "principal" (PLAN T2.3) : T1
    (écriture interne, docs/architecture/DEPARTEMENTS.md), plus T0 (audit M3 §2.4)."""
    outil = next(o for o in outils() if o.nom == "m3_estimer_projet")
    assert outil.autonomie == Autonomie.T1


def test_estimer_projet_arguments_invalides_ne_touche_jamais_le_stockage():
    """Un rejet de SCHÉMA (contrat manquant) court-circuite `executer()` avant tout appel à
    `estimer_projet`, donc avant tout accès au registre durable — même patron que
    `test_creer_devis_champ_requis_manquant_refuse_par_le_schema` ci-dessous. Le comportement
    d'exécution réelle (registre durable, devis_id, élargissement de l'intervalle, blocage,
    REFERENCE_ECHELLE_ABSENTE, arrondi au cent) est éprouvé par `test_estimation.py` (orchestrateur
    pur) et `test_estimation_stockage.py` (câblage durable réel)."""
    outil = next(o for o in outils() if o.nom == "m3_estimer_projet")
    reponse = executer(outil, {
        "marqueur": _marqueur(), "photos": [_photo(1, largeur=500)],
        "seuils": SEUILS, "bareme": BAREME, "quantite": 1200, "plancher_rentable": 9000,
    })
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"
    assert any("contrat" in detail for detail in reponse["details"])


def test_contrat_required_dans_le_schema_de_loutil():
    outil = next(o for o in outils() if o.nom == "m3_estimer_projet")
    assert "contrat" in outil.parametres["required"]
    assert "marqueur" in outil.parametres["required"]
    assert "type_travaux" not in outil.parametres["properties"], (
        "type_travaux ne doit plus être un paramètre séparé : il vit dans contrat"
    )


def test_contrat_declare_lenumere_type_travaux_dans_son_sous_schema():
    outil = next(o for o in outils() if o.nom == "m3_estimer_projet")
    enum_declare = outil.parametres["properties"]["contrat"]["properties"]["type_travaux"]["enum"]
    assert list(enum_declare) == list(contrats.TYPES_TRAVAUX)


def test_simuler_intervalle_outil_arrondit_aussi_au_cent():
    from decimal import Decimal
    outil = next(o for o in outils() if o.nom == "m3_simuler_intervalle")
    reponse = executer(outil, {"bareme": BAREME, "type_travaux": "ravalement",
                               "quantite": 1200, "graine": 42})
    assert reponse["ok"] is True
    intervalle = reponse["resultat"]["resultat"]
    for cle in ("borne_basse", "borne_haute"):
        valeur = Decimal(str(intervalle[cle]))
        assert valeur == valeur.quantize(Decimal("0.01")), f"{cle}={intervalle[cle]!r} pas arrondi au cent"


# ------------------------------------------------------------------ devis durable (PLAN T2.3-a) : contrat des outils
# Ces tests portent seulement sur le SCHÉMA JSON et l'autonomie déclarés : un rejet de schéma
# (`arguments_invalides`) court-circuite `executer()` avant tout appel à la fonction, donc avant
# tout accès au stockage — aucune base durable n'est nécessaire ici. Le comportement métier
# (calculs, idempotence, transitions, événement) est éprouvé par test_devis_durable.py et
# test_devis_durable_stockage.py.
_LIGNE_DEVIS_VALIDE = {
    "description": "Gouttière alu 5 po",
    "quantite": "30",
    "unite": "pi_lin",
    "cout_unitaire": "10.00",
    "reference_besoin_materiau": None,
}


def _outil_devis(nom):
    return next(o for o in outils() if o.nom == nom)


def test_les_trois_outils_devis_durable_sont_exposes_avec_lautonomie_attendue():
    """T1 pour la création (brouillon interne, PLAN T2.3-a), T0 pour la lecture, T3 pour
    l'acceptation (frontière humaine, AGENTS.md « engagements externes »)."""
    assert _outil_devis("m3_creer_devis").autonomie == Autonomie.T1
    assert _outil_devis("m3_lire_devis").autonomie == Autonomie.T0
    assert _outil_devis("m3_marquer_devis_accepte").autonomie == Autonomie.T3


def test_aucun_outil_denvoi_de_devis_au_client_nest_expose():
    """SOUL.md : « Envoyer un devis au client sans approbation : c'est une action externe. »
    L'envoi ira derrière les approbations du socle en T1.3 (PLAN T2.3-a) : aucun outil ne
    l'expose encore, exactement comme `m3_envoyer_devis_client` documenté mais absent (audit M3)."""
    noms = {o.nom for o in outils()}
    assert not any("envoy" in nom for nom in noms)


def test_creer_devis_champ_requis_manquant_refuse_par_le_schema():
    outil = _outil_devis("m3_creer_devis")
    arguments = {
        "devis_id": "M3-DEVIS-schema-001",
        "lead_id": "lead-1",
        "chantier_id": None,
        "lignes": [_LIGNE_DEVIS_VALIDE],
        "horodatage": "2026-09-28T14:00:00-04:00",
        # taux_marge manquant : requis par le schéma, jamais codé en dur.
    }
    reponse = executer(outil, arguments)
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"
    assert any("taux_marge" in detail for detail in reponse["details"])


def test_creer_devis_chantier_id_doit_etre_present_meme_null():
    """`chantier_id` est nullable mais REQUIS (présence de la clé) — même patron que `revue_id`
    dans le catalogue m4.travaux_termines.json : fail-closed, jamais un défaut silencieux."""
    outil = _outil_devis("m3_creer_devis")
    arguments = {
        "devis_id": "M3-DEVIS-schema-002",
        "lead_id": "lead-1",
        "lignes": [_LIGNE_DEVIS_VALIDE],
        "taux_marge": "0.20",
        "horodatage": "2026-09-28T14:00:00-04:00",
    }
    reponse = executer(outil, arguments)
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


def test_creer_devis_proprietes_inconnues_refusees_par_le_schema():
    outil = _outil_devis("m3_creer_devis")
    arguments = {
        "devis_id": "M3-DEVIS-schema-003",
        "lead_id": "lead-1",
        "chantier_id": None,
        "lignes": [_LIGNE_DEVIS_VALIDE],
        "taux_marge": "0.20",
        "horodatage": "2026-09-28T14:00:00-04:00",
        "prix": "1.00",  # jamais accepté en entrée (CLES_INTERDITES, cf. contrats.py)
    }
    reponse = executer(outil, arguments)
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


def test_lire_devis_role_hors_enum_refuse_par_le_schema():
    outil = _outil_devis("m3_lire_devis")
    reponse = executer(outil, {"devis_id": "M3-DEVIS-schema-004", "role": "proprietaire"})
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


def test_marquer_devis_accepte_approbateur_manquant_refuse_par_le_schema():
    outil = _outil_devis("m3_marquer_devis_accepte")
    reponse = executer(
        outil, {"devis_id": "M3-DEVIS-schema-005", "horodatage": "2026-09-28T14:00:00-04:00"}
    )
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"
