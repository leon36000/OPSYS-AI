"""Demande de génération (outil, N2) et exécuteur de génération (hors transaction).

Même séparation que le sas social et WordPress : un OUTIL d'agent ne génère rien et n'appelle aucun modèle ; il consigne
une DEMANDE (brief, modèle sélectionné par le registre, invite, dimensions, graine, instantané de licence). L'EXÉCUTEUR,
appelé par un processus séparé qui peut ouvrir le coffre (un secret ne se résout pas dans une transaction métier),
refait
la sélection (le registre peut avoir changé), refuse tout remplacement de modèle, appelle l'adaptateur par le port,
revérifie la sortie, écrit la PROVENANCE puis l'actif `fond`. Aucun planificateur ne l'appelle dans cette version.

Fail-closed : aucun adaptateur pour le fournisseur sélectionné = échec typé (aucun repli sur un autre) ; un brief non
fictif refuse un générateur double ; une licence devenue non conforme ou un modèle changé depuis la demande = échec ;
trois
échecs closent la demande ; un message d'erreur d'adaptateur est masqué (secrets) et tronqué avant d'entrer au journal.

Module sans entrée-sortie propre : journaux, sélection du modèle, écriture du fichier et horloge sont des arguments.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Callable, Mapping
from typing import Any

from opsys.secrets_coffre import masquage

from .. import journal_chaine
from . import actifs, gabarits, generation, modeles, provenance
from .brief import Brief

REGISTRE = ("m07-marketing", "jobs_studio")
M_DEMANDE = "demande_generation"
M_TERMINEE = "generation_terminee"
M_ECHEC = "generation_echouee"
TENTATIVES_MAX = 3
DETAIL_MAX = 300
REJ_JOBS_ALTERE = "REJ-STUDIO-JOBS-JOURNAL-ALTERE"
REJ_JOB_INCONNU = "REJ-STUDIO-JOB-INCONNU"
REJ_MODELE_CHANGE = "REJ-STUDIO-MODELE-CHANGE"
REJ_TENTATIVES = "REJ-STUDIO-GENERATION-TENTATIVES-EPUISEES"
REJ_FOND_NON_DEMANDE = "REJ-STUDIO-BRIEF-SANS-FOND-GENERE"
REJ_SORTIE_NON_ECRITE = "REJ-STUDIO-FOND-NON-ECRIT"


def _refus(code: str, chemin: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "refus": [{"code": code, "chemin": chemin, "detail": detail}]}


def identifiant_job(brief_empreinte: str, genre: str, variante: int) -> str:
    return "job-" + hashlib.sha256(f"{brief_empreinte}\n{genre}\n{variante}".encode()).hexdigest()[:16]


@dataclasses.dataclass(frozen=True)
class EtatJob:
    job_id: str
    demande: Mapping[str, Any]
    etat: str  # en_attente | terminee | echec
    echecs: int
    resultat: Mapping[str, Any] | None


def plier(journal: Any) -> dict[str, EtatJob]:
    jobs: dict[str, EtatJob] = {}
    for m in journal_chaine.maillons(journal):
        jid = m["job_id"]
        if m["type"] == M_DEMANDE:
            jobs[jid] = EtatJob(jid, m, "en_attente", 0, None)
        elif jid in jobs and m["type"] == M_TERMINEE:
            jobs[jid] = dataclasses.replace(jobs[jid], etat="terminee", resultat=m)
        elif jid in jobs and m["type"] == M_ECHEC:
            jobs[jid] = dataclasses.replace(jobs[jid], etat="echec", echecs=jobs[jid].echecs + 1, resultat=m)
    return jobs


def charger(journal: Any) -> tuple[dict[str, EtatJob], dict[str, Any] | None]:
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return {}, _refus(REJ_JOBS_ALTERE, "$", "; ".join(problemes[:3]))
    return plier(journal), None


def demander_generation(
    journal: Any,
    brief_id: str,
    brief: Brief,
    selection: modeles.SelectionModele,
    *,
    par: str,
    horodatage: str,
    maintenant: Any,
    variante: int = 0,
    ppp: int | None = None,
) -> dict[str, Any]:
    """Consigne une demande de fond généré. N'appelle aucun modèle."""
    if not brief.genere:
        return _refus(REJ_FOND_NON_DEMANDE, "$.fond.mode", "ce brief n'a pas de fond généré (mode « genere » exigé)")
    jobs, refus = charger(journal)
    if refus is not None:
        return refus
    genre = selection.fournisseur.capacite
    job_id = identifiant_job(brief.empreinte(), genre, variante)
    existant = jobs.get(job_id)
    if existant is not None:
        return {"accepte": True, "job_id": job_id, "etat": existant.etat, "deja_demande": True}
    fmt = gabarits.format_de(brief.gabarit, brief.format)
    geo = gabarits.geometrie(fmt, ppp or brief.donnees.get("ppp") or fmt.ppp_defaut)
    largeur, hauteur = generation.dimensions_du_fond(geo.largeur, geo.hauteur)
    invite, negative = generation.construire_invite(brief)
    graine = (
        brief.fond["graine"]
        if "graine" in brief.fond and variante == 0
        else generation.graine_par_defaut(brief.empreinte(), job_id)
    )
    demande = generation.DemandeGeneration(
        job_id,
        brief_id,
        brief.empreinte(),
        genre,
        invite,
        negative,
        largeur,
        hauteur,
        graine,
        duree_s=5 if genre == "video" else None,
        images_par_seconde=8 if genre == "video" else None,
        parametres={"fond_spec_empreinte": brief.empreinte_fond(), "variante": variante},
    )
    journal_chaine.ajouter(
        journal,
        M_DEMANDE,
        {
            "job_id": job_id,
            "brief_id": brief_id,
            "brief_empreinte": brief.empreinte(),
            "genre": genre,
            "fournisseur_id": selection.fournisseur.identifiant,
            "fictif": brief.fictif,
            "licence": selection.instantane(maintenant),
            "demande": demande.vers_dict(),
            "fond_spec_empreinte": brief.empreinte_fond(),
            "par": par,
        },
        horodatage,
    )
    return {
        "accepte": True,
        "job_id": job_id,
        "etat": "en_attente",
        "deja_demande": False,
        "fournisseur": selection.fournisseur.identifiant,
        "graine": graine,
        "execution": "Aucune : la génération est faite par un exécuteur hors transaction, jamais par un outil d'agent.",
    }


def executer(
    journal_jobs: Any,
    journal_provenance: Any,
    journal_actifs: Any,
    job_id: str,
    *,
    adaptateurs: Mapping[str, Any],
    resoudre_modele: Callable[[str], modeles.SelectionModele],
    ecrire_fond: Callable[[str, bytes, str], None],
    par: str,
    horodatage: str,
    maintenant: Any,
) -> dict[str, Any]:
    """Exécute UNE demande : sélection refaite, adaptateur appelé, provenance écrite, fond enregistré."""
    jobs, refus = charger(journal_jobs)
    if refus is not None:
        return refus
    job = jobs.get(job_id)
    if job is None:
        return _refus(REJ_JOB_INCONNU, "$.job_id", f"demande inconnue : {job_id!r}")
    if job.etat == "terminee":
        return {
            "accepte": True,
            "job_id": job_id,
            "etat": "terminee",
            "deja_execute": True,
            "fond_actif_id": job.resultat["fond_actif_id"],
            "provenance_chaine": job.resultat["provenance_chaine"],
        }
    if job.echecs >= TENTATIVES_MAX:
        return _refus(REJ_TENTATIVES, "$.job_id", f"{TENTATIVES_MAX} échecs : refaire une demande (autre variante)")

    def echouer(code: str, detail: str) -> dict[str, Any]:
        journal_chaine.ajouter(
            journal_jobs,
            M_ECHEC,
            {"job_id": job_id, "code": code, "detail": masquage.masquer_texte(detail)[:DETAIL_MAX]},
            horodatage,
        )
        return _refus(code, "$.job_id", masquage.masquer_texte(detail)[:DETAIL_MAX])

    demande_brute = job.demande["demande"]
    demande = generation.DemandeGeneration(**{**demande_brute, "parametres": dict(demande_brute["parametres"])})
    try:
        selection = resoudre_modele(demande.genre)
    except modeles.ModeleRefuse as exc:
        return echouer(exc.code, f"{exc.detail} {list(exc.refus)}")
    if selection.fournisseur.identifiant != job.demande["fournisseur_id"]:
        return echouer(
            REJ_MODELE_CHANGE,
            f"le modèle sélectionné est devenu {selection.fournisseur.identifiant}, la "
            f"demande portait sur {job.demande['fournisseur_id']} : refaire la demande (aucun remplacement)",
        )
    adaptateur = adaptateurs.get(selection.fournisseur.identifiant)
    if adaptateur is None:
        return echouer(
            generation.REJ_ADAPTATEUR_ABSENT,
            f"aucun adaptateur n'est branché pour {selection.fournisseur.identifiant} (aucun repli sur un "
            "autre modèle)",
        )
    if not job.demande["fictif"] and adaptateur.nature != generation.NATURE_REEL:
        return echouer(
            generation.REJ_GENERATEUR_DE_TEST, "un brief non fictif n'accepte pas un générateur de test (double)"
        )
    try:
        sortie = adaptateur.generer(demande)
        generation.verifier_sortie(sortie, demande)
    except generation.ErreurGeneration as exc:
        return echouer(exc.code, exc.detail)
    except Exception as exc:  # noqa: BLE001 - toute panne d'adaptateur devient un échec typé, masqué
        return echouer(generation.REJ_GENERATION, f"{type(exc).__name__}: {exc}")
    sha = hashlib.sha256(sortie.octets).hexdigest()
    maillon = provenance.trouver_par_sortie(journal_provenance, sha)
    if maillon is None:
        maillon = provenance.enregistrer(
            journal_provenance,
            demande,
            sortie,
            selection.instantane(maintenant),
            selection.fournisseur.identifiant,
            par,
            horodatage,
        )
    try:
        ecrire_fond(sha, sortie.octets, sortie.format)
    except OSError as exc:
        return echouer(REJ_SORTIE_NON_ECRITE, f"{type(exc).__name__}")
    resultat = actifs.enregistrer_fond(
        journal_actifs,
        sha256=sha,
        format_=sortie.format,
        largeur=sortie.largeur,
        hauteur=sortie.hauteur,
        genre=demande.genre,
        brief_id=demande.brief_id,
        brief_empreinte=demande.brief_empreinte,
        fond_spec_empreinte=job.demande["fond_spec_empreinte"],
        provenance_chaine=maillon["chaine"],
        nature_generateur=sortie.nature,
        fictif=bool(job.demande["fictif"]),
        par=par,
        horodatage=horodatage,
    )
    if not resultat.get("accepte"):
        return resultat
    journal_chaine.ajouter(
        journal_jobs,
        M_TERMINEE,
        {
            "job_id": job_id,
            "fond_actif_id": resultat["actif_id"],
            "provenance_chaine": maillon["chaine"],
            "sortie_sha256": sha,
        },
        horodatage,
    )
    return {
        "accepte": True,
        "job_id": job_id,
        "etat": "terminee",
        "fond_actif_id": resultat["actif_id"],
        "provenance_chaine": maillon["chaine"],
        "nature_generateur": sortie.nature,
        "deja_execute": False,
    }
