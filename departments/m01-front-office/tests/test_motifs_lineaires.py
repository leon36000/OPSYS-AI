"""Temps linéaire des trois motifs de M1 hors du garde-fou du socle (PLAN T4.17-g) : un texte hostile ne bloque rien.

`qualification._EMAIL_REGEX` lit le texte du client sans plafond. `contrats._PRIX_REGEX` et le courriel de `transferts`
lisent des textes plafonnés par leur contrat (500 et 1 200 caractères), mais les motifs eux-mêmes ne le sont pas. Avant
T4.17-g, chacun relisait la même suite de caractères à chaque départ (temps de calcul pour 20 000 caractères) : 0,5 s
au courriel du client (11 s pour 100 000), plus d'une minute au prix, de 1,1 à 1,5 s au courriel d'un résumé. Ce
fichier prouve quatre choses.

1. Le sens. Le prix n'a pas changé : le motif d'avant (recopié ici, tel quel, comme oracle) et celui de M1 donnent le
   même verdict sur toutes les suites de jetons jusqu'à une longueur donnée, sur les textes de la fixture de M1, sur
   des textes tirés au hasard (graine fixe) et sur une table de cas nommés. Les deux courriels ont changé de sens
   exprès. Celui du client (PLAN T4.17-g2) se lit en entier, lettres accentuées comprises, ou pas du tout, jamais
   tronqué (le lead le garde et M2 en tire le `client_id`). Celui d'un résumé (T4.17-g3) se reconnaît aussi derrière un
   accent combinant ou un autre caractère qui peut faire partie d'une adresse : le garde-fou refuse plus, jamais moins
   que l'ancien motif. Chacun a pour oracle une référence écrite lettre à lettre, lente et évidente
   (`_courriel_de_reference`, `_coordonnee_de_reference`), comparée sur les mêmes textes ; les tables de cas nommés
   disent ce que l'ancien motif lisait et ce que M1 lit maintenant.
2. Le temps croît comme le texte : les textes hostiles de 20 000 et de 100 000 caractères passent sous une borne
   absolue généreuse, et le rapport des temps reste loin du carré (25 pour cinq fois plus de texte).
3. Les fonctions de M1 qui lisent ces motifs (contact du texte du client, coordonnées d'un résumé) le font aussi.
4. Aucun motif de niveau module de M1, quel que soit son module, ne ralentit sur un texte hostile de la taille maximale
   de la réception : le balayage aurait nommé les trois d'avant.

Les textes sont fictifs (adresses, montants et phrases inventés).
"""

from __future__ import annotations

import importlib
import itertools
import pkgutil
import random
import re
import string
import time
import unicodedata
from pathlib import Path

import m1_front_office
import pytest
import yaml
from m1_front_office import contrats, qualification, reception, transferts

FICTIF = True

NBSP, NNBSP = "\u00a0", "\u202f"
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

# ----------------------------------------------------------------------------------------------------------------------
# L'oracle : les motifs tels qu'ils étaient avant T4.17-g (recopiés, jamais importés de M1). Celui du courriel du client
# ne sert plus qu'à dire, dans la table des cas nommés, ce qui a changé avec T4.17-g2.
# ----------------------------------------------------------------------------------------------------------------------
EMAIL_AVANT = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
COURRIEL_AVANT = re.compile(r"[\w.%+'-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}")
PRIX_AVANT = re.compile(
    r"""(
        \$\s*\d+(?:[\s,.]\d+)* |                      # $ 5 000 ou 5,000
        \d+(?:[\s,.]\d+)*\s*\$ |                      # 5 000 $ ou 5,000$
        €\s*\d+(?:[\s,.]\d+)* |                        # € 5 000
        \d+(?:[\s,.]\d+)*\s*€ |                        # 5 000 €
        \d+(?:[\s,.]\d+)*\s*(?:dollars|euros|CAD) |    # 500 dollars
        (?:dollars|euros|CAD)\s*\d+(?:[\s,.]\d+)* |    # dollars 500
        à\s+partir\s+de\s+\d+(?:[\s,.]\d+)* |          # à partir de 500
        fourchette\s+\d+(?:[\s,.]\d+)*\s*-\s*\d+(?:[\s,.]\d+)* | # fourchette 100-200
        \d+(?:[\s,.]\d+)*\s*/\s*m[²2] |                # 50/m²
        \d+(?:[\s,.]\d+)*\s*/\s*h |                    # 50/h
        \d+(?:[\s,.]\d+)*\s*/\s*pi[²2]                 # 50/pi²
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def _courriel_avant(texte: str) -> str | None:
    """Le courriel que l'ancien motif lisait dans le texte du client (avant T4.17-g2), ou `None`."""
    trouve = EMAIL_AVANT.search(texte)
    return None if trouve is None else trouve.group()


def _courriel_apres(texte: str) -> str | None:
    """Le courriel que M1 lit aujourd'hui dans le texte du client (celui que le lead garde), ou `None`."""
    return qualification._courriel_du_texte(texte)


def _contact_apres(texte: str) -> str | None:
    """Le courriel que `qualification` extrait du texte du client, ou `None`."""
    contact = qualification.contact_du_texte(texte)
    return None if contact is None else contact.get("courriel")


# Le courriel du client depuis T4.17-g2 : la référence, écrite lettre à lettre, lente et évidente. Elle ne partage
# avec M1 que la règle : le texte en forme NFC ; un départ jamais juste après un caractère qui peut prolonger un mot ou
# une adresse ; les signes qui ouvrent la suite sautés ; une partie locale qui commence par une lettre, un chiffre ou
# `_` et se lit jusqu'au « @ » ; un domaine ASCII coupé après le dernier point suivi d'au moins deux lettres ASCII qui
# finissent le mot. Le premier départ qui donne un courriel l'emporte.
_SIGNES_LOCAUX = ".%+'-"
_AUTRES_CARACTERES_RFC = "!#$&*/=?^`{|}~"
_AUSSI_DANS_UN_MOT = "\u2010\u2011\u2019\u00b7"  # traits d'union Unicode, apostrophe typographique, point médian
_LETTRES_ASCII = frozenset(string.ascii_letters)
_DOMAINE_ASCII = frozenset(string.ascii_letters + string.digits + ".-")


def _mot(caractere: str) -> bool:
    return caractere.isalnum() or caractere == "_"


def _peut_prolonger(caractere: str) -> bool:
    """Vrai si `caractere` peut faire partie d'un mot ou d'une adresse : un courriel qui commencerait juste après
    serait la fin d'un mot ou d'une adresse plus longue."""
    categorie = unicodedata.category(caractere)
    return (_mot(caractere) or caractere in _SIGNES_LOCAUX or caractere in _AUTRES_CARACTERES_RFC or caractere == "@"
            or categorie[0] == "M" or categorie in ("Pc", "Cf") or caractere in _AUSSI_DANS_UN_MOT)


def _fin_du_domaine(texte: str, debut: int) -> int | None:
    """Où finit le domaine qui commence à `debut`, ou `None`."""
    fin_de_suite = debut
    while fin_de_suite < len(texte) and texte[fin_de_suite] in _DOMAINE_ASCII:
        fin_de_suite += 1
    for point in range(fin_de_suite - 1, debut, -1):  # du dernier point au premier, un caractère au moins devant
        if texte[point] != ".":
            continue
        fin = point + 1
        while fin < len(texte) and texte[fin] in _LETTRES_ASCII:
            fin += 1
        if fin - point > 2 and (fin == len(texte) or not _mot(texte[fin])):
            return fin
    return None


def _courriel_de_reference(texte: str) -> str | None:
    """Le courriel que le client a écrit, selon la règle de T4.17-g2, ou `None`."""
    texte = unicodedata.normalize("NFC", texte)
    for debut in range(len(texte)):
        if debut > 0 and _peut_prolonger(texte[debut - 1]):
            continue
        local = debut
        while local < len(texte) and texte[local] in _SIGNES_LOCAUX:
            local += 1
        if local == len(texte) or not _mot(texte[local]):
            continue
        arobase = local
        while arobase < len(texte) and (_mot(texte[arobase]) or texte[arobase] in _SIGNES_LOCAUX):
            arobase += 1
        if arobase < len(texte) and texte[arobase] == "@":
            fin = _fin_du_domaine(texte, arobase + 1)
            if fin is not None:
                return texte[local:fin]
    return None


def _domaine_d_un_resume(texte: str, debut: int) -> bool:
    """Un domaine commence à `debut`, selon le garde-fou d'un résumé : des segments de lettres, chiffres, `_` ou `-`
    séparés par des points, le premier non vide, puis un segment qui commence par deux lettres ASCII avant tout segment
    vide (aucune fin de mot n'est exigée)."""
    fin = debut
    while fin < len(texte) and (_mot(texte[fin]) or texte[fin] in ".-"):
        fin += 1
    premier, *suivants = texte[debut:fin].split(".")
    if not premier:
        return False
    for segment in suivants:
        if len(segment) >= 2 and segment[0] in _LETTRES_ASCII and segment[1] in _LETTRES_ASCII:
            return True
        if not segment:
            return False
    return False


def _coordonnee_de_reference(texte: str) -> bool:
    """Le garde-fou d'un résumé depuis T4.17-g3 : un « @ » suivi d'un domaine, avec devant lui un caractère qui peut
    faire partie d'une adresse ou d'un mot (un autre « @ » n'en est pas un)."""
    return any(
        texte[i] == "@" and i > 0 and texte[i - 1] != "@" and _peut_prolonger(texte[i - 1])
        and _domaine_d_un_resume(texte, i + 1)
        for i in range(len(texte))
    )


def _prix_avant(texte: str) -> bool:
    return PRIX_AVANT.search(texte) is not None


def _prix_apres(texte: str) -> bool:
    return contrats._PRIX_REGEX.search(texte) is not None


def _coordonnee_avant(texte: str) -> bool:
    return COURRIEL_AVANT.search(texte) is not None


def _coordonnee_apres(texte: str) -> bool:
    return transferts._courriel_present(texte)


# ----------------------------------------------------------------------------------------------------------------------
# 1. Le sens n'a pas changé : toutes les suites de jetons, puis des textes générés
# ----------------------------------------------------------------------------------------------------------------------
# Chaque jeu vise des cas limites : (jetons, longueur maximale, préfixe commun). Courriel du client : une suite de
# caractères permis, lettres accentuées comprises, ce qui la précède (ce qui peut prolonger un mot ou une adresse
# interdit le départ), les signes qui l'ouvrent, le domaine et ce qui le suit.
JETONS_COURRIEL_CLIENT = {
    "caracteres_et_domaine": (["a", ".", "-", "_", "@", "é", " ", "x.ca", "1", "%"], 6, ""),
    "lettre_accentuee_devant": (["é", "a", ".", "@", "x.ca", "-", " "], 7, ""),
    "signes_de_la_partie_locale": (["a", "+", "%", ".", "-", "@", "b.cd", "É", "٣", "²"], 5, ""),
    "domaines": (["a", ".", "-", "_", "1", "cd", "C", "é", " ", "@"], 6, "a@"),
    "dans_un_mot": (["a", "\u2019", "'", "\u0301", "e", "@", "x.ca", "\u00b7", "\u200b", " ", "\u2011"], 6, ""),
    "caracteres_rfc_et_delimiteurs": (["a", "&", "/", "*", "=", "@", "x.ca", "<", ":", " "], 6, ""),
}
# Courriel d'un résumé : ce qui précède le « @ » (lettres accentuées, chiffres, soulignement, apostrophes, accent
# combinant, caractères de format et signes de la RFC), puis le domaine.
JETONS_COURRIEL_RESUME = {
    "caracteres_et_domaine": (["a", ".", "-", "_", "@", "é", "'", "x.ca", "%", "+", "1"], 5, ""),
    "lettre_accentuee_et_domaines": (["é", "a", ".", "@", "x.ca", "-", "_", "b"], 6, ""),
    "domaines": (["a", ".", "-", "_", "1", "cd", "C", "é", " ", "'", "@"], 5, "a@"),
    "accents_combinants_et_signes": (["a", "\u0301", "\u2019", "!", "@", "x.ca", " ", "\u200b", "«", "."], 5, ""),
}
# Prix : un chiffre que touche une devise, un taux ou un mot ; la fourchette lit deux nombres et un tiret.
JETONS_PRIX = {
    "chiffres_devises_taux": (
        ["1", "5", " ", NBSP, ",", ".", "$", "€", "CAD", "dollars", "euros", "/", "h", "m²", "m2", "pi2", "-", "x"],
        4, ""),
    "fourchette_et_separateurs": (["fourchette ", "1", " ", ",", "-"], 7, ""),
    "fourchette_puis_deux_nombres": (["1", "2", " ", ",", "-", ".", NBSP], 6, "fourchette "),
    "devise_devant": (["$", "€", "dollars", "CAD", " ", NBSP, "\n", "5", "٣", ",", "x"], 5, ""),
}


def _suites(jetons: list[str], longueur_max: int, prefixe: str):
    for longueur in range(1, longueur_max + 1):
        for suite in itertools.product(jetons, repeat=longueur):
            yield prefixe + "".join(suite)


@pytest.mark.parametrize("jeu", JETONS_COURRIEL_CLIENT)
def test_le_courriel_du_client_donne_le_texte_de_la_reference_sur_toutes_les_suites_de_jetons(jeu):
    ecarts = []
    total = trouves = 0
    for texte in _suites(*JETONS_COURRIEL_CLIENT[jeu]):
        attendu, lu = _courriel_de_reference(texte), _courriel_apres(texte)
        total += 1
        trouves += attendu is not None
        if attendu != lu:
            ecarts.append((texte, attendu, lu))
    assert not ecarts[:5], f"{len(ecarts)} écarts sur {total} textes, dont {ecarts[:5]}"
    assert trouves > 1000, "la référence doit trouver assez de courriels pour que la comparaison prouve quelque chose"


@pytest.mark.parametrize("jeu", JETONS_COURRIEL_RESUME)
def test_le_courriel_d_un_resume_suit_la_reference_et_ne_refuse_jamais_moins_qu_avant_sur_toutes_les_suites(jeu):
    ecarts, en_moins = [], []
    total = trouves = 0
    for texte in _suites(*JETONS_COURRIEL_RESUME[jeu]):
        attendu, apres = _coordonnee_de_reference(texte), _coordonnee_apres(texte)
        total += 1
        trouves += attendu
        if attendu != apres:
            ecarts.append((texte, attendu, apres))
        if _coordonnee_avant(texte) and not apres:
            en_moins.append(texte)
    assert not ecarts[:5], f"{len(ecarts)} écarts sur {total} textes, dont {ecarts[:5]}"
    assert not en_moins[:5], f"{len(en_moins)} textes que l'ancien motif refusait ne le sont plus, dont {en_moins[:5]}"
    assert trouves > 1000, "la référence doit trouver assez de courriels pour que la comparaison prouve quelque chose"


@pytest.mark.parametrize("jeu", JETONS_PRIX)
def test_le_prix_d_un_chiffrage_donne_le_meme_verdict_que_l_ancien_motif_sur_toutes_les_suites_de_jetons(jeu):
    ecarts = []
    total = refuses = 0
    for texte in _suites(*JETONS_PRIX[jeu]):
        avant, apres = _prix_avant(texte), _prix_apres(texte)
        total += 1
        refuses += avant
        if avant != apres:
            ecarts.append((texte, avant, apres))
    assert not ecarts[:5], f"{len(ecarts)} écarts sur {total} textes, dont {ecarts[:5]}"
    assert refuses > 1000, "l'oracle doit refuser assez de textes pour que la comparaison prouve quelque chose"


def _ecarts_des_trois_motifs(textes) -> tuple[list[tuple[str, str]], int]:
    """Les textes où M1 s'écarte de son oracle (la référence pour les deux courriels, le motif d'avant pour le prix) ou
    refuse un résumé que l'ancien motif refusait, et combien de textes les oracles ont trouvés."""
    ecarts = []
    positifs = 0
    for texte in textes:
        client, resume, prix = _courriel_de_reference(texte), _coordonnee_de_reference(texte), _prix_avant(texte)
        positifs += (client is not None) + resume + prix
        if client != _courriel_apres(texte):
            ecarts.append(("courriel du client", texte))
        if resume != _coordonnee_apres(texte):
            ecarts.append(("courriel d'un résumé", texte))
        if _coordonnee_avant(texte) and not _coordonnee_apres(texte):
            ecarts.append(("courriel d'un résumé que l'ancien motif refusait", texte))
        if prix != _prix_apres(texte):
            ecarts.append(("prix", texte))
    return ecarts, positifs


LOCAUX = ["a", "A", "1", "_", ".", "-", "+", "%", "'", "a.b", "a..b", "-a", "é", "éa", "a.é", "andré.tremblay", "٣",
          "a b", "d'arcy", "o\u2019neil", "andre\u0301", "q\u0301a", "jean&marie", "l\u00b7l"]
DOMAINES = ["x.ca", "a.b.cc", "a.c", "a", "-a.ca", "a-.ca", "a..ca", ".ca", "a.CA", "a_b.ca", "é.ca", "a.cé", "a.ca1",
            "a.ca_", "a.ca-", "x.ca.", "x.ca.com", "٣.ca"]
AVANT_COURRIEL = ["", " ", "(", "é", "_", "mailto:", "<", "a.", "-", ".", "'", NBSP, "a@", "é.", "\u2019", "&", "/",
                  "=", "*", "\u0301", "\u200b", "\u00b7", "«", "\U0001F4E7", "\u2011", "e\u0301"]
APRES_COURRIEL = ["", " ", ".", "é", "x", ")", "@a.bc", "1", "_", "-", ".ca"]

NOMBRES = ["1", "12500", "12 500", "12" + NBSP + "500", "12" + NNBSP + "500", "9 999,99", "٣٤٥", "１２３", "1  500",
           "1..5", "1.", ",1", "1 ", " 1", "12²"]
DEVISES = ["$", " $", "  $", NBSP + "$", "\n$", "€", " €", "CAD", " cad", " dollars", " DOLLARS", " euros", " EUR",
           "dollarsx", " dollars_", "dollarſ", "$/h", " $ / h", "/m²", " / m2", " /M2", "/h", " / H", "/pi²",
           " / pi2", "/pied", "/ m", ""]
AVANT_PRIX = ["", "Le prix est ", "a", "_", "$", "$ ", "-", "fourchette ", "1 ", "à partir de ", "À PARTIR DE ", "€ ",
              "x/"]
APRES_PRIX = ["", ".", " ", "a", " à", ",", ".5", "x", "\n", "$", " - 5", "5"]


def _generes_courriels() -> list[str]:
    combinaisons = itertools.product(AVANT_COURRIEL, LOCAUX, DOMAINES, APRES_COURRIEL)
    return [avant + local + "@" + domaine + apres for avant, local, domaine, apres in combinaisons]


def _generes_prix() -> list[str]:
    return [a + n + d + ap for a, n, d, ap in itertools.product(AVANT_PRIX, NOMBRES, DEVISES, APRES_PRIX)]


def _generes_devises_devant() -> list[str]:
    """La devise ou le mot AVANT le nombre : « $ 5 », « €5 », « dollars 500 », « à partir de 500 »."""
    mots = ["$", "€", "dollars", "euros", "CAD", "cad", "Dollars", "à partir de", "À partir de", "a partir de",
            "à partir", "partir de", "de", "à", "$$", "US$", "dollarſ", "à" + NBSP + "partir" + NBSP + "de",
            "àpartir de", "à partirde", "àpartirde", "à  partir  de"]
    liens = ["", " ", "  ", NBSP, "\n", "\t", "\u3000", "x", "-", ":", "\u200b"]
    nombres = ["5", "500", "5 000", "٣", "１", "5,5", ",5", ".5", "a5", "5a", " 5", ""]
    return [m + lien + n + ap for m, lien, n, ap in itertools.product(mots, liens, nombres, ["", " ", "$", "x"])]


def _generes_fourchettes() -> list[str]:
    mots = ["fourchette", "FOURCHETTE", "fourchettes", "budget"]
    espaces = ["", " ", "  ", NBSP, "\n"]
    n1 = ["8", "8 000", "8,5", "٣", "8a", "a8", "1..2", "1 2", "1  2", "1.2.3", "8 ", "8  ", "8,", ",8"]
    liens = ["-", " - ", " -", "- ", "  -  ", "–", "à", "--", "-\n", "\n-", "- -", "-" + NBSP, "/", ""]
    n2 = ["12", "12 000", "12,5", "12a", "12-", "٣", "x12", "", "-12", " 12", "\n12"]
    fins = ["", " $"]
    return [m + e + a + lien + b + f for m, e, a, lien, b, f in itertools.product(mots, espaces, n1, liens, n2, fins)]


GENERES = {
    "courriels": _generes_courriels,
    "prix": _generes_prix,
    "devise_ou_mot_devant_le_nombre": _generes_devises_devant,
    "fourchettes": _generes_fourchettes,
}


@pytest.mark.parametrize("nom", GENERES)
def test_les_motifs_donnent_les_memes_verdicts_que_l_ancienne_ecriture_sur_des_textes_generes(nom):
    textes = GENERES[nom]()
    ecarts, positifs = _ecarts_des_trois_motifs(textes)
    assert not ecarts[:5], f"{len(ecarts)} écarts sur {len(textes)} textes, dont {ecarts[:5]}"
    assert positifs > 1000, "l'oracle doit trouver assez de textes pour que la comparaison prouve quelque chose"


# ----------------------------------------------------------------------------------------------------------------------
# 1. Le sens n'a pas changé : la fixture de M1, des textes tirés au hasard
# ----------------------------------------------------------------------------------------------------------------------
def _chaines(objet, sortie: list[str]) -> None:
    if isinstance(objet, str):
        sortie.append(objet)
    elif isinstance(objet, dict):
        for valeur in objet.values():
            _chaines(valeur, sortie)
    elif isinstance(objet, list):
        for valeur in objet:
            _chaines(valeur, sortie)


def _textes_des_fixtures() -> list[str]:
    textes: list[str] = []
    for fichier in sorted(_FIXTURES.rglob("*.yaml")):
        _chaines(yaml.safe_load(fichier.read_text(encoding="utf-8")), textes)
    return textes


def test_les_textes_des_fixtures_de_m1_donnent_les_memes_verdicts_que_l_ancienne_ecriture():
    textes = _textes_des_fixtures()
    assert len(textes) > 200, "la fixture de M1 doit fournir assez de textes"
    ecarts, positifs = _ecarts_des_trois_motifs(textes)
    assert not ecarts[:5], f"{len(ecarts)} écarts sur {len(textes)} textes, dont {ecarts[:5]}"
    assert positifs >= 5, "l'oracle doit refuser des textes de la fixture (les corpus interdits parlent de prix)"


FRAGMENTS_AU_HASARD = [
    "jean@exemple.ca", "a.b@c.ca", "x@y.z", "é.a@x.ca", "andré.tremblay@exemple.ca", "françois@exemple.ca",
    "a_b+c%d@e-f.gh", "@", ".", "-", "_", "%", "+", "'", "é", "É", "٣", "²", " ", "\n", NBSP, "mailto:", "<", ">",
    "(", ")", ",", "ca", "co.uk", "5 000 $", "12 500 $", "9 999,99 €", "500 dollars", "CAD 12", "à partir de 500",
    "fourchette 8-12", "fourchette 8 - 12", "fourchette 1..2-3", "50/m²", "50 / h", "12/pi2", "$ 5", "€5",
    "12" + NBSP + "500 $", "1" + NNBSP + "000 €", "dollars", "euros", "cad", "fourchette", "à partir de", "5", "12",
    "1,5", "2.5", "0", "٣٤٥", "１２３", "x", "a", "Le prix est", "\u2019", "\u0301", "e\u0301", "&", "/", "*", "=",
    "\u200b", "\u00b7", "o\u2019neil@exemple.ca", "d'arcy@exemple.ca", "josé.tremblay@exemple.ca", "«", "»",
]


def test_les_motifs_donnent_les_memes_verdicts_que_l_ancienne_ecriture_sur_des_textes_tires_au_hasard():
    rng = random.Random(20260929)
    textes = ["".join(rng.choice(FRAGMENTS_AU_HASARD) for _ in range(rng.randint(1, 10))) for _ in range(30_000)]
    ecarts, positifs = _ecarts_des_trois_motifs(textes)
    assert not ecarts[:5], f"{len(ecarts)} écarts, dont {ecarts[:5]}"
    assert positifs > 1000, "l'oracle doit trouver assez de textes pour que la comparaison prouve quelque chose"


# ----------------------------------------------------------------------------------------------------------------------
# 1. Le sens, en cas nommés
# ----------------------------------------------------------------------------------------------------------------------
# (texte du client, courriel que l'ancien motif lisait, courriel que M1 lit maintenant). L'ancien est vérifié sur sa
# copie : la table dit ce que T4.17-g2 a changé, et seulement cela.
COURRIELS_DU_CLIENT = [
    ("Mon courriel : jean.tremblay@exemple-fictif.ca, merci", "jean.tremblay@exemple-fictif.ca",
     "jean.tremblay@exemple-fictif.ca"),
    ("jean@exemple.ca", "jean@exemple.ca", "jean@exemple.ca"),
    ("JEAN_T+promo%2@Exemple.CA", "JEAN_T+promo%2@Exemple.CA", "JEAN_T+promo%2@Exemple.CA"),
    ("écrivez à a.b-c@d-e.f.gh.", "a.b-c@d-e.f.gh", "a.b-c@d-e.f.gh"),
    ("<jean@exemple.ca>", "jean@exemple.ca", "jean@exemple.ca"),
    ("mailto:jean@exemple.ca", "jean@exemple.ca", "jean@exemple.ca"),
    ("premier a@b.cd, second e@f.gh", "a@b.cd", "a@b.cd"),  # le premier courriel
    ("a..b@exemple.ca", "a..b@exemple.ca", "a..b@exemple.ca"),
    ("x@y.co.uk", "x@y.co.uk", "x@y.co.uk"),
    ("x@y.ca.", "x@y.ca", "x@y.ca"),  # le point final n'en fait pas partie
    ("-abc@exemple.ca", "abc@exemple.ca", "abc@exemple.ca"),  # les signes qui ouvrent la suite sont sautés
    (".abc@exemple.ca", "abc@exemple.ca", "abc@exemple.ca"),
    ("+1.514@exemple.ca", "1.514@exemple.ca", "1.514@exemple.ca"),
    ("a b@exemple.ca", "b@exemple.ca", "b@exemple.ca"),
    ("«jean@exemple.ca»", "jean@exemple.ca", "jean@exemple.ca"),
    ("(jean@exemple.ca)", "jean@exemple.ca", "jean@exemple.ca"),
    ("\U0001F4E7jean@exemple.ca", "jean@exemple.ca", "jean@exemple.ca"),
    ("", None, None),
    ("aucun courriel ici", None, None),
    ("jean@", None, None),
    ("@exemple.ca", None, None),
    ("jean@exemple", None, None),
    ("jean@exemple.c", None, None),
    ("jean @exemple.ca", None, None),
    ("jean@ exemple.ca", None, None),
    ("jean@.ca", None, None),
    ("jean@exemple.ca1", None, None),  # la fin du domaine doit finir le mot
    ("jean@exemple.ca_", None, None),
    ("jean@exemple.caé", None, None),
    ("jean@exemple_fictif.ca", None, None),  # le soulignement n'est pas permis dans le domaine
    ("jean@café.ca", None, None),  # un domaine accentué ne donne rien, jamais « jean@caf… »
    # T4.17-g2 : la partie locale se lit en entier, lettres accentuées comprises ; l'ancien motif la tronquait.
    ("andré.tremblay@exemple.ca", ".tremblay@exemple.ca", "andré.tremblay@exemple.ca"),
    ("josé.tremblay@exemple.ca", ".tremblay@exemple.ca", "josé.tremblay@exemple.ca"),  # le même, avant : un client
    ("José.Tremblay@exemple.ca", ".Tremblay@exemple.ca", "José.Tremblay@exemple.ca"),
    ("éa.b@exemple.ca", ".b@exemple.ca", "éa.b@exemple.ca"),
    ("frédéric-tremblay@exemple.ca", "-tremblay@exemple.ca", "frédéric-tremblay@exemple.ca"),
    ("d'Arcy@exemple.ca", "Arcy@exemple.ca", "d'Arcy@exemple.ca"),
    ("premier: françois@exemple.ca, second: jean@exemple.ca", "jean@exemple.ca", "françois@exemple.ca"),
    ("françois@exemple.ca", None, "françois@exemple.ca"),
    ("éric@exemple.ca", None, "éric@exemple.ca"),
    ("a.é@exemple.ca", None, "a.é@exemple.ca"),
    ("ça@exemple.ca", None, "ça@exemple.ca"),
    ("٣@exemple.ca", None, "٣@exemple.ca"),
    # Un accent tapé en deux caractères (NFD) : la même adresse, donc le même client, que l'accent composé.
    ("andre\u0301.tremblay@exemple.ca", "tremblay@exemple.ca", "andré.tremblay@exemple.ca"),
    ("rene\u0301@exemple.ca", None, "rené@exemple.ca"),
    # T4.17-g2 : ce qui peut prolonger un mot ou une adresse interdit le départ ; rien plutôt que la fin d'une adresse.
    ("o\u2019neil@exemple.ca", "neil@exemple.ca", None),  # apostrophe typographique
    ("jean&marie@exemple.ca", "marie@exemple.ca", None),  # caractère permis par la RFC 5322
    ("a/jean@exemple.ca", "jean@exemple.ca", None),
    ("courriel=jean@exemple.ca", "jean@exemple.ca", None),
    ("*jean@exemple.ca*", "jean@exemple.ca", None),
    ("a@jean@exemple.ca", "jean@exemple.ca", None),
    ("q\u0301a@exemple.ca", "a@exemple.ca", None),  # accent combinant sans forme composée
    ("jean\u2011tremblay@exemple.ca", "tremblay@exemple.ca", None),  # trait d'union insécable
    ("jean\u00adtremblay@exemple.ca", "tremblay@exemple.ca", None),  # trait d'union conditionnel
    ("col\u00b7legi@exemple.ca", "legi@exemple.ca", None),  # point médian
    ("\u200bjean@exemple.ca", "jean@exemple.ca", None),  # caractère de format devant l'adresse
    ("jean\u2010tremblay@exemple.ca", "tremblay@exemple.ca", None),  # trait d'union Unicode
    ("jean\uff3ftremblay@exemple.ca", "tremblay@exemple.ca", None),  # liaison (soulignement pleine chasse)
    ("o\u2019neil@exemple.ca ou jean@exemple.ca", "neil@exemple.ca", "jean@exemple.ca"),  # le suivant reste lu
]


@pytest.mark.parametrize(("texte", "avant", "maintenant"), COURRIELS_DU_CLIENT)
def test_le_courriel_du_client_se_lit_en_entier_ou_pas_du_tout(texte, avant, maintenant):
    assert _courriel_avant(texte) == avant, "l'ancien motif (recopié) lisait ce courriel"
    assert _courriel_de_reference(texte) == maintenant
    assert _courriel_apres(texte) == maintenant
    assert qualification.contact_du_texte(texte) == (None if maintenant is None else {"courriel": maintenant})


@pytest.mark.parametrize("signe", sorted(_AUTRES_CARACTERES_RFC + "@"))
def test_un_caractere_permis_dans_une_adresse_devant_la_suite_ne_laisse_rien_lire(signe):
    """« a&jean@x.ca » est peut-être une adresse entière : l'ancien motif en lisait la fin, M1 ne lit rien."""
    texte = f"a{signe}jean@exemple.ca"
    assert _courriel_avant(texte) == "jean@exemple.ca"
    assert _courriel_de_reference(texte) is None
    assert _courriel_apres(texte) is None


def test_deux_clients_dont_l_adresse_differe_par_le_prenom_restent_deux_contacts():
    """Le cas qui a ouvert T4.17-g2 : l'ancien motif lisait « .tremblay@exemple.ca » dans les deux textes."""
    andre = qualification.contact_du_texte("andré.tremblay@exemple.ca")
    jose = qualification.contact_du_texte("josé.tremblay@exemple.ca")
    assert andre == {"courriel": "andré.tremblay@exemple.ca"}
    assert jose == {"courriel": "josé.tremblay@exemple.ca"}
    assert andre != jose
    # Composé ou tapé en deux caractères, le même accent donne le même contact.
    assert qualification.contact_du_texte("andre\u0301.tremblay@exemple.ca") == andre


def test_le_courriel_et_le_telephone_du_client_se_lisent_ensemble_comme_avant():
    texte = "Appelez le 514-555-0142 ou écrivez à jean@exemple.ca"
    assert qualification.contact_du_texte(texte) == {"telephone": "514-555-0142", "courriel": "jean@exemple.ca"}
    assert qualification.contact_du_texte("Mon numéro : (514) 555-0142") == {"telephone": "(514) 555-0142"}


COORDONNEES_D_UN_RESUME_REFUSEES = [
    "jean@exemple.ca",
    "Courriel : jean.tremblay@exemple.ca.",
    "Contact jean@exemple.ca pour la suite.",
    "a@b.cd",
    "j'ai@exemple.ca",
    "a%b+c@d-e.fr",
    "d'Arcy@exemple.ca",
    "françois@exemple.ca",  # `\w` lit les lettres accentuées
    "x@y.co.uk",
    "a@b.cd1",  # aucune fin de mot exigée
    "a@b.cdé",
    "a@exemple_fictif.ca",
    "٣@exemple.ca",
    "a.@exemple.ca",
    "a-@exemple.ca",
    "a_@exemple.ca",
    "a+@exemple.ca",
    "a%@exemple.ca",
    "'@exemple.ca",
    ".@exemple.ca",
]

COORDONNEES_D_UN_RESUME_NON_REFUSEES = [
    "",
    "Plainte reçue par sms.",
    "jean",
    "@exemple.ca",
    "jean@",
    "jean@exemple",
    "jean@exemple.c",
    "jean @exemple.ca",
    "jean@ exemple.ca",
    "jean@.ca",
    "jean@exemple..ca",
    "jean@exemple.c1",
    "jean@-",
    "jean@exemple.",
    "«@exemple.ca»",  # aucune partie locale devant le « @ »
    "@@exemple.ca",
]

# T4.17-g3 : l'ancien motif ne les voyait pas ; le garde-fou d'un résumé les refuse maintenant.
COORDONNEES_D_UN_RESUME_REFUSEES_DEPUIS_T4_17_G3 = [
    "rene\u0301@exemple.ca",  # accent tapé en deux caractères juste devant le « @ »
    "q\u0301@exemple.ca",  # accent combinant sans forme composée
    "o\u2019@exemple.ca",  # apostrophe typographique
    "jean!@exemple.ca",  # signe permis par la RFC 5322
    "a&@exemple.ca",
    "\u200b@exemple.ca",  # caractère de format
    "col\u00b7@exemple.ca",  # point médian
    "jean\u2011@exemple.ca",  # trait d'union insécable
]


@pytest.mark.parametrize("texte", COORDONNEES_D_UN_RESUME_REFUSEES)
def test_un_courriel_dans_un_resume_est_refuse_comme_avant(texte):
    assert _coordonnee_avant(texte), "l'oracle (l'ancien motif) reconnaissait ce courriel"
    assert _coordonnee_apres(texte)
    assert transferts.contient_coordonnees(texte) is True


@pytest.mark.parametrize("texte", COORDONNEES_D_UN_RESUME_NON_REFUSEES)
def test_ce_que_le_courriel_d_un_resume_ne_reconnaissait_pas_n_est_toujours_pas_reconnu(texte):
    assert not _coordonnee_avant(texte), "l'oracle (l'ancien motif) ne reconnaissait pas ce texte"
    assert not _coordonnee_de_reference(texte)
    assert not _coordonnee_apres(texte)
    assert transferts.contient_coordonnees(texte) is False


@pytest.mark.parametrize("signe", sorted(_AUTRES_CARACTERES_RFC))
def test_un_signe_permis_par_la_rfc_devant_le_arobase_fait_refuser_un_resume(signe):
    """« jean#@x.ca » peut être une adresse : l'ancien motif ne la voyait pas, le garde-fou la refuse."""
    texte = f"Rappeler jean{signe}@exemple.ca demain"
    assert not _coordonnee_avant(texte), "l'ancien motif (recopié) ne voyait pas ce courriel"
    assert _coordonnee_de_reference(texte)
    assert _coordonnee_apres(texte)
    assert transferts.contient_coordonnees(texte) is True


@pytest.mark.parametrize("texte", COORDONNEES_D_UN_RESUME_REFUSEES_DEPUIS_T4_17_G3)
def test_un_courriel_derriere_un_caractere_qui_prolonge_une_adresse_est_refuse_dans_un_resume(texte):
    assert not _coordonnee_avant(texte), "l'ancien motif (recopié) ne voyait pas ce courriel"
    assert _coordonnee_de_reference(texte)
    assert _coordonnee_apres(texte)
    assert transferts.contient_coordonnees(texte) is True


PRIX_REFUSES = [
    "5000 $",
    "5 000 $",
    "5,000$",
    "12.5€",
    "1 234,56 €",
    "12" + NBSP + "500 $",
    "12" + NNBSP + "500" + NNBSP + "$",
    "500 dollars",
    "500 Dollars",
    "500 euros",
    "500 CAD",
    "500 cad",
    "5 dollarsx",  # aucune fin de mot exigée
    "dollars 500",
    "CAD 500",
    "euros5",
    "$ 5 000",
    "$5",
    "€ 5",
    "€5",
    "à partir de 500",
    "À PARTIR DE 500",
    "à  partir\nde  500",
    "fourchette 100-200",
    "fourchette 100 - 200",
    "FOURCHETTE\t1 000-2 000",
    "fourchette 1,5-2.5",
    "fourchette 8-12 pour la toiture",
    "50/m²",
    "50/m2",
    "50 / M2",
    "50/h",
    "50 / H",
    "50/heure",
    "50/pi²",
    "50/pi2",
    "٣٤٥ $",
    "１２３ €",
    "Réparation toiture pour 5000 $ et remplacement des gouttières.",
]

PRIX_NON_REFUSES = [
    "",
    "12 500",
    "Nous avons 12 500 clients satisfaits",
    "514-555-0142",
    "$",
    "€",
    "$ abc",
    "dollars",
    "CAD",
    "dollars abc",
    "à partir de demain",
    "à partir de",
    "à partir 500",
    "a partir de 500",
    "àpartir de 500",  # au moins une espace entre les mots
    "à partirde 500",
    "à partir de500",
    "fourchette",
    "fourchette 100 à 200",
    "fourchette 100 - ",
    "fourchette 100-",
    "fourchette -200",
    "fourchette100-200",  # au moins une espace après le mot
    "fourchette 1..2-3",  # un séparateur entre deux chiffres, jamais deux
    "fourchette 1  2-3",
    "fourchette 100–200",  # le tiret cadratin n'est pas un tiret
    "fourchette 100/200",
    "50/",
    "50/pi",
    "50/m",
    "50 / mètre",
    "m²",
    "/h",
    "a/h",
]


@pytest.mark.parametrize("texte", PRIX_REFUSES)
def test_un_prix_est_refuse_comme_avant(texte):
    assert _prix_avant(texte), "l'oracle (l'ancien motif) refusait ce texte"
    assert _prix_apres(texte)


@pytest.mark.parametrize("texte", PRIX_NON_REFUSES)
def test_ce_que_le_prix_ne_refusait_pas_n_est_toujours_pas_refuse(texte):
    assert not _prix_avant(texte), "l'oracle (l'ancien motif) laissait passer ce texte"
    assert not _prix_apres(texte)


def test_une_description_de_chiffrage_avec_un_prix_est_refusee_et_sans_prix_acceptee():
    base = {
        "lead_id": "L1", "conversation_id": "C1", "contact": {"telephone": "5145550100"}, "type_travaux": "autre",
        "ville": "Laval", "urgence_declaree": False, "canal": "texte",
    }
    sans_prix = "Remplacement de gouttières en aluminium sur deux façades, échafaudage nécessaire au deuxième étage."
    assert contrats.valider_chiffrage({**base, "description_factuelle": sans_prix})["code"] == "EVT-CONTRAT-VALIDE"
    for prix in ("5 000 $", "50/m²", "fourchette 100-200", "à partir de 500", "500 dollars", "$ 5"):
        with pytest.raises(ValueError, match="contient un prix"):
            contrats.valider_chiffrage({**base, "description_factuelle": f"{sans_prix} {prix}"})


# ----------------------------------------------------------------------------------------------------------------------
# 2. Le temps croît comme le texte
# ----------------------------------------------------------------------------------------------------------------------
PILOTE = 4_000  # un cinquième de la taille maximale : un motif quadratique s'arrête ici, pas au bout de minutes
BORNE_PILOTE = 1.0  # s pour PILOTE caractères ; le temps linéaire mesuré est de l'ordre de la milliseconde
PETIT, GRAND = reception.TAILLE_MAX_TEXTE, 100_000  # ce que la réception accepte d'un client, puis cinq fois plus
BORNE_ABSOLUE = 2.0  # s pour GRAND caractères ; le temps linéaire mesuré est de l'ordre de 0,001 à 0,05 s
RAPPORT_MAX = 15  # t(GRAND) / t(PETIT) : 5 si le temps est linéaire, 25 s'il est quadratique
PLANCHER = 0.020  # s : sous ce temps, la mesure du petit texte est du bruit


def _meilleur_temps(fonction, texte: str, essais: int) -> float:
    """Le meilleur temps de `essais` lectures. Un temps cinq fois au-dessus de la borne n'est pas du bruit : on s'arrête
    (un motif quadratique mettrait des minutes à échouer si l'on répétait chaque mesure)."""
    meilleur = float("inf")
    for _ in range(essais):
        debut = time.perf_counter()
        fonction(texte)
        meilleur = min(meilleur, time.perf_counter() - debut)
        if meilleur > 5 * BORNE_ABSOLUE:
            break
    return meilleur


def _lineaire(fonction, fabrique, essais: tuple[int, int] = (5, 3)) -> tuple[float, float]:
    """Mesure `fonction` sur `fabrique(PETIT)` puis `fabrique(GRAND)` ; `AssertionError` si le temps n'est pas linéaire.

    Le meilleur de plusieurs essais écarte le bruit de la machine (ordonnanceur, ramasse-miettes). Si le rapport
    dépasse la limite, une seconde série remesure avant de conclure. Sous 20 ms, le petit texte ne dit rien du rapport
    (le bruit domine) : la limite se calcule alors sur 20 ms, et la borne absolue juge seule les cas plus rapides.
    Une première mesure, sur PILOTE caractères, arrête tôt un motif quadratique : 20 000 chiffres coûtaient plus d'une
    minute à l'ancien prix, et ce test n'a pas à les attendre pour échouer."""
    pilote = _meilleur_temps(fonction, fabrique(PILOTE), 1)
    assert pilote < BORNE_PILOTE, f"{PILOTE} caractères : {pilote:.2f} s"
    petit = _meilleur_temps(fonction, fabrique(PETIT), essais[0])
    assert petit < BORNE_ABSOLUE, f"{PETIT} caractères : {petit:.2f} s"
    grand = _meilleur_temps(fonction, fabrique(GRAND), essais[1])
    assert grand < BORNE_ABSOLUE, f"{GRAND} caractères : {grand:.2f} s ({petit * 1000:.0f} ms pour {PETIT})"
    if grand > RAPPORT_MAX * max(petit, PLANCHER):
        petit = min(petit, _meilleur_temps(fonction, fabrique(PETIT), essais[0]))
        grand = min(grand, _meilleur_temps(fonction, fabrique(GRAND), essais[1]))
    assert grand <= RAPPORT_MAX * max(petit, PLANCHER), (
        f"le temps n'est pas linéaire : {petit * 1000:.1f} ms pour {PETIT}, {grand * 1000:.1f} ms pour {GRAND} "
        f"(rapport {grand / max(petit, 1e-6):.1f} pour un texte cinq fois plus long)")
    return petit, grand


# Chaque texte hostile vise un motif ou une mutation : (fabrique(n) -> texte d'environ n caractères, courriel que le
# client a écrit et que le lead garde, en fonction de n, ou `None`). Le résultat attendu prouve que la lecture est
# entière, pas abrégée.
COURRIEL_AU_BOUT = "@exemple.ca"
TEXTES_HOSTILES_COURRIEL = {
    "points": (lambda n: "a." * (n // 2), None),
    "tirets": (lambda n: "a-" * (n // 2), None),
    "soulignes": (lambda n: "a_" * (n // 2), None),
    "pourcents": (lambda n: "a%" * (n // 2), None),
    "plus": (lambda n: "a+" * (n // 2), None),
    "plus_un": (lambda n: "+1" * (n // 2), None),
    "chiffres_et_points": (lambda n: "1.1" * (n // 3), None),
    "lettres": (lambda n: "a" * n, None),
    "majuscules": (lambda n: "A" * n, None),
    "chiffres": (lambda n: "1" * n, None),
    "apostrophes": (lambda n: "e'" * (n // 2), None),
    "tous_les_caracteres_d_une_partie_locale": (lambda n: "a.b_c%d+e-f0A" * (n // 13), None),
    "lettres_puis_arobase": (lambda n: "a" * n + "@", None),
    "points_puis_arobase": (lambda n: "a." * (n // 2) + "@", None),
    "points_arobase_points": (lambda n: "a." * (n // 4) + "@" + "a." * (n // 4), None),
    "arobase_puis_points": (lambda n: "a@" + "a." * (n // 2), None),
    "arobase_puis_lettres": (lambda n: "a@" + "a" * n, None),
    "arobase_puis_tirets": (lambda n: "a@" + "a-" * (n // 2), None),
    "arobase_puis_domaine_sans_fin": (lambda n: "a@b." + "c" * n + "1", None),
    "arobase_puis_domaines": (lambda n: "a@b." * (n // 4), None),
    "arobases": (lambda n: "@" * n, None),
    "arobase_apres_chaque_lettre": (lambda n: "a@" * (n // 2), None),
    "lettres_accentuees": (lambda n: "é" * n, None),
    "accentuee_puis_points": (lambda n: "é" + "a." * (n // 2), None),
    "points_seuls": (lambda n: "." * n, None),
    "tirets_seuls": (lambda n: "-" * n, None),
    "espaces": (lambda n: " " * n, None),
    "points_puis_courriel": (
        lambda n: "a." * (n // 2) + COURRIEL_AU_BOUT, lambda n: "a." * (n // 2) + COURRIEL_AU_BOUT),
    "lettres_puis_courriel": (lambda n: "a" * n + COURRIEL_AU_BOUT, lambda n: "a" * n + COURRIEL_AU_BOUT),
    "tirets_puis_courriel": (lambda n: "-" * n + "a" + COURRIEL_AU_BOUT, lambda n: "a" + COURRIEL_AU_BOUT),
    "espaces_puis_courriel": (lambda n: " " * n + "a" + COURRIEL_AU_BOUT, lambda n: "a" + COURRIEL_AU_BOUT),
    # T4.17-g2 : la partie locale se lit en entier, ou rien n'est lu.
    "accentuees_puis_courriel": (lambda n: "é" * n + COURRIEL_AU_BOUT, lambda n: "é" * n + COURRIEL_AU_BOUT),
    "accents_combinants_puis_courriel": (
        lambda n: "e\u0301" * (n // 2) + COURRIEL_AU_BOUT, lambda n: "é" * (n // 2) + COURRIEL_AU_BOUT),
    "accents_sans_forme_composee": (lambda n: "q\u0301" * (n // 2) + "q" + COURRIEL_AU_BOUT, None),
    "apostrophes_typographiques": (lambda n: "a\u2019" * (n // 2) + "a" + COURRIEL_AU_BOUT, None),
    "caracteres_rfc": (lambda n: "a/" * (n // 2) + "a" + COURRIEL_AU_BOUT, None),
    "courriels_refuses": (lambda n: "a\u2019b@x.ca " * (n // 10), None),
}


def _courriel_attendu(nom: str, taille: int) -> str | None:
    lu = TEXTES_HOSTILES_COURRIEL[nom][1]
    return None if lu is None else lu(taille)


@pytest.mark.parametrize("nom", TEXTES_HOSTILES_COURRIEL)
def test_le_courriel_du_client_reste_lineaire_sur_un_texte_hostile(nom):
    fabrique = TEXTES_HOSTILES_COURRIEL[nom][0]
    assert _contact_apres(fabrique(PETIT)) == _courriel_attendu(nom, PETIT)
    _lineaire(qualification._courriel_du_texte, fabrique)


# Le courriel d'un résumé n'exige pas une fin de mot : une suite de lettres suivie d'un « 1 » finit un domaine valide.
# Là où le courriel du client ne lit rien plutôt qu'une adresse tronquée, le garde-fou du résumé refuse.
COORDONNEE_A_PART = {
    "arobase_puis_domaine_sans_fin": True,
    "accents_sans_forme_composee": True,
    "apostrophes_typographiques": True,
    "caracteres_rfc": True,
    "courriels_refuses": True,
}


@pytest.mark.parametrize("nom", TEXTES_HOSTILES_COURRIEL)
def test_le_courriel_d_un_resume_reste_lineaire_sur_un_texte_hostile(nom):
    fabrique = TEXTES_HOSTILES_COURRIEL[nom][0]
    attendu = COORDONNEE_A_PART.get(nom, _courriel_attendu(nom, PETIT) is not None)
    assert _coordonnee_apres(fabrique(PETIT)) is attendu
    _lineaire(transferts._courriel_present, fabrique)


TEXTES_HOSTILES_PRIX = {
    "chiffres": (lambda n: "1" * n, False),
    "chiffres_puis_lettre": (lambda n: "1" * n + "a", False),
    "chiffres_puis_devise": (lambda n: "1" * n + " $", True),
    "chiffres_espace": (lambda n: "1 " * (n // 2), False),
    "groupes_de_milliers": (lambda n: "1" + " 111" * (n // 4), False),
    "groupes_de_milliers_puis_lettre": (lambda n: "1" + " 111" * (n // 4) + "a", False),
    "groupes_insecables": (lambda n: ("111" + NBSP) * (n // 4), False),
    "groupes_fins_insecables": (lambda n: ("111" + NNBSP) * (n // 4), False),
    "decimales": (lambda n: "1." + "1" * n, False),
    "decimales_puis_lettre": (lambda n: "1." + "1" * n + "a", False),
    "chiffres_et_virgules": (lambda n: "1,1" * (n // 3), False),
    "chiffres_et_points": (lambda n: "1.1" * (n // 3), False),
    "chiffre_puis_espaces": (lambda n: "1" + " " * n + "x", False),
    "chiffre_puis_insecables": (lambda n: "1" + NBSP * n + "x", False),
    "chiffre_puis_espaces_puis_devise": (lambda n: "1" + " " * n + "$", True),
    "espaces": (lambda n: " " * n, False),
    "blancs_mixtes": (lambda n: " \t\n\r\f\v" * (n // 6), False),
    "dollars": (lambda n: "$" * n, False),
    "dollar_espace": (lambda n: "$ " * (n // 2), False),
    "dollar_puis_espaces": (lambda n: "$" + " " * n, False),
    "dollar_puis_espaces_puis_chiffre": (lambda n: "$" + " " * n + "5", True),
    "euros_puis_espaces": (lambda n: "€" + " " * n, False),
    "chiffre_dollar": (lambda n: "1a" * (n // 2) + "1$", True),
    "mots_devise": (lambda n: "dollars" * (n // 7), False),
    "mots_devise_euros": (lambda n: "euros" * (n // 5), False),
    "mots_devise_cad": (lambda n: "CAD" * (n // 3), False),
    "mot_devise_puis_espaces": (lambda n: "dollars" + " " * n + "x", False),
    "mot_devise_puis_espaces_puis_chiffre": (lambda n: "dollars" + " " * n + "9", True),
    "a_partir_de": (lambda n: "à partir de " * (n // 12), False),
    "a_partir_de_puis_espaces": (lambda n: "à partir de" + " " * n, False),
    "a_puis_espaces": (lambda n: "à" + " " * n + "x", False),
    "fourchettes": (lambda n: "fourchette " * (n // 11), False),
    "fourchette_puis_chiffres": (lambda n: "fourchette " + "1" * n, False),
    "fourchette_puis_chiffres_espaces": (lambda n: "fourchette " + "1 " * (n // 2), False),
    "fourchette_puis_decimales": (lambda n: "fourchette " + "1.1" * (n // 3), False),
    "fourchette_puis_espaces": (lambda n: "fourchette" + " " * n + "x", False),
    "fourchette_chiffre_repetee": (lambda n: "fourchette 1 " * (n // 13), False),
    "fourchette_puis_tiret_et_chiffres": (lambda n: "fourchette " + "1" * n + "-2", True),
    "fourchette_chiffres_espaces_tiret": (lambda n: "fourchette 1" + " " * n + "-" + " " * n + "x", False),
    "fourchette_chiffres_espaces_tiret_chiffre": (lambda n: "fourchette 1" + " " * n + "-" + " " * n + "2", True),
    "fourchette_groupes_puis_tiret": (lambda n: "fourchette " + "1 " * (n // 2) + "- 2", True),
    "taux": (lambda n: "1/" * (n // 2), False),
    "taux_espaces": (lambda n: "1 / " * (n // 4), False),
    "taux_puis_espaces": (lambda n: "1/" + " " * n + "x", False),
    "taux_lettres": (lambda n: "12/m" * (n // 4), False),
    "taux_au_bout": (lambda n: "1 " * (n // 2) + "/h", True),
}


@pytest.mark.parametrize("nom", TEXTES_HOSTILES_PRIX)
def test_le_prix_d_un_chiffrage_reste_lineaire_sur_un_texte_hostile(nom):
    fabrique, attendu = TEXTES_HOSTILES_PRIX[nom]
    assert _prix_apres(fabrique(PETIT)) is attendu
    _lineaire(lambda texte: contrats._PRIX_REGEX.search(texte), fabrique)


# ----------------------------------------------------------------------------------------------------------------------
# 3. Les fonctions de M1 qui lisent ces motifs
# ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "nom", ["points", "tirets", "lettres", "tous_les_caracteres_d_une_partie_locale", "points_arobase_points",
            "arobase_puis_points", "accentuee_puis_points", "espaces", "points_puis_courriel",
            "accentuees_puis_courriel", "accents_combinants_puis_courriel", "apostrophes_typographiques"])
def test_le_contact_du_texte_d_un_client_se_lit_en_temps_lineaire(nom):
    fabrique = TEXTES_HOSTILES_COURRIEL[nom][0]
    assert _contact_apres(fabrique(PETIT)) == _courriel_attendu(nom, PETIT)
    _lineaire(qualification.contact_du_texte, fabrique, essais=(3, 2))


@pytest.mark.parametrize(
    "nom", ["points", "lettres", "chiffres", "tous_les_caracteres_d_une_partie_locale", "arobase_puis_points",
            "arobase_puis_domaine_sans_fin", "espaces"])
def test_les_coordonnees_d_un_resume_se_lisent_en_temps_lineaire(nom):
    fabrique = TEXTES_HOSTILES_COURRIEL[nom][0]
    # une suite de sept chiffres ou plus est un numéro ; un domaine valide au bout d'une longue suite est un courriel
    assert transferts.contient_coordonnees(fabrique(PETIT)) is (nom in ("chiffres", "arobase_puis_domaine_sans_fin"))
    _lineaire(transferts.contient_coordonnees, fabrique, essais=(3, 2))


# ----------------------------------------------------------------------------------------------------------------------
# 4. Tout motif de M1, sur un texte hostile de la taille maximale de la réception
# ----------------------------------------------------------------------------------------------------------------------
def _motifs_de_m1() -> list[tuple[str, re.Pattern[str]]]:
    """Les motifs de niveau module de tous les modules de M1 (seuls ou en suite)."""
    trouves = []
    for module_info in pkgutil.iter_modules(m1_front_office.__path__):
        module = importlib.import_module(f"m1_front_office.{module_info.name}")
        for nom, valeur in vars(module).items():
            if isinstance(valeur, re.Pattern):
                trouves.append((f"{module_info.name}.{nom}", valeur))
            elif isinstance(valeur, (tuple, list)) and valeur and all(isinstance(v, re.Pattern) for v in valeur):
                trouves.extend((f"{module_info.name}.{nom}[{i}]", v) for i, v in enumerate(valeur))
    return trouves


BORNE_BALAYAGE = 0.4  # s par motif et par texte de PETIT caractères ; le temps linéaire mesuré est de l'ordre de 0,03 s
TEXTES_DU_BALAYAGE = {
    "chiffres": lambda n: "1" * n,
    "lettres": lambda n: "a" * n,
    "majuscules": lambda n: "A" * n,
    "points": lambda n: "a." * (n // 2),
    "tirets": lambda n: "a-" * (n // 2),
    "soulignes": lambda n: "a_" * (n // 2),
    "plus_un": lambda n: "+1" * (n // 2),
    "apostrophes": lambda n: "a'" * (n // 2),
    "arobases": lambda n: "a@" * (n // 2),
    "courriels": lambda n: "a@a." * (n // 4),
    "espaces": lambda n: " " * n,
    "chiffres_espaces": lambda n: "1 " * (n // 2),
    "chiffre_puis_espaces": lambda n: "1" + " " * n + "x",
    "parentheses": lambda n: "1(" * (n // 2),
    "decimales": lambda n: "1.1" * (n // 3),
    "virgules": lambda n: "1," * (n // 2),
    "chiffres_tirets": lambda n: "1-" * (n // 2),
    "chiffres_et_lettres": lambda n: "1a" * (n // 2),
    "mots": lambda n: "mot " * (n // 4),
    "points_espaces": lambda n: "a. " * (n // 3),
    "sauts_de_ligne": lambda n: "\n" * n,
    "crochets": lambda n: "[" * n,
    "exclamations": lambda n: "!" * n,
    "deux_points": lambda n: ":" * n,
    "accentuees": lambda n: "é" * n,
}


def _premier_texte_lent(motif: re.Pattern[str]) -> str | None:
    """Le premier texte du balayage que `motif` lit trop lentement (deux passages : PILOTE puis PETIT), ou `None`."""
    for nom_du_texte, fabrique in TEXTES_DU_BALAYAGE.items():
        for taille, borne in ((PILOTE, BORNE_PILOTE), (PETIT, BORNE_BALAYAGE)):
            texte = fabrique(taille)
            duree = _meilleur_temps(motif.search, texte, 1)
            if duree > borne:
                duree = min(duree, _meilleur_temps(motif.search, texte, 2))
            if duree > borne:
                return f"« {nom_du_texte} » de {taille} caractères : {duree:.2f} s"
    return None


def test_aucun_motif_de_m1_ne_ralentit_sur_un_texte_hostile_de_la_taille_maximale_de_la_reception():
    """Le balayage voit les motifs de tous les modules : celui qui relirait une suite à chaque départ (comme les trois
    d'avant T4.17-g, d'une demi-seconde à plus d'une minute pour ces textes) serait nommé ici, quel que soit son
    module. Un premier passage sur PILOTE caractères écarte vite un motif quadratique ; on s'arrête au troisième
    motif lent."""
    motifs = _motifs_de_m1()
    noms = {nom for nom, _ in motifs}
    assert {"qualification._EMAIL_REGEX", "contrats._PRIX_REGEX", "transferts._ARROBASE_ET_DOMAINE"} <= noms
    assert len(motifs) >= 25, "le balayage doit voir les motifs des modules de M1"
    lents = []
    for nom, motif in motifs:
        lent = _premier_texte_lent(motif)
        if lent is not None:
            lents.append(f"{nom} sur {lent}")
        if len(lents) >= 3:
            break
    assert lents == [], f"motifs trop lents : {lents}"
