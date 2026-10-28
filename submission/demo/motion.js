(() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const reveals = document.querySelectorAll('.reveal');
  if (reduced || !('IntersectionObserver' in window)) reveals.forEach(node => node.classList.add('is-visible'));
  else {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) { entry.target.classList.add('is-visible'); observer.unobserve(entry.target); }
    }), {threshold: .14});
    reveals.forEach(node => observer.observe(node));
  }

  if (!reduced) document.querySelectorAll('[data-tilt]').forEach(card => {
    card.addEventListener('pointermove', event => {
      const rect = card.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width - .5;
      const y = (event.clientY - rect.top) / rect.height - .5;
      const horizontal = x < -.16 ? 'left' : x > .16 ? 'right' : 'center';
      const vertical = y < -.16 ? 'top' : y > .16 ? 'bottom' : 'middle';
      card.dataset.tiltPosition = `${vertical}-${horizontal}`;
    });
    card.addEventListener('pointerleave', () => { delete card.dataset.tiltPosition; });
  });

  const counters = document.querySelectorAll('[data-count]');
  if (counters.length) {
    const count = node => { const target = Number(node.dataset.count); let value = 0; const tick = () => { value += Math.max(1, Math.ceil((target - value) / 7)); node.textContent = Math.min(value, target); if (value < target) requestAnimationFrame(tick); }; tick(); };
    const observer = new IntersectionObserver(entries => entries.forEach(entry => { if (entry.isIntersecting) { count(entry.target); observer.unobserve(entry.target); } }), {threshold: .7}); counters.forEach(node => observer.observe(node));
  }

  const terminal = document.querySelector('#mcp-terminal');
  const run = document.querySelector('#run-mcp-demo');
  if (terminal && run) {
    const frames = [
      ['term-prompt', '$ agent: “Refactor safe_join path normalization.”'],
      ['term-tool', '→ recall_repository_memory'],
      ['term-json', '  1 verified capsule · relevance 0.94\n  Claim: Windows device names remain rejected.\n  Regression: SHA-256 706b7d…be7c3'],
      ['term-prompt', '$ agent edits src/werkzeug/security.py'],
      ['term-tool', '→ audit_repository_revision'],
      ['term-json', '  Upload bounded revision → fresh Nebius Sandbox\n  Replay frozen regression → assertion failure'],
      ['term-bad', '✕ memory_conflict\n  Proposed revision violated the recalled behavior.']
    ];
    const escape = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    run.addEventListener('click', async () => {
      run.disabled = true; terminal.innerHTML = '';
      for (const [kind, value] of frames) { const line = document.createElement('span'); line.className = kind; line.innerHTML = escape(value); terminal.append(line, document.createTextNode('\n')); terminal.scrollTop = terminal.scrollHeight; if (!reduced) await new Promise(resolve => setTimeout(resolve, 650)); }
      run.disabled = false; run.textContent = 'Replay sequence';
    });
  }
})();
