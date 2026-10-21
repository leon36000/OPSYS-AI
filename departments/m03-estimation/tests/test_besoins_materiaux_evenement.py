"""M3 publie `m3.besoins_materiaux` (PLAN T2.3-e) : par l'outil RÉEL `m3_estimer_projet`, sur le
stockage durable et le bus du socle (ADR-0009), dans la même transaction que l'inscription de
l'estimation — jamais seulement à l'acceptation du devis.

Prouve : le fait est publié quand l'estimation produit des quantités, et seulement alors ;
idempotent par devis et version d'estimation ; atomique avec le registre ; le catalogue du socle
refuse tout prix ou coût dans ce canal et ses clés sont celles du contrat. Fixtures fictives.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from m2_preparation_estimation import marqueur_m2
from sqlalchemy import func, select

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import besoins_materiaux, outils  # noqa: E402
from m3_estimation.outils import registre_production  # noqa: E402

from opsys import evenements, stockage  # noqa: E402
from opsys.evenements.schemas import erreurs_charge  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402
from opsys.stockage import codec  # noqa: E402
from opsys.stockage.schema import EVENEMENTS_SORTANTS  # noqa: E402

TYPE = "m3.besoins_materiaux"
SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
MATERIAUX = [
    {
        "materiau": "Revêtement vinyle (fictif)",
        "sku": "SKU-FICTIF-VINYLE",
        "quantite_par_unite": "0.0111",
        "unite": "carton",
        "facteur_perte": "0.10",
    },
    {"materiau": "Clous (fictif)", "quantite_par_unite": "0.5", "unite": "boite"},
]


def _bareme(materiaux=MATERIAUX):
    poste = {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}
    if materiaux is not None:
        poste["materiaux"] = copy.deepcopy(materiaux)
    return {"version": "2026.1", "unite": "pi2", "postes": {"ravalement": poste}}


def _photo(largeur=3000, reference=None):
    return {
        "photo_id": "p1", "resolution_largeur": largeur, "resolution_hauteur": 2000,
        "eclairage": 7, "angle": "face", "reference_echelle": reference,
    }


def _outil(nom):
    return next(o for o in outils.outils() if o.nom == nom)


def _estimer(**surcharges):
    arguments = {
        "contrat": {
            "lead_id": "lead-ev-001", "conversation_id": "conv-ev-001", "type_travaux": "ravalement",
            "ville": "Quebec", "canal": "formulaire_web",
            "contact": {"nom": "Durand", "telephone": "5145550000"}, "urgence_declaree": False,
        },
        "marqueur": marqueur_m2("lead-ev-001"),
        "photos": [_photo(reference={"type": "porte", "dimensions_connues": True})],
        "seuils": SEUILS,
        "bareme": _bareme(),
        "quantite": 1200,
        "plancher_rentable": 9000,
    }
    arguments.update(surcharges)
    return executer_atomique(_outil("m3_estimer_projet"), arguments)


def _publies():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == TYPE)
            .order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)
        ).mappings().all()
    return [(ligne["evenement_id"], ligne["producteur"], codec.decoder(ligne["charge"])) for ligne in lignes]


def _nb_evenements():
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one()


def _taille_registre():
    with stockage.transaction():
        return len(registre_production().lire())


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


# ------------------------------------------------------------------------------------- publication
def test_une_estimation_qui_produit_des_quantites_publie_les_besoins(base_durable):
    reponse = _estimer(taux_marge="0.35")
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    besoins = reponse["resultat"]["besoins_materiaux"]

    publies = _publies()
    assert len(publies) == 1, "un fait par estimation, publié sans attendre l'acceptation d'un devis"
    evenement_id, producteur, charge = publies[0]
    assert producteur == "m03-estimation"
    assert charge == besoins, "l'événement est exactement le contrat rendu à l'appelant"
    assert evenement_id == besoins_materiaux.identifiant_evenement(besoins)
    assert evenement_id.startswith(f"m3-besoins-materiaux-{besoins['devis_id']}-")


def test_aucun_devis_ni_acceptation_nest_requis_pour_publier(base_durable):
    _estimer()
    with stockage.transaction() as cnx:
        types = {ligne[0] for ligne in cnx.execute(select(EVENEMENTS_SORTANTS.c.type_evenement)).all()}
    assert types == {TYPE}


def test_la_charge_publiee_ne_porte_ni_prix_ni_cout_meme_avec_un_taux_de_marge(base_durable):
    _estimer(taux_marge="0.35")
    charge = _publies()[0][2]
    cles = set()

    def _parcourir(objet):
        if isinstance(objet, dict):
            for cle, valeur in objet.items():
                cles.add(cle)
                _parcourir(valeur)
        elif isinstance(objet, list):
            for element in objet:
                _parcourir(element)

    _parcourir(charge)
    assert not cles & besoins_materiaux.CLES_PRIX_ET_COUT_INTERDITES


def test_l_estimation_id_publie_est_le_hash_du_maillon_inscrit_au_registre_durable(base_durable):
    reponse = _estimer()
    besoins = reponse["resultat"]["besoins_materiaux"]
    with stockage.transaction():
        maillon = registre_production().lire()[0]
    assert besoins["estimation_id"] == maillon["hash_maillon"]
    assert besoins["rang_registre"] == maillon["rang"]
    assert maillon["charge"]["besoins_materiaux"]["lignes"] == besoins["lignes"]


# ------------------------------------------------------------------ quand rien ne doit être publié
def test_poste_sans_materiaux_ne_publie_rien(base_durable):
    reponse = _estimer(bareme=_bareme(None))
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True
    assert reponse["resultat"]["besoins_materiaux"] is None
    assert _nb_evenements() == 0


def test_prix_bloque_ne_publie_rien(base_durable):
    reponse = _estimer(photos=[_photo(largeur=100)])
    assert reponse["ok"] is True and reponse["resultat"]["estimation"]["prix_bloque"] is True
    assert _nb_evenements() == 0


def test_bloc_materiaux_malforme_ne_publie_rien_et_n_ecrit_rien_au_registre(base_durable):
    malforme = [{"materiau": "M", "quantite_par_unite": 0.5, "unite": "u"}]
    reponse = _estimer(bareme=_bareme(malforme))
    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-BESOINS-MATERIAUX-INVALIDE"
    assert _nb_evenements() == 0
    assert _taille_registre() == 0


# ------------------------------------------------------------------------------------- idempotence
def test_republier_la_meme_version_est_un_no_op_du_bus(base_durable):
    besoins = _estimer()["resultat"]["besoins_materiaux"]
    with stockage.transaction():
        # Rejeu du producteur (panne réseau entre l'écriture et la réponse) : même devis, même version.
        rejoue = outils._publier_besoins_materiaux(copy.deepcopy(besoins))
    assert rejoue == besoins_materiaux.identifiant_evenement(besoins)
    assert len(_publies()) == 1


def test_une_nouvelle_estimation_du_meme_devis_publie_une_nouvelle_version(base_durable):
    premier = _estimer()["resultat"]["besoins_materiaux"]
    second = _estimer()["resultat"]["besoins_materiaux"]
    assert premier["devis_id"] == second["devis_id"]
    assert premier["estimation_id"] != second["estimation_id"]
    identifiants = [evenement_id for evenement_id, _, _ in _publies()]
    assert len(identifiants) == len(set(identifiants)) == 2
    assert {charge["rang_registre"] for _, _, charge in _publies()} == {0, 1}


# --------------------------------------------------------------------------------------- atomicité
def test_si_la_publication_echoue_l_inscription_au_registre_est_annulee(base_durable, monkeypatch):
    def _refus(_contrat):
        raise evenements.ChargeInvalide("simulé : le catalogue refuse la charge")

    monkeypatch.setattr(outils, "_publier_besoins_materiaux", _refus)
    reponse = _estimer()
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier", reponse
    assert _taille_registre() == 0, "registre et événement réussissent ou échouent ensemble"
    assert _nb_evenements() == 0


# -------------------------------------------------------------------------- catalogue du socle
def _charge_valide():
    return copy.deepcopy(_estimer()["resultat"]["besoins_materiaux"])


def test_le_catalogue_declare_exactement_les_cles_du_contrat():
    schema = evenements.schema(TYPE)
    assert set(schema["properties"]) == set(schema["required"]) == set(besoins_materiaux.CHAMPS_BESOINS_MATERIAUX_V1)
    ligne = schema["properties"]["lignes"]["items"]
    assert set(ligne["required"]) == set(besoins_materiaux.CHAMPS_LIGNE_BESOINS_REQUIS)
    assert set(ligne["properties"]) == (
        set(besoins_materiaux.CHAMPS_LIGNE_BESOINS_REQUIS) | set(besoins_materiaux.CHAMPS_LIGNE_BESOINS_OPTIONNELS)
    )
    assert schema["additionalProperties"] is False and ligne["additionalProperties"] is False


def test_le_catalogue_accepte_le_contrat_produit_par_l_orchestrateur(base_durable):
    assert erreurs_charge(TYPE, _charge_valide()) == []


@pytest.mark.parametrize(
    "cle",
    ["prix_total", "prix_recommande", "cout_total", "taux_marge", "intervalle_confiance", "montant", "marge"],
)
def test_le_catalogue_refuse_toute_cle_de_prix_ou_de_cout_au_premier_niveau(base_durable, cle):
    charge = _charge_valide()  # publie une estimation valide : le compte de référence
    avant = _nb_evenements()
    charge[cle] = "1.00"
    with pytest.raises(evenements.ChargeInvalide, match=cle), stockage.transaction():
        evenements.publier(TYPE, "m03-estimation", charge, evenement_id="m3-test-charge-refusee")
    assert _nb_evenements() == avant, "un refus du catalogue n'écrit rien"


@pytest.mark.parametrize("cle", ["prix_unitaire", "prix_ligne", "cout_unitaire", "cout_ligne"])
def test_le_catalogue_refuse_toute_cle_de_prix_ou_de_cout_dans_une_ligne(base_durable, cle):
    charge = _charge_valide()  # publie une estimation valide : le compte de référence
    avant = _nb_evenements()
    charge["lignes"][0][cle] = "12.00"
    with pytest.raises(evenements.ChargeInvalide, match=cle), stockage.transaction():
        evenements.publier(TYPE, "m03-estimation", charge, evenement_id="m3-test-charge-refusee")
    assert _nb_evenements() == avant, "un refus du catalogue n'écrit rien"


def test_le_catalogue_refuse_une_quantite_en_nombre_json_et_un_facteur_de_perte_hors_forme(base_durable):
    charge = _charge_valide()
    charge["lignes"][0]["quantite_estimee"] = 13.32
    assert any("quantite_estimee" in erreur for erreur in erreurs_charge(TYPE, charge))
    charge = _charge_valide()
    charge["lignes"][0]["facteur_perte"] = "10 %"
    assert any("facteur_perte" in erreur for erreur in erreurs_charge(TYPE, charge))
    charge = _charge_valide()
    charge["niveau_confiance"] = "MULTI_VUES"
    assert any("niveau_confiance" in erreur for erreur in erreurs_charge(TYPE, charge))


def test_le_manifeste_declare_le_type_publie(base_durable):
    from opsys.departements import charger_departements

    departements = charger_departements()
    assert TYPE in departements["m03-estimation"].evenements_publie
    assert evenements.verifier_coherence(departements) == []
