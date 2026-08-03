"""Identité de paquet M8 (analytics) — patron #109.

Plusieurs modules du dépôt exposent des fichiers de même nom (`contrats`,
`registre`, `encodage`, `digest`, `conformite`) ; sans identité de paquet
propre, `sys.modules` ferait exercer aux tests de M8 le code d'un voisin en
silence.
"""
