/* QA only. Explicit visual examples, never recommendations or user records. */
(function (root) {
  'use strict';
  const data = {
    source: { name: 'Free Exercise DB', revision: 'f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5', license: 'Unlicense', url: 'https://github.com/yuhonas/free-exercise-db' },
    program: { name: 'Hipertrofia', days: [
      { id: 'D1', name: 'Pecho + espalda', exercises: 6, sets: 18, minutes: 58, previous: '29 sep', preview: ['bench', 'row', 'incline'] },
      { id: 'D2', name: 'Piernas', exercises: 5, sets: 17, minutes: 55, previous: '30 sep', preview: ['squat', 'curl'] },
      { id: 'D3', name: 'Hombros + brazos', exercises: 6, sets: 18, minutes: 52, previous: '25 sep', preview: ['curl', 'incline'] },
      { id: 'D4', name: 'Torso', exercises: 6, sets: 18, minutes: 60, previous: '26 sep', preview: ['bench', 'row'] },
      { id: 'D5', name: 'Piernas + core', exercises: 5, sets: 16, minutes: 50, previous: '27 sep', preview: ['squat'] }
    ] },
    exercises: {
      bench: { name: 'Press banca', externalId: 'Barbell_Bench_Press_-_Medium_Grip', canonicalName: 'Barbell Bench Press - Medium Grip', image: 'assets/bench-0.jpg', detailImage: 'assets/bench-1.jpg', muscles: 'Pecho · Tríceps', equipment: 'Barra', mechanic: 'Compuesto', load: '80', reps: 8, range: '6–8', rir: 2, sets: [8,7,7], state: 'increase_load', change: '+2.5 kg este mes', volume: '1,760', bestSet: '80 kg × 8', sessions: 12, estimate: '101', estimateChange: '+4.3%', rule: 'Ejemplo de regla · Sin evaluar', reason: 'Un posible incremento de diseño. Antes de proponerlo, habrá que validar todas las series y el esfuerzo.', evidence: ['Última sesión: 80 kg × 8 / 7 / 7', 'Rango de la rutina: 6–8 reps · RIR objetivo 2', 'Las tres series aún no alcanzan 8 reps'], proposed: '82.5', unit: 'kg', instruction: 'Referencia del catálogo: press en banco plano, agarre medio. Consulta las dos posiciones del movimiento.' },
      row: { name: 'Remo con barra', externalId: 'Bent_Over_Barbell_Row', canonicalName: 'Bent Over Barbell Row', image: 'assets/row-0.jpg', muscles: 'Espalda · Bíceps', equipment: 'Barra', mechanic: 'Compuesto', load: '70', reps: 10, range: '8–10', rir: 2, sets: [10,9,8], state: 'maintain', change: 'Consolida esta carga', volume: '1,890', bestSet: '70 kg × 10', sessions: 9, estimate: null, rule: 'Ejemplo de regla · Sin evaluar', reason: 'Conserva la referencia de tu última sesión. La propuesta de mantener es un ejemplo visual, pendiente del motor de progresión.', evidence: ['Última sesión: 70 kg × 10 / 9 / 8', 'Rango: 8–10 reps · RIR objetivo 2'], proposed: '70', unit: 'kg', instruction: 'Variante del catálogo: remo inclinado con barra y agarre prono.' },
      incline: { name: 'Press inclinado', externalId: 'Incline_Dumbbell_Press', canonicalName: 'Incline Dumbbell Press', image: 'assets/incline-0.jpg', muscles: 'Pecho · Hombros', equipment: 'Mancuernas', mechanic: 'Compuesto', load: '30', reps: 8, range: '8–10', rir: 2, sets: [8,8,7], state: 'increase_reps', change: '+2 kg por mancuerna', unit: 'kg por mancuerna' },
      curl: { name: 'Curl con barra', externalId: 'Barbell_Curl', canonicalName: 'Barbell Curl', image: 'assets/curl-0.jpg', muscles: 'Bíceps', equipment: 'Barra', mechanic: 'Aislado', load: '25', reps: 7, range: '8–10', rir: 2, sets: [7,7,6], state: 'increase_reps', change: 'Busca una repetición más', unit: 'kg' },
      squat: { name: 'Sentadilla con barra', externalId: 'Barbell_Squat', canonicalName: 'Barbell Squat', image: 'assets/squat-0.jpg', muscles: 'Cuádriceps · Glúteos', equipment: 'Barra', mechanic: 'Compuesto', load: '90', reps: 8, range: '6–8', rir: 2, sets: [8,7,7], state: 'maintain', unit: 'kg' }
    },
    /* Same point fields as progress_exercise_detail. Never pair best_reps and best_load as one set. */
    points: [
      {date:'2026-04-20',best_load_kg:'65'}, {date:'2026-05-18',best_load_kg:'67.5'}, {date:'2026-06-15',best_load_kg:'70'},
      {date:'2026-07-13',best_load_kg:'70'}, {date:'2026-07-27',best_load_kg:'72.5'}, {date:'2026-08-10',best_load_kg:'72.5'},
      {date:'2026-08-17',best_load_kg:'75'}, {date:'2026-08-24',best_load_kg:'75'}, {date:'2026-08-31',best_load_kg:'75'},
      {date:'2026-09-07',best_load_kg:'77.5'}, {date:'2026-09-14',best_load_kg:'77.5'}, {date:'2026-09-21',best_load_kg:'80'},
      {date:'2026-09-29',best_load_kg:'80'}
    ],
    history: [
      {date:'29 sep',load:'80',sets:[8,7,7],rir:[2,1,2],volume:'1,760'},
      {date:'21 sep',load:'80',sets:[7,7,6],rir:[2,2,1],volume:'1,600'},
      {date:'14 sep',load:'77.5',sets:[8,8,7],rir:[2,2,1],volume:'1,782.5'}
    ],
    proposals: {
      increase_load: { label:'Progresando', icon:'↗', action:'Preparar cambio', tone:'lime' },
      increase_reps: { label:'Buscando más reps', icon:'＋', action:'Preparar objetivo', tone:'cyan' },
      maintain: { label:'Mantener', icon:'＝', action:'Revisar propuesta', tone:'neutral' },
      review: { label:'Revisar', icon:'!', action:'Revisar ejercicio', tone:'amber' },
      insufficient_data: { label:'Construyendo historial', icon:'◷', action:null, tone:'neutral' }
    }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = data;
  else root.GymDesignFixtures = data;
})(typeof globalThis !== 'undefined' ? globalThis : this);
