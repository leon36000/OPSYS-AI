"""Travailleurs MULTI-PROCESSUS du magasin de développement M10 et de ses jobs de consolidation
(`pg_concurrence.lancer`).

Chaque travailleur est un vrai processus `spawn`, avec sa connexion, qui attend l'instant de départ commun puis fait UN
geste de production : écrire un prompt dans le magasin, ou exécuter le job de consolidation. Données fictives."""

from __future__ import annotations

HORODATAGE = "2026-09-30T15:00:00+00:00"


def _admin():
    from opsys import contexte

    return contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.dev", "admin"))


def _ouvrir() -> None:
    from opsys import stockage

    with stockage.transaction() as cnx:
        cnx.exec_driver_sql("SELECT 1")


def ecrire_prompt(prompt_id: str, texte: str, version: int, attendre) -> tuple:
    from m10_memoire import developpement as dev

    _ouvrir()
    attendre()
    try:
        with _admin():
            resultat = dev.enregistrer_prompt(prompt_id, texte, version=version, module="M10", objectif="course",
                                              horodatage=HORODATAGE)
    except Exception as exc:  # noqa: BLE001 — l'issue typée est l'objet du test
        return ("refus", type(exc).__name__)
    return ("ok", bool(resultat.get("replayed")))


def executer_job(job_id: str, credential: str, attendre) -> tuple:
    from m10_memoire import consolidation_developpement as job

    _ouvrir()
    attendre()
    try:
        resultat = job.executer(job_id, credential)
    except Exception as exc:  # noqa: BLE001
        return ("refus", type(exc).__name__)
    return ("ok", resultat["status"], bool(resultat["replayed"]))
