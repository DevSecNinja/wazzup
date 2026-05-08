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
const BACKGROUND_SYNC_TAG = 'wazzup-hourly-update';
const DEFAULT_RETENTION_DAYS = 35;
const SEEN_BRIEFING_ITEMS_STORAGE_KEY = 'wazzup:seenBriefingItems';
const HIDE_SEEN_STORAGE_KEY = 'wazzup:hideSeen';

let briefingSeenObserver = null;
let hideSeenEnabled = safeLocalStorageGet(HIDE_SEEN_STORAGE_KEY) === '1';

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

function stripInterestBoilerplate(text) {
  if (typeof text !== 'string') return text;
  // Strip trailing AI-generated interest-match boilerplate appended during scoring.
  // Handles: "… Relevant to your X interests.", "… It matches your X interests.",
  //          "… Why it matters: …"
  return text
    .replace(/ (?:It matches|Relevant to) your\b[^.]*\binterests\.?\s*$/, '')
    .replace(/ Why it matters:[\s\S]*$/, '')
    .trimEnd();
}

function normalizeBullet(bullet, citations) {
  const firstCitation = (bullet.citations || []).map((itemId) => citations.get(itemId)).find(Boolean);
  const fullTitle = bullet.title || firstCitation?.title || 'Update';
  const title = truncateText(fullTitle, MAX_HEADLINE_LENGTH);
  const rawDescription = stripInterestBoilerplate(
    bullet.description || stripLeadingTitle(bullet.text, fullTitle) || bullet.text || '',
  );
  const sourceTag = firstCitation?.sourceTag || firstCitation?.sourceName || '';
  const tags = Array.from(new Set([sourceTag, ...(firstCitation?.tags || [])].filter(Boolean))).slice(0, 5);
  return {
    title,
    description: truncateText(rawDescription, MAX_DESCRIPTION_LENGTH),
    tags,
    temperature: firstCitation?.temperature || { level: 'cool', label: 'Background', icon: '•' },
  };
}

function temperatureClass(temperature) {
  const level = String(temperature?.level || 'cool').toLowerCase();
  return ['hot', 'warm', 'cool'].includes(level) ? level : 'cool';
}

function resolveDataUrl(path) {
  const value = String(path || '');
  return value.startsWith('data/') ? value : `data/${value}`;
}

function briefingDayKey(briefing) {
  return localDateKey(briefing?.generatedAt || new Date().toISOString());
}

function safeLocalStorageGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeLocalStorageSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Ignore storage failures so the PWA still renders offline data.
  }
}

function retentionDaysFromManifest(manifest) {
  const value = Number(manifest?.retentionDays);
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : DEFAULT_RETENTION_DAYS;
}

function hasOwn(object, key) {
  return Object.prototype.hasOwnProperty.call(object, key);
}

function seenItemStorageKey(dayKey, itemId) {
  return `${dayKey}:${String(itemId || '').trim()}`;
}

function retentionCutoffDayKey(dayKey, retentionDays) {
  const [year, month, day] = String(dayKey || '').split('-').map(Number);
  if (!year || !month || !day) return null;
  const cutoff = new Date(Date.UTC(year, month - 1, day));
  cutoff.setUTCDate(cutoff.getUTCDate() - Math.max(retentionDays - 1, 0));
  return cutoff.toISOString().slice(0, 10);
}

function pruneSeenBriefingItems(entries, dayKey, retentionDays) {
  const cutoffDayKey = retentionCutoffDayKey(dayKey, retentionDays);
  return Object.fromEntries(
    Object.entries(entries || {}).filter(([storageKey]) => {
      const [entryDayKey] = storageKey.split(':');
      return !cutoffDayKey || entryDayKey >= cutoffDayKey;
    }),
  );
}

function createSeenBriefingState(briefing, manifest) {
  const dayKey = briefingDayKey(briefing);
  const retentionDays = retentionDaysFromManifest(manifest);
  let parsedEntries = {};
  try {
    parsedEntries = JSON.parse(safeLocalStorageGet(SEEN_BRIEFING_ITEMS_STORAGE_KEY) || '{}');
  } catch {
    parsedEntries = {};
  }
  if (!parsedEntries || Array.isArray(parsedEntries) || typeof parsedEntries !== 'object') {
    parsedEntries = {};
  }
  const entries = pruneSeenBriefingItems(parsedEntries, dayKey, retentionDays);
  if (JSON.stringify(entries) !== JSON.stringify(parsedEntries)) {
    safeLocalStorageSet(SEEN_BRIEFING_ITEMS_STORAGE_KEY, JSON.stringify(entries));
  }
  return { dayKey, entries, seenKeys: new Set(Object.keys(entries)) };
}

function bulletItemIds(briefing, bullet, sectionIndex, bulletIndex) {
  const itemIds = Array.from(new Set((bullet.citations || []).filter(Boolean).map((itemId) => String(itemId))));
  const fallbackBriefingId = briefing.id || briefing.generatedAt || 'briefing';
  return itemIds.length ? itemIds : [`${fallbackBriefingId}:${sectionIndex}:${bulletIndex}`];
}

function isSeenBriefingItem(seenState, itemIds) {
  return itemIds.every((itemId) => seenState.seenKeys.has(seenItemStorageKey(seenState.dayKey, itemId)));
}

function setBulletSeenState(bulletEl, seen) {
  if (!bulletEl) return;
  if (bulletEl.dataset.seenState === (seen ? 'seen' : 'new')) return;
  const statusEl = bulletEl.querySelector('.bullet__status');
  bulletEl.dataset.seenState = seen ? 'seen' : 'new';
  bulletEl.classList.toggle('bullet--seen', seen);
  bulletEl.classList.toggle('bullet--hidden', hideSeenEnabled && seen);
  if (!statusEl) return;
  statusEl.textContent = seen ? 'Seen' : 'New';
  statusEl.classList.toggle('bullet__status--seen', seen);
  statusEl.classList.toggle('bullet__status--new', !seen);
}

function applyHideSeenFilter() {
  const bullets = Array.from(briefingEl.querySelectorAll('[data-seen-state]'));
  bullets.forEach((bulletEl) => {
    bulletEl.classList.toggle('bullet--hidden', hideSeenEnabled && bulletEl.dataset.seenState === 'seen');
  });
  const button = briefingEl.querySelector('#hideSeenButton');
  if (!button) return;
  button.textContent = hideSeenEnabled ? 'Show seen' : 'Hide seen';
  button.setAttribute('aria-pressed', hideSeenEnabled ? 'true' : 'false');
}

function bindHideSeenButton() {
  const button = briefingEl.querySelector('#hideSeenButton');
  if (!button) return;
  button.addEventListener('click', () => {
    hideSeenEnabled = !hideSeenEnabled;
    safeLocalStorageSet(HIDE_SEEN_STORAGE_KEY, hideSeenEnabled ? '1' : '0');
    applyHideSeenFilter();
  });
  applyHideSeenFilter();
}

function markSeenBriefingItems(seenState, itemIds) {
  let changed = false;
  itemIds.forEach((itemId) => {
    const storageKey = seenItemStorageKey(seenState.dayKey, itemId);
    if (seenState.seenKeys.has(storageKey)) return;
    seenState.entries[storageKey] = new Date().toISOString();
    seenState.seenKeys.add(storageKey);
    changed = true;
  });
  if (changed) {
    safeLocalStorageSet(SEEN_BRIEFING_ITEMS_STORAGE_KEY, JSON.stringify(seenState.entries));
  }
  return changed;
}

function markBriefingBulletSeen(bulletEl, seenState) {
  const itemIds = String(bulletEl?.dataset?.seenItemIds || '')
    .split(',')
    .map((itemId) => itemId.trim())
    .filter(Boolean);
  if (!itemIds.length) return;
  markSeenBriefingItems(seenState, itemIds);
  setBulletSeenState(bulletEl, true);
}

function observeBriefingItems(seenState) {
  if (briefingSeenObserver) {
    briefingSeenObserver.disconnect();
    briefingSeenObserver = null;
  }
  const bullets = Array.from(briefingEl.querySelectorAll('[data-seen-item-ids]'));
  if (!bullets.length) return;
  if (!('IntersectionObserver' in window)) {
    bullets.forEach((bulletEl) => markBriefingBulletSeen(bulletEl, seenState));
    return;
  }
  briefingSeenObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting || entry.intersectionRatio < 0.6) return;
        markBriefingBulletSeen(entry.target, seenState);
        briefingSeenObserver?.unobserve(entry.target);
      });
    },
    { threshold: [0.6] },
  );
  bullets.forEach((bulletEl) => {
    if (bulletEl.dataset.seenState === 'seen') return;
    briefingSeenObserver.observe(bulletEl);
  });
}

function renderBriefing(briefing, seenState) {
  const citations = citationMap(briefing);
  const hasMultipleSections = (briefing.sections || []).length > 1;
  const sections = (briefing.sections || [])
    .map((section, sectionIndex) => {
      const bullets = (section.bullets || [])
        .map((bullet, bulletIndex) => {
          const normalized = normalizeBullet(bullet, citations);
          const temperature = normalized.temperature;
          const temperatureLevel = temperatureClass(temperature);
          const itemIds = bulletItemIds(briefing, bullet, sectionIndex, bulletIndex);
          const seen = isSeenBriefingItem(seenState, itemIds);
          const links = (bullet.citations || [])
            .map((itemId) => citations.get(itemId))
            .filter(Boolean)
            .map(
              (citation) =>
                `<a class="citation" href="${escapeHtml(citation.url)}" target="_blank" rel="noopener noreferrer">${citation.publishedAt ? `${escapeHtml(formatDate(citation.publishedAt))} · ` : ''}${escapeHtml(citation.sourceName)}</a>`,
            )
            .join('');
          const tags = normalized.tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('');
          return `<li class="bullet bullet--${temperatureLevel}${seen ? ' bullet--seen' : ''}" data-seen-item-ids="${escapeHtml(itemIds.join(','))}" data-seen-state="${seen ? 'seen' : 'new'}"><div class="bullet__heading"><span class="temperature temperature--${temperatureLevel}" title="${escapeHtml(temperature.label || 'Importance')}">${escapeHtml(temperature.icon || '•')}</span><h4>${escapeHtml(normalized.title)}</h4><span class="bullet__status bullet__status--${seen ? 'seen' : 'new'}">${seen ? 'Seen' : 'New'}</span></div><p>${escapeHtml(normalized.description)}</p>${tags ? `<div class="tag-list">${tags}</div>` : ''}<div class="citations">${links}</div></li>`;
        })
        .join('');
      return `<section class="section">${hasMultipleSections ? `<h3>${escapeHtml(section.title)}</h3>` : ''}<ul class="bullet-list">${bullets}</ul></section>`;
    })
    .join('');

  briefingEl.innerHTML = `
    <p class="meta">Generated ${formatDate(briefing.generatedAt)}</p>
    <div class="briefing-controls"><button id="hideSeenButton" class="button button--compact" type="button" aria-pressed="${hideSeenEnabled ? 'true' : 'false'}">${hideSeenEnabled ? 'Show seen' : 'Hide seen'}</button></div>
    ${sections}
    ${briefing.provider?.type === 'fake' ? '<p class="provider-note">Deterministic fallback summary. Add a Copilot token secret for AI-written briefings.</p>' : ''}
  `;
  bindHideSeenButton();
}

function renderHero(briefing) {
  const citations = citationMap(briefing);
  const topBullet = briefing.sections?.[0]?.bullets?.[0];
  const normalized = topBullet ? normalizeBullet(topBullet, citations) : null;
  heroHeadlineEl.textContent = normalized?.title || truncateText(briefing.headline, MAX_HEADLINE_LENGTH);
  heroSummaryEl.textContent = normalized?.description || 'No notable updates were found in today’s rolling briefing.';
}

function renderSources(status) {
  const sources = (status.sources || [])
    .slice()
    .sort((sourceA, sourceB) => sourceA.sourceId.localeCompare(sourceB.sourceId));
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
      const briefing = await getJson(resolveDataUrl(yamlPath.replace(/\.yaml$/, '.json')));
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

async function registerBackgroundNotifications(registration) {
  if (!registration) return;
  if ('periodicSync' in registration) {
    let status = null;
    try {
      if ('permissions' in navigator && navigator.permissions?.query) {
        status = await navigator.permissions.query({ name: 'periodic-background-sync' });
      }
    } catch {
      status = null;
    }
    try {
      if (status?.state !== 'denied') {
        await registration.periodicSync.register(BACKGROUND_SYNC_TAG, { minInterval: 60 * 60 * 1000 });
        return;
      }
    } catch {
      // Ignore unsupported periodic background sync checks and fall back to open-app notifications.
    }
  }
  if ('sync' in registration) {
    try {
      await registration.sync.register(BACKGROUND_SYNC_TAG);
    } catch {
      // Ignore unsupported one-off background sync registration.
    }
  }
}

function syncLatestBriefing(registration, briefing, latest) {
  const worker = registration?.active || registration?.waiting || registration?.installing;
  if (!worker?.postMessage) return;
  worker.postMessage({
    type: 'sync-latest-briefing',
    latestBriefingUrl: latest.latestBriefingUrl,
    headline: briefing.headline,
  });
}

async function enableNotifications(registration, briefing, latest) {
  if (!('Notification' in window) || !registration?.showNotification) return;
  notifyButton.hidden = Notification.permission === 'denied';
  notifyButton.textContent = Notification.permission === 'granted' ? 'Hourly update notifications enabled' : 'Notify me when a new hourly update lands';
  notifyButton.disabled = Notification.permission === 'granted';
  if (Notification.permission === 'granted') {
    await registerBackgroundNotifications(registration);
  }
  notifyButton.addEventListener('click', async () => {
    const permission = await Notification.requestPermission();
    notifyButton.textContent = permission === 'granted' ? 'Hourly update notifications enabled' : 'Notifications unavailable';
    notifyButton.disabled = permission === 'granted';
    if (permission === 'granted') {
      await registerBackgroundNotifications(registration);
      syncLatestBriefing(registration, briefing, latest);
    }
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
  syncLatestBriefing(registration, briefing, latest);
}

async function main() {
  try {
    const [latest, buildInfo] = await Promise.all([getJson('data/latest.json'), loadBuildInfo()]);
    const [briefing, status, manifest] = await Promise.all([
      getJson(resolveDataUrl(latest.latestBriefingUrl)),
      getJson('data/sources/status.json'),
      getJson('data/manifest.json'),
    ]);
    const seenState = createSeenBriefingState(briefing, manifest);
    renderHero(briefing);
    renderBriefing(briefing, seenState);
    observeBriefingItems(seenState);
    renderSources(status);
    await renderYesterday(manifest, latest, briefing);
    await renderFooter(buildInfo);
    if ('serviceWorker' in navigator) {
      const registration = await navigator.serviceWorker.register(`sw.js?v=${encodeURIComponent(buildInfo.buildId || 'dev')}`, { updateViaCache: 'none' });
      await registration.update();
      await enableNotifications(registration, briefing, latest);
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
