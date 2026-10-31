"""Port interne M5 de publication à partir d’une capacité M4 qualifiée."""

from opsys import service_capability, stockage

from . import encodage, outils, wct_recus


def _sources_metier(sources):
    return {k: v for k, v in sources.items() if k not in ("traces", "nombre_de_traces")}


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
