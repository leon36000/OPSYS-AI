"""Lecture M5 privée sous portée de revalidation Core ; ne publie ni ne crée de droit."""

from opsys import service_capability, stockage

from . import cout_reel, devis_recus, encodage, outils, wct_recus


def _capturer(cnx):
    registres = [
        ("m05-financecore", n)
        for n in (
            "wct_recus",
            "devis_recus",
            "variance_recue",
            "factures",
            "tarifs_equipes",
            "rentabilite",
            "rentabilite_service_v1",
            "rentabilite_recalcul_v2",
        )
    ] + [("m06-material-control", "livre_prix")]
    try:
        captures = {
            nom: stockage.copier_maillons_stricts(
                cnx,
                departement=departement,
                registre=nom,
                max_lignes=1000,
                max_octets_ligne=262144,
                max_octets_total=16777216,
            )
            for departement, nom in registres
        }
    except (TypeError, ValueError) as exc:
        raise service_capability.RefusAutorite("sources strictes non vérifiables") from exc
    if any(type(ligne.maillon) is not dict for capture in captures.values() for ligne in capture.lignes):
        raise service_capability.RefusAutorite("type de source invalide")
    return captures


def calculer(devis_id, cap):
    """Recalcule depuis une portée Core déjà ouverte, sans écriture ni valeur d'appelant."""
    cnx = stockage.connexion_courante()
    if cnx is None or not cnx.in_transaction() or cnx.dialect.name != "sqlite" or type(devis_id) is not str:
        raise service_capability.RefusAutorite("lecture courante non qualifiée")
    enveloppe = cap.projection_m4()
    faits, projection, charge = enveloppe["faits"], enveloppe["vue"], enveloppe["charge"]
    if charge.get("devis_id") != devis_id:
        raise service_capability.RefusAutorite("devis différent de la portée")
    cap.verifier_projection(enveloppe)
    try:
        preuve_devis = cap.lire_devis_m3()
    except (TypeError, ValueError, KeyError) as exc:
        raise service_capability.RefusAutorite("source devis M3 non vérifiable") from exc
    if type(preuve_devis) is not dict or set(preuve_devis) != {"charge", "empreinte"}:
        raise service_capability.RefusAutorite("preuve devis M3 invalide")
    avant = _capturer(cnx)
    sources = outils._sources_cout_reel()
    tarifs = outils._instantane_tarifs_equipes()
    for nom, valeur in (
        ("wct_recus", sources["wct"]),
        ("devis_recus", sources["devis"]),
        ("variance_recue", sources["variance"]),
        ("factures", outils._registre_factures(None).lire()),
        ("tarifs_equipes", list(stockage.maillons("m05-financecore", "tarifs_equipes"))),
        ("livre_prix", list(sources["livre"])),
    ):
        if encodage.encoder_canonique([x.maillon for x in avant[nom].lignes]) != encodage.encoder_canonique(valeur):
            raise service_capability.RefusAutorite("sources M5 divergentes")
    traces = [x.maillon for x in avant["rentabilite"].lignes]
    derniers = {x.get("devis_id"): x for x in traces}
    if encodage.encoder_canonique(derniers) != encodage.encoder_canonique(sources["traces"]):
        raise service_capability.RefusAutorite("traces M5 divergentes")
    recu_wct = [r for r in sources["wct"] if r.get("wct_id") == faits[3]]
    recu_devis = [r for r in sources["devis"] if r.get("devis_id") == devis_id]
    wct_devis = [r for r in sources["wct"] if r.get("devis_id") == devis_id]
    attendu = wct_recus.construire(
        wct_id=charge["wct_id"],
        intervention_id=charge["intervention_id"],
        devis_id=charge.get("devis_id"),
        horodatage_completion=charge["horodatage_completion"],
        duree_reelle_minutes=charge.get("duree_reelle_minutes"),
        empreinte_charge=encodage.empreinte(charge),
    )
    if (
        len(recu_wct) != 1
        or len(wct_devis) != 1
        or len(recu_devis) != 1
        or encodage.encoder_canonique(recu_wct[0]) != encodage.encoder_canonique(attendu)
        or encodage.encoder_canonique(wct_devis[0]) != encodage.encoder_canonique(attendu)
    ):
        raise service_capability.RefusAutorite("reçu WCT ou devis absent, divergent ou ambigu")
    devis_source = preuve_devis["charge"]
    if type(devis_source) is not dict or devis_source.get("devis_id") != devis_id:
        raise service_capability.RefusAutorite("charge devis M3 divergente")
    try:
        devis_attendu = devis_recus.construire(
            devis_id=devis_source["devis_id"],
            lead_id=devis_source["lead_id"],
            chantier_id=devis_source["chantier_id"],
            lignes=devis_source["lignes"],
            prix_total=devis_source["prix_total"],
            horodatage_acceptation=devis_source["horodatage_acceptation"],
            cout_total=devis_source.get("cout_total"),
            taux_marge=devis_source.get("taux_marge"),
        )
    except KeyError as exc:
        raise service_capability.RefusAutorite("charge devis M3 incomplète") from exc
    if encodage.encoder_canonique(recu_devis[0]) != encodage.encoder_canonique(devis_attendu):
        raise service_capability.RefusAutorite("réception M5 et source devis M3 divergentes")
    try:
        wct_recus.verifier_rejeu(recu_wct[0], charge)
    except (TypeError, ValueError) as exc:
        raise service_capability.RefusAutorite("reçu WCT non vérifiable") from exc
    signature = encodage.encoder_canonique(sources, tarifs)
    cap.verifier_projection(enveloppe)
    etat = outils._etat_chantier(
        devis_id, sources, ventilation_verifiee={"projection": projection, "tarifs": tarifs, "charge": charge}
    )
    trace = sources["traces"].get(devis_id)
    if (
        etat.get("statut") == "calculee"
        and trace is not None
        and trace.get("version_entrees") == etat["rentabilite"]["version_entrees"]
    ):
        attendue = cout_reel.construire_trace(etat["rentabilite"], etat["horodatage"])
        if set(trace) != set(attendue) | {"provenance_service_v1"} or encodage.encoder_canonique(
            {k: trace[k] for k in attendue}
        ) != encodage.encoder_canonique(attendue):
            raise service_capability.RefusAutorite("trace courante divergente")
        provenance = trace["provenance_service_v1"]
        prov_attendue = {
            "version": faits[6],
            "instance_id": faits[1],
            "wct_id": faits[3],
            "source_m4": faits[5],
            "empreinte_projection": faits[7],
            "source_tarifs": tarifs["source"],
        }
        if encodage.encoder_canonique(provenance) != encodage.encoder_canonique(prov_attendue):
            raise service_capability.RefusAutorite("provenance courante divergente")
        rang = next(
            (
                ligne.rang
                for ligne in reversed(avant["rentabilite"].lignes)
                if ligne.maillon.get("devis_id") == devis_id
            ),
            None,
        )
        recus = [
            (nom, ligne.maillon)
            for nom in ("rentabilite_service_v1", "rentabilite_recalcul_v2")
            for ligne in avant[nom].lignes
            if type(ligne.maillon) is dict and ligne.maillon.get("trace_rang") == rang
        ]
        if len(recus) != 1:
            raise service_capability.RefusAutorite("publication M5 absente ou ambiguë")
        registre, recu = recus[0]
        if (
            type(recu.get("trace_rang")) is not int
            or recu["trace_rang"] != rang
            or recu.get("instance_id") != faits[1]
            or recu.get("wct_id") != faits[3]
            or recu.get("trace_empreinte") != encodage.empreinte(trace)
        ):
            raise service_capability.RefusAutorite("reçu de publication divergent")
        ref = recu.get("reference_core")
        if type(ref) is not dict:
            raise service_capability.RefusAutorite("référence Core absente")
        if registre == "rentabilite_recalcul_v2":
            from opsys.service_recalcul_m4 import valider_reference_v2

            valider_reference_v2(ref)
            domaine, type_recu = "m5.publication_recalcul.v2", "publication_recalcul_v2"
            if (
                ref["devis_id"] != devis_id
                or ref["wct_id"] != faits[3]
                or ref["instance_id"] != faits[1]
                or ref["source_m4"] != faits[5]
                or ref["projection_m4"] != faits[7]
                or ref["version_m4"] != faits[6]
                or ref["trace_rang"] != rang
                or ref["trace_empreinte"] != recu["trace_empreinte"]
            ):
                raise service_capability.RefusAutorite("référence V2 divergente")
        else:
            domaine, type_recu = "m5.publication_service.v1", "publication_service_v1"
            if (
                set(ref) != {"schema", "id", "instance_id", "evenement_id", "operation", "revision"}
                or ref.get("schema") != "opsys.core.m4.audit-usage.v1"
                or type(ref.get("id")) is not int
                or ref["id"] <= 0
                or type(ref.get("revision")) is not int
                or ref["revision"] <= 0
                or ref.get("instance_id") != faits[1]
                or ref.get("evenement_id") != faits[3]
                or ref.get("operation") != "m4.verifier_v3"
            ):
                raise service_capability.RefusAutorite("référence V1 invalide")
        champs = {"type", "instance_id", "wct_id", "reference_core", "trace_rang", "trace_empreinte", "empreinte"}
        if set(recu) != champs or recu.get("type") != type_recu:
            raise service_capability.RefusAutorite("forme de publication invalide")
        corps = {k: v for k, v in recu.items() if k != "empreinte"}
        if recu["empreinte"] != encodage.empreinte(domaine, corps):
            raise service_capability.RefusAutorite("empreinte de publication invalide")
        preuve_historique = cap.verifier_reference_publication(ref)
        if registre == "rentabilite_recalcul_v2":
            attendu_historique = {
                "schema": "opsys.core.m4.historique-v2",
                "reference": ref,
                "version_resultat": trace["version_entrees"],
                "statut": "historique_non_revalide",
            }
        else:
            from opsys.service_lecture_m4 import empreinte_trace_v1

            attendu_historique = {
                "schema": "opsys.core.m4.historique-v1",
                "instance_id": faits[1],
                "wct_id": faits[3],
                "audit_id": ref["id"],
                "revision": ref["revision"],
                "trace_rang": rang,
                "trace_sha256": empreinte_trace_v1(trace),
                "source_m4": faits[5],
                "projection_sha256": faits[7],
                "version_m4": faits[6],
                "statut": "historique_non_revalide",
            }
        if encodage.encoder_canonique(preuve_historique) != encodage.encoder_canonique(attendu_historique):
            raise service_capability.RefusAutorite("preuve historique Core divergente")
    apres = _capturer(cnx)
    if any(avant[n].empreinte_snapshot_calculee != apres[n].empreinte_snapshot_calculee for n in avant):
        raise service_capability.RefusAutorite("sources M5 modifiées")
    if signature != encodage.encoder_canonique(outils._sources_cout_reel(), outils._instantane_tarifs_equipes()):
        raise service_capability.RefusAutorite("sources métier modifiées")
    try:
        preuve_devis_apres = cap.lire_devis_m3()
    except (TypeError, ValueError, KeyError) as exc:
        raise service_capability.RefusAutorite("source devis M3 modifiée") from exc
    if encodage.encoder_canonique(preuve_devis_apres) != encodage.encoder_canonique(preuve_devis):
        raise service_capability.RefusAutorite("preuve devis M3 modifiée")
    cap.verifier_projection(enveloppe)
    return etat, sources
