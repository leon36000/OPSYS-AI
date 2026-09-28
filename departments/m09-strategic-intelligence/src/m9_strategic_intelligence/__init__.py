"""Identité de paquet M9 (strategic-intelligence) — patron #109.

Plusieurs modules du dépôt exposent des fichiers de même nom (`contrats`,
`registre`, `encodage`, `validation`, `conformite`) ; sans identité de paquet
propre, `sys.modules` ferait exercer aux tests de M9 le code d'un voisin en
silence.
"""
