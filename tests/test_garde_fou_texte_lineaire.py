"""Temps linéaire du garde-fou de texte (PLAN T4.17-f) : un texte hostile de 100 000 caractères ne bloque rien.

Le profil de M1 n'a pas de plafond de longueur, et la réception accepte 20 000 octets d'un client. Avant T4.17-f,
`MONTANT_MONETAIRE` relisait toute la suite de chiffres à chaque chiffre : 20 000 chiffres coûtaient 27 s (déni de
service par expression régulière). Ce fichier prouve trois choses.

1. Le sens n'a pas changé. Les motifs d'avant (recopiés ici, tels quels, comme oracle) et ceux du socle donnent le même
   verdict (et, pour le prix et le courriel de M7, le même extrait cité dans le refus) sur toutes les suites de jetons
   jusqu'à une longueur donnée, sur des textes tirés au hasard (graine fixe), et sur une table de cas nommés.
2. Aucun motif du socle ne contient plus « n'importe quoi » derrière un déclencheur (`.*`) : l'écriture qui relit la
   ligne à chaque déclencheur ne revient pas sans que ce test le dise.
3. Le temps croît comme le texte : les textes hostiles de 20 000 et de 100 000 caractères passent sous une borne
   absolue généreuse, et le rapport des temps reste loin du carré (25 pour cinq fois plus de texte).

Les textes sont fictifs (montants, phrases et noms inventés).
"""

from __future__ import annotations

import itertools
import random
import re
import time

import pytest

from opsys import garde_fou_texte as gft
from opsys.garde_fou_texte import confidentialite, engagements, promesses

FICTIF = True

NBSP, NNBSP = " ", " "

# ----------------------------------------------------------------------------------------------------------------------
# L'oracle : les motifs et le découpage tels qu'ils étaient avant T4.17-f (recopiés, jamais importés du socle).
# ----------------------------------------------------------------------------------------------------------------------
_SEP = r"[\x20  ]"
MONTANT_AVANT = re.compile(
    rf"""
    (?:{_SEP}*|\b)\d{{1,3}}(?:{_SEP}{{0,1}}\d{{3}})*(?:[.,]\d+)?\s*
    (?:\$|€|(?:CAD|dollars?|euros?)\b)
    |
    \$\s*\d{{1,3}}(?:{_SEP}{{0,1}}\d{{3}})*(?:[.,]\d+)?\b
    |
    \b\d+\s*(?:\$|CAD|€|dollars?|euros?)\s*/\s*(?:h|heure|pied\s+carré|m²)\b
    |
    \b(?:deux\s+mille|mille)\s+(?:dollars?|CAD|\$|€|euros?)\b
    |
    \bfourchette\b.*\b\d{{1,3}}(?:{_SEP}{{0,1}}\d{{3}})*(?:[.,]\d+)?\s*(?:à|et)\s*\d{{1,3}}(?:{_SEP}{{0,1}}\d{{3}})*(?:[.,]\d+)?\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
AVEU_AVANT = re.compile(
    r"""
    \bnotre\s+faute\b|
    \bnous\s+sommes\s+responsables?\b|
    \berreur\s+de\s+notre\s+part\b|
    \bon\s+[al]\s+mal\s+fait\b|
    \ba\s+commis\s+une\s+faute\b|
    \bnous\s+assumons\s+la\s+responsabilité\b|
    \bje\s+reconnais\s+que\s+nous\s+avons\s+mal\b|
    \bnous\s+prenons\s+le\s+blâme\b|
    \bc['’]est\s+une\s+erreur\s+de\s+notre\b|
    \ble\s+vice\s+est\s+dû?\s+à\s+notre\b|
    \bde\s+notre\s+fait\b|
    \bentièrement\s+de\s+notre\s+fait\b|
    \bnous\s+reconnaissons\s+que\b.*\berreur\b|
    \bnous\s+sommes\s+responsables\b.*\bdégâts\b|
    \bnous\s+assumons\b.*\bresponsabilité\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
_SEPARATEUR_AVANT = re.compile(r"\s*(?:[.!?;]|\n)\s*")
COURRIEL_AVANT = re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}")
PRIX_AVANT = re.compile(r"(?<!\d)(?<!\d )\d[\d ]*+(?:[.,]\d+)?\s*(?:\$|cad\b|dollars?\b|piastres?\b|€|euros?\b)")


def decouper_avant(texte: str) -> list[str]:
    return [p.strip() for p in _SEPARATEUR_AVANT.split(texte) if p.strip()]


# ----------------------------------------------------------------------------------------------------------------------
# 1. Le sens n'a pas changé
# ----------------------------------------------------------------------------------------------------------------------
JETONS = {
    "montant": ["1", "12", "123", "1234", " ", NBSP, ".", ",", "$", "CAD", "x"],
    "devise": ["0", "99", "000", "5", " ", NNBSP, ",", "€", "euros", "dollar", "s", "/", "h", "a"],
    "fourchette": ["fourchette ", "8 à ", "12", " ", "\n", "x", "a", "1234 et ", "8"],
    "fourchette_et_blancs": ["fourchette ", "8", "12,5", " ", "\n", "à", "et", "x", "a", "_", "$"],
}
LONGUEUR_MAX = {"montant": 5, "devise": 4, "fourchette": 5, "fourchette_et_blancs": 5}


@pytest.mark.parametrize("jeu", JETONS)
def test_le_montant_donne_les_memes_verdicts_que_l_ancienne_ecriture_sur_toutes_les_suites_de_jetons(jeu):
    ecarts = []
    total = refuses = 0
    for longueur in range(1, LONGUEUR_MAX[jeu] + 1):
        for suite in itertools.product(JETONS[jeu], repeat=longueur):
            texte = "".join(suite)
            avant = MONTANT_AVANT.search(texte) is not None
            apres = engagements.MONTANT_MONETAIRE.search(texte) is not None
            total += 1
            refuses += avant
            if avant != apres:
                ecarts.append((texte, avant, apres))
    assert not ecarts[:5], f"{len(ecarts)} écarts sur {total} textes, dont {ecarts[:5]}"
    assert refuses > 1000, "l'oracle doit refuser assez de textes pour que la comparaison prouve quelque chose"


JETONS_AVEU = [
    "nous assumons ", "nous reconnaissons que ", "nous\nassumons ", "responsabilité ", "erreur ", "dégâts ", "x ", "\n",
]


def test_l_aveu_donne_les_memes_verdicts_que_l_ancienne_ecriture_sur_toutes_les_suites_de_jetons():
    ecarts = []
    refuses = 0
    for longueur in range(1, 6):
        for suite in itertools.product(JETONS_AVEU, repeat=longueur):
            texte = "".join(suite)
            avant = AVEU_AVANT.search(texte) is not None
            apres = engagements.AVEU.search(texte) is not None
            refuses += avant
            if avant != apres:
                ecarts.append((texte, avant, apres))
    assert not ecarts[:5], f"{len(ecarts)} écarts, dont {ecarts[:5]}"
    assert refuses > 1000, "l'oracle doit refuser assez de textes pour que la comparaison prouve quelque chose"


def _texte_au_hasard(rng: random.Random, fragments: list[str], longueur_max: int) -> str:
    return "".join(rng.choice(fragments) for _ in range(rng.randint(1, longueur_max)))


def test_le_montant_et_l_aveu_donnent_les_memes_verdicts_que_l_ancienne_ecriture_sur_des_textes_tires_au_hasard():
    rng = random.Random(20260929)
    fragments = [
        "Le prix est ", "fourchette", " de ", "8 000", "12 000", " à ", " et ", "12" + NBSP + "500", "9 999,99", "$",
        " $", "€", "dollars", "CAD", "/h", "$/heure", " le pied carré", "mille", "deux mille", "\n", ". ", "1234567",
        "a", "_", "nous assumons", "nous reconnaissons que", "nous sommes responsables", "responsabilité", "erreur",
        "dégâts", " ", "٣٤٥", "１２３", "0", "45", "\t", "x",
    ]
    ecarts = []
    for _ in range(20_000):
        texte = _texte_au_hasard(rng, fragments, 14)
        if (MONTANT_AVANT.search(texte) is None) != (engagements.MONTANT_MONETAIRE.search(texte) is None):
            ecarts.append(("montant", texte))
        if (AVEU_AVANT.search(texte) is None) != (engagements.AVEU.search(texte) is None):
            ecarts.append(("aveu", texte))
    assert not ecarts[:5], f"{len(ecarts)} écarts, dont {ecarts[:5]}"


def test_le_decoupage_en_segments_donne_les_memes_segments_que_l_ancienne_ecriture():
    jetons = [".", "!", ";", "\n", "\r\n", " ", "\t", NBSP, "x", "à demain"]
    ecarts = []
    for longueur in range(1, 6):
        for suite in itertools.product(jetons, repeat=longueur):
            texte = "".join(suite)
            if decouper_avant(texte) != engagements.decouper_segments(texte):
                ecarts.append(texte)
    assert not ecarts[:5], f"{len(ecarts)} écarts, dont {ecarts[:5]}"


JETONS_COURRIEL = ["a", "b.c", "@", ".", "-", "_", " ", "1", "ca", "x@y.ca", "%", "+", "é"]


def test_le_courriel_donne_les_memes_verdicts_et_le_meme_extrait_que_l_ancienne_ecriture():
    """Le refus cite l'extrait trouvé : le même départ, donc le même texte, pas seulement le même verdict."""
    ecarts = []
    trouves = 0
    for longueur in range(1, 6):
        for suite in itertools.product(JETONS_COURRIEL, repeat=longueur):
            texte = "".join(suite)
            avant, apres = COURRIEL_AVANT.search(texte), confidentialite._COURRIEL.search(texte)
            trouves += avant is not None
            if (avant and avant.group(0)) != (apres and apres.group(0)):
                ecarts.append((texte, avant and avant.group(0), apres and apres.group(0)))
    assert not ecarts[:5], f"{len(ecarts)} écarts, dont {ecarts[:5]}"
    assert trouves > 1000


JETONS_PRIX = ["1", "12", "500", " ", "  ", "$", "cad", "dollars", ",", ".", "x", "€", "4 500 "]


def test_le_prix_de_m7_donne_les_memes_verdicts_et_le_meme_extrait_que_l_ancienne_ecriture():
    ecarts = []
    trouves = 0
    for longueur in range(1, 6):
        for suite in itertools.product(JETONS_PRIX, repeat=longueur):
            texte = "".join(suite)
            avant, apres = PRIX_AVANT.search(texte), promesses._PRIX[0].search(texte)
            trouves += avant is not None
            # `extrait` retire les blancs des deux bouts : le refus cite le même texte
            if (avant and avant.group(0).strip()) != (apres and apres.group(0).strip()):
                ecarts.append((texte, avant and avant.group(0), apres and apres.group(0)))
    assert not ecarts[:5], f"{len(ecarts)} écarts, dont {ecarts[:5]}"
    assert trouves > 1000


# ----------------------------------------------------------------------------------------------------------------------
# Le sens, en cas nommés
# ----------------------------------------------------------------------------------------------------------------------
MONTANTS_REFUSES = [
    "Le montant total est de 12 500 $.",
    "Cela vous coûtera 12500$.",
    "Environ 15 000 dollars",
    "12" + NBSP + "500 $",
    "12" + NNBSP + "500" + NNBSP + "$",
    "Le prix final est de 9 999,99 $.",
    "Le prix final est de 9 999.99 $.",
    "1 234 567 €",
    "3 euros",
    "1,5 dollar",
    "Entre 8 000 et 12 000 CAD",
    "5 CAD",
    "Nos services débutent à partir de 89 $/heure.",
    "La rénovation coûte 45 $ le pied carré.",
    "Notre tarif actuel est de 120 $/h.",
    "Ça vous coûtera environ deux mille dollars.",
    "mille euros",
    "$ 4 500",
    "$4500",
    "Il faut prévoir $ 30 000.",
    "La fourchette se situe de 20 000 à 25 000.",
    "La fourchette : 8 000 et 12 000",
    "La fourchette 8à12",
    "FOURCHETTE de 8,5 à 12,5",
    "La fourchette de départ, pour la toiture, est de 8 000\nà 12 000",  # le second nombre peut suivre un saut de ligne
    "fourchette fourchette fourchette de 8 à 12",  # plusieurs déclencheurs : le dernier trouve la cible
    "fourchettes ; la fourchette est de 8 à 12",
    "٣٤٥ $",  # chiffres arabes : \d les lit comme des chiffres
    "１２３ €",
]


@pytest.mark.parametrize("texte", MONTANTS_REFUSES)
def test_un_montant_est_refuse_comme_avant(texte):
    assert MONTANT_AVANT.search(texte) is not None, "l'oracle (l'ancienne écriture) refusait ce texte"
    assert engagements.MONTANT_MONETAIRE.search(texte) is not None


MONTANTS_NON_REFUSES = [
    "12 500",  # un nombre sans devise
    "Nous avons 12 500 clients satisfaits",
    "5 dollarsx",  # la devise doit finir le mot
    "12 dollars_",
    "$12abc",  # le nombre après « $ » doit finir le mot
    "$",
    "$ abc",
    "US$",
    "12 000 à 15 000",  # sans le mot « fourchette »
    "fourchette\n8 à 12",  # l'écart ne franchit pas le saut de ligne
    "fourchette a8 à 12",  # le premier nombre doit commencer un mot
    "fourchette 8 à 12x",  # le second doit finir un mot
    "fourchette 8 a 12",  # « a » n'est pas « à »
    "fourchette 8 ou 12",
    "fourchettes de 8 à 12",  # « fourchette » doit être un mot entier
    "trois cents $ de plus",  # aucun chiffre : pas de montant (le mot « cents » n'est pas lu)
]


@pytest.mark.parametrize("texte", MONTANTS_NON_REFUSES)
def test_ce_que_le_montant_ne_refusait_pas_n_est_toujours_pas_refuse(texte):
    assert MONTANT_AVANT.search(texte) is None, "l'oracle (l'ancienne écriture) laissait passer ce texte"
    assert engagements.MONTANT_MONETAIRE.search(texte) is None


def test_un_montant_est_refuse_par_le_profil_de_m1_meme_derriere_une_suite_de_chiffres_hostile():
    profil = gft.profil("m1", (gft.PRIX_MONTANT,))
    texte = "1 111 " * 3000 + "et un total de 5 $"
    assert [v.regle for v in gft.controler(texte, profil)] == ["REJ-INTERDIT-PRIX"]
    assert [v.regle for v in gft.controler("1 111 " * 3000, profil)] == []


def test_l_ecart_d_un_declencheur_ne_recouvre_jamais_un_autre_declencheur_mais_le_dernier_trouve_la_cible():
    motif = re.compile(engagements._apres_sur_la_meme_ligne(r"\bavant\b", r"\bapres\b"))
    assert motif.search("avant, puis quelque chose, puis apres")
    assert motif.search("avant avant avant apres")  # le dernier « avant » trouve la cible
    assert motif.search("avant\navant apres")  # la cible est sur la ligne du second déclencheur
    assert motif.search("apres avant") is None  # la cible précède le déclencheur
    assert motif.search("avant\napres") is None  # l'écart ne franchit pas le saut de ligne
    assert motif.search("avantage apres") is None  # le déclencheur est un mot entier
    declencheur_sur_deux_lignes = re.compile(engagements._apres_sur_la_meme_ligne(r"\bun\s+deux\b", r"\btrois\b"))
    assert declencheur_sur_deux_lignes.search("un\ndeux trois")  # le déclencheur peut contenir un saut de ligne
    assert declencheur_sur_deux_lignes.search("un deux x un\ndeux trois")  # le premier est masqué : le second trouve


AVEUX_A_ECART = [
    "Nous assumons pleinement notre responsabilité.",  # « nous assumons la responsabilité » (alternative fixe)
    "Nous assumons, dans cette affaire, toute la responsabilité",  # alternative à écart
    "Nous reconnaissons que, dans ce dossier, il y a une erreur",
    "nous assumons nous assumons nous assumons la responsabilité",
    "nous assumons x\nnous assumons responsabilité",
    "nous assumons\nx nous\nassumons responsabilité",  # le second déclencheur contient un saut de ligne
]


@pytest.mark.parametrize("texte", AVEUX_A_ECART)
def test_un_aveu_a_ecart_est_refuse_comme_avant(texte):
    assert AVEU_AVANT.search(texte) is not None
    assert engagements.AVEU.search(texte) is not None
    assert engagements._detecter_aveu(texte)


@pytest.mark.parametrize("texte", [
    "Nous assumons\nla suite. La responsabilité revient au client",
    "Nous reconnaissons que\nc'est une erreur",
    "responsabilité, puis nous assumons",
    "Nous assumons",
])
def test_un_aveu_dont_la_cible_est_sur_une_autre_ligne_ou_avant_n_est_pas_refuse_par_l_ecart(texte):
    assert AVEU_AVANT.search(texte) is None, "l'oracle (l'ancienne écriture) laissait passer ce texte"
    assert engagements.AVEU.search(texte) is None


def test_les_segments_gardent_les_dates_iso_et_ne_cassent_pas_sur_les_blancs():
    assert engagements.decouper_segments("installation prévue le 2026-08-14. Merci\nBonjour ; à demain!") == [
        "installation prévue le 2026-08-14", "Merci", "Bonjour", "à demain"]
    assert engagements.decouper_segments("  a  .  ; \n\n  b\r\n c ") == ["a", "b", "c"]
    assert engagements.decouper_segments("") == [] and engagements.decouper_segments(" \n . ; ") == []
    assert engagements.decouper_segments("un deux") == ["un deux"]


# ----------------------------------------------------------------------------------------------------------------------
# 2. Plus de « n'importe quoi » derrière un déclencheur
# ----------------------------------------------------------------------------------------------------------------------
def _motifs_du_paquet() -> list[tuple[str, re.Pattern[str]]]:
    trouves = []
    for nom_module in ("engagements", "promesses", "confidentialite", "droit"):
        module = getattr(gft, nom_module)
        for nom, valeur in vars(module).items():
            if isinstance(valeur, re.Pattern):
                trouves.append((f"{nom_module}.{nom}", valeur))
            elif isinstance(valeur, tuple) and valeur and all(isinstance(v, re.Pattern) for v in valeur):
                trouves.extend((f"{nom_module}.{nom}[{i}]", v) for i, v in enumerate(valeur))
    return trouves


def test_le_paquet_a_des_motifs_et_aucun_ne_contient_un_point_etoile():
    """`.*` derrière un déclencheur relit la fin de la ligne à chaque déclencheur (quadratique). Écriture permise :
    `engagements._apres_sur_la_meme_ligne`, dont l'écart ne recouvre jamais un autre déclencheur."""
    motifs = _motifs_du_paquet()
    noms = {nom for nom, _ in motifs}
    assert {"engagements.MONTANT_MONETAIRE", "engagements.AVEU", "promesses._PRIX[0]", "confidentialite._COURRIEL",
            "droit._AVIS_LEGAL"} <= noms, "le balayage doit voir les motifs des quatre modules"
    assert len(motifs) >= 30
    fautifs = [nom for nom, motif in motifs if ".*" in motif.pattern or ".+" in motif.pattern]
    assert fautifs == []


# ----------------------------------------------------------------------------------------------------------------------
# 3. Le temps croît comme le texte
# ----------------------------------------------------------------------------------------------------------------------
PETIT, GRAND = 20_000, 100_000
BORNE_ABSOLUE = 2.0  # s pour GRAND caractères ; le temps linéaire mesuré est de l'ordre de 0,01 à 0,2 s
RAPPORT_MAX = 15  # t(GRAND) / t(PETIT) : 5 si le temps est linéaire, 25 s'il est quadratique


def _meilleur_temps(fonction, texte: str, essais: int) -> float:
    meilleur = float("inf")
    for _ in range(essais):
        debut = time.perf_counter()
        fonction(texte)
        meilleur = min(meilleur, time.perf_counter() - debut)
    return meilleur


def _lineaire(fonction, fabrique, essais: tuple[int, int] = (5, 3)) -> tuple[float, float]:
    """Mesure `fonction` sur `fabrique(PETIT)` puis `fabrique(GRAND)` ; `AssertionError` si le temps n'est pas linéaire.

    Le meilleur de plusieurs essais écarte le bruit de la machine (ordonnanceur, ramasse-miettes). Si le rapport
    dépasse la limite, une seconde série remesure avant de conclure. Sous 10 ms, le petit texte ne dit rien du rapport :
    seule la borne absolue juge."""
    petit = _meilleur_temps(fonction, fabrique(PETIT), essais[0])
    assert petit < BORNE_ABSOLUE, f"{PETIT} caractères : {petit:.2f} s"
    grand = _meilleur_temps(fonction, fabrique(GRAND), essais[1])
    assert grand < BORNE_ABSOLUE, f"{GRAND} caractères : {grand:.2f} s ({petit * 1000:.0f} ms pour {PETIT})"
    if grand > RAPPORT_MAX * max(petit, 0.010):
        petit = min(petit, _meilleur_temps(fonction, fabrique(PETIT), essais[0]))
        grand = min(grand, _meilleur_temps(fonction, fabrique(GRAND), essais[1]))
    assert grand <= RAPPORT_MAX * max(petit, 0.010), (
        f"le temps n'est pas linéaire : {petit * 1000:.1f} ms pour {PETIT}, {grand * 1000:.1f} ms pour {GRAND} "
        f"(rapport {grand / max(petit, 1e-6):.1f} pour un texte cinq fois plus long)")
    return petit, grand


# Chaque texte hostile vise un motif : (nom, fabrique(n) -> texte d'environ n caractères).
TEXTES_HOSTILES = {
    "chiffres": lambda n: "1" * n,
    "chiffres_puis_lettre": lambda n: "1" * n + "a",
    "chiffres_puis_dollar": lambda n: "1" * n + " $",  # le montant est trouvé, au bout d'une longue suite
    "chiffres_espace": lambda n: "1 " * (n // 2),
    "groupes_de_milliers": lambda n: "1" + " 111" * (n // 4),
    "groupes_de_milliers_puis_lettre": lambda n: "1" + " 111" * (n // 4) + "a",
    "groupes_insecables": lambda n: ("111" + NBSP) * (n // 4),
    "groupes_fins_insecables": lambda n: ("111" + NNBSP) * (n // 4),
    "groupes_puis_devise_collee": lambda n: "12 " * (n // 3) + "5$",  # amont hostile, devise à la toute fin
    "decimales": lambda n: "1." + "1" * n,
    "decimales_puis_lettre": lambda n: "1." + "1" * n + "a",
    "chiffres_et_virgules": lambda n: "1,1" * (n // 3),
    "espaces": lambda n: " " * n,
    "espaces_puis_lettre": lambda n: " " * n + "x",
    "insecables": lambda n: NBSP * n,
    "fines_insecables": lambda n: NNBSP * n,
    "blancs_mixtes": lambda n: " \t\n\r\f\v" * (n // 6),
    "sauts_de_ligne": lambda n: "\n" * n,
    "chiffre_puis_espaces": lambda n: "1" + " " * n + "x",
    "dollar_puis_espaces": lambda n: "$" + " " * n,
    "dollars": lambda n: "$" * n,
    "dollar_espace": lambda n: "$ " * (n // 2),
    "chiffre_dollar": lambda n: "1$" * (n // 2),
    "dollar_chiffres": lambda n: "$" + "1" * n + "a",
    "lettres": lambda n: "a" * n,
    "points": lambda n: "." * n,
    "ponctuation_et_blancs": lambda n: ". " * (n // 2),
    "fourchettes": lambda n: "fourchette " * (n // 11),
    "fourchette_puis_chiffres": lambda n: "fourchette " + "1" * n,
    "fourchette_puis_chiffres_espaces": lambda n: "fourchette " + "1 " * (n // 2),
    "fourchette_chiffre_repetee": lambda n: "fourchette 1 " * (n // 13),
    "fourchette_a_repetee": lambda n: "fourchette 1 à " * (n // 15),
    "fourchette_puis_lettres": lambda n: "fourchette " + "a" * n,
    "fourchettes_par_lignes": lambda n: ("fourchette " * 50 + "\n") * (n // 551 + 1),
    "fourchettes_puis_cible": lambda n: "fourchette " * (n // 11) + "8 à 12",
    "nous_assumons": lambda n: "nous assumons " * (n // 14),
    "nous_assumons_puis_cible": lambda n: "nous assumons " * (n // 14) + "la responsabilité",
    "nous_reconnaissons": lambda n: "nous reconnaissons que " * (n // 23),
    "nous_sommes_responsables": lambda n: "nous sommes responsables " * (n // 25),
    "nous_assumons_par_lignes": lambda n: ("nous assumons " * 50 + "\n") * (n // 701 + 1),
    "prix_puis_nombres_colles": lambda n: "prix " + "1234a " * (n // 6),
    "prix_puis_chiffres": lambda n: "prix " + "1" * n,
    "dates_et_verbes": lambda n: "travaux " * (n // 8),
    "verbe_puis_espaces": lambda n: "travaux" + " " * n + "x",
    "delai_puis_chiffres": lambda n: "dans " + "1" * n,
}


@pytest.mark.parametrize("nom", TEXTES_HOSTILES)
def test_le_montant_le_prix_l_aveu_et_les_segments_restent_lineaires_sur_un_texte_hostile(nom):
    fabrique = TEXTES_HOSTILES[nom]

    def lire(texte: str) -> None:
        engagements.MONTANT_MONETAIRE.search(texte)
        engagements.GRAND_NOMBRE.search(texte)
        engagements.AVEU.search(texte)
        engagements.decouper_segments(texte)

    _lineaire(lire, fabrique)


PROFIL_M1 = gft.profil(
    "m1_lineaire", (gft.PRIX_MONTANT, gft.DATE_EXECUTION, gft.ENGAGEMENT, gft.AVEU, gft.AVIS_LEGAL))

# Ce que le profil de M1 rend pour chaque texte hostile de 20 000 caractères : la lecture est entière, pas abrégée.
VERDICTS_ATTENDUS = {
    "chiffres": [],
    "chiffres_puis_dollar": ["REJ-INTERDIT-PRIX"],
    "groupes_de_milliers": [],
    "espaces": [],
    "fourchettes": [],
    "fourchette_puis_chiffres": ["REJ-INTERDIT-PRIX"],  # mot-clé « fourchette » et un grand nombre
    "fourchettes_puis_cible": ["REJ-INTERDIT-PRIX"],
    "nous_assumons": [],
    "nous_assumons_puis_cible": ["REJ-INTERDIT-AVEU"],
    "groupes_puis_devise_collee": ["REJ-INTERDIT-PRIX"],
}


@pytest.mark.parametrize("nom", VERDICTS_ATTENDUS)
def test_le_profil_de_m1_lit_en_temps_lineaire_un_texte_hostile_et_rend_le_verdict_attendu(nom):
    fabrique = TEXTES_HOSTILES[nom]
    assert [v.regle for v in gft.controler(fabrique(PETIT), PROFIL_M1)] == VERDICTS_ATTENDUS[nom]
    _lineaire(lambda texte: gft.controler(texte, PROFIL_M1), fabrique, essais=(3, 2))


# ----------------------------------------------------------------------------------------------------------------------
# Le catalogue entier, sans plafond de longueur : un département qui choisit ces familles n'est pas bloqué non plus
# ----------------------------------------------------------------------------------------------------------------------
CONTEXTE_MARQUE = gft.Contexte(
    garanties_validees=("Garantie limitée de la main-d'œuvre",), noms_de_marque=("Synergy",),
    noms_clients=("Tremblay",), identifiants=("lead-4711",),
)
TOUT_SANS_PLAFOND = gft.profil(
    "tout_sans_plafond", [n for n in gft.FAMILLES if n not in (gft.TEXTE_VIDE, gft.LONGUEUR)])
TEXTES_HOSTILES_DU_CATALOGUE = {
    "lettres": lambda n: "a" * n,
    "chiffres_a_deux_espaces": lambda n: "1  " * (n // 3),
    "chiffres_separes_par_une_marque": lambda n: "1 Synergy " * (n // 10),  # le masque de marque laisse trois espaces
    "lettres_puis_arobase": lambda n: "a" * n + "@",
    "courriels_sans_fin": lambda n: "a@a." * (n // 4),
    "mots": lambda n: "mot " * (n // 4),
    "majuscules": lambda n: "Ab " * (n // 3),
    "coordonnees_gps": lambda n: "1.1234 " * (n // 7),
    "chez": lambda n: "chez Ab " * (n // 8),
    "garantie": lambda n: "garantie " * (n // 9),
}


@pytest.mark.parametrize("nom", TEXTES_HOSTILES_DU_CATALOGUE)
def test_chaque_famille_du_catalogue_lit_en_temps_lineaire_un_texte_hostile_sans_plafond(nom):
    fabrique = TEXTES_HOSTILES_DU_CATALOGUE[nom]
    _lineaire(lambda texte: gft.controler(texte, TOUT_SANS_PLAFOND, CONTEXTE_MARQUE), fabrique, essais=(2, 2))
