import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useNetInfo } from "@react-native-community/netinfo";
import * as Crypto from "expo-crypto";
import { useTranslation } from "react-i18next";
import { ajouterLigne, creerLigneVide, modifierLigne, retirerLigne, TYPES_LIGNE_MATERIAUX, validerLigne } from "@/ecrans/materials";
import type { LigneEnSaisie } from "@/ecrans/materials";
import { estimationEnNombreExact } from "@/m6/contexteMateriaux";
import { useDeclarationMateriaux } from "@/terrain/useDeclarationMateriaux";

const RAISONS_LOCALES = ["cible_absente", "cible_changee", "source_changee", "prevu_absent", "prevu_vide", "page_deja_importee", "estimation_non_importable", "trop_de_lignes", "identifiants_invalides", "intention_en_attente", "aucune_ligne", "lignes_invalides", "lecture_indisponible","preuve_manquante","capture_indisponible","preuves_invalides","fichiers_en_attente","achat_terrain_hors_preuves"];

/** Lecture actuelle M4/M3/M6 sans cache ; les seuls éléments persistés sont la saisie et
 * sa cible/provenance. Le WCT mémorisé n'est pas un droit d'accès. */
export default function EcranMateriaux() {
  const router=useRouter();
  const { t } = useTranslation(), { id } = useLocalSearchParams<{id:string}>();
  const interventionId=typeof id==="string"?id:"", enLigne=useNetInfo().isConnected===true;
  const v=useDeclarationMateriaux(interventionId,enLigne), c=v.contexte, d=v.brouillon;
  const desactive=v.verrouille||v.traitement, suivant=c?.pagination.suivant;
  const bouton=(cle:string,action:()=>void,disabled=false)=><Pressable accessibilityLabel={cle} style={styles.boutonSecondaire} disabled={disabled} onPress={action}><Text style={styles.boutonSecondaireTexte}>{t(cle)}</Text></Pressable>;
  return <ScrollView contentContainerStyle={styles.conteneur}>
    <Text style={styles.titre}>{t("materials.titre")}</Text>
    {v.autorisee?<Text style={styles.identifiant}>{interventionId}</Text>:<Text style={styles.erreur}>{t("materials.appareilNonAppaire")}</Text>}
    {v.autorisee&&!v.charge?<ActivityIndicator/>:null}
    <Text>{t("materials.contexte.lectureSeule")}</Text>
    {!enLigne?<Text style={styles.avis}>{t("materials.contexte.horsLigne")}</Text>:null}
    {v.charge&&!v.wctLecture?<Text style={styles.erreur}>{t("materials.aucunWct")}</Text>:null}
    {bouton("materials.contexte.charger",()=>void v.charger(0),!v.autorisee||!v.charge||!v.wctLecture||!enLigne||v.chargementContexte)}
    {v.chargementContexte&&enLigne?<ActivityIndicator/>:null}
    {c?<View style={styles.ligneCarte}>
      <Text>{t("materials.contexte.wct",{valeur:c.wct.wct_id})}</Text>
      <Text>{t("materials.contexte.dateCompletion",{valeur:c.wct.horodatage_completion})}</Text>
      <Text>{t("materials.contexte.hashWct",{valeur:c.wct.hash_maillon})}</Text>
      <Text>{t("materials.contexte.bus",{type:c.wct.reference_bus.type,id:c.wct.reference_bus.evenement_id})}</Text>
      <Text>{c.wct.devis_id===null?t("materials.contexte.devisAbsent"):t("materials.contexte.devis",{valeur:c.wct.devis_id})}</Text>
      <Text>{c.chantier.chantier_id===null?t("materials.contexte.chantierAbsent"):t("materials.contexte.chantier",{valeur:c.chantier.chantier_id})}</Text>
      <Text>{t(`materials.contexte.origine_${c.chantier.origine}`)}</Text>
      <Text>{t(`materials.contexte.statut_${c.prevu.statut}`)}</Text>
      {c.prevu.source?<>
        <Text>{t("materials.contexte.sourcePrevu",{registre:c.prevu.source.registre,rang:c.prevu.source.rang,hash:c.prevu.source.empreinte_snapshot})}</Text>
        <Text>{c.prevu.source.horodatage===null?t("materials.contexte.datePrevuAbsente"):t("materials.contexte.datePrevu",{valeur:c.prevu.source.horodatage})}</Text>
        <Text>{c.prevu.source.reference_m3===null?t("materials.contexte.provenanceAbsente"):t("materials.contexte.sourceM3",{type:c.prevu.source.reference_m3.type,id:c.prevu.source.reference_m3.evenement_id})}</Text>
        {c.prevu.source.estimation_id!==null&&c.prevu.source.rang_m3==null&&c.prevu.source.bareme_version==null?<Text>{t("materials.contexte.estimation",{id:c.prevu.source.estimation_id,rang:c.prevu.source.rang_m3,bareme:c.prevu.source.bareme_version})}</Text>:null}
      </>:null}
      {c.manques.map(m=><Text key={m}>{t(`materials.contexte.manque_${m}`)}</Text>)}
      <Text>{t("materials.contexte.page",{decalage:c.pagination.decalage,affichees:c.pagination.affichees,total:c.pagination.total,reste:c.pagination.reste})}</Text>
      {c.lignes.length===0?<Text>{t(c.prevu.statut==="absent"?"materials.contexte.prevuAbsent":"materials.contexte.pageVide")}</Text>:null}
      {c.lignes.map(l=><View key={l.position_source}>
        <Text>{t("materials.contexte.ligne",{position:l.position_source,materiau:l.materiau_id,quantite:l.quantite_estimee,unite:l.unite})}</Text>
        <Text>{t(`materials.contexte.quantite_${l.origine_quantite}`)}</Text>
        {estimationEnNombreExact(l.quantite_estimee)===null?<Text style={styles.avis}>{t("materials.contexte.nonImportable")}</Text>:null}
      </View>)}
      <Text>{t("materials.contexte.bornes",{taille:c.taille_caracteres,borne:c.borne_caracteres,plafond:c.couverture.plafond_lignes})}</Text>
      {bouton("materials.contexte.adopter",v.adopterCible,desactive||c.chantier.chantier_id===null)}
      {bouton("materials.contexte.importer",v.importer,desactive||c.lignes.length===0)}
      {c.pagination.decalage!==0?bouton("materials.contexte.premiere",()=>void v.charger(0),v.chargementContexte):null}
      {suivant!==undefined&&suivant!==null?bouton("materials.contexte.suivante",()=>void v.charger(suivant),v.chargementContexte):null}
    </View>:null}
    <Text>{t("materials.contexte.reelVide")}</Text>
    {d.wctId?<Text>{t("materials.contexte.cibleBrouillon",{wct:d.wctId,chantier:d.chantierId??t("materials.contexte.chantierAbsent")})}</Text>:null}
    {d.sourcePrevu?<Text>{t("materials.contexte.provenanceBrouillon",{hash:d.sourcePrevu})}</Text>:null}
    {d.lignes.length===0?<Text style={styles.vide}>{t("materials.aucuneLigne")}</Text>:null}
    {d.lignes.map(l=><View key={l.id}><LigneMateriau ligne={l} enTraitement={desactive}
      onChange={patch=>v.changerLignes(ls=>modifierLigne(ls,l.id,patch))} onRetirer={()=>v.changerLignes(ls=>retirerLigne(ls,l.id))}/>
      {(l.typeLigne==="perte"||l.typeLigne==="bris")?<View style={styles.ligneCarte} testID={`preuve-${l.id}`}>
        <Text>{t("materials.preuves.titre")}</Text>
        <TextInput accessibilityLabel={t("materials.preuves.note")} testID={`note-${l.id}`} editable={!desactive}
          multiline value={d.preuves?.find(p=>p.ligneId===l.id)?.note??""}
          onChangeText={note=>v.changerPreuve(l.id,{note})}/>
        <Text>{t("materials.preuves.limites")}</Text>
        {bouton("materials.preuves.ouvrirPhotos",()=>{if(v.autorisee&&!desactive)router.push({pathname:"/(employee)/job/[id]/photos",params:{id:interventionId}});},desactive)}
        {v.captures.map(photo=>{
          const ids=d.preuves?.find(p=>p.ligneId===l.id)?.captureIds??[],selectionnee=ids.includes(photo.capture_id);
          return <View key={photo.capture_id}><Text>{t("materials.preuves.photo",{nature:t(`materials.preuves.nature_${photo.nature}`),taille:photo.taille_octets})}</Text>
            <Pressable testID={`capture-${l.id}-${photo.capture_id}`} disabled={desactive||(!selectionnee&&ids.length>=3)}
              onPress={()=>v.changerPreuve(l.id,{captureIds:selectionnee?ids.filter(id=>id!==photo.capture_id):[...ids,photo.capture_id]})}>
              <Text>{t(selectionnee?"materials.preuves.dissocier":"materials.preuves.associer")}</Text>
            </Pressable></View>;
        })}
        <Text>{(d.preuves?.find(p=>p.ligneId===l.id)?.captureIds.length??0)===0?t("materials.preuves.noteSeule"):t("materials.preuves.selection",{nombre:d.preuves?.find(p=>p.ligneId===l.id)?.captureIds.length??0})}</Text>
      </View>:null}
    </View>)}
    {bouton("materials.ajouterLigne",()=>v.changerLignes(ls=>ajouterLigne(ls,creerLigneVide(Crypto.randomUUID()))),desactive)}
    {v.stockage?<Text style={styles.erreur}>{t(`materials.contexte.stockage_${v.stockage}`)}</Text>:null}
    {v.stockage==="echec"?bouton("materials.contexte.sauver",()=>void v.sauver(),!v.autorisee):null}
    {v.avis?<Text style={styles.avis}>{RAISONS_LOCALES.includes(v.avis)?t(`materials.contexte.raison_${v.avis}`):t("materials.contexte.refus",{code:v.avis})}{v.detailAvis?` — ${v.detailAvis}`:""}</Text>:null}
    {v.enQuarantaine?<Text style={styles.avis}>{t("materials.contexte.quarantaine")}</Text>:null}
    {v.intention?<Text>{t("materials.contexte.intention",{id:v.intention.id,statut:v.intention.statut})}</Text>:d.intentionId?<Text>{t("materials.contexte.intentionInconnue",{id:d.intentionId})}</Text>:null}
    {v.intention&&!v.confirme?<Text>{t(v.intention.statut==="echec_permanent"?"materials.contexte.refusPermanent":"materials.contexte.intentionConservee")}</Text>:null}
    {v.confirme?<Text style={styles.succes}>{t("materials.succes")}</Text>:null}
    {(v.intention||d.intentionId)?bouton("materials.contexte.statut",()=>void v.rafraichirStatut(),!v.autorisee||v.traitement):null}
    <Text>{t("materials.contexte.limitePreuves")}</Text>
    <Pressable accessibilityLabel="materials.bouton" style={styles.bouton} disabled={desactive||!d.wctId||!d.chantierId} onPress={()=>void v.soumettre()}>
      {v.traitement?<ActivityIndicator color="#fff"/>:<Text style={styles.boutonTexte}>{t("materials.bouton")}</Text>}
    </Pressable>
  </ScrollView>;
}

interface ProprietesLigneMateriau {
  readonly ligne: LigneEnSaisie;
  readonly enTraitement: boolean;
  readonly onChange: (patch: Partial<LigneEnSaisie>) => void;
  readonly onRetirer: () => void;
}

/** Un éditeur de ligne — composant local, pas exporté : uniquement le câblage React d'une
 * `LigneEnSaisie` (`src/ecrans/materials.ts`, qui porte toute la logique testée). */
function LigneMateriau({ ligne, enTraitement, onChange, onRetirer }: ProprietesLigneMateriau) {
  const { t } = useTranslation();
  const erreur = validerLigne(ligne);

  return (
    <View style={styles.ligneCarte}>
      <View style={styles.onglets}>
        {TYPES_LIGNE_MATERIAUX.map((type) => (
          <Pressable
            key={type}
            style={[styles.onglet, ligne.typeLigne === type ? styles.ongletActif : null]}
            disabled={enTraitement}
            onPress={() => onChange({ typeLigne: type })}
          >
            <Text style={ligne.typeLigne === type ? styles.ongletTexteActif : styles.ongletTexte}>{t(`materials.typeLigne.${type}`)}</Text>
          </Pressable>
        ))}
      </View>

      <TextInput
        style={styles.champ}
        placeholder={t("materials.champMateriau")}
        value={ligne.materiauId}
        onChangeText={(v) => onChange({ materiauId: v })}
        editable={!enTraitement}
        accessibilityLabel={t("materials.champMateriau")}
      />
      <View style={styles.ligneChamps}>
        <TextInput
          style={[styles.champ, styles.champMoitie]}
          placeholder={t("materials.champQuantite")}
          value={ligne.quantiteTexte}
          onChangeText={(v) => onChange({ quantiteTexte: v })}
          editable={!enTraitement}
          keyboardType="numeric"
          accessibilityLabel={t("materials.champQuantite")}
        />
        <TextInput
          style={[styles.champ, styles.champMoitie]}
          placeholder={t("materials.champUnite")}
          value={ligne.unite}
          onChangeText={(v) => onChange({ unite: v })}
          editable={!enTraitement}
          accessibilityLabel={t("materials.champUnite")}
        />
      </View>

      {ligne.typeLigne === "prevu" ? (
        <TextInput
          style={styles.champ}
          placeholder={t("materials.champQuantiteEstimee")}
          value={ligne.quantiteEstimeeTexte}
          onChangeText={(v) => onChange({ quantiteEstimeeTexte: v })}
          editable={!enTraitement}
          keyboardType="numeric"
          accessibilityLabel={t("materials.champQuantiteEstimee")}
        />
      ) : null}

      {ligne.typeLigne === "achat_terrain" ? (
        <View style={styles.ligneChamps}>
          <Pressable
            style={[styles.casePreuve, ligne.photoFournie ? styles.casePreuveActive : null]}
            disabled={enTraitement}
            onPress={() => onChange({ photoFournie: !ligne.photoFournie })}
          >
            <Text style={ligne.photoFournie ? styles.casePreuveTexteActif : styles.casePreuveTexte}>{t("materials.photoFournie")}</Text>
          </Pressable>
          <Pressable
            style={[styles.casePreuve, ligne.recuFourni ? styles.casePreuveActive : null]}
            disabled={enTraitement}
            onPress={() => onChange({ recuFourni: !ligne.recuFourni })}
          >
            <Text style={ligne.recuFourni ? styles.casePreuveTexteActif : styles.casePreuveTexte}>{t("materials.recuFourni")}</Text>
          </Pressable>
        </View>
      ) : null}

      {erreur ? <Text style={styles.erreurLigne}>{t(`materials.erreurs.${erreur}`)}</Text> : null}

      <Pressable disabled={enTraitement} onPress={onRetirer}>
        <Text style={styles.retirer}>{t("materials.retirerLigne")}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  conteneur: { flexGrow: 1, padding: 16, gap: 10 },
  titre: { fontSize: 20, fontWeight: "600" },
  identifiant: { color: "#888", fontSize: 12 },
  vide: { color: "#666" },
  erreur: { color: "#b00020" },
  erreurLigne: { color: "#b00020", fontSize: 12 },
  avis: { color: "#666" },
  succes: { color: "#1c6f5c", fontWeight: "600" },
  ligneCarte: { borderWidth: 1, borderColor: "#ddd", borderRadius: 8, padding: 12, gap: 8 },
  onglets: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  onglet: { paddingVertical: 6, paddingHorizontal: 10, borderRadius: 6, borderWidth: 1, borderColor: "#999" },
  ongletActif: { backgroundColor: "#1c6f5c", borderColor: "#1c6f5c" },
  ongletTexte: { color: "#333", fontSize: 12 },
  ongletTexteActif: { color: "#fff", fontWeight: "600", fontSize: 12 },
  champ: { borderWidth: 1, borderColor: "#999", borderRadius: 6, padding: 10 },
  ligneChamps: { flexDirection: "row", gap: 8 },
  champMoitie: { flex: 1 },
  casePreuve: { flex: 1, paddingVertical: 8, borderRadius: 6, borderWidth: 1, borderColor: "#999", alignItems: "center" },
  casePreuveActive: { backgroundColor: "#1c6f5c", borderColor: "#1c6f5c" },
  casePreuveTexte: { color: "#333" },
  casePreuveTexteActif: { color: "#fff", fontWeight: "600" },
  retirer: { color: "#b00020" },
  boutonSecondaire: { borderWidth: 1, borderColor: "#1c6f5c", paddingVertical: 10, borderRadius: 6, alignItems: "center" },
  boutonSecondaireTexte: { color: "#1c6f5c", fontWeight: "600" },
  bouton: { backgroundColor: "#1c6f5c", paddingVertical: 12, borderRadius: 6, alignItems: "center" },
  boutonPresse: { opacity: 0.7 },
  boutonTexte: { color: "#fff", fontWeight: "600" },
});
