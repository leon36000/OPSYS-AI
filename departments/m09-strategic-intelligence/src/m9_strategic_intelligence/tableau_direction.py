"""Tableau de direction d'Athéna : santé, pipeline, prévisions, trésorerie, échéances, capacité, risques de chantier et
alertes M8, tels que les producteurs les ont rapportés — chaque ligne avec sa source, son âge et son STATUT DE
CERTITUDE.

Module pur et déterministe : aucune horloge (``maintenant`` est fourni), aucun import d'``opsys``, aucun calcul
d'affaires.
M9 ne fait que CITER ce que les captures (M9.1) contiennent, les classer (``certitude``) et dire ce qui manque :

* une valeur n'apparaît que si le fait existe dans une capture acceptée et complète ; sinon la ligne dit
  « indéterminé », « non lue » ou « refusé par le producteur », avec la raison — jamais un zéro, jamais une estimation ;
* un fait ``ESSAI_NON_APPROUVE``, ``PERIME``, ``INDETERMINE`` ou une prévision porte son statut dans la ligne et
  ``certain: false`` : un lecteur pressé ne peut pas le prendre pour un fait établi ;
* chaque valeur chiffrée porte l'adresse du fait (``<lecture>#<rang>:p<page>.<chemin>``) : elle se vérifie dans la
  capture, mot pour mot ;
* une prévision est TOUJOURS rendue avec son intervalle ; sans intervalle, elle n'est pas rendue.

La santé de l'entreprise est « indéterminée : bornes à fixer par la direction » tant que les bornes du score ne sont
pas déclarées ; M9 n'invente jamais de bornes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from . import capture_strategique as cs
from . import certitude as ct
from . import dossier_strategique, previsions
from . import risques as rk

VERSION = "2026-11-01.1"
SECTIONS = (
    "sante", "pipeline", "previsions", "tresorerie", "echeances", "sources_fiscales", "capacite", "chantiers",
    "alertes_m8",
)  # fmt: skip
TITRES = {
    "sante": "Santé de l'entreprise",
    "pipeline": "Pipeline des ventes",
    "previsions": "Prévision des leads (M2)",
    "tresorerie": "Trésorerie (M5)",
    "echeances": "Échéances (M5)",
    "sources_fiscales": "Sources fiscales (revue)",
    "capacite": "Capacité des équipes (M4)",
    "chantiers": "Risques de chantier",
    "alertes_m8": "Alertes de mesure (M8)",
}
LECTURES = {
    "sante": ("m8.synthese_direction",),
    "pipeline": ("m2.analyse_pipeline",),
    "previsions": ("m2.prevision_pipeline",),
    "tresorerie": ("m5.prevision_tresorerie",),
    "echeances": ("m5.calendrier_obligations",),
    "sources_fiscales": ("m5.statut_revue_fiscale",),
    "capacite": ("m4.capacite_equipe",),
    "chantiers": ("m4.retards_incidents", "m6.disponibilite", "m5.comptes_a_payer", "m8.mesures_chantier"),
    "alertes_m8": (),
}
PHRASE_SANTE_INDETERMINEE = "indéterminée : bornes à fixer par la direction"
MAX_PERIODES = 8
MAX_RISQUES = 5
_LIMITES = (
    "Faits reçus des producteurs, cités tels quels : ni vérité, ni fraîcheur garanties au-delà de ce que chaque "
    "réponse déclare.",
    "Seul le statut ETABLI se présente comme certain ; ESSAI_NON_APPROUVE, PERIME, INDETERMINE et les prévisions ne "
    "le sont jamais.",
    "Indicateurs préparatoires : À valider auprès d'un comptable (CPA) / professionnel qualifié.",
)


# ----------------------------------------------------------------------------------------------------- aides
class _Lecture:
    """Une lecture dans son état connu : capture, faits citables (adresse → texte), classes de certitude."""

    def __init__(self, connues: Sequence[Mapping], lecture_id: str) -> None:
        self.lecture_id = lecture_id
        self.etat = ct.etat_lecture(connues, lecture_id)
        self.capture = self.etat["capture"]
        self.certitude_lecture = self.etat["certitude"]
        self._faits: dict[str, str] | None = None
        self._classes: dict[str, str] | None = None

    @property
    def faits(self) -> dict[str, str]:
        if self._faits is None:
            self._faits = {}
            if self.utilisable:
                self._faits, _ = dossier_strategique.faits_citables([self.capture], max_faits=10**6)
        return self._faits

    @property
    def classes(self) -> dict[str, str]:
        if self._classes is None:
            self._classes = ct.classer_faits(self.capture) if self.utilisable else {}
        return self._classes

    @property
    def utilisable(self) -> bool:
        return self.certitude_lecture == ct.ETABLI

    def page(self, numero: int = 0) -> Mapping:
        return self.capture["pages"][numero]

    def adresse(self, chemin: str, numero_page: int = 0) -> str:
        return f"{self.lecture_id}#{self.capture['index']}:p{numero_page}.{chemin}"

    def fait(self, chemin: str) -> tuple[str | None, str | None, str]:
        """``(texte, adresse, statut)`` du fait à ``chemin`` ; ``(None, None, ABSENT)`` s'il n'existe pas (nul, non
        citable, ou lecture inutilisable) : une absence n'est jamais une valeur."""
        if not self.utilisable:
            return None, None, self.certitude_lecture
        adresse = self.adresse(chemin)
        if adresse not in self.faits:
            return None, None, ct.ABSENT
        return self.faits[adresse], adresse, ct.statut_du_fait(self.classes, chemin)

    def source(self) -> dict | None:
        if self.capture is None:
            return None
        return {
            "lecture_id": self.lecture_id,
            "capture": self.capture["index"],
            "hash_maillon": self.capture["hash_maillon"],
            "recu_a": self.capture["recu_a"],
        }


def _age_s(maintenant: str, recu_a: str) -> int | None:
    a, b = cs.instant(maintenant), cs.instant(recu_a)
    return None if a is None or b is None else int((a - b).total_seconds())


def _ligne(
    libelle: str, valeur: str | None, statut: str, *, adresse: str | None = None, unite: str | None = None,
    note: str | None = None, **supplement: object,
) -> dict:  # fmt: skip
    ligne: dict = {
        "libelle": libelle,
        "valeur": valeur,
        "unite": unite,
        "certitude": statut,
        "certain": ct.est_certain(statut),
        "adresse": adresse,
    }
    if note:
        ligne["note"] = note
    ligne.update(supplement)
    return ligne


def _non_lue(lecture: _Lecture, titre: str) -> dict:
    """Section dont la lecture n'est pas utilisable : on dit pourquoi, on ne remplit rien."""
    etat = lecture.certitude_lecture
    precisions = {
        ct.ABSENT: "aucune capture connue : lancer la capture de cette lecture",
        ct.REFUSE: f"lecture refusée par le producteur (code {lecture.etat['code']})",
        ct.PARTIEL: "capture incomplète : aucun fait citable",
        ct.CONTRADICTOIRE: "deux réponses se contredisent : aucune n'est choisie",
    }
    return {
        "certitude": etat,
        "certain": False,
        "message": f"{titre} : non lue ({precisions.get(etat, etat)}).",
        "lignes": [],
        "manques": [precisions.get(etat, etat)],
    }


def _section(
    id_: str, certitude: str, message: str, lignes: list[dict], manques: Sequence[str], lectures: Sequence[_Lecture],
    **supplement: object,
) -> dict:  # fmt: skip
    return {
        "id": id_,
        "titre": TITRES[id_],
        "certitude": certitude,
        "certain": ct.est_certain(certitude),
        "message": message,
        "lignes": lignes,
        "manques": list(manques),
        "sources": [s for s in (lec.source() for lec in lectures) if s is not None],
        **supplement,
    }


# ----------------------------------------------------------------------------------------------------- santé
def _sante(lecture: _Lecture) -> dict:
    titre = TITRES["sante"]
    if not lecture.utilisable:
        base = _non_lue(lecture, titre)
        return _section("sante", base["certitude"], base["message"], [], base["manques"], [lecture])
    statut, a_statut, _ = lecture.fait("resultat.sante.statut")
    valide, a_valide, _ = lecture.fait("resultat.sante.ponderations.validee")
    manques = lecture.page()["resultat"]["sante"]["manques"]
    raisons = sorted({m["raison"] for m in manques})
    bornes = sorted({m["metric_id"] for m in manques if m["raison"] in ("bornes_a_configurer", "bornes_invalides")})
    a_rafraichir = sorted(
        {m["metric_id"] for m in manques if m["raison"] in ("mesure_manquante", "mesure_perimee", "fraicheur_inconnue")}
    )
    composantes = []
    for rang, composante in enumerate(lecture.page()["resultat"]["sante"]["composantes"]):
        score, adresse, classe = lecture.fait(f"resultat.sante.composantes[{rang}].score")
        composantes.append(
            _ligne(
                composante["libelle"],
                score,
                classe if score is not None else ct.INDETERMINE,
                adresse=adresse,
                unite="/100",
                note=None if score is not None else "composante indéterminée",
                composante=composante["id"],
                poids=composante["poids"],
            )
        )
    a_faire = []
    if bornes:
        a_faire.append(f"Bornes (pire/cible) à fixer par la direction pour : {', '.join(bornes)}.")
    if a_rafraichir:
        a_faire.append(f"Mesures manquantes ou périmées à rafraîchir : {', '.join(a_rafraichir)}.")
    if statut == "indetermine":
        message = f"{titre} : {PHRASE_SANTE_INDETERMINEE}." if bornes else f"{titre} : indéterminée."
        if a_rafraichir:
            message += " Des mesures sont manquantes ou périmées."
        return _section(
            "sante", ct.INDETERMINE, message, composantes, a_faire or ["aucun détail du producteur"], [lecture],
            raisons=raisons, a_faire_par_la_direction=a_faire, mention=ct.MENTION_CPA,
        )  # fmt: skip
    score, a_score, classe = lecture.fait("resultat.sante.score")
    if score is None:
        return _section(
            "sante", ct.INDETERMINE, f"{titre} : le producteur ne donne aucun score.", composantes,
            ["score absent"], [lecture], mention=ct.MENTION_CPA,
        )  # fmt: skip
    if valide != "true":
        message = (
            f"{titre} : ESSAI — score {score}/100 selon des pondérations PROPOSÉES, non validées par la direction ; "
            "ne pas le présenter comme établi."
        )
        a_faire.append("Pondérations du score à valider par la direction.")
    else:
        message = f"{titre} : {score}/100 (pondérations validées par la direction)."
    ligne = _ligne("Score de santé", score, classe, adresse=a_score, unite="/100")
    return _section(
        "sante", classe, message, [ligne, *composantes], a_faire, [lecture],
        ponderations_validees=valide == "true", adresse_ponderations=a_valide, a_faire_par_la_direction=a_faire,
        mention=ct.MENTION_CPA,
    )  # fmt: skip


# ----------------------------------------------------------------------------------------------------- pipeline
def _taux(lecture: _Lecture, libelle: str, chemin: str) -> dict:
    valeur, adresse, classe = lecture.fait(f"{chemin}.valeur")
    n, a_n, _ = lecture.fait(f"{chemin}.n")
    seuil, _, _ = lecture.fait(f"{chemin}.seuil")
    if valeur is None:
        return _ligne(
            libelle, None, ct.INDETERMINE, unite="ratio",
            note=(
                f"indéterminé : échantillon insuffisant ({n} observé(s) sur {seuil} exigé(s)) ; "
                "le producteur n'estime rien"
            ),
            adresse_effectif=a_n,
        )  # fmt: skip
    return _ligne(libelle, valeur, classe, adresse=adresse, unite="ratio", note=f"{n} observé(s), seuil {seuil}")


def _pipeline(lecture: _Lecture) -> dict:
    if not lecture.utilisable:
        base = _non_lue(lecture, TITRES["pipeline"])
        return _section("pipeline", base["certitude"], base["message"], [], base["manques"], [lecture])
    lignes = []
    for libelle, chemin in (
        ("Leads ingérés", "resultat.resultat.entonnoir.ingeres"),
        ("Leads ouverts", "resultat.resultat.pipeline.ouverts"),
        ("Leads convertis un jour", "resultat.resultat.entonnoir.convertis_un_jour"),
        ("Leads perdus", "resultat.resultat.entonnoir.perdus"),
    ):
        valeur, adresse, classe = lecture.fait(chemin)
        lignes.append(_ligne(libelle, valeur, classe, adresse=adresse, unite="leads"))
    lignes.append(
        _taux(lecture, "Taux de conversion des leads résolus", "resultat.resultat.taux_conversion_des_resolus")
    )
    lignes.append(_taux(lecture, "Taux de qualification", "resultat.resultat.taux_qualification"))
    racine = "resultat.resultat.valeur_ponderee.valeur_ponderee"
    centre, a_centre, classe = lecture.fait(f"{racine}.centre")
    niveau, _, _ = lecture.fait(f"{racine}.intervalle.niveau")
    bas, a_bas, _ = lecture.fait(f"{racine}.intervalle.bas")
    haut, a_haut, _ = lecture.fait(f"{racine}.intervalle.haut")
    if centre is None or bas is None or haut is None or niveau is None:
        lignes.append(
            _ligne(
                "Valeur pondérée du pipeline", None, ct.INDETERMINE, unite="CAD",
                note="indéterminée : le producteur ne la calcule pas (valeur déclarée ou probabilité de conversion "
                     "indisponible)",
            )
        )  # fmt: skip
    else:
        lignes.append(
            _ligne(
                "Valeur pondérée du pipeline", centre, ct.PREVISION, adresse=a_centre, unite="CAD",
                intervalle={"niveau": niveau, "bas": bas, "haut": haut, "adresses": [a_bas, a_haut]},
                note=f"prévision : intervalle à {niveau} % de {bas} à {haut} CAD ; le centre n'est pas une promesse",
            )
        )  # fmt: skip
    recu, a_recu, _ = lecture.fait("resultat.resultat.empreinte_recu")
    pire = ct.plus_grave([ligne["certitude"] for ligne in lignes])
    return _section(
        "pipeline", pire,
        f"{TITRES['pipeline']} : comptes établis ; chaque taux ou valeur sous son seuil d'échantillon "
        "reste indéterminé.",
        lignes, [ligne["note"] for ligne in lignes if ligne["certitude"] == ct.INDETERMINE], [lecture],
        recu={"empreinte": recu, "adresse": a_recu, "verification": "m2_rejouer_recu_commercial"},
    )  # fmt: skip


# ----------------------------------------------------------------------------------------------------- prévisions
def _previsions(lecture: _Lecture) -> dict:
    titre = TITRES["previsions"]
    if lecture.certitude_lecture == ct.REFUSE:
        code = lecture.etat["code"]
        return _section(
            "previsions", ct.INDETERMINE,
            f"{titre} : aucune prévision produite par M2 ({code}). Rien n'est estimé à sa place.",
            [], [f"prévision refusée par le producteur : {code}"], [lecture], code_refus=code,
        )  # fmt: skip
    if not lecture.utilisable:
        base = _non_lue(lecture, titre)
        return _section("previsions", base["certitude"], base["message"], [], base["manques"], [lecture])
    racine = "resultat.resultat.prevision_totale"
    centre, a_centre, _ = lecture.fait(f"{racine}.centre")
    niveau, _, _ = lecture.fait(f"{racine}.intervalle.niveau")
    bas, a_bas, _ = lecture.fait(f"{racine}.intervalle.bas")
    haut, a_haut, _ = lecture.fait(f"{racine}.intervalle.haut")
    horizon, _, _ = lecture.fait(f"{racine}.horizon_periodes")
    serie, _, _ = lecture.fait("resultat.resultat.serie.nom")
    if None in (centre, niveau, bas, haut):
        return _section(
            "previsions", ct.INDETERMINE, f"{titre} : réponse sans intervalle, non rendue (un point seul est refusé).",
            [], ["intervalle absent"], [lecture],
        )  # fmt: skip
    lignes = [
        _ligne(
            f"Total sur {horizon} semaine(s)", centre, ct.PREVISION, adresse=a_centre, unite=serie,
            intervalle={"niveau": niveau, "bas": bas, "haut": haut, "adresses": [a_bas, a_haut]},
            note=f"intervalle à {niveau} % de {bas} à {haut}",
        )
    ]  # fmt: skip
    for rang in range(min(int(horizon or 0), MAX_PERIODES)):
        c, a_c, _ = lecture.fait(f"resultat.resultat.par_periode[{rang}].centre")
        b, a_b, _ = lecture.fait(f"resultat.resultat.par_periode[{rang}].intervalle.bas")
        h, a_h, _ = lecture.fait(f"resultat.resultat.par_periode[{rang}].intervalle.haut")
        if None in (c, b, h):
            continue
        lignes.append(
            _ligne(
                f"Semaine {rang + 1}", c, ct.PREVISION, adresse=a_c, unite=serie,
                intervalle={"niveau": niveau, "bas": b, "haut": h, "adresses": [a_b, a_h]},
            )
        )  # fmt: skip
    recu, a_recu, _ = lecture.fait("resultat.resultat.empreinte_recu")
    return _section(
        "previsions", ct.PREVISION,
        f"{titre} : prévision par intervalle, jamais une certitude.", lignes, [], [lecture],
        recu={"empreinte": recu, "adresse": a_recu, "verification": "m2_rejouer_recu_commercial"},
    )  # fmt: skip


# ----------------------------------------------------------------------------------------------------- trésorerie
def _tresorerie(captures_connues: Sequence[Mapping], maintenant: str, perime_apres_jours: int | None) -> dict:
    titre = TITRES["tresorerie"]
    consolide = previsions.consolider(captures_connues, connaissance=maintenant, perime_apres_jours=perime_apres_jours)
    domaine = next(d for d in consolide["domaines"] if d["domaine"] == "tresorerie")
    statut = domaine["statut"]
    if statut in ("ABSENTE", "AUCUNE_VERSION_UTILISABLE"):
        etat = ct.ABSENT if statut == "ABSENTE" else ct.PARTIEL
        return {
            "id": "tresorerie", "titre": titre, "certitude": etat, "certain": False,
            "message": f"{titre} : {domaine['raison']}.", "lignes": [], "manques": [domaine["raison"]], "sources": [],
        }  # fmt: skip
    version = next(v for v in domaine["versions"] if v["capture"] == domaine["courante"])
    valeurs, faits = version["valeurs"], version["faits"]
    source = {"lecture_id": "m5.prevision_tresorerie", "capture": version["capture"],
              "hash_maillon": version["hash_capture"], "recu_a": version["recu_a"]}  # fmt: skip
    calculable = valeurs.get("calculable")
    lignes = []
    if calculable != "true":
        return {
            "id": "tresorerie", "titre": titre, "certitude": ct.INDETERMINE, "certain": False,
            "message": f"{titre} : prévision non calculable par M5 ; aucun solde futur n'est estimé.",
            "lignes": [], "manques": [str(m) for m in version["manque"]][:10], "sources": [source],
            "non_calculable_a_partir_de": valeurs.get("non_calculable_a_partir_de"),
        }  # fmt: skip
    for libelle, chemin, unite in (
        ("Solde initial", "solde_initial.montant", "CAD"),
        ("Alerte de trésorerie", "alerte.statut", None),
        ("Première semaine en déficit", "premiere_semaine_en_deficit", None),
        ("Horizon (semaines)", "horizon_semaines", "semaines"),
    ):
        texte = valeurs.get(chemin) if chemin != "solde_initial.montant" else version["solde_initial"]
        if texte is None:
            lignes.append(_ligne(libelle, None, ct.INDETERMINE, note="non fourni par M5"))
            continue
        classe = ct.ETABLI if chemin in ("solde_initial.montant", "horizon_semaines") else ct.PREVISION
        lignes.append(_ligne(libelle, texte, classe, adresse=faits.get(chemin), unite=unite))
    certitude = ct.PERIME if statut == "PERIMEE" else ct.PREVISION
    message = (
        f"{titre} : prévision de M5, sans intervalle chiffré (l'incertitude est décrite par ses réserves) ; "
        f"âgée de {version['age_jours']} jour(s) à la date de référence."
    )
    return {
        "id": "tresorerie", "titre": titre, "certitude": certitude, "certain": False, "message": message,
        "lignes": lignes, "manques": [str(m) for m in version["manque"]][:10], "sources": [source],
        "reserves": list(version["reserves"])[:6], "age_jours": version["age_jours"], "mention": ct.MENTION_CPA,
    }  # fmt: skip


# ----------------------------------------------------------------------------------------------------- échéances
_LIBELLE_STATUT_OBLIGATION = {
    "DOCUMENTEE_A_VALIDER": "documentée, à valider par le CPA",
    "ECHEANCE_PASSEE_A_VERIFIER": "échéance passée : à vérifier (aucun paiement n'est inféré)",
    "INCOMPLETE": "incomplète : déclarations manquantes",
    "SOURCE_PERIMEE": "source périmée",
}


def _echeances(lecture: _Lecture) -> dict:
    titre = TITRES["echeances"]
    if not lecture.utilisable:
        base = _non_lue(lecture, titre)
        return _section("echeances", base["certitude"], base["message"], [], base["manques"], [lecture])
    charge = lecture.page()["resultat"]["resultat"]
    lignes = []
    for rang, obligation in enumerate(charge["obligations"]):
        echeance, a_ech, c_ech = lecture.fait(f"resultat.resultat.obligations[{rang}].echeance")
        montant, a_mont, c_mont = lecture.fait(f"resultat.resultat.obligations[{rang}].montant_utilisable")
        statut = obligation["statut"]
        lignes.append(
            _ligne(
                obligation["nom"], montant, c_mont if montant is not None else ct.INDETERMINE, adresse=a_mont,
                    unite="CAD",
                note=_LIBELLE_STATUT_OBLIGATION.get(statut, statut), obligation=obligation["id"], echeance=echeance,
                adresse_echeance=a_ech, certitude_echeance=c_ech if echeance is not None else ct.INDETERMINE,
            )
        )  # fmt: skip
    taxes = charge["echeances_tps_tvq"]
    if taxes.get("statut") == "DOCUMENTE_A_VALIDER":
        for rang, echeance in enumerate((taxes.get("echeances") or [])[:4]):
            paiement, a_pai, c_pai = lecture.fait(
                f"resultat.resultat.echeances_tps_tvq.echeances[{rang}].limite_paiement"
            )
            net, a_net, c_net = lecture.fait(
                f"resultat.resultat.echeances_tps_tvq.echeances[{rang}].taxes_nettes.a_remettre"
            )
            couverture, _, _ = lecture.fait(
                f"resultat.resultat.echeances_tps_tvq.echeances[{rang}].taxes_nettes.couverture.statut"
            )
            note = "taxes nettes non calculées par M5 (couverture absente : un zéro n'est pas confirmé)"
            if net is not None:
                note = f"montant provisoire, couverture {str(couverture).lower()} : non confirmé, à valider par le CPA"
            lignes.append(
                _ligne(
                    f"TPS/TVQ période {echeance['periode_debut']} → {echeance['periode_fin']}", net,
                    c_net if net is not None else ct.INDETERMINE, adresse=a_net, unite="CAD", note=note,
                    obligation="tps_tvq", echeance=paiement, adresse_echeance=a_pai,
                    certitude_echeance=c_pai if paiement is not None else ct.INDETERMINE,
                )
            )  # fmt: skip
    pire = ct.plus_grave(
        [c for ligne in lignes for c in (ligne["certitude"], ligne.get("certitude_echeance", ct.ETABLI))] or [ct.ABSENT]
    )
    validation = (taxes.get("validation_cpa") or {}) if isinstance(taxes, Mapping) else {}
    return _section(
        "echeances", pire,
        f"{titre} : préparatoires, jamais validées par le CPA tant que le producteur ne le dit pas ; "
        "aucun paiement ni dépôt n'est inféré.",
        lignes, [ligne["note"] for ligne in lignes if ligne["certitude"] in (ct.INDETERMINE, ct.PERIME)], [lecture],
        validation_cpa=dict(validation), mention=ct.MENTION_CPA,
    )  # fmt: skip


def _sources_fiscales(lecture: _Lecture) -> dict:
    titre = TITRES["sources_fiscales"]
    if not lecture.utilisable:
        base = _non_lue(lecture, titre)
        return _section("sources_fiscales", base["certitude"], base["message"], [], base["manques"], [lecture])
    charge = lecture.page()["resultat"]["resultat"]
    renseignes, a_ren, _ = lecture.fait("resultat.resultat.base.parametres_renseignes")
    approuves, a_app, _ = lecture.fait("resultat.resultat.base.par_statut.approuve")
    non_renseignes, a_non, _ = lecture.fait("resultat.resultat.base.non_renseignes")
    par_statut: dict[str, int] = {}
    for sujet in charge["sujets"]:
        par_statut[sujet["statut_sources"]] = par_statut.get(sujet["statut_sources"], 0) + 1
    tout_approuve = (
        renseignes is not None and renseignes == approuves and int(non_renseignes or 0) == 0
        and set(par_statut) <= {"APPROUVE", "SANS_REGLE_REQUISE"}
    )  # fmt: skip
    certitude = ct.ETABLI if tout_approuve else ct.ESSAI
    lignes = [
        _ligne("Valeurs fiscales approuvées par deux réviseurs", approuves, certitude, adresse=a_app,
            unite=f"sur {renseignes}"),
        _ligne("Paramètres sans source officielle", non_renseignes, ct.ETABLI, adresse=a_non),
    ]  # fmt: skip
    for statut, nombre in sorted(par_statut.items()):
        lignes.append(_ligne(f"Sujets de conseil fiscal : {statut}", str(nombre), ct.ETABLI, unite="sujets"))
    message = (
        f"{titre} : {approuves}/{renseignes} valeurs approuvées ; tout conseil fiscal chiffré repose sur un essai ou "
        "sur une règle non renseignée tant que la revue n'est pas faite."
        if not tout_approuve
        else f"{titre} : toutes les valeurs renseignées sont approuvées."
    )
    return _section(
        "sources_fiscales", certitude, message, lignes,
        [] if tout_approuve else ["sources fiscales non approuvées : revue par deux personnes requise"], [lecture],
        mention=ct.MENTION_CPA,
    )  # fmt: skip


# ----------------------------------------------------------------------------------------------------- capacité
def _capacite(lecture: _Lecture) -> dict:
    titre = TITRES["capacite"]
    if not lecture.utilisable:
        base = _non_lue(lecture, titre)
        return _section("capacite", base["certitude"], base["message"], [], base["manques"], [lecture])
    calculable, _, _ = lecture.fait("resultat.resultat.calculable")
    manques = [str(m) for m in (lecture.page()["resultat"]["resultat"].get("manque") or [])][:10]
    if calculable != "true":
        return _section(
            "capacite", ct.INDETERMINE,
            f"{titre} : non calculable ; aucune capacité n'est estimée.", [], manques or ["cause non nommée"],
                [lecture],
        )  # fmt: skip
    lignes = []
    for libelle, chemin in (
        ("Heures d'équipe disponibles", "resultat.resultat.heures_disponibles"),
        ("Heures d'équipe planifiées", "resultat.resultat.heures_planifiees"),
    ):
        valeur, adresse, classe = lecture.fait(chemin)
        lignes.append(
            _ligne(
                libelle,
                valeur,
                classe if valeur is not None else ct.INDETERMINE,
                adresse=adresse,
                unite="heures déclarées",
            )
        )
    return _section(
        "capacite", ct.plus_grave([ligne["certitude"] for ligne in lignes]),
        f"{titre} : heures d'équipe déclarées ; ce ne sont ni des jours-personnes ni une présence individuelle.",
        lignes, manques, [lecture],
    )  # fmt: skip


# ----------------------------------------------------------------------------------------------------- chantiers
def _chantiers(captures: Sequence[Mapping], maintenant: str) -> dict:
    titre = TITRES["chantiers"]
    radar = rk.evaluer(captures, connaissance=maintenant)
    presents = [r for r in radar["risques"] if r["statut"] != "LEVE"]
    lignes = [
        _ligne(
            f"{r['regle']} — {r['sujet']}", r["gravite"], ct.ESSAI,
                note=f"statut {r['statut']} ; gravité selon une grille proposée",
            risque_id=r["risque_id"],
        )
        for r in presents[:MAX_RISQUES]
    ]  # fmt: skip
    inconnues = [n["regle"] for n in radar["regles_non_evaluees"]]
    if inconnues:
        certitude = ct.INDETERMINE
        message = (
            f"{titre} : {len(presents)} risque(s) sourcé(s) ; {len(inconnues)} règle(s) non évaluée(s) — un risque "
            "inconnu n'est pas un risque nul."
        )
    elif presents:
        certitude = ct.ESSAI
        message = (
            f"{titre} : {len(presents)} risque(s) sourcé(s) ; la gravité suit une grille non validée par la direction."
        )
    else:
        certitude = ct.ETABLI
        message = f"{titre} : aucun risque sourcé parmi les règles évaluées."
    connues = cs.connues_a(captures, maintenant)
    sources = [
        {"lecture_id": c["lecture_id"], "capture": c["index"], "hash_maillon": c["hash_maillon"], "recu_a": c["recu_a"]}
        for lecture_id in LECTURES["chantiers"]
        for c in [next((x for x in reversed(connues) if x["lecture_id"] == lecture_id), None)]
        if c is not None
    ]  # fmt: skip
    return {
        "id": "chantiers", "titre": titre, "certitude": certitude, "certain": ct.est_certain(certitude),
        "message": message, "lignes": lignes, "manques": [f"règle non évaluée : {r}" for r in inconnues[:10]],
        "sources": sources, "risques_presents": len(presents), "regles_non_evaluees": len(inconnues),
        "grille": radar["grille"]["statut"],
    }  # fmt: skip


# ----------------------------------------------------------------------------------------------------- alertes
def _alertes(alertes: Sequence[Mapping] | None) -> dict:
    titre = TITRES["alertes_m8"]
    if alertes is None:
        return {
            "id": "alertes_m8", "titre": titre, "certitude": ct.ABSENT, "certain": False,
            "message": f"{titre} : registre des alertes non fourni.", "lignes": [], "manques": ["registre non lu"],
            "sources": [],
        }  # fmt: skip
    seuils = sorted({a["metric_id"] for a in alertes if a.get("type_alerte") == "MESURE-SEUIL-A-CONFIGURER"})
    franchis = [a for a in alertes if a.get("type_alerte") == "MESURE-SEUIL-FRANCHI"]
    autres = [a for a in alertes if a.get("type_alerte") not in ("MESURE-SEUIL-FRANCHI", "MESURE-SEUIL-A-CONFIGURER")]
    lignes = [
        _ligne("Seuils de mesure franchis", str(len(franchis)), ct.ETABLI, unite="alertes"),
        _ligne("Alertes de qualité des données", str(len(autres)), ct.ETABLI, unite="alertes"),
    ]
    for alerte in sorted(franchis, key=lambda a: a["evenement_id"])[:MAX_RISQUES]:
        lignes.append(
            _ligne(
                f"{alerte['metric_id']}",
                None,
                ct.ETABLI,
                note=alerte["quoi"][:160],
                evenement_id=alerte["evenement_id"],
            )
        )
    manques = [f"seuil à configurer pour {m}" for m in seuils]
    return {
        "id": "alertes_m8", "titre": titre, "certitude": ct.ETABLI, "certain": True,
        "message": f"{titre} : {len(franchis)} seuil(s) franchi(s) dans la fenêtre ; M9 ne décide rien.",
        "lignes": lignes, "manques": manques, "sources": [{"lecture_id": "m8.alerte_proposee",
            "registre": "alertes_m8"}],
    }  # fmt: skip


# ----------------------------------------------------------------------------------------------------- composer
def composer(
    captures: Sequence[Mapping], *, maintenant: str, alertes_m8: Sequence[Mapping] | None = None,
    perime_apres_jours: int | None = None,
) -> dict:  # fmt: skip
    """Le tableau de direction à ``maintenant``, tel que M9 le connaissait à cet instant (une capture reçue plus tard
    n'y figure pas)."""
    if cs.instant(maintenant) is None:
        raise ValueError("REJ-TABLEAU-TEMPS : instant avec fuseau explicite requis")
    connues = cs.connues_a(captures, maintenant)
    lectures = {lecture_id: _Lecture(connues, lecture_id) for ids in LECTURES.values() for lecture_id in ids}
    sections = {
        "sante": _sante(lectures["m8.synthese_direction"]),
        "pipeline": _pipeline(lectures["m2.analyse_pipeline"]),
        "previsions": _previsions(lectures["m2.prevision_pipeline"]),
        "tresorerie": _tresorerie(connues, maintenant, perime_apres_jours),
        "echeances": _echeances(lectures["m5.calendrier_obligations"]),
        "sources_fiscales": _sources_fiscales(lectures["m5.statut_revue_fiscale"]),
        "capacite": _capacite(lectures["m4.capacite_equipe"]),
        "chantiers": _chantiers(connues, maintenant),
        "alertes_m8": _alertes(alertes_m8),
    }
    for section in sections.values():
        for source in section["sources"]:
            if "recu_a" in source:
                source["age_s"] = _age_s(maintenant, source["recu_a"])
    declarations = declarations_attendues(sections)
    tableau = {
        "type": "TABLEAU_DIRECTION",
        "version": VERSION,
        "maintenant": maintenant,
        "sections": sections,
        "declarations_attendues": declarations,
        "limites": list(_LIMITES),
    }
    tableau["tableau_id"] = hashlib.sha256(
        json.dumps(tableau, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return tableau


def declarations_attendues(sections: Mapping[str, Mapping]) -> list[dict]:
    """Ce que SEULE la direction peut fournir ou valider (bornes, pondérations, revue des sources, validation CPA) : des
    constats tirés des sections, jamais des décisions. Chaque élément nomme sa section."""
    attendues: list[dict] = []
    sante = sections["sante"]
    for texte in sante.get("a_faire_par_la_direction", []):
        attendues.append({"id": f"sante-{len(attendues) + 1}", "section": "sante", "texte": texte})
    sources = sections["sources_fiscales"]
    if sources["certitude"] == ct.ESSAI:
        attendues.append(
            {
                "id": "sources-fiscales",
                "section": "sources_fiscales",
                "texte": "Faire relire par deux personnes les sources fiscales avant tout conseil fiscal chiffré.",
            }
        )
    echeances = sections["echeances"]
    if echeances.get("validation_cpa") and any(v != "VALIDE" for v in echeances["validation_cpa"].values()):
        attendues.append(
            {
                "id": "calendrier-fiscal",
                "section": "echeances",
                "texte": "Faire valider le calendrier TPS/TVQ par le CPA (À valider auprès d'un comptable (CPA) / "
                         "professionnel qualifié).",
            }
        )
    return attendues


# ----------------------------------------------------------------------------------------------------- plan de lecture
PREVISION_PAR_DEFAUT = {"serie": "leads_ingeres", "methode": "moyenne_mobile", "fenetre": 3, "horizon": 4, "niveau": 80}
_SERIES = ("leads_ingeres", "leads_qualifies", "leads_convertis", "leads_perdus")


def plan_de_lectures(
    maintenant: str, jour: str, *, debut_semaine: str | None = None, prevision: Mapping | None = None
) -> list[dict]:  # fmt: skip
    """Les lectures que le rafraîchissement du tableau demande aux producteurs, avec leurs arguments : dérivées des
    seuls
    instants fournis. Rien n'est lu ici. La semaine de capacité n'est jamais devinée : sans ``debut_semaine``, la
    capacité est dite NON DEMANDÉE. Les paramètres de la prévision de M2 sont des choix de méthode (jamais des seuils
    d'affaires) : ils sont rendus avec le plan."""
    if cs.instant(maintenant) is None:
        raise ValueError("REJ-TABLEAU-TEMPS : instant avec fuseau explicite requis")
    try:
        import datetime as _dt

        _dt.date.fromisoformat(jour)
    except (TypeError, ValueError) as exc:
        raise ValueError("REJ-TABLEAU-TEMPS : jour AAAA-MM-JJ requis") from exc
    choix = {**PREVISION_PAR_DEFAUT, **dict(prevision or {})}
    if set(choix) != set(PREVISION_PAR_DEFAUT) or choix["serie"] not in _SERIES:
        raise ValueError("REJ-TABLEAU-PREVISION : serie, methode, fenetre, horizon et niveau seulement")
    plan = [
        {"lecture_id": "m8.synthese_direction", "arguments": {"maintenant": maintenant}},
        {"lecture_id": "m2.analyse_pipeline", "arguments": {"horodatage": maintenant}},
        {
            "lecture_id": "m2.prevision_pipeline",
            "arguments": {
                "horodatage": maintenant,
                "serie": choix["serie"],
                "methode": choix["methode"],
                "fenetre": choix["fenetre"],
                "horizon": choix["horizon"],
                "niveau": choix["niveau"],
            },
        },  # fmt: skip
        {"lecture_id": "m5.prevision_tresorerie", "arguments": {"aujourd_hui": jour}},
        {"lecture_id": "m5.calendrier_obligations", "arguments": {"aujourd_hui": jour}},
        {"lecture_id": "m5.statut_revue_fiscale", "arguments": {"aujourd_hui": jour}},
        {"lecture_id": "m5.comptes_a_payer", "arguments": {}},
        {"lecture_id": "m4.retards_incidents", "arguments": {"horodatage_reference": maintenant}},
        {"lecture_id": "m10.faits_analytiques", "arguments": {}},
    ]
    if debut_semaine is not None:
        plan.append(
            {
                "lecture_id": "m4.capacite_equipe",
                "arguments": {"debut_semaine": debut_semaine, "horodatage_reference": maintenant},
            }
        )
    return plan
