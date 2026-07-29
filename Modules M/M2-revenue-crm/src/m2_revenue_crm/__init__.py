"""Paquet du module M2-revenue-crm.

Le nom de paquet est UNIQUE au dépôt : plusieurs modules exposent des
fichiers de même nom (registre, verdicts, horodatage...). Sans identité de
paquet, sys.modules conserve le premier chargé et l'appartenance d'un
module dépend de l'ordre de collecte, pas de son arbre — mesuré :
trois collisions et 21 tests exerçant le code du module voisin sans
aucun signal.
"""
