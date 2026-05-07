const briefingEl = document.querySelector('#briefing');
const sourcesEl = document.querySelector('#sources');
const yesterdayEl = document.querySelector('#yesterday');
const heroHeadlineEl = document.querySelector('#heroHeadline');
const heroSummaryEl = document.querySelector('#heroSummary');
const notifyButton = document.querySelector('#notifyButton');
const commitLink = document.querySelector('#commitLink');
const starCountText = document.querySelector('#starCountText');

const REPOSITORY = 'DevSecNinja/wazzup';
const FALLBACK_TIME_ZONE = 'Europe/Amsterdam';
const MAX_HEADLINE_LENGTH = 96;
const MAX_DESCRIPTION_LENGTH = 320;

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

function truncateText(value, maxLength) {
  const text = String(value || '').trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 1).trim()}…`;
}

function stripLeadingTitle(text, title) {
  const cleanText = String(text || '').trim();
  const cleanTitle = String(title || '').trim();
  if (!cleanTitle) return cleanText;
  const lowerText = cleanText.toLowerCase();
  const lowerTitle = cleanTitle.toLowerCase();
  if (lowerText.startsWith(`${lowerTitle}:`)) return cleanText.slice(cleanTitle.length + 1).trim();
  if (lowerText.startsWith(`${lowerTitle} —`)) return cleanText.slice(cleanTitle.length + 2).trim();
  if (lowerText.startsWith(`${lowerTitle} -`)) return cleanText.slice(cleanTitle.length + 2).trim();
  return cleanText;
}

function normalizeBullet(bullet, citations) {
  const firstCitation = (bullet.citations || []).map((itemId) => citations.get(itemId)).find(Boolean);
  const fullTitle = bullet.title || firstCitation?.title || 'Update';
  const title = truncateText(fullTitle, MAX_HEADLINE_LENGTH);
  const rawDescription = bullet.description || stripLeadingTitle(bullet.text, fullTitle) || bullet.text || '';
  return {
    title,
    description: truncateText(rawDescription, MAX_DESCRIPTION_LENGTH),
    temperature: firstCitation?.temperature || { level: 'cool', label: 'Background', icon: '•' },
  };
}

function temperatureClass(temperature) {
  const level = String(temperature?.level || 'cool').toLowerCase();
  return ['hot', 'warm', 'cool'].includes(level) ? level : 'cool';
}

function renderBriefing(briefing) {
  const citations = citationMap(briefing);
  const sections = (briefing.sections || [])
    .map((section) => {
      const bullets = (section.bullets || [])
        .map((bullet) => {
          const normalized = normalizeBullet(bullet, citations);
          const temperature = normalized.temperature;
          const temperatureLevel = temperatureClass(temperature);
          const links = (bullet.citations || [])
            .map((itemId) => citations.get(itemId))
            .filter(Boolean)
            .map(
              (citation) =>
                `<a class="citation" href="${escapeHtml(citation.url)}" target="_blank" rel="noopener noreferrer">${citation.publishedAt ? `${escapeHtml(formatDate(citation.publishedAt))} · ` : ''}${escapeHtml(citation.sourceName)}</a>`,
            )
            .join('');
          return `<li class="bullet bullet--${temperatureLevel}"><div class="bullet__heading"><span class="temperature temperature--${temperatureLevel}" title="${escapeHtml(temperature.label || 'Importance')}">${escapeHtml(temperature.icon || '•')}</span><h4>${escapeHtml(normalized.title)}</h4></div><p>${escapeHtml(normalized.description)}</p><div class="citations">${links}</div></li>`;
        })
        .join('');
      return `<section class="section"><h3>${escapeHtml(section.title)}</h3><ul class="bullet-list">${bullets}</ul></section>`;
    })
    .join('');

  briefingEl.innerHTML = `
    <p class="eyebrow">${escapeHtml(briefing.kind)} briefing</p>
    <h2>Today's rolling briefing</h2>
    <p class="meta">Generated ${formatDate(briefing.generatedAt)} · Window ${formatDate(briefing.windowStart)} → ${formatDate(briefing.windowEnd)}</p>
    ${sections}
    ${briefing.provider?.type === 'fake' ? '<p class="provider-note">Deterministic fallback summary. Add a Copilot token secret for AI-written briefings.</p>' : ''}
  `;
}

function renderHero(briefing) {
  const citations = citationMap(briefing);
  const topBullet = briefing.sections?.[0]?.bullets?.[0];
  const normalized = topBullet ? normalizeBullet(topBullet, citations) : null;
  heroHeadlineEl.textContent = truncateText(briefing.headline, MAX_HEADLINE_LENGTH);
  heroSummaryEl.textContent = normalized?.description || 'No notable updates were found in today’s rolling briefing.';
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

function localDateKey(value) {
  const date = new Date(value);
  const options = { year: 'numeric', month: '2-digit', day: '2-digit' };
  try {
    return localDateKeyParts(date, options);
  } catch {
    return localDateKeyParts(date, { ...options, timeZone: FALLBACK_TIME_ZONE });
  }
}

function localDateKeyParts(date, options) {
  const parts = new Intl.DateTimeFormat('en-GB', options)
    .formatToParts(date)
    .reduce((acc, part) => ({ ...acc, [part.type]: part.value }), {});
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function previousLocalDateKey(dateKey) {
  const [year, month, day] = dateKey.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

async function findYesterdayBriefing(manifest, latest, currentBriefing) {
  const yesterdayDate = previousLocalDateKey(localDateKey(currentBriefing.generatedAt));
  const candidates = (manifest.briefings || [])
    .filter((path) => path !== latest.latestBriefingYamlUrl)
    .slice()
    .sort()
    .reverse()
    .slice(0, 72);

  for (const yamlPath of candidates) {
    try {
      const briefing = await getJson(`data/${yamlPath.replace(/\.yaml$/, '.json')}`);
      if (localDateKey(briefing.generatedAt) === yesterdayDate) return briefing;
    } catch {
      // Ignore retained manifest entries whose JSON mirror is unavailable.
    }
  }
  return null;
}

async function renderYesterday(manifest, latest, currentBriefing) {
  const briefing = await findYesterdayBriefing(manifest, latest, currentBriefing);
  if (!briefing) {
    yesterdayEl.innerHTML = `
      <p class="eyebrow">Yesterday</p>
      <h2>No yesterday summary yet</h2>
      <p class="meta">Once yesterday has retained briefing data, its latest daily roll-up will appear here.</p>
    `;
    return;
  }

  const citations = citationMap(briefing);
  const topBullet = briefing.sections?.[0]?.bullets?.[0];
  const normalized = topBullet ? normalizeBullet(topBullet, citations) : null;
  yesterdayEl.innerHTML = `
    <p class="eyebrow">Yesterday</p>
    <h2>${escapeHtml(truncateText(briefing.headline, MAX_HEADLINE_LENGTH))}</h2>
    <div class="yesterday-summary">
      <p>${escapeHtml(normalized?.description || 'No summary text was available for yesterday.')}</p>
      <p class="meta">Generated ${escapeHtml(formatDate(briefing.generatedAt))}</p>
    </div>
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
    await renderYesterday(manifest, latest, briefing);
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
    yesterdayEl.innerHTML = '<p class="eyebrow">Yesterday</p><h2>Unavailable</h2>';
  }
}

main();
