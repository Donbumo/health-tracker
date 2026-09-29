(() => {
  'use strict';
  const form = document.getElementById('gym-mapping');
  if (!form) return;
  form.querySelectorAll('select[data-day]').forEach(select => {
    select.addEventListener('change', () => {
      window.gymDraftSave({action:'mapping',day:Number(select.dataset.day),exercise:Number(select.dataset.exercise),value:select.value});
    });
  });
})();
