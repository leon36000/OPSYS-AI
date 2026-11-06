"""Les deux vrais outils M6 passent par la porte d'appareil avant leur projection admin fermée."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from harnais_e2e import MOT_DE_PASSE, iso
from harnais_e2e_chantier import MATERIAU_ID, AppEmploye, preparer_chantier
from m6_material_control import livre_prix

from opsys import stockage
from opsys.console import application
from opsys.console.securite import Configuration


@pytest.mark.parametrize("avec_preuves", [False, True])
def test_les_declarations_reelles_sont_lues_sans_rejouer_ni_exposer_le_recu(equipe, moteur, avec_preuves):
    chantier = preparer_chantier(
        moteur.departements, suffixe=f"reconciliation-{avec_preuves}-fictif", technicien="etienne",
        debut=moteur.horloge.maintenant,
    )
    app_employe = AppEmploye(moteur, equipe["employe"], chantier, derive_appareil_s=0)
    fin = app_employe.journee_jusqu_a_la_completion()
    assert fin.metier["accepte"] is True
    moteur.drainer_bus(moteur.horloge.maintenant)

    if avec_preuves:
        with stockage.transaction():
            refus = livre_prix.enregistrer_prix(
                MATERIAU_ID, "fournisseur-reconciliation-fictif", 12.34, "CAD", "2026-01-01",
                stockage.maillons("m06-material-control", "livre_prix"), "DOC-RECONCILIATION-FICTIF", "pi",
            )[1]
            assert refus is None
        wct = fin.resultat["wct_id"]
        arguments = {
            "wct_id": wct,
            "formulaire": {
                "wct_id": wct,
                "intervention_id": chantier.intervention_id,
                "chantier_id": chantier.chantier_id,
                "lignes_materiaux": [{
                    "type_ligne": "perte", "materiau_id": MATERIAU_ID, "quantite": 1.0, "unite": "pi",
                }],
            },
            "preuves_lignes": [{"position_ligne": 0, "note": "Perte fictive vérifiée.", "photos": []}],
        }
        cle = "reconciliation-preuves-intention-fictive"
        declaration = equipe["employe"].appeler(
            "m6_declarer_materiaux_avec_preuves_appareil", arguments,
            cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant),
        )
    else:
        declaration = app_employe.declarer_materiaux(fin.resultat["wct_id"], 3.0)
        cle = app_employe.appels[-1].cle
    assert declaration.metier["accepte"] is True, declaration.corps

    console = application.creer_application(
        Configuration("secret-session-reconciliation-e2e-fictif-" + "x" * 32, cookie_securise=False),
        moteur.departements, stockage.transaction,
    )
    with TestClient(console, base_url="https://testserver/opsys") as client:
        login = client.post(
            "/connexion", data={"identifiant": "nathan", "mot_de_passe": MOT_DE_PASSE}, follow_redirects=False,
        )
        assert login.status_code == 303
        csrf = client.get("/api/session").json()["csrf"]
        response = client.post(
            "/api/m6/intention/etat",
            json={"appareil": equipe["employe"].appareil_id, "cle_idempotence": cle},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        assert response.json() == {"etat": "acceptee"}
        assert "cout_unitaire" not in response.text
        assert "hash_tete" not in response.text
        assert "preuves" not in response.text
