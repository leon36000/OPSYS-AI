"""Repository minimal (C05-003) — encapsulation générique de requêtes SQL
paramétrées sur la connexion d'une `UnitOfWork` (uow.py).

Volontairement réduit à UNE SEULE primitive générique (`executer`) :
aucune logique métier M1-M10, aucun mapping d'entité, aucun ORM
(« Implémentation strictement bornée » de tasks/C05-003.md — le spec ne
nomme aucune interface pour `Repository`, seul le mot « repositories »
apparaît dans le périmètre). Les repositories spécialisés (ex.
`LedgerStore`) viennent de tâches futures (C05-004+), hors périmètre ici
— un `Repository` avec de la logique métier serait une sortie qui
dépasse ce que cette tâche a le droit de construire.

Instancié PAR `UnitOfWork.repository()` — jamais construit directement
par l'appelant (le spec dit que l'UnitOfWork encapsule connexion ET
repositories, donc l'UnitOfWork possède, jamais l'inverse).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from opsys_core.persistence.uow import UnitOfWork


class Repository:
    """Point d'encapsulation générique de requêtes SQL paramétrées sur la
    connexion d'une `UnitOfWork` active. Couplage intentionnel et étroit
    à `UnitOfWork` (accès à ses attributs internes) : les deux classes
    forment une seule unité conceptuelle, séparée en 2 fichiers par les
    Sorties exactes de la tâche, pas 2 sous-systèmes indépendants."""

    def __init__(self, uow: "UnitOfWork") -> None:
        self._uow = uow

    def executer(
        self, sql: str, parametres: Sequence[object] | None = None
    ) -> list[tuple[object, ...]]:
        """Exécute `sql` avec des paramètres LIÉS (jamais d'interpolation
        de chaîne — même discipline que `_APPLICATION_NAME`/`options`
        dans connection.py, C05-001) sur la connexion de l'UnitOfWork
        propriétaire.

        Refuse si l'UnitOfWork n'est plus active (`UnitOfWorkFermee`,
        levée par `uow._verifier_active()`) : propriété réelle et
        testable — aucune écriture ne peut s'échapper de l'unité de
        travail après sa clôture.

        Retourne les lignes du résultat (`cur.fetchall()`) si la
        commande en produit un (SELECT, ou INSERT/UPDATE/DELETE avec
        RETURNING) ; une liste vide sinon (`cur.description is None` —
        commande sans jeu de résultats, ex. INSERT nu)."""
        self._uow._verifier_active()  # noqa: SLF001 — couplage intentionnel, cf. docstring de classe
        conn = self._uow._database.conn  # noqa: SLF001 — idem
        with conn.cursor() as cur:
            cur.execute(sql, parametres)
            if cur.description is None:
                return []
            return cur.fetchall()
