/* تحسينات ختامية: انتقال سلس من عناصر قمع الرؤية والرسالة إلى حقول العنصر المحدد. */
(function () {
  'use strict';

  function scrollToActiveFunnelInput() {
    window.requestAnimationFrame(function () {
      const target =
        document.querySelector('#funnelElementAnswer textarea') ||
        document.getElementById('funnelElementAnswer') ||
        document.getElementById('funnelQuestionList');

      if (!target) return;
      target.style.scrollMarginTop = '110px';
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });

      if (target.matches && target.matches('textarea')) {
        window.setTimeout(function () {
          target.focus({ preventScroll: true });
        }, 450);
      }
    });
  }

  const originalSelectFunnelStage = window.selectFunnelStage;
  if (typeof originalSelectFunnelStage === 'function') {
    window.selectFunnelStage = function (index) {
      originalSelectFunnelStage(index);
      scrollToActiveFunnelInput();
    };
  }

  const originalSetFunnelMode = window.setFunnelMode;
  if (typeof originalSetFunnelMode === 'function') {
    window.setFunnelMode = function (mode) {
      originalSetFunnelMode(mode);
      scrollToActiveFunnelInput();
    };
  }
})();
