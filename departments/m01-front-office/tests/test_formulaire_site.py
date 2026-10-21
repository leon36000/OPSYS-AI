"""PLAN T4.17-e3 — l'extrait de formulaire que le propriétaire colle sur son site (`site/formulaire-demande.html`).

Rien n'est publié : c'est un fichier du dépôt. Ces tests lisent le fichier tel qu'il sera collé (analyseur HTML de la
bibliothèque standard, aucun navigateur) et gardent ce qui doit rester vrai : les clés que le script recopie sont
exactement celles du contrat de lead v2 ; le script recopie la valeur telle quelle, sans la transformer ni la compléter,
et ne garde rien ; il n'appelle aucun autre site ; le formulaire refuse de partir tant que l'adresse de son récepteur
n'est pas posée ; les champs sont ceux que M1 attend d'un formulaire. Le comportement du script a été vérifié une
fois, à la main, avec un faux DOM et le vrai `URLSearchParams` : ce qui suit garde sa forme, pas son exécution.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from m1_front_office import contrats

M1 = Path(__file__).resolve().parents[1]
RACINE = M1.parents[1]
FICHIER = M1 / "site" / "formulaire-demande.html"
DOC = RACINE / "docs" / "departements" / "M1-canaux.md"


class _Lecteur(HTMLParser):
    """Ce que le fichier déclare : le formulaire, ses champs, le script et les commentaires."""

    def __init__(self) -> None:
        super().__init__()
        self.formulaires: list[dict[str, str | None]] = []
        self.champs: list[dict[str, str | None]] = []
        self.scripts: list[str] = []
        self.commentaires: list[str] = []
        self.attributs_src: list[str] = []
        self._dans_script = False

    def handle_starttag(self, balise, attributs):
        dico = dict(attributs)
        if balise == "form":
            self.formulaires.append(dico)
        elif balise in ("input", "textarea", "select"):
            self.champs.append({"balise": balise, **dico})
        elif balise == "script":
            self._dans_script = True
            self.scripts.append("")
        if "src" in dico:
            self.attributs_src.append(dico["src"] or "")

    def handle_endtag(self, balise):
        if balise == "script":
            self._dans_script = False

    def handle_data(self, donnees):
        if self._dans_script:
            self.scripts[-1] += donnees

    def handle_comment(self, donnees):
        self.commentaires.append(donnees)


@pytest.fixture(scope="module")
def lecture() -> _Lecteur:
    lecteur = _Lecteur()
    lecteur.feed(FICHIER.read_text(encoding="utf-8"))
    lecteur.close()
    return lecteur


@pytest.fixture(scope="module")
def script(lecture) -> str:
    assert len(lecture.scripts) == 1, "un seul script : ce que le propriétaire colle se relit d'un regard"
    return lecture.scripts[0]


def test_le_fichier_existe_et_est_en_francais_sans_donnee_reelle():
    texte = FICHIER.read_text(encoding="utf-8")
    assert FICHIER.is_file() and "Envoyer ma demande" in texte
    assert not re.search(r"https?://", texte), "aucune adresse, aucun site tiers : rien de réel n'est écrit ici"
    assert not re.search(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b", texte), "aucun numéro de téléphone"


def test_le_formulaire_envoie_en_post_a_une_adresse_que_le_proprietaire_doit_remplacer(lecture):
    (formulaire,) = lecture.formulaires
    assert formulaire["id"] == "demande-soumission" and formulaire["method"] == "post"
    assert formulaire["action"].startswith("REMPLACER"), "l'adresse n'est jamais inventée : elle est à remplacer"


def test_les_champs_sont_ceux_que_m1_attend_d_un_formulaire(lecture):
    par_nom = {c["name"]: c for c in lecture.champs}
    assert set(par_nom) == {"nom", "courriel", "telephone", "message"}
    # Un attribut booléen (`required`) vaut `None` pour l'analyseur : c'est sa PRÉSENCE qui compte, jamais sa valeur.
    assert par_nom["courriel"]["type"] == "email" and "required" in par_nom["courriel"]
    assert par_nom["message"]["balise"] == "textarea" and "required" in par_nom["message"]
    assert "required" not in par_nom["nom"] and "required" not in par_nom["telephone"]
    assert all(c.get("type") != "checkbox" for c in lecture.champs), "aucune case, aucun consentement précoché"


def test_aucun_champ_utm_n_est_ecrit_dans_la_page_le_script_les_cree_seulement_quand_ils_existent(lecture):
    """Un champ vide serait envoyé comme `utm_source=` : une valeur vide que M2 refuse. Créés au besoin."""
    assert not [c for c in lecture.champs if (c.get("name") or "").startswith("utm_")]
    assert not [c for c in lecture.champs if c.get("type") == "hidden"]


def test_le_script_recopie_exactement_les_cles_du_contrat_de_lead(script):
    trouve = re.search(r"var CLES_UTM = \[([^\]]*)\];", script)
    assert trouve is not None, "la liste des clés est déclarée une fois, en tête du script"
    cles = re.findall(r'"([^"]+)"', trouve.group(1))
    assert cles == list(contrats._CLES_UTM), "mêmes clés, même ordre que le contrat gelé v2 et que M2"


def test_le_script_lit_l_adresse_de_la_page_et_recopie_la_valeur_telle_quelle(script):
    assert "new URLSearchParams(window.location.search)" in script
    assert "parametres.get(cle)" in script and "champ.value = valeur;" in script
    assert 'champ.type = "hidden";' in script and "champ.name = cle;" in script
    garde_absent_ou_vide = 'if (valeur === null || valeur === "") { return; }'
    assert garde_absent_ou_vide in script, "absent ou vide : aucun champ, jamais une valeur par défaut"
    for transformation in (".trim(", ".toLowerCase(", ".toUpperCase(", ".replace(", "encodeURI", "decodeURI", ".slice(",
                           ".substring(", ".split(", ".concat(", "JSON."):
        assert transformation not in script, f"{transformation} : la valeur passerait autrement que telle quelle"
    assert len(re.findall(r"champ\.value\s*=", script)) == 1, "une seule affectation de valeur : celle du paramètre"
    assert "location.href" not in script and "document.referrer" not in script, "seule l'adresse de la page compte"


def test_le_script_ne_garde_rien_et_n_appelle_personne(script):
    for interdit in ("document.cookie", "localStorage", "sessionStorage", "indexedDB", "fetch(", "XMLHttpRequest",
                     "sendBeacon", "WebSocket", "import(", "eval(", "Function(", "document.write", "innerHTML",
                     "setTimeout", "setInterval", "addEventListener"):
        assert interdit not in script, f"{interdit} : le script ne stocke rien, n'appelle rien, n'exécute rien"


def test_aucune_ressource_externe_n_est_chargee(lecture):
    assert lecture.attributs_src == [], "aucun script, aucune image ni frame venus d'ailleurs"


def test_le_formulaire_refuse_de_partir_tant_que_l_adresse_du_recepteur_n_est_pas_posee(script):
    assert "if (!adresse || adresse.indexOf(\"REMPLACER\") !== -1) {" in script
    assert 'querySelector(\'button[type="submit"]\').disabled = true;' in script
    assert "pas encore configuré" in script
    # Le refus vient AVANT la création des champs : un formulaire éteint ne prépare rien.
    assert script.index("REMPLACER") < script.index("URLSearchParams")


def test_le_commentaire_du_fichier_renvoie_a_un_guide_qui_existe():
    texte = FICHIER.read_text(encoding="utf-8")
    assert "docs/departements/M1-canaux.md" in texte and "section 13" in texte
    assert re.search(r"^## 13\. ", DOC.read_text(encoding="utf-8"), re.MULTILINE), "la section 13 du guide existe"
