/* Tests for the open-now / hours logic in assets/app.js.
 *
 * app.js is a plain browser script, so it is loaded by stubbing the few DOM
 * globals it touches at parse time and re-exporting the pure helpers. This
 * keeps the production file free of test scaffolding. */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = path.join(__dirname, '..', 'assets', 'app.js');

function loadApp() {
    const source = fs.readFileSync(SRC, 'utf8');
    const sandbox = {
        document: { addEventListener() {} },
        navigator: { userAgent: 'node', geolocation: null },
        localStorage: { getItem: () => null, setItem() {} },
        location: { search: '', pathname: '/', href: '/' },
        history: { replaceState() {} },
        console,
        setTimeout,
        Intl,
        URLSearchParams,
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(
        `${source}\nglobalThis.__api = { openState, floridaNow, haversineMiles, `
        + `toMinutes, formatClock, dayOffset, directionsUrl };`,
        sandbox,
    );
    return sandbox.__api;
}

const api = loadApp();

let passed = 0;
const failures = [];

function check(name, actual, expected) {
    const a = JSON.stringify(actual);
    const e = JSON.stringify(expected);
    if (a === e) passed += 1;
    else failures.push(`${name}\n     expected ${e}\n     actual   ${a}`);
}

function assert(name, condition, detail = '') {
    if (condition) passed += 1;
    else failures.push(`${name}${detail ? `\n     ${detail}` : ''}`);
}

/* ---- fixtures ----------------------------------------------------------- */
const DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
const everyDay = (ranges) => Object.fromEntries(DAYS.map((d) => [d, ranges]));

const nightclub = {   // Club Space: Fri 23:00 -> Sat 12:00
    hours: { ...everyDay(null), fri: [['23:00', '12:00']], sat: [['23:00', '12:00']], sun: [['23:00', '10:00']] },
};
const always = { hours: everyDay([['00:00', '24:00']]) };
const nineToFive = { hours: everyDay([['09:00', '17:00']]) };
const closedMonday = { hours: { ...everyDay([['11:00', '18:00']]), mon: null } };
const splitHours = { hours: everyDay([['09:00', '12:00'], ['17:00', '21:00']]) };

/* ---- cross-midnight ----------------------------------------------------- */
// Saturday 02:00 falls inside Friday's 23:00->12:00 window.
assert('nightclub open Sat 02:00 (from Friday night)',
    api.openState(nightclub, 'sat', 2 * 60).open === true);
// Saturday 14:00 is after Friday's window closed at noon and before 23:00.
assert('nightclub closed Sat 14:00',
    api.openState(nightclub, 'sat', 14 * 60).open === false);
// Friday 23:30 is inside Friday's own window.
assert('nightclub open Fri 23:30',
    api.openState(nightclub, 'fri', 23 * 60 + 30).open === true);
// Monday 02:00 — Sunday's window ended at 10:00, so Monday 02:00 is open.
assert('nightclub open Mon 02:00 (from Sunday night)',
    api.openState(nightclub, 'mon', 2 * 60).open === true);
// Thursday 02:00 — Wednesday is closed, so nothing carries over.
assert('nightclub closed Thu 02:00',
    api.openState(nightclub, 'thu', 2 * 60).open === false);

/* ---- 24/7 and plain ranges --------------------------------------------- */
assert('24/7 open at 02:00', api.openState(always, 'tue', 2 * 60).open === true);
assert('24/7 open at 23:59', api.openState(always, 'tue', 23 * 60 + 59).open === true);
assert('9-5 closed at 02:00', api.openState(nineToFive, 'tue', 2 * 60).open === false);
assert('9-5 open at 09:00 exactly', api.openState(nineToFive, 'tue', 9 * 60).open === true);
assert('9-5 closed at 17:00 exactly (end exclusive)',
    api.openState(nineToFive, 'tue', 17 * 60).open === false);

/* ---- split hours ------------------------------------------------------- */
assert('split hours open 10:00', api.openState(splitHours, 'tue', 10 * 60).open === true);
assert('split hours closed 14:00', api.openState(splitHours, 'tue', 14 * 60).open === false);
assert('split hours open 18:00', api.openState(splitHours, 'tue', 18 * 60).open === true);

/* ---- next-opening reporting -------------------------------------------- */
const mondayClosed = api.openState(closedMonday, 'mon', 12 * 60);
assert('closed Monday reports a future opening', mondayClosed.open === false
    && mondayClosed.opensDay === 'tue' && mondayClosed.opensInDays === 1,
    JSON.stringify(mondayClosed));

const beforeOpen = api.openState(nineToFive, 'tue', 7 * 60);
assert('before opening reports same-day open time', beforeOpen.open === false
    && beforeOpen.opensAt === 9 * 60 && beforeOpen.opensInDays === 0,
    JSON.stringify(beforeOpen));

const neverOpen = api.openState({ hours: everyDay(null) }, 'tue', 10 * 60);
assert('a place with no hours is closed and has no opening',
    neverOpen.open === false && neverOpen.opensAt === undefined);

/* ---- helpers ----------------------------------------------------------- */
check('toMinutes 00:00', api.toMinutes('00:00'), 0);
check('toMinutes 24:00', api.toMinutes('24:00'), 1440);
check('toMinutes 09:30', api.toMinutes('09:30'), 570);
check('formatClock noon', api.formatClock(12 * 60), '12pm');
check('formatClock midnight', api.formatClock(0), '12am');
check('formatClock 17:30', api.formatClock(17 * 60 + 30), '5:30pm');
check('formatClock wraps 24:00 to 12am', api.formatClock(1440), '12am');
check('dayOffset wraps backwards', api.dayOffset('sun', -1), 'sat');
check('dayOffset wraps forwards', api.dayOffset('sat', 1), 'sun');

/* ---- timezone independence --------------------------------------------- */
// floridaNow must report Florida's wall clock regardless of the host TZ.
const florida = api.floridaNow();
const expected = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', weekday: 'short', hour: '2-digit',
    minute: '2-digit', hour12: false,
}).formatToParts(new Date());
const expHour = Number(expected.find((p) => p.type === 'hour').value) % 24;
const expMin = Number(expected.find((p) => p.type === 'minute').value);
check(`floridaNow matches America/New_York (TZ=${process.env.TZ || 'host default'})`,
    florida.minutes, expHour * 60 + expMin);
assert('floridaNow returns a valid weekday', DAYS.includes(florida.day), florida.day);

/* ---- distance ---------------------------------------------------------- */
const miamiToFtl = api.haversineMiles(
    { lat: 25.7617, lng: -80.1918 }, { lat: 26.1224, lng: -80.1373 });
assert('Miami -> Fort Lauderdale is roughly 25 miles',
    miamiToFtl > 23 && miamiToFtl < 28, `got ${miamiToFtl.toFixed(1)}`);
check('distance to self is zero',
    Math.round(api.haversineMiles({ lat: 25, lng: -80 }, { lat: 25, lng: -80 })), 0);

/* ---- directions links -------------------------------------------------- */
assert('place id is used when present',
    api.directionsUrl({ title: 'X', mapsPlaceId: 'abc123', address: '1 A St, Miami', lat: 1, lng: 2 })
        .includes('destination_place_id=abc123'));
assert('a street address is used when there is no place id',
    decodeURIComponent(api.directionsUrl(
        { title: 'Lesters', address: '250 Marina Blvd, Fort Lauderdale', lat: 1, lng: 2 }))
        .includes('250 Marina Blvd'));
assert('coordinates are used when the address has no street number',
    api.directionsUrl({ title: 'Lake Eola Park', address: 'Orlando, Florida', lat: 28.5, lng: -81.3 })
        .includes('destination=28.5%2C-81.3'));

/* ---- report ------------------------------------------------------------ */
console.log(`\n  ${passed} passed, ${failures.length} failed`);
if (failures.length) {
    console.log('\nFAILURES:');
    failures.forEach((f, i) => console.log(`  ${i + 1}. ${f}`));
    process.exit(1);
}
console.log('  all hours/geo/link logic OK\n');
