"""Rejeu PostgreSQL des notes d'achat M6 (console) + publication simultanée de la même référence, en vrais processus.

Défaut latent L10 du rapport de qualification PostgreSQL : deux publications simultanées de la même référence ne
produisaient qu'UNE référence sortante (le bus est idempotent) mais DEUX lignes d'audit `console.reference_note_m6`.
Corrigé par un verrou consultatif nommé pris avant la lecture de l'état (`notes_commande_memoire.publier`).
"""

from collections import Counter

from pg_concurrence import lancer, publier_reference_note
from pg_rejeu import installer, module
from sqlalchemy import func, select

from opsys.stockage.schema import JOURNAL

INJECTES = installer(globals(), "test_console_notes_commande.py")
notes = module("test_console_notes_commande.py")
N = 4


def test_n_processus_publient_la_meme_reference_une_seule_sortante_un_seul_audit(client, session):
    f = notes.preparer_reference(client, session)
    issues = lancer(publier_reference_note, [(f["source_hash"],)] * N)
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    assert Counter(i[0] for i in issues) == {"EN_ATTENTE": N}, issues  # tous rendent l'état validé par le premier
    assert len(notes.references_sortantes(session)) == 1
    with session() as cnx:
        assert cnx.execute(select(func.count()).select_from(JOURNAL).where(
            JOURNAL.c.action == "console.reference_note_m6")).scalar_one() == 1
