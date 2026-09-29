import { interpreterResultatListerDemandes } from "../approbations/contrat";
import type { ListeApprobations } from "../approbations/contrat";
import { construireArgumentsListerDemandes, OUTIL_LISTER_DEMANDES } from "../approbations/chargeur";
import { estObjet } from "../protocole/enveloppeOutil";
import type { ConfigurationChargeurAdmin } from "./appel";
import { ouvrirEnveloppe } from "./enveloppe";
import type { LectureSection } from "./enveloppe";
import { lireSection } from "./lecture";
import type { DefinitionSection, ResultatSection } from "./lecture";

/**
 * L'accueil « À voir » du propriétaire (`(admin)/admin.tsx`, PLAN T4.20, §9.5 « Approbations » et alertes) : les
 * demandes d'approbation en attente et les attentes des départements (complétion en revue avec écart de matériaux
 * critique, facture prête, chantier à réviser, besoin de commande...) que `m9_lister_demandes_approbation` rend. C'est
 * la MÊME lecture que l'écran des approbations (`approvals.tsx`), que l'accueil ne remplace pas : il la résume, avec le
 * lien vers lui. L'accueil ne décide de rien et n'offre aucun bouton de décision.
 *
 * Lecture d'abord, cache marqué (date et raison) ; un refus du serveur n'est jamais remplacé par le cache. À la
 * différence de `approvals.tsx` (qui n'a pas de cache : on ne décide pas une demande peut-être déjà décidée), l'accueil
 * ne montre que des sommaires, marqués comme gardés.
 *
 * MINIMISATION (Loi 25) : ce que l'accueil ne montre pas n'est pas gardé. Les arguments exacts d'une demande, son motif et
 * la description de son outil restent au serveur ; le cache les remplace par « non affichés » (`null`, ce que le
 * serveur dit déjà d'une personne qui n'a pas le droit de les voir), et se relit par le MÊME lecteur.
 */
export const SECTION_A_VOIR: DefinitionSection<ListeApprobations> = {
  outil: OUTIL_LISTER_DEMANDES,
  args: construireArgumentsListerDemandes(undefined),
  cache: "a_voir",
  interpreter: interpreterAVoir,
  epurerPourLeCache: epurerPourLeCache,
};

/**
 * Lit l'enveloppe de `m9_lister_demandes_approbation` en gardant les trois genres d'échec : `interpreterResultatListerDemandes`
 * les fond en un seul verdict, alors que le cache ne doit jamais remplacer un REFUS et peut remplacer une panne.
 */
export function interpreterAVoir(resultatBrut: unknown): LectureSection<ListeApprobations> {
  const ouverte = ouvrirEnveloppe(resultatBrut, "couple");
  if (!ouverte.ok) {
    return ouverte;
  }
  const lue = interpreterResultatListerDemandes(resultatBrut);
  return lue.ok ? { ok: true, valeur: lue.liste } : { ok: false, genre: "illisible", verdict: lue.verdict };
}

/** L'enveloppe, sans les arguments, le motif ni la description de chaque demande : ce que l'accueil ne montre pas. */
export function epurerPourLeCache(resultatBrut: unknown): unknown {
  if (!estObjet(resultatBrut) || !estObjet(resultatBrut.resultat) || !estObjet(resultatBrut.resultat.resultat)) {
    return resultatBrut;
  }
  const corps = resultatBrut.resultat.resultat;
  if (!Array.isArray(corps.demandes)) {
    return resultatBrut;
  }
  const demandes = corps.demandes.map((demande: unknown) =>
    estObjet(demande) ? { ...demande, arguments: null, motif_demande: null, description_outil: null } : demande,
  );
  return { ...resultatBrut, resultat: { ...resultatBrut.resultat, resultat: { ...corps, demandes } } };
}

export interface ChargeurAVoir {
  /** Ne lève jamais pour une raison réseau ou HTTP. */
  chargerAVoir(): Promise<ResultatSection<ListeApprobations>>;
}

export function creerChargeurAVoir(config: ConfigurationChargeurAdmin): ChargeurAVoir {
  return { chargerAVoir: () => lireSection(config, SECTION_A_VOIR) };
}
