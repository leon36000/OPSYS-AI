"""Tests des politiques revue/consensus/ratification (C01-005).

Contrat exact (task spec `tasks/C01-005.md`) :
- `evaluate_policy(policy: str, reviews: list[dict], ratifications:
  list[dict]) -> PolicyResult` : évalue UNE politique nommée contre
  l'ensemble des revues et/ou ratifications fournies.

`PolicyResult` : dataclass `{satisfied: bool, status: str, reasons:
tuple[str, ...]}` — reprend la forme éprouvée du harnais du pack
(`tools/review_policy.py::PolicyResult`), déjà mesurée correcte sur
7 tours de revue de phase C00 (aucune raison de réinventer une forme
différente pour l'équivalent PRODUIT).

Politiques et leur source de données :
- `NONE` : toujours satisfaite.
- `INDEPENDENT_REVIEW` (utilise `reviews`) : 0 objection CRITICAL
  ouverte, ≥1 verdict APPROVE parmi des `reviewer_id` DISTINCTS.
- `TRIAD_CONSENSUS` (utilise `reviews`) : 0 objection CRITICAL ouverte,
  ≥3 revues, ≥3 vendors distincts ET ≥3 failure_domains distincts
  (parmi TOUTES les revues), ≥2 APPROVE, ET parmi les APPROVE
  spécifiquement ≥2 vendors distincts ET ≥2 failure_domains distincts
  (l'indépendance de l'ACCORD, pas seulement de l'examen).
- `NATHAN_RATIFICATION` (utilise `ratifications`) : ≥1 ratification
  `decision == "APPROVE"`, `role == "NATHAN"`, ET
  `generated_by_agent` n'est PAS `True` — un modèle ne peut jamais
  produire une ratification T3 valide, même en se déclarant "NATHAN".
- `PROFESSIONAL_GATE` (utilise `ratifications`) : idem avec
  `role in {"CPA", "FISCALISTE", "AVOCAT", "NOTAIRE"}`.

Écrit par l'Orchestrateur AVANT toute implémentation (RED d'abord, TDD) —
le crew implémente `tools/proof/review_policy.py` (`evaluate_policy`) +
`tools/proof/ratification.py` (hachage des ratifications, utilisé en
interne) CONTRE ce fichier.
"""
from __future__ import annotations

from tools.proof.review_policy import PolicyResult, evaluate_policy


def _revue(vendor: str, domaine: str, verdict: str = "APPROVE", objections: list | None = None, reviewer_id: str | None = None) -> dict:
    return {
        "reviewer_id": reviewer_id or f"reviewer-{vendor}",
        "vendor": vendor,
        "failure_domain": domaine,
        "verdict": verdict,
        "objections": objections or [],
    }


def _objection_critique_ouverte() -> dict:
    return {"code": "x", "severity": "CRITICAL", "text": "y", "status": "OPEN"}


def _ratification(role: str, decision: str = "APPROVE", generated_by_agent: bool = False) -> dict:
    return {"role": role, "decision": decision, "generated_by_agent": generated_by_agent}


def test_impl_menter_les_politiques_revue_consensus_et_ratification_1():
    """Cas RED obligatoire : INDEPENDENT_REVIEW exige un reviewer
    distinct — une liste VIDE (aucun reviewer du tout) ne satisfait pas
    la politique ; un unique reviewer réellement identifié, même
    apparaissant deux fois dans la liste (ex. un retry), reste
    correctement compté comme UN SEUL reviewer distinct (pas zéro, pas
    deux) et satisfait la politique — la déduplication par set() est le
    comportement VOULU, pas une faille.

    Piège évité (mesuré) : une première version de ce test affirmait
    qu'un reviewer dupliqué NE devait PAS suffire — faux : un reviewer
    unique enregistré deux fois représente toujours exactement UN
    reviewer réel, pas une fraude. La spec elle-même ('compte les
    reviewer_id DISTINCTS ; si ce compte < 1') dit explicitement que
    ≥1 reviewer distinct suffit, quel que soit le nombre d'entrées."""
    resultat = evaluate_policy("INDEPENDENT_REVIEW", [], [])
    assert not resultat.satisfied

    resultat = evaluate_policy(
        "INDEPENDENT_REVIEW",
        [_revue("deepseek", "correction", reviewer_id="X"), _revue("deepseek", "correction", reviewer_id="X")],
        [],
    )
    assert resultat.satisfied, "un reviewer unique dupliqué dans la liste reste UN reviewer distinct, doit suffire"

    resultat = evaluate_policy(
        "INDEPENDENT_REVIEW",
        [_revue("deepseek", "correction", reviewer_id="X")],
        [],
    )
    assert resultat.satisfied, resultat.reasons


def test_impl_menter_les_politiques_revue_consensus_et_ratification_2():
    """Cas RED obligatoire : TRIAD_CONSENSUS exige trois vendors et
    failure domains distincts.

    Piège évité (mesuré) : une première version de ce test utilisait 3
    revues APPROVE toutes du même vendor (ou du même domaine) — ce
    scénario trippe AUSSI, par construction, le contrôle SÉPARÉ
    « indépendance des approbateurs » (les 3 APPROVE partageant le même
    vendor/domaine donnent MÉCANIQUEMENT approving_vendors ou
    approving_domains < 2), rendant la mutation du contrôle de diversité
    GLOBALE invisible. Corrigé : construit un cas où SEULE la diversité
    GLOBALE (vendors ou domaines sur TOUTES les revues) est insuffisante,
    tout en gardant les approbateurs eux-mêmes suffisamment divers entre
    eux (>=2 vendors ET >=2 domaines parmi les APPROVE) pour que SEUL le
    contrôle ciblé puisse intercepter la violation."""
    vendors_globaux_insuffisants = [
        _revue("deepseek", "correction", reviewer_id="A"),
        _revue("deepseek", "contrats", reviewer_id="B"),  # même vendor que A
        _revue("google", "securite", reviewer_id="C"),
    ]
    # 2 vendors distincts au total (deepseek, google) < 3 ; mais les
    # approbateurs eux-mêmes (tous APPROVE ici) ont 2 vendors ET 3
    # domaines distincts entre eux -> l'indépendance des APPROVE ne
    # peut PAS intercepter seule cette violation.
    resultat = evaluate_policy("TRIAD_CONSENSUS", vendors_globaux_insuffisants, [])
    assert not resultat.satisfied

    domaines_globaux_insuffisants = [
        _revue("deepseek", "correction", reviewer_id="A"),
        _revue("google", "correction", reviewer_id="B"),  # même domaine que A
        _revue("alibaba", "securite", reviewer_id="C"),
    ]
    # 2 domaines distincts au total < 3 ; approbateurs : 3 vendors ET 2
    # domaines distincts entre eux (>=2 des deux) -> indépendance seule
    # ne peut pas non plus intercepter.
    resultat = evaluate_policy("TRIAD_CONSENSUS", domaines_globaux_insuffisants, [])
    assert not resultat.satisfied

    valide = [
        _revue("deepseek", "correction", reviewer_id="A"),
        _revue("google", "contrats", reviewer_id="B"),
        _revue("alibaba", "securite", reviewer_id="C"),
    ]
    resultat = evaluate_policy("TRIAD_CONSENSUS", valide, [])
    assert resultat.satisfied, resultat.reasons


def test_impl_menter_les_politiques_revue_consensus_et_ratification_3():
    """Cas RED obligatoire : une objection CRITICAL ouverte bloque —
    quelle que soit la politique (INDEPENDENT_REVIEW ou TRIAD_CONSENSUS),
    même avec un consensus par ailleurs valide."""
    resultat = evaluate_policy(
        "INDEPENDENT_REVIEW",
        [_revue("deepseek", "correction", reviewer_id="A")],
        [],
    )
    assert resultat.satisfied

    avec_objection = [
        _revue("deepseek", "correction", reviewer_id="A", objections=[_objection_critique_ouverte()]),
    ]
    resultat = evaluate_policy("INDEPENDENT_REVIEW", avec_objection, [])
    assert not resultat.satisfied

    triad_valide_sauf_objection = [
        _revue("deepseek", "correction", reviewer_id="A", objections=[_objection_critique_ouverte()]),
        _revue("google", "contrats", reviewer_id="B"),
        _revue("alibaba", "securite", reviewer_id="C"),
    ]
    resultat = evaluate_policy("TRIAD_CONSENSUS", triad_valide_sauf_objection, [])
    assert not resultat.satisfied

    # Une objection RÉSOLUE (status != OPEN) ne bloque PAS.
    objection_resolue = dict(_objection_critique_ouverte())
    objection_resolue["status"] = "RESOLVED"
    triad_objection_resolue = [
        _revue("deepseek", "correction", reviewer_id="A", objections=[objection_resolue]),
        _revue("google", "contrats", reviewer_id="B"),
        _revue("alibaba", "securite", reviewer_id="C"),
    ]
    resultat = evaluate_policy("TRIAD_CONSENSUS", triad_objection_resolue, [])
    assert resultat.satisfied, resultat.reasons


def test_impl_menter_les_politiques_revue_consensus_et_ratification_4():
    """Cas RED obligatoire : NATHAN_RATIFICATION et PROFESSIONAL_GATE ne
    peuvent pas être simulés par un modèle — une ratification déclarant
    `generated_by_agent: True` (même avec role=NATHAN/CPA et
    decision=APPROVE) ne satisfait JAMAIS ces 2 politiques."""
    ratification_simulee = _ratification("NATHAN", generated_by_agent=True)
    resultat = evaluate_policy("NATHAN_RATIFICATION", [], [ratification_simulee])
    assert not resultat.satisfied

    ratification_reelle = _ratification("NATHAN", generated_by_agent=False)
    resultat = evaluate_policy("NATHAN_RATIFICATION", [], [ratification_reelle])
    assert resultat.satisfied, resultat.reasons

    pro_simulee = _ratification("CPA", generated_by_agent=True)
    resultat = evaluate_policy("PROFESSIONAL_GATE", [], [pro_simulee])
    assert not resultat.satisfied

    pro_reelle = _ratification("AVOCAT", generated_by_agent=False)
    resultat = evaluate_policy("PROFESSIONAL_GATE", [], [pro_reelle])
    assert resultat.satisfied, resultat.reasons

    # Rôle hors énumération humaine (même sans generated_by_agent) rejeté.
    role_invente = _ratification("MODELE-IA-QUELCONQUE", generated_by_agent=False)
    resultat = evaluate_policy("NATHAN_RATIFICATION", [], [role_invente])
    assert not resultat.satisfied


# ---------------------------------------------------------------------------
# Robustesse additionnelle.
# ---------------------------------------------------------------------------


def test_policy_none_toujours_satisfaite():
    """NONE est satisfaite quels que soient reviews/ratifications
    (y compris vides) — matches le contrat du harnais pack éprouvé."""
    resultat = evaluate_policy("NONE", [], [])
    assert resultat.satisfied

    resultat = evaluate_policy("NONE", [_revue("x", "y", verdict="REJECT")], [])
    assert resultat.satisfied


def test_policy_inconnue_rejetee():
    """Une chaîne de politique HORS de l'ensemble fermé connu est
    rejetée nommément, jamais silencieusement satisfaite par défaut."""
    resultat = evaluate_policy("POLITIQUE_INVENTEE", [], [])
    assert not resultat.satisfied


def test_triad_accord_independant_pas_seulement_examen():
    """D27 (leçon du harnais pack, reportée ici) : la diversité mesurée
    sur TOUTES les revues prouve que 3 voix ont EXAMINÉ le sujet, mais
    l'ACCORD (les APPROVE) doit venir de voix INDÉPENDANTES ENTRE ELLES.

    Piège évité (mesuré) : une première version (1 APPROVE + 2 REJECT)
    trippait le contrôle « au moins 2 APPROVE » AVANT même d'atteindre
    le contrôle d'indépendance ciblé — mutation invisible. Corrigé avec
    4 revues : 2 APPROVE PARTAGEANT le même vendor ET le même domaine
    (satisfait le compte >=2 mais PAS l'indépendance) + 2 REJECT qui
    fournissent la diversité GLOBALE manquante (3 vendors, 3 domaines
    au total) — isole l'indépendance des approbateurs seule."""
    deux_approve_non_independants = [
        _revue("deepseek", "correction", verdict="APPROVE", reviewer_id="A"),
        _revue("deepseek", "correction", verdict="APPROVE", reviewer_id="B"),  # même vendor+domaine que A
        _revue("google", "contrats", verdict="REJECT", reviewer_id="C"),
        _revue("alibaba", "securite", verdict="REJECT", reviewer_id="D"),
    ]
    resultat = evaluate_policy("TRIAD_CONSENSUS", deux_approve_non_independants, [])
    assert not resultat.satisfied, (
        "2 APPROVE du même vendor/domaine ne peuvent pas satisfaire "
        "TRIAD_CONSENSUS même si la diversité globale (via les REJECT) "
        "est présente"
    )


def test_triad_consensus_rejected_vs_approvals_not_independent_statuts_distincts():
    """Le statut CONSENSUS_REJECTED (moins de 2 APPROVE) est
    STRUCTURELLEMENT subsumé par APPROVALS_NOT_INDEPENDENT pour le seul
    booléen satisfied (0 ou 1 APPROVE implique toujours <2 vendors/
    domaines distincts parmi les approbateurs) — mais sa valeur réelle
    est DIAGNOSTIQUE : un orchestrateur qui lit `status` doit pouvoir
    distinguer « il manque des revues » de « les revues existent mais
    ne sont pas indépendantes », deux actions correctives différentes.
    Vérifié sur le STATUS exact, pas seulement sur satisfied."""
    un_seul_approve_diversite_globale_ok = [
        _revue("deepseek", "correction", verdict="APPROVE", reviewer_id="A"),
        _revue("google", "contrats", verdict="REJECT", reviewer_id="B"),
        _revue("alibaba", "securite", verdict="REJECT", reviewer_id="C"),
    ]
    resultat = evaluate_policy("TRIAD_CONSENSUS", un_seul_approve_diversite_globale_ok, [])
    assert not resultat.satisfied
    assert resultat.status == "CONSENSUS_REJECTED", resultat.status


def test_policy_result_est_un_objet_structure():
    resultat = evaluate_policy("NONE", [], [])
    assert isinstance(resultat, PolicyResult)
    assert isinstance(resultat.satisfied, bool)
    assert isinstance(resultat.status, str)
    assert resultat.status
    assert isinstance(resultat.reasons, tuple)


def test_ratification_hachage_deterministe_et_sensible_au_contenu():
    """« hacher les ratifications » (implémentation strictement bornée) :
    tools/proof/ratification.py expose une fonction de hachage canonique
    — même ratification -> même hash (déterminisme), ratification
    modifiée -> hash différent (sensibilité au contenu), jamais une
    valeur aléatoire ou dépendante de l'ordre d'insertion des clés."""
    from tools.proof.ratification import hash_ratification

    r1 = _ratification("NATHAN", generated_by_agent=False)
    r2 = dict(r1)  # même contenu, ordre de construction différent
    h1 = hash_ratification(r1)
    h2 = hash_ratification(r2)
    assert isinstance(h1, str)
    assert len(h1) == 64  # sha256 hex
    assert h1 == h2, "même contenu doit produire le même hash"

    r3 = _ratification("NATHAN", generated_by_agent=True)  # 1 champ diffère
    h3 = hash_ratification(r3)
    assert h3 != h1, "un contenu différent doit produire un hash différent"
