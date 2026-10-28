"""Lecture des rencontres M2 d'un projet; HTML échappé et continuation liée aux sources."""
import re
from urllib.parse import urlencode

from fastapi import HTTPException

from . import pages


def base_url(prefixe, lead_id):
    return f"{prefixe}/crm/lead/{pages._segment(lead_id)}/rencontres"


def parametres(query):
    brut = query.get("decalage", "0")
    source = query.get("source_attendue", "")
    if (set(query) - {"decalage", "source_attendue"}
            or any(len(query.getlist(k)) != 1 for k in query)
            or re.fullmatch(r"[0-9]{1,5}", brut) is None
            or int(brut) > 10000 or int(brut) % 25
            or (source and re.fullmatch(r"[0-9a-f]{64}", source) is None)
            or (int(brut) > 0 and not source)):
        raise HTTPException(400, "Pagination des rencontres invalide")
    return {"decalage": int(brut), "source_attendue": source}


def contenu(lead_id, resultat, prefixe):
    base = base_url(prefixe, lead_id)
    debut = (f'<section class="carte" id="rencontres"><h2>Rencontres de ce projet : {pages.e(lead_id)}</h2>'
             '<p>Agenda interne M2, heures de Montréal. Tous vendeurs d’origine, y compris les rendez-vous '
             'annulés. Une planification ne prouve ni la confirmation du client ni la tenue de la rencontre.</p>')
    if resultat is None:
        return (debut + '<p role="alert">Rencontres indisponibles : '
                'la source ne permet pas une lecture fiable.</p></section>')
    lignes = []
    for r in resultat["rendez_vous"]:
        lien = f'{prefixe}/crm/agenda/rendez-vous/{pages._segment(r["rendez_vous_id"])}'
        propriete = '' if r['propriete_courante'] else ' — vendeur d’origine, projet réassigné'
        statut = 'Annulé' if r['statut'] == 'annule' else 'Planifié en interne'
        lignes.append(
            f'<tr><td><a href="{pages.e(lien)}">{pages.e(r["titre"])}</a></td>'
            f'<td>{pages.e(r["debut"])} → {pages.e(r["fin"])}</td>'
            f'<td>{pages.e(r["vendeur_id"])}{propriete}</td><td>{statut}</td>'
            f'<td>Révision {r["revision"]} · {pages.e(r["source_id"])}</td></tr>')
    tableau = ('<table><thead><tr><th>Rencontre et historique</th><th>Créneau</th><th>Vendeur</th>'
               '<th>État</th><th>Source M2</th></tr></thead><tbody>' + ''.join(lignes) + '</tbody></table>'
               if lignes else '<p>Aucune rencontre enregistrée pour ce projet.</p>')
    navigation = f'<a href="{pages.e(base)}">Recommencer la lecture</a>'
    for offset, label in [(resultat['decalage'] - 25, 'Page précédente'),
                          (resultat['decalage_suivant'], 'Page suivante')]:
        if offset is not None and offset >= 0:
            lien = base + '?' + urlencode({'decalage': offset, 'source_attendue': resultat['source_empreinte']})
            navigation += f' · <a href="{pages.e(lien)}">{label}</a>'
    return (debut + f'<p>{resultat["total"]} rencontre(s), ordre chronologique, 25 par page.</p>'
            + tableau + f'<p>{navigation}</p>'
            + f'<p class="note">Empreinte de lecture M2 : {pages.e(resultat["source_empreinte"])}</p></section>')
