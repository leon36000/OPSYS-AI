"""Paquet du module M6-material-control.

Le nom de paquet est UNIQUE au dépôt (chore #109) : plusieurs modules exposent
des fichiers de même nom (contrats, registre, verdicts, digest, conformite...).
Sans identité de paquet, sys.modules conserve le premier chargé et
l'appartenance d'un fichier dépend de l'ordre de collecte des tests, pas de
son arbre. Le module NAÎT donc avec son paquet — les gardes structurelles
l'imposent dès la première story.
"""
