"""M9.4/M9.23 — réaudit : statuts d'une citation face aux captures (immuables, plus récentes, absentes) (fictif)."""

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import reaudit_conseil as ra

FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"
LECTURE = "m2.leads"
CHEMIN = "resultat.resultat.total"


def _chaine(*totaux, arguments=None):
    """Une capture de m2.leads par total (None = fait absent), arguments identiques sauf demande contraire."""
    chaine, precedent = [], cs.HASH_INITIAL
    for index, total in enumerate(totaux):
        contenu = {} if total is None else {"total": total}
        reponse = {"ok": True, "resultat": {"accepte": True, "resultat": contenu}}
        capture = cs.construire(
            cat.obtenir(LECTURE),
            (arguments or {}).get(index, {"horodatage": "2026-10-20T12:00:00Z"}),
            [reponse],
            recu_a=f"2026-10-2{index + 1}T12:00:00Z",
            reference=None,
            index=index,
            hash_precedent=precedent,
        )
        chaine.append(capture)
        precedent = capture["hash_maillon"]
    return chaine


def _citer(chaine, reference, valeur, connaissance=CONNAISSANCE):
    connues = cs.connues_a(chaine, connaissance)
    conflits = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
    return ra._citation(chaine, connues, conflits, reference, valeur)


def test_a_jour_quand_aucune_capture_plus_recente_ou_meme_valeur():
    chaine = _chaine("3")
    assert _citer(chaine, f"{LECTURE}#0:p0.{CHEMIN}", "3")["statut"] == "A_JOUR"
    deux = _chaine("3", "3")
    assert _citer(deux, f"{LECTURE}#0:p0.{CHEMIN}", "3") | {} == {
        "reference": f"{LECTURE}#0:p0.{CHEMIN}", "valeur_citee": "3", "statut": "A_JOUR", "capture_la_plus_recente": 1,
    }  # fmt: skip


def test_source_plus_recente_differente_et_fait_disparu():
    chaine = _chaine("3", "5")
    ligne = _citer(chaine, f"{LECTURE}#0:p0.{CHEMIN}", "3")
    assert ligne["statut"] == "SOURCE_PLUS_RECENTE_DIFFERENTE" and ligne["valeur_plus_recente"] == "5"
    assert ligne["adresse_plus_recente"] == f"{LECTURE}#1:p0.{CHEMIN}"
    disparu = _chaine("3", None)
    assert _citer(disparu, f"{LECTURE}#0:p0.{CHEMIN}", "3")["statut"] == "PLUS_RECENTE_SANS_LE_FAIT"


def test_une_capture_plus_recente_apres_la_connaissance_ou_d_autres_arguments_est_ignoree():
    chaine = _chaine("3", "5")
    assert _citer(chaine, f"{LECTURE}#0:p0.{CHEMIN}", "3", connaissance="2026-10-21T18:00:00Z")["statut"] == "A_JOUR"
    autres = _chaine("3", "5", arguments={1: {"horodatage": "2026-10-20T12:00:00Z", "decalage": 5}})
    assert _citer(autres, f"{LECTURE}#0:p0.{CHEMIN}", "3")["statut"] == "A_JOUR", (
        "autre série : ni plus récente ni liée"
    )


@pytest.mark.parametrize(
    "reference, valeur, statut",
    [
        (f"{LECTURE}#9:p0.{CHEMIN}", "3", "CAPTURE_INTROUVABLE"),
        (f"m6.disponibilite#0:p0.{CHEMIN}", "3", "CAPTURE_INTROUVABLE"),
        ("n'importe quoi", "3", "CAPTURE_INTROUVABLE"),
        (f"{LECTURE}#0:p0.{CHEMIN}", "4", "VALEUR_DIFFERENTE_DANS_LA_CAPTURE"),
    ],
)
def test_citation_falsifiee_ou_registre_altere_est_nommee(reference, valeur, statut):
    assert _citer(_chaine("3"), reference, valeur)["statut"] == statut


def test_instant_invalide_refuse_et_statuts_a_revoir_sont_les_quatre_attendus():
    with pytest.raises(ValueError, match="REJ-REAUDIT-TEMPS"):
        ra.reauditer([], [], session_id="s", connaissance="demain")
    assert {
        "SOURCE_PLUS_RECENTE_DIFFERENTE", "PLUS_RECENTE_SANS_LE_FAIT", "CAPTURE_INTROUVABLE",
        "VALEUR_DIFFERENTE_DANS_LA_CAPTURE",
    } == ra.STATUTS_A_REVOIR  # fmt: skip
