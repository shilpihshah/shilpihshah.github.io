/* Tabs + VC Pulse dashboard. Reads data.json and pitchbook_snapshot.json (no dependencies). */
(function () {
  // ---------- tabs ----------
  const TABS = ["blog", "dashboard", "about"];
  function route() {
    const t = (location.hash || "#blog").slice(1);
    const tab = TABS.includes(t) ? t : "blog";
    TABS.forEach(n => document.getElementById("tab-" + n).classList.toggle("show", n === tab));
    document.querySelectorAll("#tabs a").forEach(a => a.classList.toggle("active", a.dataset.tab === tab));
    if (tab === "dashboard" && !loaded) load();
    window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", route);

  // ---------- helpers ----------
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = m => m == null ? "Undisclosed" : m >= 1000 ? "$" + (m / 1000).toFixed(m >= 10000 ? 0 : 1) + "B" : m >= 1 ? "$" + (m >= 100 ? Math.round(m) : +m.toFixed(1)) + "M" : "$" + Math.round(m * 1000) + "K";
  const fmtDate = iso => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const STAGE_ORDER = ["Pre-Seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Series E", "Series F", "Series G", "Series H", "Growth", "Other", "Undisclosed"];
  const stageBucket = s => /^Series [C-H]$/.test(s) || s === "Growth" ? "Series C+" : s;
  const median = a => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const stageClass = s => s === "Series A" ? "s-a" : s === "Series B" ? "s-b" : s === "Undisclosed" ? "s-und" : "";

  const PER_PAGE = 8, PER_NEWS = 5;
  let DATA = null, loaded = false, page = 0, sortKey = "date", sortDir = -1, abOnly = false;

  async function getJSON(url) {
    const r = await fetch(url + "?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error(url + " " + r.status);
    return r.json();
  }

  async function load() {
    loaded = true;
    try { DATA = await getJSON("data.json"); }
    catch (e) { $("updated").textContent = "unavailable (serve this folder over http)"; return; }
    renderAll();
    loadPitchbook();
  }
  // re-pull every 15 minutes while open
  setInterval(() => { if (loaded) { getJSON("data.json").then(d => { DATA = d; renderAll(); }).catch(() => {}); } }, 15 * 60 * 1000);

  function renderAll() {
    const gen = new Date(DATA.generated_at);
    $("updated").textContent = gen.toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
    buildFilters(); kpis(); charts(); table(); news(); sources();
  }

  function spanLabel() {
    const ds = DATA.rounds.map(r => new Date(r.date)); if (!ds.length) return "";
    return "since " + fmtDate(new Date(Math.min(...ds)).toISOString());
  }
  // ---------- KPIs ----------
  function kpis() {
    const R = DATA.rounds, now = new Date(DATA.generated_at), wk = R.filter(r => now - new Date(r.date) <= 7 * 864e5);
    const wkDollars = wk.reduce((s, r) => s + (r.amount_musd || 0), 0);
    $("k-week").textContent = wk.length;
    $("k-week-sub").textContent = money(wkDollars) + " disclosed";
    const top = R.filter(r => r.amount_musd != null).sort((a, b) => b.amount_musd - a.amount_musd)[0];
    if (top) { $("k-max").textContent = money(top.amount_musd); $("k-max-sub").innerHTML = esc(top.company) + " · " + esc(top.stage === "Undisclosed" ? "stage n/a" : top.stage); }
    const counts = {}; R.forEach(r => { if (r.stage !== "Undisclosed" && r.stage !== "Other") { const b = stageBucket(r.stage); counts[b] = (counts[b] || 0) + 1; } });
    const best = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
    if (best) { $("k-stage").textContent = best[0]; $("k-stage-sub").textContent = best[1] + " of " + R.length + " rounds " + spanLabel(); }
    const mA = median(R.filter(r => r.stage === "Series A" && r.amount_musd != null).map(r => r.amount_musd));
    const mB = median(R.filter(r => r.stage === "Series B" && r.amount_musd != null).map(r => r.amount_musd));
    $("k-ab").textContent = (mA ? money(mA) : "–") + " / " + (mB ? money(mB) : "–");
    $("k-ab-sub").textContent = R.filter(r => r.stage === "Series A").length + " A · " + R.filter(r => r.stage === "Series B").length + " B rounds tracked";
  }

  // ---------- charts (inline SVG) ----------
  function barsV(el, rows, hi) {
    const W = 480, H = 220, pad = { l: 30, r: 8, t: 14, b: 34 }, max = Math.max(1, ...rows.map(r => r[1]));
    const bw = (W - pad.l - pad.r) / rows.length;
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Rounds by stage">`;
    for (let i = 0; i <= 4; i++) { const y = pad.t + (H - pad.t - pad.b) * i / 4, v = Math.round(max * (1 - i / 4));
      s += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}" stroke="#e6edf5"/><text x="${pad.l - 6}" y="${y + 4}" font-size="11" text-anchor="end" fill="#8494a6">${v}</text>`; }
    rows.forEach(([k, v], i) => {
      const h = (H - pad.t - pad.b) * v / max, x = pad.l + i * bw + bw * .18, y = H - pad.b - h;
      s += `<rect x="${x}" y="${y}" width="${bw * .64}" height="${h}" rx="3" fill="${hi.includes(k) ? "#1F4E79" : "#9cc3e6"}"><title>${k}: ${v}</title></rect>`;
      s += `<text x="${x + bw * .32}" y="${y - 4}" font-size="12" text-anchor="middle" fill="#1F4E79">${v}</text>`;
      s += `<text x="${x + bw * .32}" y="${H - pad.b + 16}" font-size="11.5" text-anchor="middle" fill="#5b6b7c">${k.replace("Series ", "Ser. ")}</text>`;
    });
    el.innerHTML = s + "</svg>";
  }
  function barsH(el, rows) {
    const W = 480, rowH = 24, pad = { l: 150, r: 56, t: 4 }, H = pad.t + rows.length * rowH + 4, max = Math.max(1, ...rows.map(r => r[1]));
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Disclosed capital by sector">`;
    rows.forEach(([k, v], i) => {
      const y = pad.t + i * rowH, w = (W - pad.l - pad.r) * v / max;
      s += `<text x="${pad.l - 8}" y="${y + 16}" font-size="12.5" text-anchor="end" fill="#33475b">${esc(k)}</text>`;
      s += `<rect x="${pad.l}" y="${y + 4}" width="${Math.max(2, w)}" height="${rowH - 9}" rx="3" fill="${i === 0 ? "#1F4E79" : "#5b9bd5"}"><title>${esc(k)}: $${Math.round(v)}M</title></rect>`;
      s += `<text x="${pad.l + w + 6}" y="${y + 16}" font-size="12" fill="#1F4E79">${money(v)}</text>`;
    });
    el.innerHTML = s + "</svg>";
  }
  function charts() {
    const R = DATA.rounds, order = ["Pre-Seed", "Seed", "Series A", "Series B", "Series C+", "Undisclosed"], c = {};
    R.forEach(r => { const b = r.stage === "Other" ? "Undisclosed" : stageBucket(r.stage); c[b] = (c[b] || 0) + 1; });
    barsV($("chart-stage"), order.map(k => [k, c[k] || 0]), ["Series A", "Series B"]);
    $("c1-sub").textContent = spanLabel();
    const sec = {}; R.forEach(r => { if (r.amount_musd) { const t = r.sectors[0]; sec[t] = (sec[t] || 0) + r.amount_musd; } });
    barsH($("chart-sector"), Object.entries(sec).sort((a, b) => b[1] - a[1]).slice(0, 8));
  }

  // ---------- table ----------
  function buildFilters() {
    const st = $("f-stage"), se = $("f-sector"), sv = st.value, ev = se.value;
    const stages = ["Pre-Seed", "Seed", "Series A", "Series B", "Series C+", "Undisclosed"];
    st.innerHTML = `<option value="">All stages</option>` + stages.map(s => `<option>${s}</option>`).join("");
    const secs = [...new Set(DATA.rounds.flatMap(r => r.sectors))].sort();
    se.innerHTML = `<option value="">All sectors</option>` + secs.map(s => `<option>${esc(s)}</option>`).join("");
    st.value = sv; se.value = ev;
  }
  function filtered() {
    const st = $("f-stage").value, se = $("f-sector").value, q = $("f-q").value.trim().toLowerCase();
    let R = DATA.rounds.filter(r => {
      const b = r.stage === "Other" ? "Undisclosed" : stageBucket(r.stage);
      if (abOnly && !(r.stage === "Series A" || r.stage === "Series B")) return false;
      if (st && b !== st) return false;
      if (se && !r.sectors.includes(se)) return false;
      if (q && !(r.company + " " + (r.investors || "") + " " + r.title).toLowerCase().includes(q)) return false;
      return true;
    });
    const key = r => sortKey === "stage" ? STAGE_ORDER.indexOf(r.stage) : sortKey === "amount_musd" ? (r.amount_musd ?? -1) : sortKey === "sectors" ? r.sectors[0] : (r[sortKey] || "").toString().toLowerCase();
    return R.sort((a, b) => (key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0) * sortDir);
  }
  function table() {
    const R = filtered(), tb = document.querySelector("#rounds tbody");
    $("count").textContent = R.length + " of " + DATA.rounds.length + " rounds";
    const pages = Math.max(1, Math.ceil(R.length / PER_PAGE));
    page = Math.min(Math.max(0, page), pages - 1);
    const start = page * PER_PAGE, end = Math.min(start + PER_PAGE, R.length);
    tb.innerHTML = R.slice(start, end).map(r => `<tr>
      <td class="src">${fmtDate(r.date)}</td>
      <td class="co"><a href="${esc(r.link)}" target="_blank" rel="noopener" title="${esc(r.title)}">${esc(r.company)}</a></td>
      <td><span class="stage ${stageClass(r.stage)}">${esc(r.stage)}</span></td>
      <td class="amt">${r.amount_approx ? "≈" : ""}${money(r.amount_musd)}</td>
      <td class="hide-sm">${r.sectors.map(s => `<span class="tag">${esc(s)}</span>`).join("")}</td>
      <td class="inv hide-sm">${esc(r.investors || "–")}</td>
      <td class="src hide-sm">${esc(r.source)}${r.also_reported_by && r.also_reported_by.length ? " +" + r.also_reported_by.length : ""}</td></tr>`).join("")
      || `<tr><td colspan="7" class="empty">No rounds match these filters.</td></tr>`;
    $("pg-info").textContent = R.length ? (end - start > 1 ? (start + 1) + "–" + end : end) + " of " + R.length : "0 of 0";
    $("pg-prev").disabled = page === 0;
    $("pg-next").disabled = page >= pages - 1;
    $("pager").style.display = R.length > PER_PAGE ? "" : "none";
    document.querySelectorAll("#rounds th").forEach(th => th.classList.toggle("sorted", th.dataset.k === sortKey));
  }
  ["f-stage", "f-sector"].forEach(id => $(id).addEventListener("change", () => { page = 0; table(); }));
  $("f-q").addEventListener("input", () => { page = 0; table(); });
  $("f-ab").addEventListener("click", e => { abOnly = !abOnly; e.target.classList.toggle("on", abOnly); e.target.setAttribute("aria-pressed", abOnly); page = 0; table(); });
  const go = d => { page += d; table(); const b = d < 0 ? $("pg-prev") : $("pg-next"); if (b.disabled) (d < 0 ? $("pg-next") : $("pg-prev")).focus(); };
  $("pg-prev").addEventListener("click", () => go(-1));
  $("pg-next").addEventListener("click", () => go(1));
  $("rounds-card").addEventListener("keydown", e => {
    if (e.target.matches("input, select")) return;
    if (e.key === "ArrowLeft" && !$("pg-prev").disabled) { e.preventDefault(); go(-1); }
    if (e.key === "ArrowRight" && !$("pg-next").disabled) { e.preventDefault(); go(1); }
  });
  document.querySelectorAll("#rounds th").forEach(th => th.addEventListener("click", () => {
    const k = th.dataset.k; sortDir = sortKey === k ? -sortDir : (k === "date" || k === "amount_musd" ? -1 : 1); sortKey = k; page = 0; table();
  }));
  document.querySelectorAll("#rounds th").forEach(th => { th.tabIndex = 0; th.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); th.click(); } }); });

  // ---------- news + sources ----------
  function news() {
    const byDate = (a, b) => new Date(b.date) - new Date(a.date);
    const N = DATA.news.filter(n => !n.is_round).sort(byDate);
    const list = (N.length ? N : [...DATA.news].sort(byDate)).slice(0, PER_NEWS);
    $("news").innerHTML = list.map(n => `<li><a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a><span class="src">${esc(n.source)} · ${fmtDate(n.date)}</span></li>`).join("");
  }
  function sources() {
    $("sources").innerHTML = DATA.sources.map(s => `<li><span>${esc(s.source)}</span><span class="${s.ok ? "ok" : "err"}">${s.ok ? s.items + " items · " + s.rounds + " rounds" : "unavailable"}</span></li>`).join("");
  }

  // ---------- PitchBook snapshot ----------
  async function loadPitchbook() {
    const el = $("pitchbook");
    let pb = null;
    try { pb = await getJSON("pitchbook_snapshot.json"); } catch (e) { pb = null; }
    const deals = pb && Array.isArray(pb.deals) ? pb.deals : [];
    if (!deals.length) { el.innerHTML = `<div class="empty"><b>Coming soon</b>Curated PitchBook deal snapshots will be added here periodically.</div>`; return; }
    if (pb.as_of) $("pb-asof").textContent = "as of " + pb.as_of;
    el.innerHTML = `<div class="table-wrap"><table><thead><tr><th>Company</th><th>Stage</th><th class="amt">Deal size</th><th class="amt">Post-money</th><th>Lead</th></tr></thead><tbody>` +
      deals.map(d => `<tr><td class="co">${esc(d.company)}</td><td><span class="stage">${esc(d.stage)}</span></td><td class="amt">${money(d.deal_size_musd)}</td><td class="amt">${d.post_money_musd != null ? money(d.post_money_musd) : "–"}</td><td class="inv">${esc((d.lead_investors || []).join(", "))}</td></tr>`).join("") +
      `</tbody></table></div>`;
  }

  route();
})();
