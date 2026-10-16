// Интерактивная сказка — поведение страницы
(function () {
  'use strict';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // 1. Веер карточек наклоняется за курсором или наклоном телефона — как фигурка-джойстик
  var fan = document.getElementById('fan');
  var cards = fan ? fan.querySelectorAll('.card') : [];

  function tilt(nx, ny) { // nx, ny в диапазоне -1..1
    cards.forEach(function (card, i) {
      var depth = (i % 3) + 1;
      card.style.setProperty('--ry', (nx * 10) + 'deg');
      card.style.setProperty('--rx', (-ny * 8) + 'deg');
      card.style.setProperty('--tx', (nx * 6 * depth) + 'px');
      card.style.setProperty('--ty', (ny * 5 * depth) + 'px');
    });
  }

  if (fan && !reduceMotion) {
    window.addEventListener('pointermove', function (e) {
      if (e.pointerType !== 'mouse') return;
      tilt(e.clientX / window.innerWidth * 2 - 1, e.clientY / window.innerHeight * 2 - 1);
    });
    window.addEventListener('deviceorientation', function (e) {
      if (e.gamma == null) return;
      var clamp = function (v) { return Math.max(-1, Math.min(1, v)); };
      tilt(clamp(e.gamma / 30), clamp((e.beta - 45) / 30));
    });
  }

  // 2. Мини-демо развилки
  var demo = document.getElementById('demo');
  var demoText = document.getElementById('demoText');
  var answers = {
    sing: { text: 'Лиса облизнулась: «Спой-ка ещё разок, поближе…» Ой! Попробуй другой путь.', cls: 'is-lose' },
    run:  { text: 'Ура! Колобок укатился в кусты — и сказка пошла по новой тропинке.', cls: 'is-win' }
  };
  if (demo) {
    demo.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-choice]');
      if (!btn) return;
      var a = answers[btn.dataset.choice];
      demo.classList.remove('is-win', 'is-lose');
      void demo.offsetWidth; // перезапуск анимации
      demo.classList.add(a.cls);
      demoText.textContent = a.text;
    });
  }

  // 3. «Хочу эту сказку» → выбрать сказку в форме и прокрутить к заявке
  var taleSelect = document.getElementById('taleSelect');
  document.querySelectorAll('[data-tale]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      taleSelect.value = btn.dataset.tale;
      document.getElementById('signup').scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth' });
      setTimeout(function () { document.querySelector('#form input[name=name]').focus({ preventScroll: true }); }, 600);
    });
  });
  document.querySelectorAll('[data-who]').forEach(function (link) {
    link.addEventListener('click', function () {
      var r = document.querySelector('#form input[name=who][value="' + link.dataset.who + '"]');
      if (r) r.checked = true;
    });
  });

  // 4. Форма заявки — пока только проверка и сообщение (обработчик подключить перед запуском)
  var form = document.getElementById('form');
  var msg = document.getElementById('formMsg');
  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var ok = true;
      ['name', 'contact'].forEach(function (n) {
        var f = form.elements[n];
        var bad = !f.value.trim();
        if (n === 'contact' && !bad) bad = !/(@.+\.)|(\d{6,})/.test(f.value.replace(/[\s()-]/g, ''));
        f.classList.toggle('is-invalid', bad);
        if (bad) ok = false;
      });
      if (!form.elements.agree.checked) ok = false;
      msg.className = 'form__msg ' + (ok ? 'ok' : 'err');
      msg.textContent = ok
        ? 'Спасибо! Мы напишем, как только фигурки будут готовы.'
        : 'Заполните имя, телефон или e-mail и отметьте согласие.';
      if (ok) form.reset();
    });
  }

  // 5. Появление блоков при прокрутке
  var items = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && !reduceMotion) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('is-in'); io.unobserve(en.target); }
      });
    }, { threshold: 0.12 });
    items.forEach(function (el) { io.observe(el); });
  } else {
    items.forEach(function (el) { el.classList.add('is-in'); });
  }
})();
