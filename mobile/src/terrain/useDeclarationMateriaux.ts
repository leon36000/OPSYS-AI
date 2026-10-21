import { useCallback, useEffect, useRef, useState } from "react";
import { useFocusEffect } from "expo-router";
import * as Crypto from "expo-crypto";
import { useSessionAppareil } from "../roles/contexte";
import { capturerSessionMateriauxLecture } from "../protocole/configuration";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { lireWctIdCompletion } from "../m4/wctIdCompletion";
import { estAccuseCompletionM4 } from "../m4/completion";
import { evaluerPreparationFormulaire } from "../ecrans/materials";
import type { LigneEnSaisie } from "../ecrans/materials";
import { construireArgumentsDeclarerMateriauxUtilises, validerRecuDeclarerMateriauxUtilises } from "../m6/materiaux";
import { validerRecuMateriauxAvecPreuves } from "../m6/materiauxAvecPreuves";
import { figerPreuvesMateriaux, listerCapturesPreuves } from "./preuvesMateriaux";
import type { CapturePreuve, PreuveEnSaisie } from "./preuvesMateriaux";
import type { ContexteMateriauxM6 } from "../m6/contexteMateriaux";
import type { MutationOutbox } from "../outbox/types";
import { creerMutation, soumettreMutation } from "../outbox/mutation";
import { genererMutationId } from "../outbox/id";
import { obtenirDepot, declencherVidange } from "../outbox/service";
import { obtenirDepotLocal } from "../stockage/service";
import { lireBrouillonMateriaux, sauverBrouillonMateriaux } from "./brouillonMateriaux";
import type { BrouillonMateriaux, CibleBrouillonMateriaux } from "./brouillonMateriaux";
import { appliquerPagePrevue } from "./prefillMateriaux";
import { chargerContexteMateriaux, actualiserConnectiviteContexteMateriaux } from "./contexteMateriaux";

const vide = (): BrouillonMateriaux => ({ wctId:null, chantierId:null, sourcePrevu:null, positionsImportees:[], intentionId:null, lignes:[] });
function wctMutation(m: MutationOutbox): string | null {
  const p = copierJsonLecture(m.payload);
  return p !== JSON_LECTURE_INVALIDE && p !== null && typeof p === "object" && !Array.isArray(p) && typeof p.wct_id === "string" ? p.wct_id : null;
}
function recuValide(m:MutationOutbox){return m.type==="materials_submit_with_proofs"?validerRecuMateriauxAvecPreuves(m):validerRecuDeclarerMateriauxUtilises(m);}
/** Même objet physique : un ancien propriétaire/inconnu ne libère pas une intention incertaine. */
function retrouver(mutations: readonly MutationOutbox[], intervention: string, wct: string | null, id: string | null, personne: string) {
  const memes = mutations.filter(m => (m.type === "materials_submit" || m.type === "materials_submit_with_proofs") && m.chantierId === intervention).sort((a,b)=>(a.sequence??0)-(b.sequence??0));
  return memes.find(m => m.statut !== "echec_permanent" && (m.statut !== "envoyee" || !recuValide(m)))
    ?? memes.find(m => m.id === id && m.proprietaire === personne)
    ?? memes.find(m => m.proprietaire === personne && wctMutation(m) === wct) ?? null;
}
/** Orchestration locale de la vraie route. Aucun DTO courant n'est écrit dans le brouillon. */
export function useDeclarationMateriaux(interventionId: string, enLigne: boolean) {
  const profil = useSessionAppareil();
  const captureRendu = capturerSessionMateriauxLecture(), session = captureRendu.session;
  const autorite = session ? JSON.stringify([session.urlBase,session.appareilId,session.personne,session.jeton,profil]) : "";
  const epoch = useRef(0), active = useRef(false), edition = useRef(0), requete = useRef(0), verrou = useRef(false);
  const reseau = useRef({ valeur:enLigne, generation:0 });
  if (reseau.current.valeur !== enLigne) { reseau.current = { valeur:enLigne,generation:reseau.current.generation+1 }; }
  actualiserConnectiviteContexteMateriaux(enLigne);
  const [brouillon,setBrouillon] = useState<BrouillonMateriaux>(vide), ref = useRef(brouillon);
  const [charge,setCharge] = useState(false), [wctLecture,setWctLecture] = useState<string|null>(null);
  const [stockage,setStockage] = useState<"illisible"|"echec"|null>(null), [avis,setAvis] = useState<string|null>(null), [detailAvis,setDetailAvis] = useState("");
  const [traitement,setTraitement] = useState(false), [chargementContexte,setChargementContexte] = useState(false);
  const [captures,setCaptures] = useState<readonly CapturePreuve[]>([]);
  const [intention,setIntention] = useState<MutationOutbox|null>(null), [lectureRefusee,setLectureRefusee] = useState(false);
  const [reponse,setReponse] = useState<{ valeur:ContexteMateriauxM6; courante:()=>boolean }|null>(null);
  const cibleRef = useRef<CibleBrouillonMateriaux|null>(null), sale = useRef(false);
  // Refus de cette lecture, RAM seulement : le focus ne rétablit aucune permission.
  const refusRef = useRef<{cle:string;code:string;detail:string}|null>(null);
  const cleAutorite = JSON.stringify([autorite,interventionId]);
  const generationRendu = epoch.current, numeroRendu=requete.current, reseauRendu=reseau.current.generation;
  const courante = () => active.current && generationRendu === epoch.current && captureRendu.courante();
  const actionCourante = () => courante() && numeroRendu===requete.current && reseauRendu===reseau.current.generation;
  const courantContexte = enLigne && reponse?.courante() ? reponse.valeur : null;
  const montrer = courante();
  const verrouille = lectureRefusee || verrou.current || brouillon.intentionId !== null || intention !== null || stockage === "illisible";

  useFocusEffect(useCallback(() => {
    const generation = ++epoch.current; active.current=true; requete.current++;
    const capture = capturerSessionMateriauxLecture(), s = capture.session;
    const valide = () => active.current && generation === epoch.current && capture.courante();
    const refuse=refusRef.current?.cle===cleAutorite ? refusRef.current : null;
    verrou.current=false; setTraitement(false); setChargementContexte(false); setReponse(null); setCharge(false); setAvis(refuse?.code??null);setDetailAvis(refuse?.detail??""); setIntention(null); setCaptures([]); setLectureRefusee(refuse!==null); setStockage(null);
    if (!s || !interventionId) return () => {active.current=false; epoch.current++;};
    const cible: CibleBrouillonMateriaux = { urlBase:s.urlBase, appareilId:s.appareilId, personne:s.personne, interventionId };
    if (JSON.stringify(cibleRef.current) !== JSON.stringify(cible)) { ref.current=vide(); setBrouillon(ref.current); sale.current=false; edition.current++; }
    cibleRef.current=cible;
    const version = edition.current;
    void (async()=>{
      try {
        const kv = await obtenirDepotLocal(); if(!valide())return;
        const wct = await lireWctIdCompletion(kv,interventionId); if(!valide())return;
        const lu = await lireBrouillonMateriaux(kv,cible); if(!valide())return;
        const depot = await obtenirDepot(); if(!valide())return;
        const mutations = await depot.lister(); if(!valide())return;
        if (version===edition.current && !sale.current) {
          if(lu.genre==="present") { ref.current=lu.valeur; setBrouillon(lu.valeur); }
          if(lu.genre==="illisible")setStockage("illisible");
        }
        const m= retrouver(mutations,interventionId,ref.current.wctId??wct,ref.current.intentionId,s.personne);
        setIntention(m); setCaptures(listerCapturesPreuves(mutations,s.personne,interventionId)); setWctLecture(wct); setCharge(true);
      } catch { if(valide()){setStockage("illisible");setCharge(true);} }
    })();
    return () => {active.current=false; epoch.current++; requete.current++;};
  },[interventionId,autorite]));

  useEffect(()=>{requete.current++;setReponse(null);setChargementContexte(false);},[enLigne]);

  async function persister(d: BrouillonMateriaux, valide:()=>boolean=courante) {
    const cible=cibleRef.current; if(!cible || !valide())return;
    try { const kv=await obtenirDepotLocal(); if(!valide())return; await sauverBrouillonMateriaux(kv,cible,d); if(valide())setStockage(null); }
    catch { if(valide())setStockage("echec"); }
  }
  function changer(d:BrouillonMateriaux) {
    if(!actionCourante() || !charge || verrouille || ref.current.intentionId!==null || verrou.current)return;
    edition.current++; requete.current++; sale.current=true; ref.current=d; setBrouillon(d); setAvis(null);setDetailAvis("");
    setChargementContexte(false); void persister(d);
  }
  async function charger(decalage=0) {
    if(!actionCourante() || !charge || !wctLecture || !enLigne)return;
    const numero=++requete.current, version=edition.current, r=reseau.current.generation;
    const valide=()=>courante() && r===reseau.current.generation && reseau.current.valeur && numero===requete.current && version===edition.current;
    setChargementContexte(true);setReponse(null);setAvis(null);setDetailAvis("");
    try {
      const lu=await chargerContexteMateriaux(interventionId,wctLecture,decalage);
      if(!valide())return;
      if(lu.source==="serveur"){refusRef.current=null;setLectureRefusee(false);setReponse({valeur:lu.valeur,courante:()=>courante() && r===reseau.current.generation && reseau.current.valeur});}
      else { const v=lu.source==="refus" ? lu.verdict : lu.raison;if(lu.source==="refus"){refusRef.current={cle:cleAutorite,code:v.code,detail:v.detail};setLectureRefusee(true);}setAvis(v.code);setDetailAvis(v.detail); }
    } catch {if(valide())setAvis("lecture_indisponible");}
    finally {if(valide())setChargementContexte(false);}
  }
  function adopterCible() {
    const c=courantContexte;
    if(!actionCourante()||!c||verrouille)return;
    if(c.chantier.chantier_id===null){setAvis("cible_absente");return;}
    if(ref.current.lignes.length>0 && ((ref.current.wctId!==null && ref.current.wctId!==c.wct.wct_id) || (ref.current.chantierId!==null && ref.current.chantierId!==c.chantier.chantier_id))) {setAvis("cible_changee");return;}
    changer({...ref.current,wctId:c.wct.wct_id,chantierId:c.chantier.chantier_id,...(ref.current.lignes.length===0?{sourcePrevu:null,positionsImportees:[]}: {})});
  }
  function importer() {
    if(!actionCourante()||!courantContexte||verrouille)return;
    const r=appliquerPagePrevue(ref.current,courantContexte,Crypto.randomUUID);
    if(r.ok)changer(r.valeur);else setAvis(r.raison);
  }
  async function rafraichirStatut(vidanger=true) {
    if(!actionCourante())return;
    const r=reseau.current.generation, garde=()=>courante() && r===reseau.current.generation && reseau.current.valeur;
    try {
      const rapport=vidanger&&enLigne ? await declencherVidange(garde) : null; if(!actionCourante())return;
      const refus=rapport?.echecsPermanents.find(e=>e.id===(ref.current.intentionId??intention?.id));
      if(refus){setAvis(refus.verdict.code);setDetailAvis(refus.verdict.detail);}
      const d=await obtenirDepot();if(!actionCourante())return;
      const toutes=await d.lister();if(!actionCourante()||!session)return;
      setIntention(retrouver(toutes,interventionId,ref.current.wctId??wctLecture,ref.current.intentionId,session.personne));
    } catch {if(courante())setStockage("echec");}
  }
  async function soumettre() {
    if(!actionCourante()||!charge||lectureRefusee||verrou.current||stockage==="illisible"||!session)return;
    verrou.current=true;setTraitement(true);setAvis(null);setDetailAvis("");
    try {
      const depot=await obtenirDepot();if(!actionCourante())return;
      const toutes=await depot.lister();if(!actionCourante())return;
      const d=ref.current, existante=retrouver(toutes,interventionId,d.wctId??wctLecture,d.intentionId,session.personne);
      if(existante || d.intentionId!==null){setIntention(existante);setAvis("intention_en_attente");return;}
      if(!d.wctId||!d.chantierId || (wctLecture!==null && wctLecture!==d.wctId)){setAvis("cible_absente");return;}
      if(courantContexte && (courantContexte.wct.wct_id!==d.wctId || courantContexte.chantier.chantier_id!==d.chantierId)){setAvis("cible_changee");return;}
      const etat=evaluerPreparationFormulaire(d.wctId,interventionId,d.chantierId,d.lignes);
      if(!etat.pret){setAvis(etat.raison);return;}
      const avecPreuves=d.lignes.some(l=>l.typeLigne==="perte"||l.typeLigne==="bris");
      let payload:Readonly<Record<string,unknown>>;
      if(avecPreuves){
        if(d.lignes.some(l=>l.typeLigne==="achat_terrain")){setAvis("achat_terrain_hors_preuves");return;}
        try {const f=figerPreuvesMateriaux(d.lignes,etat.formulaire,d.preuves??[],listerCapturesPreuves(toutes,session.personne,interventionId));payload={...f.args,_fichiers_locaux:f.fichiers};}
        catch(e){setAvis(e instanceof Error && ["preuve_manquante","capture_indisponible","preuves_invalides"].includes(e.message)?e.message:"preuves_invalides");return;}
      } else payload={...construireArgumentsDeclarerMateriauxUtilises(etat.formulaire)};
      const maintenant=new Date();
      const completion=toutes.find(m=>m.type==="job_completion"&&m.chantierId===interventionId&&m.proprietaire===session.personne&&m.statut==="envoyee"&&estAccuseCompletionM4(m.resumeAccepte)&&m.resumeAccepte.wct_id===d.wctId);
      const m=soumettreMutation(creerMutation({type:avecPreuves?"materials_submit_with_proofs":"materials_submit",chantierId:interventionId,payload,dependsOn:completion?.id??null},genererMutationId,{maintenant,decalageMinutesUTC:-maintenant.getTimezoneOffset()}));
      const reserve={...d,intentionId:m.id};ref.current=reserve;setBrouillon(reserve);sale.current=true;
      // L'outbox est la seconde preuve durable si sauver le brouillon échoue.
      try {const inseree=await depot.inserer({...m,proprietaire:session.personne});if(courante())setIntention(inseree);}
      finally {await persister(reserve);}
      if(!courante())return;
      await rafraichirStatut();
    } catch {if(courante())setStockage("echec");}
    finally {if(generationRendu===epoch.current){verrou.current=false;if(courante())setTraitement(false);}}
  }
  const confirme=montrer && intention?.proprietaire===session?.personne && intention?.statut==="envoyee" && recuValide(intention);
  return { charge:montrer&&charge, wctLecture:montrer?wctLecture:null, brouillon:montrer?brouillon:vide(), contexte:montrer?courantContexte:null,
    stockage:montrer?stockage:null, avis:montrer?avis:null, detailAvis:montrer?detailAvis:"", enQuarantaine:montrer&&intention!==null&&intention.proprietaire!==session?.personne, traitement, chargementContexte, autorisee:montrer, verrouille:!montrer||!charge||verrouille,
    intention:montrer?intention:null, confirme, captures:montrer?captures:[],
    changerPreuve:(ligneId:string,patch:Partial<Pick<PreuveEnSaisie,"note"|"captureIds">>)=>{
      if(!ref.current.lignes.some(l=>l.id===ligneId))return;
      const existante=(ref.current.preuves??[]).find(p=>p.ligneId===ligneId)??{ligneId,note:"",captureIds:[]};
      changer({...ref.current,preuves:[...(ref.current.preuves??[]).filter(p=>p.ligneId!==ligneId),{...existante,...patch}]});
    }, changerLignes:(miseAJour:readonly LigneEnSaisie[]|((lignes:readonly LigneEnSaisie[])=>readonly LigneEnSaisie[]))=>changer({...ref.current,lignes:typeof miseAJour==="function"?miseAJour(ref.current.lignes):miseAJour}),
    charger, adopterCible, importer, soumettre, rafraichirStatut, sauver:()=>persister(ref.current) };
}
