import type { MutationOutbox } from "../outbox/types";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";

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

function objet(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
function ferme(v: unknown, cles: readonly string[]): v is Record<string, unknown> {
  return objet(v) && Object.keys(v).length === cles.length && cles.every(c => Object.hasOwn(v, c));
}
const texte = (v: unknown): v is string => typeof v === "string" && v.length > 0;
const quantite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v > 0;
const typeLigne = (v: unknown): v is TypeLigneMateriaux => TYPES_LIGNE_MATERIAUX.some(t => t === v);
function ligne(v: unknown): v is LigneDeclareeChantierM6 {
  if (!objet(v) || !typeLigne(v.type_ligne)) return false;
  const cles = ["type_ligne", "materiau_id", "quantite", "unite",
    ...(v.type_ligne === "prevu" ? ["quantite_estimee"] : []),
    ...(v.type_ligne === "achat_terrain" ? ["photo_fournie", "recu_fourni"] : [])];
  return ferme(v, cles) && texte(v.materiau_id) && texte(v.unite) && quantite(v.quantite) &&
    (v.type_ligne !== "prevu" || quantite(v.quantite_estimee)) &&
    (v.type_ligne !== "achat_terrain" || (typeof v.photo_fournie === "boolean" && typeof v.recu_fourni === "boolean" && (v.photo_fournie || v.recu_fourni)));
}
export interface ConfirmationMateriauxUtilisesM6 {
  readonly intervention_id: string;
  readonly chantier_id: string;
  readonly lignes_declarees: readonly LigneDeclareeChantierM6[];
}
function formulaireMutation(v: unknown): FormulaireMateriauxUtilisesM6 | null {
  if (!objet(v) || v.type !== "materials_submit" || !texte(v.proprietaire) ||
    !ferme(v.payload, ["wct_id", "formulaire"]) || !texte(v.payload.wct_id)) return null;
  const f = v.payload.formulaire;
  if (!ferme(f, ["wct_id", "intervention_id", "chantier_id", "lignes_materiaux"]) ||
    !texte(f.wct_id) || f.wct_id !== v.payload.wct_id || !texte(f.intervention_id) || v.chantierId !== f.intervention_id ||
    !texte(f.chantier_id) || !Array.isArray(f.lignes_materiaux) || f.lignes_materiaux.length === 0 || !f.lignes_materiaux.every(ligne)) return null;
  return { wct_id: f.wct_id, intervention_id: f.intervention_id, chantier_id: f.chantier_id, lignes_materiaux: f.lignes_materiaux };
}
function confirmation(v: unknown, f: FormulaireMateriauxUtilisesM6): ConfirmationMateriauxUtilisesM6 | null {
  if (!ferme(v, ["intervention_id", "chantier_id", "lignes_declarees"]) || v.intervention_id !== f.intervention_id ||
    v.chantier_id !== f.chantier_id || !Array.isArray(v.lignes_declarees) || v.lignes_declarees.length !== f.lignes_materiaux.length ||
    !v.lignes_declarees.every(ligne)) return null;
  for (let i = 0; i < v.lignes_declarees.length; i++) {
    const recue = v.lignes_declarees[i], attendue = f.lignes_materiaux[i];
    if (Object.keys(recue).some(k => Reflect.get(recue, k) !== Reflect.get(attendue, k))) return null;
  }
  return { intervention_id: f.intervention_id, chantier_id: f.chantier_id, lignes_declarees: v.lignes_declarees };
}
const INCONNU: InterpretationDeclarerMateriauxUtilises = { accepte: false,
  verdict: { code: "accuse_invalide", detail: "Confirmation des matériaux inconnue ou non liée : intention conservée." } };
const codeRefus = (v: unknown): v is string => typeof v === "string" && /^REJ-[A-Z0-9]+(?:-[A-Z0-9]+)*$/.test(v);
// Ce refus d'identité natif précède toute écriture (_declarant_appareil/acces.acteur_de).
// Il n'est pas une faute irréversible du formulaire ni une autorisation rétablie.
function conserverRefusIdentite(detail: string): InterpretationDeclarerMateriauxUtilises {
  return { accepte: false, verdict: { code: "accuse_invalide", detail: `REJ-IDENTITE-APPAREIL-INVALIDE : ${detail}` } };
}
const ERREURS_REFUS = ["invalid_request", "arguments_invalides", "hors_portee_role", "refus_metier", "outil_introuvable"];
/** Confirmation native de contrats_sortie.py : intervention/chantier/lignes, sans écho WCT,
 * UUID ni personne. Le contexte persistant lie ce tuple aux args et vérifie les deux WCT du
 * payload ; il ne crée aucun champ de preuve absent de la réponse. Toute ambiguïté conserve
 * l'intention (accuse_invalide), jamais un succès null ou un refus permanent inventé. */
export function interpreterResultatDeclarerMateriauxUtilises(
  resultatBrut: unknown, mutation?: MutationOutbox,
): InterpretationDeclarerMateriauxUtilises {
  const r = copierJsonLecture(resultatBrut);
  if (r === JSON_LECTURE_INVALIDE || !objet(r)) return INCONNU;
  const cles = Object.hasOwn(r, "rejoue") ? ["ok", "resultat", "rejoue"] : ["ok", "resultat"];
  if (Object.hasOwn(r, "rejoue") && typeof r.rejoue !== "boolean") return INCONNU;
  if (r.ok === false) {
    if (!ferme(r, ["ok", "erreur", "details"]) || !texte(r.erreur) ||
      !(codeRefus(r.erreur) || ERREURS_REFUS.includes(r.erreur)) || typeof r.details !== "string") return INCONNU;
    return r.erreur === "REJ-IDENTITE-APPAREIL-INVALIDE" ? conserverRefusIdentite(r.details)
      : { accepte: false, verdict: { code: r.erreur, detail: r.details } };
  }
  if (!ferme(r, cles) || r.ok !== true || !objet(r.resultat)) return INCONNU;
  const m = r.resultat;
  if (m.accepte === false) {
    if (!ferme(m, ["accepte", "verdict"]) || !objet(m.verdict)) return INCONNU;
    const vc = Object.hasOwn(m.verdict, "detail") ? ["code", "detail"] : ["code"];
    if (!ferme(m.verdict, vc) || !codeRefus(m.verdict.code) ||
      (Object.hasOwn(m.verdict, "detail") && typeof m.verdict.detail !== "string")) return INCONNU;
    const detail = typeof m.verdict.detail === "string" ? m.verdict.detail : "";
    return m.verdict.code === "REJ-IDENTITE-APPAREIL-INVALIDE" ? conserverRefusIdentite(detail)
      : { accepte: false, verdict: { code: m.verdict.code, detail } };
  }
  if (!ferme(m, ["accepte", "resultat", "registre"]) || m.accepte !== true ||
    !ferme(m.registre, ["taille", "hash_tete"]) || typeof m.registre.taille !== "number" ||
    !Number.isSafeInteger(m.registre.taille) || m.registre.taille < 1 || typeof m.registre.hash_tete !== "string" ||
    !/^[0-9a-f]{64}$/.test(m.registre.hash_tete)) return INCONNU;
  const c = copierJsonLecture(mutation);
  if (c === JSON_LECTURE_INVALIDE) return INCONNU;
  const f = formulaireMutation(c);
  if (!f || m.registre.taille < f.lignes_materiaux.length) return INCONNU;
  const resultat = confirmation(m.resultat, f);
  return resultat ? { accepte: true, resultat } : INCONNU;
}
/** Un ancien statut envoyé ne libère une nouvelle intention que si son reçu persistant
 * possède la vraie forme et correspond exactement au formulaire de cette intention. */
export function validerRecuDeclarerMateriauxUtilises(mutation: MutationOutbox): boolean {
  const c = copierJsonLecture(mutation);
  if (c === JSON_LECTURE_INVALIDE || !objet(c) || c.statut !== "envoyee") return false;
  const f = formulaireMutation(c);
  return f !== null && confirmation(c.resumeAccepte, f) !== null;
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
