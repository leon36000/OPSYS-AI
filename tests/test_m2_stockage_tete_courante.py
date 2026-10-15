"""Une écriture interposée ne peut faire accepter une ancienne tête M2."""

import pytest
from m2_revenue_crm.registre import Registre

from opsys import stockage
from opsys.stockage.maillons import EcritureConcurrente, MaillonsDurables


def test_maillon_m2_prepare_avant_ecriture_interposee_est_refuse(session, monkeypatch):
    original = MaillonsDurables.append
    interposee = False

    def ajouter_b(self, maillon, *, rang_attendu=None):
        nonlocal interposee
        if self.departement == "m02-revenue-crm" and self.registre == "principal" and not interposee:
            interposee = True
            # Vrai producteur et véritable INSERT, après construction du maillon A.
            Registre(stockage.maillons("m02-revenue-crm", "principal")).ajouter({
                "type_entree": "interaction", "horodatage": "2026-10-15T08:00:00-04:00",
                "lead_id": "lead-tete-fictif", "resume": "Interaction B FICTIVE",
            })
        return original(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", ajouter_b)
    with session():
        journal = Registre(stockage.maillons("m02-revenue-crm", "principal"))
        refus = None
        try:
            journal.ajouter({
                "type_entree": "interaction", "horodatage": "2026-10-15T08:01:00-04:00",
                "lead_id": "lead-tete-fictif", "resume": "Interaction A FICTIVE",
            })
        except EcritureConcurrente as exc:
            refus = exc
        courant = Registre(stockage.maillons("m02-revenue-crm", "principal"))
        assert courant.valider_chaine(), "CHAINE_M2: un ancien précédent a été accepté"
        assert refus is not None, "le maillon construit avant B doit être refusé"
        assert courant.taille() == 1
        assert courant.lire()[0]["resume"] == "Interaction B FICTIVE"


@pytest.mark.parametrize("niveau", ["REPEATABLE READ", "SERIALIZABLE", "READ UNCOMMITTED"])
def test_garde_refuse_isolement_pg_non_qualifie_avant_sql(session, monkeypatch, niveau):
    """Oracle unitaire de sélection du mode, sans prétendre exécuter PostgreSQL.

    La connexion/transaction est réelle ; seul le niveau déclaré du backend est
    interposé. La sentinelle interdit toute requête avant le refus du mode.
    Les propriétés PostgreSQL réelles sont réservées aux contre-tests natifs CI.
    """
    from opsys.stockage.maillons import _verrouiller_m2_principal

    with session() as cnx, monkeypatch.context() as interposition:
        interposition.setattr(cnx.dialect, "name", "postgresql")
        interposition.setattr(cnx, "get_isolation_level", lambda: niveau)

        def requete_interdite(*args, **kwargs):
            raise AssertionError("requête tentée avant le refus d'un isolement non qualifié")

        interposition.setattr(cnx, "execute", requete_interdite)
        with pytest.raises(ValueError, match="READ COMMITTED"):
            _verrouiller_m2_principal(cnx, partage=True)
