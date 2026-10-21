/**
 * Contrat mobile de l'outil `m4_pointer` (M4.4 — PLAN T1.4-d).
 *
 * Lecture SEULE du schéma de paramètres et des verdicts de
 * `departments/m04-field-ops/src/m4_field_ops/outils.py` (closure `pointer`, lignes 131-140,
 * et l'entrée `Outil(nom="m4_pointer", ...)`, lignes 315-338) et de
 * `departments/m04-field-ops/src/m4_field_ops/pointage.py` (`enregistrer_pointage`,
 * `ACTIONS`) — jamais exécuté ici (ADR-0008, le bac à sable ne construit/teste que `core/`,
 * pas les départements Python, mais la même règle d'esprit s'applique : on lit, on ne modifie
 * ni n'exécute `departments/`).
 *
 * Les clés des interfaces `*M4` ci-dessous sont en snake_case et suivent LITTÉRALEMENT le JSON
 * Schema serveur (`additionalProperties: false`, tous les champs `required`) — comme
 * `depot.sqlite.ts` mappe les colonnes SQL 1:1 avant de les traduire en `MutationOutbox`
 * camelCase, ce module est la frontière de traduction entre le contrat outil (snake_case) et
 * le reste de l'app mobile (camelCase). Ne JAMAIS ajouter un champ ici sans le retrouver dans
 * `outils.py` : un champ en trop ferait échouer `additionalProperties: false` côté serveur.
 */

/** `pointage.ACTIONS` — catalogue fermé, jamais une valeur inventée côté mobile. */
export type ActionPointageM4 = "arrivee" | "depart" | "pause_debut" | "pause_fin";

export interface FixGpsM4 {
  readonly latitude: number;
  readonly longitude: number;
}

/**
 * `outils.py`, `_ATTESTATION` : « {fictif: true, appareil_id} — mode ombre uniquement. »
 * `pointage.py` (étape 8) refuse tout `fictif` autre que `true` : l'outil, TEL QU'IL EXISTE
 * AUJOURD'HUI, ne sert que le mode ombre — ce n'est pas une donnée inventée par ce client, c'est
 * la seule forme que le serveur accepte en ce moment.
 */
export interface AttestationPointageM4 {
  readonly fictif: true;
  readonly appareil_id: string;
}

/** `_FENETRE` : « {debut, fin} ISO-8601 avec fuseau. » */
export interface FenetreTravailM4 {
  readonly debut: string;
  readonly fin: string;
}

export interface EntreeReferentielVilleM4 {
  readonly latitude: number;
  readonly longitude: number;
  readonly rayon_km: number;
}

/** `_REFERENTIEL_VILLES` : « {ville_tokenisee: {latitude, longitude, rayon_km}}. » La clé est le
 * jeton produit côté serveur par `cedule.tokeniser_ville(sel, ville)` — le client ne le
 * recalcule jamais, il transmet le référentiel tel qu'il lui a été fourni. */
export type ReferentielVillesM4 = Readonly<Record<string, EntreeReferentielVilleM4>>;

/**
 * Args exacts attendus par `m4_pointer` (voir l'en-tête de fichier). `intervention_id`
 * correspond, côté file sortante, à `MutationOutbox.chantierId` (vocabulaire générique de
 * `src/outbox` ; M4 nomme sa propre entité « intervention »).
 */
export interface ArgumentsM4Pointer {
  readonly intervention_id: string;
  readonly technicien_id: string;
  readonly action: ActionPointageM4;
  readonly horodatage: string;
  readonly fix_gps: FixGpsM4;
  readonly attestation: AttestationPointageM4;
  readonly fenetre_travail: FenetreTravailM4;
  readonly referentiel_villes: ReferentielVillesM4;
  readonly ville: string;
  readonly sel: string;
}

/**
 * Champs de `m4_pointer` que rien, dans l'app mobile actuelle, ne peut encore fournir avec des
 * données réelles :
 *  - `fixGps` : capture GPS hors périmètre de cette tranche — R12 §6, la lecture « fenêtre
 *    bornée = compatible Loi 25 » n'est pas encore confirmée par Nathan/juriste, et
 *    `expo-location` n'est volontairement pas installé (MOBILE.md, « volontairement pas encore
 *    installés ») ;
 *  - `fenetreTravail`/`referentielVilles`/`ville`/`sel` : aucune route serveur n'expose encore
 *    ces données au mobile (pas de `today.tsx`, pas d'appairage T1.4-c pour les demander avec
 *    autorité) ;
 * `technicienId`/`interventionId` ne sont PAS dans ce contexte : `interventionId` est saisi ou
 * connu de l'écran, `technicienId` est la personne que le serveur a confirmée pour l'appareil
 * (`src/identite/`, PLAN T1.4-c5) — paramètres explicites de `construireArgumentsPointer`
 * ci-dessous, jamais une valeur par défaut cachée dans ce contexte.
 *
 * `punch.tsx` fournit ce contexte pour l'instant depuis une seule source PROVISOIRE et
 * clairement nommée (`src/m4/contextePointageProvisoire.ts`), jamais une valeur inventée
 * présentée comme réelle : exactement le même esprit que `attestation.fictif` ci-dessus, que le
 * serveur lui-même limite au mode ombre. Remplacer ce contexte par de vraies sources (GPS
 * consenti, fenêtre/référentiel serveur) est un travail des tranches suivantes, isolé ici pour
 * n'avoir à changer qu'un seul fichier.
 */
export interface ContextePointageM4 {
  readonly fixGps: FixGpsM4;
  readonly appareilId: string;
  readonly fenetreTravail: FenetreTravailM4;
  readonly referentielVilles: ReferentielVillesM4;
  readonly ville: string;
  readonly sel: string;
}

/**
 * Construit les args EXACTS de `m4_pointer` à partir d'une action employé et d'un contexte
 * (fonction pure — `horodatage`, `interventionId` et `technicienId` sont injectés par
 * l'appelant, jamais lus d'une horloge ou d'un état ici). Le résultat est destiné à devenir tel
 * quel le `payload` de la mutation en file (`src/outbox`) : la mutation reste ainsi
 * auto-suffisante, sans dépendre d'un contexte encore vivant au moment où le vidangeur
 * l'enverra, potentiellement après un redémarrage de l'app (R12 §4, reprise).
 */
export function construireArgumentsPointer(
  interventionId: string,
  technicienId: string,
  action: ActionPointageM4,
  horodatage: string,
  contexte: ContextePointageM4,
): ArgumentsM4Pointer {
  return {
    intervention_id: interventionId,
    technicien_id: technicienId,
    action,
    horodatage,
    fix_gps: contexte.fixGps,
    attestation: { fictif: true, appareil_id: contexte.appareilId },
    fenetre_travail: contexte.fenetreTravail,
    referentiel_villes: contexte.referentielVilles,
    ville: contexte.ville,
    sel: contexte.sel,
  };
}

/** Verdict de rejet M4 (`verdicts.construire_verdict`, `departments/.../verdicts.py`) —
 * `statut` existe côté serveur mais reste vide pour un rejet (voir `pointage.py`), on ne
 * l'expose donc pas ici : seuls `code`/`detail` sont utiles à l'affichage. */
export interface VerdictServeurM4 {
  readonly code: string;
  readonly detail: string;
}

/** Accusé de succès (`pointage.py`, étape 15) — ce que le serveur renvoie quand le pointage est
 * accepté, cohérent GPS ou non (`gpsCoherent: false` route vers `en_revue` mais N'EST PAS un
 * rejet, voir docstring de `interpreterResultatPointage`). */
export interface AccusePointageM4 {
  readonly intervention_id: string;
  readonly technicien_id: string;
  readonly action: string;
  readonly horodatage: string;
  readonly ligne_id: string;
  readonly gps_coherent: boolean;
  readonly statut: string;
  readonly demande_id: string | null;
}

export type InterpretationPointage =
  | { readonly accepte: true; readonly accuse: AccusePointageM4 | null }
  | { readonly accepte: false; readonly verdict: VerdictServeurM4 };

function estObjet(valeur: unknown): valeur is Record<string, unknown> {
  return typeof valeur === "object" && valeur !== null;
}

function texteOu(valeur: unknown, repli: string): string {
  return typeof valeur === "string" ? valeur : repli;
}

/**
 * Interprète la réponse BUSINESS de `m4_pointer` — distincte du succès/échec HTTP de
 * `/tools/invoke`, déjà classé par `src/protocole/classification.ts`. Un appel peut recevoir un
 * HTTP 200 `ok:true` et être malgré tout un REJET métier définitif (fenêtre de travail dépassée,
 * assignation incohérente, contrat mal formé…) : `pointage.enregistrer_pointage` renvoie
 * `(None, verdict)` dans ce cas, traduit par `opsys.outils.depuis_couple`
 * (`src/opsys/outils.py`, lu) en `{"accepte": false, "verdict": {...}}`, lui-même le `resultat`
 * de l'enveloppe `{"ok": true, "resultat": {...}, "rejoue": bool}` que
 * `Capacites._appeler_idempotent`/`outils.executer` produit
 * (`docs/architecture/IDEMPOTENCE.md` §3.2 point 3, §6 — exemple exact cité). Sans cette
 * lecture, un rejet métier s'afficherait comme un succès silencieux — contraire à R12 §4
 * (« ne jamais perdre silencieusement un événement mis en file »).
 *
 * Un fix GPS incohérent (`gps_coherent: false`) N'EST PAS un rejet : le pointage est quand même
 * accepté et enregistré, routé en `en_revue` côté serveur (pointage.py, étapes 11-14). Seul
 * `accepte: false` (verdict `REJ-*`) est un échec.
 *
 * `rejoue` (idempotence, IDEMPOTENCE.md §3.2/§6) n'a AUCUNE influence sur cette lecture : un
 * renvoi rejoué porte exactement la même enveloppe `resultat`, donc le même verdict
 * accepté/rejeté — c'est précisément ce qui permet à la file sortante de traiter un rejeu comme
 * un succès ordinaire, sans cas spécial.
 *
 * Lecture défensive, jamais vérifiée contre le fork réel dans ce bac à sable (ADR-0008) : toute
 * forme non reconnue est traitée comme un SUCCÈS sans accusé détaillé plutôt qu'un blocage —
 * le serveur a de toute façon répondu HTTP 200, et un faux « échec » bloquerait à tort une
 * mutation réellement acceptée. À confirmer par le premier test de bout en bout contre un core
 * réel (R12 §5 étape 7, E2E Maestro) ; voir docs/architecture/MOBILE.md.
 */
export function interpreterResultatPointage(resultatBrut: unknown): InterpretationPointage {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : {};

  // `outils.executer` lui-même en échec (arguments_invalides / refus_metier) : ne devrait pas
  // arriver pour m4_pointer, qui ne lève jamais (il renvoie (resultat, verdict)), mais on reste
  // fail-closed plutôt que de crasher sur une forme inattendue.
  if (enveloppe.ok === false) {
    return {
      accepte: false,
      verdict: {
        code: texteOu(enveloppe.erreur, "erreur_inconnue"),
        detail: texteOu(enveloppe.details, ""),
      },
    };
  }

  const resultatMetier = estObjet(enveloppe.resultat) ? enveloppe.resultat : undefined;

  if (resultatMetier?.accepte === false) {
    const verdictBrut = estObjet(resultatMetier.verdict) ? resultatMetier.verdict : {};
    return {
      accepte: false,
      verdict: {
        code: texteOu(verdictBrut.code, "REJ-INCONNU"),
        detail: texteOu(verdictBrut.detail, ""),
      },
    };
  }

  if (resultatMetier?.accepte === true) {
    const accuseBrut = estObjet(resultatMetier.resultat) ? (resultatMetier.resultat as unknown) : null;
    return { accepte: true, accuse: accuseBrut as AccusePointageM4 | null };
  }

  return { accepte: true, accuse: null };
}
