"""Tests pour core/src/opsys_core/{errors,result}.py (C03-004) — taxonomie
d'erreurs Core.

Couvre les 3 cas RED obligatoires de tasks/C03-004.md :
  1. séparer VALIDATION, POLICY_DENIED, PREREQUISITE_MISSING, CONFLICT,
     IN_DOUBT, EXTERNAL_FAILURE
  2. ne jamais exposer secret/PII
  3. erreur inconnue = UNKNOWN_FAILURE, jamais succès
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from opsys_core.errors import CoreError, ErrorCode, mapper_exception  # noqa: E402
from opsys_core.result import Result, executer  # noqa: E402


# ---------------------------------------------------------------------------
# Cas RED 1 — séparer les 6 codes métier (+ UNKNOWN_FAILURE, cas RED 3)
# ---------------------------------------------------------------------------


def test_d_finir_la_taxonomie_d_erreurs_core_1():
    """Cas RED #1 — les 6 codes métier nommés existent, distincts."""
    attendu_metier = {
        "VALIDATION", "POLICY_DENIED", "PREREQUISITE_MISSING",
        "CONFLICT", "IN_DOUBT", "EXTERNAL_FAILURE",
    }
    noms = {c.name for c in ErrorCode}
    assert attendu_metier <= noms, f"codes métier manquants : {attendu_metier - noms}"
    assert "UNKNOWN_FAILURE" in noms, "UNKNOWN_FAILURE (cas RED #3) doit aussi exister"


def test_vocabulaire_errorcode_est_exactement_les_7_codes():
    """Balayage exhaustif : ErrorCode contient EXACTEMENT ces 7 codes,
    jamais un code inventé, jamais un code manquant."""
    attendu = {
        "VALIDATION", "POLICY_DENIED", "PREREQUISITE_MISSING", "CONFLICT",
        "IN_DOUBT", "EXTERNAL_FAILURE", "UNKNOWN_FAILURE",
    }
    assert {c.name for c in ErrorCode} == attendu


def test_core_error_refuse_un_code_hors_taxonomie():
    """Un CoreError avec un code hors taxonomie (chaîne arbitraire) doit
    être refusé — les codes doivent rester STABLES et fermés."""
    with pytest.raises(ValueError):
        CoreError(code="CODE_INVENTE_HORS_TAXONOMIE", retryable=False, safe_message="x")


def test_core_error_accepte_chaque_code_de_la_taxonomie():
    for code in ErrorCode:
        # ne doit jamais lever pour un code réellement dans la taxonomie
        CoreError(code=code.value, retryable=False, safe_message="message sûr générique")


# ---------------------------------------------------------------------------
# Cas RED 2 — ne jamais exposer secret/PII
# ---------------------------------------------------------------------------


def test_d_finir_la_taxonomie_d_erreurs_core_2():
    """Cas RED #2 — mapper une exception dont le message brut contient un
    secret NE DOIT JAMAIS faire fuiter ce secret dans safe_message."""
    exc = ValueError("connexion refusée: password=hunter2 sur postgres://user:hunter2@host/db")  # proof:allow — secret synthétique de test, jamais réel
    erreur = mapper_exception(exc)
    assert "hunter2" not in erreur.safe_message, "GARDE RETIRÉE : le secret a fuité dans safe_message"
    assert "password" not in erreur.safe_message.lower()
    assert "postgres://" not in erreur.safe_message


def test_mapper_exception_avec_pii_ne_fuite_pas_non_plus():
    """Contrôle complémentaire : un message contenant une PII (email/NAS)
    ne doit pas non plus fuiter."""
    exc = RuntimeError("échec pour l'utilisateur jean.dupont@example.com, NAS 123-456-789")
    erreur = mapper_exception(exc)
    assert "jean.dupont@example.com" not in erreur.safe_message
    assert "123-456-789" not in erreur.safe_message


def test_mapper_exception_preserve_le_type_pour_diagnostic():
    """safe_message peut nommer le TYPE de l'exception (générique, jamais
    sensible) — sinon aucun diagnostic n'est possible du tout."""
    exc = ConnectionError("host=secret-internal-db.local port=5432 user=admin pass=xyz")
    erreur = mapper_exception(exc)
    assert "ConnectionError" in erreur.safe_message
    assert "secret-internal-db" not in erreur.safe_message
    assert "xyz" not in erreur.safe_message


def test_mapper_exception_produit_un_details_ref_pour_retrouver_la_cause():
    """« préserver cause interne dans la preuve » : details_ref doit être
    un pointeur déterministe et non vide vers la cause complète — jamais
    la cause elle-même directement dans le CoreError."""
    exc = ValueError("secret=abc123")  # proof:allow — secret synthétique de test, jamais réel
    erreur = mapper_exception(exc)
    assert erreur.details_ref, "details_ref doit être renseigné pour retrouver la cause"
    assert "abc123" not in erreur.details_ref, "details_ref ne doit pas non plus contenir le secret en clair"


def test_mapper_exception_details_ref_est_deterministe_content_addressed():
    """Deux appels avec des exceptions IDENTIQUES (même type, même message)
    produisent le MÊME details_ref — corrélation fiable, jamais un id
    aléatoire qui empêcherait de retrouver deux occurrences de la même cause."""
    e1 = mapper_exception(ValueError("panne identique"))
    e2 = mapper_exception(ValueError("panne identique"))
    assert e1.details_ref == e2.details_ref


def test_mapper_exception_details_ref_resiste_a_une_attaque_par_dictionnaire():
    """Cas RED sécurité (revue TRIAD_CONSENSUS clôture C03, DeepSeek-V4-Pro,
    MAJEURE, confirmée par lecture directe de la source) : un sha256 NU et
    NON SALÉ de repr(exc) est un ORACLE d'énumération — un attaquant qui
    suppose un secret à faible entropie (ex. un mot de passe candidat) peut
    précalculer son hash HORS LIGNE avec la même formule et le comparer à
    details_ref, confirmant sa supposition sans jamais voir le secret en
    clair. « jamais la cause elle-même exposée directement » (docstring du
    module) doit aussi couvrir cette fuite indirecte par oracle — pas
    seulement l'absence littérale du secret dans la chaîne (déjà couverte
    par test_mapper_exception_produit_un_details_ref_pour_retrouver_la_cause
    ci-dessus, qui ne teste PAS ce mode d'attaque). Le déterminisme
    INTRA-PROCESS testé ci-dessus doit être préservé (pas de sel aléatoire
    PAR APPEL) — la clé doit être fixe pour le process, secrète, et absente
    de toute donnée dérivable de repr(exc) seul."""
    secret_candidat = "mot-de-passe-invalide-1234"  # proof:allow — secret synthétique de test, jamais réel
    exc = ValueError(secret_candidat)
    empreinte_hash_nu = hashlib.sha256(repr(exc).encode("utf-8")).hexdigest()

    erreur = mapper_exception(exc)

    assert f"sha256:{empreinte_hash_nu}" != erreur.details_ref, (
        "ORACLE: details_ref reproductible par un simple sha256(repr(exc)) "
        "calculé hors ligne — un attaquant peut vérifier une supposition de "
        "secret sans jamais y avoir accès"
    )


# ---------------------------------------------------------------------------
# Cas RED 3 — erreur inconnue = UNKNOWN_FAILURE, jamais succès
# ---------------------------------------------------------------------------


def test_d_finir_la_taxonomie_d_erreurs_core_3():
    """Cas RED #3 — une exception totalement inattendue (aucun code
    spécifié par l'appelant) devient UNKNOWN_FAILURE, jamais un succès."""
    def _panne_totalement_inattendue():
        raise KeyError("clé jamais vue")

    resultat = executer(_panne_totalement_inattendue)
    assert not resultat.is_ok, "GARDE RETIRÉE : une exception ne doit jamais produire un Result réussi"
    assert resultat.error is not None
    assert resultat.error.code == ErrorCode.UNKNOWN_FAILURE.value


def test_executer_avec_succes_produit_un_result_ok():
    resultat = executer(lambda: 42)
    assert resultat.is_ok
    assert resultat.value == 42
    assert resultat.error is None


def test_executer_avec_code_specifie_respecte_ce_code():
    """Quand l'appelant précise un code CONNU de la taxonomie, il est
    respecté — UNKNOWN_FAILURE reste réservé au cas non spécifié."""
    def _echec_validation():
        raise ValueError("champ requis manquant")

    resultat = executer(_echec_validation, code=ErrorCode.VALIDATION.value)
    assert not resultat.is_ok
    assert resultat.error.code == ErrorCode.VALIDATION.value


def test_executer_avec_code_invalide_specifie_retombe_sur_unknown_failure():
    """Un code hors taxonomie fourni par erreur ne doit jamais se propager
    tel quel — retombe sur UNKNOWN_FAILURE plutôt que de corrompre le
    contrat de codes stables."""
    def _plante():
        raise RuntimeError("x")

    resultat = executer(_plante, code="CECI_N_EST_PAS_UN_CODE_VALIDE")
    assert resultat.error.code == ErrorCode.UNKNOWN_FAILURE.value


def test_result_ne_peut_pas_porter_valeur_et_erreur_simultanement():
    with pytest.raises(ValueError):
        Result(value=42, error=CoreError(code=ErrorCode.VALIDATION.value, retryable=False, safe_message="x"))


def test_result_ok_avec_valeur_none_reste_un_succes():
    """Une opération qui réussit et retourne None (ex. suppression) reste
    un SUCCÈS — value=None ne doit jamais être confondu avec un échec."""
    resultat = Result.ok(None)
    assert resultat.is_ok
    assert resultat.error is None


# ---------------------------------------------------------------------------
# Robustesse structurelle
# ---------------------------------------------------------------------------


def test_core_error_est_gele():
    erreur = CoreError(code=ErrorCode.VALIDATION.value, retryable=False, safe_message="x")
    with pytest.raises(Exception):
        erreur.safe_message = "message modifié"  # type: ignore[misc]


def test_result_est_gele():
    resultat = Result.ok(1)
    with pytest.raises(Exception):
        resultat.value = 2  # type: ignore[misc]
