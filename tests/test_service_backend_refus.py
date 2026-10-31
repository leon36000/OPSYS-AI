"""Un backend non qualifié ne reçoit aucune autorité de service."""

from types import SimpleNamespace

import pytest
from opsys import service_capability as sc


def test_postgresql_refuse_sans_emettre_capacite():
    cnx = SimpleNamespace(engine=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    portee = SimpleNamespace(cnx=cnx)
    token = sc._COURANTE.set(portee)
    try:
        with pytest.raises(sc.RefusAutorite, match="backend non qualifié"):
            sc.courante()
    finally:
        sc._COURANTE.reset(token)


def test_postgresql_refuse_revocation_sans_ecriture(monkeypatch):
    cnx = SimpleNamespace(
        engine=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")), get_transaction=lambda: object()
    )
    monkeypatch.setattr(sc, "connexion_courante", lambda: cnx)
    with pytest.raises(sc.RefusAutorite, match="backend non qualifié"):
        sc._revoquer(cnx, "instance-fictive", "m05-financecore")
