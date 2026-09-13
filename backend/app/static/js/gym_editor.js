(() => {
  'use strict';
  const form = document.getElementById('gym-editor');
  const draft = JSON.parse(document.getElementById('gym-draft-data').textContent);
  const days = document.getElementById('program-days');
  let sequence = 0;
  function element(tag, text, className) {
    const node = document.createElement(tag); if (text) node.textContent = text;
    if (className) node.className = className; return node;
  }
  function field(parent, label, value, onChange, type = 'text') {
    const wrapper = element('div'); const id = `gym-editor-field-${++sequence}`;
    const caption = element('label', label); caption.htmlFor = id;
    const input = element('input'); input.id = id; input.type = type;
    input.value = value ?? ''; input.maxLength = type === 'text' ? 200 : 12;
    if (type === 'number') { input.inputMode = 'decimal'; input.step = 'any'; input.min = '0'; }
    input.addEventListener('input', () => onChange(input.value));
    wrapper.append(caption, input); parent.append(wrapper); return input;
  }
  function button(parent, label, action) {
    const node = element('button', label, 'button button-secondary'); node.type = 'button';
    node.addEventListener('click', action); parent.append(node); return node;
  }
  function move(items, index, offset) {
    const target = index + offset;
    if (target >= 0 && target < items.length) [items[index], items[target]] = [items[target], items[index]];
    render();
  }
  function render() {
    days.replaceChildren();
    draft.days.forEach((day, dayIndex) => {
      const panel = element('section', '', 'gym-editor-day');
      field(panel, 'Nombre del día', day.name, value => { day.name = value; }).required = true;
      const actions = element('div', '', 'gym-actions');
      button(actions, '↑ Día', () => move(draft.days, dayIndex, -1));
      button(actions, '↓ Día', () => move(draft.days, dayIndex, 1));
      button(actions, 'Eliminar día', () => { if (window.confirm('¿Eliminar este día del borrador?')) { draft.days.splice(dayIndex, 1); render(); } });
      panel.append(actions);
      day.exercises.forEach((exercise, exerciseIndex) => {
        const card = element('article', '', 'gym-preview-exercise');
        field(card, 'Ejercicio', exercise.raw_name, value => { exercise.raw_name = value; delete exercise.resolved_exercise_id; delete exercise.name; exercise.create_new = true; }).required = true;
        const controls = element('div', '', 'gym-actions');
        button(controls, '↑ Ejercicio', () => move(day.exercises, exerciseIndex, -1));
        button(controls, '↓ Ejercicio', () => move(day.exercises, exerciseIndex, 1));
        button(controls, 'Eliminar ejercicio', () => { if (window.confirm('¿Eliminar este ejercicio del borrador?')) { day.exercises.splice(exerciseIndex, 1); render(); } });
        card.append(controls);
        exercise.sets.forEach((target, setIndex) => {
          const set = element('details'); const title = `Serie ${setIndex + 1} · ${target.reps ?? (target.reps_min ? `${target.reps_min}–${target.reps_max}` : 'Define reps')}`;
          set.append(element('summary', title));
          const fields = element('div', '', 'gym-editor-fields');
          [['reps','Reps objetivo'],['reps_min','Reps mínimas'],['reps_max','Reps máximas'],['load_value','Carga objetivo'],['rir','RIR'],['rpe','RPE'],['rest_seconds','Descanso (s)']].forEach(([key, label]) => {
            field(fields, label, target[key], value => {
              if (value === '') delete target[key];
              else target[key] = ['reps','reps_min','reps_max','rest_seconds'].includes(key) ? Number(value) : value;
              if (key === 'load_value') { delete target.weight_kg; delete target.load_details; }
            }, 'number');
          });
          const unitWrapper = element('div'); const label = element('label', 'Unidad de carga'); const select = element('select');
          select.id = `gym-editor-unit-${++sequence}`; label.htmlFor = select.id;
          ['', 'kg', 'lb'].forEach(unit => { const option = element('option', unit || 'Seleccionar'); option.value = unit; option.selected = target.load_unit === unit; select.append(option); });
          select.addEventListener('change', () => { target.load_unit = select.value; delete target.load_details; delete target.weight_kg; });
          unitWrapper.append(label, select); fields.append(unitWrapper); set.append(fields);
          if (target.weight_kg !== undefined) set.append(element('p', `Carga conservada: ${target.weight_kg} kg`));
          button(set, 'Eliminar serie', () => { exercise.sets.splice(setIndex, 1); render(); });
          card.append(set);
        });
        button(card, 'Añadir serie', () => { if (exercise.sets.length < 30) { exercise.sets.push(exercise.sets.length ? {...exercise.sets.at(-1), id: undefined} : {}); render(); } });
        field(card, 'Notas', exercise.notes, value => { exercise.notes = value; });
        panel.append(card);
      });
      button(panel, 'Añadir ejercicio', () => { if (day.exercises.length < 100) { day.exercises.push({raw_name: '', create_new: true, sets: [{}]}); render(); } });
      days.append(panel);
    });
  }
  document.getElementById('add-day').addEventListener('click', () => { if (draft.days.length < 28) { draft.days.push({name: '', exercises: []}); render(); } });
  form.addEventListener('submit', () => {
    draft.program.name = document.getElementById('program-name').value;
    draft.days.forEach((day, index) => { day.order = index + 1; day.exercises.forEach(exercise => exercise.sets.forEach((set, i) => { set.set_number = i + 1; })); });
    draft.unresolved = []; document.getElementById('draft-input').value = JSON.stringify(draft);
  });
  render();
})();
