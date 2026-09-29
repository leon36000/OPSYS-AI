"""Registre durable (ADR-0009) : mêmes garanties qu'en mémoire, sur `opsys.stockage`.

Le module pur `registre.py` ignore `opsys` : il ne voit dans `maillons` qu'un objet qui se
comporte comme une liste (voir son docstring de constructeur). Ce fichier prouve que brancher
`Registre` sur `opsys.stockage.maillons("m02-revenue-crm", ...)` — le registre de production,
actif dès le chargement de `outils.py` — ne change ni les identifiants ni le
comportement de validation face à un registre en mémoire, que l'état survit à une nouvelle
instance Python (donc à un redémarrage de processus), et que la détection d'altération résiste
à une écriture SQL directe qui contourne complètement l'API Python du registre.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from m2_revenue_crm import outils, registre
from sqlalchemy import update

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

_DEPARTEMENT = "m02-revenue-crm"
_NOM_REGISTRE = "principal"

# Trois maillons représentatifs d'un cycle de vie réel de lead — mêmes types d'entrée et mêmes
# formes que ingestion.py/statuts.py/interactions.py (dict imbriqué, booléen, chaînes) : c'est
# le contenu réel que le registre de production doit conserver, pas une fixture synthétique.
_ENTREE_INGESTION = {
    "type_entree": "lead_ingere",
    "horodatage": "2026-06-15T09:00:00+00:00",
    "lead_id": "DUR-1",
    "contrat": {
        "lead_id": "DUR-1",
        "conversation_id": "conv-DUR-1",
        "contact": {
            "nom": "Client Durable",
            "telephone": "418-555-0101",
            "courriel": "durable@example.test",
        },
        "type_travaux": "renovation_totale",
        "ville": "Québec",
        "urgence_declaree": True,
        "canal": "telephone",
    },
    "empreinte_contrat": "peu-importe-ici",
    "statut": "nouveau",
}
_ENTREE_TRANSITION = {
    "type_entree": "transition_statut",
    "horodatage": "2026-06-15T09:30:00+00:00",
    "lead_id": "DUR-1",
    "statut": "qualifie",
    "statut_precedent": "nouveau",
    "owner": "Alice",
    "prochaine_action": {"description": "Appeler le client", "echeance": "2026-06-20T09:00:00+00:00"},
}
_ENTREE_INTERACTION = {
    "type_entree": "interaction",
    "horodatage": "2026-06-15T10:00:00+00:00",
    "lead_id": "DUR-1",
    "auteur": "Alice",
    "resume": "Appel de suivi effectué",
}
_ENTREES = (_ENTREE_INGESTION, _ENTREE_TRANSITION, _ENTREE_INTERACTION)


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire et migrée, libérée en fin de test (patron de tests/test_stockage.py)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _remplir(cible: registre.Registre) -> None:
    for entree in _ENTREES:
        cible.ajouter(entree)


class TestRegistreDurableEquivautAuRegistreMemoire:
    def test_memoire_et_durable_produisent_les_memes_identifiants(self, base_durable):
        r_memoire = registre.Registre()
        _remplir(r_memoire)

        r_durable = registre.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        with stockage.transaction():
            _remplir(r_durable)

        assert r_durable.lire() == r_memoire.lire(), (
            "un registre durable doit produire exactement les mêmes maillons (ligne_id, "
            "precedent_ligne_id, contenu) qu'un registre en mémoire pour les mêmes entrées : "
            "le passage par la base (codec JSON typé) ne doit rien changer au contenu ni au "
            "chaînage"
        )
        assert r_durable.tete() == r_memoire.tete()
        assert r_durable.valider_chaine() is True
        assert r_durable.valider_chaine(ancre=r_memoire.tete()) is True

    def test_lire_rend_une_vraie_liste(self, base_durable):
        r = registre.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        with stockage.transaction():
            _remplir(r)
        assert type(r.lire()) is list

    def test_valide_apres_relecture_par_une_nouvelle_instance(self, base_durable):
        r = registre.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        with stockage.transaction():
            _remplir(r)
        tete_attendue = r.tete()

        # Nouvelle instance Python, aucun état partagé avec `r` (pas même le module) : simule un
        # nouveau processus qui relit le registre depuis la base après un redémarrage — la
        # preuve centrale de la persistance exigée par l'audit M2.
        relu = registre.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        assert relu is not r
        assert relu.taille() == 3
        assert relu.tete() == tete_attendue
        assert relu.lire() == r.lire()
        assert relu.valider_chaine() is True
        relu.assert_chaine(ancre=tete_attendue)  # ne lève pas

    def test_alteration_directe_en_base_est_detectee(self, base_durable):
        r = registre.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        with stockage.transaction():
            _remplir(r)
        maillon_milieu = r.lire()[1]

        # Falsification hors API Python : UPDATE SQL direct de la ligne du maillon du milieu,
        # comme le ferait un accès base non contrôlé (contournement complet de Registre/
        # MaillonsDurables). Le contenu métier change, le ligne_id stocké ne bouge pas :
        # exactement la mutation que valider_chaine doit repérer au recalcul par maillon.
        falsifie = dict(maillon_milieu, owner="INJECTE")
        with stockage.transaction() as cnx:
            resultat = cnx.execute(
                update(REGISTRES)
                .where(
                    (REGISTRES.c.departement == _DEPARTEMENT)
                    & (REGISTRES.c.registre == _NOM_REGISTRE)
                    & (REGISTRES.c.rang == 1)
                )
                .values(maillon=codec.encoder(falsifie))
            )
            assert resultat.rowcount == 1, "l'UPDATE de preuve doit toucher exactement une ligne"

        relu = registre.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        assert relu.valider_chaine() is False, (
            "une altération directe en base (hors API Python) doit invalider la chaîne relue"
        )
        with pytest.raises(registre.VerificationError, match="incohérent"):
            relu.assert_chaine()


class TestAdaptateurOutils:
    """`outils.py` est l'adaptateur : lui seul connaît `opsys.stockage` (règle 3 du mandat)."""

    def test_utiliser_stockage_durable_persiste_entre_deux_instances(self, base_durable):
        outils.reinitialiser_registre()
        try:
            outils.utiliser_stockage_durable()
            reg1 = outils._obtenir_registre()
            with stockage.transaction():
                reg1.ajouter(dict(_ENTREE_INGESTION))

            # Un deuxième appel obtient une instance FRAÎCHE (aucun cache, comme
            # `opsys.stockage.maillons`) : elle doit pourtant voir l'écriture faite via la
            # première, car c'est la base qui porte l'état, jamais l'objet Python.
            reg2 = outils._obtenir_registre()
            assert reg2 is not reg1
            maillons = reg2.lire()
            assert len(maillons) == 1
            maillon = maillons[0]
            assert maillon["precedent_ligne_id"] is None
            assert isinstance(maillon["ligne_id"], str) and maillon["ligne_id"]
            for cle, valeur in _ENTREE_INGESTION.items():
                assert maillon[cle] == valeur
            assert reg2.valider_chaine() is True
        finally:
            outils.reinitialiser_registre()

    def test_au_chargement_le_registre_est_durable_sans_toucher_la_base(self, tmp_path):
        # Processus neuf : l'état du module n'a été modifié par aucun test.
        base = tmp_path / "jamais-ouverte.db"
        code = ("import m2_revenue_crm.outils as o; "
                "assert o._stockage_durable_actif is True, 'registre de production en mémoire'")
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path),
               stockage.ENV_URL: f"sqlite:///{base}"}
        resultat = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        assert resultat.returncode == 0, resultat.stderr
        assert not base.exists(), "le chargement du module ne doit ouvrir aucune base"

    def test_reinitialiser_registre_revient_a_la_memoire(self, base_durable):
        outils.reinitialiser_registre()
        try:
            outils.utiliser_stockage_durable()
            with stockage.transaction():
                outils._obtenir_registre().ajouter(dict(_ENTREE_INGESTION))
        finally:
            outils.reinitialiser_registre()

        # De retour en mode test : un registre en mémoire neuf, sans la donnée écrite en base.
        assert outils._obtenir_registre().taille() == 0
        assert outils._obtenir_registre() is outils._obtenir_registre(), (
            "en mémoire, _obtenir_registre() doit toujours retourner le même singleton partagé "
            "d'un appel à l'autre : c'est le patron existant, requis par les tests unitaires "
            "actuels du département (plusieurs appels d'outils successifs doivent voir le même "
            "état partagé)."
        )
