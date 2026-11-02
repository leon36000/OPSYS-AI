"""Entrées fictives du rapport hebdomadaire (M7-RAPPORT-HEBDO) : mesures de M8, contenus mesurés, performance, avis."""

from __future__ import annotations

import copy

import pytest

FICTIF = True
LUNDI = "2026-10-26"
DIMANCHE = "2026-11-01"


def mesure(metric_id, valeur, statut="calculee", fraicheur="a_jour", unite="CAD", couverture="complete"):
    return {
        "metric_id": metric_id,
        "valeur": valeur,
        "unite": unite,
        "statut": statut,
        "fraicheur": fraicheur,
        "couverture": couverture,
        "a_jour": fraicheur == "a_jour" and statut == "calculee",
    }


def contenu(cle, canal="facebook", leads=0, envoyes=0, acceptes=0, suivi="lien", exporte="2026-10-05T10:00:00-04:00"):
    mesurable = suivi == "lien"
    return {
        "utm_content": cle,
        "canal": canal,
        "exporte_le": exporte,
        "suivi": suivi,
        "leads": leads if mesurable else None,
        "devis_envoyes": envoyes if mesurable else None,
        "devis_acceptes": acceptes if mesurable else None,
    }


def observation(oid, plateforme, campagne, valeur, fin="2026-10-25", metrique="taux_engagement", unite="pct"):
    return {
        "observation_id": oid,
        "metrique": metrique,
        "valeur": valeur,
        "unite": unite,
        "periode": {"debut": fin, "fin": fin},
        "plateforme": plateforme,
        "campagne": campagne,
    }


ENTREES_RICHES = {
    "m8_mesures": [
        mesure("m8_cout_par_lead_pub_cad", "42.50"),
        mesure("m8_leads_publicitaires", "8", unite="leads"),
        mesure("m8_depense_pub_comptabilisee_cad", "340.00"),
        mesure("m8_leads_recus", "20", unite="leads"),
    ],
    "m8_contenus": [
        contenu("facebook-aaaa", "facebook", leads=4, envoyes=3, acceptes=2),
        contenu("instagram-bbbb", "instagram", leads=2, envoyes=1, acceptes=0),
        contenu("fiche_google-cccc", "fiche_google", leads=0),
        contenu("video_courte-dddd", "video_courte", leads=0),
        contenu("facebook-eeee", "facebook", suivi="sans_lien"),
    ],
    "performance": {
        "campagnes": [
            {
                "source": "facebook",
                "campagne": "contenu-2026",
                "leads_associes_observes": 5,
                "devis_acceptes": 2,
                "marge_constatee_M5_cad": "3100.00",
                "couverture": "PARTIELLE",
                "manque": ["MARGE_M5_PARTIELLE"],
            },
            {
                "source": "google",
                "campagne": "gbp",
                "leads_associes_observes": 3,
                "devis_acceptes": 0,
                "marge_constatee_M5_cad": None,
                "couverture": "PARTIELLE",
                "manque": [],
            },
            {
                "source": None,
                "campagne": None,
                "leads_associes_observes": 2,
                "devis_acceptes": 0,
                "marge_constatee_M5_cad": None,
                "couverture": "INCONNUE",
                "manque": ["ATTRIBUTION_ABSENTE"],
            },
        ]
    },
    "reputation": {
        "avis_semaine": 4,
        "note_moyenne_semaine": 3.75,
        "categories": {"eloge": 2, "urgence": 2, "litige": 0, "neutre": 0},
        "sans_reponse": 3,
        "negatifs_sans_reponse": 2,
    },
    "calendrier": {
        "en_attente_de_decision": 2,
        "approuves_non_exportes": 1,
        "exportes_semaine": 0,
        "creneaux_semaine": 0,
    },
    "croissance": [
        observation("obs-fb-reel-1", "facebook", "format:reel", 6.0),
        observation("obs-fb-reel-2", "facebook", "format:reel", 7.0),
        observation("obs-fb-reel-3", "facebook", "format:reel", 8.0),
        observation("obs-fb-photo-1", "facebook", "format:photo", 3.0),
        observation("obs-fb-photo-2", "facebook", "format:photo", 4.0),
        observation("obs-fb-photo-3", "facebook", "format:photo", 2.0),
        observation(
            "obs-ig-abonnes-1", "instagram", "croissance", 120, fin="2026-10-11", metrique="abonnes", unite="abonnés"
        ),
        observation(
            "obs-ig-abonnes-2", "instagram", "croissance", 100, fin="2026-10-25", metrique="abonnes", unite="abonnés"
        ),
    ],
}


@pytest.fixture
def entrees():
    return copy.deepcopy(ENTREES_RICHES)


@pytest.fixture
def fab():
    import types

    return types.SimpleNamespace(
        mesure=mesure, contenu=contenu, observation=observation, LUNDI=LUNDI, DIMANCHE=DIMANCHE, RICHES=ENTREES_RICHES
    )
