/**
 * Contrat mobile de `m6_declarer_materiaux_utilises` (M6.10, PLAN T1.4-f, DEFINITION-PRODUIT.md
 * §9.3/§9.7 étape 3 ; PLAN T1.4-i pour l'origine du WCT).
 *
 * Lecture SEULE de `departments/m06-material-control/src/m6_material_control/outils.py`
 * (fonction `declarer_materiaux_utilises` et l'entrée `Outil` correspondante, schémas
 * `_WCT_ID`/`_FORMULAIRE_MATERIAUX_UTILISES`/`_LIGNE_DECLAREE_CHANTIER`) et de
 * `materiel.py::soumettre_materiaux_utilises` (pour les codes `REJ-*` cités dans sa docstring) —
 * jamais exécuté ni modifié ici (ADR-0008), même discipline que `src/m4/pointage.ts`.
 *
 * **Le mobile n'envoie que le `wct_id`, jamais le WCT (PLAN T1.4-i).** Avant T1.4-i, l'outil
 * exigeait le WCT complet (12 clés) de l'APPELANT et M6 n'en vérifiait que la forme : un appareil
 * pouvait fabriquer un WCT et rattacher des matériaux à un chantier qui n'existe pas, et l'app
 * relisait `m4_lire_outbox` pour en garder une copie. Désormais l'outil prend `wct_id` (celui de
 * l'accusé de `m4_completer_intervention`, `src/m4/completion.ts`) et le formulaire ; M6 relit
 * lui-même la charge `m4.travaux_termines` publiée par M4 pour cet identifiant. Un `wct_id` que M4
 * n'a jamais publié est refusé (`REJ-WCT-INCONNU`, affiché TEL QUEL par `materials.tsx`) sans rien
 * écrire. Ce module ne connaît donc plus rien de la forme du WCT (AGENTS.md : un fait vient de sa
 * source de vérité, jamais de l'appelant).
 *
 * **Aucune liste « prévue » (M3/M6) pré-remplie — décision documentée, pas un oubli.** Le contrat
 * fixe donné pour cette tranche ne couvre QUE `m4_deposer_fichier`/`m4_etat_fichier` ; aucune
 * route de lecture des besoins estimés (`besoins_prevus`, lu dans `outils.py` pour
 * `m6_creer_po_brouillon` mais jamais exposée à ce module) n'a été confirmée. Mission (item 3) :
 * « Aucune quantité ni aucun prix proposés par défaut : l'employé saisit, le serveur calcule » —
 * cohérent avec l'absence de pré-remplissage : l'employé compose chaque ligne à la main
 * (`src/ecrans/materials.ts`, `materials.tsx`). Voir MOBILE.md pour le détail de cet écart.
 */

/** `_LIGNE_DECLAREE_CHANTIER.type_ligne.enum` — catalogue fermé, jamais une valeur inventée. */
export type TypeLigneMateriaux = "prevu" | "non_prevu" | "retour" | "perte" | "bris" | "achat_terrain";

export const TYPES_LIGNE_MATERIAUX: readonly TypeLigneMateriaux[] = [
  "prevu",
  "non_prevu",
  "retour",
  "perte",
  "bris",
  "achat_terrain",
];

/**
 * Une ligne du formulaire (`_LIGNE_DECLAREE_CHANTIER`). `quantite_estimee` « en plus si prevu » ;
 * `photo_fournie`/`recu_fourni` « en plus si achat_terrain » (contrat, docstring de
 * `_LIGNE_DECLAREE_CHANTIER`) — ce module ne les inclut donc que pour le `type_ligne` concerné
 * (voir `construireLigneDeclaree`), jamais une clé étrangère envoyée par prudence.
 */
export interface LigneDeclareeChantierM6 {
  readonly type_ligne: TypeLigneMateriaux;
  readonly materiau_id: string;
  readonly quantite: number;
  readonly unite: string;
  readonly quantite_estimee?: number;
  readonly photo_fournie?: boolean;
  readonly recu_fourni?: boolean;
}

export interface FormulaireMateriauxUtilisesM6 {
  readonly wct_id: string;
  readonly intervention_id: string;
  readonly chantier_id: string;
  readonly lignes_materiaux: readonly LigneDeclareeChantierM6[];
}

/** Args exacts de `m6_declarer_materiaux_utilises` : `wct_id` et `formulaire`, rien d'autre (le
 * schéma de l'outil est fermé, `additionalProperties: false`). `wct_id` est TOUJOURS celui du
 * formulaire : une seule source, jamais deux valeurs qui pourraient diverger (le serveur refuse
 * de toute façon un formulaire dont le `wct_id` diffère, `REJ-FORMULAIRE-MATERIAUX-WCT-INCOHERENT`). */
export interface ArgumentsM6DeclarerMateriauxUtilises {
  readonly wct_id: string;
  readonly formulaire: FormulaireMateriauxUtilisesM6;
}

export function construireArgumentsDeclarerMateriauxUtilises(
  formulaire: FormulaireMateriauxUtilisesM6,
): ArgumentsM6DeclarerMateriauxUtilises {
  return { wct_id: formulaire.wct_id, formulaire };
}

export interface VerdictServeurMateriaux {
  readonly code: string;
  readonly detail: string;
}

export type InterpretationDeclarerMateriauxUtilises =
  | { readonly accepte: true; readonly resultat: unknown }
  | { readonly accepte: false; readonly verdict: VerdictServeurMateriaux };

function estObjet(valeur: unknown): valeur is Record<string, unknown> {
  return typeof valeur === "object" && valeur !== null;
}

function texteOu(valeur: unknown, repli: string): string {
  return typeof valeur === "string" ? valeur : repli;
}

function verdictDepuisErreurTechnique(enveloppe: Record<string, unknown>): VerdictServeurMateriaux {
  return { code: texteOu(enveloppe.erreur, "erreur_inconnue"), detail: texteOu(enveloppe.details, "") };
}

/**
 * Interprète la réponse BUSINESS de `m6_declarer_materiaux_utilises` — même patron défensif que
 * `interpreterResultatPointage`. **Différence de forme confirmée en lisant `outils.py`
 * (`declarer_materiaux_utilises`) : le verdict de refus ne porte que `{"code": code}`,
 * JAMAIS de `detail`** (contrairement à `verdicts.construire_verdict` utilisé par M4) — `detail`
 * est donc TOUJOURS lu défensivement (`texteOu(..., "")`) ici, une chaîne vide n'étant pas une
 * erreur de lecture mais la forme réelle et attendue de cette réponse précise. Les codes `REJ-*`
 * cités par `materiel.soumettre_materiaux_utilises` (`REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE`,
 * `REJ-DECLARATION-DEJA-SOUMISE`, `REJ-COUT-UNITAIRE-INTROUVABLE`, `REJ-WCT-INCONNU` (T1.4-i), et ceux de
 * `validation.valider_wct`/`valider_formulaire_materiaux_utilises`, non lus ici) sont affichés
 * TEL QUELS par `materials.tsx`, jamais retraduits en dur dans ce module (même discipline que
 * `complete.tsx`, mission item 2).
 */
export function interpreterResultatDeclarerMateriauxUtilises(resultatBrut: unknown): InterpretationDeclarerMateriauxUtilises {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : {};
  if (enveloppe.ok === false) {
    return { accepte: false, verdict: verdictDepuisErreurTechnique(enveloppe) };
  }
  const resultatMetier = estObjet(enveloppe.resultat) ? enveloppe.resultat : undefined;

  if (resultatMetier?.accepte === false) {
    const v = estObjet(resultatMetier.verdict) ? resultatMetier.verdict : {};
    return { accepte: false, verdict: { code: texteOu(v.code, "REJ-INCONNU"), detail: texteOu(v.detail, "") } };
  }
  if (resultatMetier?.accepte === true) {
    return { accepte: true, resultat: resultatMetier.resultat ?? null };
  }
  return { accepte: true, resultat: null };
}

/**
 * Construit une ligne déclarée — fonction pure, n'inclut `quantite_estimee`/`photo_fournie`/
 * `recu_fourni` QUE lorsque pertinents pour `typeLigne` (voir en-tête). `quantiteEstimee` est
 * ignorée si `typeLigne !== "prevu"` ; `photoFournie`/`recuFourni` sont ignorés si `typeLigne !==
 * "achat_terrain"` — jamais une clé étrangère envoyée par prudence, jamais une clé requise
 * omise par erreur.
 */
export function construireLigneDeclaree(params: {
  readonly typeLigne: TypeLigneMateriaux;
  readonly materiauId: string;
  readonly quantite: number;
  readonly unite: string;
  readonly quantiteEstimee?: number;
  readonly photoFournie?: boolean;
  readonly recuFourni?: boolean;
}): LigneDeclareeChantierM6 {
  const base: LigneDeclareeChantierM6 = {
    type_ligne: params.typeLigne,
    materiau_id: params.materiauId,
    quantite: params.quantite,
    unite: params.unite,
  };
  if (params.typeLigne === "prevu" && params.quantiteEstimee !== undefined) {
    return { ...base, quantite_estimee: params.quantiteEstimee };
  }
  if (params.typeLigne === "achat_terrain") {
    return { ...base, photo_fournie: params.photoFournie === true, recu_fourni: params.recuFourni === true };
  }
  return base;
}

export function construireFormulaireMateriauxUtilises(
  wctId: string,
  interventionId: string,
  chantierId: string,
  lignes: readonly LigneDeclareeChantierM6[],
): FormulaireMateriauxUtilisesM6 {
  return { wct_id: wctId, intervention_id: interventionId, chantier_id: chantierId, lignes_materiaux: [...lignes] };
}
