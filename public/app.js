const briefingEl = document.querySelector('#briefing');
const sourcesEl = document.querySelector('#sources');
const archiveEl = document.querySelector('#archive');
const heroHeadlineEl = document.querySelector('#heroHeadline');
const heroSummaryEl = document.querySelector('#heroSummary');
const notifyButton = document.querySelector('#notifyButton');
const commitLink = document.querySelector('#commitLink');
const starCountText = document.querySelector('#starCountText');

const REPOSITORY = 'DevSecNinja/wazzup';
const FALLBACK_TIME_ZONE = 'Europe/Amsterdam';

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
  const date = new Date(value);
  const options = {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    hour12: false,
  };
  try {
    return formatDateParts(date, options);
  } catch {
    return formatDateParts(date, { ...options, timeZone: FALLBACK_TIME_ZONE });
  }
}

function formatDateParts(date, options) {
  const parts = new Intl.DateTimeFormat('en-GB', options)
    .formatToParts(date)
    .reduce((acc, part) => ({ ...acc, [part.type]: part.value }), {});
  return `${parts.hour}:${parts.minute} - ${parts.day}/${parts.month}/${parts.year}`;
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
                `<a class="citation" href="${escapeHtml(citation.url)}" target="_blank" rel="noopener noreferrer">${citation.publishedAt ? `${escapeHtml(formatDate(citation.publishedAt))} · ` : ''}${escapeHtml(citation.sourceName)}</a>`,
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
    <p class="meta">Generated ${formatDate(briefing.generatedAt)} · Window ${formatDate(briefing.windowStart)} → ${formatDate(briefing.windowEnd)}</p>
    ${sections}
    ${briefing.provider?.type === 'fake' ? '<p class="provider-note">Deterministic fallback summary. Add a Copilot token secret for AI-written briefings.</p>' : ''}
  `;
}

function renderHero(briefing) {
  const topBullet = briefing.sections?.[0]?.bullets?.[0]?.text || 'No notable updates were found in this briefing window.';
  heroHeadlineEl.textContent = briefing.headline;
  heroSummaryEl.textContent = topBullet;
}

function renderSources(status) {
  const sources = status.sources || [];
  const items = sources
    .map(
      (source) => `<li>
        <span class="status ${source.ok ? '' : 'status--bad'}">${source.ok ? 'OK' : 'Failed'}</span>
        <strong>${escapeHtml(source.sourceId)}</strong>
        <p class="source-meta">${escapeHtml(source.itemCount)} items · latest ${source.lastArticleAt ? escapeHtml(formatDate(source.lastArticleAt)) : 'n/a'} · ${escapeHtml(source.message)}</p>
      </li>`,
    )
    .join('');
  sourcesEl.innerHTML = `
    <p class="eyebrow">Source health</p>
    <h2>${sources.filter((source) => source.ok).length}/${sources.length} sources healthy</h2>
    <ul class="source-list">${items}</ul>
  `;
}

async function renderArchive(manifest, latest) {
  const latestYaml = latest.latestBriefingYamlUrl;
  const recent = (manifest.briefings || [])
    .filter((path) => path !== latestYaml)
    .slice()
    .sort()
    .reverse()
    .slice(0, 6);

  if (!recent.length) {
    archiveEl.innerHTML = `
      <p class="eyebrow">Previous hours</p>
      <h2>No previous briefings yet</h2>
      <p class="meta">The archive will fill in as more hourly runs complete.</p>
    `;
    return;
  }

  const briefings = await Promise.all(
    recent.map(async (yamlPath) => {
      const jsonPath = yamlPath.replace(/\.yaml$/, '.json');
      try {
        return { path: jsonPath, briefing: await getJson(`data/${jsonPath}`) };
      } catch {
        return { path: jsonPath, briefing: null };
      }
    }),
  );
  const items = briefings
    .map(({ path, briefing }) => {
      if (!briefing) return '';
      return `<li><a class="archive-link" href="data/${escapeHtml(path)}" target="_blank" rel="noopener noreferrer">
        <strong>${escapeHtml(briefing.headline)}</strong>
        <span class="source-meta">${escapeHtml(briefing.kind)} · ${escapeHtml(formatDate(briefing.generatedAt))}</span>
      </a></li>`;
    })
    .join('');
  archiveEl.innerHTML = `
    <p class="eyebrow">Previous hours</p>
    <h2>Recent briefings</h2>
    <ul class="archive-list">${items}</ul>
  `;
}

async function loadBuildInfo() {
  try {
    return await getJson('build-info.json');
  } catch {
    return {
      buildId: 'dev',
      shortSha: 'dev',
      commitUrl: 'https://github.com/DevSecNinja/wazzup',
      repositoryUrl: 'https://github.com/DevSecNinja/wazzup',
    };
  }
}

async function renderFooter(buildInfo) {
  commitLink.textContent = buildInfo.shortSha || 'dev';
  commitLink.href = buildInfo.commitUrl || buildInfo.repositoryUrl || 'https://github.com/DevSecNinja/wazzup';
  try {
    const repo = await getJson(`https://api.github.com/repos/${REPOSITORY}`);
    const stars = repo.stargazers_count ?? 0;
    starCountText.textContent = `${stars} ${stars === 1 ? 'star' : 'stars'}`;
  } catch {
    starCountText.textContent = 'Star on GitHub';
  }
}

function enableNotifications(registration, briefing, latest) {
  if (!('Notification' in window) || !registration?.showNotification) return;
  notifyButton.hidden = Notification.permission === 'denied';
  notifyButton.textContent = Notification.permission === 'granted' ? 'Hourly update notifications enabled' : 'Notify me when a new hourly update lands';
  notifyButton.disabled = Notification.permission === 'granted';
  notifyButton.addEventListener('click', async () => {
    const permission = await Notification.requestPermission();
    notifyButton.textContent = permission === 'granted' ? 'Hourly update notifications enabled' : 'Notifications unavailable';
    notifyButton.disabled = permission === 'granted';
  });

  const storageKey = 'wazzup:lastBriefingUrl';
  const previous = localStorage.getItem(storageKey);
  if (previous && previous !== latest.latestBriefingUrl && Notification.permission === 'granted') {
    registration.showNotification('Wazzup hourly update', {
      body: briefing.headline,
      icon: 'icons/icon-192.png',
      badge: 'icons/icon-192.png',
      tag: 'wazzup-hourly-update',
    });
  }
  localStorage.setItem(storageKey, latest.latestBriefingUrl);
}

async function main() {
  try {
    const [latest, buildInfo] = await Promise.all([getJson('data/latest.json'), loadBuildInfo()]);
    const [briefing, status, manifest] = await Promise.all([
      getJson(`data/${latest.latestBriefingUrl}`),
      getJson('data/sources/status.json'),
      getJson('data/manifest.json'),
    ]);
    renderHero(briefing);
    renderBriefing(briefing);
    renderSources(status);
    await renderArchive(manifest, latest);
    await renderFooter(buildInfo);
    if ('serviceWorker' in navigator) {
      const registration = await navigator.serviceWorker.register(`sw.js?v=${encodeURIComponent(buildInfo.buildId || 'dev')}`, { updateViaCache: 'none' });
      enableNotifications(registration, briefing, latest);
    }
  } catch (error) {
    heroHeadlineEl.textContent = 'Briefing unavailable';
    heroSummaryEl.textContent = 'The latest briefing could not be loaded. Try again after the next scheduled run.';
    briefingEl.innerHTML = `<p class="eyebrow">Error</p><h2>Could not load briefing</h2><p class="meta">${escapeHtml(error.message)}</p>`;
    sourcesEl.innerHTML = '<p class="eyebrow">Source health</p><h2>Unavailable</h2>';
    archiveEl.innerHTML = '<p class="eyebrow">Previous hours</p><h2>Unavailable</h2>';
  }
}

main();
