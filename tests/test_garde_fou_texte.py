"""Garde-fou de texte du socle (PLAN T4.17-c) : un catalogue de familles nommées, que chaque département choisit.

Le module est pur : ces tests n'ouvrent ni base ni réseau. Les textes sont fictifs (noms, adresses et montants
inventés). Les corpus de M1 (44 textes interdits, 22 légitimes) et les tests du contrôle de M7 prouvent, de leur côté,
que les deux départements rendent les mêmes verdicts qu'avant le déplacement ; ici, on prouve le socle lui-même :
chaque famille refuse en se nommant, le choix des familles change le verdict, l'ordre est fixe, rien ne sort du module.
"""

from __future__ import annotations

import ast
import time
import tomllib
from pathlib import Path

import pytest

from opsys import garde_fou_texte as gft
from opsys.garde_fou_texte import Contexte, Famille, Profil

FICTIF = True

TOUT = gft.profil("tout", gft.FAMILLES)
FAMILLES_TEXTE_PUBLIC = (
    gft.TEXTE_VIDE, gft.LONGUEUR, gft.LIEN, gft.ADRESSE, gft.COORDONNEES, gft.NOM_CLIENT, gft.IDENTIFIANT_INTERNE,
    gft.PRIX_OFFRE, gft.CHIFFRE_NON_SOURCE, gft.GARANTIE_NON_VALIDEE, gft.PROMESSE_DE_DATE, gft.EXAGERATION,
)
RACINE_MODULE = Path(gft.__file__).parent

# (famille, un texte qu'elle refuse, un texte que la MÊME famille laisse passer)
CAS = [
    (gft.TEXTE_VIDE, "  \n ", "Bonjour"),
    (gft.LIEN, "Voir https://exemple-fictif.ca/soumission", "Voir notre bio"),
    (gft.ADRESSE, "Gouttières installées au 1234 rue des Érables", "Gouttières installées à Laval"),
    (gft.COORDONNEES, "Écrivez à client.fictif@exemple-fictif.ca", "Écrivez-nous"),
    (gft.COORDONNEES, "Appelez le (450) 555-0100", "Appelez-nous"),
    (gft.NOM_CLIENT, "Merci à la famille Bouchard", "Merci à notre client"),
    (gft.PRIX_MONTANT, "Le montant total est de 12 500 $.", "Un estimateur vous fournira le prix précis."),
    (gft.PRIX_OFFRE, "Soumission gratuite pour tous", "Une soumission détaillée"),
    (gft.CHIFFRE_NON_SOURCE, "Nous avons posé 150 pieds de gouttières", "Nous avons posé des gouttières"),
    (gft.GARANTIE_NON_VALIDEE, "Une garantie à vie sur la main-d'œuvre", "Un travail soigné"),
    (gft.DATE_EXECUTION, "Les travaux seront terminés demain.", "Nous vous rappelons demain."),
    (gft.PROMESSE_DE_DATE, "On revient la semaine prochaine", "On revient"),
    (gft.EXAGERATION, "Le meilleur service au Québec", "Un service fiable"),
    (gft.ENGAGEMENT, "Nous nous engageons à terminer", "Nous étudions votre projet"),
    (gft.AVEU, "C'est notre faute, nous sommes responsables", "Merci pour votre retour constructif"),
    (gft.AVIS_LEGAL, "Vous avez le droit de refuser de payer.", "Nous avons bien reçu votre message"),
]

CONTEXTE_LONGUEUR = Contexte(longueur_max=20)
CONTEXTE_IDENTIFIANTS = Contexte(identifiants=("lead-4711",))
CONTEXTE_NOMS = Contexte(noms_clients=("Tremblay",))


def _regles(texte: str, profil: Profil, contexte: Contexte | None = None) -> list[str]:
    return [v.regle for v in gft.controler(texte, profil, contexte)]


# -- le catalogue --------------------------------------------------------------------------------------------------
def test_chaque_famille_a_un_nom_un_code_de_refus_unique_et_un_libelle():
    familles = list(gft.FAMILLES.values())
    assert len(familles) == 17
    assert len({f.nom for f in familles}) == len(familles)
    assert len({f.regle for f in familles}) == len(familles)  # un code de refus par famille : il nomme la règle
    assert all(f.regle.startswith("REJ-") and f.libelle and f.nom == cle for cle, f in gft.FAMILLES.items())


def test_les_codes_de_refus_sont_ceux_que_m1_et_m7_rendaient_deja():
    """Rien ne change pour un département qui rend le code d'une famille : ses verdicts, corpus et tests tiennent."""
    codes = {nom: f.regle for nom, f in gft.FAMILLES.items()}
    assert codes[gft.PRIX_MONTANT] == "REJ-INTERDIT-PRIX" and codes[gft.PRIX_OFFRE] == "REJ-PRIX"
    assert codes[gft.DATE_EXECUTION] == "REJ-INTERDIT-DATE" and codes[gft.PROMESSE_DE_DATE] == "REJ-PROMESSE-DE-DATE"
    assert codes[gft.ENGAGEMENT] == "REJ-INTERDIT-ENGAGEMENT" and codes[gft.AVEU] == "REJ-INTERDIT-AVEU"
    assert codes[gft.AVIS_LEGAL] == "REJ-INTERDIT-AVIS-LEGAL"
    assert codes[gft.ADRESSE] == "REJ-ADRESSE" and codes[gft.NOM_CLIENT] == "REJ-NOM-CLIENT"
    assert codes[gft.GARANTIE_NON_VALIDEE] == "REJ-GARANTIE-NON-VALIDEE" and codes[gft.LIEN] == "REJ-LIEN"


def test_l_ordre_du_catalogue_est_celui_d_evaluation_de_m1_puis_de_m7():
    noms = list(gft.FAMILLES)
    m1 = [gft.PRIX_MONTANT, gft.DATE_EXECUTION, gft.ENGAGEMENT, gft.AVEU, gft.AVIS_LEGAL]
    for ordre in (m1, list(FAMILLES_TEXTE_PUBLIC)):
        assert [n for n in noms if n in ordre] == ordre


def test_un_nom_ou_un_code_de_refus_en_double_est_refuse_a_l_import_du_catalogue():
    def detecteur(formes, contexte):
        return None

    un, autre = Famille("un", "REJ-UN", "x", detecteur), Famille("autre", "REJ-AUTRE", "y", detecteur)
    assert list(gft._indexer((un, autre))) == ["un", "autre"]
    with pytest.raises(ValueError, match="en double"):
        gft._indexer((un, Famille("un", "REJ-AUTRE-CODE", "z", detecteur)))  # même nom
    with pytest.raises(ValueError, match="en double"):
        gft._indexer((un, Famille("autre", "REJ-UN", "z", detecteur)))  # même code de refus


def test_le_catalogue_ne_se_modifie_pas_de_l_exterieur():
    with pytest.raises(TypeError):
        gft.FAMILLES["intrus"] = Famille("intrus", "REJ-INTRUS", "x", lambda formes, contexte: None)  # type: ignore[index]


# -- chaque famille refuse en se nommant, et laisse passer un texte propre --------------------------------------------
@pytest.mark.parametrize(("famille", "fautif", "propre"), CAS)
def test_chaque_famille_refuse_son_texte_en_nommant_sa_regle(famille, fautif, propre):
    seule = gft.profil("seule", (famille,))
    violations = gft.controler(fautif, seule)
    assert [v.famille for v in violations] == [famille]
    assert violations[0].regle == gft.FAMILLES[famille].regle
    assert violations[0].detail  # jamais un refus muet : il dit quoi retirer
    assert gft.controler(propre, seule) == ()


@pytest.mark.parametrize(("famille", "fautif", "propre"), [c for c in CAS if c[0] != gft.TEXTE_VIDE])
def test_une_famille_qu_un_profil_ne_cite_pas_n_est_jamais_lue(famille, fautif, propre):
    autres = gft.profil("autres", [n for n in gft.FAMILLES if n not in (famille, gft.TEXTE_VIDE)])
    assert famille not in autres
    assert famille not in {v.famille for v in gft.controler(fautif, autres)}


def test_le_detail_d_un_refus_cite_ce_qui_l_a_declenche_quand_le_motif_le_permet():
    (violation,) = gft.controler("Gouttières à partir de 4 500 $", gft.profil("p", (gft.PRIX_OFFRE,)))
    assert "4 500" in violation.detail
    (violation,) = gft.controler("Nous consultons notre avocat.", gft.profil("p", (gft.AVIS_LEGAL,)))
    assert "avocat" in violation.detail


def test_les_familles_a_contexte_lisent_le_contexte_du_departement():
    garantie = gft.profil("g", (gft.GARANTIE_NON_VALIDEE,))
    validee = "Garantie limitée de la main-d'œuvre"
    assert gft.controler(f"Un chantier soigné. {validee}.", garantie) != ()
    assert gft.controler(f"Un chantier soigné. {validee}.", garantie, Contexte(garanties_validees=(validee,))) == ()
    marque = Contexte(noms_de_marque=("Toitures Garantie Inc.",))
    assert gft.controler("Toitures Garantie Inc. a fini ce projet", garantie, marque) == ()
    assert gft.controler("Toitures Garantie Inc. : travail garanti", garantie, marque) != ()
    assert _regles("Dossier LEAD-4711 terminé", gft.profil("i", (gft.IDENTIFIANT_INTERNE,)), CONTEXTE_IDENTIFIANTS) == [
        "REJ-IDENTIFIANT-INTERNE"]
    assert _regles("Un chantier pour tremblay", gft.profil("n", (gft.NOM_CLIENT,)), CONTEXTE_NOMS) == ["REJ-NOM-CLIENT"]
    assert _regles("x" * 21, gft.profil("l", (gft.LONGUEUR,)), CONTEXTE_LONGUEUR) == ["REJ-LONGUEUR"]
    assert _regles("x" * 20, gft.profil("l", (gft.LONGUEUR,)), CONTEXTE_LONGUEUR) == []
    assert _regles("x" * 500, gft.profil("l", (gft.LONGUEUR,))) == []  # sans plafond, aucun contrôle de longueur


# -- un département choisit ses familles ---------------------------------------------------------------------------
REPONSE_CLIENT = gft.profil(
    "reponse", (gft.PRIX_MONTANT, gft.DATE_EXECUTION, gft.ENGAGEMENT, gft.AVEU, gft.AVIS_LEGAL))
TEXTE_PUBLIC = gft.profil(
    "public", (gft.TEXTE_VIDE, gft.LIEN, gft.ADRESSE, gft.PRIX_OFFRE, gft.PROMESSE_DE_DATE, gft.EXAGERATION))


@pytest.mark.parametrize(("texte", "reponse_client", "texte_public"), [
    ("Avez-vous déjà un budget en tête pour ce projet?", True, False),  # M1 le demande, M7 ne parle jamais d'argent
    ("Le service est entièrement gratuit pour l'estimation.", True, False),
    ("Nous pouvons planifier une visite la semaine prochaine, sans engagement.", True, False),
    ("Le meilleur service au Québec", True, False),
    ("Nous vous rappelons demain pour confirmer l'heure.", True, False),
    ("Le montant total est de 12 500 $.", False, False),  # les deux refusent un montant
    ("Vous avez le droit de refuser de payer.", False, True),  # M1 refuse l'avis légal, un texte public ne le vise pas
])
def test_le_meme_texte_a_le_verdict_du_profil_qui_l_applique(texte, reponse_client, texte_public):
    assert (gft.controler(texte, REPONSE_CLIENT) == ()) is reponse_client
    assert (gft.controler(texte, TEXTE_PUBLIC) == ()) is texte_public


def test_le_meme_texte_de_prix_est_nomme_differemment_selon_le_niveau_de_la_famille():
    assert _regles("Le montant total est de 12 500 $.", REPONSE_CLIENT) == ["REJ-INTERDIT-PRIX"]
    assert _regles("Le montant total est de 12 500 $.", TEXTE_PUBLIC) == ["REJ-PRIX"]
    assert _regles("Les travaux seront terminés demain.", REPONSE_CLIENT) == ["REJ-INTERDIT-DATE"]
    assert _regles("Les travaux seront terminés demain.", TEXTE_PUBLIC) == ["REJ-PROMESSE-DE-DATE"]


def test_un_profil_est_relu_dans_l_ordre_du_catalogue_quel_que_soit_l_ordre_cite():
    mele = gft.profil("mele", (gft.AVIS_LEGAL, gft.AVEU, gft.PRIX_MONTANT, gft.ENGAGEMENT, gft.DATE_EXECUTION))
    assert [f.nom for f in mele.familles] == [f.nom for f in REPONSE_CLIENT.familles]
    texte = "Nous nous engageons, c'est notre faute, vous avez le droit à 500 $ selon la loi."
    assert _regles(texte, mele) == _regles(texte, REPONSE_CLIENT)
    assert _regles(texte, mele) == [
        "REJ-INTERDIT-PRIX", "REJ-INTERDIT-ENGAGEMENT", "REJ-INTERDIT-AVEU", "REJ-INTERDIT-AVIS-LEGAL"]


def test_les_libelles_du_profil_suivent_l_ordre_d_evaluation():
    libelles = REPONSE_CLIENT.libelles()
    assert list(libelles) == [
        "REJ-INTERDIT-PRIX", "REJ-INTERDIT-DATE", "REJ-INTERDIT-ENGAGEMENT", "REJ-INTERDIT-AVEU",
        "REJ-INTERDIT-AVIS-LEGAL"]
    assert all(libelles.values())


@pytest.mark.parametrize("appel", [
    lambda: gft.profil("p", ("prix", )),  # « prix » n'est pas une famille : le catalogue dit prix_montant, prix_offre
    lambda: gft.profil("p", (gft.AVEU, gft.AVEU)),
    lambda: gft.profil("p", (gft.AVEU,), texte_max=100),  # un plafond exige la famille qui nomme son refus
])
def test_un_profil_mal_forme_est_une_erreur_de_programmation_levee_au_chargement(appel):
    with pytest.raises(ValueError, match="profil 'p'"):
        appel()


# -- la première violation, les barrières ---------------------------------------------------------------------------
def test_la_premiere_violation_est_la_premiere_du_catalogue_et_les_suivantes_ne_sont_pas_lues():
    def _explose(formes, contexte):
        raise AssertionError("une famille suivante a été lue")

    explosive = Famille("explosive", "REJ-EXPLOSIVE", "x", _explose)
    profil_piege = Profil("piege", (gft.FAMILLES[gft.PRIX_MONTANT], explosive))
    assert gft.premiere_violation("12 500 $", profil_piege).regle == "REJ-INTERDIT-PRIX"
    with pytest.raises(AssertionError):
        gft.controler("12 500 $", profil_piege)  # `controler` lit tout : le piège prouve que la première s'arrête
    assert gft.premiere_violation("Bonjour", REPONSE_CLIENT) is None


def test_premiere_violation_est_la_premiere_de_controler():
    for _, fautif, _ in CAS:
        assert gft.premiere_violation(fautif, TOUT) == gft.controler(fautif, TOUT)[0]


def test_un_texte_vide_ne_lit_que_la_famille_texte_vide_quand_le_profil_la_cite():
    assert _regles("", TEXTE_PUBLIC) == ["REJ-TEXTE-VIDE"]
    assert _regles(" \n ", TOUT) == ["REJ-TEXTE-VIDE"]
    assert gft.controler("", REPONSE_CLIENT) == () and gft.controler("   ", REPONSE_CLIENT) == ()  # M1 : vide = OK


def test_le_plafond_absolu_refuse_un_texte_sans_le_lire_et_seulement_pour_le_profil_qui_le_demande():
    plafonne = gft.profil("plafonne", (gft.TEXTE_VIDE, gft.LONGUEUR, gft.PRIX_OFFRE), texte_max=gft.TEXTE_MAX_CONTROLE)
    texte = "1 2 3 4 " * 2000
    violations = gft.controler(texte, plafonne)
    assert [v.regle for v in violations] == ["REJ-LONGUEUR"] and str(gft.TEXTE_MAX_CONTROLE) in violations[0].detail
    assert gft.controler("x" * gft.TEXTE_MAX_CONTROLE, plafonne) == ()
    assert [v.regle for v in gft.controler("x" * (gft.TEXTE_MAX_CONTROLE + 1), plafonne)] == ["REJ-LONGUEUR"]
    # Sans `texte_max`, le profil de M1 lit le texte entier, comme avant.
    assert _regles(texte + " 500 $", REPONSE_CLIENT) == ["REJ-INTERDIT-PRIX"]
    # Un texte de blancs plus long que le plafond est vide avant d'être long.
    assert _regles(" " * (gft.TEXTE_MAX_CONTROLE + 10), plafonne) == ["REJ-TEXTE-VIDE"]


@pytest.mark.parametrize("mauvais", [None, 42, b"octets", ["liste"]])
def test_un_texte_qui_n_est_pas_une_chaine_est_une_erreur_de_programmation(mauvais):
    with pytest.raises(TypeError):
        gft.controler(mauvais, TOUT)
    with pytest.raises(TypeError):
        gft.premiere_violation(mauvais, TOUT)


def test_le_verdict_est_deterministe_et_ne_modifie_pas_le_contexte():
    contexte = Contexte(noms_de_marque=("Marque Fictive",), garanties_validees=("Garantie limitée",))
    texte = "Terminé demain au 12 rue Principale, à partir de 500 $, garanti"
    assert gft.controler(texte, TOUT, contexte) == gft.controler(texte, TOUT, contexte)
    assert contexte == Contexte(noms_de_marque=("Marque Fictive",), garanties_validees=("Garantie limitée",))


def test_motif_de_refus_nomme_chaque_regle_violee_et_est_vide_sans_violation():
    assert gft.motif_de_refus(()) == ""
    violations = gft.controler("Terminé demain, à partir de 500 $", TEXTE_PUBLIC)
    motif = gft.motif_de_refus(violations)
    assert [v.regle for v in violations] == ["REJ-PRIX", "REJ-PROMESSE-DE-DATE"]
    assert motif == " ; ".join(f"{v.regle} ({v.detail})" for v in violations)
    assert motif.startswith("REJ-PRIX (") and " ; REJ-PROMESSE-DE-DATE (" in motif


def test_une_violation_se_rend_en_dict_avec_sa_regle_et_son_detail_seulement():
    (violation,) = gft.controler("Nous consultons notre avocat.", gft.profil("p", (gft.AVIS_LEGAL,)))
    assert set(violation.en_dict()) == {"regle", "detail"}
    assert violation.en_dict()["regle"] == "REJ-INTERDIT-AVIS-LEGAL"


# -- la famille « avis légal » -------------------------------------------------------------------------------------
# Une phrase par alternative du motif, où AUCUNE autre alternative ne s'applique : retirer un terme du motif fait
# échouer son cas, jamais un cas voisin.
AVIS_LEGAUX = [
    "Vous avez droit à un remboursement.",
    "Vous avez le droit de refuser de payer.",
    "Vos droits sont protégés.",
    "Selon la loi, c'est réglé.",
    "En vertu de l'entente, c'est réglé.",
    "En vertu du règlement, c'est réglé.",
    "Ce n'est pas légal.",
    "Une clause légale s'applique.",
    "Le vice est illégal.",
    "C'est une situation juridique complexe.",
    "Nous irons au tribunal.",
    "Les tribunaux décident.",
    "Une poursuite est possible.",
    "Nous pourrions poursuivre.",
    "Il existe un recours.",
    "Une mise en demeure est possible.",
    "Nous consultons notre avocat.",
    "Notre avocate vous écrira.",
    "Le Code civil s'applique.",
    "La protection du consommateur s'applique.",
    "La responsabilité civile de l'entreprise est engagée.",
    "Clause contractuelle en vigueur.",
    "La prescription est de trois ans.",
]


@pytest.mark.parametrize("avis", AVIS_LEGAUX)
def test_un_avis_legal_est_refuse(avis):
    assert _regles(avis, gft.profil("p", (gft.AVIS_LEGAL,))) == ["REJ-INTERDIT-AVIS-LEGAL"]
    assert _regles(avis.upper(), gft.profil("p", (gft.AVIS_LEGAL,))) == ["REJ-INTERDIT-AVIS-LEGAL"]  # casse ignorée


@pytest.mark.parametrize("texte", [
    "Merci de votre appel, nous traitons votre demande.",
    "Nous vous rappelons demain pour confirmer l'heure.",
    "Pourriez-vous prendre une photo du dommage?",
    "Votre demande est enregistrée.",
    "Nous prenons note de l'urgence de votre situation.",
])
def test_un_message_ordinaire_n_est_pas_un_avis_legal(texte):
    assert _regles(texte, gft.profil("p", (gft.AVIS_LEGAL,))) == []


def test_l_apostrophe_courbe_ne_contourne_aucune_famille_de_reponse():
    assert _regles("C’est notre faute", REPONSE_CLIENT) == ["REJ-INTERDIT-AVEU"]
    assert _regles("Je m’engage à venir", REPONSE_CLIENT) == ["REJ-INTERDIT-ENGAGEMENT"]
    assert gft.apostrophes_droites("l’avis") == "l'avis"


# -- la segmentation des dates d'exécution --------------------------------------------------------------------------
def test_les_segments_ne_coupent_pas_une_date_iso_et_le_rappel_ne_neutralise_que_son_segment():
    assert gft.decouper_segments("installation prévue le 2026-08-14. Merci\nBonjour ; à demain!") == [
        "installation prévue le 2026-08-14", "Merci", "Bonjour", "à demain"]
    assert _regles("Je vous rappelle lundi. La dalle sera coulée le 14/08.", REPONSE_CLIENT) == ["REJ-INTERDIT-DATE"]
    assert _regles("Je vous rappelle lundi.", REPONSE_CLIENT) == []


# -- performance : un texte pathologique sous le plafond reste linéaire ---------------------------------------------
@pytest.mark.parametrize("texte", ["1" * 4900, "1 " * 2450, "a" * 4900, "@" * 4900, "chez " + "Ab " * 1600])
def test_le_controle_reste_rapide_sur_des_textes_pathologiques(texte):
    plafonne = gft.profil("p", FAMILLES_TEXTE_PUBLIC, texte_max=gft.TEXTE_MAX_CONTROLE)
    debut = time.perf_counter()
    gft.controler(texte, plafonne)
    assert time.perf_counter() - debut < 0.5


# -- pureté : ni entrée-sortie, ni horloge, ni réseau, ni modèle, ni autre département ---------------------------------
IMPORTS_PERMIS = {
    "__future__", "collections", "dataclasses", "functools", "re", "types", "unicodedata",
}
APPELS_INTERDITS = {"open", "exec", "eval", "input", "print", "__import__"}
NOMS_INTERDITS = {"datetime", "time", "socket", "urllib", "http", "requests", "openai", "litellm", "subprocess", "os"}


def _sources() -> list[Path]:
    return sorted(RACINE_MODULE.glob("*.py"))


def test_le_module_est_fait_de_six_fichiers_et_aucun_ne_sort_de_lui_meme():
    assert [p.name for p in _sources()] == [
        "__init__.py", "_types.py", "confidentialite.py", "droit.py", "engagements.py", "promesses.py"]
    for source in _sources():
        arbre = ast.parse(source.read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                racines = {a.name.split(".")[0] for a in noeud.names}
            elif isinstance(noeud, ast.ImportFrom):
                # `from . import x` reste dans le module ; `from .. import x` en sortirait.
                racines = ({"."} if noeud.level == 1 else {"hors du module"}) if noeud.level else {
                    (noeud.module or "").split(".")[0]}
            else:
                continue
            assert racines <= IMPORTS_PERMIS | {"."}, (source.name, racines)


def test_le_module_n_appelle_ni_entree_sortie_ni_horloge():
    for source in _sources():
        arbre = ast.parse(source.read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name):
                assert noeud.func.id not in APPELS_INTERDITS, (source.name, noeud.func.id)
            if isinstance(noeud, ast.Name):
                assert noeud.id not in NOMS_INTERDITS, (source.name, noeud.id)


def test_aucun_departement_n_importe_un_autre_pour_son_controle_de_texte():
    """Le code partagé vit dans le socle : M1 et M7 s'en servent, et aucun des deux ne lit l'autre."""
    racine = Path(gft.__file__).resolve().parents[3] / "departments"
    for chemin, autre in (
        (racine / "m01-front-office" / "src", "m7_marketing"), (racine / "m07-marketing" / "src", "m1_front_office"),
    ):
        for source in chemin.rglob("*.py"):
            arbre = ast.parse(source.read_text(encoding="utf-8"))
            for noeud in ast.walk(arbre):
                noms = (
                    [a.name for a in noeud.names] if isinstance(noeud, ast.Import)
                    else [noeud.module or ""] if isinstance(noeud, ast.ImportFrom) and not noeud.level else []
                )
                assert not any(n.split(".")[0] == autre for n in noms), (source.name, autre)


def test_m1_et_m7_ne_recopient_aucun_motif_du_garde_fou():
    """Test de dérive : les deux modules qui avaient leurs motifs ne font plus que choisir des familles du socle."""
    racine = Path(gft.__file__).resolve().parents[3] / "departments"
    for chemin in (
        racine / "m01-front-office" / "src" / "m1_front_office" / "garde_fou.py",
        racine / "m07-marketing" / "src" / "m7_marketing" / "usine" / "controle_texte.py",
    ):
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        importes = {a.name for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names}
        appels = {
            n.func.attr for n in ast.walk(arbre) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "re" not in importes and "compile" not in appels, chemin.name
        assert "opsys" in {n.module for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom)}, chemin.name


def test_tous_les_paquets_du_socle_sont_declares_dans_pyproject():
    """M1 et M7 importent `opsys.garde_fou_texte` : un paquet absent de la liste de `pyproject.toml` manquerait à
    l'image de déploiement (installée par `pip install`), pas à ces tests (qui lisent `src/`)."""
    racine = Path(gft.__file__).resolve().parents[3]
    pyproject = tomllib.loads((racine / "pyproject.toml").read_text(encoding="utf-8"))
    declares = set(pyproject["tool"]["setuptools"]["packages"])
    presents = {
        ".".join(dossier.relative_to(racine / "src").parts)
        for dossier in (racine / "src" / "opsys").rglob("*") if (dossier / "__init__.py").is_file()
    } | {"opsys"}
    assert "opsys.garde_fou_texte" in declares
    assert presents <= declares, sorted(presents - declares)
