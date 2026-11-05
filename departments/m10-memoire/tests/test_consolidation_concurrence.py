"""Le chemin de consolidation public sérialise son test d'idempotence avant les lectures."""

from contextlib import contextmanager

from m10_memoire import outils


def test_consolider_prend_le_verrou_transactionnel_avant_la_relecture(monkeypatch):
    cnx = object()
    appels = []

    monkeypatch.setattr(outils.stockage, "connexion_courante", lambda: cnx)

    def verrou(connexion, nom):
        appels.append(("verrou", connexion, nom))

    def consolider(affaire_id, jour, horodatage, registre_evenements, registre_affaires):
        appels.append(("relecture_et_ecriture", affaire_id, jour))
        return {"ecrit": False, "deja_consolide": True, "fait": None, "verdict": None}

    monkeypatch.setattr(outils, "verrou_consultatif", verrou)
    monkeypatch.setattr(outils.consolidation, "consolider_affaire", consolider)

    resultat = outils.consolider_affaire("AFFAIRE-FICTIVE", "2026-09-15", "2026-09-16T00:00:00Z")

    assert resultat["deja_consolide"] is True
    assert appels == [
        ("verrou", cnx, "m10-consolidation-affaire"),
        ("relecture_et_ecriture", "AFFAIRE-FICTIVE", "2026-09-15"),
    ]


def test_consolider_direct_ouvre_une_transaction_et_garde_l_idempotence(monkeypatch):
    cnx = object()
    courant = {"cnx": None}
    appels = []

    monkeypatch.setattr(outils.stockage, "connexion_courante", lambda: courant["cnx"])

    @contextmanager
    def transaction():
        courant["cnx"] = cnx
        try:
            yield cnx
        finally:
            courant["cnx"] = None

    monkeypatch.setattr(outils.stockage, "transaction", transaction)
    monkeypatch.setattr(outils, "verrou_consultatif", lambda connexion, nom: appels.append((connexion, nom)))
    monkeypatch.setattr(
        outils.consolidation,
        "consolider_affaire",
        lambda *args: {"ecrit": False, "deja_consolide": True, "fait": None, "verdict": None},
    )

    resultat = outils.consolider_affaire("AFFAIRE-FICTIVE", "2026-09-15", "2026-09-16T00:00:00Z")

    assert resultat["deja_consolide"] is True
    assert appels == [(cnx, "m10-consolidation-affaire")]
    assert courant["cnx"] is None
