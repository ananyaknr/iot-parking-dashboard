'use strict';
/* Sample parking data in the same shape as the camera/parking service
   (GET /parking/status and GET /parking/history from vvryw/intelligence-parking-lot).
   Used only when /api/parking/* is unavailable; every page then shows a "Sample data" banner. */
(function () {
  let seed = 28;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  const pick = a => a[Math.floor(rnd() * a.length)];
  const letters = ['กข', 'กท', 'ขค', 'งจ', 'ฒก', 'ฆม', 'ษว', 'นบ', 'พร', 'กย', 'สม', 'ฌษ'];
  const plate = () => `${pick(letters)}${1000 + Math.floor(rnd() * 8999)}`;
  const uuid = () => 'demo-' + Math.floor(rnd() * 1e12).toString(16);
  const iso = t => new Date(t).toISOString();
  const now = Date.now();
  const bays = [['VIP-1', 'vip'], ['VIP-2', 'vip'], ['NORMAL-1', 'normal'], ['NORMAL-2', 'normal'], ['NORMAL-3', 'normal']];
  const sessions = [], events = [];
  for (const [id, kind] of bays) {
    // Each bay hosts visits back-to-back, walking back from now.
    let t = now - rnd() * 50 * 60000;
    const active = id !== 'VIP-2' && id !== 'NORMAL-3';
    for (let i = 0; i < (kind === 'vip' ? 3 : 5); i++) {
      const stay = (15 + rnd() * 90) * 60000;
      const still = active && i === 0;
      const entered = still ? t : t - stay;
      const type = kind === 'vip' ? pick(['sportcar', 'sportcar', 'supercar']) : 'car';
      const s = { id: uuid(), plate: plate(), vehicle_type: type, space_id: id,
        status: still ? 'still_in' : 'left', entered_at: iso(entered), exited_at: still ? null : iso(t),
        entrance_photo_url: null, exit_photo_url: null };
      sessions.push(s);
      events.push({ id: uuid(), camera: 'entrance', plate: s.plate, vehicle_type: type, space_id: id, session_id: s.id,
        approved: true, reason: 'entry_registered', created_at: s.entered_at, photo_url: null });
      if (!still) events.push({ id: uuid(), camera: 'exit', plate: s.plate, vehicle_type: type, space_id: id, session_id: s.id,
        approved: true, reason: 'exit_registered', created_at: s.exited_at, photo_url: null });
      t = entered - (5 + rnd() * 50) * 60000;
    }
  }
  [['entrance', 'recognition_needs_review', 'car'], ['entrance', 'vip_full', 'supercar'],
   ['exit', 'no_active_session', null], ['entrance', 'already_inside', 'car']].forEach(([camera, reason, type], i) => {
    events.push({ id: uuid(), camera, plate: reason === 'recognition_needs_review' ? null : plate(), vehicle_type: type,
      space_id: null, session_id: null, approved: false, reason, created_at: iso(now - (6 + i * 37 + rnd() * 9) * 60000), photo_url: null });
  });
  sessions.sort((a, b) => Date.parse(b.entered_at) - Date.parse(a.entered_at));
  events.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  const spaces = bays.map(([id, kind]) => {
    const s = sessions.find(x => x.space_id === id && x.status === 'still_in');
    return { id, kind, session_id: s ? s.id : null, plate: s ? s.plate : null, vehicle_type: s ? s.vehicle_type : null,
      entered_at: s ? s.entered_at : null, status: s ? 'occupied' : 'free' };
  });
  const capacity = {};
  for (const kind of ['vip', 'normal']) {
    const g = spaces.filter(b => b.kind === kind), occ = g.filter(b => b.status === 'occupied').length;
    capacity[kind] = { total: g.length, occupied: occ, available: g.length - occ, unavailable: 0 };
  }
  window.DEMO_PARKING = {
    status: { capacity, spaces, database: 'sample', storage: 'sample', gate_mode: 'simulation',
      occupancy_source: 'sample', archived_observations: events.length, archived_images: 0 },
    history: { events: events.slice(0, 100), sessions: sessions.slice(0, 100) }
  };
})();
