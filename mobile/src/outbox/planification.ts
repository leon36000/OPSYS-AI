import type { MutationOutbox, StatutMutation } from "./types";

/**
 * Statuts éligibles à un envoi immédiat. `envoi` y figure exprès : une ligne retrouvée dans cet
 * état au démarrage n'est pas un échec, c'est une reprise après crash/redémarrage en plein
 * envoi (R12 §4) — elle doit être renvoyée avec le MÊME id (= idempotencyKey), jamais recréée,
 * et SANS attendre son recul (`estDue` ci-dessous la laisse toujours passer).
 * `identifierMutationsAReprendre` ci-dessous isole ce sous-cas pour que l'appelant puisse le
 * tracer séparément (P3, traçabilité), mais la sélection normale l'inclut aussi.
 */
const STATUTS_ENVOYABLES = new Set<StatutMutation>(["en_attente", "envoi"]);

function parentEstEnvoyee(mutation: MutationOutbox, parId: ReadonlyMap<string, MutationOutbox>): boolean {
  if (mutation.dependsOn === null) {
    return true;
  }
  return parId.get(mutation.dependsOn)?.statut === "envoyee";
}

/**
 * Une mutation `en_attente` n'est due que si `prochaineTentativeA` est `null` (jamais encore
 * échouée) ou déjà passé. Une reprise (`envoi`) n'attend jamais son recul : elle a été
 * interrompue par un crash/redémarrage, pas par un échec réseau à espacer.
 */
function estDue(mutation: MutationOutbox, maintenant: Date): boolean {
  if (mutation.statut === "envoi") {
    return true;
  }
  if (mutation.prochaineTentativeA === null) {
    return true;
  }
  return new Date(mutation.prochaineTentativeA).getTime() <= maintenant.getTime();
}

/**
 * Sélectionne, DANS L'ORDRE où elles doivent être envoyées, les mutations actuellement
 * envoyables (R12 §4) :
 *   1. statut `en_attente` ou `envoi` (reprise) ;
 *   2. `en_attente` seulement si due — `prochaineTentativeA` (recul exponentiel,
 *      `src/outbox/recul.ts`) nul ou déjà passé au regard de `maintenant`, injecté par
 *      l'appelant (fonction pure) ;
 *   3. si `dependsOn` est renseigné, la mutation parente doit être `envoyee` — « une mutation
 *      n'est jamais envoyée avant sa parente ‹ envoyée › » ;
 *   4. triées par chantier puis par `sequence` (entier assigné par le dépôt à l'insertion —
 *      FIFO par chantier, robuste au changement d'heure et de fuseau ; `createdAtLocal` ne sert
 *      plus qu'à l'affichage, voir `types.ts`).
 * Fonction pure : ne lit ni n'écrit aucun stockage, prend et retourne des données.
 */
export function selectionnerProchainesEnvoyables(
  mutations: readonly MutationOutbox[],
  maintenant: Date,
): MutationOutbox[] {
  const parId = new Map(mutations.map((m) => [m.id, m] as const));
  return mutations
    .filter((m) => STATUTS_ENVOYABLES.has(m.statut))
    .filter((m) => estDue(m, maintenant))
    .filter((m) => parentEstEnvoyee(m, parId))
    .slice()
    .sort((a, b) => {
      if (a.chantierId !== b.chantierId) {
        return a.chantierId < b.chantierId ? -1 : 1;
      }
      const seqA = a.sequence ?? Number.POSITIVE_INFINITY;
      const seqB = b.sequence ?? Number.POSITIVE_INFINITY;
      return seqA - seqB;
    });
}

/**
 * Sous-ensemble « reprise au démarrage » (statut `envoi` trouvé en base) — isolé pour que
 * l'appelant puisse journaliser cette reprise distinctement (P3) avant de la fondre dans la
 * sélection générale ci-dessus.
 */
export function identifierMutationsAReprendre(mutations: readonly MutationOutbox[]): MutationOutbox[] {
  return mutations.filter((m) => m.statut === "envoi");
}

/**
 * Identifie les mutations `en_attente`/`envoi` dont un ANCÊTRE — pas seulement le parent direct
 * — est en `echec_permanent`. Sans cette fonction, un descendant d'une mutation en échec
 * permanent reste `en_attente` pour toujours : `selectionnerProchainesEnvoyables` l'exclut déjà
 * correctement (sa parente n'est jamais `envoyee`), mais SILENCIEUSEMENT — R12 §4 : « ne jamais
 * perdre silencieusement un événement mis en file ». L'app doit pouvoir montrer ces mutations
 * (alerte, écran de diagnostic), pas seulement les laisser attendre. Relevé en relecture après
 * PLAN T1.4-a.
 *
 * Remonte toute la chaîne `dependsOn` (récursif, garde anti-cycle défensive) : un enfant dont le
 * PARENT DIRECT est encore `en_attente` (pas lui-même en échec) mais dont le GRAND-PARENT est en
 * `echec_permanent` est quand même bloqué, et doit être signalé.
 */
export function identifierMutationsBloqueesParEchecPermanent(
  mutations: readonly MutationOutbox[],
): MutationOutbox[] {
  const parId = new Map(mutations.map((m) => [m.id, m] as const));

  function ancetreEnEchecPermanent(mutation: MutationOutbox, visites: ReadonlySet<string>): boolean {
    if (mutation.dependsOn === null) {
      return false;
    }
    if (visites.has(mutation.dependsOn)) {
      return false; // cycle défensif : jamais bouclé indéfiniment (ne devrait pas arriver)
    }
    const parent = parId.get(mutation.dependsOn);
    if (!parent) {
      return false; // parente pas (encore) chargée : pas à cette fonction de le déclarer bloqué
    }
    if (parent.statut === "echec_permanent") {
      return true;
    }
    return ancetreEnEchecPermanent(parent, new Set([...visites, mutation.dependsOn]));
  }

  return mutations.filter(
    (m) => (m.statut === "en_attente" || m.statut === "envoi") && ancetreEnEchecPermanent(m, new Set()),
  );
}
