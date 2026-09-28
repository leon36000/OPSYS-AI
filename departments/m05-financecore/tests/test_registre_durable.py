"""Registre financier durable (ADR-0009) : mêmes garanties qu'en mémoire, sur `opsys.stockage`.

Le module pur `registre.py` ignore `opsys` : il ne voit dans `maillons` qu'un objet qui se
comporte comme une liste (voir son docstring de constructeur). Ce fichier prouve que brancher
`Registre` sur `opsys.stockage.maillons("m05-financecore", "principal")` — le registre des
MOUVEMENTS de production, actif dès le chargement de `outils.py` — ne change ni les
empreintes (`ligne_id`) ni le solde/argent disponible calculés face à un registre en mémoire, que
l'état (montants `Decimal` compris) survit à une nouvelle instance Python (donc à un redémarrage
de processus), et que la détection d'altération résiste à une écriture SQL directe qui contourne
complètement l'API Python du registre.

Scénario : encaissement client réel, taxes TPS/TVQ calculées dessus (fichier versionné réel,
CA-M5-07) mises en provision, décaissement fournisseur partiel — des montants `Decimal` réels,
jamais de float, exactement le contrat `MouvementFinancier` du paquet.

Aucune garde AST du département (`conformite.verifier_conformite`,
`verifier_aucun_import_domaine`, `verifier_aucune_cause_signalee`) ne porte sur ce fichier :
toutes scannent `src/m5_financecore`, jamais `tests/` (voir leurs appels dans
`test_conformite.py`) — aucune adaptation n'a donc été nécessaire (mandat, règle 4).

Import : comme les autres fichiers de tests du département, celui-ci insère `src/` dans
`sys.path` par prudence, mais s'appuie surtout sur le `pythonpath` de `pyproject.toml` racine
pour `opsys` et `sqlalchemy`.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import update

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m5_financecore import facturation, outils, registre, soldes, taux_fiscaux, taxes  # noqa: E402

from opsys import stockage  # noqa: E402
from opsys.stockage import codec  # noqa: E402
from opsys.stockage.schema import REGISTRES  # noqa: E402

_DEPARTEMENT = "m05-financecore"
_NOM_REGISTRE = "principal"
_CHEMIN_TAUX_FISCAUX = Path(__file__).resolve().parents[1] / "contracts" / "taux_fiscaux.v1.yaml"

HORODATAGE = "2026-08-03T12:00:00+00:00"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire et migrée, libérée en fin de test (patron de tests/test_stockage.py)."""
    url = f"sqlite:///{tmp_path / 'opsys-m5.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _scenario_mouvements() -> list[dict]:
    """Trois mouvements réels, montants `Decimal` (jamais de float) : le calcul de taxes
    versionné (CA-M5-07) est réellement exercé — pas une fixture inventée."""
    dictionnaire_taux, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX_FISCAUX)
    assert not erreurs, erreurs
    resultat_taxes, verdict = taxes.calculer_taxes(Decimal("500.00"), dictionnaire_taux)
    assert verdict is None, verdict

    return [
        {
            "montant": Decimal("500.00"),
            "type_mouvement": "ENCAISSEMENT",
            "horodatage": HORODATAGE,
            "classe_retention": "STANDARD",
            "source": "client-A",
        },
        {
            "montant": resultat_taxes["total_taxes"],
            "type_mouvement": "PROVISION",
            "horodatage": HORODATAGE,
            "classe_retention": "FISCALE_6_ANS",
            "source": "tps-tvq",
        },
        {
            "montant": Decimal("-120.00"),
            "type_mouvement": "DECAISSEMENT",
            "horodatage": HORODATAGE,
            "classe_retention": "STANDARD",
            "source": "fournisseur-B",
        },
    ]


def _ecrire_scenario(journal: registre.Registre, mouvements: list[dict]) -> None:
    for mouvement in mouvements:
        registre.enregistrer_mouvement(mouvement, journal)


# -- registre.py : même scénario, en mémoire et en durable -------------------------------------


def test_memes_empreintes_et_montants_decimal_en_memoire_et_en_durable(base_durable):
    mouvements = _scenario_mouvements()

    memoire = registre.Registre()
    _ecrire_scenario(memoire, mouvements)

    durable = registre.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    with stockage.transaction():
        _ecrire_scenario(durable, mouvements)

    maillons_memoire = memoire.lire()
    maillons_durables = durable.lire()

    assert type(maillons_durables) is list  # copie profonde -> liste, jamais MaillonsDurables
    assert [m["ligne_id"] for m in maillons_durables] == [m["ligne_id"] for m in maillons_memoire]
    assert [m["precedent_ligne_id"] for m in maillons_durables] == [
        m["precedent_ligne_id"] for m in maillons_memoire
    ]
    assert durable.tete() == memoire.tete()
    assert durable.valider_chaine() == (True, "")
    assert memoire.valider_chaine() == (True, "")

    for attendu, relu in zip(maillons_memoire, maillons_durables, strict=True):
        assert relu["montant"] == attendu["montant"]
        assert type(relu["montant"]) is Decimal


def test_solde_et_argent_disponible_identiques_apres_relecture_par_une_nouvelle_instance(base_durable):
    mouvements = _scenario_mouvements()

    ecrivain = registre.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    with stockage.transaction():
        _ecrire_scenario(ecrivain, mouvements)

    # Attendu déterministe (§_scenario_mouvements) : 500.00 encaissés, 120.00 décaissés ; la
    # PROVISION de taxes n'entre pas dans le solde (soldes._TYPES_SOLDE l'exclut), seulement dans
    # l'argent disponible.
    solde_attendu = Decimal("500.00") + Decimal("-120.00")
    disponible_attendu = solde_attendu - mouvements[1]["montant"]

    # Nouvelle instance Python, aucun état partagé avec `ecrivain` (pas même le module) : simule
    # un redémarrage de processus qui relit le registre depuis la base — rien en cache Python,
    # seule la base persiste (MaillonsDurables, docstring).
    relu = registre.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    assert relu is not ecrivain

    solde_relu = soldes.calculer_solde(relu)
    disponible_relu = soldes.calculer_argent_disponible(relu)

    assert solde_relu == solde_attendu == soldes.calculer_solde(ecrivain)
    assert disponible_relu == disponible_attendu == soldes.calculer_argent_disponible(ecrivain)
    assert type(solde_relu) is Decimal
    assert type(disponible_relu) is Decimal


def test_alteration_directe_en_base_est_detectee(base_durable):
    mouvements = _scenario_mouvements()

    ecrivain = registre.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    with stockage.transaction():
        _ecrire_scenario(ecrivain, mouvements)
    maillon_encaissement = ecrivain.lire()[0]
    assert maillon_encaissement["type_mouvement"] == "ENCAISSEMENT"

    # Falsification hors API Python : UPDATE SQL direct de la ligne du premier maillon, comme le
    # ferait un bogue ou une attaque qui contourne complètement le module pur `registre.py` — le
    # montant change, le ligne_id stocké ne bouge pas : exactement la mutation que
    # valider_chaine() doit repérer au recalcul par maillon (cf. test_registre.py équivalent en
    # mémoire, test_valider_chaine_detecte_une_valeur_de_maillon_falsifiee).
    falsifie = dict(maillon_encaissement, montant=Decimal("999999.99"))
    filtre = (
        (REGISTRES.c.departement == _DEPARTEMENT)
        & (REGISTRES.c.registre == _NOM_REGISTRE)
        & (REGISTRES.c.rang == 0)
    )
    with stockage.transaction() as cnx:
        resultat = cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(falsifie)))
        assert resultat.rowcount == 1, "l'UPDATE de preuve doit toucher exactement une ligne"

    relu = registre.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    valide, detail = relu.valider_chaine()

    assert valide is False
    assert detail
    # La lecture brute (hors validation) confirme que le montant falsifié est bien celui relu :
    # ce n'est pas une confusion de rang qui produirait aussi un `valide is False`.
    assert relu.lire()[0]["montant"] == Decimal("999999.99")


# -- outils.py : l'adaptateur (mandat, règle 2) -------------------------------------------------


def test_stockage_durable_persiste_entre_deux_appels_d_outil_sans_historique_transmis(base_durable):
    """`utiliser_stockage_durable()` est l'unique endroit du département qui connaît
    `opsys.stockage` : une fois actif, deux appels successifs à `outils.enregistrer_mouvement`
    SANS `mouvements_historique` s'enchaînent — la continuité n'est plus transportée par
    l'appelant, elle vit dans la base."""
    outils.reinitialiser_stockage_mouvements()
    try:
        outils.utiliser_stockage_durable()

        with stockage.transaction():
            r1 = outils.enregistrer_mouvement(
                montant="500.00",
                type_mouvement="ENCAISSEMENT",
                horodatage=HORODATAGE,
                classe_retention="STANDARD",
                source="client-A",
            )
        assert r1["accepte"] is True

        with stockage.transaction():
            r2 = outils.enregistrer_mouvement(
                montant="-120.00",
                type_mouvement="DECAISSEMENT",
                horodatage=HORODATAGE,
                classe_retention="STANDARD",
                source="fournisseur-B",
            )
        assert r2["accepte"] is True
        # Deuxième appel : aucun mouvements_historique transmis, pourtant il enchaîne bien sur le
        # premier (precedent_ligne_id) — c'est la base qui porte l'état entre deux appels d'outil.
        assert r2["resultat"]["precedent_ligne_id"] == r1["resultat"]["ligne_id"]

        etat = outils.etat_tresorerie(role="gestionnaire", autorise_couts=True)
        assert etat["solde"] == Decimal("380.00")
        assert etat["argent_disponible"] == Decimal("380.00")
        assert type(etat["solde"]) is Decimal
    finally:
        outils.reinitialiser_stockage_mouvements()


def test_reinitialiser_stockage_mouvements_revient_a_la_memoire(base_durable):
    outils.reinitialiser_stockage_mouvements()
    try:
        outils.utiliser_stockage_durable()
        with stockage.transaction():
            reponse = outils.enregistrer_mouvement(
                montant="500.00",
                type_mouvement="ENCAISSEMENT",
                horodatage=HORODATAGE,
                classe_retention="STANDARD",
                source="client-A",
            )
        assert reponse["accepte"] is True
    finally:
        outils.reinitialiser_stockage_mouvements()

    # De retour en mode test : un registre en mémoire vide, sans la donnée écrite en base — rien
    # ne fuit d'un test à l'autre.
    etat = outils.etat_tresorerie(role="gestionnaire", autorise_couts=True)
    assert etat["solde"] == Decimal("0")
    assert etat["argent_disponible"] == Decimal("0")


# -- outils.py : le registre des FACTURES (mandat T1.1-e), même patron que les mouvements ------

_LIGNES_FACTURE = [
    {
        "description": "Gouttières 5po aluminium",
        "quantite": "40",
        "unite": "pi",
        "prix_unitaire": "8.50",
        "reference_ligne_devis": "L1",
    },
    {
        "description": "Main d'oeuvre installation",
        "quantite": "1",
        "unite": "forfait",
        "prix_unitaire": "260.00",
        "reference_ligne_devis": "L2",
    },
]


def test_registre_des_factures_persiste_entre_deux_appels_d_outil_sans_historique_transmis(base_durable):
    """Même bascule `_stockage_durable_actif` que les mouvements (une seule, mandat T1.1-e) :
    une fois active, deux appels successifs à `outils.creer_facture_brouillon` SANS
    `factures_historique` s'enchaînent sur le registre durable dédié « factures », distinct de
    celui des mouvements (« principal »)."""
    outils.reinitialiser_stockage_mouvements()
    try:
        outils.utiliser_stockage_durable()

        with stockage.transaction():
            r1 = outils.creer_facture_brouillon(
                facture_id="FACT-001",
                chantier_id="CHANTIER-001",
                devis_id="DEVIS-001",
                client_id="CLIENT-001",
                lignes=_LIGNES_FACTURE,
                horodatage=HORODATAGE,
            )
        assert r1["accepte"] is True
        assert r1["registre_factures"]["taille"] == 1

        with stockage.transaction():
            r2 = outils.creer_facture_brouillon(
                facture_id="FACT-002",
                chantier_id="CHANTIER-002",
                devis_id="DEVIS-002",
                client_id="CLIENT-001",
                lignes=_LIGNES_FACTURE,
                horodatage=HORODATAGE,
            )
        assert r2["accepte"] is True
        # Deuxième appel, aucun historique transmis : il enchaîne quand même sur le premier —
        # la continuité vit dans la base (registre « factures »), pas chez l'appelant.
        assert r2["resultat"]["precedent_ligne_id"] == r1["resultat"]["ligne_id"]
        assert r2["registre_factures"]["taille"] == 2

        # Le registre des MOUVEMENTS, lui, n'a jamais été touché par ces deux appels de facture.
        etat = outils.etat_tresorerie(role="gestionnaire", autorise_couts=True)
        assert etat["solde"] == Decimal("0")
        assert etat["argent_disponible"] == Decimal("0")
    finally:
        outils.reinitialiser_stockage_mouvements()


def test_registre_des_factures_relu_par_une_nouvelle_instance_apres_redemarrage(base_durable):
    """Même preuve que pour les mouvements (`test_solde_et_argent_disponible_identiques_...`) :
    l'état d'un registre durable survit à une nouvelle instance Python, montants Decimal compris,
    sans qu'aucun état ne soit mis en cache côté module."""
    ecrivain = registre.Registre(maillons=stockage.maillons(_DEPARTEMENT, "factures"))
    with stockage.transaction():
        maillon, verdict = facturation.creer_facture_brouillon(
            facture_id="FACT-001",
            chantier_id="CHANTIER-001",
            devis_id="DEVIS-001",
            client_id="CLIENT-001",
            lignes=_LIGNES_FACTURE,
            horodatage=HORODATAGE,
            dictionnaire_taux=taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX_FISCAUX)[0],
            registre_cible=ecrivain,
        )
    assert verdict is None

    # Nouvelle instance Python, aucun état partagé avec `ecrivain` : simule un redémarrage.
    relu = registre.Registre(maillons=stockage.maillons(_DEPARTEMENT, "factures"))
    assert relu is not ecrivain
    assert relu.tete() == maillon["ligne_id"]
    assert relu.lire()[0]["facture_id"] == "FACT-001"
    assert relu.lire()[0]["montant_avant_taxes"] == Decimal("600.00")
    assert type(relu.lire()[0]["montant_avant_taxes"]) is Decimal
    assert relu.valider_chaine() == (True, "")
