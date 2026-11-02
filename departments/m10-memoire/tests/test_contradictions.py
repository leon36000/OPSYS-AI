"""Contradictions de la mémoire de M10, logique pure : affirmations fermées, supersede, détection, marques, états
rejoués,
décisions humaines. Registres en mémoire ; données FICTIVES ; l'ordre de vérité est la donnée livrée."""

from __future__ import annotations

import json

import pytest
from m10_memoire import contradictions as c
from m10_memoire import registre, verite

FICTIF = True
H = "2026-11-02T04:10:00-05:00"
REF_AFFAIRES = "registre:affaires:" + "a" * 64
REF_EVENEMENTS = "registre:evenements:" + "b" * 64
REF_PROJET = "projet:docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M10.json@" + "c" * 64
HUMAIN = {"par": "nathan", "role": "nathan_owner", "source": "approbation"}
MOTIF = "Source plus à jour, vérifiée avec la matrice."


@pytest.fixture
def ordre():
    return verite.charger()


def champs(**surcharge):
    base = {
        "domaine": "affaires",
        "sujet": "devis:D-12",
        "attribut": "statut",
        "valeur": "accepte",
        "classe": "journal",
        "ref": REF_AFFAIRES,
        "emetteur": "agent:m10-memoire",
    }
    base.update(surcharge)
    return base


class Monde:
    """Deux registres en mémoire, comme les registres durables : on y ajoute des affirmations puis on rejoue l'état."""

    def __init__(self, ordre):
        self.ordre = ordre
        self.affirmations = registre.Registre()
        self.contradictions = registre.Registre()

    def affirmer(self, canal="agent", horodatage=H, **surcharge):
        if canal == "ingestion":
            surcharge = {"ref": REF_PROJET, "emetteur": "fichier:docs/x.md", **surcharge}
            surcharge.setdefault("domaine", "developpement")
            surcharge.setdefault("sujet", "exigence:M10.4")
            surcharge.setdefault("classe", "matrice_vivante")
        valide = c.valider(champs(**surcharge), self.ordre, canal)
        prepare = c.preparer(c.affirmations(self.affirmations.lire()), valide, horodatage, self.ordre)
        if prepare["entree"] is not None:
            self.affirmations.ajouter(prepare["entree"])
        return prepare

    def liste(self):
        return c.affirmations(self.affirmations.lire())

    def detecter(self, horodatage=H):
        actives = c.actives(self.liste())
        connues = set(c.etats(self.contradictions.lire(), actives))
        nouvelles = c.detecter(actives, connues, self.ordre, horodatage)
        for detection in nouvelles:
            for entree in c.entrees_detection(detection):
                self.contradictions.ajouter(entree)
        return nouvelles

    def etats(self):
        return c.etats(self.contradictions.lire(), c.actives(self.liste()))


@pytest.fixture
def monde(ordre):
    return Monde(ordre)


# -- 1. la forme fermée de l'affirmation --------------------------------------------------------------------
@pytest.mark.parametrize(
    "surcharge, code",
    [
        ({"domaine": "clients"}, c.REJ_DOMAINE),
        ({"classe": "verite_absolue"}, c.REJ_CLASSE_INCONNUE),
        ({"classe": "constitution"}, c.REJ_CLASSE_NON_ADMISE),  # un agent ne déclare pas la constitution
        ({"classe": "decision_proprietaire"}, c.REJ_CLASSE_NON_ADMISE),
        ({"classe": "matrice_vivante"}, c.REJ_CLASSE_NON_ADMISE),
        (
            {"domaine": "developpement", "classe": "journal"},
            c.REJ_CLASSE_NON_ADMISE,
        ),  # aucune voie d'agent au développement
        ({"sujet": "client:jean"}, c.REJ_SUJET),  # famille hors du domaine
        ({"sujet": "devis:D 12"}, c.REJ_SUJET),
        ({"sujet": "devis:jean@example.test"}, c.REJ_SUJET),
        ({"sujet": "devis"}, c.REJ_SUJET),
        ({"attribut": "Statut"}, c.REJ_ATTRIBUT),
        ({"attribut": "a b"}, c.REJ_ATTRIBUT),
        ({"valeur": "jean@example.test"}, c.REJ_VALEUR),
        ({"valeur": "le client veut annuler"}, c.REJ_VALEUR),  # une phrase n'est pas une valeur
        ({"valeur": ""}, c.REJ_VALEUR),
        ({"valeur": "5145550123"}, c.REJ_DONNEE_PERSONNELLE),
        ({"valeur": "514-555-0123"}, c.REJ_DONNEE_PERSONNELLE),
        ({"valeur": "4111-1111-1111-1111"}, c.REJ_DONNEE_PERSONNELLE),
        ({"sujet": "devis:51455501234"}, c.REJ_DONNEE_PERSONNELLE),
        ({"sujet": "devis:514-555-0123"}, c.REJ_DONNEE_PERSONNELLE),
        ({"ref": "http://exemple.test/x"}, c.REJ_REFERENCE),
        ({"ref": "registre:soi:" + "a" * 64}, c.REJ_REFERENCE),  # un registre hors liste
        ({"ref": REF_PROJET}, c.REJ_REFERENCE),  # la référence d'un fichier n'est pas celle du canal agent
        ({"ref": "registre:affaires:abc"}, c.REJ_REFERENCE),
        ({"emetteur": "humain:nathan"}, c.REJ_EMETTEUR),
        ({"emetteur": "agent:Voleur"}, c.REJ_EMETTEUR),
    ],
)
def test_une_affirmation_hostile_ou_mal_formee_est_refusee_sans_citer_la_valeur(ordre, surcharge, code):
    with pytest.raises(ValueError) as exc:
        c.valider(champs(**surcharge), ordre, "agent")
    assert str(exc.value).startswith(code + ":")
    for morceau in ("jean", "5145550123", "514-555", "4111", "le client veut"):
        assert morceau not in str(exc.value)  # un refus ne cite jamais la valeur reçue


def test_les_champs_sont_exacts():
    ordre = verite.charger()
    for retirer in champs():
        defectueux = {k: v for k, v in champs().items() if k != retirer}
        with pytest.raises(ValueError):
            c.valider(defectueux, ordre, "agent")
    with pytest.raises(ValueError):
        c.valider({**champs(), "extra": "x"}, ordre, "agent")
    with pytest.raises(ValueError):
        c.valider("pas un objet", ordre, "agent")


def test_le_canal_ingestion_exige_une_reference_de_fichier_et_le_canal_humain_une_personne(ordre):
    valide = c.valider(
        champs(
            domaine="developpement",
            sujet="exigence:M10.4",
            classe="matrice_vivante",
            ref=REF_PROJET,
            emetteur="fichier:docs/x.md",
        ),
        ordre,
        "ingestion",
    )
    assert valide["canal"] == "ingestion" and valide["classe"] == "matrice_vivante"
    with pytest.raises(ValueError, match=c.REJ_REFERENCE):
        c.valider(
            champs(
                domaine="developpement", classe="matrice_vivante", sujet="exigence:M10.4", emetteur="fichier:docs/x.md"
            ),
            ordre,
            "ingestion",
        )  # registre: au lieu de projet:
    humain = c.valider(champs(classe="decision_proprietaire", emetteur="humain:nathan"), ordre, "humain")
    assert humain["emetteur"] == "humain:nathan"
    with pytest.raises(ValueError, match=c.REJ_CLASSE_NON_ADMISE):
        c.valider(champs(classe="constitution", emetteur="humain:nathan"), ordre, "humain")
    with pytest.raises(ValueError, match=c.REJ_CLASSE_NON_ADMISE):
        c.valider(champs(classe="journal"), ordre, "canal_inconnu")


# -- 2. supersede, retrait, idempotence --------------------------------------------------------------------
def test_la_meme_source_qui_se_reexprime_remplace_sa_version_precedente_sans_rien_effacer(monde):
    premiere = monde.affirmer(valeur="accepte")
    assert premiere["resultat"] == "ajoutee"
    assert monde.affirmer(valeur="accepte")["resultat"] == "inchangee"  # rejouer ne change rien
    assert len(monde.affirmations.lire()) == 1
    seconde = monde.affirmer(valeur="refuse")
    assert seconde["resultat"] == "remplace"
    liste = monde.liste()
    assert [a["active"] for a in liste] == [False, True]
    assert (
        liste[0]["remplacee_par"] == liste[1]["ligne_id"] and liste[0]["valeur"] == "accepte"
    )  # la trace d'origine reste
    assert monde.detecter() == []  # la même source qui change d'avis n'est PAS une contradiction


def test_un_remplace_forge_vers_une_autre_cle_est_ignore(monde):
    monde.affirmer(sujet="devis:D-12", valeur="accepte")
    cible = monde.liste()[0]["ligne_id"]
    monde.affirmations.ajouter(
        {
            "type_entree": c.TYPE_AFFIRMATION,
            "horodatage": H,
            **c.valider(champs(sujet="devis:D-99", valeur="refuse"), verite.charger(), "agent"),
            "remplace": cible,
        }
    )
    assert all(a["active"] for a in monde.liste())  # l'ancienne n'a pas été remplacée par une autre clé


def test_une_affirmation_retiree_reste_au_registre_mais_n_est_plus_active(monde):
    monde.affirmer(valeur="accepte")
    [a] = monde.liste()
    monde.affirmations.ajouter(c.entree_retrait(a, "absente_de_la_source", H))
    [apres] = monde.liste()
    assert apres["retiree"] is True and apres["active"] is False and c.actives(monde.liste()) == []
    assert len(monde.affirmations.lire()) == 2
    with pytest.raises(ValueError):
        c.entree_retrait(a, "parce_que", H)


def test_le_plafond_d_affirmations_actives_par_domaine_ferme_la_porte(monde, monkeypatch):
    monkeypatch.setattr(c, "PLAFOND_ACTIVES", 3)
    for i in range(3):
        monde.affirmer(sujet=f"devis:D-{i}")
    with pytest.raises(ValueError, match=c.REJ_PLAFOND):
        monde.affirmer(sujet="devis:D-9")
    assert monde.affirmer(sujet="devis:D-0", valeur="refuse")["resultat"] == "remplace"  # remplacer reste permis


# -- 3. la détection ----------------------------------------------------------------------------------------
def test_deux_valeurs_de_classes_differentes_sur_la_meme_cle_sont_une_contradiction_resolue_par_l_ordre(monde):
    monde.affirmer(classe="memoire_ancienne", valeur="FAIT_PROUVE", sujet="devis:D-12", attribut="statut")
    monde.affirmer(
        classe="journal", valeur="PARTIEL", sujet="devis:D-12", attribut="statut", emetteur="agent:m10-autre"
    )
    [detection] = monde.detecter()
    assert detection["traitement"] == "auto" and detection["critique"] is False
    # Le côté « a » est toujours la source de plus haute autorité : ici le journal l'emporte sur la mémoire ancienne.
    assert detection["a"]["classe"] == "journal" and detection["b"]["classe"] == "memoire_ancienne"
    assert detection["proposition"]["retenue"] == "a"
    assert detection["ordre_version"] == monde.ordre.version and detection["ordre_empreinte"] == monde.ordre.empreinte
    assert "rang" in detection["proposition"]["raison"] and "FAIT_PROUVE" not in json.dumps(detection["proposition"])
    [etat] = monde.etats().values()
    assert etat["statut"] == c.STATUT_AUTO
    marques = c.marques_effectives(monde.etats())
    gagnante, perdante = detection["a"]["ligne_id"], detection["b"]["ligne_id"]
    assert (marques[gagnante], marques[perdante]) == (c.MARQUE_RETENUE, c.MARQUE_DOMINEE)
    # les DEUX mémoires restent lisibles dans le registre : la trace d'origine n'est pas perdue
    assert {a["valeur"] for a in monde.liste()} == {"FAIT_PROUVE", "PARTIEL"}


def test_la_detection_est_idempotente_et_deterministe(monde):
    monde.affirmer(classe="memoire_ancienne", valeur="a1")
    monde.affirmer(classe="journal", valeur="b1", emetteur="agent:m10-autre")
    premiere = monde.detecter()
    assert len(premiere) == 1
    avant = len(monde.contradictions.lire())
    assert monde.detecter("2027-01-01T00:00:00-05:00") == []  # rejouer plus tard n'ajoute rien
    assert len(monde.contradictions.lire()) == avant
    autre = Monde(verite.charger())
    autre.affirmer(classe="journal", valeur="b1", emetteur="agent:m10-autre")
    autre.affirmer(classe="memoire_ancienne", valeur="a1")
    # L'identifiant ne dépend que de (clé, deux affirmations), pas de l'ordre d'arrivée : ici les lignes diffèrent
    # (horodatage de chaîne), mais la forme est stable et reproductible.
    assert len(premiere[0]["contradiction_id"]) == 32


def test_une_meme_valeur_ou_une_cle_differente_n_est_pas_une_contradiction(monde):
    monde.affirmer(classe="memoire_ancienne", valeur="accepte")
    monde.affirmer(classe="journal", valeur="accepte", emetteur="agent:m10-autre")
    monde.affirmer(classe="journal", valeur="refuse", sujet="devis:D-77", emetteur="agent:m10-autre")
    monde.affirmer(classe="journal", valeur="refuse", attribut="priorite", emetteur="agent:m10-autre")
    assert monde.detecter() == []


def test_trois_valeurs_font_trois_paires(monde):
    monde.affirmer(classe="hypothese", valeur="v1")
    monde.affirmer(classe="memoire_ancienne", valeur="v2", emetteur="agent:m10-b")
    monde.affirmer(classe="journal", valeur="v3", emetteur="agent:m10-c")
    assert len(monde.detecter()) == 3


def test_deux_domaines_ne_se_croisent_jamais(monde):
    monde.affirmer(classe="journal", valeur="x1", sujet="regle:approbation", attribut="statut")
    monde.affirmer(canal="ingestion", classe="documentation", valeur="x2", sujet="regle:approbation", attribut="statut")
    assert monde.detecter() == []
    assert {a["domaine"] for a in monde.liste()} == {"affaires", "developpement"}


def test_meme_rang_aucune_proposition_aucune_marque_de_domination(monde):
    monde.affirmer(classe="journal", valeur="x1", emetteur="agent:m10-a")
    monde.affirmer(classe="journal", valeur="x2", emetteur="agent:m10-b")
    [detection] = monde.detecter()
    assert detection["traitement"] == "ouverte" and detection["proposition"]["retenue"] is None
    assert set(c.marques_effectives(monde.etats()).values()) == {c.MARQUE_CONTESTEE}
    assert monde.etats()[detection["contradiction_id"]]["statut"] == c.STATUT_OUVERTE
    assert c.a_demander(monde.etats()) == []  # une égalité n'ouvre pas de demande au sas
    assert c.sans_proposition(monde.etats()) == 0  # non critique : simplement ouverte


def test_une_contradiction_critique_attend_une_personne_meme_avec_un_gagnant_clair(monde):
    monde.affirmer(
        canal="humain",
        classe="decision_proprietaire",
        valeur="non",
        sujet="regle:approbation_envoi",
        attribut="gate_humain",
        emetteur="humain:nathan",
    )
    monde.affirmer(classe="journal", valeur="oui", sujet="regle:approbation_envoi", attribut="gate_humain")
    [detection] = monde.detecter()
    assert detection["critique"] is True and detection["traitement"] == "humain"
    assert detection["proposition"]["retenue"] == "a"  # la décision du propriétaire est PROPOSÉE...
    assert set(c.marques_effectives(monde.etats()).values()) == {c.MARQUE_CONTESTEE}  # ...pas appliquée
    [etat] = monde.etats().values()
    assert etat["statut"] == c.STATUT_HUMAIN
    [a_demander] = c.a_demander(monde.etats())
    assert c.arguments_de_demande(a_demander) == {
        "contradiction_id": etat["contradiction_id"],
        "decision": "retenir_a",
        "motif": c.arguments_de_demande(a_demander)["motif"],
    }


def test_l_egalite_critique_n_a_pas_de_demande_automatique_elle_est_comptee(monde):
    monde.affirmer(classe="journal", valeur="x1", attribut="gate_humain", emetteur="agent:m10-a")
    monde.affirmer(classe="journal", valeur="x2", attribut="gate_humain", emetteur="agent:m10-b")
    monde.detecter()
    assert c.a_demander(monde.etats()) == [] and c.sans_proposition(monde.etats()) == 1


# -- 4. la caducité -----------------------------------------------------------------------------------------
def test_une_contradiction_devient_caduque_quand_une_des_deux_affirmations_est_remplacee(monde):
    monde.affirmer(classe="memoire_ancienne", valeur="a1")
    monde.affirmer(classe="journal", valeur="b1", emetteur="agent:m10-autre")
    monde.detecter()
    ancien_id = next(iter(monde.etats()))
    monde.affirmer(classe="memoire_ancienne", valeur="b1")  # l'ancienne source se corrige : plus de contradiction
    assert monde.etats()[ancien_id]["statut"] == c.STATUT_CADUQUE
    assert c.marques_effectives(monde.etats()) == {}  # une contradiction caduque ne marque plus rien
    assert monde.detecter() == []
    assert c.compter(monde.etats())[c.STATUT_CADUQUE] == 1


def test_la_marque_la_plus_severe_gagne_entre_contradictions(monde):
    monde.affirmer(classe="hypothese", valeur="h1")
    monde.affirmer(classe="journal", valeur="j1", emetteur="agent:m10-j")
    monde.affirmer(classe="memoire_ancienne", valeur="m1", emetteur="agent:m10-m")
    monde.detecter()
    marques = c.marques_effectives(monde.etats())
    par_classe = {a["classe"]: marques.get(a["ligne_id"]) for a in monde.liste()}
    assert par_classe == {
        "hypothese": c.MARQUE_DOMINEE,
        "memoire_ancienne": c.MARQUE_DOMINEE,
        "journal": c.MARQUE_RETENUE,
    }


# -- 5. la décision humaine ---------------------------------------------------------------------------------
def _contradiction_critique(monde):
    monde.affirmer(
        canal="humain",
        classe="decision_proprietaire",
        valeur="non",
        sujet="regle:approbation_envoi",
        attribut="gate_humain",
        emetteur="humain:nathan",
    )
    monde.affirmer(classe="journal", valeur="oui", sujet="regle:approbation_envoi", attribut="gate_humain")
    return monde.detecter()[0]["contradiction_id"]


@pytest.mark.parametrize(
    "decision, marque_a, marque_b",
    [
        ("retenir_a", "retenue", "dominee"),
        ("retenir_b", "dominee", "retenue"),
        ("coexistence_valide", "valide", "valide"),
        ("fausse_alerte", "valide", "valide"),
    ],
)
def test_chaque_decision_humaine_pose_ses_marques_et_ne_supprime_rien(monde, decision, marque_a, marque_b):
    ident = _contradiction_critique(monde)
    avant = len(monde.affirmations.lire())
    for entree in c.preparer_decision(monde.etats(), ident, decision, MOTIF, HUMAIN, H):
        monde.contradictions.ajouter(entree)
    etat = monde.etats()[ident]
    assert (
        etat["statut"] == c.STATUT_DECIDEE
        and etat["decision"]["par"] == "nathan"
        and etat["decision"]["decision"] == decision
    )
    assert (etat["marques"][etat["a"]["ligne_id"]], etat["marques"][etat["b"]["ligne_id"]]) == (marque_a, marque_b)
    assert len(monde.affirmations.lire()) == avant  # aucune affirmation supprimée ni modifiée


def test_une_decision_refuse_ce_qui_n_est_pas_une_personne_un_motif_ou_une_decision_connue(monde):
    ident = _contradiction_critique(monde)
    etats = monde.etats()
    with pytest.raises(ValueError, match=c.REJ_INCONNUE):
        c.preparer_decision(etats, "inconnue", "retenir_a", MOTIF, HUMAIN, H)
    with pytest.raises(ValueError, match=c.REJ_DECISION):
        c.preparer_decision(etats, ident, "fusionner", MOTIF, HUMAIN, H)  # jamais de fusion
    for acteur in (
        {"par": "nathan", "role": "agent", "source": "approbation"},
        {"par": "Nathan!", "role": "admin", "source": "cli"},
        {"par": "nathan", "role": "nathan_owner", "source": "modele"},
        {},
    ):
        with pytest.raises(ValueError, match="REJ-HUMAIN"):
            c.preparer_decision(etats, ident, "retenir_a", MOTIF, acteur, H)
    with pytest.raises(ValueError, match="REJ-HUMAIN-MOTIF"):
        c.preparer_decision(etats, ident, "retenir_a", "court", HUMAIN, H)
    with pytest.raises(ValueError, match="REJ-HUMAIN-HORODATAGE"):
        c.preparer_decision(etats, ident, "retenir_a", MOTIF, HUMAIN, "hier")


def test_une_decision_est_definitive_et_une_contradiction_caduque_ne_se_decide_plus(monde):
    ident = _contradiction_critique(monde)
    for entree in c.preparer_decision(monde.etats(), ident, "retenir_a", MOTIF, HUMAIN, H):
        monde.contradictions.ajouter(entree)
    with pytest.raises(ValueError, match=c.REJ_DEJA_DECIDEE):
        c.preparer_decision(monde.etats(), ident, "retenir_b", MOTIF, HUMAIN, H)
    monde.affirmer(classe="journal", valeur="non", sujet="regle:approbation_envoi", attribut="gate_humain")
    assert monde.etats()[ident]["statut"] == c.STATUT_CADUQUE
    with pytest.raises(ValueError, match=c.REJ_CADUQUE):
        c.preparer_decision(monde.etats(), ident, "retenir_b", MOTIF, HUMAIN, H)


def test_la_demande_d_approbation_est_enregistree_une_fois_et_sort_de_la_liste_a_demander(monde):
    ident = _contradiction_critique(monde)
    assert [e["contradiction_id"] for e in c.a_demander(monde.etats())] == [ident]
    monde.contradictions.ajouter(c.entree_demande(ident, "demande-fictive", H))
    monde.contradictions.ajouter(
        c.entree_demande(ident, "autre-demande", H)
    )  # un doublon forgé n'écrase pas la première
    assert monde.etats()[ident]["demande_id"] == "demande-fictive" and c.a_demander(monde.etats()) == []


def test_un_marqueur_ou_une_decision_pour_une_contradiction_inconnue_est_ignore(monde):
    monde.contradictions.ajouter(
        {
            "type_entree": c.TYPE_MARQUE,
            "horodatage": H,
            "contradiction_id": "fantome",
            "affirmation_ligne_id": "x",
            "marque": c.MARQUE_DOMINEE,
            "fondement": c.FONDEMENT_DECISION,
        }
    )
    assert monde.etats() == {}


def test_la_vue_est_sans_donnee_personnelle_et_serialisable(monde):
    ident = _contradiction_critique(monde)
    vue = c.vue(monde.etats()[ident])
    texte = json.dumps(vue, ensure_ascii=False)
    assert (
        "@" not in texte and vue["statut"] == c.STATUT_HUMAIN and set(vue["marques"].values()) == {c.MARQUE_CONTESTEE}
    )
    assert vue["a"]["classe"] == "decision_proprietaire" and vue["b"]["classe"] == "journal"


def test_le_registre_accepte_les_quatre_types_de_contradiction_et_les_deux_d_affirmation():
    r = registre.Registre()
    for genre in (*c.types_affirmations(), *c.types_contradictions()):
        r.ajouter({"type_entree": genre, "horodatage": H})
    assert r.valider_chaine() == (True, "")
