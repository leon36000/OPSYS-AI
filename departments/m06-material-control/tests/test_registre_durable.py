"""Preuve du branchement du registre M6 sur le stockage durable de l'instance (ADR-0009).

`registre.py` reste pur (aucun import `opsys`/SQLAlchemy) : il ignore si ses maillons vivent dans
une liste Python ou dans `opsys.stockage.maillons(...)`. Ce test rejoue EXACTEMENT le même scénario
métier (réception, consommation, comptage) via les vrais orchestrateurs de `materiel.py` — jamais
des maillons construits à la main — sur un registre en mémoire et sur un registre durable SQLite, et
prouve : mêmes hash ; le stock relu par une instance TOUTE NEUVE (simulation de redémarrage, rien en
cache) est identique ; un lot qui échoue au milieu d'une transaction ne laisse aucun maillon
(`ajouter_lot` reste tout ou rien, ADR-0009 décision 2) ; une altération faite directement en base,
hors de toute méthode du registre, est détectée par `valider_chaine`. Une dernière preuve montre
que `outils.py` bascule bien sur ce registre durable dès qu'une transaction de l'instance est
ouverte — le registre de PRODUCTION — sans toucher au comportement mémoire de
`test_outils_agent.py` (aucune transaction n'y est jamais ouverte).

Import : comme `test_outils_agent.py`, aucune insertion dans `sys.path` — le `pythonpath` du
`pyproject.toml` racine suffit pour `m6_material_control` et `opsys`.
"""

from __future__ import annotations

import pytest
from m6_material_control import materiel, outils, stock
from m6_material_control.registre import Registre
from sqlalchemy import select, update

from opsys import stockage
from opsys.stockage import EcritureConcurrente, MaillonsDurables, codec
from opsys.stockage.schema import REGISTRES

_DEPARTEMENT = "m06-material-control"
_NOM_REGISTRE = "principal"
_CHANTIER = "CHANTIER-1"
_MATERIAU = "MAT-1"


def _bon_demande():
    return {
        "po_id": "PO-100",
        "chantier_id": _CHANTIER,
        "lignes_demandees": [{"materiau_id": _MATERIAU, "quantite_demandee": 10.0}],
        "horodatage": "2026-01-01T08:00:00Z",
    }


def _reception_po():
    return {
        "po_id": "PO-100",
        "chantier_id": _CHANTIER,
        "lignes_recues": [{"materiau_id": _MATERIAU, "quantite_recue": 10.0}],
        "horodatage": "2026-01-02T08:00:00Z",
    }


def _catalogue():
    return {
        "version": "2026.01",
        "unite_monetaire": "CAD",
        "postes": {_MATERIAU: {"cout_unitaire": 12.5, "libelle": "Matériau 1"}},
    }


def _wct():
    return {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "lead_id": "lead-1",
        "technicien_id": "tech-1",
        "horodatage_completion": "2026-01-03T00:00:00Z",
        "fix_gps_completion": {"latitude": 1.0, "longitude": 2.0},
        "duree_reelle_minutes": 30,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M6"],
        "devis_id": None,
    }


def _formulaire_consommation():
    return {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": _CHANTIER,
        "lignes_consommees": [{"materiau_id": _MATERIAU, "quantite": 4.0}],
    }


def _comptage():
    return {
        "chantier_id": _CHANTIER,
        "materiau_id": _MATERIAU,
        "quantite_comptee": 7.0,
        "horodatage": "2026-01-05T00:00:00Z",
    }


def _rejouer_scenario(registre: Registre) -> None:
    """Réception -> consommation -> comptage, via les VRAIS orchestrateurs de `materiel.py` (les
    seuls points d'écriture, DA-M6-11) : le scénario doit être identique quel que soit le support
    du registre reçu."""
    resultat, code = materiel.enregistrer_reception(_bon_demande(), _reception_po(), _catalogue(), registre)
    assert code is None, code
    assert resultat["accuse_reception"]["verdict_reception"] == "CONFORME"

    confirmation, code = materiel.consommer_materiaux(_wct(), _formulaire_consommation(), registre)
    assert code is None, code
    assert confirmation["stock_restant"] == [{"materiau_id": _MATERIAU, "quantite": 6.0}]

    variance, code = materiel.soumettre_comptage(_comptage(), registre)
    assert code is None, code
    assert variance["verdict_variance"] == "STOCK_SUPERIEUR_AU_THEORIQUE"
    assert variance["ecart"] == 1.0


@pytest.fixture
def base_sqlite(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée (ADR-0009), libérée après le test — jamais `~/.opsys`."""
    url = f"sqlite:///{tmp_path / 'm6-durable.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _registre_durable() -> Registre:
    return Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))


def test_meme_scenario_memoire_et_durable_produit_les_memes_hash(base_sqlite):
    memoire = Registre()
    _rejouer_scenario(memoire)

    with stockage.transaction():
        durable = _registre_durable()
        _rejouer_scenario(durable)

    maillons_memoire = memoire.lire()
    maillons_durable = durable.lire()
    assert len(maillons_memoire) == 3 and len(maillons_durable) == 3
    assert [m["hash_maillon"] for m in maillons_durable] == [m["hash_maillon"] for m in maillons_memoire]
    assert [m["hash_precedent"] for m in maillons_durable] == [m["hash_precedent"] for m in maillons_memoire]
    assert [m["quantite"] for m in maillons_durable] == [m["quantite"] for m in maillons_memoire]
    assert durable.hash_tete() == memoire.hash_tete()
    assert durable.valider_chaine() == memoire.valider_chaine() == (True, "")


def test_stock_identique_apres_relecture_par_une_nouvelle_instance(base_sqlite):
    """Simulation de redémarrage : la deuxième instance ne partage aucun état Python avec la
    première (nouveau `Registre`, nouveau `MaillonsDurables`) — seule la base persiste, exactement
    ce qui se passe entre deux démarrages du processus OPSYS (`MaillonsDurables` : aucun cache)."""
    with stockage.transaction():
        ecrivain = _registre_durable()
        _rejouer_scenario(ecrivain)
    tete_avant = ecrivain.hash_tete()

    redemarre = _registre_durable()
    assert len(redemarre.lire()) == 3
    assert redemarre.hash_tete() == tete_avant
    assert redemarre.valider_chaine() == (True, "")

    # Le stock théorique (RECEPTION + CONSOMMATION uniquement, stock.py) survit intact : 10 reçus
    # - 4 consommés = 6, quel que soit le maillon VARIANCE_INVENTAIRE du comptage écrit ensuite.
    assert stock.deriver_stock_theorique(_CHANTIER, _MATERIAU, redemarre) == 6.0


def test_lot_qui_echoue_au_milieu_ne_laisse_aucun_maillon(base_sqlite, monkeypatch):
    """`ajouter_lot` reste tout ou rien en durable : si le deuxième maillon d'un lot de trois
    échoue une fois le premier réellement écrit (panne simulée : un autre processus a écrit au
    même rang, `EcritureConcurrente`), la transaction de l'instance annule tout — aucun maillon du
    lot ne survit (ADR-0009 décision 2 : une transaction couvre l'écriture entière)."""
    with stockage.transaction():
        prealable = _registre_durable()
        prealable.ajouter(
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": _CHANTIER,
                "materiau_id": _MATERIAU,
                "quantite": 10.0,
                "cout_unitaire": 12.5,
            }
        )
    longueur_avant = len(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    assert longueur_avant == 1

    appel_original = MaillonsDurables.append
    appels = {"n": 0}

    def append_qui_echoue_au_deuxieme_maillon(self, maillon):
        appels["n"] += 1
        if appels["n"] == 2:
            raise EcritureConcurrente("panne simulée : un autre processus a écrit au même rang")
        return appel_original(self, maillon)

    monkeypatch.setattr(MaillonsDurables, "append", append_qui_echoue_au_deuxieme_maillon)

    lot = [
        {"type_mouvement": "CONSOMMATION", "chantier_id": _CHANTIER, "materiau_id": _MATERIAU,
         "quantite": -1.0, "cout_unitaire": 12.5},
        {"type_mouvement": "CONSOMMATION", "chantier_id": _CHANTIER, "materiau_id": _MATERIAU,
         "quantite": -2.0, "cout_unitaire": 12.5},
        {"type_mouvement": "CONSOMMATION", "chantier_id": _CHANTIER, "materiau_id": _MATERIAU,
         "quantite": -3.0, "cout_unitaire": 12.5},
    ]

    with pytest.raises(EcritureConcurrente), stockage.transaction():
        registre_du_lot = _registre_durable()
        registre_du_lot.ajouter_lot(lot)

    # Le premier maillon du lot AVAIT réellement été écrit (dans la transaction) avant l'échec du
    # deuxième : la preuve tient dans son absence après coup, pas seulement dans l'absence des
    # deux suivants.
    assert len(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE)) == longueur_avant
    assert list(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))[-1]["type_mouvement"] == "RECEPTION"


def test_alteration_d_un_maillon_en_base_est_detectee(base_sqlite):
    with stockage.transaction():
        ecrivain = _registre_durable()
        _rejouer_scenario(ecrivain)

    filtre = (
        (REGISTRES.c.departement == _DEPARTEMENT)
        & (REGISTRES.c.registre == _NOM_REGISTRE)
        & (REGISTRES.c.rang == 0)
    )
    with stockage.transaction() as cnx:
        texte_original = cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one()
        maillon = codec.decoder(texte_original)
        maillon["quantite"] = 999.0  # contenu changé, hash_maillon NON recalculé
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(maillon)))

    relu = _registre_durable()
    valide, message = relu.valider_chaine()
    assert valide is False
    assert "0" in message


def _formulaire_materiaux_utilises():
    return {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": _CHANTIER,
        "lignes_materiaux": [
            {
                "type_ligne": "prevu", "materiau_id": _MATERIAU, "quantite": 3.0,
                "unite": "boite", "quantite_estimee": 3.0,
            },
            {"type_ligne": "retour", "materiau_id": _MATERIAU, "quantite": 1.0, "unite": "boite"},
        ],
    }


def test_soumettre_materiaux_utilises_survit_au_stockage_durable_wct_id_inclus(base_sqlite):
    """PLAN T1.1-d2 : preuve que wct_id (optionnel, hors des huit clés historiques) et les
    nouveaux types RETOUR/PERTE/BRIS ne sont pas qu'un détail en mémoire — ils survivent
    un aller-retour Postgres/SQLite réel (codec JSON typé, opsys.stockage), relus par une
    instance TOUTE NEUVE (simulation de redémarrage, comme les tests voisins)."""
    with stockage.transaction():
        ecrivain = _registre_durable()
        resultat, code = materiel.enregistrer_reception(_bon_demande(), _reception_po(), _catalogue(), ecrivain)
        assert code is None, code

    with stockage.transaction():
        ecrivain = _registre_durable()
        confirmation, code = materiel.soumettre_materiaux_utilises(_wct(), _formulaire_materiaux_utilises(), ecrivain)
        assert code is None, code

    redemarre = _registre_durable()
    maillons = redemarre.lire()
    assert len(maillons) == 3
    assert maillons[1]["type_mouvement"] == "CONSOMMATION" and maillons[1]["wct_id"] == "wct-1"
    assert maillons[2]["type_mouvement"] == "RETOUR" and maillons[2]["wct_id"] == "wct-1"
    assert redemarre.valider_chaine() == (True, "")

    # Idempotence relue depuis le stockage durable, pas seulement en mémoire : une seconde
    # déclaration pour le même wct_id est refusée même après un « redémarrage » complet.
    with stockage.transaction():
        rejeu = _registre_durable()
        confirmation_2, code_2 = materiel.soumettre_materiaux_utilises(
            _wct(), _formulaire_materiaux_utilises(), rejeu
        )
    assert confirmation_2 is None
    assert code_2 == "REJ-DECLARATION-DEJA-SOUMISE"

    # Stock théorique cohérent (point 1) après écriture durable : 10 reçus - 3 consommés
    # (prevu) + 1 réintégré (retour) = 8.
    assert stock.deriver_stock_theorique(_CHANTIER, _MATERIAU, redemarre) == 8.0

    # variance_chantier.comparer_depuis_registre relit le même réel déclaré, durablement.
    from m6_material_control import variance_chantier

    verdicts = variance_chantier.comparer_depuis_registre(
        [{"materiau_id": _MATERIAU, "quantite_estimee": 3.0, "unite": "boite"}],
        _CHANTIER,
        redemarre,
        wct_id="wct-1",
    )
    assert verdicts[0]["quantite_reelle"] == 2.0  # 3 consommé - 1 rendu
    assert verdicts[0]["cause_possible"] is None


def test_outils_declarer_materiaux_utilises_utilise_le_registre_durable_en_production(base_sqlite):
    with stockage.transaction():
        outils.receptionner_commande(_bon_demande(), _reception_po(), _catalogue())

    with stockage.transaction():
        reponse = outils.declarer_materiaux_utilises(_wct(), _formulaire_materiaux_utilises())

    assert reponse["accepte"] is True
    relu = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE)
    assert len(relu) == 3
    assert relu[1]["type_mouvement"] == "CONSOMMATION"
    assert relu[2]["type_mouvement"] == "RETOUR"

    # Même patron que m6_receptionner_commande en production : tête + taille, jamais
    # l'historique complet.
    assert "registre_historique" not in reponse
    assert reponse["registre"] == {"taille": 3, "hash_tete": relu[-1]["hash_maillon"]}


def test_outils_receptionner_commande_utilise_le_registre_durable_en_production(base_sqlite):
    """`outils.py` bascule sur `stockage.maillons(...)` dès qu'une transaction de l'instance est
    ouverte (`Capacites.appeler`/`executer_atomique`, ADR-0009) : c'est le registre de PRODUCTION,
    sans historique à transporter. Hors transaction, `test_outils_agent.py` continue, lui,
    d'utiliser la mémoire — inchangé, aucune transaction n'y est jamais ouverte."""
    with stockage.transaction():
        reponse = outils.receptionner_commande(_bon_demande(), _reception_po(), _catalogue())

    assert reponse["accepte"] is True
    assert reponse["resultat"]["accuse_reception"]["verdict_reception"] == "CONFORME"

    # Le maillon est bien passé par le stockage durable, lisible par une instance neuve — jamais
    # seulement transporté dans le `registre_historique` de la réponse JSON.
    relu = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE)
    assert len(relu) == 1
    assert relu[0]["type_mouvement"] == "RECEPTION"
    assert relu[0]["quantite"] == 10.0

    # En production, la réponse ne renvoie pas l'historique (il grossit sans limite) : seulement
    # la tête de chaîne et la taille, cohérentes avec la base.
    assert "registre_historique" not in reponse
    assert reponse["registre"] == {"taille": 1, "hash_tete": relu[0]["hash_maillon"]}
