"""Racine de configuration pytest pour la suite M7 Marketing.

Historiquement, ce fichier ajoutait src/brand au sys.path pour permettre des imports
plats (import brand_schema). Toute la suite importe désormais explicitement depuis le
paquet unique m7_marketing (departments/m07-marketing/src déjà sur pythonpath via
pyproject.toml [tool.pytest.ini_options]) : plus aucun hack sys.path n'est nécessaire.
"""
