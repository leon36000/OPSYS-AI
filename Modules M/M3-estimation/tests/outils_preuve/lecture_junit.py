"""Lecture durcie des rapports JUnit produits par pytest, partagée par les batteries.

Cette fonction existait à l'identique dans les cinq batteries de mutation. `bandit` la
signalait cinq fois (B314, MEDIUM) : l'analyse XML non durcie est classée VULNERABILITY par
les analyseurs statiques, et une seule vulnérabilité suffit à faire tomber la note de sécurité.
Elle est extraite ici pour être durcie UNE fois.

On n'extrait QUE la lecture, jamais la logique de mutation. Chaque batterie garde son propre
extracteur textuel `_echecs_sortie` et continue d'unir les deux résultats : si cette lecture
partagée devenait défaillante, l'extracteur textuel de chaque batterie tient encore, et le cas
où les deux rendent le vide sur une suite rouge reste signalé comme ROUGE NON ATTRIBUABLE.
La redondance qui protège réellement est donc préservée ; seule la copie inutile disparaît.

CE QUE LE DURCISSEMENT FERME. Trois gestionnaires expat refusent respectivement les
déclarations de type de document, les déclarations d'entité et les références d'entité
externes. Cela ferme l'expansion d'entités externes (lecture d'un fichier local ou d'une URL
via `SYSTEM`) et l'expansion récursive dite « billion laughs ». Vérifié par mesure sur des
charges réelles des deux familles : refus, ensemble vide, motif écrit sur la sortie d'erreur.

CE QU'IL NE FERME PAS, et qu'il faut savoir. Un rapport légitime mais énorme reste chargé
intégralement en mémoire — aucune borne de taille n'est posée. Une imbrication profonde sans
aucune entité n'est pas refusée. Et surtout : cette lecture ne vérifie PAS que le rapport
correspond bien à l'exécution qu'on croit mesurer ; c'est à l'appelant de le garantir par le
chemin temporaire qu'il fournit.

LE SILENCE EST RENDU VISIBLE. Un rapport illisible donne un ensemble VIDE — contrat conservé
des appelants, qui unissent avec leur extracteur textuel. Mais le motif exact est écrit sur la
sortie d'erreur : un instrument peut rendre un résultat neutre, il ne doit pas le faire sans
le dire. Si les gestionnaires expat attendus n'existaient pas dans l'interpréteur, la
configuration ÉCHOUE bruyamment plutôt que d'analyser sans protection.
"""

import sys
import xml.etree.ElementTree as ET
from xml.parsers import expat


class _DTDRefusee(Exception):
    """Une déclaration de type de document a été rencontrée."""


class _EntiteRefusee(Exception):
    """Une déclaration ou référence d'entité a été rencontrée."""


class _ConfigurationExpatImpossible(Exception):
    """Les gardes expat nécessaires ne sont pas disponibles."""


def nom_balise(element):
    """Retourne le nom local d'une balise XML, sans son espace de noms."""
    return element.tag.rsplit("}", 1)[-1]


def _refuser_dtd(*_arguments):
    raise _DTDRefusee()


def _refuser_entite(*_arguments):
    raise _EntiteRefusee()


def _configurer_gardes_expat(parseur):
    """Configure les gestionnaires expat qui interdisent DTD et entités."""
    gestionnaires = {
        "StartDoctypeDeclHandler": _refuser_dtd,
        "EntityDeclHandler": _refuser_entite,
        "ExternalEntityRefHandler": _refuser_entite,
    }

    absents = [
        nom for nom in gestionnaires
        if not hasattr(parseur, nom)
    ]
    if absents:
        raise _ConfigurationExpatImpossible(
            "gestionnaire(s) expat absent(s) : " + ", ".join(absents)
        )

    for nom, gestionnaire in gestionnaires.items():
        setattr(parseur, nom, gestionnaire)


def _journaliser(journalisation, motif, chemin):
    if journalisation is None or journalisation is False:
        return

    sortie = sys.stderr if journalisation is True else journalisation
    sortie.write(f"lecture_junit : {motif} : {chemin}\n")


def _analyse_durcie(chemin):
    """Analyse un rapport sans transmettre DTD ni entités à ElementTree."""
    analyseur_expat = expat.ParserCreate()
    _configurer_gardes_expat(analyseur_expat)

    analyseur_xml = ET.XMLParser()

    # Le XMLParser accéléré de CPython ne publie pas son parseur expat interne :
    # contrairement à l'implémentation Python pure, il n'expose pas forcément
    # l'attribut ``parser``. On vérifie donc réellement son existence avant de
    # l'utiliser, sans supposer un attribut privé ou un nom imaginaire.
    #
    # Quand cet attribut est disponible, les mêmes gardes sont posées aussi sur
    # le parseur interne d'ElementTree. Quand il ne l'est pas, l'analyseur expat
    # indépendant ci-dessus valide chaque fragment AVANT sa remise à XMLParser.
    # Ainsi, aucune DTD ni entité refusée n'atteint ElementTree.
    parseur_interne = getattr(analyseur_xml, "parser", None)
    if parseur_interne is not None:
        _configurer_gardes_expat(parseur_interne)

    with open(chemin, "rb") as rapport:
        while True:
            fragment = rapport.read(65536)
            if not fragment:
                break
            analyseur_expat.Parse(fragment, False)
            analyseur_xml.feed(fragment)

    analyseur_expat.Parse(b"", True)
    return analyseur_xml.close()


def echecs_junit(chemin, journalisation=True):
    """Retourne les identifiants JUnit en échec, ou un ensemble vide si illisible.

    Les DTD et déclarations d'entités sont refusées avant tout traitement par
    ElementTree. Cette garde ferme l'expansion d'entités externes et l'expansion
    récursive dite « billion laughs ».

    Elle ne couvre pas les consommations de ressources dues à un document XML
    licite mais volumineux ou très profond, ni la validation métier, de schéma,
    ou la confiance accordée au contenu d'un rapport valide.
    """
    try:
        racine = _analyse_durcie(chemin)
    except FileNotFoundError:
        _journaliser(journalisation, "fichier absent", chemin)
        return set()
    except _DTDRefusee:
        _journaliser(journalisation, "DTD refusée", chemin)
        return set()
    except _EntiteRefusee:
        _journaliser(journalisation, "entité refusée", chemin)
        return set()
    except (
        _ConfigurationExpatImpossible,
        ET.ParseError,
        expat.ExpatError,
        IsADirectoryError,
        OSError,
        PermissionError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        _journaliser(journalisation, "analyse impossible", chemin)
        return set()

    echecs = set()
    for cas in racine.iter():
        if nom_balise(cas) != "testcase":
            continue
        if not any(
            nom_balise(enfant) in {"failure", "error"}
            for enfant in cas
        ):
            continue
        classe = cas.attrib.get("classname", "")
        nom = cas.attrib.get("name", "<test sans nom>")
        echecs.add(f"{classe}::{nom}" if classe else nom)

    for suite in racine.iter():
        if nom_balise(suite) != "testsuite":
            continue
        for enfant in suite:
            if nom_balise(enfant) in {"failure", "error"}:
                echecs.add(
                    f"{suite.attrib.get('name', '<collecte>')}::"
                    f"{nom_balise(enfant)}"
                )

    return echecs
