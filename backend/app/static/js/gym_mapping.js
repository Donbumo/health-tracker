(() => {
  'use strict';
  const form = document.getElementById('gym-mapping');
  const input = document.getElementById('mapping-draft');
  const draft = JSON.parse(input.value);
  form.querySelectorAll('select[data-day]').forEach(select => {
    select.addEventListener('change', () => {
      const exercise = draft.days[Number(select.dataset.day)].exercises[Number(select.dataset.exercise)];
      delete exercise.resolved_exercise_id;
      delete exercise.name;
      exercise.create_new = select.value === 'new';
      if (select.value && select.value !== 'new') exercise.resolved_exercise_id = select.value;
      input.value = JSON.stringify(draft);
      document.querySelector('#gym-confirm button').disabled = true;
    });
  });
})();
