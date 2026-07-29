import yaml

__all__ = ["charger_fixture"]


def charger_fixture(chemin):
    """
    Charge un fichier YAML et vérifie qu'il contient exactement 'fictif: true'.
    Lève une exception REJ-FIXTURE-NON-FICTIVE dans tous les autres cas.
    """
    with open(chemin, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or data.get("fictif") is not True:
        raise Exception("REJ-FIXTURE-NON-FICTIVE")
    return data
