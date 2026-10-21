import yaml

__all__ = ["FixtureNonFictive", "charger_fixture"]


class FixtureNonFictive(Exception):
    """
    Levée par charger_fixture lorsque le fichier chargé ne porte pas
    exactement le marqueur 'fictif: true'.

    Une Exception nue forcerait l'appelant à écrire 'except Exception', ce
    qui masquerait toutes les autres fautes ; cette classe dédiée rend le
    refus attrapable précisément. Elle reste sous-classe d'Exception pour ne
    pas casser les tests existants qui font pytest.raises(Exception).
    """


def charger_fixture(chemin):
    """
    Charge un fichier YAML et vérifie qu'il contient exactement 'fictif: true'.
    Lève FixtureNonFictive (code stable REJ-FIXTURE-NON-FICTIVE) dans tous les
    autres cas, avec un détail actionnable indiquant ce qui a été trouvé à la
    place : document non-dict, marqueur absent, ou valeur effective du
    marqueur telle qu'elle apparaît, avec son type.
    """
    with open(chemin, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise FixtureNonFictive(
            "REJ-FIXTURE-NON-FICTIVE : document YAML non-dict, "
            f"type obtenu {type(data).__name__}, valeur {data!r}"
        )
    if "fictif" not in data:
        raise FixtureNonFictive(
            "REJ-FIXTURE-NON-FICTIVE : marqueur 'fictif' absent, "
            f"clés présentes {sorted(data, key=repr)!r}"
        )
    valeur = data.get("fictif")
    if valeur is not True:
        raise FixtureNonFictive(
            "REJ-FIXTURE-NON-FICTIVE : marqueur 'fictif' différent de true, "
            f"valeur {valeur!r} de type {type(valeur).__name__}"
        )
    return data
