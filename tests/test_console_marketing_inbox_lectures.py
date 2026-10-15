"""Lectures natives fictives : coût des historiques, fraîcheur et confidentialité."""

from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path

import pytest
from m7_marketing import outils
from sqlalchemy import inspect, update

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import PERSONNES

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "inbox_lectures_fictives", ROOT / "tests/test_console_marketing_marque_inbox.py",
)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client = f.client
console = f.console
base_sqlite = f.base_sqlite
FICTIF = True
OUTILS = {outil.nom: outil for outil in outils.outils()}
REGISTRES = {"reputation_avis", "reputation_decisions", "reputation_exports"}


def _lister(personne="owner-r44", role="admin", **arguments):
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(personne, role)):
        return executer_atomique(OUTILS["m7_lister_inbox_reputation"], arguments)


def _avis(reponse):
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]["avis"]


def _importer(console, cle, jour=28, *, prive=False):
    client, csrf, _ = console
    charge = {
        "action": "importer", "mutation_id": cle, "avis_source_id": cle,
        "plateforme": "google_business_profile", "date_avis": f"2026-09-{jour:02d}",
        "note": 1 if prive else 5,
        "texte": "Plainte fictive : remboursement demandé." if prive else "Excellent travail fictif.",
        "source_url": "https://exemple-fictif.ca/avis/" + cle,
    }
    return f.f._resultat(client.post("/api/marketing/avis", headers={"x-csrf-token": csrf}, json=charge))["avis_id"]


def _action(console, avis_id, action):
    client, csrf, _ = console
    return f.f._resultat(client.post("/api/marketing/avis", headers={"x-csrf-token": csrf}, json={
        "action": action, "avis_id": avis_id, "mutation_id": action + avis_id,
        **({"motif": "Révision fictive nécessaire"} if action == "rejeter" else {}),
    }))


def _snapshot():
    with stockage.transaction() as cnx:
        return {
            nom: sorted(codec.encoder(dict(ligne)) for ligne in cnx.exec_driver_sql(
                'SELECT * FROM "' + nom.replace('"', '""') + '"',
            ).mappings())
            for nom in sorted(inspect(cnx).get_table_names())
        }


def _mesurer(monkeypatch, **arguments):
    """Les observateurs délèguent entièrement aux vrais lecteurs et au vrai codec."""
    decodes, iterations = Counter(), Counter()
    actif = [None]
    original_iter, original_decoder = MaillonsDurables.__iter__, codec.decoder

    def decoder(texte):
        valeur = original_decoder(texte)
        if actif[0] is not None:
            decodes[actif[0]] += 1
        return valeur

    def iterer(self):
        precedent = actif[0]
        cible = self.departement == "m07-marketing" and self.registre in REGISTRES
        actif[0] = self.registre if cible else None
        if cible:
            iterations[self.registre] += 1
        try:
            return original_iter(self)
        finally:
            actif[0] = precedent

    avant = _snapshot()
    with monkeypatch.context() as m:
        m.setattr(codec, "decoder", decoder)
        m.setattr(MaillonsDurables, "__iter__", iterer)
        reponse = _lister(**arguments)
    assert _snapshot() == avant, "La consultation doit laisser toutes les tables inchangées"
    assert _lister(**arguments) == reponse, "L’observation ne doit pas changer le résultat"
    assert _snapshot() == avant
    return reponse, decodes, iterations


@pytest.mark.parametrize("taille", [8, 16])
@pytest.mark.parametrize("filtre", [{"categorie": "litige"}, {"statut": "REJETE"}])
def test_consultation_ne_redecode_pas_les_historiques_par_avis(console, monkeypatch, taille, filtre):
    """Attrape la relecture quadratique, sans prétendre fixer un budget de latence."""
    f._configurer(console)
    ids = []
    for indice in range(taille):
        avis_id = _importer(console, f"avis-volume-fictif-{indice}")
        assert _action(console, avis_id, "approuver")["statut"] == "APPROUVE"
        ids.append(avis_id)
    _action(console, ids[0], "exporter")
    reponse, decodes, iterations = _mesurer(monkeypatch, limite=1, **filtre)
    assert _avis(reponse) == []
    assert decodes["reputation_avis"] == taille
    assert decodes["reputation_decisions"] <= taille, dict(decodes)
    assert decodes["reputation_exports"] <= 1, dict(decodes)
    assert all(compte <= 1 for compte in iterations.values()), dict(iterations)


def test_tri_filtres_priorite_export_et_confidentialite_avant_limite(console, monkeypatch):
    f._configurer(console)
    propose = _importer(console, "propose-fictif", 26)
    exporte = _importer(console, "exporte-fictif", 27)
    rejete = _importer(console, "rejete-fictif", 28)
    prive = _importer(console, "prive-fictif", 29, prive=True)
    _action(console, exporte, "approuver")
    _action(console, exporte, "exporter")
    _action(console, rejete, "rejeter")
    _action(console, prive, "approuver")
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "employe-fictif", "Employé fictif", f.f.PASSWORD, ["employee"])
    reponse, _, _ = _mesurer(monkeypatch, limite=100)
    assert [(a["avis_id"], a["statut"]) for a in _avis(reponse)] == [
        (prive, "APPROUVE_PRIVE"), (rejete, "REJETE"), (exporte, "EXPORTE_MANUEL"), (propose, "PROPOSE"),
    ]
    employee, _, _ = _mesurer(monkeypatch, personne="employe-fictif", role="employee", limite=2)
    assert [(a["avis_id"], a["statut"]) for a in _avis(employee)] == [
        (rejete, "REJETE"), (exporte, "EXPORTE_MANUEL"),
    ]
    assert "Plainte fictive" not in str(employee) and "prive-fictif" not in str(employee)
    assert _avis(_lister(categorie="litige", statut="APPROUVE_PRIVE"))[0]["avis_id"] == prive
    assert _avis(_lister(statut="APPROUVE")) == []  # L’export prime sur l’approbation.
    assert [a["avis_id"] for a in _avis(_lister(limite=1))] == [prive]


def test_premiere_decision_historique_reste_prioritaire(console):
    """Un ancien historique ambigu fictif conserve la lecture du premier maillon."""
    f._configurer(console)
    avis_id = _importer(console, "historique-fictif")
    _action(console, avis_id, "approuver")
    with stockage.transaction():
        registre = stockage.maillons("m07-marketing", "reputation_decisions")
        premiere = list(registre)[0]
        registre.append({**premiere, "decision": "REJETE", "motif": "Ancienne ambiguïté fictive"})
    avant = _snapshot()
    assert _avis(_lister())[0]["statut"] == "APPROUVE"
    assert _avis(_lister(statut="REJETE")) == []
    assert _snapshot() == avant


def test_page_deja_exportee_ne_charge_pas_les_decisions_inutiles(console, monkeypatch):
    f._configurer(console)
    avis_id = _importer(console, "export-prioritaire-fictif")
    _action(console, avis_id, "approuver")
    _action(console, avis_id, "exporter")
    reponse, decodes, iterations = _mesurer(monkeypatch, limite=1)
    assert [(a["avis_id"], a["statut"]) for a in _avis(reponse)] == [(avis_id, "EXPORTE_MANUEL")]
    assert decodes["reputation_avis"] == decodes["reputation_exports"] == 1
    assert decodes["reputation_decisions"] == iterations["reputation_decisions"] == 0


def test_deux_consultations_relisent_decision_export_et_identite_courants(console, monkeypatch):
    f._configurer(console)
    avis_id = _importer(console, "fraicheur-fictive")
    assert _avis(_lister())[0]["statut"] == "PROPOSE"
    _action(console, avis_id, "approuver")
    assert _avis(_lister())[0]["statut"] == "APPROUVE"
    _action(console, avis_id, "exporter")
    assert _avis(_lister())[0]["statut"] == "EXPORTE_MANUEL"
    with stockage.transaction() as cnx:
        cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == "owner-r44").values(actif=False))
    reponse, decodes, iterations = _mesurer(monkeypatch)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-REQUIS"
    assert decodes == iterations == {}  # Aucun historique privé lu après révocation.
