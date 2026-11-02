"""Port interne M5 de publication à partir d’une capacité M4 qualifiée."""

from opsys import service_capability, stockage

from . import encodage, outils, wct_recus


def _sources_metier(sources):
    return {k: v for k, v in sources.items() if k not in ("traces", "nombre_de_traces", "certifiees")}


def publier(devis_id, *, cap=None):
    """Dans la livraison active : source M4 et tarifs vérifiés avant publication."""
    if cap is None:
        cap = service_capability.courante()
    enveloppe = cap.projection_m4()
    faits, projection, charge = enveloppe["faits"], enveloppe["vue"], enveloppe["charge"]
    if charge.get("devis_id") != devis_id:
        raise service_capability.RefusAutorite("devis incompatible")
    sources = outils._sources_cout_reel()
    cnx = stockage.connexion_courante()

    def lecture_stricte():
        try:
            return {
                nom: stockage.copier_maillons_stricts(
                    cnx,
                    departement="m05-financecore",
                    registre=registre,
                    max_lignes=1000,
                    max_octets_ligne=262144,
                    max_octets_total=16777216,
                )
                for nom, registre in (("wct", "wct_recus"), ("devis", "devis_recus"))
            }
        except (ValueError, TypeError) as exc:
            raise service_capability.RefusAutorite("reçus M5 stricts non vérifiables") from exc

    captures = lecture_stricte()
    for nom, snapshot in captures.items():
        if encodage.encoder_canonique([ligne.maillon for ligne in snapshot.lignes]) != encodage.encoder_canonique(
            sources[nom]
        ):
            raise service_capability.RefusAutorite("reçus M5 divergents")

    def verifier_recus():
        actuels = lecture_stricte()
        if any(
            actuels[nom].empreinte_snapshot_calculee != captures[nom].empreinte_snapshot_calculee for nom in captures
        ):
            raise service_capability.RefusAutorite("reçus M5 modifiés")

    # Le reçu local est une preuve distincte de la projection propriétaire :
    # refuser ambiguïté, ancien reçu sans empreinte et champs locaux altérés.
    par_wct = [r for r in sources["wct"] if r.get("wct_id") == faits[3]]
    par_devis = [r for r in sources["wct"] if r.get("devis_id") == devis_id]
    devis = [r for r in sources["devis"] if r.get("devis_id") == devis_id]
    attendu = wct_recus.construire(
        wct_id=charge["wct_id"],
        intervention_id=charge["intervention_id"],
        devis_id=charge.get("devis_id"),
        horodatage_completion=charge["horodatage_completion"],
        duree_reelle_minutes=charge.get("duree_reelle_minutes"),
        empreinte_charge=encodage.empreinte(charge),
        **wct_recus.dimensions_a_rejouer(par_wct[0] if len(par_wct) == 1 else None, charge),
    )
    if (
        len(par_wct) != 1
        or len(par_devis) != 1
        or len(devis) > 1
        or encodage.encoder_canonique(par_wct[0]) != encodage.encoder_canonique(attendu)
        or encodage.encoder_canonique(par_devis[0]) != encodage.encoder_canonique(attendu)
    ):
        raise service_capability.RefusAutorite("reçu WCT M5 absent, divergent ou ambigu")
    try:
        wct_recus.verifier_rejeu(par_wct[0], charge)
    except (TypeError, ValueError) as exc:
        raise service_capability.RefusAutorite("reçu WCT M5 non vérifiable") from exc
    tarifs = outils._instantane_tarifs_equipes()
    etat = outils._etat_chantier(
        devis_id, sources, ventilation_verifiee={"projection": projection, "tarifs": tarifs, "charge": charge}
    )
    if etat["statut"] in ("en_attente_devis_accepte", "en_attente_travaux_termines"):
        cap.verifier_projection(enveloppe)
        verifier_recus()
        return {"statut": etat["statut"]}
    if etat["statut"] != "calculee":
        raise service_capability.RefusAutorite("état M5 inconnu")
    rentabilite = etat["rentabilite"]
    if rentabilite["wct_id"] != faits[3]:
        raise service_capability.RefusAutorite("WCT M5 divergent")
    sequence = sources["nombre_de_traces"].get(devis_id, 0) + 1
    precedent = sources["traces"].get(devis_id)
    if precedent is not None and precedent.get("version_entrees") == rentabilite["version_entrees"]:
        return {"statut": "deja_tracee"}
    signature = encodage.encoder_canonique(_sources_metier(sources))
    source_tarifs = tarifs["source"]
    cap.verifier_projection(enveloppe)
    if (
        encodage.encoder_canonique(_sources_metier(outils._sources_cout_reel())) != signature
        or outils._instantane_tarifs_equipes()["source"] != source_tarifs
    ):
        raise service_capability.RefusAutorite("sources M5 modifiées")
    provenance = {
        "version": faits[6],
        "instance_id": faits[1],
        "wct_id": faits[3],
        "source_m4": faits[5],
        "empreinte_projection": faits[7],
        "source_tarifs": source_tarifs,
    }
    registre = stockage.maillons("m05-financecore", "rentabilite")
    traces_avant = list(registre)
    rang = len(traces_avant)
    trace = outils._consigner_rentabilite(
        rentabilite, sequence, etat["horodatage"], provenance_service=provenance, publier=False
    )
    verifier_recus()
    recalcul_v2 = hasattr(cap, "attester_recalcul_m4")
    if recalcul_v2:
        reference = cap.attester_recalcul_m4(enveloppe, rang, encodage.empreinte(trace))
        from opsys.service_recalcul_m4 import valider_reference_v2

        valider_reference_v2(reference)
        if (
            reference["instance_id"] != faits[1]
            or reference["wct_id"] != faits[3]
            or reference["devis_id"] != devis_id
            or reference["wct_hash"] != faits[4]
            or reference["source_m4"] != faits[5]
            or reference["version_m4"] != faits[6]
            or reference["projection_m4"] != faits[7]
            or reference["trace_rang"] != rang
            or reference["trace_empreinte"] != encodage.empreinte(trace)
        ):
            raise service_capability.RefusAutorite("attestation recalcul invalide")
        nom_registre = "rentabilite_recalcul_v2"
        corps = {
            "type": "publication_recalcul_v2",
            "instance_id": faits[1],
            "wct_id": faits[3],
            "reference_core": reference,
            "trace_rang": rang,
            "trace_empreinte": encodage.empreinte(trace),
        }
        domaine = "m5.publication_recalcul.v2"
    else:
        reference = cap.attester_trace_m4(enveloppe, rang)
        if (
            type(reference) is not dict
            or set(reference) != {"schema", "id", "instance_id", "evenement_id", "operation", "revision"}
            or reference.get("schema") != "opsys.core.m4.audit-usage.v1"
            or type(reference.get("id")) is not int
            or reference["id"] <= 0
            or type(reference.get("revision")) is not int
            or reference["revision"] <= 0
            or reference.get("instance_id") != faits[1]
            or reference.get("evenement_id") != faits[3]
            or reference.get("operation") != "m4.verifier_v3"
        ):
            raise service_capability.RefusAutorite("référence Core historique indisponible")
        nom_registre = "rentabilite_service_v1"
        corps = {
            "type": "publication_service_v1",
            "instance_id": faits[1],
            "wct_id": faits[3],
            "reference_core": reference,
            "trace_rang": rang,
            "trace_empreinte": encodage.empreinte(trace),
        }
        domaine = "m5.publication_service.v1"
    registre_recus = stockage.maillons("m05-financecore", nom_registre)
    recus_avant = list(registre_recus)
    if len(recus_avant) >= 1000:
        raise service_capability.RefusAutorite("reçus service hors limites")
    recu = {**corps, "empreinte": encodage.empreinte(domaine, corps)}
    registre_recus.append(recu, rang_attendu=len(recus_avant))
    if (
        encodage.encoder_canonique(_sources_metier(outils._sources_cout_reel())) != signature
        or outils._instantane_tarifs_equipes()["source"] != source_tarifs
        or encodage.encoder_canonique(list(registre)) != encodage.encoder_canonique([*traces_avant, trace])
    ):
        raise service_capability.RefusAutorite("sources M5 modifiées avant publication")
    # Dernière revalidation après la création du reçu et les relectures M5.
    cap.verifier_projection(enveloppe)
    verifier_recus()
    outils._publier_rentabilite(rentabilite, sequence, etat["horodatage"])
    verifier_recus()
    # Une perte d'autorité pendant l'écriture annule l'événement dans cette transaction.
    cap.verifier_projection(enveloppe)
    if (
        encodage.encoder_canonique(_sources_metier(outils._sources_cout_reel())) != signature
        or outils._instantane_tarifs_equipes()["source"] != source_tarifs
        or encodage.encoder_canonique(list(registre)) != encodage.encoder_canonique([*traces_avant, trace])
        or encodage.encoder_canonique(list(registre_recus)) != encodage.encoder_canonique([*recus_avant, recu])
    ):
        raise service_capability.RefusAutorite("sources M5 modifiées après publication")
    if recalcul_v2:

        def strict_registre(nom):
            try:
                return stockage.copier_maillons_stricts(
                    cnx,
                    departement="m05-financecore",
                    registre=nom,
                    max_lignes=1000,
                    max_octets_ligne=262144,
                    max_octets_total=16777216,
                )
            except (ValueError, TypeError) as exc:
                raise service_capability.RefusAutorite("reçu ou trace strict non vérifiable") from exc

        verifier_recus()
        capture_trace, capture_recu = strict_registre("rentabilite"), strict_registre(nom_registre)
        if encodage.encoder_canonique(capture_trace.lignes[-1].maillon) != encodage.encoder_canonique(
            trace
        ) or encodage.encoder_canonique(capture_recu.lignes[-1].maillon) != encodage.encoder_canonique(recu):
            raise service_capability.RefusAutorite("trace ou reçu modifié")

        def controle_final():
            cap.verifier_projection(enveloppe)
            verifier_recus()
            actuelles = outils._sources_cout_reel()
            if (
                encodage.encoder_canonique(_sources_metier(actuelles)) != signature
                or outils._instantane_tarifs_equipes()["source"] != source_tarifs
                or strict_registre("rentabilite") != capture_trace
                or strict_registre(nom_registre) != capture_recu
            ):
                raise service_capability.RefusAutorite("source M5 modifiée après écriture finale")

        return {
            "statut": "publiee",
            "version": rentabilite["version_entrees"],
            "attestation": reference,
            "_controle_final": controle_final,
        }
    return {"statut": "publiee", "version": rentabilite["version_entrees"]}


# -- Lecture pour le réconciliateur Core (E8) et l'affichage admin (D3) : lecture seule, aucune écriture -------------
_DOMAINE_INTENTION = "opsys.reconciliateur.cout-certifie.v1"


def etat_cout_certifie(devis_id, sources=None):
    """L'état du coût certifié d'un devis tel que M5 le voit, depuis ses registres : statut D3, WCT reçu, et
    l'empreinte de l'état ordinaire (pièces M5) qui fonde une intention DÉTERMINISTE (même état, même intention).

    `statut` vaut `a_jour`, `perime_recalcul_en_attente`, `inconnu`, ou `non_calculable` (devis ou WCT pas encore
    reçus, WCT sans devis). Ne lit ni M4, ni la projection : le moteur qualifié s'en charge sous politique."""
    sources = outils._sources_cout_reel() if sources is None else sources
    etat = outils._etat_chantier(devis_id, sources)
    if etat["statut"] != "calculee":
        return {"statut": "non_calculable", "devis_id": devis_id, "raison": etat["statut"]}
    rentabilite = etat["rentabilite"]
    statut, certifiee, sequence = outils._statut_cout_certifie(devis_id, rentabilite, sources)
    perime_signale = any(
        isinstance(m, dict) and m.get("code") == outils.cout_reel.CODE_CERTIFIE_A_RECALCULER
        for m in ((sources["traces"].get(devis_id) or {}).get("rentabilite") or {}).get("manque", ())
    )
    source_tarifs = outils._source_tarifs_equipes_ou_none()
    nombre = sources["nombre_de_traces"].get(devis_id, 0)
    empreinte = encodage.empreinte(_DOMAINE_INTENTION, {
        "wct_id": rentabilite["wct_id"], "devis_id": devis_id, "version_entrees": rentabilite["version_entrees"],
        "source_tarifs": source_tarifs, "nombre_de_traces": nombre,
    })
    return {
        "statut": statut, "devis_id": devis_id, "wct_id": rentabilite["wct_id"], "empreinte_etat": empreinte,
        "perime_signale": perime_signale, "sequence_certifiee": sequence,
        "version_certifiee": None if certifiee is None else certifiee.get("version_entrees"),
        "empreinte_projection_certifiee": None if certifiee is None
        else (certifiee.get("provenance_service_v1") or {}).get("empreinte_projection"),
        "signature_main_d_oeuvre_certifiee": None if certifiee is None else signature_main_d_oeuvre(certifiee),
    }


def signature_main_d_oeuvre(trace):
    """Empreinte de ce que la projection M4 CHIFFRE dans une trace (statut, minutes, taux, coût, lignes par visite
    et équipe, manques), sans les empreintes de provenance (`projection_empreinte`, `tarifs_empreinte`) : celles-ci
    changent à chaque écriture M4 ou M5, même sans rapport avec ce chantier."""
    corps = trace.get("rentabilite") if isinstance(trace, dict) else None
    cout = corps.get("cout_reel") if isinstance(corps, dict) else None
    mo = cout.get("main_d_oeuvre") if isinstance(cout, dict) else None
    if not isinstance(mo, dict):
        return None
    return encodage.empreinte("m5.signature-main-d-oeuvre.v1", {
        k: v for k, v in mo.items() if k not in ("projection_empreinte", "tarifs_empreinte")})


def signature_main_d_oeuvre_derniere(devis_id):
    """Signature de la DERNIÈRE trace du devis (celle que le moteur vient d'écrire dans un savepoint)."""
    traces = [t for t in stockage.maillons("m05-financecore", "rentabilite") if t.get("devis_id") == devis_id]
    return signature_main_d_oeuvre(traces[-1]) if traces else None


def certifies_a_jour(sources=None):
    """Devis dont le dernier certifié est `a_jour` côté M5 : ceux dont une correction purement M4 pourrait avoir
    changé la projection (le réconciliateur la relit sous politique). Ordre de réception des WCT."""
    sources = outils._sources_cout_reel() if sources is None else sources
    vus, etats = set(), []
    for recu in sources["wct"]:
        devis_id = recu.get("devis_id")
        if type(devis_id) is not str or not devis_id or devis_id in vus:
            continue
        vus.add(devis_id)
        etat = etat_cout_certifie(devis_id, sources)
        if etat["statut"] == "a_jour" and etat["signature_main_d_oeuvre_certifiee"]:
            etats.append(etat)
    return etats


def marquer_a_recalculer(devis_id):
    """Marque le devis « à recalculer » (trace partielle `REJ-COUT-CERTIFIE-A-RECALCULER`, mécanisme E1)."""
    return outils._marquer_cout_certifie_a_recalculer(devis_id)


def candidats_cout_certifie(sources=None):
    """Devis dont le coût certifié n'est pas à jour, dans un ordre déterministe : d'abord ceux qu'une trace
    `REJ-COUT-CERTIFIE-A-RECALCULER` vient de déclarer périmés, puis les autres périmés, puis les inconnus (ordre
    de réception des WCT). Un WCT sans devis ou un devis non calculable n'est jamais candidat."""
    sources = outils._sources_cout_reel() if sources is None else sources
    vus, etats = set(), []
    for recu in sources["wct"]:
        devis_id = recu.get("devis_id")
        if type(devis_id) is not str or not devis_id or devis_id in vus:
            continue
        vus.add(devis_id)
        etat = etat_cout_certifie(devis_id, sources)
        if etat["statut"] in ("perime_recalcul_en_attente", "inconnu"):
            etats.append(etat)

    def rang(e):
        return 0 if e["perime_signale"] else (1 if e["statut"] == "perime_recalcul_en_attente" else 2)

    return sorted(etats, key=rang)  # tri stable : l'ordre de réception est conservé à rang égal
