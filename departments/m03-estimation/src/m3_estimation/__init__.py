"""Paquet ``m3_estimation`` — module M3-estimation du dépôt.

Le nom de paquet ``m3_estimation`` est UNIQUE au dépôt (chore #109).
Plusieurs modules du dépôt exposent des fichiers de même nom (``contrats``,
``verdicts``, ``registre``) : sans identité de paquet propre, ``sys.modules``
conserve le premier module chargé sous un nom donné et les tests d'un module
exercent alors le code d'un autre, en silence. L'identité de paquet garantit
que ``m3_estimation.contrats`` ne désigne jamais que le ``contrats`` de M3,
et jamais celui d'un module voisin.

Ce fichier ne fait aucun import et ne ré-exporte rien : les sous-modules sont
importés explicitement par leur nom pleinement qualifié.
"""
