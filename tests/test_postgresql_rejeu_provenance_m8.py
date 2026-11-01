"""Rejeu PostgreSQL : lecture de provenance M5 vers M8 (cohorte bornée en un SELECT).

Défaut corrigé : les bornes 64 bits des entiers (`tentatives`, `rang`) étaient liées à une colonne INTEGER ; 2**63 débordait
(« integer out of range ») et la transaction PostgreSQL restait avortée. Les bornes sont maintenant des littéraux BigInteger.
"""

from pg_rejeu import installer

INJECTES = installer(
    globals(),
    "test_provenance_m8_lecture_atomique.py",
)
