"""Revue adverse (num) : l'empreinte d'une pièce justificative est EXACTEMENT 64 hexadécimaux minuscules.

Défaut trouvé : `lier_piece` validait le sha256 avec `^[0-9a-f]{64}$` et `.match` : `$` accepte un « \\n » final.
« <hash>\\n » passait, était stocké tel quel et comptait comme une empreinte DIFFÉRENTE de « <hash> » : le contrôle
« un reçu ne justifie qu'une dépense » (`reutilisee_ailleurs`) se contournait en ajoutant un saut de ligne, et la même
pièce se liait deux fois à la même opération (clé d'idempotence distincte). Données fictives.
"""

from __future__ import annotations

import pytest
from m5_financecore import operations_comptables as oc
from m5_financecore import operations_registre as ore
from m5_financecore import registre as registre_module

FICTIF = True
H = "2026-10-15T10:00:00-04:00"
SHA = "ab" * 32
CIBLES = {"depense_employe": ["dep-1", "dep-2"]}


def _lier(ops, sha=SHA, cible_id="dep-1"):
    return oc.lier_piece(
        ops, ore.etat_operations(ops.lire()), cible_type="depense_employe", cible_id=cible_id, cibles_connues=CIBLES,
        nom="recu.pdf", sha256=sha, taille=1234, lie_par="comptable", horodatage=H)


@pytest.mark.parametrize("sha", [SHA + "\n", SHA + "\r\n", SHA + " ", " " + SHA, "\n" + SHA, SHA[:-1], SHA + "a",
                                 SHA.upper(), "０" * 64, SHA[:-1] + "é", None, 123, b"ab" * 32])
def test_une_empreinte_qui_n_est_pas_exactement_64_hexadecimaux_est_refusee(sha):
    ops = registre_module.Registre()
    resultat, refus = _lier(ops, sha)
    assert resultat is None and refus["code"] == "REJ-OPS-PIECE-INVALIDE"
    assert ops.taille() == 0


def test_le_saut_de_ligne_final_ne_contourne_ni_la_reutilisation_ni_l_idempotence():
    ops = registre_module.Registre()
    assert _lier(ops)[1] is None
    reutilisee, refus = _lier(ops, cible_id="dep-2")
    assert refus is None and reutilisee["reutilisee_ailleurs"] == ["dep-1"]
    contournement, refus = _lier(ops, SHA + "\n", cible_id="dep-2")
    assert contournement is None and refus["code"] == "REJ-OPS-PIECE-INVALIDE"
    assert len(ore.etat_operations(ops.lire())["par_type"]["op_piece_liee"]) == 2


def test_une_empreinte_valide_reste_acceptee():
    ops = registre_module.Registre()
    liee, refus = _lier(ops, "0123456789abcdef" * 4)
    assert refus is None and liee["statut"] == "liee"


def test_les_references_et_identifiants_avec_saut_de_ligne_final_sont_refuses():
    """Même défaut pour la référence d'une note de crédit, l'identifiant d'employé et les dates : « NC-1\\n » ne devait
    pas pouvoir doubler « NC-1 » (clé d'idempotence distincte, même numéro affiché)."""
    from pathlib import Path

    from m5_financecore import grand_livre, plan_comptable, taux_fiscaux

    racine = Path(__file__).resolve().parents[1] / "contracts"
    plan, refus = plan_comptable.charger_plan(racine / "plan_comptable_pme_qc.v1.yaml")
    assert refus is None
    taux, erreurs = taux_fiscaux.charger_taux_fiscaux(racine / "taux_fiscaux.v1.yaml")
    assert erreurs == []

    def depense(ops, gl, **changes):
        args = {"employe_id": "emp-1", "reference": "R-1", "date_depense": "2026-10-04", "categorie": "carburant",
                "description": "plein d'essence camion", "montant_avant_taxes": "100.00", "taxable": True,
                "total_recu": "114.98", "compte_remboursement": "2200", "horodatage": H}
        args.update(changes)
        return oc.proposer_depense_employe(ops, ore.etat_operations(ops.lire()), gl, plan, taux, **args)

    for champ, valeur in (("employe_id", "emp-1\n"), ("reference", "R-1\n"), ("date_depense", "2026-10-04\n")):
        ops, gl = registre_module.Registre(), registre_module.Registre()
        resultat, refus = depense(ops, gl, **{champ: valeur})
        assert resultat is None and refus["code"] in ("REJ-OPS-ENTREE-INVALIDE", "REJ-OPS-DATE-INVALIDE"), champ
        assert ops.taille() == 0 and gl.taille() == 0
    ops, gl = registre_module.Registre(), registre_module.Registre()
    assert depense(ops, gl)[1] is None

    assert grand_livre._date("2026-10-01\n") is None and oc._date("2026-10-01\n") is None
    assert oc._date("2026-10-01") is not None and grand_livre._date("2026-10-01") is not None


def test_la_reference_d_une_note_de_credit_avec_saut_de_ligne_final_est_refusee():
    from pathlib import Path

    from m5_financecore import facturation, plan_comptable, taux_fiscaux

    racine = Path(__file__).resolve().parents[1] / "contracts"
    plan, _ = plan_comptable.charger_plan(racine / "plan_comptable_pme_qc.v1.yaml")
    taux, _ = taux_fiscaux.charger_taux_fiscaux(racine / "taux_fiscaux.v1.yaml")
    factures = registre_module.Registre()
    lignes = [{"description": "travaux (fictif)", "quantite": "1", "unite": "u", "prix_unitaire": "600.00",
               "reference_ligne_devis": "L1"}]
    assert facturation.creer_facture_brouillon(
        "F-1", "CH-1", "D-F-1", "client-1", lignes, "2026-09-01T09:00:00-04:00", taux, factures)[1] is None
    assert facturation.envoyer_facture("F-1", "2026-09-01T10:00:00-04:00", factures)[1] is None
    facture = facturation.facture_active_pour_devis(factures, "D-F-1")
    ops, gl = registre_module.Registre(), registre_module.Registre()

    def note(reference):
        return oc.proposer_note_credit(
            ops, ore.etat_operations(ops.lire()), gl, plan, taux, genre="client", facture=facture, reference=reference,
            montant_avant_taxes="100.00", date_effet="2026-09-10", motif="rabais", horodatage=H)

    resultat, refus = note("NC-1\n")
    assert resultat is None and refus["code"] == "REJ-OPS-ENTREE-INVALIDE" and ops.taille() == 0
    assert note("NC-1")[1] is None
