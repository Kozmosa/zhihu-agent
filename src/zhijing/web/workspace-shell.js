'use strict';

// These shortcuts only fill the user's question; generating remains an explicit action.
document.querySelectorAll('[data-question]').forEach(button => {
  button.addEventListener('click', () => {
    const input = document.getElementById('author-question');
    input.value = button.dataset.question;
    input.focus();
  });
});

if (document.body.dataset.desktop === 'true') {
  document.querySelector('.brand').href = '/desktop';
  document.title = '知境 · 随身工作台';
}
