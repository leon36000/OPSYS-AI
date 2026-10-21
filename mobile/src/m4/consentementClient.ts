import type { StatutMutation } from "../outbox/types";

/**
 * Consentements que l'employé recueille AUPRÈS DU CLIENT à « Terminer » (PLAN T1.5-d,
 * DEFINITION-PRODUIT.md §6 « travaux terminés », ligne M7 : « propose une demande d'avis et, avec
 * consentement, du contenu avant/après » ; §9.3 employé : « autorisation du client », « client
 * satisfait oui/non »).
 *
 * Lecture SEULE de `departments/m04-field-ops/src/m4_field_ops/outils.py` (closure
 * `completer_intervention`, `_preuve_consentement_client`) — jamais exécuté ici (ADR-0008).
 *
 * **Deux consentements DISTINCTS** (Loi 25 ; `docs/compliance/politiques/POLITIQUE-photos-non-
 * contractuelles.md` §3 : « consentement distinct et explicite ») : être contacté pour laisser un avis
 * (`consentement_demande_avis`) et l'usage de photos du chantier par l'entreprise
 * (`consentement_marketing`). L'un n'est jamais déduit de l'autre : deux cases, deux énoncés.
 *
 * **Rien n'est inventé.** Les deux cases sont NON COCHÉES par défaut (`CHOIX_CLIENT_VIDES`) ; une case
 * non cochée n'envoie RIEN (ni `false`, ni valeur par défaut) : absence = non consenti, côté serveur
 * comme côté M7. `client_satisfait` n'est envoyé que si l'employé a relevé une réponse du client.
 *
 * **Ce que l'app envoie, et ce qu'elle ne peut PAS écrire.** Elle envoie les consentements cochés et
 * l'identifiant de la version du texte présenté (`consentement_version_texte`). Qui les a recueillis
 * et quand est posé par le SERVEUR (la personne authentifiée du jeton, l'heure de réception du
 * serveur) : le schéma de `m4_completer_intervention` ne connaît pas `consentement_recueilli_par`
 * ni `consentement_recueilli_le`, l'appareil ne peut donc pas les fournir. `photos` et
 * `description_factuelle` ne sont pas envoyés non plus : ce ne sont pas des paroles du client, et
 * aucune désignation photo par photo n'existe (M7 floute et fait valider chaque contenu).
 *
 * **Le texte est versionné.** `VERSION_TEXTE_CONSENTEMENT_CLIENT` désigne EXACTEMENT les deux énoncés
 * ci-dessous, en fr-CA (le client d'ici est servi en français ; ces énoncés ne suivent pas la langue
 * de l'interface de l'employé). Modifier un mot exige une NOUVELLE version : le test
 * `consentementClient.test.ts` épingle l'empreinte SHA-256 du texte à sa version et échoue sinon. Le
 * serveur garde la version avec chaque consentement, il peut donc dire à quoi un client a consenti.
 *
 * **PROPOSITION** : ces énoncés sont à faire valider par Nathan ou un juriste (T3) avant tout usage
 * réel. Le retrait du consentement se fait aujourd'hui à la demande, par une personne : le moteur n'a
 * pas encore de mécanisme de retrait (M7, `contenu_public.py`).
 */

/** Identifiant du texte ci-dessous : lettres, chiffres, point, tiret, 64 au plus — le format que le
 * serveur exige (`_FORMAT_VERSION_TEXTE_CONSENTEMENT`, `outils.py`). */
export const VERSION_TEXTE_CONSENTEMENT_CLIENT = "consentement-client-fr-CA-v1";

export const TEXTE_CONSENTEMENT_DEMANDE_AVIS =
  "J'accepte que l'entreprise me contacte pour me demander de laisser un avis en ligne sur les travaux " +
  "réalisés chez moi. Je peux refuser sans que cela change quoi que ce soit au service reçu, et retirer " +
  "mon consentement en tout temps en le demandant à l'entreprise.";

export const TEXTE_CONSENTEMENT_PHOTOS =
  "J'accepte que des photos des travaux réalisés chez moi servent à faire connaître l'entreprise (site " +
  "Web, réseaux sociaux), après avoir été floutées (visages, plaques d'immatriculation, adresse). Je peux " +
  "refuser sans que cela change quoi que ce soit au service reçu, et retirer mon consentement en tout " +
  "temps en le demandant à l'entreprise.";

/** Réponse relevée auprès du client à « êtes-vous satisfait du résultat ? » ; `null` = pas de réponse
 * relevée (jamais un « oui » par défaut). */
export type ReponseSatisfaction = "satisfait" | "insatisfait" | null;

/** Ce que l'employé a relevé auprès du client, tel que l'écran le tient. */
export interface ChoixClient {
  readonly consentementDemandeAvis: boolean;
  readonly consentementPhotos: boolean;
  readonly satisfaction: ReponseSatisfaction;
}

/** État initial de l'écran : aucune case cochée, aucune réponse (rien n'est consenti d'avance). */
export const CHOIX_CLIENT_VIDES: ChoixClient = {
  consentementDemandeAvis: false,
  consentementPhotos: false,
  satisfaction: null,
};

/** Les champs client de `m4_completer_intervention` que cette app peut envoyer (sous-ensemble du
 * schéma serveur). Les consentements ne valent que `true` : une case décochée n'a pas de clé. */
export interface ChampsClientM4 {
  readonly consentement_demande_avis?: true;
  readonly consentement_marketing?: true;
  readonly consentement_version_texte?: string;
  readonly client_satisfait?: boolean;
}

/**
 * Champs client à joindre aux arguments de « Terminer » (fonction pure, sans horloge ni état).
 *
 *  - une case cochée -> sa clé à `true`, et JAMAIS une clé à `false` pour une case décochée ;
 *  - `consentement_version_texte` seulement si l'un des consentements est envoyé (le serveur l'exige
 *    alors, et le refuse sans consentement) ;
 *  - `client_satisfait` seulement si une réponse a été relevée : `true` ou `false`.
 * Aucun choix : `{}` — « Terminer » part exactement comme avant.
 */
export function construireChampsClient(choix: ChoixClient): ChampsClientM4 {
  const champs: {
    -readonly [C in keyof ChampsClientM4]: ChampsClientM4[C];
  } = {};
  if (choix.consentementDemandeAvis) {
    champs.consentement_demande_avis = true;
  }
  if (choix.consentementPhotos) {
    champs.consentement_marketing = true;
  }
  if (choix.consentementDemandeAvis || choix.consentementPhotos) {
    champs.consentement_version_texte = VERSION_TEXTE_CONSENTEMENT_CLIENT;
  }
  if (choix.satisfaction !== null) {
    champs.client_satisfait = choix.satisfaction === "satisfait";
  }
  return champs;
}

/** Les deux cases de consentement de l'écran. */
export type CaseConsentement = "consentementDemandeAvis" | "consentementPhotos";

/** Coche ou décoche une case (fonction pure : l'état de l'écran n'est jamais modifié en place). Le
 * client peut se raviser tant que « Terminer » n'est pas parti : décocher retire la clé de l'envoi. */
export function basculerConsentement(choix: ChoixClient, caseVisee: CaseConsentement): ChoixClient {
  return { ...choix, [caseVisee]: !choix[caseVisee] };
}

/** Relève la réponse du client ; toucher deux fois la même réponse l'efface (`null` : pas de réponse
 * relevée, jamais un « oui » par défaut). */
export function choisirSatisfaction(choix: ChoixClient, reponse: Exclude<ReponseSatisfaction, null>): ChoixClient {
  return { ...choix, satisfaction: choix.satisfaction === reponse ? null : reponse };
}

export interface EtatVerrouillageChoixClient {
  readonly enTraitement: boolean;
  /** Le serveur a accepté la complétion (cette session, ou une précédente : statut `envoyee`). */
  readonly completionEnvoyee: boolean;
  /** Statut de la mutation `job_completion` du chantier dans la file sortante, `null` s'il n'y en a pas. */
  readonly statutMutationCompletion: StatutMutation | null;
}

/**
 * Les choix du client ne bougent plus dès que la complétion est en cours d'envoi, en file (hors ligne)
 * ou partie : ce qui est parti est ce que le client a accepté à cet instant, l'écran ne doit pas en
 * montrer un autre. Un rejet DÉFINITIF les libère : rien de ce qui est parti ne vaut plus, l'employé
 * peut redemander au client puis renvoyer.
 */
export function choixClientVerrouilles(etat: EtatVerrouillageChoixClient): boolean {
  const enFile = etat.statutMutationCompletion !== null && etat.statutMutationCompletion !== "echec_permanent";
  return etat.enTraitement || etat.completionEnvoyee || enFile;
}
