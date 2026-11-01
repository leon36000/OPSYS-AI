"""Revue adverse (coord-01) : le garde-fou de texte ne doit pas être contourné par des caractères invisibles ou des
homoglyphes. Un texte publié garde ces caractères : le lecteur voit « garantie » ou un numéro de téléphone que le
motif ne reconnaissait pas."""

from __future__ import annotations

import pytest

from opsys import garde_fou_texte as g

PROFIL = g.profil("revue_adverse", list(g.FAMILLES))


def _regles(texte: str) -> set[str]:
    return {v.regle for v in g.controler(texte, PROFIL)}


@pytest.mark.parametrize(("propre", "piege", "regle"), [
    ("Appelez le 514-555-1234", "Appelez le 514​-555-1234", "REJ-COORDONNEES"),
    ("Appelez le 514-555-1234", "Appelez le 5⁠14-555-1234", "REJ-COORDONNEES"),
    ("Seulement 99$ aujourd'hui", "Seulement 99​$ aujourd'hui", "REJ-PRIX"),
    ("C'est le meilleur choix", "C'est le meil​leur choix", "REJ-EXAGERATION"),
    ("C'est le meilleur choix", "C'est le meil­leur choix", "REJ-EXAGERATION"),
    ("C'est le meilleur choix", "C'est le meil‮leur choix", "REJ-EXAGERATION"),
    ("C'est le meilleur choix", "C'est le meil️leur choix", "REJ-EXAGERATION"),
    ("C'est le meilleur choix", "C'est le meil\U000e0041leur choix", "REJ-EXAGERATION"),
    ("C'est le meilleur choix", "C'est le meil\x00leur choix", "REJ-EXAGERATION"),
    ("Une garantie ferme", "Une garаntie ferme", "REJ-GARANTIE-NON-VALIDEE"),  # « а » cyrillique
    ("Écrivez à jean@example.test", "Écrivez à jean@exam​ple.test", "REJ-COORDONNEES"),
])
def test_le_texte_propre_est_refuse_et_le_texte_piege_aussi(propre: str, piege: str, regle: str) -> None:
    assert regle in _regles(propre)
    assert regle in _regles(piege), f"contourné par un caractère invisible ou un homoglyphe : {piege!r}"


def test_homoglyphe_cyrillique_dans_un_nom_de_client() -> None:
    assert "REJ-NOM-CLIENT" in _regles("Merci Monsieur Tremblay")
    assert "REJ-NOM-CLIENT" in _regles("Merci Monsieur Trеmblay")  # « е » cyrillique


def test_un_texte_legitime_reste_accepte() -> None:
    p = g.profil("seul", [g.COORDONNEES, g.PRIX_OFFRE, g.EXAGERATION, g.GARANTIE_NON_VALIDEE])
    assert g.controler("Nous réalisons des travaux soignés, avec le sourire.", p) == ()
    # Un accent, un emoji et une apostrophe courbe n'y changent rien.
    assert g.controler("Une équipe à l’écoute 😀", p) == ()


def test_les_formes_qui_gardent_la_casse_et_les_accents_sont_nettoyees_aussi() -> None:
    # `droit` (avis légal, engagements) et `normal` (noms propres, voies nommées) ne passent pas par `plier`.
    assert "REJ-INTERDIT-AVIS-LEGAL" in _regles("Vous avez le dr​oit de contester.")
    assert "REJ-INTERDIT-AVIS-LEGAL" in _regles("Vous avez le droit de contester.")
    assert "REJ-NOM-CLIENT" in _regles("Merci Monsieur Trem​blay")
    assert "REJ-ADRESSE" in _regles("Passez rue ​Desjardins")
    assert "REJ-ADRESSE" in _regles("Passez rue Desjardins")
