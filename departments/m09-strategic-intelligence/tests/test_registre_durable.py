"""Branchement du registre de snapshots M9 sur le stockage durable de l'instance (ADR-0009).

Même scénario (trois snapshots réels) rejoué en mémoire et en durable SQLite (base temporaire) :
mêmes maillons, mêmes hash, chaîne valide après relecture par une NOUVELLE instance Python
(aucun cache — la preuve qu'un redémarrage du processus ne perd rien), et une altération directe
d'un maillon en base est détectée par `valider_chaine()`.

Aucune garde AST du département (`conformite.verifier_conformite`,
`verifier_aucun_import_domaine`, `verifier_aucune_cause_signalee`) ne porte sur ce fichier :
toutes scannent `src/m9_strategic_intelligence`, jamais `tests/` (voir leurs appels dans
test_conformite.py) — aucune adaptation n'a donc été nécessaire (mandat, règle 4).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m9_strategic_intelligence import outils, registre
from sqlalchemy import select, update

from opsys import contexte, stockage
from opsys.contexte import IdentiteAppelante
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

_SRC = Path(__file__).resolve().parents[1] / "src"

DEPARTEMENT = "m09-strategic-intelligence"
REGISTRE_NOM = "snapshots"


def _snapshot(module_source, horodatage, valeurs):
    return {"module_source": module_source, "horodatage": horodatage, "valeurs": valeurs}


_SNAPSHOTS = [
    _snapshot("M-durable", "2026-01-04T00:00:00Z", {"prevision": "100"}),
    _snapshot("M-durable", "2026-01-05T00:00:00Z", {"prevision": "110"}),
    _snapshot("M-durable", "2026-01-06T00:00:00Z", {"prevision": "120"}),
]


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire, isolée de ~/.opsys et de toute autre suite (OPSYS_BASE_URL)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _rejouer(cible: registre.RegistreSnapshots) -> list[dict]:
    maillons = []
    for snapshot in _SNAPSHOTS:
        maillon, erreur = cible.ajouter(snapshot)
        assert erreur is None
        maillons.append(maillon)
    return maillons


def test_meme_scenario_en_memoire_et_en_durable_produit_les_memes_hash(base_durable):
    memoire = registre.RegistreSnapshots()
    _rejouer(memoire)

    with stockage.transaction():
        durable = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
        _rejouer(durable)

    # Relecture par une instance neuve (aucun cache Python) : même contenu, mêmes hash, que le
    # registre vive en mémoire ou dans la base durable.
    durable_relu = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
    assert durable_relu.lire() == memoire.lire()
    assert [m["hash_maillon"] for m in durable_relu.lire()] == [m["hash_maillon"] for m in memoire.lire()]
    assert durable_relu.hash_tete() == memoire.hash_tete() != registre.HASH_PREDECESSEUR_INITIAL
    assert memoire.valider_chaine() == (True, "")
    assert durable_relu.valider_chaine() == (True, "")


def test_valider_chaine_vrai_apres_relecture_par_une_nouvelle_instance(base_durable):
    with stockage.transaction():
        premiere = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
        _rejouer(premiere)
        tete_attendue = premiere.hash_tete()

    # Nouvelle instance, comme après un redémarrage du processus MCP : reconstruit son état
    # entièrement depuis la base, sans rien connaître de `premiere`.
    relue = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
    assert len(relue.lire()) == 3
    assert relue.hash_tete() == tete_attendue
    assert relue.valider_chaine() == (True, "")


def test_alteration_directe_d_un_maillon_en_base_est_detectee(base_durable):
    with stockage.transaction():
        cible = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
        _rejouer(cible)

    filtre = (
        (REGISTRES.c.departement == DEPARTEMENT)
        & (REGISTRES.c.registre == REGISTRE_NOM)
        & (REGISTRES.c.rang == 0)
    )
    with stockage.transaction() as cnx:
        # Altération SQL directe du premier maillon, hash_maillon laissé tel quel (comme une
        # écriture hors application) : valeurs et empreinte stockée divergent désormais.
        texte = cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one()
        maillon = codec.decoder(texte)
        assert maillon["valeurs"] == {"prevision": "100"}
        maillon["valeurs"] = {"prevision": "ALTERE-EN-BASE"}
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(maillon)))

    relue = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
    valide, message = relue.valider_chaine()
    assert valide is False
    assert "0" in message


def test_adaptateur_branche_le_registre_de_production_sur_stockage_maillons():
    """Preuve statique de la règle 2 (mission de branchement) : `outils()` sans argument —
    utilisé par `charger_outils()` en production — adosse le registre à
    `stockage.maillons("m09-strategic-intelligence", "snapshots")`."""
    texte = (_SRC / "m9_strategic_intelligence" / "outils.py").read_text(encoding="utf-8")
    assert 'stockage.maillons("m09-strategic-intelligence", "snapshots")' in texte


_MATIN = "2026-01-05T07:00:00Z"
_SOURCE_FICTIVE = _snapshot("source-declaree-fictive", "2026-01-04T12:00:00Z", {"prevision": "100.00"})
_LECTURES_ET_AJOUT = [
    ("m9_lire_etat_consolide", {}),
    ("m9_produire_briefing_matin", {"maintenant": _MATIN}),
    ("m9_lire_suite_briefing", {"maintenant": _MATIN, "section": "faits_veille"}),
    ("m9_etat_consolide", {"snapshot": _snapshot("autre-source-fictive", _MATIN, {"prevision": "200.00"})}),
]


def _appeler_natif(nom, arguments):
    return executer_atomique({o.nom: o for o in outils.outils()}[nom], arguments)


def _maillons_bruts():
    with stockage.transaction() as cnx:
        return list(cnx.execute(select(REGISTRES.c.maillon).where(
            (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == REGISTRE_NOM)
        ).order_by(REGISTRES.c.rang)).scalars())


@pytest.mark.parametrize("nom,arguments", _LECTURES_ET_AJOUT)
def test_source_legacy_intacte_reste_lisible_et_peut_recevoir_un_ajout(base_durable, nom, arguments):
    assert _appeler_natif("m9_etat_consolide", {"snapshot": _SOURCE_FICTIVE})["resultat"]["accepte"]
    avant = _maillons_bruts()
    # Ancien format exact conservé, aucun champ/version ajouté au registre.
    assert set(codec.decoder(avant[0])) == {
        "index", "module_source", "horodatage", "valeurs", "hash_precedent", "hash_maillon"}
    reponse = _appeler_natif(nom, arguments)
    assert reponse["ok"] is True, reponse
    relue = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
    assert relue.valider_chaine() == (True, "")
    apres = _maillons_bruts()
    assert apres[0] == avant[0]
    if nom == "m9_etat_consolide":
        assert reponse["resultat"]["accepte"] and len(apres) == 2
    else:
        assert apres == avant and "100.00" in str(reponse)


@pytest.mark.parametrize("nom,arguments", _LECTURES_ET_AJOUT)
@pytest.mark.parametrize("malforme", [False, True])
def test_chaine_rompue_refuse_lecture_et_ajout_sans_fuite_ni_reparation(base_durable, nom, arguments, malforme):
    assert _appeler_natif("m9_etat_consolide", {"snapshot": _SOURCE_FICTIVE})["resultat"]["accepte"]
    filtre = ((REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == REGISTRE_NOM)
              & (REGISTRES.c.rang == 0))
    with stockage.transaction() as cnx:
        maillon = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
        maillon["valeurs"]["prevision"] = "999999.00-FICTIF-ALTERE"
        if malforme:
            del maillon["hash_maillon"]
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(maillon)))
    if not malforme:
        relue = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
        assert relue.valider_chaine()[0] is False
    avant = _maillons_bruts()
    reponse = _appeler_natif(nom, arguments)
    assert _maillons_bruts() == avant  # ni nouvelle charge, ni réparation, ni réécriture
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier", reponse
    assert reponse["details"].startswith("REJ-SNAPSHOT-CHAINE-INVALIDE")
    assert "999999.00" not in str(reponse) and "FICTIF-ALTERE" not in str(reponse)


@pytest.mark.parametrize("nom,arguments", _LECTURES_ET_AJOUT)
def test_autorisation_precede_validation_et_lecture_de_chaine(base_durable, nom, arguments):
    class RegistreInterdit:
        def valider_chaine(self):
            raise AssertionError("chaîne lue avant refus d'identité")

        def lire(self):
            raise AssertionError("registre lu avant refus d'identité")

        def ajouter(self, snapshot):
            raise AssertionError("registre écrit avant refus d'identité")

    natifs = {o.nom: o for o in outils.outils(registre_cible=RegistreInterdit(), alertes_cible=[])}
    with contexte.appele_par_appareil(IdentiteAppelante("employe-fictif", "employee")):
        reponse = executer_atomique(natifs[nom], arguments)
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier", reponse
    assert reponse["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE")


@pytest.mark.parametrize("nom,arguments", _LECTURES_ET_AJOUT[:3])
def test_lecture_restitue_la_copie_validee_si_la_source_change(base_durable, nom, arguments, monkeypatch):
    # Oracle local du même entrelacement que le contre-test PG : la validation
    # native réussit, puis la source change avant la restitution. Pas de cache
    # entre appels ; la lecture suivante doit constater la corruption.
    maillons = []
    source = registre.RegistreSnapshots(maillons=maillons)
    source.ajouter(_SOURCE_FICTIVE)
    natifs = {o.nom: o for o in outils.outils(registre_cible=source, alertes_cible=[])}
    originale = registre.RegistreSnapshots.valider_chaine

    def valider_puis_alterer(self):
        resultat = originale(self)
        assert resultat == (True, "")
        maillons[0]["valeurs"]["prevision"] = "900.00"
        return resultat

    monkeypatch.setattr(registre.RegistreSnapshots, "valider_chaine", valider_puis_alterer)
    reponse = executer_atomique(natifs[nom], arguments)
    assert reponse["ok"] is True
    assert "100.00" in str(reponse) and "900.00" not in str(reponse)
    monkeypatch.setattr(registre.RegistreSnapshots, "valider_chaine", originale)
    suivant = executer_atomique(natifs[nom], arguments)
    assert suivant["ok"] is False and suivant["erreur"] == "refus_metier"
    assert suivant["details"].startswith("REJ-SNAPSHOT-CHAINE-INVALIDE")
    assert "900.00" not in str(suivant)
    assert maillons[0]["valeurs"]["prevision"] == "900.00"  # aucune réparation
