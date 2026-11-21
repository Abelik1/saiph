// SPDX-License-Identifier: AGPL-3.0-or-later
// Progressive policy tabs: every document stays readable without JavaScript.
(function () {
  const alias = document.querySelector('[data-policy-redirect]');
  if (alias) {
    const fragment = window.location.hash || '#' + alias.dataset.policyRedirect;
    window.location.replace('privacy.html' + fragment);
    return;
  }
  const navigation = document.querySelector('[data-policy-tabs]');
  if (!navigation) return;
  const tabs = Array.from(navigation.querySelectorAll('a'));
  const panels = Array.from(document.querySelectorAll('[data-policy-panel]'));
  navigation.setAttribute('role', 'tablist');
  tabs.forEach((tab, index) => {
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', panels[index].id);
    panels[index].setAttribute('role', 'tabpanel');
    panels[index].setAttribute('aria-labelledby', tab.id);
  });
  function showHash(scroll) {
    let target = null;
    try { target = document.getElementById(decodeURIComponent(window.location.hash.slice(1))); } catch (_) { /* malformed fragment */ }
    const selected = panels.find(panel => panel === target || panel.contains(target)) || panels[0];
    panels.forEach(panel => { panel.hidden = panel !== selected; });
    tabs.forEach((tab, index) => {
      const active = panels[index] === selected;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    if (scroll && target && target !== selected) target.scrollIntoView({block: 'start'});
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', event => {
      event.preventDefault();
      // Replacing tabs should keep the compact navigation in view.
      window.history.pushState(null, '', tab.getAttribute('href'));
      showHash(false);
    });
    tab.addEventListener('keydown', event => {
      const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length
        : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
      if (next === null) return;
      event.preventDefault();
      tabs[next].focus();
      tabs[next].click();
    });
  });
  window.addEventListener('hashchange', () => showHash(true));
  window.addEventListener('popstate', () => showHash(true));
  showHash(true);
})();
