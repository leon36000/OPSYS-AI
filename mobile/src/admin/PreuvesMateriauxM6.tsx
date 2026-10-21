import { useCallback, useEffect, useRef, useState } from 'react';
import { Image, Text, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { capturerSessionAdminLecture } from '../protocole/configuration';
import { useSessionAppareil } from '../roles/contexte';
import type { PagePreuvesM6, PhotoPreuveM6, ReferencePreuveM6 } from '../m6/preuvesLecture';
import type { ApercuPreuve } from './apercuPreuve';
import type { ResultatSection } from './lecture';
import { chargerPreuvesPertesWctM6 } from './pertesAlertes';
import { BoutonSecondaire, stylesAdmin as styles } from './composants';

export function PreuvesMateriauxM6({ wctId, connected, surRefus }: {
  readonly wctId: string; readonly connected: boolean; readonly surRefus: () => void;
}) {
  const { t } = useTranslation(), session = useSessionAppareil();
  const [lecture, setLecture] = useState<ResultatSection<PagePreuvesM6>>();
  const [apercu, setApercu] = useState<ApercuPreuve>();
  const [occupe, setOccupe] = useState(false);
  const [, rendreGeneration] = useState(0);
  const generation = useRef(0), focus = useRef(false), reseau = useRef(connected);
  reseau.current = connected;
  const controller = useRef<AbortController | null>(null), image = useRef<ApercuPreuve | undefined>(undefined);
  const gardeLecture = useRef<(() => boolean) | null>(null);
  const purger = useCallback(() => {
    controller.current?.abort(); controller.current = null;
    const ancienne = image.current; image.current = undefined; setApercu(undefined);
    if (ancienne?.genre === 'pret') void ancienne.purger().catch(() => undefined);
  }, []);
  const invalider = useCallback(() => {
    ++generation.current; gardeLecture.current = null; purger(); setLecture(undefined); setOccupe(false);
    rendreGeneration(n => n + 1);
  }, [purger]);
  useFocusEffect(useCallback(() => {
    focus.current = true; invalider();
    return () => { focus.current = false; ++generation.current; gardeLecture.current = null; purger(); };
  }, [invalider, purger]));
  useEffect(() => { invalider(); }, [session, connected, wctId, invalider]);
  const capture = capturerSessionAdminLecture(), nRendu = generation.current;
  const permis = () => focus.current && reseau.current && capture.session !== null && capture.courante();
  async function charger(decalage = 0) {
    if (!permis() || nRendu !== generation.current) return;
    purger(); const n = ++generation.current; gardeLecture.current = capture.courante;
    setLecture(undefined); setOccupe(true);
    try {
      const r = await chargerPreuvesPertesWctM6(wctId, decalage);
      if (!permis() || n !== generation.current) return;
      if (r?.source === 'refus') { invalider(); surRefus(); return; }
      setLecture(r ?? { source: 'aucune', raison: { code: 'lecture_indisponible', detail: '' } });
    } catch { if (permis() && n === generation.current) setLecture({ source: 'aucune', raison: { code: 'lecture_indisponible', detail: '' } }); }
    finally { if (n === generation.current) setOccupe(false); }
  }
  const visible = permis() && gardeLecture.current?.() === true;
  const page = visible && lecture?.source === 'serveur' && lecture.valeur.wct_id === wctId ? lecture.valeur : null;
  async function voir(preuve: ReferencePreuveM6<'preuves_pertes_bris'>, photo: PhotoPreuveM6) {
    if (!permis() || !page || nRendu !== generation.current) return;
    purger(); const n = generation.current; const abort = new AbortController(); controller.current = abort; setOccupe(true);
    const courante = () => permis() && generation.current === n && !abort.signal.aborted;
    try {
      const natif: typeof import('./apercuPreuveNatif') = require('./apercuPreuveNatif');
      const { chargerApercuPreuveNatif } = natif;
      if (!courante()) return;
      const r = await chargerApercuPreuveNatif({ wct_id: wctId,
        preuve: { index: preuve.index, hash_maillon: preuve.hash_maillon }, position_photo: photo.position_photo }, photo, abort.signal, courante);
      if (!courante()) { if (r.genre === 'pret') await r.purger(); return; }
      if (r.genre === 'echec' && r.status !== undefined && r.status >= 400 && r.status < 500) { invalider(); surRefus(); return; }
      image.current = r; setApercu(r);
    } catch { if (courante()) setApercu({ genre: 'echec', code: 'photo_indisponible' }); }
    finally { if (courante()) setOccupe(false); }
  }
  return <View>
    <Text style={styles.sousTitre}>{t('admin.preuvesMateriaux.titre')}</Text>
    <Text style={styles.avis}>{t('admin.preuvesMateriaux.limites')}</Text>
    <BoutonSecondaire texte={t('admin.preuvesMateriaux.charger')} desactive={!permis() || occupe} onPress={() => void charger()} />
    {visible && lecture?.source === 'aucune' ? <Text>{t('admin.preuvesMateriaux.indisponible')}</Text> : null}
    {page ? <>
      <Text>{t('admin.preuvesMateriaux.page', { affichees: page.pertes_bris.length, total: page.total })}</Text>
      {page.pertes_bris.map(p => <View key={p.reference_mouvement.hash_maillon}>
        <Text>{p.type_mouvement} · {p.materiau_id} · {p.quantite} · {t('admin.preuvesMateriaux.uniteInconnue')}</Text>
        <Text>{t('admin.preuvesMateriaux.' + p.preuve.etat)}</Text>
        {p.preuve.note !== null ? <Text>{p.preuve.note}</Text> : null}
        {p.preuve.enregistre_le ? <Text>{t('admin.preuvesMateriaux.enregistre', { date: p.preuve.enregistre_le })}</Text> : null}
        {p.preuve.horodatage_appareil_declare ? <Text>{t('admin.preuvesMateriaux.declare', { date: p.preuve.horodatage_appareil_declare })}</Text> : null}
        {p.preuve.photos.map(photo => <BoutonSecondaire key={photo.reference} texte={t('admin.preuvesMateriaux.' + photo.etat_actuel)}
          desactive={!permis() || occupe || photo.etat_actuel !== 'disponible'}
          onPress={() => { if (p.preuve.reference) void voir(p.preuve.reference, photo); }} />)}
      </View>)}
      {page.decalage_suivant !== null ? <BoutonSecondaire texte={t('admin.preuvesMateriaux.suite')} desactive={!permis() || occupe}
        onPress={() => { if (page.decalage_suivant !== null) void charger(page.decalage_suivant); }} /> : null}
    </> : null}
    {visible && apercu?.genre === 'pret' && apercu.courante() ? <View>
      <Image source={{ uri: apercu.uri }} style={{ width: '100%', height: 240 }} resizeMode="contain"
        onError={() => {
          if (image.current !== apercu || nRendu !== generation.current || !permis()) return;
          purger(); setApercu({ genre: 'echec', code: 'photo_indisponible' });
        }} />
      <BoutonSecondaire texte={t('admin.preuvesMateriaux.fermer')} onPress={purger} />
    </View> : null}
    {visible && apercu?.genre === 'echec' ? <Text>{t('admin.preuvesMateriaux.indisponible')}</Text> : null}
  </View>;
}
