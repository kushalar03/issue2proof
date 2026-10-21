/*
 * Public demo adapter.
 *
 * The production frontend below is unchanged. This adapter answers its API calls
 * with compact reviewed evidence summaries so every control can be tried without
 * exposing an application token or consuming Nebius credits.
 */
(() => {
  const nativeFetch = window.fetch.bind(window);
  const recentRuns = [
    {id: 'example-real-bug-werkzeug', case: 'repository', mode: 'repository draft', verdict: 'checks_passed'},
    {id: 'example-live-pricing-repair', case: 'repair', mode: 'model repair', verdict: 'verified'},
    {id: 'example-live-rejection-evaluation', case: 'repository', mode: 'evaluation', verdict: 'candidate_rejected'}
  ];
  const examples = [
    ['live-pricing-repair', 'Live AI pricing repair'],
    ['live-repository-repair', 'Live uploaded-project repair'],
    ['live-rejection-evaluation', 'Live bad-candidate rejection'],
    ['real-bug-werkzeug', 'Historical Werkzeug repair'],
    ['real-bug-requests', 'Historical Requests repair'],
    ['live-dependency-investigation', 'Package and dependency repair']
  ].map(([id, title]) => ({id, title}));
  const capsule = {
    id: '4c88c2a9-df98-4cdf-866e-b1106fcf6cf7',
    version: 1,
    claim: 'On Windows, safe_join rejects special device names while preserving ordinary joins and traversal checks.',
    repository_key: 'pallets/werkzeug',
    created_at: '2026-10-20T15:38:00Z',
    scope: {paths: ['src/werkzeug/security.py', 'tests/test_security.py']},
    evidence: {
      verdict: 'checks_passed',
      operation_ids: [
        '01a159f6-49c5-70e4-9bf6-836550b8b706',
        '01a159f7-577c-77ba-aef2-0f1ad71dcb12'
      ],
      regression: {
        source: [
          'def test_safe_join_windows_device_names_rejected(monkeypatch):',
          '    monkeypatch.setattr(security.os, "name", "nt")',
          '    assert safe_join("trusted", "CON") is None',
          '    assert safe_join("trusted", "NUL.txt") is None',
          '    assert safe_join("trusted", "ordinary.txt") == "trusted/ordinary.txt"'
        ].join('\n'),
        sha256: '67dd5577c198ee957065674c8a6a82c85b02f79f33e6445fa454d2c2cbb6dc28'
      }
    },
    ai_index: {
      summary: 'Reject reserved Windows device names using string validation while keeping ordinary path joining and traversal protection unchanged.',
      keywords: ['safe_join', 'Windows', 'device names', 'path traversal', 'regression'],
      model: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
      role: 'fast'
    },
    risk_boundaries: [
      'Evidence covers the recorded Windows device-name regression.',
      'The original and replayed checks ran in isolated Nebius Sandboxes.',
      'Unrelated filesystem behavior remains outside this capsule.'
    ]
  };
  const cases = [
    {id: 'repair', title: 'Excess discount', issue: 'Clamp an excess discount to zero while preserving ordinary order totals.'},
    {id: 'reject', title: 'Catch a plausible bad fix', issue: 'Reject a patch that returns zero for every order total.'},
    {id: 'unresolved', title: 'Exhaust the repair budget', issue: 'Show the bounded outcome after all candidate patches fail.'},
    {id: 'ambiguous', title: 'Clarify expected behavior', issue: 'Show the clarification boundary for an underspecified failure.'}
  ];
  const passed = (command, output = '1 passed') => ({
    command,
    output,
    exit_code: 0,
    seconds: 0.42,
    evidence_valid: true
  });
  const failed = (command, output = '1 failed') => ({
    command,
    output,
    exit_code: 1,
    seconds: 0.39,
    evidence_valid: true
  });
  const repositoryReport = {
    id: 'demo-repository',
    case: 'repository',
    mode: 'recorded public demo',
    issue: 'Reject reserved device names while preserving ordinary joins and traversal protection.',
    verdict: 'checks_passed',
    explanation: 'The original failure was reproduced before repair. The candidate passed the frozen regression, existing checks and an independent boundary suite.',
    attempts: [],
    events: [],
    sources: {
      'src/path_rules.py': [
        'def safe_join(base, name):',
        '    if is_reserved_device_name(name):',
        '        return None',
        '    return validated_join(base, name)'
      ].join('\n')
    },
    existing_tests: {},
    dependency_manifests: {'requirements.txt': 'pytest==8.4.2'},
    resources: {},
    excluded_files: ['Generated caches and binary assets'],
    limitations: [
      'This public interaction uses compact demonstration data.',
      'Fresh model and sandbox operations require the authenticated deployment.'
    ],
    verification: {
      baseline: passed('pytest -q tests/existing'),
      independent_baseline: failed('pytest -q tests/independent', 'Reserved-name assertion failed before repair'),
      reproduction: failed('pytest -q frozen_regression.py', 'Original behavior reproduced'),
      regression: passed('pytest -q frozen_regression.py'),
      existing: passed('pytest -q tests/existing', '18 passed'),
      independent: passed('pytest -q tests/independent', '7 passed')
    },
    generated_regression: {
      source: 'def test_reserved_name_rejected():\n    assert safe_join("trusted", "CON") is None'
    },
    draft_diff: [
      '--- a/src/path_rules.py',
      '+++ b/src/path_rules.py',
      '@@',
      '+    if is_reserved_device_name(name):',
      '+        return None'
    ].join('\n')
  };
  const pricingReport = {
    id: 'demo-pricing',
    case: 'repair',
    mode: 'recorded public demo',
    issue: 'Clamp an excess discount to zero while preserving ordinary order totals.',
    verdict: 'verified',
    explanation: 'The candidate passed the frozen regression, existing suite and independent boundary checks in isolated execution.',
    baseline: passed('pytest -q tests/test_existing.py'),
    reproduction: failed('pytest -q frozen_regression.py', 'Expected zero, received -50'),
    regression_test: 'def test_excess_discount():\n    assert total(100, 150) == 0',
    test_hashes: {regression: 'sha256:demo-regression'},
    attempts: [{
      number: 1,
      accepted: true,
      protected_tests_intact: true,
      diff: '--- a/pricing.py\n+++ b/pricing.py\n@@\n-    return subtotal - discount\n+    return max(0, subtotal - discount)',
      regression: passed('pytest -q frozen_regression.py'),
      existing: passed('pytest -q tests/test_existing.py'),
      independent: passed('pytest -q tests/test_independent.py', '4 passed')
    }],
    limitations: [
      'This is a reviewed demonstration fixture.',
      'The public host makes no model or sandbox calls.'
    ]
  };
  const rejectionReport = {
    ...pricingReport,
    id: 'demo-rejection',
    verdict: 'candidate_rejected',
    explanation: 'The plausible shortcut fixed the reported example but failed independent checks for ordinary totals.',
    attempts: [{
      number: 1,
      accepted: false,
      protected_tests_intact: true,
      diff: '--- a/pricing.py\n+++ b/pricing.py\n@@\n-    return subtotal - discount\n+    return 0',
      regression: passed('pytest -q frozen_regression.py'),
      existing: failed('pytest -q tests/test_existing.py', 'Normal discount total changed from 80 to 0'),
      independent: failed('pytest -q tests/test_independent.py', '3 boundary assertions failed')
    }]
  };
  const demoReports = {
    'live-pricing-repair': pricingReport,
    'live-repository-repair': repositoryReport,
    'live-rejection-evaluation': rejectionReport,
    'real-bug-werkzeug': repositoryReport,
    'real-bug-requests': repositoryReport,
    'live-dependency-investigation': repositoryReport
  };

  function json(value, status = 200) {
    return new Response(JSON.stringify(value), {
      status,
      headers: {'Content-Type': 'application/json'}
    });
  }

  async function loadReport(name) {
    const report = demoReports[name];
    if (!report) throw new Error('Demonstration record could not be loaded.');
    return structuredClone(report);
  }

  function exampleName(path) {
    const match = path.match(/^\/api\/examples\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }

  window.ISSUE2PROOF_STATIC_DEMO = true;
  window.fetch = async (input, options = {}) => {
    const raw = typeof input === 'string' ? input : input.url;
    const url = new URL(raw, window.location.href);
    if (!url.pathname.startsWith('/api/')) return nativeFetch(input, options);
    const path = url.pathname;
    const method = (options.method || 'GET').toUpperCase();

    if (path === '/api/health') return json({authenticated: true, authentication_required: false, mode: 'recorded-demo'});
    if (path === '/api/cases') return json(cases);
    if (path === '/api/jobs') return json([]);
    if (path === '/api/budget') return json({remaining_spendable_usd: 19.98, protected_reserve_usd: 5.0});
    if (path === '/api/memories' && method === 'GET') return json([capsule]);
    if (path === '/api/memories/search') return json([{capsule, score: 0.94}]);
    if (path.match(/^\/api\/memories\/[^/]+\/enrich$/)) return json(capsule);
    if (path === '/api/runs' && url.searchParams.get('summaries') === 'true') return json(recentRuns);
    if (path === '/api/examples') return json(examples);

    const name = exampleName(path);
    if (name && path.endsWith('/memory')) return json(capsule, 201);
    if (name && path.endsWith('/artifacts')) {
      return json({message: 'Compact public demonstration artifact', report: await loadReport(name)});
    }
    if (name) {
      const report = await loadReport(name);
      return json({...report, saved_example: true, id: `example-${name}`});
    }

    if (path === '/api/runs' && method === 'POST') {
      const body = JSON.parse(options.body || '{}');
      const selected = body.case === 'reject' ? 'live-rejection-evaluation' : 'live-pricing-repair';
      const report = await loadReport(selected);
      return json({...report, saved_example: true, id: `example-${selected}`});
    }
    if (path.startsWith('/api/runs/')) {
      const id = decodeURIComponent(path.split('/')[3] || '');
      const selected = id.replace(/^example-/, '') || 'real-bug-werkzeug';
      const report = await loadReport(selected);
      return json({...report, saved_example: true, id: `example-${selected}`});
    }
    if ((path === '/api/projects/github' || path === '/api/projects') && method === 'POST') {
      const report = await loadReport('real-bug-werkzeug');
      return json({...report, saved_example: true, id: 'example-real-bug-werkzeug'});
    }
    if (path === '/api/login' || path === '/api/logout') return json({ok: true});
    return json({detail: 'This public demo supports recorded evidence actions only.'}, 404);
  };

  window.addEventListener('DOMContentLoaded', () => {
    const repository = document.querySelector('#repository-url');
    const issue = document.querySelector('#bug-report');
    const memoryQuery = document.querySelector('#memory-query');
    if (repository) repository.value = 'https://github.com/pallets/werkzeug';
    if (issue) issue.value = 'Reject Windows device names in safe_join while preserving ordinary joins and traversal checks.';
    if (memoryQuery) memoryQuery.value = 'Refactor safe_join path validation';

    document.querySelector('a[href="#werkzeug-demo"]')?.addEventListener('click', async event => {
      event.preventDefault();
      const report = await loadReport('real-bug-werkzeug');
      window.render({...report, saved_example: true, id: 'example-real-bug-werkzeug'});
      document.querySelector('#results')?.scrollIntoView({behavior: 'smooth', block: 'start'});
    });
    document.querySelector('a[href="#calendar-demo"]')?.addEventListener('click', async event => {
      event.preventDefault();
      const report = await loadReport('live-repository-repair');
      window.render({...report, saved_example: true, id: 'example-live-repository-repair'});
      document.querySelector('#results')?.scrollIntoView({behavior: 'smooth', block: 'start'});
    });
    document.addEventListener('click', event => {
      const link = event.target.closest('a[href^="/api/"]');
      if (!link) return;
      event.preventDefault();
      const blob = new Blob([
        JSON.stringify({
          demo: 'Issue2Proof recorded evidence',
          note: 'The complete evidence files are available in the public source repository.'
        }, null, 2)
      ], {type: 'application/json'});
      const download = document.createElement('a');
      download.href = URL.createObjectURL(blob);
      download.download = 'issue2proof-recorded-evidence.json';
      download.click();
      URL.revokeObjectURL(download.href);
    });
  });
})();
