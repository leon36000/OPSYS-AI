"""Service propriétaire M5 du dossier de paie préparatoire : aperçu, versions, corrections, rebase, comparaison.

Orchestration seulement : les montants viennent des moteurs publics via `dossier_paie_preparatoire.composer`,
les heures et le taux d'un fournisseur de brut injecté (`preparer_brut_regulier`, donc le port M4 en lecture et le
contrat M5), l'admission documentaire d'un fournisseur serveur injecté. Aucun fournisseur ne reçoit un résultat de
l'appelant. Rien n'écrit dans M4, dans le grand livre, les obligations, les paiements ou les factures : le seul
effet d'écriture est un événement chiffré du journal `dossiers_paie_preparatoires`.

Un aperçu ne persiste rien. Conserver une version exige l'empreinte exacte de l'aperçu vu par l'humain ; si une source a
changé entre-temps, la conservation est refusée et l'aperçu doit être refait.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import Connection

from . import dossier_paie_preparatoire as dossier
from . import journal_dossiers_paie as journal

FournisseurBrut = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
FournisseurAdmission = Callable[[Mapping[str, Any]], Mapping[str, Any]]

_CHAMPS_ADMISSION = ("admissible", "motifs", "sources_verifiees", "empreintes_sources", "schema")


ServiceErreur = dossier.DossierErreur


def _lever(code: str, detail: str) -> ServiceErreur:
    return ServiceErreur(dossier.refus(code, detail))


def _resume_admission(admission: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(admission, Mapping):
        return {
            "admissible": False,
            "motifs": ["ADMISSION_NON_EVALUEE"],
            "sources_verifiees": [],
            "empreintes_sources": {},
            "schema": None,
        }
    resume = {cle: admission.get(cle) for cle in _CHAMPS_ADMISSION}
    resume["admissible"] = admission.get("admissible") is True
    return resume


def _contexte_admission(entrees: Mapping[str, Any]) -> dict[str, Any]:
    periode = entrees["periode"]
    return {
        "annee": periode["annee"],
        "date_paie": periode["date_paie"],
        "juridiction": "QC",
        "frequence": "bihebdomadaire",
        "periode_annuelle": periode["periode_annuelle"],
        "pm": 12,
    }


def _extraire_brut(reponse: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if isinstance(reponse, Mapping) and reponse.get("accepte") is True and isinstance(reponse.get("resultat"), Mapping):
        return dict(reponse["resultat"]), None
    verdict = reponse.get("verdict") if isinstance(reponse, Mapping) else None
    code = verdict.get("code") if isinstance(verdict, Mapping) else "inconnu"
    detail = verdict.get("detail", "") if isinstance(verdict, Mapping) else ""
    return None, dossier.refus("SOURCE-REFUSEE", f"brut M4/M5 refusé ({code}) : {detail}")


def _resoudre_cumuls_simules(
    cnx: Connection,
    entrees: dict[str, Any],
    employee_person_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Cumuls hypothétiques de la version COURANTE de la période précédente; jamais ceux de l'appelant."""
    cumuls = entrees["cumuls_avant"]
    if cumuls["origine"] != "SIMULE_VERSION_PRECEDENTE":
        return entrees, None
    source = cumuls["source_simulee"]
    periode = entrees["periode"]
    attendu = journal.identifiant_dossier(
        cnx,
        employee_person_id,
        entrees["employeur_reference"],
        periode["annee"],
        periode["periode_annuelle"] - 1,
        creer=False,
    )
    if periode["periode_annuelle"] == 1 or attendu is None or source["dossier_id"] != attendu:
        raise _lever(
            "CUMUL-INVALIDE", "la source simulée doit être le dossier de la période précédente du même employé"
        )
    precedent = journal.lire_dossier(cnx, attendu)
    if precedent is None:
        raise _lever("CUMUL-INVALIDE", "dossier de la période précédente introuvable")
    courante = precedent["versions"][-1]
    if courante["numero"] != source["numero_version"] or courante["hash_version"] != source["hash_version"]:
        raise _lever(
            "CUMUL-PERIME",
            "la version simulée n'est plus la version courante de la période précédente : rebase explicite requis",
        )
    apres = courante["version"].get("cumuls_apres_hypothetiques")
    if not isinstance(apres, Mapping) or set(apres) != set(dossier.CHAMPS_CUMULS):
        raise _lever(
            "CUMUL-INVALIDE", "la période précédente n'a pas de composition complète : aucun cumul simulé disponible"
        )
    resolu = dict(entrees)
    resolu["cumuls_avant"] = {**cumuls, "valeurs": dict(apres)}
    return resolu, {"dossier_id": attendu, **{k: source[k] for k in ("numero_version", "hash_version")}}


def _construire_version(
    entrees: dict[str, Any],
    identite: dict[str, Any],
    brut: Mapping[str, Any] | None,
    admission: Mapping[str, Any] | None,
    erreur_brut: Mapping[str, Any] | None,
) -> dict[str, Any]:
    calcul = dossier.composer(entrees, brut, admission)
    if erreur_brut is not None:
        calcul["refus"] = dict(erreur_brut)
    brut_cad = brut.get("brut_brouillon") if brut else None
    sources_brut = (brut or {}).get("sources", {})
    version = {
        "schema": dossier.SCHEMA_VERSION,
        "identite": identite,
        "entrees": entrees,
        "sources": {
            "heures_m4": {
                **sources_brut.get("heures_m4", {}),
                "minutes_regulieres": (brut or {}).get("minutes_regulieres"),
                "periode": (brut or {}).get("periode"),
            }
            if brut
            else None,
            "contrat_m5": sources_brut.get("contrat_m5") if brut else None,
            "brut": {
                "brut_brouillon": brut_cad,
                "brut_exact_fraction": brut.get("brut_exact_fraction"),
                "devise": brut.get("devise"),
                "politique_arrondi": entrees["arrondi"]["politique"],
                "hypothese_arrondi": entrees["arrondi"]["hypothese"],
            }
            if brut
            else None,
        },
        "admission": _resume_admission(admission),
        "calcul": calcul,
        "cumuls_apres_hypothetiques": dossier.cumuls_apres(entrees, calcul, brut_cad) if brut_cad else None,
        "parametres": {
            "employeur_hash": dossier.cotisations_employeur_2026.HASH_PARAMETRES,
            "federal_hash": (calcul.get("moteurs") or {}).get("hash_parametres_federal"),
            "empreinte_sortie_moteurs": (calcul.get("moteurs") or {}).get("empreinte_sortie_moteurs"),
        },
        "mentions": {
            "mode": dossier.MODE,
            "qualification_regles": dossier.QUALIFICATION,
            "aucun_versement": True,
            "cumuls_apres": "HYPOTHETIQUES_NON_VERSES_NON_CONFIRMES",
            "validation_humaine_requise": True,
            "actions_officielles_bloquees": True,
        },
    }
    version["empreinte_calcul"] = dossier.empreinte(calcul)
    return version


def _empreinte_apercu(version: Mapping[str, Any]) -> str:
    """Ce que l'humain a vu : références de sources, état, matrice (montants) et totaux; stable d'un appel à l'autre."""
    calcul = version["calcul"]
    return dossier.empreinte(
        {
            "identite": version["identite"],
            "entrees": version["entrees"],
            "sources": version["sources"],
            "admission": version["admission"],
            "etat": calcul["etat"],
            "matrice": calcul["matrice"],
            "totaux": calcul["totaux"],
            "parametres": version["parametres"],
        }
    )


def apercu(
    cnx: Connection,
    *,
    employee_person_id: str,
    entrees_brutes: object,
    fournisseur_brut: FournisseurBrut,
    fournisseur_admission: FournisseurAdmission,
) -> dict[str, Any]:
    """Lecture seule : valide, lit les sources, vérifie l'admission, compose. Ne persiste jamais."""
    entrees, verdict = dossier.valider_entrees(entrees_brutes)
    if verdict is not None or entrees is None:
        raise ServiceErreur(verdict or dossier.refus("STRUCTURE-INVALIDE", "entrées invalides"))
    entrees, simulee = _resoudre_cumuls_simules(cnx, entrees, employee_person_id)
    identite = {
        "employee_person_id": employee_person_id,
        "employeur_reference": entrees["employeur_reference"],
        "annee": entrees["periode"]["annee"],
        "periode_annuelle": entrees["periode"]["periode_annuelle"],
    }
    _, verdict_periode = dossier.valider_periode(entrees["periode"])
    brut, erreur_brut = (None, verdict_periode)
    if verdict_periode is None:
        reponse = fournisseur_brut(employee_person_id, entrees)
        brut, erreur_brut = _extraire_brut(reponse)
    admission = None
    if brut is not None and not dossier.evaluer_couverture(entrees):
        admission = fournisseur_admission(_contexte_admission(entrees))
    version = _construire_version(entrees, identite, brut, admission, erreur_brut if brut is None else None)
    version["simulation_cumuls"] = simulee
    return {
        "version": version,
        "empreinte_apercu": _empreinte_apercu(version),
        "conservable": version["calcul"]["etat"] != "SOURCE_REFUSEE" and brut is not None,
    }


def _recu(statut: str, evt: Mapping[str, Any], dossier_id: str) -> dict[str, Any]:
    """Reçu minimal, sans montant : c'est ce que l'idempotence partagée peut conserver."""
    base = {"statut": statut, "dossier_id": dossier_id, "rang": evt.get("rang"), "type": evt["type"]}
    if evt["type"] == "VERSION":
        base.update(
            numero=evt["numero"],
            hash_version=evt["hash_version"],
            type_version=evt["type_version"],
            etat_calcul=evt["version"]["calcul"]["etat"],
        )
    elif evt["type"] == "REVUE":
        base.update(numero=evt["numero"], hash_version=evt["hash_version"], decision=evt["decision"])
    elif evt["type"] == "EXPORT":
        base.update(
            numero=evt["numero"],
            hash_version=evt["hash_version"],
            format=evt["format"],
            empreinte_export=evt["empreinte_export"],
        )
    else:
        base.update(depuis_numero=evt["depuis_numero"], hash_version=evt["hash_version"])
    return base


def conserver_version(
    cnx: Connection,
    *,
    acteur: str,
    employee_person_id: str,
    entrees_brutes: object,
    empreinte_apercu: str,
    version_attendue: int,
    type_version: str,
    motif: str,
    mutation_id: str,
    maintenant: str,
    fournisseur_brut: FournisseurBrut,
    fournisseur_admission: FournisseurAdmission,
    verifier_acteur: Callable[[Connection, str], None],
) -> dict[str, Any]:
    """Écrit une version immuable. Rejeu exact → même reçu; autre charge → refus; version périmée → refus."""
    if not journal.est_type_version(type_version) or not isinstance(motif, str) or len(motif) > journal.MAX_NOTE:
        raise _lever("STRUCTURE-INVALIDE", "type_version ou motif invalide")
    entrees, verdict = dossier.valider_entrees(entrees_brutes)
    if verdict is not None or entrees is None:
        raise ServiceErreur(verdict or dossier.refus("STRUCTURE-INVALIDE", "entrées invalides"))
    periode = entrees["periode"]
    dossier_id = journal.identifiant_dossier(
        cnx,
        employee_person_id,
        entrees["employeur_reference"],
        periode["annee"],
        periode["periode_annuelle"],
        creer=True,
    )
    assert dossier_id is not None
    requete = dossier.empreinte(
        {
            "action": "VERSION",
            "dossier_id": dossier_id,
            "employee": employee_person_id,
            "entrees": entrees,
            "apercu": empreinte_apercu,
            "type_version": type_version,
            "motif": motif,
            "version_attendue": version_attendue,
        }
    )
    deja = journal.retrouver_mutation(cnx, mutation_id)
    if deja is not None:
        if deja["requete_sha256"] != requete or deja["dossier_id"] != dossier_id or deja["type"] != "VERSION":
            raise _lever("MUTATION-CONFLIT", "identifiant de mutation déjà utilisé avec une autre requête")
        return _recu("REJOUEE", deja, dossier_id)
    courant = journal.lire_dossier(cnx, dossier_id)
    if courant is not None and courant["etat"] == "REVUE_COMPLETEE":
        raise _lever("DOSSIER-REVU", "dossier revu : rouvrez-le explicitement avant de conserver une nouvelle version")
    if type_version == "CREATION":
        for autre in journal.lire_tout(cnx).values():
            ident = autre["versions"][-1]["version"]["identite"]
            if (
                autre["dossier_id"] != dossier_id
                and ident["employee_person_id"] == employee_person_id
                and ident["annee"] == periode["annee"]
                and ident["periode_annuelle"] == periode["periode_annuelle"]
            ):
                raise _lever(
                    "DOSSIER-DOUBLON",
                    "un dossier existe déjà pour cet employé et cette période sous une autre référence d'employeur",
                )
    if (type_version == "CREATION") != (version_attendue == 0):
        raise _lever("STRUCTURE-INVALIDE", "CREATION exige version_attendue=0, CORRECTION/REBASE une version existante")
    resultat = apercu(
        cnx,
        employee_person_id=employee_person_id,
        entrees_brutes=entrees_brutes,
        fournisseur_brut=fournisseur_brut,
        fournisseur_admission=fournisseur_admission,
    )
    if not resultat["conservable"]:
        raise _lever("SOURCE-REFUSEE", "aucune version conservable : source M4/M5 ou période refusée")
    if resultat["empreinte_apercu"] != empreinte_apercu:
        raise _lever("SOURCE-MODIFIEE", "les sources ou le calcul ont changé depuis l'aperçu : refaites l'aperçu")
    version = resultat["version"]
    numero = version_attendue + 1
    version = {**version, "dossier_id": dossier_id, "numero": numero}
    resultat_ecriture = journal.ajouter(
        cnx,
        dossier_id=dossier_id,
        type_evt="VERSION",
        mutation_id=mutation_id,
        acteur=acteur,
        horodatage=maintenant,
        version_attendue=version_attendue,
        requete_sha256=requete,
        verifier_acteur=verifier_acteur,
        contenu={
            "numero": numero,
            "parent": None if numero == 1 else numero - 1,
            "type_version": type_version,
            "motif": motif,
            "hash_version": dossier.empreinte(version),
            "version": version,
        },
    )
    return _recu(resultat_ecriture["statut"], resultat_ecriture["evenement"], dossier_id)


def rouvrir(
    cnx: Connection,
    *,
    acteur: str,
    dossier_id: str,
    numero: int,
    hash_version: str,
    motif: str,
    mutation_id: str,
    maintenant: str,
    verifier_acteur: Callable[[Connection, str], None],
) -> dict[str, Any]:
    courant = journal.lire_dossier(cnx, dossier_id)
    if courant is None or not courant["versions"]:
        raise _lever("INTROUVABLE", "dossier introuvable")
    derniere = courant["versions"][-1]
    if not isinstance(motif, str) or not 1 <= len(motif.strip()) <= journal.MAX_NOTE:
        raise _lever("STRUCTURE-INVALIDE", "motif de réouverture requis")
    requete = dossier.empreinte(
        {
            "action": "REOUVERTURE",
            "dossier_id": dossier_id,
            "numero": numero,
            "hash": hash_version,
            "motif": motif.strip(),
        }
    )
    deja = journal.retrouver_mutation(cnx, mutation_id)
    if deja is not None:
        if deja["requete_sha256"] != requete or deja["dossier_id"] != dossier_id or deja["type"] != "REOUVERTURE":
            raise _lever("MUTATION-CONFLIT", "identifiant de mutation déjà utilisé avec une autre requête")
        return _recu("REJOUEE", deja, dossier_id)
    if derniere["numero"] != numero or derniere["hash_version"] != hash_version:
        raise _lever("VERSION-PERIMEE", "la version à rouvrir n'est pas la version courante")
    if courant["etat"] not in {"REVUE_COMPLETEE", "A_CORRIGER"}:
        raise _lever("ETAT-INVALIDE", "seul un dossier revu ou à corriger peut être rouvert")
    ecriture = journal.ajouter(
        cnx,
        dossier_id=dossier_id,
        type_evt="REOUVERTURE",
        mutation_id=mutation_id,
        acteur=acteur,
        horodatage=maintenant,
        version_attendue=numero,
        requete_sha256=requete,
        verifier_acteur=verifier_acteur,
        contenu={"depuis_numero": numero, "hash_version": hash_version, "motif": motif.strip()},
    )
    return _recu(ecriture["statut"], ecriture["evenement"], dossier_id)


def verifier_version(
    cnx: Connection,
    *,
    dossier_id: str,
    numero: int | None,
    fournisseur_brut: FournisseurBrut,
    fournisseur_admission: FournisseurAdmission,
) -> dict[str, Any]:
    """Compare une version conservée à : (1) elle-même recomposée des entrées figées; (2) les sources actuelles.

    (1) détecte altération ou dérive d'un moteur ; (2) détecte heures M4, contrat M5, admission ou cumul modifiés.
    Aucune écriture. L'ancienne version n'est jamais modifiée : une différence mène à une nouvelle version explicite.
    """
    d = journal.lire_dossier(cnx, dossier_id)
    if d is None:
        raise _lever("INTROUVABLE", "dossier introuvable")
    version = version_numero(d, numero)
    figee = version["version"]
    differences: list[dict[str, str]] = []
    brut_fige = figee["sources"]["brut"]
    recompose = dossier.composer(
        figee["entrees"],
        {"brut_brouillon": brut_fige["brut_brouillon"]} if brut_fige else None,
        figee["admission"],
    )
    reproductible = dossier.empreinte(recompose) == figee["empreinte_calcul"]
    if not reproductible:
        differences.append(
            {
                "code": "CALCUL-NON-REPRODUCTIBLE",
                "detail": "les entrées figées ne redonnent plus le résultat conservé (moteur ou donnée modifié)",
            }
        )
    identite = figee["identite"]
    actuel = apercu_sources(cnx, figee, fournisseur_brut, fournisseur_admission)
    differences += actuel["differences"]
    return {
        "dossier_id": dossier_id,
        "numero": version["numero"],
        "hash_version": version["hash_version"],
        "reproductible": reproductible,
        "sources_inchangees": not actuel["differences"],
        "est_version_courante": d["versions"][-1]["numero"] == version["numero"],
        "differences": differences,
        "employee_person_id": identite["employee_person_id"],
    }


def apercu_sources(
    cnx: Connection,
    figee: Mapping[str, Any],
    fournisseur_brut: FournisseurBrut,
    fournisseur_admission: FournisseurAdmission,
) -> dict[str, Any]:
    differences: list[dict[str, str]] = []
    identite = figee["identite"]
    reponse = fournisseur_brut(identite["employee_person_id"], figee["entrees"])
    brut, erreur = _extraire_brut(reponse)
    if brut is None:
        differences.append({"code": "SOURCE-INDISPONIBLE", "detail": (erreur or {}).get("detail", "brut indisponible")})
    else:
        for cle in ("heures_m4", "contrat_m5"):
            avant = {
                k: v
                for k, v in (figee["sources"][cle] or {}).items()
                if k in {"ligne_id", "revision", "empreinte_sources", "contrat_id"}
            }
            apres = {
                k: v
                for k, v in brut["sources"][cle].items()
                if k in {"ligne_id", "revision", "empreinte_sources", "contrat_id"}
            }
            if avant != apres:
                differences.append(
                    {"code": f"SOURCE-{cle.upper()}-MODIFIEE", "detail": f"{cle} a changé depuis la version conservée"}
                )
        if brut["brut_brouillon"] != figee["sources"]["brut"]["brut_brouillon"]:
            differences.append(
                {"code": "BRUT-MODIFIE", "detail": "le brut régulier recalculé diffère de la version conservée"}
            )
    if figee["admission"].get("admissible"):
        adm = _resume_admission(fournisseur_admission(_contexte_admission(figee["entrees"])))
        if adm["empreintes_sources"] != figee["admission"]["empreintes_sources"] or adm["admissible"] is not True:
            differences.append(
                {
                    "code": "ADMISSION-MODIFIEE",
                    "detail": "l'admission documentaire courante diffère de celle de la version",
                }
            )
    source = figee["entrees"]["cumuls_avant"]["source_simulee"]
    if source is not None:
        precedent = journal.lire_dossier(cnx, source["dossier_id"])
        courante = precedent["versions"][-1] if precedent and precedent["versions"] else None
        if courante is None or courante["hash_version"] != source["hash_version"]:
            differences.append(
                {
                    "code": "CUMUL-SIMULE-PERIME",
                    "detail": "la période précédente a une nouvelle version : le cumul simulé est périmé",
                }
            )
    return {"differences": differences}


def version_numero(d: Mapping[str, Any], numero: int | None) -> Mapping[str, Any]:
    if numero is None:
        return d["versions"][-1]
    if type(numero) is not int or not 1 <= numero <= len(d["versions"]):
        raise _lever("INTROUVABLE", "version introuvable")
    return d["versions"][numero - 1]


def revue(
    cnx: Connection,
    *,
    acteur: str,
    dossier_id: str,
    numero: int,
    hash_version: str,
    decision: str,
    note: str,
    mutation_id: str,
    maintenant: str,
    fournisseur_brut: FournisseurBrut,
    fournisseur_admission: FournisseurAdmission,
    verifier_acteur: Callable[[Connection, str], None],
) -> dict[str, Any]:
    """Revue interne du propriétaire liée à la version ET au hash exacts. Ce n'est pas une validation fiscale."""
    if not journal.est_decision_revue(decision) or not isinstance(note, str) or len(note) > journal.MAX_NOTE:
        raise _lever("REVUE-INVALIDE", "décision ou note invalide")
    d = journal.lire_dossier(cnx, dossier_id)
    if d is None or not d["versions"]:
        raise _lever("INTROUVABLE", "dossier introuvable")
    requete = dossier.empreinte(
        {
            "action": "REVUE",
            "dossier_id": dossier_id,
            "numero": numero,
            "hash": hash_version,
            "decision": decision,
            "note": note.strip(),
        }
    )
    deja = journal.retrouver_mutation(cnx, mutation_id)
    if deja is not None:
        if deja["requete_sha256"] != requete or deja["dossier_id"] != dossier_id or deja["type"] != "REVUE":
            raise _lever("MUTATION-CONFLIT", "identifiant de mutation déjà utilisé avec une autre requête")
        return _recu("REJOUEE", deja, dossier_id)
    derniere = d["versions"][-1]
    if derniere["numero"] != numero or derniere["hash_version"] != hash_version:
        raise _lever("VERSION-PERIMEE", "la revue doit porter sur la version courante et son hash exact")
    if d["etat"] == "REVUE_COMPLETEE":
        raise _lever("ETAT-INVALIDE", "version déjà revue : rouvrez le dossier pour la corriger")
    if decision == "REVUE_COMPLETEE":
        if derniere["version"]["calcul"]["etat"] != "COMPOSE_PREPARATOIRE":
            raise _lever("REVUE-INVALIDE", "seule une composition complète peut être revue comme complète")
        controle = verifier_version(
            cnx,
            dossier_id=dossier_id,
            numero=numero,
            fournisseur_brut=fournisseur_brut,
            fournisseur_admission=fournisseur_admission,
        )
        if controle["differences"]:
            raise _lever(
                "SOURCE-MODIFIEE",
                "sources ou calcul modifiés depuis la version : conservez une nouvelle version avant la revue",
            )
    ecriture = journal.ajouter(
        cnx,
        dossier_id=dossier_id,
        type_evt="REVUE",
        mutation_id=mutation_id,
        acteur=acteur,
        horodatage=maintenant,
        version_attendue=numero,
        requete_sha256=requete,
        verifier_acteur=verifier_acteur,
        contenu={"numero": numero, "hash_version": hash_version, "decision": decision, "note": note.strip()},
    )
    return _recu(ecriture["statut"], ecriture["evenement"], dossier_id)


def _aplatir(valeur: Any, prefixe: str = "") -> dict[str, Any]:
    if isinstance(valeur, Mapping):
        sortie: dict[str, Any] = {}
        for cle in sorted(valeur):
            sortie.update(_aplatir(valeur[cle], f"{prefixe}.{cle}" if prefixe else str(cle)))
        return sortie
    if isinstance(valeur, list) and all(isinstance(v, Mapping) and "id" in v for v in valeur):
        sortie = {}
        for v in valeur:
            sortie.update(_aplatir(v, f"{prefixe}[{v['id']}]"))
        return sortie
    return {prefixe: valeur}


def comparer(d: Mapping[str, Any], de: int, vers: int) -> dict[str, Any]:
    """Différences lisibles et déterministes entre deux versions conservées d'un même dossier."""
    a, b = version_numero(d, de), version_numero(d, vers)

    def vue(version: Mapping[str, Any]) -> dict[str, Any]:
        figee = version["version"]
        calcul = figee["calcul"]
        return {
            "entrees": _aplatir(figee["entrees"]),
            "sources": _aplatir(figee["sources"]),
            "admission": _aplatir(figee["admission"]),
            "postes": {p["id"]: {"etat": p["etat"], "montant": p["montant"]} for p in calcul["matrice"]},
            "totaux": {k: {"etat": t["etat"], "montant": t["montant"]} for k, t in calcul["totaux"].items()},
            "etat_calcul": calcul["etat"],
        }

    va, vb = vue(a), vue(b)

    def diff(x: Mapping[str, Any], y: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [
            {"champ": cle, "avant": x.get(cle), "apres": y.get(cle)}
            for cle in sorted(set(x) | set(y))
            if x.get(cle) != y.get(cle)
        ]

    return {
        "de": a["numero"],
        "vers": b["numero"],
        "hash_de": a["hash_version"],
        "hash_vers": b["hash_version"],
        "etat_calcul": {"avant": va["etat_calcul"], "apres": vb["etat_calcul"]},
        "entrees": diff(va["entrees"], vb["entrees"]),
        "sources": diff(va["sources"], vb["sources"]),
        "admission": diff(va["admission"], vb["admission"]),
        "postes": diff(va["postes"], vb["postes"]),
        "totaux": diff(va["totaux"], vb["totaux"]),
        "identique": a["hash_version"] == b["hash_version"],
    }


def resume_dossier(d: Mapping[str, Any]) -> dict[str, Any]:
    derniere = d["versions"][-1]
    figee = derniere["version"]
    totaux = figee["calcul"]["totaux"]
    return {
        "dossier_id": d["dossier_id"],
        "etat": d["etat"],
        "employee_person_id": figee["identite"]["employee_person_id"],
        "employeur_reference": figee["identite"]["employeur_reference"],
        "annee": figee["identite"]["annee"],
        "periode_annuelle": figee["identite"]["periode_annuelle"],
        "date_paie": figee["entrees"]["periode"]["date_paie"],
        "numero_courant": derniere["numero"],
        "hash_version": derniere["hash_version"],
        "etat_calcul": figee["calcul"]["etat"],
        "nombre_versions": len(d["versions"]),
        "net_preparatoire": totaux["net_preparatoire"]["montant"],
        "fictif": figee["entrees"]["fictif"],
    }


def exporter(
    cnx: Connection,
    *,
    acteur: str,
    dossier_id: str,
    numero: int,
    hash_version: str,
    format_export: str,
    mutation_id: str,
    maintenant: str,
    liens_officiels: tuple[Mapping[str, Any], ...],
    fournisseur_brut: FournisseurBrut,
    fournisseur_admission: FournisseurAdmission,
    verifier_acteur: Callable[[Connection, str], None],
) -> dict[str, Any]:
    """Audite l'export d'une version REVUE, courante, aux sources inchangées. Rend un reçu, jamais le contenu."""
    from . import export_paie_preparatoire as export

    if not export.est_format(format_export):
        raise _lever("EXPORT-REFUSE", "format d'export inconnu")
    d = journal.lire_dossier(cnx, dossier_id)
    if d is None or not d["versions"]:
        raise _lever("INTROUVABLE", "dossier introuvable")
    requete = dossier.empreinte(
        {
            "action": "EXPORT",
            "dossier_id": dossier_id,
            "numero": numero,
            "hash": hash_version,
            "format": format_export,
        }
    )
    deja = journal.retrouver_mutation(cnx, mutation_id)
    if deja is not None:
        if deja["requete_sha256"] != requete or deja["dossier_id"] != dossier_id or deja["type"] != "EXPORT":
            raise _lever("MUTATION-CONFLIT", "identifiant de mutation déjà utilisé avec une autre requête")
        return _recu("REJOUEE", deja, dossier_id)
    derniere = d["versions"][-1]
    if derniere["numero"] != numero or derniere["hash_version"] != hash_version:
        raise _lever("VERSION-PERIMEE", "l'export doit porter sur la version courante et son hash exact")
    if d["etat"] != "REVUE_COMPLETEE":
        raise _lever("EXPORT-REFUSE", "export refusé : la version courante n'a pas de revue complétée")
    controle = verifier_version(
        cnx,
        dossier_id=dossier_id,
        numero=numero,
        fournisseur_brut=fournisseur_brut,
        fournisseur_admission=fournisseur_admission,
    )
    if controle["differences"]:
        raise _lever("SOURCE-MODIFIEE", "sources ou calcul modifiés depuis la version : export refusé")
    _, empreinte_export = export.produire(d, numero, format_export, liens_officiels)
    ecriture = journal.ajouter(
        cnx,
        dossier_id=dossier_id,
        type_evt="EXPORT",
        mutation_id=mutation_id,
        acteur=acteur,
        horodatage=maintenant,
        version_attendue=numero,
        requete_sha256=requete,
        verifier_acteur=verifier_acteur,
        contenu={
            "numero": numero,
            "hash_version": hash_version,
            "format": format_export,
            "empreinte_export": empreinte_export,
        },
    )
    return _recu(ecriture["statut"], ecriture["evenement"], dossier_id)


def lire_export(
    cnx: Connection,
    *,
    dossier_id: str,
    numero: int,
    hash_version: str,
    format_export: str,
    liens_officiels: tuple[Mapping[str, Any], ...],
) -> tuple[bytes, str]:
    """Reconstruit l'export reproductible; refuse s'il ne correspond pas à un export audité de la version courante."""
    from . import export_paie_preparatoire as export

    d = journal.lire_dossier(cnx, dossier_id)
    if d is None or not d["versions"]:
        raise _lever("INTROUVABLE", "dossier introuvable")
    derniere = d["versions"][-1]
    if derniere["numero"] != numero or derniere["hash_version"] != hash_version or d["etat"] != "REVUE_COMPLETEE":
        raise _lever("EXPORT-REFUSE", "seule la version courante revue peut être exportée")
    octets, empreinte_export = export.produire(d, numero, format_export, liens_officiels)
    if not any(
        e["numero"] == numero and e["format"] == format_export and e["empreinte_export"] == empreinte_export
        for e in d["exports"]
    ):
        raise _lever("EXPORT-REFUSE", "aucun export audité ne correspond à ce contenu : demandez d'abord l'export")
    return octets, empreinte_export


def lister(cnx: Connection) -> list[dict[str, Any]]:
    """Résumés des dossiers (sans détail de postes), du plus récent au plus ancien par date de paie puis employé."""
    resumes = [resume_dossier(d) for d in journal.lire_tout(cnx).values() if d["versions"]]
    return sorted(resumes, key=lambda r: (r["date_paie"], r["employee_person_id"]), reverse=True)
