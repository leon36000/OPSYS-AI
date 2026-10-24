"""Choix opérateur explicites pour instances fictives des tests de configuration."""
from opsys import agents_base, identite


def provisionner_base_qa(cnx_factory, departements, *, budget_entreprise_jour=10_000_000,
                        budget_entreprise_mois=100_000_000):
    with cnx_factory() as cnx:
        if identite.personne_active(cnx, "base-admin-fictif") is None:
            identite.creer_personne(cnx, "base-admin-fictif", "Admin fictif",
                                   "mot-de-passe-qa-base-1234", ["admin"])
        return agents_base.provisionner(
            cnx, departements, par="base-admin-fictif", limite_tours=8,
            limite_reessais=2, limite_concurrence=1,
            budget_entreprise_jour=budget_entreprise_jour, budget_entreprise_mois=budget_entreprise_mois,
        )
