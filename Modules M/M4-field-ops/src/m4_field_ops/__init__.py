"""Paquet du module M4-field-ops.

Le nom de paquet est UNIQUE au dépôt (chore #109) : plusieurs modules exposent
des fichiers de même nom (registre, verdicts, horodatage...). Sans identité de
paquet, sys.modules conserve le premier chargé et l'appartenance d'un module
dépend de l'ordre de collecte, pas de son arbre. Le module NAÎT donc avec son
paquet — les gardes structurelles l'imposent dès la première story.
"""
