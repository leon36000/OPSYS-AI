"""La sortie du sas avec des DOUBLES : aucun réseau, aucune clé. Idempotence, pannes, reprise, secrets, point de sortie.

Rien ici ne prouve qu'un vrai réseau accepterait ces publications : seulement que le sas ne publie pas ce qu'il ne
doit pas
publier, ne publie jamais deux fois, et ne laisse fuir aucun jeton.
"""

from __future__ import annotations

import ast
import contextlib
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fabriques_sociales import HORODATAGE, JETON, MAINTENANT, annonce, publication
from m7_marketing import journal_chaine
from m7_marketing.sas_social import doubles, etats, executeur, politique, service
from m7_marketing.sas_social.reseaux import ErreurReseau

from opsys.secrets_coffre import masquage

FICTIF = True
HEURE_PREVUE = datetime(2026, 1, 6, 15, 0, 0, tzinfo=UTC)


class Fournisseur:
    """Le fournisseur de secret (le coffre) : compte ses ouvertures."""

    def __init__(self, jeton=JETON):
        self.jeton, self.ouvertures = jeton, 0

    @contextlib.contextmanager
    def __call__(self):
        self.ouvertures += 1
        yield self.jeton


def planifiee(
    journal,
    comptes_actifs,
    declarations,
    politique_sas,
    proprietaire,
    donnees=None,
    cle="cle-sortie-0123456789ab",
    niveau=3,
):
    cree = service.composer(journal, donnees or publication("facebook"), cle, comptes_actifs, "agent", HORODATAGE)
    assert service.soumettre(journal, cree["publication_id"], declarations, politique_sas, MAINTENANT, HORODATAGE)[
        "accepte"
    ]
    ok = service.approuver(
        journal,
        cree["publication_id"],
        cree["empreinte"],
        niveau,
        proprietaire,
        declarations,
        politique_sas,
        MAINTENANT,
        HORODATAGE,
    )
    assert ok["accepte"], ok
    return cree["publication_id"]


@pytest.fixture
def pret(journal, comptes_actifs, declarations, politique_sas, proprietaire):
    publication_id = planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)
    double = doubles.DoubleFacebook(jeton_attendu=JETON)
    return publication_id, double, Fournisseur()


def sortir(journal, publication_id, double, fournisseur, politique_sas, instant=HEURE_PREVUE):
    return executeur.executer(journal, publication_id, {"facebook": double}, fournisseur, politique_sas, instant)


def test_une_publication_approuvee_et_arrivee_a_echeance_sort_une_fois(journal, pret, politique_sas):
    publication_id, double, fournisseur = pret
    resultat = sortir(journal, publication_id, double, fournisseur, politique_sas)
    assert resultat["accepte"] and resultat["publie"] and resultat["retrouvee"] is False
    assert len(double.publiees) == 1 and double.appels == 1
    etat = etats.plier(journal)[publication_id]
    assert (
        etat.etat == "publie" and etat.id_externe == "facebook-000001" and etat.tentatives == 1 and not etat.incertain
    )
    assert [m["type"] for m in journal][-2:] == ["tentative", "publiee"]
    assert journal[-1]["publie_le"] == "2026-01-06T15:00:00Z"
    requete = double.publiees[0]["requete"]
    assert requete.empreinte == etat.empreinte and requete.cle_idempotence == "cle-sortie-0123456789ab"
    assert requete.divulgation["texte_ia"] is True and not hasattr(requete, "jeton")


def test_la_deuxieme_execution_ne_republie_pas(journal, pret, politique_sas):
    publication_id, double, fournisseur = pret
    sortir(journal, publication_id, double, fournisseur, politique_sas)
    again = sortir(journal, publication_id, double, fournisseur, politique_sas)
    assert again["accepte"] is False and again["refus"][0]["code"] == "REJ-SOCIAL-ETAT"
    assert len(double.publiees) == 1 and double.appels == 1 and fournisseur.ouvertures == 1


def test_avant_l_heure_approuvee_rien_ne_part_et_le_coffre_n_est_pas_ouvert(journal, pret, politique_sas):
    publication_id, double, fournisseur = pret
    n = len(journal)
    for instant in (HEURE_PREVUE - timedelta(seconds=1), HEURE_PREVUE - timedelta(days=1)):
        refus = sortir(journal, publication_id, double, fournisseur, politique_sas, instant)
        assert refus["refus"][0]["code"] == "REJ-SOCIAL-PAS-ENCORE" and refus["publie"] is False
    assert len(journal) == n and double.appels == 0 and fournisseur.ouvertures == 0


def test_trop_tard_la_publication_n_est_plus_publiee(journal, pret, politique_sas):
    publication_id, double, fournisseur = pret
    limite = HEURE_PREVUE + timedelta(seconds=politique_sas.tolerance_retard_s)
    sortir(journal, publication_id, double, fournisseur, politique_sas, limite + timedelta(seconds=1))
    assert double.appels == 0 and fournisseur.ouvertures == 0
    etat = etats.plier(journal)[publication_id]
    assert (
        etat.etat == "echec"
        and etat.derniere_erreur["code"] == "REJ-SOCIAL-ECHEANCE-DEPASSEE"
        and not etat.derniere_erreur["transitoire"]
    )


def test_pile_a_la_tolerance_la_publication_sort(journal, pret, politique_sas):
    publication_id, double, fournisseur = pret
    limite = HEURE_PREVUE + timedelta(seconds=politique_sas.tolerance_retard_s)
    assert sortir(journal, publication_id, double, fournisseur, politique_sas, limite)["publie"] is True


def test_hors_de_la_fenetre_au_moment_de_sortir_on_attend_sans_rien_ecrire(
    journal,
    comptes_actifs,
    declarations,
    politique_sas,
    proprietaire,
):
    soir = publication("facebook", planifie_le="2026-01-07T01:30:00Z")  # 20 h 30 à Toronto : dans la fenêtre
    publication_id = planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire, soir)
    double, fournisseur = doubles.DoubleFacebook(jeton_attendu=JETON), Fournisseur()
    n = len(journal)
    refus = sortir(
        journal, publication_id, double, fournisseur, politique_sas, datetime(2026, 1, 7, 2, 5, tzinfo=UTC)
    )  # 21 h 05
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-HORS-FENETRE" and len(journal) == n and double.appels == 0
    assert sortir(journal, publication_id, double, fournisseur, politique_sas, datetime(2026, 1, 7, 1, 30, tzinfo=UTC))[
        "publie"
    ]


def test_le_quota_est_reverifie_a_la_sortie_sur_les_instants_reels_de_publication(
    journal,
    comptes_actifs,
    declarations,
    politique_sas,
    proprietaire,
):
    """Trois publications GBP prévues à 10 h, 10 h 30 et 11 h (Toronto) sortent TOUTES à 12 h (en retard, dans la
    tolérance de
    2 h). Une quatrième, prévue le lendemain à 10 h 30 et approuvée avant, respectait le quota sur les heures
    PRÉVUES mais plus
    sur les heures RÉELLES : elle attend. À 12 h pile le lendemain, la fenêtre glissante a lâché les trois autres."""
    ids = [
        planifiee(
            journal,
            comptes_actifs,
            declarations,
            politique_sas,
            proprietaire,
            publication("gbp", planifie_le=f"2026-01-06T15:{minute}:00Z"),
            cle=f"cle-quota-sortie-{i}-0123456",
        )
        for i, minute in enumerate(("00", "30", "59"))
    ]
    quatrieme = planifiee(
        journal,
        comptes_actifs,
        declarations,
        politique_sas,
        proprietaire,
        publication("gbp", planifie_le="2026-01-07T15:30:00Z"),
        cle="cle-quota-sortie-q-0123456",
    )
    double, fournisseur = doubles.DoubleGBP(jeton_attendu=JETON), Fournisseur()
    midi_17 = datetime(2026, 1, 6, 17, 0, tzinfo=UTC)
    for publication_id in ids:
        assert executeur.executer(journal, publication_id, {"gbp": double}, fournisseur, politique_sas, midi_17)[
            "publie"
        ]
    n, ouvertures = len(journal), fournisseur.ouvertures
    refus = executeur.executer(
        journal, quatrieme, {"gbp": double}, fournisseur, politique_sas, datetime(2026, 1, 7, 15, 30, tzinfo=UTC)
    )
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-QUOTA-24H" and refus["publie"] is False
    assert len(journal) == n and fournisseur.ouvertures == ouvertures and double.appels == 3, (
        "rien d'écrit, rien d'ouvert"
    )
    assert etats.plier(journal)[quatrieme].etat == "planifie"
    ok = executeur.executer(
        journal, quatrieme, {"gbp": double}, fournisseur, politique_sas, datetime(2026, 1, 7, 17, 0, tzinfo=UTC)
    )
    assert ok["publie"] is True and double.appels == 4


def test_les_controles_de_contenu_sont_refaits_a_la_sortie(journal, comptes_actifs, declarations, proprietaire):
    pol = politique.PolitiqueSas()
    publication_id = planifiee(journal, comptes_actifs, declarations, pol, proprietaire)
    resserree = politique.PolitiqueSas(contexte_texte=type(pol.contexte_texte)(noms_clients=("toiture",)))
    double, fournisseur = doubles.DoubleFacebook(jeton_attendu=JETON), Fournisseur()
    refus = sortir(journal, publication_id, double, fournisseur, resserree)
    assert refus["publie"] is False and refus["refus"][0]["code"] == "REJ-NOM-CLIENT"
    assert double.appels == 0 and fournisseur.ouvertures == 0
    assert etats.plier(journal)[publication_id].etat == "echec"


def test_l_adaptateur_d_un_autre_reseau_est_refuse(journal, pret, politique_sas):
    publication_id, _, fournisseur = pret
    refus = executeur.executer(
        journal, publication_id, {"facebook": doubles.DoubleInstagram()}, fournisseur, politique_sas, HEURE_PREVUE
    )
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-ADAPTATEUR" and fournisseur.ouvertures == 0
    refus = executeur.executer(journal, publication_id, {}, fournisseur, politique_sas, HEURE_PREVUE)
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-ADAPTATEUR"


def test_une_publication_inconnue_ou_non_planifiee_ne_sort_pas(journal, comptes_actifs, declarations, politique_sas):
    fournisseur = Fournisseur()
    assert (
        sortir(journal, "pub-inconnue", doubles.DoubleFacebook(), fournisseur, politique_sas)["refus"][0]["code"]
        == "REJ-SOCIAL-PUBLICATION-INCONNUE"
    )
    cree = service.composer(
        journal, publication("facebook"), "cle-brouillon-0123456789ab", comptes_actifs, "agent", HORODATAGE
    )
    double = doubles.DoubleFacebook()
    assert (
        sortir(journal, cree["publication_id"], double, fournisseur, politique_sas)["refus"][0]["code"]
        == "REJ-SOCIAL-ETAT"
    )
    service.soumettre(journal, cree["publication_id"], declarations, politique_sas, MAINTENANT, HORODATAGE)
    assert (
        sortir(journal, cree["publication_id"], double, fournisseur, politique_sas)["refus"][0]["code"]
        == "REJ-SOCIAL-ETAT"
    )
    assert double.appels == 0 and fournisseur.ouvertures == 0


# -- l'approbation est reverifiee au point de sortie, meme contre un journal reecrit avec une chaine recalculee
# ---------------------------
def _reecrire(journal, modifier):
    """Un attaquant qui a l'accès au registre ET sait recalculer la chaîne : seul le contrôle de fond peut l'arrêter."""
    neuf, precedent = [], journal_chaine.GENESE
    for ancien in journal:
        corps = modifier({k: v for k, v in ancien.items() if k != "chaine"})
        neuf.append({**corps, "chaine": journal_chaine._chaine(precedent, corps)})
        precedent = neuf[-1]["chaine"]
    assert journal_chaine.verifier(neuf) == []
    return neuf


def test_un_texte_remplace_apres_l_approbation_ne_sort_pas_meme_avec_une_chaine_recalculee(
    journal, pret, politique_sas
):
    publication_id, double, fournisseur = pret

    def modifier(m):
        if m["type"] == "brouillon_cree":
            m["publication"] = {**m["publication"], "texte": "Texte frauduleux, tout aussi sobre."}
        return m

    refus = sortir(_reecrire(journal, modifier), publication_id, double, fournisseur, politique_sas)
    assert (
        refus["refus"][0]["code"] == "REJ-SOCIAL-EMPREINTE-DIFFERENTE"
        and double.appels == 0
        and fournisseur.ouvertures == 0
    )


@pytest.mark.parametrize(
    "modification",
    [
        lambda a: {**a, "approbation": {**a["approbation"], "role": "admin"}},
        lambda a: {**a, "approbation": {**a["approbation"], "role": "system_agent"}},
        lambda a: {**a, "empreinte": "f" * 64},
        lambda a: {**a, "niveau": 2},
    ],
)
def test_une_approbation_alteree_ne_suffit_pas_a_la_sortie(journal, pret, politique_sas, modification):
    publication_id, double, fournisseur = pret
    refus = sortir(
        _reecrire(journal, lambda m: modification(m) if m["type"] == "approuvee" else m),
        publication_id,
        double,
        fournisseur,
        politique_sas,
    )
    assert refus["publie"] is False and refus["refus"][0]["code"] == "REJ-SOCIAL-NON-APPROUVEE"
    assert double.appels == 0


def test_une_annonce_approuvee_en_n3_ne_sort_pas(journal, comptes_actifs, declarations, politique_sas, proprietaire):
    publication_id = planifiee(
        journal, comptes_actifs, declarations, politique_sas, proprietaire, annonce("facebook"), niveau=4
    )
    faux = _reecrire(journal, lambda m: {**m, "niveau": 3} if m["type"] == "approuvee" else m)
    double, fournisseur = doubles.DoubleFacebook(jeton_attendu=JETON), Fournisseur()
    refus = sortir(faux, publication_id, double, fournisseur, politique_sas)
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-NON-APPROUVEE" and double.appels == 0
    assert sortir(journal, publication_id, double, fournisseur, politique_sas)["publie"]


def test_un_journal_retouche_sans_recalcul_de_chaine_ne_sort_pas(journal, pret, politique_sas):
    publication_id, double, fournisseur = pret
    journal[0]["publication"]["texte"] = "Retouché"
    assert (
        sortir(journal, publication_id, double, fournisseur, politique_sas)["refus"][0]["code"]
        == "REJ-SOCIAL-JOURNAL-ALTERE"
    )
    assert double.appels == 0


# -- pannes
# ---------------------------------------------------------------------------------------------------------------------
def test_panne_avant_l_envoi_puis_reprise_une_seule_publication(journal, pret, politique_sas):
    publication_id, _, fournisseur = pret
    double = doubles.DoubleFacebook(jeton_attendu=JETON, scenario=[doubles.PANNE_AVANT_ENVOI])
    echec = sortir(journal, publication_id, double, fournisseur, politique_sas)
    assert echec["publie"] is False and echec["transitoire"] is True and echec["resultat_incertain"] is False
    assert etats.plier(journal)[publication_id].etat == "echec" and len(double.publiees) == 0
    assert executeur.reprendre(journal, publication_id, politique_sas, HORODATAGE)["etat"] == "planifie"
    assert sortir(journal, publication_id, double, fournisseur, politique_sas)["publie"]
    assert len(double.publiees) == 1 and etats.plier(journal)[publication_id].tentatives == 2


def test_panne_apres_l_envoi_le_sas_retrouve_au_lieu_de_republier(journal, pret, politique_sas):
    publication_id, _, fournisseur = pret
    double = doubles.DoubleFacebook(jeton_attendu=JETON, scenario=[doubles.PANNE_APRES_ENVOI])
    echec = sortir(journal, publication_id, double, fournisseur, politique_sas)
    assert echec["resultat_incertain"] is True and len(double.publiees) == 1, "la plateforme a bien publié"
    assert etats.plier(journal)[publication_id].incertain is True
    assert executeur.reprendre(journal, publication_id, politique_sas, HORODATAGE)["accepte"]
    repris = sortir(journal, publication_id, double, fournisseur, politique_sas)
    assert repris["publie"] and repris["retrouvee"] is True
    assert len(double.publiees) == 1, "aucun doublon"
    assert double.appels == 1, "publier n'a pas été rappelé"
    assert etats.plier(journal)[publication_id].id_externe == double.publiees[0]["resultat"].id_externe


def test_un_processus_tue_apres_la_tentative_est_traite_comme_incertain(journal, pret, politique_sas):
    publication_id, double, fournisseur = pret
    # la tentative est écrite, puis plus rien (le processus meurt) ; la plateforme, elle, avait publié
    journal_chaine.ajouter(
        journal, "tentative", {"publication_id": publication_id, "tentative": 1, "cle_idempotence": "x"}, HORODATAGE
    )
    requete = executeur.requete_de(
        etats.plier(journal)[publication_id],
        __import__("m7_marketing.sas_social.modele", fromlist=["x"]).depuis_dict(
            etats.plier(journal)[publication_id].publication
        )[0],
    )
    double.publier(requete, JETON)
    assert etats.plier(journal)[publication_id].incertain is True
    resultat = sortir(journal, publication_id, double, fournisseur, politique_sas)
    assert resultat["publie"] and resultat["retrouvee"] is True and len(double.publiees) == 1


def test_un_processus_tue_avant_que_la_plateforme_ait_publie_republie_une_fois(journal, pret, politique_sas):
    publication_id, double, fournisseur = pret
    journal_chaine.ajouter(
        journal, "tentative", {"publication_id": publication_id, "tentative": 1, "cle_idempotence": "x"}, HORODATAGE
    )
    resultat = sortir(journal, publication_id, double, fournisseur, politique_sas)
    assert resultat["publie"] and resultat["retrouvee"] is False and len(double.publiees) == 1
    assert etats.plier(journal)[publication_id].tentatives == 2


def test_une_panne_definitive_ne_se_reprend_pas(journal, pret, politique_sas):
    publication_id, _, fournisseur = pret
    double = doubles.DoubleFacebook(jeton_attendu=JETON, scenario=[doubles.PANNE_DEFINITIVE])
    echec = sortir(journal, publication_id, double, fournisseur, politique_sas)
    assert echec["transitoire"] is False
    refus = executeur.reprendre(journal, publication_id, politique_sas, HORODATAGE)
    assert refus["refus"][0]["code"] == "REJ-SOCIAL-REPRISE-IMPOSSIBLE" and len(double.publiees) == 0


def test_les_tentatives_sont_bornees(journal, pret, politique_sas):
    publication_id, _, fournisseur = pret
    double = doubles.DoubleFacebook(jeton_attendu=JETON, scenario=[doubles.PANNE_AVANT_ENVOI] * 10)
    for _ in range(politique_sas.tentatives_max):
        assert sortir(journal, publication_id, double, fournisseur, politique_sas)["publie"] is False
        reprise = executeur.reprendre(journal, publication_id, politique_sas, HORODATAGE)
    assert reprise["refus"][0]["code"] == "REJ-SOCIAL-REPRISE-IMPOSSIBLE", "la troisième panne n'est plus reprise"
    assert double.appels == politique_sas.tentatives_max and len(double.publiees) == 0
    assert etats.plier(journal)[publication_id].etat == "echec"


def test_la_reprise_apres_incertitude_survit_a_l_epuisement_des_tentatives(journal, pret, politique_sas):
    publication_id, _, fournisseur = pret
    double = doubles.DoubleFacebook(
        jeton_attendu=JETON, scenario=[doubles.PANNE_AVANT_ENVOI, doubles.PANNE_AVANT_ENVOI, doubles.PANNE_APRES_ENVOI]
    )
    for _ in range(3):
        sortir(journal, publication_id, double, fournisseur, politique_sas)
        reprise = executeur.reprendre(journal, publication_id, politique_sas, HORODATAGE)
    assert reprise["accepte"], "trois tentatives, la dernière incertaine : une reprise reste permise pour retrouver"
    final = sortir(journal, publication_id, double, fournisseur, politique_sas)
    assert final["publie"] and final["retrouvee"] and len(double.publiees) == 1


def test_sans_reprise_une_publication_en_echec_ne_sort_pas(journal, pret, politique_sas):
    publication_id, _, fournisseur = pret
    double = doubles.DoubleFacebook(jeton_attendu=JETON, scenario=[doubles.PANNE_AVANT_ENVOI])
    sortir(journal, publication_id, double, fournisseur, politique_sas)
    assert sortir(journal, publication_id, double, fournisseur, politique_sas)["refus"][0]["code"] == "REJ-SOCIAL-ETAT"


# -- secrets
# ----------------------------------------------------------------------------------------------------------------------
def test_le_jeton_n_entre_jamais_au_journal_meme_dans_un_message_d_erreur(journal, pret, politique_sas):
    publication_id, _, _ = pret
    jeton = "sk-fictif-0123456789abcdef"  # forme reconnue par le masquage permanent

    class Bavard(doubles.DoubleFacebook):
        def publier(self, requete, jeton_acces):
            raise ErreurReseau(
                "REJ-RESEAU-REFUS", f"le service a refusé le jeton {jeton_acces} pour ce compte", transitoire=True
            )

    bavard, fournisseur = Bavard(), Fournisseur(jeton)
    echec = sortir(journal, publication_id, bavard, fournisseur, politique_sas)
    assert jeton not in json.dumps(journal) and jeton not in json.dumps(echec)
    assert "•••" in journal[-1]["detail"]


def test_un_jeton_de_forme_quelconque_est_masque_pendant_l_appel_puis_oublie(journal, pret, politique_sas):
    publication_id, _, _ = pret
    jeton = "valeur-opaque-sans-forme-connue-123456"

    class Bavard(doubles.DoubleFacebook):
        def publier(self, requete, jeton_acces):
            raise ErreurReseau("REJ-RESEAU-REFUS", f"refus de {jeton_acces}", transitoire=True)

    sortir(journal, publication_id, Bavard(), Fournisseur(jeton), politique_sas)
    assert jeton not in json.dumps(journal)
    assert masquage.masquer_texte(jeton) == jeton, "le masquage a oublié la valeur après l'appel (rien n'est retenu)"


def test_une_exception_inattendue_de_l_adaptateur_ne_cite_pas_son_message(journal, pret, politique_sas):
    publication_id, _, _ = pret
    jeton = "valeur-opaque-sans-forme-connue-654321"

    class Casse(doubles.DoubleFacebook):
        def publier(self, requete, jeton_acces):
            raise RuntimeError(f"échec interne avec {jeton_acces}")

    resultat = sortir(journal, publication_id, Casse(), Fournisseur(jeton), politique_sas)
    assert jeton not in json.dumps(journal) and jeton not in json.dumps(resultat)
    assert journal[-1]["code"] == "REJ-SOCIAL-ERREUR-ADAPTATEUR" and journal[-1]["detail"] == "exception RuntimeError"
    assert journal[-1]["resultat_incertain"] is True


def test_le_jeton_passe_a_l_adaptateur_est_celui_du_fournisseur_et_le_double_le_refuse_sinon(
    journal, pret, politique_sas
):
    publication_id, _, _ = pret
    double = doubles.DoubleFacebook(jeton_attendu=JETON)
    refus = sortir(journal, publication_id, double, Fournisseur("autre-jeton-fictif-0123456789"), politique_sas)
    assert (
        refus["publie"] is False
        and refus["refus"][0]["code"] == "REJ-RESEAU-JETON-REFUSE"
        and refus["transitoire"] is False
    )
    assert len(double.publiees) == 0


def test_aucune_requete_d_adaptateur_ne_porte_un_jeton(journal, pret, politique_sas):
    publication_id, double, fournisseur = pret
    sortir(journal, publication_id, double, fournisseur, politique_sas)
    requete = double.publiees[0]["requete"]
    assert JETON not in repr(requete)
    assert {"jeton", "token", "secret"}.isdisjoint(requete.__dataclass_fields__)


# -- aucune entrée-sortie réseau dans le code du sas
# ------------------------------------------------------------------------------
def test_le_sas_n_importe_aucun_module_reseau_et_ne_lit_aucune_cle():
    racine = Path(__file__).resolve().parents[2] / "src" / "m7_marketing" / "sas_social"
    interdits = {
        "socket",
        "ssl",
        "http",
        "urllib",
        "urllib3",
        "requests",
        "httpx",
        "aiohttp",
        "smtplib",
        "ftplib",
        "subprocess",
        "facebook",
        "googleapiclient",
        "tweepy",
        "linkedin",
        "openai",
        "litellm",
    }
    for source in sorted(racine.glob("*.py")):
        arbre = ast.parse(source.read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            noms = (
                [a.name for a in noeud.names]
                if isinstance(noeud, ast.Import)
                else ([noeud.module] if isinstance(noeud, ast.ImportFrom) and noeud.module and not noeud.level else [])
            )
            assert not {n.split(".")[0] for n in noms} & interdits, (source.name, noms)
            if isinstance(noeud, ast.Name):
                assert noeud.id not in {"open", "eval", "exec", "__import__"}, (source.name, noeud.id)
        texte = source.read_text(encoding="utf-8")
        assert "os.environ" not in texte and "getenv" not in texte, source.name


# -- simulation : zéro doublon avec pannes
# ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("graine", [1, 2])
def test_mille_publications_avec_pannes_zero_doublon(declarations, politique_sas, proprietaire, graine):
    """R4 E6 : « 0 doublon sur 1 000 publications simulées avec pannes ». 1 000 publications (en 20 journaux de 50),
    un double
    qui échoue au hasard avant l'envoi, après l'envoi (réponse perdue) ou définitivement, et un exécuteur qui
    reprend."""
    hasard = random.Random(graine)
    issues = (
        [doubles.OK] * 55
        + [doubles.PANNE_AVANT_ENVOI] * 17
        + [doubles.PANNE_APRES_ENVOI] * 20
        + [doubles.PANNE_DEFINITIVE] * 8
    )

    def scenario():
        while True:
            yield hasard.choice(issues)

    double = doubles.DoubleFacebook(jeton_attendu=JETON, scenario=scenario())
    fournisseur = Fournisseur()
    publiees = definitives = 0
    total = 0
    for lot in range(20):
        comptes = {("facebook", f"page-{lot:02d}-{i:03d}") for i in range(50)}
        journal = []
        ids = []
        for i in range(50):
            donnees = publication("facebook", compte=f"page-{lot:02d}-{i:03d}")
            ids.append(
                planifiee(
                    journal,
                    comptes,
                    declarations,
                    politique_sas,
                    proprietaire,
                    donnees,
                    cle=f"cle-sim-{lot:02d}-{i:03d}-012345",
                )
            )
        for publication_id in ids:
            total += 1
            for _ in range(8):
                resultat = sortir(journal, publication_id, double, fournisseur, politique_sas)
                etat = etats.plier(journal)[publication_id]
                if etat.etat == "publie":
                    break
                reprise = (
                    executeur.reprendre(journal, publication_id, politique_sas, HORODATAGE)
                    if etat.etat == "echec"
                    else None
                )
                if reprise is not None and not reprise["accepte"]:
                    break
            etat = etats.plier(journal)[publication_id]
            publiees += etat.etat == "publie"
            definitives += etat.etat == "echec"
            assert etat.etat in ("publie", "echec"), (etat.etat, resultat)
        assert journal_chaine.verifier(journal) == []
    par_cle: dict[tuple[str, str], int] = {}
    for trace in double.publiees:
        cle = (trace["requete"].compte, trace["requete"].cle_idempotence)
        par_cle[cle] = par_cle.get(cle, 0) + 1
    assert total == 1000
    assert max(par_cle.values()) == 1, "doublon : une publication est sortie deux fois sur la plateforme"
    assert len(par_cle) == publiees, "toute publication sortie est connue du journal comme publiée, et inversement"
    assert publiees + definitives == 1000 and publiees > 700, (publiees, definitives)
    assert double.appels > 1000, "des pannes ont bien eu lieu"


def test_le_point_de_sortie_borne_lui_meme_les_tentatives_si_la_reprise_est_contournee(journal, pret, politique_sas):
    """Défense en profondeur : un journal où `reprise` a été écrit au-delà des bornes (accès direct au registre, chaîne
    refaite correctement) n'obtient pas une quatrième tentative."""
    publication_id, _, fournisseur = pret
    double = doubles.DoubleFacebook(jeton_attendu=JETON, scenario=[doubles.PANNE_AVANT_ENVOI] * 10)
    for _ in range(politique_sas.tentatives_max):
        sortir(journal, publication_id, double, fournisseur, politique_sas)
        journal_chaine.ajouter(journal, "reprise", {"publication_id": publication_id}, HORODATAGE)
    appels = double.appels
    refus = sortir(journal, publication_id, double, fournisseur, politique_sas)
    assert refus["publie"] is False and refus["refus"][0]["code"] == "REJ-SOCIAL-TENTATIVES-EPUISEES"
    assert double.appels == appels, "l'adaptateur n'est pas rappelé"
    assert etats.plier(journal)[publication_id].etat == "echec"
