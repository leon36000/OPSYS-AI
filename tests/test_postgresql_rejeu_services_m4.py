"""Rejeu PostgreSQL : coût certifié M4 -> M5 (portée de livraison, politiques, relecture courante) — sans recalcul
isolé.

Le banc rejoue aussi la sonde `test_probe_preparation` dans trois de ses cas d'historique (`QA_CASE`) : ils appellent
`service_history_m4.lire_historique` (console admin) et la révocation d'une lecture, que le cas par défaut n'atteint pas.
"""

import pytest
from pg_rejeu import installer, module

INJECTES = installer(
    globals(),
    "test_qa_m4_core_m5.py",
    "test_reconciliateur_cout_certifie.py",
)
qa = module("test_qa_m4_core_m5.py")


@pytest.mark.parametrize("cas", ["v2_apres_tarif", "lecture_revocation", "historique_ancien"])
def test_la_sonde_m4_m5_dans_ses_cas_d_historique_sur_postgresql(
    cas, affaire, session, deposer_photo_test, catalogue, monkeypatch
):
    monkeypatch.setenv("QA_CASE", cas)
    qa.test_probe_preparation(affaire, session, deposer_photo_test, catalogue, monkeypatch)
