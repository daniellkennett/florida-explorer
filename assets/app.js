/* Florida Explorer — filtering, geolocation, open-now, saved trips, sharing. */

/* ---------------------------------------------------------------- branding */
/* Everything user-facing that identifies the operator lives here. */
const BRAND = {
    name: 'Florida Explorer',
    tagline: 'Curated local experiences',
    heroLead: 'Discover Florida on',
    heroAccent: 'your schedule.',
    heroBody: "Tell us where you are, what time it is, and what you're feeling. " +
              "We'll curate the perfect local experience for you.",
    curatorBadge: 'Local Pick',
    icon: 'fa-map-location-dot',
};

/* ------------------------------------------------------------- constants */
const VENUE_TZ = 'America/New_York';
const DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
const DAY_LABEL = {
    mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday',
    fri: 'Friday', sat: 'Saturday', sun: 'Sunday',
};
const STORAGE_KEY = 'florida-explorer:v1:saved';
const EARTH_RADIUS_MI = 3958.8;

const CITY_META = {
    'Miami': { icon: 'fa-umbrella-beach', lat: 25.7617, lng: -80.1918 },
    'Orlando': { icon: 'fa-wand-magic-sparkles', lat: 28.5384, lng: -81.3789 },
    'Fort Lauderdale': { icon: 'fa-anchor', lat: 26.1224, lng: -80.1373 },
};

const TAG_STYLE = {
    free: { icon: 'fa-piggy-bank', cls: 'text-green-700 bg-green-50 border-green-200' },
    food: { icon: 'fa-utensils', cls: 'text-orange-700 bg-orange-50 border-orange-200' },
    family: { icon: 'fa-children', cls: 'text-blue-700 bg-blue-50 border-blue-200' },
    nightlife: { icon: 'fa-martini-glass-citrus', cls: 'text-purple-700 bg-purple-50 border-purple-200' },
    nature: { icon: 'fa-tree', cls: 'text-teal-700 bg-teal-50 border-teal-200' },
    art: { icon: 'fa-palette', cls: 'text-pink-700 bg-pink-50 border-pink-200' },
    outdoors: { icon: 'fa-person-hiking', cls: 'text-lime-700 bg-lime-50 border-lime-200' },
    beach: { icon: 'fa-water', cls: 'text-cyan-700 bg-cyan-50 border-cyan-200' },
    seafood: { icon: 'fa-fish', cls: 'text-sky-700 bg-sky-50 border-sky-200' },
    cuban: { icon: 'fa-mug-hot', cls: 'text-amber-700 bg-amber-50 border-amber-200' },
    architecture: { icon: 'fa-landmark', cls: 'text-stone-700 bg-stone-50 border-stone-200' },
};

/* "Vibe" chips. `free` is a hard budget constraint; the rest are tastes that
   OR together, because a user ticking two of them means "either is fine". */
const VIBES = [
    { id: 'free', label: 'No spending (Free)', icon: 'fa-piggy-bank', colour: 'text-green-500', kind: 'constraint' },
    { id: 'food', label: "I'm hungry", icon: 'fa-utensils', colour: 'text-orange-400', kind: 'taste' },
    { id: 'family', label: 'Family Friendly', icon: 'fa-children', colour: 'text-blue-400', kind: 'taste' },
    { id: 'nightlife', label: 'Nightlife', icon: 'fa-martini-glass-citrus', colour: 'text-purple-500', kind: 'taste' },
    { id: 'outdoors', label: 'Outdoors', icon: 'fa-person-hiking', colour: 'text-lime-600', kind: 'taste' },
    { id: 'art', label: 'Arts & Culture', icon: 'fa-palette', colour: 'text-pink-500', kind: 'taste' },
];

/* ----------------------------------------------------------------- helpers */
function toMinutes(hhmm) {
    const [h, m] = hhmm.split(':').map(Number);
    return h * 60 + m;
}

function formatClock(minutes) {
    const total = ((minutes % 1440) + 1440) % 1440;
    const h24 = Math.floor(total / 60);
    const m = total % 60;
    const suffix = h24 >= 12 ? 'pm' : 'am';
    const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
    return m === 0 ? `${h12}${suffix}` : `${h12}:${String(m).padStart(2, '0')}${suffix}`;
}

/* Current wall-clock time where the venues are, not where the browser is.
   A client demoing from Seattle must still see Florida's opening hours. */
function floridaNow() {
    const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: VENUE_TZ, weekday: 'short', hour: '2-digit',
        minute: '2-digit', hour12: false,
    }).formatToParts(new Date());

    const get = (type) => parts.find((p) => p.type === type)?.value ?? '';
    const weekday = get('weekday').toLowerCase().slice(0, 3);
    // Intl can emit hour "24" at midnight in some engines; normalise to 0.
    const hour = Number(get('hour')) % 24;
    return {
        day: DAYS.includes(weekday) ? weekday : 'mon',
        minutes: hour * 60 + Number(get('minute')),
    };
}

function dayOffset(day, delta) {
    const i = DAYS.indexOf(day);
    return DAYS[(i + delta + 7) % 7];
}

/* Open/closed for a place at a given day + minute-of-day.
   Handles ranges that cross midnight by also testing the previous day's
   ranges, which is where naive implementations get this wrong. */
function openState(place, day, minutes) {
    const ranges = place.hours?.[day] || [];
    for (const [from, to] of ranges) {
        const start = toMinutes(from);
        let end = toMinutes(to);
        if (end <= start) end += 1440;          // crosses midnight
        if (minutes >= start && minutes < end) {
            return { open: true, closesAt: end % 1440, crossesMidnight: end > 1440 };
        }
    }

    // A range that began yesterday may still be running now.
    for (const [from, to] of place.hours?.[dayOffset(day, -1)] || []) {
        const start = toMinutes(from);
        const end = toMinutes(to);
        if (end <= start && minutes < end) {
            return { open: true, closesAt: end, crossesMidnight: true };
        }
    }

    // Closed: report the next opening within the coming week.
    for (let ahead = 0; ahead < 8; ahead += 1) {
        const d = dayOffset(day, ahead);
        for (const [from] of place.hours?.[d] || []) {
            const start = toMinutes(from);
            if (ahead > 0 || start > minutes) {
                return { open: false, opensAt: start, opensDay: d, opensInDays: ahead };
            }
        }
    }
    return { open: false };
}

function haversineMiles(a, b) {
    const rad = Math.PI / 180;
    const dLat = (b.lat - a.lat) * rad;
    const dLng = (b.lng - a.lng) * rad;
    const h = Math.sin(dLat / 2) ** 2
        + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
    return 2 * EARTH_RADIUS_MI * Math.asin(Math.sqrt(h));
}

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

/* Google Maps deep link. A precise place id is used when we have one; most
   places only have a verified address, which Maps resolves reliably. Places
   geocoded to a park or district centroid have no street number, so those
   fall back to coordinates rather than an ambiguous name search. */
function directionsUrl(place) {
    const base = 'https://www.google.com/maps/dir/?api=1';
    if (place.mapsPlaceId) {
        return `${base}&destination=${encodeURIComponent(place.title)}`
            + `&destination_place_id=${encodeURIComponent(place.mapsPlaceId)}`;
    }
    const hasStreetNumber = /\d/.test((place.address || '').split(',')[0] || '');
    const target = hasStreetNumber
        ? `${place.title}, ${place.address}`
        : `${place.lat},${place.lng}`;
    return `${base}&destination=${encodeURIComponent(target)}`;
}

function appleMapsUrl(place) {
    return `https://maps.apple.com/?daddr=${place.lat},${place.lng}`
        + `&q=${encodeURIComponent(place.title)}`;
}

function isApplePlatform() {
    return /iPhone|iPad|iPod|Macintosh/.test(navigator.userAgent);
}

/* -------------------------------------------------------------- the app */
const app = {
    places: [],
    saved: new Set(),
    position: null,          // { lat, lng } once the user shares location
    locationState: 'idle',   // idle | asking | granted | denied | unavailable
    showSavedOnly: false,
    lastRendered: [],

    /* ------------------------------------------------------------ storage */
    loadSaved() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            this.saved = new Set(raw ? JSON.parse(raw) : []);
        } catch (err) {
            this.saved = new Set();     // private mode or corrupt value
        }
    },

    persistSaved() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify([...this.saved]));
        } catch (err) {
            /* Storage unavailable (private browsing); saves last for the session. */
        }
    },

    toggleSaved(id) {
        if (this.saved.has(id)) this.saved.delete(id);
        else this.saved.add(id);
        this.persistSaved();
        this.updateSavedBadge();
        this.render();
    },

    updateSavedBadge() {
        const n = this.saved.size;
        document.querySelectorAll('[data-saved-count]').forEach((el) => {
            el.textContent = n ? String(n) : '';
            el.classList.toggle('hidden', n === 0);
        });
    },

    /* ----------------------------------------------------------- controls */
    readControls() {
        const city = document.querySelector('input[name="city"]:checked')?.value
            || Object.keys(CITY_META)[0];
        const vibes = [...document.querySelectorAll('.vibe-input:checked')]
            .map((el) => el.value);
        return {
            city,
            time: document.getElementById('time-input').value || '18:00',
            vibes,
            openNow: document.getElementById('open-now-toggle').checked,
        };
    },

    timeBucket(timeStr) {
        const hour = Number(timeStr.split(':')[0]);
        if (hour >= 5 && hour < 12) return 'Morning';
        if (hour >= 12 && hour < 17) return 'Afternoon';
        if (hour >= 17 && hour < 21) return 'Evening';
        return 'Night';
    },

    /* ------------------------------------------------------------ filtering */
    /* Returned in relevance order. `relaxed` reports which constraint had to be
       dropped to produce any results at all, so the UI can say so plainly. */
    select(controls) {
        const tastes = controls.vibes.filter(
            (v) => VIBES.find((x) => x.id === v)?.kind === 'taste');
        const wantsFree = controls.vibes.includes('free');
        const bucket = this.timeBucket(controls.time);
        const now = floridaNow();

        const base = this.places.filter((p) => {
            if (this.showSavedOnly && !this.saved.has(p.id)) return false;
            if (!this.showSavedOnly && p.city !== controls.city) return false;
            if (wantsFree && !p.price.free) return false;
            // Tastes OR together.
            if (tastes.length && !tastes.some((t) => p.tags.includes(t))) return false;
            return true;
        });

        const withTime = base.filter((p) => p.times.includes(bucket));
        const withOpen = withTime.filter(
            (p) => !controls.openNow || openState(p, now.day, now.minutes).open);

        let results = withOpen;
        let relaxed = null;
        if (!results.length && withTime.length) {
            results = withTime;
            relaxed = 'open now';
        } else if (!results.length && base.length) {
            results = base;
            relaxed = `${bucket.toLowerCase()} hours`;
        }

        return { results: this.sort(results, now), relaxed, bucket, now };
    },

    sort(list, now) {
        const here = this.position;
        return [...list].sort((a, b) => {
            if (here) {
                const d = haversineMiles(here, a) - haversineMiles(here, b);
                if (Math.abs(d) > 0.01) return d;
            }
            if (a.recommended !== b.recommended) return a.recommended ? -1 : 1;
            const ao = openState(a, now.day, now.minutes).open;
            const bo = openState(b, now.day, now.minutes).open;
            if (ao !== bo) return ao ? -1 : 1;
            return a.title.localeCompare(b.title);
        });
    },

    /* ----------------------------------------------------------- rendering */
    render() {
        const controls = this.readControls();
        const { results, relaxed, bucket, now } = this.select(controls);
        this.lastRendered = results;

        document.getElementById('time-context').textContent =
            `Showing ${bucket.toLowerCase()} recommendations.`;

        const title = document.getElementById('results-title');
        title.innerHTML = this.showSavedOnly
            ? 'Your <span class="text-brand-600">saved places</span>'
            : `Recommended in <span class="text-brand-600">${escapeHtml(controls.city)}</span>`;

        const count = document.getElementById('results-count');
        count.textContent = `${results.length} ${results.length === 1 ? 'place' : 'places'}`;

        const notice = document.getElementById('relaxed-notice');
        if (relaxed) {
            notice.innerHTML = `<i class="fa-solid fa-circle-info mr-2"></i>`
                + `Nothing matched exactly, so we relaxed the <strong>${escapeHtml(relaxed)}</strong> filter.`;
            notice.classList.remove('hidden');
        } else {
            notice.classList.add('hidden');
        }

        const grid = document.getElementById('results-grid');
        const empty = document.getElementById('empty-state');
        grid.innerHTML = '';

        if (!results.length) {
            grid.classList.add('hidden');
            empty.classList.remove('hidden');
            document.getElementById('empty-message').textContent = this.showSavedOnly
                ? "You haven't saved any places yet. Tap the heart on a card to keep it here."
                : "We couldn't find anything for these filters. Try clearing them or changing the time.";
        } else {
            grid.classList.remove('hidden');
            empty.classList.add('hidden');
            grid.innerHTML = results.map((p) => this.cardHtml(p, now)).join('');
        }

        document.getElementById('results-live').textContent =
            `${results.length} places found${relaxed ? `, ${relaxed} filter relaxed` : ''}.`;

        this.syncUrl(controls);
    },

    openLabel(place, now) {
        const state = openState(place, now.day, now.minutes);
        if (state.open) {
            const left = ((state.closesAt - now.minutes) + 1440) % 1440;
            if (left <= 60) {
                return { cls: 'bg-amber-100 text-amber-800',
                         text: `Closes in ${left} min` };
            }
            return { cls: 'bg-green-100 text-green-700', text: 'Open now' };
        }
        if (state.opensAt !== undefined) {
            const when = state.opensInDays === 0
                ? `Opens ${formatClock(state.opensAt)}`
                : `Opens ${DAY_LABEL[state.opensDay].slice(0, 3)} ${formatClock(state.opensAt)}`;
            return { cls: 'bg-slate-100 text-slate-600', text: when };
        }
        return { cls: 'bg-slate-100 text-slate-600', text: 'Hours vary' };
    },

    cardHtml(place, now) {
        const tags = place.tags.slice(0, 3).map((tag) => {
            const style = TAG_STYLE[tag]
                || { icon: 'fa-tag', cls: 'text-slate-600 bg-slate-50 border-slate-200' };
            return `<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${style.cls} capitalize">
                        <i class="fa-solid ${style.icon} mr-1.5"></i>${escapeHtml(tag)}
                    </span>`;
        }).join('');

        const price = place.price.free
            ? '<span class="px-2 py-1 bg-green-100 text-green-700 text-xs font-bold rounded">FREE</span>'
            : `<span class="px-2 py-1 bg-white/95 text-slate-700 text-xs font-bold rounded tracking-widest">${'$'.repeat(Math.max(1, place.price.level))}</span>`;

        const badge = place.recommended
            ? `<div class="absolute top-3 left-3 z-10">
                   <span class="px-2 py-1 bg-gradient-to-r from-yellow-400 to-yellow-600 text-white text-xs font-bold rounded-md inline-flex items-center shadow-lg border border-yellow-300">
                       <i class="fa-solid fa-star mr-1.5 text-[10px]"></i>${escapeHtml(BRAND.curatorBadge)}
                   </span>
               </div>`
            : '';

        const open = this.openLabel(place, now);
        const distance = this.position
            ? `<span class="inline-flex items-center text-xs font-medium text-slate-500">
                   <i class="fa-solid fa-location-arrow mr-1.5 text-brand-500"></i>
                   ${haversineMiles(this.position, place).toFixed(1)} mi away
               </span>`
            : `<span class="text-xs font-medium text-slate-400">${escapeHtml(place.neighborhood)}</span>`;

        const isSaved = this.saved.has(place.id);
        const img = place.image;
        const repLabel = img?.representative
            ? `<span class="absolute bottom-2 left-2 px-1.5 py-0.5 rounded bg-black/55 text-white text-[10px] font-medium"
                     title="A representative photo, not this exact venue">Representative image</span>`
            : '';

        return `
        <article class="bg-white rounded-2xl shadow-stripe border border-slate-100 overflow-hidden hover:shadow-stripe-lg lift hover:-translate-y-1 group flex flex-col h-full relative">
            ${badge}
            <div class="relative h-48 overflow-hidden bg-slate-100">
                ${img?.file
                    ? `<img src="${escapeHtml(img.file)}" alt="${escapeHtml(img.alt || place.title)}"
                            loading="lazy" decoding="async"
                            class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                            onerror="app.imageFailed(this)">`
                    : `<div class="img-fallback w-full h-full"><i class="fa-solid fa-image"></i></div>`}
                ${repLabel}
                <div class="absolute top-3 right-3 flex items-center gap-2">
                    ${price}
                </div>
                <button type="button" class="absolute bottom-2 right-2 w-9 h-9 rounded-full bg-white/90 hover:bg-white shadow flex items-center justify-center transition-colors"
                        aria-pressed="${isSaved}"
                        aria-label="${isSaved ? 'Remove' : 'Save'} ${escapeHtml(place.title)}"
                        onclick="app.toggleSaved('${place.id}')">
                    <i class="fa-${isSaved ? 'solid' : 'regular'} fa-heart ${isSaved ? 'text-rose-500' : 'text-slate-400'}"></i>
                </button>
            </div>
            <div class="p-5 flex-1 flex flex-col">
                <div class="flex flex-wrap gap-2 mb-3">${tags}</div>
                <h3 class="text-xl font-bold text-slate-900 mb-1 leading-tight">${escapeHtml(place.title)}</h3>
                <div class="flex items-center gap-2 mb-3">
                    <span class="px-2 py-0.5 rounded-full text-[11px] font-semibold ${open.cls}">${escapeHtml(open.text)}</span>
                    ${distance}
                </div>
                <p class="text-slate-500 text-sm flex-1 leading-relaxed">${escapeHtml(place.description)}</p>
                <div class="mt-5 pt-4 border-t border-slate-100 flex justify-between items-center gap-3">
                    <span class="text-xs font-medium text-slate-400 truncate" title="${escapeHtml(place.price.detail)}">
                        <i class="fa-solid fa-tag mr-1"></i>${escapeHtml(place.price.detail)}
                    </span>
                    <button type="button" class="shrink-0 text-brand-600 hover:text-brand-700 font-semibold text-sm inline-flex items-center group/btn"
                            onclick="app.openDetail('${place.id}')">
                        Details <i class="fa-solid fa-arrow-right ml-1 group-hover/btn:translate-x-1 transition-transform"></i>
                    </button>
                </div>
            </div>
        </article>`;
    },

    imageFailed(img) {
        const wrap = document.createElement('div');
        wrap.className = 'img-fallback w-full h-full';
        wrap.innerHTML = '<i class="fa-solid fa-image"></i>';
        img.replaceWith(wrap);
    },

    /* -------------------------------------------------------- detail modal */
    openDetail(id) {
        const place = this.places.find((p) => p.id === id);
        if (!place) return;
        const now = floridaNow();
        const open = this.openLabel(place, now);

        const rows = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].map((d) => {
            const ranges = place.hours?.[d];
            const text = ranges && ranges.length
                ? ranges.map(([a, b]) => (a === '00:00' && b === '24:00'
                    ? 'Open 24 hours'
                    : `${formatClock(toMinutes(a))} – ${formatClock(toMinutes(b))}`)).join(', ')
                : 'Closed';
            const isToday = d === now.day;
            return `<tr class="${isToday ? 'font-semibold text-slate-900' : 'text-slate-500'}">
                        <td class="py-1 pr-4">${DAY_LABEL[d]}${isToday ? ' (today)' : ''}</td>
                        <td class="py-1">${escapeHtml(text)}</td>
                    </tr>`;
        }).join('');

        const credit = place.image?.artist
            ? `<p class="text-[11px] text-slate-400 mt-2">
                   Photo: ${escapeHtml(place.image.artist)} — ${escapeHtml(place.image.licence || '')}
                   ${place.image.sourceUrl ? `· <a class="underline" href="${escapeHtml(place.image.sourceUrl)}" target="_blank" rel="noopener noreferrer">source</a>` : ''}
               </p>`
            : '';

        const distance = this.position
            ? `<p class="text-sm text-slate-500 mt-1"><i class="fa-solid fa-location-arrow mr-2 text-brand-500"></i>${haversineMiles(this.position, place).toFixed(1)} miles from you</p>`
            : '';

        document.getElementById('modal-content').innerHTML = `
            <div class="relative">
                ${place.image?.file
                    ? `<img src="${escapeHtml(place.image.file)}" alt="${escapeHtml(place.image.alt || place.title)}"
                            class="w-full h-56 object-cover" onerror="app.imageFailed(this)">`
                    : '<div class="img-fallback w-full h-56"><i class="fa-solid fa-image"></i></div>'}
                <button type="button" onclick="app.closeDetail()"
                        class="absolute top-3 right-3 w-9 h-9 rounded-full bg-white/90 hover:bg-white shadow flex items-center justify-center"
                        aria-label="Close details">
                    <i class="fa-solid fa-xmark text-slate-700"></i>
                </button>
            </div>
            <div class="p-6">
                <div class="flex items-start justify-between gap-4">
                    <div>
                        <h2 id="modal-title" class="text-2xl font-bold text-slate-900">${escapeHtml(place.title)}</h2>
                        <p class="text-sm text-slate-500">${escapeHtml(place.neighborhood)}, ${escapeHtml(place.city)}</p>
                    </div>
                    <span class="shrink-0 px-2.5 py-1 rounded-full text-xs font-semibold ${open.cls}">${escapeHtml(open.text)}</span>
                </div>

                <p class="text-slate-600 mt-4 leading-relaxed">${escapeHtml(place.description)}</p>

                <dl class="mt-5 grid sm:grid-cols-2 gap-4 text-sm">
                    <div>
                        <dt class="font-semibold text-slate-700">Price</dt>
                        <dd class="text-slate-500">${escapeHtml(place.price.detail)}</dd>
                    </div>
                    <div>
                        <dt class="font-semibold text-slate-700">Address</dt>
                        <dd class="text-slate-500">${escapeHtml(place.address || '—')}</dd>
                        ${distance}
                    </div>
                </dl>

                <h3 class="font-semibold text-slate-700 mt-5 mb-2 text-sm uppercase tracking-wider">Opening hours</h3>
                <table class="text-sm w-full"><tbody>${rows}</tbody></table>
                <p class="text-[11px] text-slate-400 mt-2">
                    Source: ${escapeHtml(place.hours_source || 'Curated')} · last verified ${escapeHtml(place.last_verified || 'unknown')}.
                    Hours change — please confirm with the venue.
                </p>

                <div class="mt-6 flex flex-wrap gap-3">
                    <a href="${escapeHtml(directionsUrl(place))}" target="_blank" rel="noopener noreferrer"
                       class="px-4 py-2.5 rounded-xl bg-brand-600 hover:bg-brand-700 text-white font-semibold text-sm inline-flex items-center">
                        <i class="fa-solid fa-diamond-turn-right mr-2"></i>Directions
                    </a>
                    ${isApplePlatform()
                        ? `<a href="${escapeHtml(appleMapsUrl(place))}" target="_blank" rel="noopener noreferrer"
                              class="px-4 py-2.5 rounded-xl bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-semibold text-sm inline-flex items-center">
                               <i class="fa-brands fa-apple mr-2"></i>Apple Maps
                           </a>` : ''}
                    ${place.website
                        ? `<a href="${escapeHtml(place.website)}" target="_blank" rel="noopener noreferrer"
                              class="px-4 py-2.5 rounded-xl bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-semibold text-sm inline-flex items-center">
                               <i class="fa-solid fa-globe mr-2"></i>Website
                           </a>` : ''}
                    <button type="button" onclick="app.toggleSaved('${place.id}'); app.openDetail('${place.id}')"
                            class="px-4 py-2.5 rounded-xl bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-semibold text-sm inline-flex items-center">
                        <i class="fa-${this.saved.has(place.id) ? 'solid' : 'regular'} fa-heart mr-2 ${this.saved.has(place.id) ? 'text-rose-500' : ''}"></i>
                        ${this.saved.has(place.id) ? 'Saved' : 'Save'}
                    </button>
                </div>
                ${credit}
            </div>`;

        const modal = document.getElementById('modal');
        this.lastFocus = document.activeElement;
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.body.style.overflow = 'hidden';
        this.trapFocus(modal);
        modal.querySelector('button, a')?.focus();
    },

    closeDetail() {
        const modal = document.getElementById('modal');
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.body.style.overflow = '';
        this.releaseFocus();
        if (this.lastFocus instanceof HTMLElement) this.lastFocus.focus();
    },

    trapFocus(modal) {
        this.focusHandler = (event) => {
            if (event.key === 'Escape') {
                this.closeDetail();
                return;
            }
            if (event.key !== 'Tab') return;
            const focusable = [...modal.querySelectorAll(
                'a[href], button:not([disabled]), input, [tabindex]:not([tabindex="-1"])')]
                .filter((el) => el.offsetParent !== null);
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        };
        document.addEventListener('keydown', this.focusHandler);
    },

    releaseFocus() {
        if (this.focusHandler) document.removeEventListener('keydown', this.focusHandler);
        this.focusHandler = null;
    },

    /* ---------------------------------------------------------- geolocation */
    requestLocation() {
        const status = document.getElementById('geo-status');
        if (!navigator.geolocation) {
            this.locationState = 'unavailable';
            status.textContent = 'Location is not supported by this browser.';
            return;
        }
        this.locationState = 'asking';
        status.textContent = 'Finding you…';

        navigator.geolocation.getCurrentPosition(
            (pos) => {
                this.position = { lat: pos.coords.latitude, lng: pos.coords.longitude };
                this.locationState = 'granted';

                const nearest = Object.entries(CITY_META)
                    .map(([name, meta]) => [name, haversineMiles(this.position, meta)])
                    .sort((a, b) => a[1] - b[1])[0];

                const [cityName, miles] = nearest;
                const input = document.querySelector(`input[name="city"][value="${cityName}"]`);
                if (input) input.checked = true;

                status.innerHTML = miles > 150
                    ? `You're about ${Math.round(miles)} mi from ${escapeHtml(cityName)} — showing it anyway. `
                      + `<button type="button" class="underline" onclick="app.clearLocation()">Use manual pick</button>`
                    : `Sorted by distance from you. Nearest city: ${escapeHtml(cityName)}. `
                      + `<button type="button" class="underline" onclick="app.clearLocation()">Clear</button>`;
                document.getElementById('geo-button').classList.add('hidden');
                this.render();
            },
            (err) => {
                this.locationState = err.code === err.PERMISSION_DENIED ? 'denied' : 'unavailable';
                status.textContent = err.code === err.PERMISSION_DENIED
                    ? 'Location declined — pick a city manually instead.'
                    : "Couldn't get your location — pick a city manually instead.";
            },
            { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
        );
    },

    clearLocation() {
        this.position = null;
        this.locationState = 'idle';
        document.getElementById('geo-status').textContent = '';
        document.getElementById('geo-button').classList.remove('hidden');
        this.render();
    },

    /* ------------------------------------------------------------ url state */
    syncUrl(controls) {
        const params = new URLSearchParams();
        params.set('city', controls.city);
        params.set('time', controls.time);
        if (controls.vibes.length) params.set('vibes', controls.vibes.join(','));
        if (controls.openNow) params.set('open', '1');
        if (this.showSavedOnly) params.set('view', 'saved');
        const url = `${location.pathname}?${params}`;
        history.replaceState(null, '', url);
    },

    applyUrl() {
        const params = new URLSearchParams(location.search);
        const city = params.get('city');
        if (city && CITY_META[city]) {
            const input = document.querySelector(`input[name="city"][value="${city}"]`);
            if (input) input.checked = true;
        }
        const time = params.get('time');
        if (time && /^\d{2}:\d{2}$/.test(time)) {
            document.getElementById('time-input').value = time;
        }
        (params.get('vibes') || '').split(',').filter(Boolean).forEach((v) => {
            const el = document.querySelector(`.vibe-input[value="${v}"]`);
            if (el) el.checked = true;
        });
        if (params.get('open') === '1') {
            document.getElementById('open-now-toggle').checked = true;
        }
        if (params.get('view') === 'saved') this.showSavedOnly = true;
        return params.has('time');
    },

    showSaved(on) {
        this.showSavedOnly = on;
        document.getElementById('city-fieldset').classList.toggle('opacity-40', on);
        document.querySelectorAll('input[name="city"]').forEach((el) => { el.disabled = on; });
        document.getElementById('saved-view-note').classList.toggle('hidden', !on);
        this.render();
    },

    resetFilters() {
        document.querySelectorAll('.vibe-input').forEach((el) => { el.checked = false; });
        document.getElementById('open-now-toggle').checked = false;
        if (this.showSavedOnly) this.showSaved(false);
        else this.render();
    },

    async shareView() {
        const url = location.href;
        const note = document.getElementById('share-note');
        try {
            if (navigator.share && /Mobi|Android/i.test(navigator.userAgent)) {
                await navigator.share({ title: BRAND.name, url });
                return;
            }
            await navigator.clipboard.writeText(url);
            note.textContent = 'Link copied.';
        } catch (err) {
            note.textContent = 'Copy the address bar to share this view.';
        }
        setTimeout(() => { note.textContent = ''; }, 2500);
    },

    /* ----------------------------------------------------------------- init */
    buildControls() {
        document.getElementById('city-options').innerHTML =
            Object.entries(CITY_META).map(([name, meta], i) => `
                <div>
                    <input type="radio" id="city-${i}" name="city" value="${escapeHtml(name)}"
                           class="sr-only city-input" ${i === 0 ? 'checked' : ''}>
                    <label for="city-${i}"
                           class="cursor-pointer inline-block px-5 py-2.5 rounded-full text-sm font-medium bg-slate-50 text-slate-600 border border-slate-200 transition-all hover:bg-slate-100">
                        <i class="fa-solid ${meta.icon} mr-2"></i>${escapeHtml(name)}
                    </label>
                </div>`).join('');

        document.getElementById('vibe-options').innerHTML = VIBES.map((v) => `
            <div>
                <input type="checkbox" id="vibe-${v.id}" value="${v.id}" class="sr-only chip-input vibe-input">
                <label for="vibe-${v.id}"
                       class="cursor-pointer inline-flex items-center px-4 py-2 rounded-xl text-sm font-medium bg-white text-slate-600 border border-slate-200 transition-all hover:bg-slate-50 shadow-stripe-sm">
                    <i class="fa-solid ${v.icon} mr-2 ${v.colour}"></i>${escapeHtml(v.label)}
                </label>
            </div>`).join('');
    },

    applyBrand() {
        document.title = `${BRAND.name} | ${BRAND.tagline}`;
        document.querySelectorAll('[data-brand-name]').forEach((el) => {
            el.textContent = BRAND.name;
        });
        document.getElementById('brand-icon').className = `fa-solid ${BRAND.icon} text-sm`;
        document.getElementById('hero-title').innerHTML =
            `${escapeHtml(BRAND.heroLead)} <span class="text-transparent bg-clip-text bg-gradient-to-r from-brand-500 to-indigo-600">${escapeHtml(BRAND.heroAccent)}</span>`;
        document.getElementById('hero-body').textContent = BRAND.heroBody;
    },

    bindEvents() {
        // Delegated: the chips are rebuilt from config, so listeners live on the
        // container rather than on inline attributes.
        document.getElementById('controls').addEventListener('change', () => this.render());

        document.getElementById('geo-button')
            .addEventListener('click', () => this.requestLocation());
        document.getElementById('reset-filters')
            .addEventListener('click', () => this.resetFilters());
        document.getElementById('share-button')
            .addEventListener('click', () => this.shareView());

        document.querySelectorAll('[data-saved-link]').forEach((el) => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                this.showSaved(!this.showSavedOnly);
            });
        });

        const nav = document.getElementById('mobile-nav');
        const burger = document.getElementById('nav-toggle');
        burger.addEventListener('click', () => {
            const open = nav.classList.toggle('hidden');
            burger.setAttribute('aria-expanded', String(!open));
        });

        document.getElementById('modal').addEventListener('click', (e) => {
            if (e.target.id === 'modal') this.closeDetail();
        });
    },

    async init() {
        this.applyBrand();
        this.buildControls();
        this.loadSaved();
        this.bindEvents();

        try {
            const res = await fetch('data/places.json', { cache: 'no-cache' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            this.places = await res.json();
        } catch (err) {
            document.getElementById('results-grid').innerHTML = `
                <div class="col-span-full p-6 bg-white rounded-2xl border border-rose-200 text-center">
                    <p class="font-semibold text-slate-900">Couldn't load the places list.</p>
                    <p class="text-sm text-slate-500 mt-1">${escapeHtml(err.message)}. If you opened this file directly,
                    serve the folder over HTTP instead — browsers block local fetches.</p>
                </div>`;
            return;
        }

        const hadUrlState = this.applyUrl();
        if (!hadUrlState) {
            // Default to the actual current Florida time, not a fixed hour.
            const now = floridaNow();
            document.getElementById('time-input').value =
                `${String(Math.floor(now.minutes / 60)).padStart(2, '0')}:${String(now.minutes % 60).padStart(2, '0')}`;
        }
        if (this.showSavedOnly) this.showSaved(true);

        this.updateSavedBadge();
        this.render();
    },
};

document.addEventListener('DOMContentLoaded', () => app.init());
