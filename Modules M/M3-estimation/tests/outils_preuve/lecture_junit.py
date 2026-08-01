"""Lecture durcie des rapports JUnit produits par pytest, partagée par les batteries.

Ce module est destiné à être importé explicitement depuis son chemin de fichier ou après
l'ajout contrôlé de son dossier parent à ``sys.path`` ; il ne modifie jamais ``sys.path`` lui-même.
Il extrait exclusivement les identifiants des testcases JUnit portant un ``failure`` ou un
``error``, ainsi que les erreurs portées directement par une testsuite. L'analyse repose
directement sur ``xml.parsers.expat`` : aucune API ElementTree n'est utilisée, afin d'éviter les
constats statiques B405/B314 et de garder le contrôle des déclarations XML dangereuses.

Les DTD, déclarations d'entités et références d'entités externes sont refusées avant toute
expansion, ce qui protège notamment contre XXE et « billion laughs ». Un rapport absent,
inaccessible ou syntaxiquement invalide retourne un ensemble vide et peut journaliser le motif.
Cette fonction ne borne toutefois ni la taille d'un rapport XML licite, ni sa profondeur, ne
valide aucun schéma JUnit et ne garantit pas que le rapport fourni correspond à une exécution
particulière : cette responsabilité reste celle de l'appelant.
"""

import sys
from xml.parsers import expat


class _DTDRefusee(Exception):
    """Une déclaration de type de document a été rencontrée."""


class _EntiteRefusee(Exception):
    """Une déclaration ou référence d'entité a été rencontrée."""


class _ConfigurationExpatImpossible(Exception):
    """Les gardes expat nécessaires ne sont pas disponibles."""


def nom_balise(nom):
    """Retourne le nom local d'une balise XML expat, sans son espace de noms."""
    return nom.rsplit("}", 1)[-1]


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
    absents = [nom for nom in gestionnaires if not hasattr(parseur, nom)]
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


def _attribut(attributs, nom, defaut):
    """Lit explicitement un attribut optionnel sans supposer sa présence."""
    if nom in attributs:
        return attributs[nom]
    return defaut


def _analyse_durcie(chemin):
    """Analyse un rapport JUnit avec expat et retourne directement ses échecs."""
    parseur = expat.ParserCreate(namespace_separator="}")
    _configurer_gardes_expat(parseur)

    echecs = set()
    pile = []
    contextes_testcase = []

    def debut_element(nom, attributs):
        balise = nom_balise(nom)
        parent = pile[-1] if pile else None

        if balise in {"failure", "error"} and parent == "testsuite":
            nom_suite = _attribut(
                pile_attributs[-1],
                "name",
                "<collecte>",
            )
            echecs.add(f"{nom_suite}::{balise}")

        if balise in {"failure", "error"} and parent == "testcase":
            profondeur_testcase = len(pile)
            for contexte in reversed(contextes_testcase):
                if contexte["profondeur"] == profondeur_testcase:
                    contexte["en_echec"] = True
                    break

        pile.append(balise)
        pile_attributs.append(attributs)

        if balise == "testcase":
            contextes_testcase.append(
                {
                    "profondeur": len(pile),
                    "classe": _attribut(attributs, "classname", ""),
                    "nom": _attribut(attributs, "name", "<test sans nom>"),
                    "en_echec": False,
                }
            )

    def fin_element(nom):
        balise = nom_balise(nom)

        if balise == "testcase":
            contexte = contextes_testcase.pop()
            if contexte["en_echec"]:
                if contexte["classe"]:
                    echecs.add(f"{contexte['classe']}::{contexte['nom']}")
                else:
                    echecs.add(contexte["nom"])

        pile.pop()
        pile_attributs.pop()

    pile_attributs = []
    parseur.StartElementHandler = debut_element
    parseur.EndElementHandler = fin_element

    with open(chemin, "rb") as rapport:
        while True:
            fragment = rapport.read(65536)
            if not fragment:
                break
            parseur.Parse(fragment, False)

    parseur.Parse(b"", True)
    return echecs


def echecs_junit(chemin, journalisation=None):
    """Retourne les identifiants JUnit en échec, ou un ensemble vide si illisible.

    Les seules exceptions converties en ensemble vide décrivent réellement un rapport
    indisponible ou invalide. Les ``TypeError``, ``ValueError`` et ``UnicodeError`` ne sont pas
    interceptées : les masquer transformerait une erreur de programmation du lecteur en silence
    indiscernable d'un rapport illisible.
    """
    try:
        return _analyse_durcie(chemin)
    except FileNotFoundError:
        _journaliser(journalisation, "fichier absent", chemin)
        return set()
    except _DTDRefusee:
        _journaliser(journalisation, "DTD refusée", chemin)
        return set()
    except _EntiteRefusee:
        _journaliser(journalisation, "entité refusée", chemin)
        return set()
    except (_ConfigurationExpatImpossible, expat.ExpatError, OSError):
        _journaliser(journalisation, "analyse impossible", chemin)
        return set()
