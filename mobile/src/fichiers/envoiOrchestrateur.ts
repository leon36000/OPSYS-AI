import { encoderBase64Standard } from "./base64";
import { candidatsPhotosApres, candidatSignature } from "./candidats";
import type { CandidatFichierM4 } from "./candidats";
import { calculerEtatEnvoiFichier } from "./etatEnvoi";
import type { EtatEnvoiFichier } from "./etatEnvoi";
import { construireArgumentsDeposerFichier } from "./protocole";
import type { ResultatEtatFichier, VerdictServeurFichier } from "./protocole";
import { validerTailleFichier, decouperEnBlocs } from "./decoupage";
import { verifierEmpreinteFichier } from "./verification";
import type { FonctionDigestSha256 } from "./empreinte";
import { creerMutation, soumettreMutation } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { DepotOutbox } from "../outbox/depot";
import type { MutationOutbox } from "../outbox/types";

/**
 * Orchestrateur d'ENVOI D'UN FICHIER par la file sortante (mission T1.4-f, item 1). Même
 * discipline que `src/today/orchestrateur.ts`/`src/outbox/vidangeur.ts` : orchestration PURE
 * côté logique (aucun accès fichier/réseau en dur), tout injecté par `ConfigurationEnvoiFichier`
 * — testable de bout en bout avec un dépôt mémoire, un lecteur de fichier factice et un `digest`
 * factice, JAMAIS contre un vrai serveur ni un vrai système de fichiers (mission, cadre de
 * travail). `src/fichiers/service.ts` fournit le câblage réel.
 *
 * Cette fonction ne fait qu'ENFILER les blocs manquants dans la file sortante (`brouillon` ->
 * `en_attente`, via `creerMutation`/`soumettreMutation`, même patron que tout le reste de
 * `src/outbox`) — l'ENVOI proprement dit reste le travail du vidangeur générique
 * (`src/outbox/vidangeur.ts`, via le descripteur `fichier_bloc` de `src/outbox/descripteurs.ts`),
 * jamais dupliqué ici : ce module ne fait jamais lui-même d'appel `/tools/invoke`, à L'EXCEPTION
 * de la lecture DIRECTE (pas par la file, comme `m4_statut_intervention`) de `m4_etat_fichier`
 * pour la REPRISE (voir `obtenirEtatServeur`).
 */
export interface ConfigurationEnvoiFichier {
  readonly depot: DepotOutbox;
  /** Lit les octets RÉELS du fichier local — injecté pour rester testable sans
   * `expo-file-system` (mission : jamais contre un vrai système de fichiers dans les tests). */
  readonly lireOctets: (uri: string) => Promise<Uint8Array<ArrayBuffer>>;
  readonly digest: FonctionDigestSha256;
  readonly genererId: () => string;
  readonly horloge: HorlogeAppareil;
  /**
   * Lecture DIRECTE de `m4_etat_fichier` (comme `m4_statut_intervention`, PAS par la file — c'est
   * une LECTURE, R12 §4) pour la REPRISE (mission item 1 : « reprise par m4_etat_fichier après
   * interruption ») : évite de ré-enfiler des blocs que le serveur a déjà reçus lors d'une
   * tentative précédente dont l'issue locale a été perdue (redémarrage avant que le vidangeur
   * n'ait pu marquer `envoyee`). `null` tant qu'aucune configuration de connexion n'existe
   * (même philosophie que `src/today/service.ts`) — dans ce cas, l'envoi se base SEULEMENT sur
   * l'état LOCAL de la file (jamais bloquant : hors ligne, la file accumule en sécurité et sera
   * rejouée telle quelle par les déclencheurs génériques, `src/outbox/declencheurs.ts`). Un
   * ÉCHEC de cet appel (réseau, technique) n'est PAS non plus bloquant : traité comme « aucune
   * information de reprise disponible », jamais une erreur qui empêcherait l'envoi.
   */
  readonly obtenirEtatServeur: (sha256: string) => Promise<ResultatEtatFichier | null>;
}

export type ResultatPreparationEnvoiFichier =
  | { readonly ok: true; readonly blocsEnfiles: number }
  | { readonly ok: false; readonly raison: "taille_invalide"; readonly verdict: VerdictServeurFichier }
  | { readonly ok: false; readonly raison: "type_non_permis" }
  | { readonly ok: false; readonly raison: "empreinte_discordante"; readonly sha256Capture: string; readonly sha256Relu: string }
  | { readonly ok: false; readonly raison: "echec_permanent" };

/**
 * Prépare/poursuit l'envoi d'UN fichier candidat : vérifie l'empreinte contre les octets RELUS
 * sur disque (fail-closed, mission item 1 — jamais un envoi si le fichier a changé depuis la
 * capture), consulte l'état déjà connu (local + optionnellement serveur) pour ne RÉ-ENFILER que
 * les blocs manquants (idempotent : un appel répété sur un fichier déjà complet/déjà en file ne
 * duplique jamais de blocs), et enfile chaque bloc manquant comme sa PROPRE mutation
 * `fichier_bloc` (sa propre clé d'idempotence = son propre `mutation.id`, comme toute mutation de
 * la file sortante — R12 §4).
 *
 * Ne DÉCLENCHE jamais elle-même de vidange (`declencherVidange`) : ce choix reste à l'appelant
 * (écran), même discipline que `src/photos/service.ts` (capture) vs `job/[id]/index.tsx`
 * (déclenchement) — cette fonction ne fait qu'ENFILER en sécurité, jamais un aller-retour réseau
 * implicite en plus de la lecture optionnelle de `m4_etat_fichier`.
 */
export async function preparerEnvoiFichier(
  config: ConfigurationEnvoiFichier,
  fichier: CandidatFichierM4,
  mutationsExistantes: readonly MutationOutbox[],
): Promise<ResultatPreparationEnvoiFichier> {
  if (fichier.typeMime === null) {
    return { ok: false, raison: "type_non_permis" };
  }

  const verdictTaille = validerTailleFichier(fichier.tailleOctets);
  if (verdictTaille) {
    return { ok: false, raison: "taille_invalide", verdict: verdictTaille };
  }

  const etatLocal = calculerEtatEnvoiFichier(mutationsExistantes, fichier.chantierId, fichier.sha256);
  if (etatLocal.statut === "complet" || etatLocal.statut === "en_cours") {
    // Déjà complet, ou déjà en file avec au moins un bloc en attente/envoi : rien à refaire —
    // idempotent, jamais un doublon de blocs pour la même empreinte.
    return { ok: true, blocsEnfiles: 0 };
  }
  if (etatLocal.statut === "echec_permanent") {
    // Un bloc de CE fichier a déjà été refusé de façon définitive (voir etatEnvoi.ts) : renvoyer
    // les MÊMES octets ne changerait pas l'issue (REJ-* du contrat, tous liés au contenu/aux
    // paramètres, jamais à un aléa réseau). L'appelant (écran) doit dire à l'employé de reprendre
    // la photo/signature — jamais une nouvelle tentative automatique silencieuse ici.
    return { ok: false, raison: "echec_permanent" };
  }

  const octets = await config.lireOctets(fichier.uri);
  const verification = await verifierEmpreinteFichier(octets, fichier.sha256, config.digest);
  if (!verification.ok) {
    return { ok: false, raison: "empreinte_discordante", sha256Capture: verification.sha256Capture, sha256Relu: verification.sha256Relu };
  }

  const etatServeur = await config.obtenirEtatServeur(fichier.sha256).catch(() => null);
  const blocsDejaRecusParLeServeur = new Set<number>(etatServeur?.blocsRecus ?? []);

  const tousLesBlocs = decouperEnBlocs(octets);
  const nombreBlocs = tousLesBlocs.length;

  let blocsEnfiles = 0;
  for (let index = 0; index < tousLesBlocs.length; index += 1) {
    if (blocsDejaRecusParLeServeur.has(index)) {
      continue; // reprise : le serveur a déjà ce bloc, ne jamais le réenvoyer (mission item 1).
    }
    const args = construireArgumentsDeposerFichier(
      fichier.sha256,
      fichier.tailleOctets,
      fichier.typeMime,
      index,
      nombreBlocs,
      encoderBase64Standard(tousLesBlocs[index]),
    );
    const brouillon = creerMutation(
      { type: "fichier_bloc", chantierId: fichier.chantierId, payload: { ...args } },
      config.genererId,
      config.horloge,
    );
    await config.depot.inserer(soumettreMutation(brouillon));
    blocsEnfiles += 1;
  }

  return { ok: true, blocsEnfiles };
}

// Réexportés pour que les écrans/tests n'aient qu'un seul module à importer pour préparer la
// liste des fichiers candidats d'un chantier (photos « après » + signature) avant d'appeler
// `preparerEnvoiFichier` sur chacun.
export { candidatsPhotosApres, candidatSignature };
export type { CandidatFichierM4, EtatEnvoiFichier };
