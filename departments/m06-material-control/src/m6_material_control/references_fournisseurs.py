"""Référence d'un préfixe fournisseur validé, sans données privées dans sa projection."""
import hashlib
import json
from datetime import datetime

from . import contrats, fournisseurs, tarif_soumission

MAX_SOURCES = 10000
MAX_OCTETS = 8388608
CHAMPS_SOURCE = (contrats.CHAMPS_FOURNISSEUR_REQUIS | contrats.CHAMPS_FOURNISSEUR_OPTIONNELS
                 | {'type_entree', 'horodatage'})


def projeter(journal, rang):
    if (type(rang) is not int or not 0 <= rang < MAX_SOURCES
            or len(journal) > MAX_SOURCES or rang >= len(journal)):
        raise ValueError('Source de référence fournisseur hors borne')
    prefixe = list(journal)[:rang + 1]
    try:
        tarif_soumission.verifier_journal_fournisseurs(prefixe)
        etats, revisions = {}, {}
        empreinte, taille = hashlib.sha256(), 0
        empreinte.update(b'[')
        for i, entree in enumerate(prefixe):
            if set(entree) - CHAMPS_SOURCE:
                raise ValueError('champs')
            ident = entree['fournisseur_id']
            courant = {**etats.get(ident, {}), **entree}
            _, refus = fournisseurs.enregistrer_fournisseur(
                ident, courant.get('nom'), courant.get('horodatage'), [],
                **{k: courant.get(k) for k in contrats.CHAMPS_FOURNISSEUR_OPTIONNELS})
            if refus is not None:
                raise ValueError('fiche')
            texte = json.dumps(entree, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':'), allow_nan=False).encode('utf-8')
            taille += len(texte) + 1
            if taille > MAX_OCTETS:
                raise ValueError('volume')
            empreinte.update((b',' if i else b'') + texte)
            etats[ident] = courant
            revisions[ident] = revisions.get(ident, 0) + 1
        empreinte.update(b']')
        original = prefixe[-1]
        horodatage = original.get('horodatage')
        if (type(horodatage) is not str or len(horodatage) > 50
                or datetime.fromisoformat(horodatage).utcoffset() is None):
            raise ValueError('horodatage')
        return dict(source_id=empreinte.hexdigest(), revision=revisions[original['fournisseur_id']],
                    horodatage=horodatage)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError('Source de référence fournisseur invalide') from None
