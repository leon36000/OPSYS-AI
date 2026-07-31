"""Batterie durable de mutations du contrôle 18 — copies déclarées du gate BMAD.

Le contrôle 18 (``verifier_copies_declarees``) n'a prouvé qu'il DÉTECTE qu'une
seule fois, à la main, lors de sa mise au point. Or une preuve dans un message
de commit n'est pas une preuve : un contrôle dont on ne revérifie plus la
détection devient décoratif — il reste vert et ne prouve plus rien. Ce fichier
rejoue donc la batterie à chaque run de la suite : il lit les deux artefacts
réels une seule fois, applique chaque mutation EN MÉMOIRE sur les chaînes,
puis appelle la fonction directement.

Aucune écriture de fichier, aucune copie, aucun sous-processus : muter les
documents suivis laisserait le dépôt corrompu si la suite était interrompue,
et une preuve qui réécrit ses propres artefacts ne serait pas reproductible.
Le gate n'étant pas un paquet installable, il est chargé par importlib depuis
son chemin réel dérivé de ``__file__`` — jamais du répertoire courant.
"""
import pytest

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _commun_gate import GATE, BRIEF, PRD, ARCHI

# Le corps des tests nomme le gate « VERIF_COHERENCE » : simple affectation
# pour conserver cet identifiant sans toucher à aucun test.
VERIF_COHERENCE = GATE

MUTATIONS = [
    {
        "libelle": "nullabilité de bareme_version retirée de l'architecture",
        "document": "archi",
        "avant": "  bareme_version: str | null",
        "apres": "  bareme_version: str",
        "doit_produire_un_message": True,
    },
    {
        "libelle": "niveau_confiance devient un int dans le PRD",
        "document": "prd",
        # Motif ÉTENDU : «  niveau_confiance: str » seul apparaît plusieurs
        # fois dans le PRD ; la ligne suivie de son commentaire est unique.
        "avant": "  niveau_confiance: str\n    # Enum",
        "apres": "  niveau_confiance: int\n    # Enum",
        "doit_produire_un_message": True,
    },
    {
        "libelle": "seuil MULTI_VUES passé de 3 à 4 photos",
        "document": "archi",
        "avant": "| `MULTI_VUES` | Au moins 3 photos",
        "apres": "| `MULTI_VUES` | Au moins 4 photos",
        "doit_produire_un_message": True,
    },
    {
        "libelle": "booléen False remplacé par True dans une table de l'architecture",
        "document": "archi",
        "avant": "calculé. | `False` |",
        "apres": "calculé. | `True` |",
        "doit_produire_un_message": True,
    },
    {
        "libelle": "copie de la section 5 toujours présente mais plus déclarée",
        "document": "archi",
        "avant": "Copié mot pour mot du PRD section 5.",
        "apres": "Repris du PRD section 5.",
        "doit_produire_un_message": True,
    },
    {
        "libelle": "déclaration de la copie de la section 4.2 effacée",
        "document": "archi",
        "avant": "Copié mot pour mot du PRD section 4.2.",
        "apres": "Table des verdicts.",
        "doit_produire_un_message": True,
    },
    {
        "libelle": "déclaration pointant vers la section inexistante 9.9 (fail-closed)",
        "document": "archi",
        "avant": "Copié mot pour mot du PRD section 4.1.",
        "apres": "Copié mot pour mot du PRD section 9.9.",
        "doit_produire_un_message": True,
    },
    {
        "libelle": "table parasite entre la déclaration 4.1 et la table des valeurs",
        "document": "archi",
        "avant": "Copié mot pour mot du PRD section 4.1.\n\n| Valeur",
        "apres": (
            "Copié mot pour mot du PRD section 4.1.\n\n"
            "| Autre | Table |\n|---|---|\n| x | y |\n\n"
            "| Valeur"
        ),
        "doit_produire_un_message": True,
    },
]


@pytest.mark.parametrize(
    "mutation", MUTATIONS, ids=[m["libelle"] for m in MUTATIONS]
)
def test_le_controle_detecte_chaque_mutation(mutation):
    """Chaque mutation en mémoire doit produire (ou non) les messages prévus."""
    documents = {"prd": PRD, "archi": ARCHI}
    cible = documents[mutation["document"]]
    occurrences = cible.count(mutation["avant"])
    assert occurrences == 1, (
        f"mutation « {mutation['libelle']} » : le motif AVANT apparaît "
        f"{occurrences} fois dans le document « {mutation['document']} » — "
        "la mutation ne muterait rien (ou serait ambiguë) et le test serait "
        "vert pour rien"
    )
    mutes = dict(documents)
    mutes[mutation["document"]] = cible.replace(
        mutation["avant"], mutation["apres"], 1
    )
    messages = VERIF_COHERENCE.verifier_copies_declarees(mutes["prd"], mutes["archi"])
    attendu = (
        "produire au moins un message"
        if mutation["doit_produire_un_message"]
        else "ne produire aucun message"
    )
    assert bool(messages) == mutation["doit_produire_un_message"], (
        f"mutation « {mutation['libelle']} » : le contrôle devait {attendu} ; "
        f"messages obtenus : {messages}"
    )


def test_le_controle_est_vert_sur_les_documents_reels():
    """Sans mutation, aucun message — sinon « mordre » ne prouverait rien."""
    messages = VERIF_COHERENCE.verifier_copies_declarees(PRD, ARCHI)
    assert messages == [], (
        "le contrôle 18 est rouge sur les documents réels ; une mutation qui "
        "mord ne prouverait alors plus rien, le contrôle étant rouge en "
        f"permanence. Messages : {messages}"
    )


def test_une_declaration_citee_dans_un_bloc_est_ignoree():
    """Une déclaration citée en exemple dans un bloc ```text n'est pas un engagement."""
    import re

    motif = re.compile(r"^### \d+\.\d+ Maillon du registre\b.*$", re.MULTILINE)
    correspondances = list(motif.finditer(ARCHI))
    assert len(correspondances) == 1, (
        "un titre de niveau 3 « Maillon du registre » (numéro quelconque de "
        "la forme <entier>.<entier>) doit apparaître exactement une fois "
        f"dans l'architecture — {len(correspondances)} occurrence(s) "
        "trouvée(s) — sinon l'insertion ne mute rien et le test serait vert "
        "pour rien. L'ancrage se fait sur le NOM de la section, jamais sur "
        "son numéro : une renumérotation a déjà cassé la version ancrée sur "
        "le numéro"
    )
    citation = (
        "### Exemple de déclaration (citation, pas un engagement)\n\n"
        "```text\n"
        "Copié mot pour mot du PRD section 1.\n"
        "```\n\n"
    )
    debut = correspondances[0].start()
    archi_mute = ARCHI[:debut] + citation + ARCHI[debut:]
    messages = VERIF_COHERENCE.verifier_copies_declarees(PRD, archi_mute)
    assert messages == [], (
        "une déclaration citée dans un bloc clôturé de langue text doit être "
        "ignorée — c'est du code, pas un engagement. Messages : "
        f"{messages}"
    )


def test_un_artefact_parasite_apres_la_copie_rend_la_zone_ambigue():
    """Un artefact parasite APRÈS la copie déclarée doit rendre la zone ambiguë.

    La mutation paramétrée « table parasite » place le parasite AVANT le vrai
    artefact : sans la garde de refus des zones ambiguës, le contrôle retient
    le parasite, ne le retrouve pas dans le PRD et échoue quand même — il
    mord, mais pour la mauvaise raison. Placé APRÈS le vrai artefact, c'est
    celui-ci qui serait retenu sans la garde : l'appariement réussirait et le
    contrôle passerait au vert alors qu'un second artefact non vérifié est
    présent. C'est le seul agencement qui discrimine cette garde.
    """
    ancre = "| `INDETERMINE` | **Échappatoire D-032** — les métadonnées fournies"
    occurrences = ARCHI.count(ancre)
    assert occurrences == 1, (
        f"la ligne d'ancrage « {ancre} » apparaît {occurrences} fois dans "
        "l'architecture — l'insertion serait ambiguë (ou ne muterait rien) et "
        "le test serait vert pour rien"
    )
    debut = ARCHI.index(ancre)
    fin_ligne = ARCHI.find("\n", debut)
    assert fin_ligne != -1, (
        "la ligne d'ancrage n'est suivie d'aucun saut de ligne — insertion "
        "après elle impossible, le test ne muterait rien"
    )
    parasite = "\n\n| Autre | Table |\n|---|---|\n| x | y |"
    archi_mute = ARCHI[:fin_ligne] + parasite + ARCHI[fin_ligne:]
    messages = VERIF_COHERENCE.verifier_copies_declarees(PRD, archi_mute)
    assert messages, (
        "un artefact parasite placé APRÈS la copie déclarée doit rendre la "
        "zone ambiguë et être refusé ; sans message, le contrôle a retenu le "
        "premier artefact, l'a apparié et a ignoré le second — la garde de "
        "refus des zones ambiguës ne mord plus"
    )


def test_une_architecture_sans_copie_ni_declaration_est_refusee():
    """Une architecture sans copie ni déclaration doit être refusée (vacuité).

    Ce cas est le SEUL qui isole la garde de vacuité : dès qu'une copie exacte
    subsiste dans l'architecture, c'est la passe 2 (copie présente mais non
    déclarée) qui parle, pas elle. Les mutations existantes laissent toujours
    au moins une déclaration, et retirer TOUTES les déclarations serait de
    toute façon rattrapé par la passe 2 puisque les copies exactes subsistent.
    Seule une architecture synthétique — sans déclaration ni artefact —
    exerce la garde seule.
    """
    archi_synthetique = (
        "# Architecture synthétique de test\n"
        "\n"
        "Ce document ne reprend aucune section du PRD : chaque règle y est\n"
        "reformulée librement, sans table ni passage cité mot à mot.\n"
    )
    messages = VERIF_COHERENCE.verifier_copies_declarees(PRD, archi_synthetique)
    assert messages, (
        "une architecture sans copie ni déclaration doit être refusée par la "
        "garde de vacuité ; sans message, une architecture vide de tout "
        "engagement passerait pour conforme — vert-par-vacuité"
    )
    assert "déclaration" in messages[0], (
        "le premier message doit mentionner l'absence de déclaration ; "
        f"message obtenu : {messages[0]!r}"
    )


# Trois gardes du contrôle 18 encore non exercées — MESURÉ garde par garde


def test_un_leurre_de_genre_different_ne_sert_pas_de_source():
    """Un leurre de genre différent ne doit pas servir de source à l'appariement.

    Test « le vert doit rester vert » : il échoue si le critère qu'il protège
    — l'exigence du même genre — disparaît. Sur les documents réels, l'artefact
    visé est le PREMIER de sa section : l'appariement n'a jamais à choisir et
    le critère de genre ne sert à rien. Ici, un bloc clôturé de langue text
    dont la première ligne de contenu est exactement l'en-tête de la vraie
    table est inséré juste avant elle dans la section 4.1 du PRD : sans le
    critère de genre, l'appariement retiendrait ce leurre comme source, le
    comparerait à la copie de l'architecture et échouerait ; avec, il saute le
    leurre et retrouve la vraie table — le contrôle doit donc rester vert.
    """
    entete = "| Valeur | Condition d'obtention |"
    occurrences = PRD.count(entete)
    assert occurrences == 1, (
        f"l'en-tête « {entete} » de la table NiveauConfiance apparaît "
        f"{occurrences} fois dans le PRD — l'insertion du leurre serait "
        "ambiguë (ou ne muterait rien) et le test serait vert pour rien"
    )
    leurre = (
        "\n```text\n"
        f"{entete}\n"
        "| ceci est un leurre : pas la vraie table |\n"
        "```\n\n"
    )
    prd_mute = PRD.replace(entete, leurre + entete, 1)
    messages = VERIF_COHERENCE.verifier_copies_declarees(prd_mute, ARCHI)
    assert messages == [], (
        "un leurre de genre différent (bloc clôturé) partageant la première "
        "ligne de la vraie table ne doit pas servir de source : l'appariement "
        "exige le même genre, saute le leurre et retrouve la vraie table. "
        f"Messages : {messages}"
    )


def test_un_leurre_de_meme_genre_mais_autre_entete_ne_sert_pas_de_source():
    """Un leurre de même genre mais d'en-tête différente ne doit pas servir de source.

    Test « le vert doit rester vert » : il échoue si le critère qu'il protège
    — l'exigence de la même première ligne — disparaît. Sur les documents
    réels, l'artefact visé est le PREMIER de sa section : l'appariement n'a
    jamais à choisir et le critère de la première ligne ne sert à rien. Ici,
    une table dont la ligne d'en-tête diffère est insérée juste avant la vraie
    table dans la section 4.1 du PRD : sans le critère de la première ligne,
    l'appariement retiendrait ce leurre comme source, le comparerait à la copie
    de l'architecture et échouerait ; avec, il saute le leurre et retrouve la
    vraie table — le contrôle doit donc rester vert.
    """
    entete = "| Valeur | Condition d'obtention |"
    occurrences = PRD.count(entete)
    assert occurrences == 1, (
        f"l'en-tête « {entete} » de la table NiveauConfiance apparaît "
        f"{occurrences} fois dans le PRD — l'insertion du leurre serait "
        "ambiguë (ou ne muterait rien) et le test serait vert pour rien"
    )
    leurre = (
        "\n| Code | Libellé |\n"
        "|---|---|\n"
        "| x | y |\n"
        "\n"
    )
    prd_mute = PRD.replace(entete, leurre + entete, 1)
    messages = VERIF_COHERENCE.verifier_copies_declarees(prd_mute, ARCHI)
    assert messages == [], (
        "un leurre de même genre (table) mais d'en-tête différente ne doit "
        "pas servir de source : l'appariement exige la même première ligne, "
        "saute le leurre et retrouve la vraie table. "
        f"Messages : {messages}"
    )


def test_une_copie_tronquee_a_la_fin_est_detectee():
    """Une copie tronquée à la fin doit être détectée par le contrôle des longueurs.

    Les mutations paramétrées altèrent une ligne AU MILIEU de la copie : c'est
    la comparaison ligne à ligne qui parle, jamais le contrôle des longueurs.
    Ici, les deux dernières lignes de la copie EstimationV1 sont retirées de
    l'architecture : le préfixe commun reste identique et seules les longueurs
    diffèrent — seul le contrôle des longueurs peut mordre.
    """
    motif = (
        "  hash_maillon: str\n"
        "    # sha256 du maillon append-only dans le registre estimé-vs-réel."
    )
    occurrences = ARCHI.count(motif)
    assert occurrences == 1, (
        "les deux dernières lignes de la copie EstimationV1 apparaissent "
        f"{occurrences} fois dans l'architecture — la troncature serait "
        "ambiguë (ou ne muterait rien) et le test serait vert pour rien"
    )
    archi_mute = ARCHI.replace("\n" + motif, "", 1)
    messages = VERIF_COHERENCE.verifier_copies_declarees(PRD, archi_mute)
    assert messages, (
        "une copie tronquée de ses deux dernières lignes doit être détectée : "
        "le préfixe commun est identique, seules les longueurs diffèrent — "
        "sans message, le contrôle des longueurs ne mord plus"
    )
    assert any("longueur" in message for message in messages), (
        "le message de détection doit mentionner les longueurs — c'est le "
        "contrôle des longueurs qui doit parler, pas la comparaison ligne à "
        f"ligne. Messages : {messages}"
    )


_PRD_SYNTHETIQUE = "# PRD\n\n## 1. Section\n\n| Valeur | Sens |\n|---|---|\n| A | un |\n"
_ARCHI_SYNTHETIQUE = ("# Archi\n\n## Copie\n\nCopié mot pour mot du PRD section 1.\n\n"
                      "| Valeur | Sens |\n|---|---|\n| A | un |\n")


def test_un_bloc_non_ferme_est_masque_jusqua_la_fin():
    """Un bloc clôturé jamais refermé doit être masqué jusqu'à la fin du document — sans ce test, un scanner qui traiterait la fin de fichier comme une clôture implicite laisserait le faux titre et la fausse déclaration fuiter du bloc, et le cas de bord le plus structurant du masquage casserait en silence."""
    messages_nu = VERIF_COHERENCE.verifier_copies_declarees(
        _PRD_SYNTHETIQUE, _ARCHI_SYNTHETIQUE
    )
    assert messages_nu == [], (
        "le couple synthétique nu doit être vert — sinon ce test « reste "
        f"vert » ne prouverait rien. Messages : {messages_nu}"
    )
    archi_bloc_non_ferme = _ARCHI_SYNTHETIQUE + "\n## Exemple\n\n```text\n# faux titre\nCopié mot pour mot du PRD section 9.\n"
    messages = VERIF_COHERENCE.verifier_copies_declarees(
        _PRD_SYNTHETIQUE, archi_bloc_non_ferme
    )
    assert messages == [], (
        "un bloc clôturé jamais refermé doit être masqué jusqu'à la fin du "
        "document : ni le faux titre ni la fausse déclaration qu'il contient "
        f"ne doivent exister pour le contrôle. Messages : {messages}"
    )
    archi_temoin = _ARCHI_SYNTHETIQUE + "\n## Exemple\n\n# faux titre\nCopié mot pour mot du PRD section 9.\n"
    messages_temoin = VERIF_COHERENCE.verifier_copies_declarees(
        _PRD_SYNTHETIQUE, archi_temoin
    )
    assert messages_temoin, (
        "témoin : les deux mêmes lignes placées HORS de tout bloc doivent "
        "produire au moins un message — sans ce témoin, le test serait vert "
        "même si le masquage masquait tout et n'importe quoi"
    )


def test_un_bloc_imbrique_ne_ferme_pas_le_bloc_englobant():
    """Une clôture de trois accents ne doit pas fermer un bloc ouvert à quatre — sans ce test, un scanner qui accepterait une clôture plus courte que l'ouverture refermerait le bloc englobant sur le bloc imbriqué et exposerait le faux titre."""
    messages_nu = VERIF_COHERENCE.verifier_copies_declarees(
        _PRD_SYNTHETIQUE, _ARCHI_SYNTHETIQUE
    )
    assert messages_nu == [], (
        "le couple synthétique nu doit être vert — sinon ce test « reste "
        f"vert » ne prouverait rien. Messages : {messages_nu}"
    )
    archi_bloc_imbrique = _ARCHI_SYNTHETIQUE + (
        "\n## Exemple\n\n````text\n```\n"
        "Copié mot pour mot du PRD section 9.\n```\n````\n"
    )
    messages = VERIF_COHERENCE.verifier_copies_declarees(
        _PRD_SYNTHETIQUE, archi_bloc_imbrique
    )
    assert messages == [], (
        "une clôture de trois accents ne doit pas fermer un bloc ouvert à "
        "quatre : la déclaration placée après la clôture courte doit rester "
        "masquée. Une clôture plus courte referme sinon le bloc englobant, "
        "la déclaration devient un engagement et cite une section absente. "
        f"Messages : {messages}"
    )


def test_une_cloture_indentee_ouvre_et_ferme_un_bloc():
    """Une clôture précédée de deux espaces doit ouvrir et fermer un bloc comme une clôture en colonne zéro — sans ce test, un scanner qui exigerait la colonne zéro ne masquerait aucun bloc indenté et le faux titre fuiterait."""
    messages_nu = VERIF_COHERENCE.verifier_copies_declarees(
        _PRD_SYNTHETIQUE, _ARCHI_SYNTHETIQUE
    )
    assert messages_nu == [], (
        "le couple synthétique nu doit être vert — sinon ce test « reste "
        f"vert » ne prouverait rien. Messages : {messages_nu}"
    )
    archi_cloture_indentee = _ARCHI_SYNTHETIQUE + (
        "\n## Exemple\n\n  ```text\n"
        "Copié mot pour mot du PRD section 9.\n  ```\n"
    )
    messages = VERIF_COHERENCE.verifier_copies_declarees(
        _PRD_SYNTHETIQUE, archi_cloture_indentee
    )
    assert messages == [], (
        "les clôtures précédées de deux espaces doivent ouvrir et fermer un "
        "bloc : la déclaration qu'il contient doit rester masquée. Un scanner "
        "exigeant la colonne zéro en ferait un engagement citant une section "
        "absente. "
        f"Messages : {messages}"
    )


def test_un_titre_indente_borne_bien_la_zone():
    """Un titre indenté de deux espaces doit borner la zone de copie exactement comme un titre en colonne zéro — sans ce test, la seconde table serait rattachée à la zone déclarée, la rendrait ambiguë, et le contrôle mordrait des documents conformes."""
    messages_nu = VERIF_COHERENCE.verifier_copies_declarees(
        _PRD_SYNTHETIQUE, _ARCHI_SYNTHETIQUE
    )
    assert messages_nu == [], (
        "le couple synthétique nu doit être vert — sinon ce test « reste "
        f"vert » ne prouverait rien. Messages : {messages_nu}"
    )
    archi_titre_indente = (
        "# Archi\n\n## Copie\n\nCopié mot pour mot du PRD section 1.\n\n"
        "| Valeur | Sens |\n|---|---|\n| A | un |\n\n  ## Suite\n\n| Autre | Table |\n|---|---|\n| x | y |\n"
    )
    messages = VERIF_COHERENCE.verifier_copies_declarees(
        _PRD_SYNTHETIQUE, archi_titre_indente
    )
    assert messages == [], (
        "le titre indenté de deux espaces est un vrai titre : il ferme la "
        "zone de copie, et la seconde table ne doit pas y être rattachée — "
        "sinon la zone serait ambiguë et le contrôle mordrait un document "
        f"conforme. Messages : {messages}"
    )
    assert "\n  ## Suite\n" in archi_titre_indente, (
        "le titre indenté doit être présent dans l'architecture de test — "
        "sinon la désindentation ne muterait rien et la comparaison serait "
        "verte pour rien"
    )
    archi_titre_desindente = archi_titre_indente.replace(
        "\n  ## Suite\n", "\n## Suite\n", 1
    )
    messages_desindente = VERIF_COHERENCE.verifier_copies_declarees(
        _PRD_SYNTHETIQUE, archi_titre_desindente
    )
    assert messages_desindente == [], (
        "le même titre désindenté doit borner la zone de la même façon : "
        "les deux formes sont des titres et ferment la zone de copie. "
        f"Messages : {messages_desindente}"
    )


def test_un_titre_de_section_indente_est_reconnu_dans_le_prd():
    """Un titre de section indenté de deux espaces dans le PRD doit être reconnu comme un vrai titre et résoudre la section citée exactement comme en colonne zéro — sans ce test, une regex de titre sans tolérance d'indentation ne trouve pas la section citée et le contrôle échoue sur un document pourtant valide."""
    prd_indente = "# PRD\n\n  ## 1. Section\n\n| Valeur | Sens |\n|---|---|\n| A | un |\n"
    messages = VERIF_COHERENCE.verifier_copies_declarees(
        prd_indente, _ARCHI_SYNTHETIQUE
    )
    assert messages == [], (
        "le titre de section indenté de deux espaces est un vrai titre "
        "markdown : la section 1 du PRD doit être résolue, sa table trouvée "
        "et appariée à la copie déclarée de l'architecture — sinon une regex "
        "de titre exigeant la colonne zéro rate la section et le contrôle "
        f"mord un document conforme. Messages : {messages}"
    )
    messages_non_indente = VERIF_COHERENCE.verifier_copies_declarees(
        _PRD_SYNTHETIQUE, _ARCHI_SYNTHETIQUE
    )
    assert messages_non_indente == [], (
        "le même PRD à titre non indenté doit donner le même résultat : les "
        "deux formes résolvent la même section — sans cette seconde "
        "assertion, le test passerait tout aussi bien si la résolution "
        f"ignorait le PRD. Messages : {messages_non_indente}"
    )


def test_un_retour_chariot_dans_une_cellule_ne_tronque_pas_l_appariement():
    """Un retour chariot dans une cellule ne doit pas tronquer la première ligne d'un artefact lors de l'appariement — sans ce test, un retour à .splitlines(), qui coupe aussi sur « \r » seul, tronquerait l'en-tête à « | A », apparierait le leurre et déclarerait divergente une copie exacte, et la régression passerait inaperçue."""
    prd = "# PRD\n\n## 1. Section\n\n| A\n|---|---|\n| leurre | ici |\n\n| A\rZ | un |\n|---|---|\n| vrai | la |\n"
    archi = "# Archi\n\n## Copie\n\nCopié mot pour mot du PRD section 1.\n\n| A\rZ | un |\n|---|---|\n| vrai | la |\n"
    messages = VERIF_COHERENCE.verifier_copies_declarees(prd, archi)
    assert messages == [], (
        "la copie est exacte : l'appariement doit retenir la seconde table du "
        "PRD, pas le leurre — une notion de ligne qui coupe sur « \r » (comme "
        ".splitlines()) tronquerait la première ligne de l'artefact à « | A », "
        "retiendrait le leurre comme source et déclarerait divergente une "
        f"copie pourtant exacte. Messages : {messages}"
    )
