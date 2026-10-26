"""Écritures durables de M3 sous un commit concurrent : la précondition de rang du socle.

`opsys.stockage.MaillonsDurables.append` recalcule le rang au moment d'écrire : sans `rang_attendu`, un état lu
avant le commit d'un autre appel (PostgreSQL READ COMMITTED) est ajouté par-dessus, sans erreur. Chaque opération
du registre durable ouvre ici sa propre transaction (aucune transaction englobante) : l'enveloppe valide le maillon
`intrus` APRÈS la lecture de M3 et AVANT son ajout, exactement l'entrelacement d'un second processus. Simulation
déterministe sur SQLite ; la preuve PostgreSQL réelle reste à faire par la CI (opt-in PG). Données fictives.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m2_preparation_estimation import marqueur_m2  # noqa: E402
from m3_estimation import devis_durable, registre  # noqa: E402
from m3_estimation import outils as outils_m3  # noqa: E402

from opsys import evenements, stockage  # noqa: E402
from opsys.stockage.maillons import EcritureConcurrente  # noqa: E402

FICTIF = True
DEP = "m03-estimation"
_HORODATAGE = "2026-09-29T14:00:00-04:00"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m3-concurrence.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


class _CommitConcurrent:
    """Le registre durable vu par M3 quand un autre appel valide `intrus` entre sa lecture et son ajout.

    `declencheur` : l'accès après lequel l'autre appel valide (`iter` : la lecture de l'état d'un devis ;
    `dernier` : la lecture de la tête par `Registre.ajouter`). L'ajout de M3 est transmis tel quel au vrai registre."""

    def __init__(self, reel, intrus, declencheur="iter"):
        self._reel = reel
        self._intrus = intrus
        self._declencheur = declencheur
        self._fait = False

    def _concurrent(self, acces):
        if acces == self._declencheur and not self._fait:
            self._fait = True
            self._intrus(self._reel) if callable(self._intrus) else self._reel.append(self._intrus)

    def __iter__(self):
        maillons = list(self._reel)
        self._concurrent("iter")
        return iter(maillons)

    def __len__(self):
        return len(self._reel)

    def __getitem__(self, index):
        maillon = self._reel[index]
        if index == -1:
            self._concurrent("dernier")
        return maillon

    def append(self, maillon, **options):
        self._reel.append(maillon, **options)


def _ligne(cout="1600.00"):
    return {"description": "Gouttière alu 5 po", "quantite": "1", "unite": "forfait",
            "cout_unitaire": cout, "reference_besoin_materiau": None}


def _devis_maillons(devis_id):
    return [m for m in stockage.maillons(DEP, "devis") if m.get("devis_id") == devis_id]


def _maillon_devis_cree(devis_id, cout):
    """Ce qu'un autre appel de `creer_devis` aurait validé pour le même identifiant, autre contenu."""
    autre = []
    etat, verdict = devis_durable.creer_devis(devis_id, "lead-c", None, [_ligne(cout)], "0.25", _HORODATAGE, autre)
    assert verdict is None, verdict
    return autre[0]


def test_deux_creations_concurrentes_du_meme_devis_ne_laissent_jamais_deux_contenus(base_durable):
    intrus = _maillon_devis_cree("M3-DEVIS-conc-001", "9999.00")
    vu_par_m3 = _CommitConcurrent(stockage.maillons(DEP, "devis"), intrus)

    with pytest.raises(EcritureConcurrente):
        devis_durable.creer_devis(
            "M3-DEVIS-conc-001", "lead-c", None, [_ligne("1600.00")], "0.25", _HORODATAGE, vu_par_m3
        )

    maillons = _devis_maillons("M3-DEVIS-conc-001")
    assert [m["type_entree"] for m in maillons] == ["devis_cree"], "un seul contenu pour un identifiant"
    etat, _ = devis_durable.lire_devis(stockage.maillons(DEP, "devis"), "M3-DEVIS-conc-001")
    assert str(etat["prix_total"]) == "12498.75"  # celui qui a été validé le premier, jamais remplacé


def test_une_acceptation_concurrente_n_est_jamais_suivie_d_un_envoi_qui_la_defait(base_durable):
    reel = stockage.maillons(DEP, "devis")
    _, verdict = devis_durable.creer_devis("M3-DEVIS-conc-002", "lead-c", None, [_ligne()], "0.25", _HORODATAGE, reel)
    assert verdict is None
    acceptation = {"type_entree": "transition_devis", "devis_id": "M3-DEVIS-conc-002", "statut": "accepte",
                   "approbateur": "proprio", "horodatage": _HORODATAGE}

    with pytest.raises(EcritureConcurrente):
        devis_durable.marquer_devis_envoye(
            "M3-DEVIS-conc-002", "2026-09-29T18:00:00+00:00", _CommitConcurrent(reel, acceptation),
            approuve_par="proprio", approuve_role="nathan_owner",
        )

    assert [m.get("statut") for m in _devis_maillons("M3-DEVIS-conc-002")] == ["brouillon", "accepte"]
    etat, _ = devis_durable.lire_devis(reel, "M3-DEVIS-conc-002")
    assert etat["statut"] == "accepte"


def test_un_envoi_concurrent_ne_laisse_pas_une_seconde_acceptation_s_ecrire_sur_un_etat_perime(base_durable):
    reel = stockage.maillons(DEP, "devis")
    _, verdict = devis_durable.creer_devis("M3-DEVIS-conc-003", "lead-c", None, [_ligne()], "0.25", _HORODATAGE, reel)
    assert verdict is None
    acceptation = {"type_entree": "transition_devis", "devis_id": "M3-DEVIS-conc-003", "statut": "accepte",
                   "approbateur": "autre", "horodatage": _HORODATAGE}

    with pytest.raises(EcritureConcurrente):
        devis_durable.marquer_devis_accepte(
            "M3-DEVIS-conc-003", "proprio", _HORODATAGE, _CommitConcurrent(reel, acceptation)
        )

    assert [m.get("statut") for m in _devis_maillons("M3-DEVIS-conc-003")] == ["brouillon", "accepte"]


def _charge(devis_id):
    return {"devis_id": devis_id, "lead_id": "lead-c", "empreinte_marqueur_m2": "a" * 64,
            "niveau_confiance": 0.9, "bareme_version": "bareme-fictif-v1", "graine_monte_carlo": 7}


def test_deux_estimations_concurrentes_ne_cassent_jamais_la_chaine(base_durable):
    reel = stockage.maillons(DEP, "principal")
    _, verdict = registre.Registre(reel).ajouter(_charge("M3-DEVIS-conc-010"))
    assert verdict is None

    def estimation_concurrente(maillons):
        _, refus = registre.Registre(maillons).ajouter(_charge("M3-DEVIS-conc-011"))
        assert refus is None

    vu_par_m3 = _CommitConcurrent(reel, estimation_concurrente, declencheur="dernier")
    with pytest.raises(EcritureConcurrente):
        registre.Registre(vu_par_m3).ajouter(_charge("M3-DEVIS-conc-012"))

    journal = registre.Registre(stockage.maillons(DEP, "principal"))
    assert journal.valider_chaine() == (True, "")
    assert [m["charge"]["devis_id"] for m in journal.lire()] == ["M3-DEVIS-conc-010", "M3-DEVIS-conc-011"]


def test_sans_concurrence_le_registre_durable_et_la_liste_ecrivent_comme_avant(base_durable):
    """Contrepoint : la précondition ne refuse rien quand personne n'a écrit entre la lecture et l'ajout."""
    for cible in (stockage.maillons(DEP, "devis"), []):
        etat, verdict = devis_durable.creer_devis("M3-DEVIS-conc-020", "lead-c", None, [_ligne()], "0.25",
                                                  _HORODATAGE, cible)
        assert verdict is None and etat["statut"] == "brouillon"
        rejeu, verdict = devis_durable.creer_devis("M3-DEVIS-conc-020", "lead-c", None, [_ligne()], "0.25",
                                                   _HORODATAGE, cible)
        assert verdict is None and rejeu["statut"] == "brouillon"
        envoye, verdict = devis_durable.marquer_devis_envoye("M3-DEVIS-conc-020", "2026-09-29T18:00:00+00:00", cible)
        assert verdict is None and envoye["statut"] == "envoye"
        accepte, verdict = devis_durable.marquer_devis_accepte("M3-DEVIS-conc-020", "proprio", _HORODATAGE, cible)
        assert verdict is None and accepte["statut"] == "accepte"
        assert [m.get("statut") for m in cible if m.get("devis_id") == "M3-DEVIS-conc-020"] == [
            "brouillon", "envoye", "accepte"]

    for maillons in (stockage.maillons(DEP, "principal"), []):
        journal = registre.Registre(maillons)
        for numero in range(3):
            _, verdict = journal.ajouter(_charge(f"M3-DEVIS-conc-03{numero}"))
            assert verdict is None
        assert journal.valider_chaine() == (True, "")


# -- L'adaptateur (`outils.py`) rejoue sur une lecture fraîche ----------------------------------------------------
#
# Le rang est global au registre : l'écriture concurrente d'un AUTRE devis (ou d'une autre estimation) fait aussi
# lever la précondition. Sans rejeu, une décision du propriétaire exécutée par `decider` finirait en `echec` pour une
# écriture sans rapport. `essais=1` montre ce que serait l'outil sans rejeu ; `essais=3` est la valeur livrée.


def _vu_par_l_outil(monkeypatch, registre_nom, intrus, essais, declencheur="iter"):
    monkeypatch.setattr(outils_m3, "_ESSAIS_ECRITURE_CONCURRENTE", essais)
    vu = _CommitConcurrent(stockage.maillons(DEP, registre_nom), intrus, declencheur)
    if registre_nom == "devis":
        monkeypatch.setattr(outils_m3, "registre_devis_production", lambda: vu)
    else:
        monkeypatch.setattr(outils_m3, "registre_production", lambda: registre.Registre(vu))


@pytest.mark.parametrize("essais", [1, 3])
def test_la_creation_d_un_devis_survit_a_l_ecriture_concurrente_d_un_autre_devis(base_durable, monkeypatch, essais):
    _vu_par_l_outil(monkeypatch, "devis", _maillon_devis_cree("M3-DEVIS-conc-autre", "9999.00"), essais)

    with stockage.transaction():
        if essais == 1:
            with pytest.raises(EcritureConcurrente):
                outils_m3.creer_devis("M3-DEVIS-conc-040", "lead-c", None, [_ligne()], "0.25", _HORODATAGE)
            return
        reponse = outils_m3.creer_devis("M3-DEVIS-conc-040", "lead-c", None, [_ligne()], "0.25", _HORODATAGE)

    assert reponse["accepte"] is True and str(reponse["resultat"]["prix_total"]) == "2000.00", reponse
    assert [m["devis_id"] for m in stockage.maillons(DEP, "devis")] == ["M3-DEVIS-conc-autre", "M3-DEVIS-conc-040"]


def test_le_rejeu_d_une_creation_concurrente_du_meme_devis_rend_le_refus_nomme(base_durable, monkeypatch):
    _vu_par_l_outil(monkeypatch, "devis", _maillon_devis_cree("M3-DEVIS-conc-041", "9999.00"), 3)

    with stockage.transaction():
        reponse = outils_m3.creer_devis("M3-DEVIS-conc-041", "lead-c", None, [_ligne()], "0.25", _HORODATAGE)

    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-DEVIS-ID-DEJA-UTILISE", reponse
    assert [m["type_entree"] for m in _devis_maillons("M3-DEVIS-conc-041")] == ["devis_cree"]


@pytest.mark.parametrize("meme_devis", [False, True])
def test_l_acceptation_rejouee_suit_le_nouvel_etat_et_ne_publie_qu_une_acceptation_reelle(
    base_durable, monkeypatch, meme_devis
):
    reel = stockage.maillons(DEP, "devis")
    for devis_id in ("M3-DEVIS-conc-050", "M3-DEVIS-conc-051"):
        _, verdict = devis_durable.creer_devis(devis_id, "lead-c", None, [_ligne()], "0.25", _HORODATAGE, reel)
        assert verdict is None
    concurrent = "M3-DEVIS-conc-050" if meme_devis else "M3-DEVIS-conc-051"
    _vu_par_l_outil(monkeypatch, "devis", {
        "type_entree": "transition_devis", "devis_id": concurrent, "statut": "accepte",
        "approbateur": "autre", "horodatage": _HORODATAGE,
    }, 3)

    with stockage.transaction():
        reponse = outils_m3.marquer_devis_accepte("M3-DEVIS-conc-050", "proprio", _HORODATAGE)
        publiee = evenements.charge_publiee("m3.devis_accepte", "m3-devis-accepte-M3-DEVIS-conc-050")

    if meme_devis:
        assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-DEVIS-TRANSITION-ILLEGALE"
        assert publiee is None
    else:
        assert reponse["accepte"] is True and publiee is not None and publiee["devis_id"] == "M3-DEVIS-conc-050"
    assert [m.get("statut") for m in _devis_maillons("M3-DEVIS-conc-050")] == ["brouillon", "accepte"]


@pytest.mark.parametrize("essais", [1, 3])
def test_une_estimation_survit_a_une_estimation_concurrente_et_la_chaine_reste_valide(
    base_durable, monkeypatch, essais
):
    lead_id = "lead-conc-estimation-fictif"
    contrat_estimation = {
        "lead_id": lead_id,
        "conversation_id": "conv-conc-fictif",
        "type_travaux": "ravalement",
        "ville": "Quebec",
        "canal": "formulaire",
        "contact": {"nom": "Client fictif", "telephone": "555-0101"},
        "urgence_declaree": False,
    }
    arguments = {
        "contrat": contrat_estimation,
        "marqueur": marqueur_m2(lead_id, contrat=contrat_estimation),
        "photos": [{"photo_id": "p-fictif", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7,
                    "angle": "face", "reference_echelle": {"type": "porte", "dimensions_connues": True}}],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": {"version": "prix-fictifs-v1", "unite": "pi2",
                   "postes": {"ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}}},
        "quantite": 1, "plancher_rentable": 1, "graine": 42,
    }

    def estimation_concurrente(maillons):
        _, refus = registre.Registre(maillons).ajouter(_charge("M3-DEVIS-conc-autre-lead"))
        assert refus is None

    # Une estimation antérieure : `Registre.ajouter` ne lit la tête (`[-1]`) que sur une chaîne non vide.
    _, verdict = registre.Registre(stockage.maillons(DEP, "principal")).ajouter(_charge("M3-DEVIS-conc-avant"))
    assert verdict is None
    _vu_par_l_outil(monkeypatch, "principal", estimation_concurrente, essais, declencheur="dernier")
    if essais == 1:
        with pytest.raises(EcritureConcurrente):
            outils_m3.estimer_projet(**arguments)
        return
    reponse = outils_m3.estimer_projet(**arguments)

    assert reponse["accepte"] is True, reponse
    journal = registre.Registre(stockage.maillons(DEP, "principal"))
    assert journal.valider_chaine() == (True, "")
    charges = [m["charge"] for m in journal.lire()]
    assert [c["devis_id"] for c in charges[:2]] == ["M3-DEVIS-conc-avant", "M3-DEVIS-conc-autre-lead"]
    assert len(charges) == 3 and charges[2]["lead_id"] == lead_id
    assert reponse["estimation"]["hash_maillon"] == journal.hash_tete()
