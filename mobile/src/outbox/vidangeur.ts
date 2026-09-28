import { marquerEchecPermanent, marquerEchecReessayable, marquerEnvoi, marquerEnvoyee } from "./mutation";
import { identifierMutationsBloqueesParEchecPermanent, selectionnerProchainesEnvoyables } from "./planification";
import type { DepotOutbox } from "./depot";
import type { MutationOutbox, TypeMutation } from "./types";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";

/** Verdict serveur affichable (code + détail) — forme partagée par tout outil qui suit le
 * patron fail-closed `depuis_couple` (`src/opsys/outils.py`, IDEMPOTENCE.md §3.2), pas
 * seulement M4. Voir `src/m4/pointage.ts` pour la lecture spécifique à `m4_pointer`. */
export interface VerdictServeur {
  readonly code: string;
  readonly detail: string;
}

export type InterpretationResultatMetier =
  | { readonly accepte: true; readonly resume: unknown }
  | { readonly accepte: false; readonly verdict: VerdictServeur };

/**
 * Ce qu'un type de mutation doit fournir au vidangeur pour être envoyé : le nom de l'outil réel
 * (`/tools/invoke`, `tool`) et la lecture de sa réponse business (distincte du succès/échec HTTP,
 * déjà classé par `src/protocole/classification.ts` — voir la docstring de
 * `interpreterResultatPointage`, `src/m4/pointage.ts`, pour le pourquoi ce second niveau est
 * nécessaire). Enregistré par type dans `src/outbox/descripteurs.ts`.
 */
export interface DescripteurTypeMutation {
  readonly tool: string;
  readonly interpreterResultat: (resultatBrut: unknown) => InterpretationResultatMetier;
}

export interface ConfigurationVidangeur {
  readonly depot: DepotOutbox;
  readonly descripteurs: ReadonlyMap<TypeMutation, DescripteurTypeMutation>;
  /** Injecté (mission item 5 déjà appliquée par src/protocole/client.ts) : dans les tests, un
   * faux transport ; en production, `invoquerOutil` de src/protocole/client.ts. */
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly urlBase: string;
  readonly jeton: string;
  /** = `opsys/appareil` / `deviceId` (src/protocole/types.ts) — voir la limite documentée dans
   * `src/m4/contextePointageProvisoire.ts` (`genererAppareilIdProvisoire`) tant que T1.4-c
   * n'existe pas. */
  readonly appareilId: string;
  /** Injecté plutôt que lu via `Date.now()` (fonction pure, même principe que `recul.ts` et
   * `selectionnerProchainesEnvoyables`). */
  readonly maintenant: () => Date;
}

/** Un échec permanent, avec le verdict à afficher à l'employé (mission item 2 : « échec
 * définitif avec le verdict du serveur ») — qu'il vienne du classement HTTP
 * (`src/protocole/classification.ts`, ex. 400/403/404) ou d'un rejet business à HTTP 200
 * (`accepte:false`, voir `src/m4/pointage.ts`) : les DEUX sources sont normalisées vers la même
 * forme `{code, detail}` ici, pour que l'écran n'ait qu'une seule forme à afficher. */
export interface EchecMutation {
  readonly id: string;
  readonly verdict: VerdictServeur;
}

/** Une mutation acceptée, avec le `resume` métier renvoyé par son interprète (PLAN T1.4-f,
 * `RapportVidange.resultatsAcceptes` ci-dessous) — `resume` reste `unknown` à ce niveau
 * générique (le vidangeur ne connaît aucun contrat M4/M6 précis, voir `DescripteurTypeMutation`
 * ci-dessus) ; l'appelant (écran) le retype selon le type de mutation qu'il a lui-même soumis. */
export interface MutationAcceptee {
  readonly id: string;
  readonly resume: unknown;
}

export interface RapportVidange {
  readonly envoyees: readonly string[];
  /**
   * Même information que `envoyees`, mais avec le `resume` métier de CHAQUE mutation acceptée
   * (PLAN T1.4-f) — jusqu'ici calculé par `descripteur.interpreterResultat` puis jeté : `job_
   * completion` (« Terminer ») a besoin du WCT renvoyé par `m4_completer_intervention` pour
   * enchaîner `materials_submit` (`m6_declarer_materiaux_utilises` exige le WCT tel quel, voir
   * `src/m4/completion.ts`/`src/m6/materiaux.ts`) — sans ce champ, le seul moyen de le retrouver
   * aurait été un second appel réseau (`m4_lire_outbox` ou équivalent), inutile ET plus fragile
   * (un rejeu ne serait pas garanti de renvoyer exactement le même WCT). Additif, ne change rien
   * au comportement existant : `envoyees` reste inchangé pour tout code déjà écrit contre lui.
   */
  readonly resultatsAcceptes: readonly MutationAcceptee[];
  /** Remises `en_attente` après un échec réessayable (recul appliqué). */
  readonly remisesEnAttente: readonly string[];
  readonly echecsPermanents: readonly EchecMutation[];
  /** `identifierMutationsBloqueesParEchecPermanent`, recalculé APRÈS cette passe (R12 §4 : « ne
   * jamais perdre silencieusement un événement mis en file ») — pour affichage/alerte, jamais
   * utilisé pour décider quoi que ce soit ici (la sélection l'exclut déjà correctement). */
  readonly bloquees: readonly string[];
  /** `true` quand cet appel n'a rien fait car une vidange était déjà en cours (verrou simple,
   * mission item 1) — PAS une erreur : le prochain déclencheur (premier plan, retour réseau)
   * reprendra ce qui reste en file. */
  readonly ignoreeVerrouActif: boolean;
}

const RAPPORT_VERROU_ACTIF: RapportVidange = {
  envoyees: [],
  resultatsAcceptes: [],
  remisesEnAttente: [],
  echecsPermanents: [],
  bloquees: [],
  ignoreeVerrouActif: true,
};

export interface Vidangeur {
  /** Vide la file sortante une fois : sélectionne les mutations envoyables (avec `maintenant`
   * injecté), les envoie dans l'ordre chantier/sequence, et transitionne chacune selon la
   * classification (réseau/HTTP puis, si l'appel a réussi, le verdict business). Ne démarre
   * JAMAIS une deuxième passe concurrente (verrou simple) : voir `RapportVidange.ignoreeVerrouActif`.
   */
  vidangerFileSortante(): Promise<RapportVidange>;
}

type IssueEnvoi =
  | { readonly genre: "envoyee"; readonly resume: unknown }
  | { readonly genre: "remise_en_attente" }
  | { readonly genre: "echec_permanent"; readonly verdict: VerdictServeur };

/** Normalise un échec HTTP/réseau (classification.ts) vers la même forme `{code, detail}`
 * qu'un rejet business — ni l'un ni l'autre n'est privilégié, l'écran affiche l'un ou l'autre
 * de façon identique (voir `EchecMutation`). */
function verdictDepuisEchecHttp(echec: { readonly message: string; readonly erreur?: { readonly type: string; readonly message: string } }): VerdictServeur {
  if (echec.erreur) {
    return { code: echec.erreur.type, detail: echec.erreur.message };
  }
  return { code: "erreur_reseau", detail: echec.message };
}

/**
 * Le « vidangeur » (R12 §4, PLAN T1.4-d item 1) : relie `src/outbox` (logique de file, déjà
 * pure et testée) à `src/protocole` (client `/tools/invoke`, déjà pur et testé) — le seul
 * branchement qui manquait encore (MOBILE.md, « pas de boucle de vidage reliant src/outbox à
 * src/protocole »). Cette fonction elle-même reste pure côté ORCHESTRATION (aucune horloge ni
 * accès réseau en dur, tout est injecté par `ConfigurationVidangeur`) ; c'est l'adaptateur —
 * `src/outbox/service.ts` fournit la configuration réelle (SQLite, `fetch`, déclencheurs).
 */
export function creerVidangeur(config: ConfigurationVidangeur): Vidangeur {
  let vidangeEnCours = false;

  async function envoyerUneMutation(mutation: MutationOutbox): Promise<IssueEnvoi> {
    // Reprise (statut déjà `envoi` retrouvé au démarrage) : ne PAS transitionner à nouveau —
    // `envoi -> envoi` n'existe pas dans le graphe (transitions.ts) — et surtout renvoyer avec
    // LA MÊME mutation (donc la même `id` = idempotencyKey), jamais en la recréant (R12 §4).
    const enEnvoi = mutation.statut === "envoi" ? mutation : marquerEnvoi(mutation);
    if (enEnvoi !== mutation) {
      await config.depot.mettreAJour(enEnvoi);
    }

    const descripteur = config.descripteurs.get(mutation.type);
    if (!descripteur) {
      // Fail-closed délibéré : un type de mutation envoyable sans descripteur enregistré est une
      // erreur de programmation (une tranche future a créé un type sans l'enregistrer dans
      // src/outbox/descripteurs.ts), jamais un cas à deviner silencieusement.
      throw new Error(`aucun descripteur enregistré pour le type de mutation « ${mutation.type} »`);
    }

    const resultatAppel = await config.appelerOutil({
      fetchImpl: config.fetchImpl,
      urlBase: config.urlBase,
      jeton: config.jeton,
      requete: {
        tool: descripteur.tool,
        args: { ...mutation.payload },
        idempotencyKey: mutation.id,
        deviceId: config.appareilId,
        deviceTimestamp: mutation.createdAtLocal,
      },
    });

    if (!resultatAppel.ok) {
      if (resultatAppel.echec.reessayable) {
        await config.depot.mettreAJour(marquerEchecReessayable(enEnvoi, config.maintenant()));
        return { genre: "remise_en_attente" };
      }
      await config.depot.mettreAJour(marquerEchecPermanent(enEnvoi));
      return { genre: "echec_permanent", verdict: verdictDepuisEchecHttp(resultatAppel.echec) };
    }

    const interpretation = descripteur.interpreterResultat(resultatAppel.result);
    if (interpretation.accepte) {
      await config.depot.mettreAJour(marquerEnvoyee(enEnvoi));
      return { genre: "envoyee", resume: interpretation.resume };
    }
    // Rejet métier (HTTP 200, mais `accepte: false`) : définitif — réessayer le MÊME payload ne
    // changerait pas l'issue (fenêtre dépassée, contrat mal formé…). R12 §4 : jamais perdu
    // silencieusement, voir RapportVidange.bloquees pour les descendants.
    await config.depot.mettreAJour(marquerEchecPermanent(enEnvoi));
    return { genre: "echec_permanent", verdict: interpretation.verdict };
  }

  async function vidangerUneFois(): Promise<RapportVidange> {
    const toutes = await config.depot.lister();
    const envoyables = selectionnerProchainesEnvoyables(toutes, config.maintenant());

    const envoyees: string[] = [];
    const resultatsAcceptes: MutationAcceptee[] = [];
    const remisesEnAttente: string[] = [];
    const echecsPermanents: EchecMutation[] = [];

    // Séquentiel, jamais Promise.all : l'ordre chantier/sequence de selectionnerProchainesEnvoyables
    // n'a de sens que si les envois se succèdent, et deux appels concurrents pour la MÊME mutation
    // (reprise) briseraient le verrou simple visé par la mission.
    for (const mutation of envoyables) {
      const issue = await envoyerUneMutation(mutation);
      if (issue.genre === "envoyee") {
        envoyees.push(mutation.id);
        resultatsAcceptes.push({ id: mutation.id, resume: issue.resume });
      } else if (issue.genre === "remise_en_attente") {
        remisesEnAttente.push(mutation.id);
      } else {
        echecsPermanents.push({ id: mutation.id, verdict: issue.verdict });
      }
    }

    const toutesApres = await config.depot.lister();
    const bloquees = identifierMutationsBloqueesParEchecPermanent(toutesApres).map((m) => m.id);

    return { envoyees, resultatsAcceptes, remisesEnAttente, echecsPermanents, bloquees, ignoreeVerrouActif: false };
  }

  return {
    async vidangerFileSortante(): Promise<RapportVidange> {
      if (vidangeEnCours) {
        // Verrou simple (mission item 1) : jamais deux vidanges concurrentes. On ne bloque PAS
        // l'appelant derrière celle déjà en cours — un déclencheur (premier plan, retour réseau)
        // qui arrive pendant une vidange active est absorbé, pas empilé ; le prochain déclencheur
        // reprendra ce qu'il reste à envoyer (rien n'est perdu, tout reste en file).
        return RAPPORT_VERROU_ACTIF;
      }
      vidangeEnCours = true;
      try {
        return await vidangerUneFois();
      } finally {
        vidangeEnCours = false;
      }
    },
  };
}
