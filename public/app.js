const briefingEl = document.querySelector('#briefing');
const sourcesEl = document.querySelector('#sources');

async function getJson(path) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to load ${path}: ${response.status}`);
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatDate(value) {
  return new Intl.DateTimeFormat('en', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function citationMap(briefing) {
  return new Map((briefing.citations || []).map((citation) => [citation.itemId, citation]));
}

function renderBriefing(briefing) {
  const citations = citationMap(briefing);
  const sections = (briefing.sections || [])
    .map((section) => {
      const bullets = (section.bullets || [])
        .map((bullet) => {
          const links = (bullet.citations || [])
            .map((itemId) => citations.get(itemId))
            .filter(Boolean)
            .map(
              (citation) =>
                `<a class="citation" href="${escapeHtml(citation.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(citation.sourceName)}</a>`,
            )
            .join('');
          return `<li class="bullet"><p>${escapeHtml(bullet.text)}</p><div class="citations">${links}</div></li>`;
        })
        .join('');
      return `<section class="section"><h3>${escapeHtml(section.title)}</h3><ul class="bullet-list">${bullets}</ul></section>`;
    })
    .join('');

  briefingEl.innerHTML = `
    <p class="eyebrow">${escapeHtml(briefing.kind)} briefing</p>
    <h2>${escapeHtml(briefing.headline)}</h2>
    <p class="meta">Generated ${formatDate(briefing.generatedAt)} · Window ${formatDate(briefing.windowStart)} – ${formatDate(briefing.windowEnd)} · ${escapeHtml(briefing.provider?.type || 'unknown provider')}</p>
    ${sections}
  `;
}

function renderSources(status) {
  const sources = status.sources || [];
  const items = sources
    .map(
      (source) => `<li>
        <span class="status ${source.ok ? '' : 'status--bad'}">${source.ok ? 'OK' : 'Failed'}</span>
        <strong>${escapeHtml(source.sourceId)}</strong>
        <p class="source-meta">${escapeHtml(source.itemCount)} items · ${escapeHtml(source.message)}</p>
      </li>`,
    )
    .join('');
  sourcesEl.innerHTML = `
    <p class="eyebrow">Source health</p>
    <h2>${sources.filter((source) => source.ok).length}/${sources.length} sources healthy</h2>
    <ul class="source-list">${items}</ul>
  `;
}

async function main() {
  try {
    const latest = await getJson('data/latest.json');
    const [briefing, status] = await Promise.all([
      getJson(`data/${latest.latestBriefingUrl}`),
      getJson('data/sources/status.json'),
    ]);
    renderBriefing(briefing);
    renderSources(status);
    if ('serviceWorker' in navigator) {
      await navigator.serviceWorker.register('sw.js');
    }
  } catch (error) {
    briefingEl.innerHTML = `<p class="eyebrow">Error</p><h2>Could not load briefing</h2><p class="meta">${escapeHtml(error.message)}</p>`;
    sourcesEl.innerHTML = '<p class="eyebrow">Source health</p><h2>Unavailable</h2>';
  }
}

main();
