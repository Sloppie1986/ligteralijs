// "Samen": eigen ijsmetingen (met foto) en het eigen forum, opgeslagen in Supabase.
// Staat uit zolang config.json geen supabase_url en supabase_key bevat.
(() => {
  const $ = id => document.getElementById(id);
  const el = (tag, attrs = {}, kids = []) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null) continue;
      if (k === "text") n.textContent = v; else if (k === "cls") n.className = v;
      else if (k.startsWith("on")) n[k] = v; else n.setAttribute(k, v);
    }
    for (const c of [].concat(kids)) if (c != null && c !== false) n.append(c);
    return n;
  };
  const tz = {timeZone: "Europe/Amsterdam"};
  const nl1 = v => (+v).toLocaleString("nl-NL", {maximumFractionDigits: 1});
  const when = t => new Date(t).toLocaleString("nl-NL", {...tz, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"});
  const store = {get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } },
                 set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} }};

  let sb = null, cfg = {}, user = null, admin = false, pickMode = false, picked = null;

  async function boot() {
    try { cfg = await (await fetch("config.json", {cache: "no-store"})).json(); } catch (e) { return; }
    if (!cfg.supabase_url || !cfg.supabase_key) return;
    await new Promise((ok, bad) => {
      const s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.min.js";
      s.onload = ok; s.onerror = bad; document.head.append(s);
    });
    sb = window.supabase.createClient(cfg.supabase_url, cfg.supabase_key);
    document.querySelectorAll("[data-samen]").forEach(n => n.hidden = false);
    sb.auth.onAuthStateChange((_e, session) => { user = session ? session.user : null; checkAdmin().then(() => { renderAuth(); loadForum(); }); });
    const {data} = await sb.auth.getSession();
    user = data.session ? data.session.user : null;
    await checkAdmin();
    renderAuth();
    loadReports(); loadForum();
    setInterval(loadReports, 5 * 60e3); setInterval(loadForum, 2 * 60e3);
    window.addEventListener("icemap-rendered", drawReports);
    wireForms();
  }

  async function checkAdmin() {
    admin = false;
    if (!user) return;
    const {data} = await sb.from("admins").select("user_id").eq("user_id", user.id);
    admin = !!(data && data.length);
  }
  const myName = () => (user && user.user_metadata && user.user_metadata.name) || store.get("samen-name") || "";
  const photoUrl = p => p ? `${cfg.supabase_url}/storage/v1/object/public/fotos/${p.split("/").map(encodeURIComponent).join("/")}` : null;

  // ---------------- inloggen
  function renderAuth() {
    for (const box of document.querySelectorAll(".samen-auth")) {
      box.replaceChildren();
      if (user) {
        box.append(el("span", {cls: "muted", text: `Ingelogd als ${myName() || user.email}${admin ? " (beheer)" : ""} · `}),
          el("button", {type: "button", cls: "linkbtn", text: "uitloggen", onclick: () => sb.auth.signOut()}));
      } else {
        box.append(el("button", {type: "button", cls: "linkbtn", text: "Inloggen om mee te doen", onclick: () => $("logindlg").showModal()}));
      }
    }
  }
  async function needLogin() {
    if (user) return true;
    $("logindlg").showModal();
    return false;
  }

  // ---------------- foto verkleinen en uploaden
  async function shrink(file) {
    const img = await createImageBitmap(file).catch(() => null);
    if (!img) throw new Error("Deze foto kan ik niet lezen.");
    const s = Math.min(1, 1600 / Math.max(img.width, img.height));
    const c = document.createElement("canvas");
    c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    return await new Promise(ok => c.toBlob(ok, "image/jpeg", 0.82));
  }
  async function upload(file) {
    if (!file) return null;
    const blob = await shrink(file);
    const path = `${user.id}/${crypto.randomUUID()}.jpg`;
    const {error} = await sb.storage.from("fotos").upload(path, blob, {contentType: "image/jpeg"});
    if (error) throw error;
    return path;
  }
  async function saveName(name) {
    store.set("samen-name", name);
    if (user && (user.user_metadata || {}).name !== name) await sb.auth.updateUser({data: {name}});
  }

  // ---------------- metingen
  let reports = [];
  async function loadReports() {
    const since = new Date(Date.now() - 72 * 3600e3).toISOString();
    const {data, error} = await sb.from("reports").select("*").gte("measured_at", since).order("measured_at", {ascending: false}).limit(300);
    if (!error) { reports = data || []; drawReports(); }
  }
  let layer = null;
  function drawReports() {
    const map = window._icemap;
    if (!map || !window.L) return;
    if (!layer) layer = L.layerGroup().addTo(map);
    layer.clearLayers();
    const known = new Set((((window._icedata || {}).ijskaart || {}).points || []).map(p => p.id).filter(Boolean));
    for (const r of reports) {
      if (known.has("sb:" + r.id)) continue;   // staat al op de kaart, met prognose
      const icon = L.divIcon({className: "", iconSize: null, iconAnchor: [20, 13],
        html: `<div class="mpin"><b>${nl1(r.cm)}</b><span class="lvl0">nieuw</span></div>`});
      L.marker([r.lat, r.lon], {icon, title: `${r.place || "Meting"}: ${nl1(r.cm)} cm`}).bindPopup(() => reportPopup(r)).addTo(layer);
    }
  }
  function reportPopup(r) {
    const d = el("div");
    const pu = photoUrl(r.photo);
    d.append(el("strong", {text: r.place || "Eigen meting"}),
      el("div", {text: `Gemeten: ${nl1(r.cm)} cm (${when(r.measured_at)})`}),
      el("div", {cls: "muted", text: "Prognose volgt bij de volgende update (binnen 15 minuten)."}),
      r.note ? el("q", {text: r.note}) : null,
      pu ? el("a", {href: pu, target: "_blank", rel: "noopener"}, [el("img", {src: pu, alt: "Foto bij de meting", cls: "rphoto", loading: "lazy"})]) : null,
      el("div", {cls: "muted", text: "Gemeld door " + r.name}),
      modButtons("reports", r, loadReports));
    return d;
  }
  window.samenPopupExtras = p => {   // foto en beheerknoppen bij gebruikersmetingen die al op de kaart staan
    if (!p.id || !String(p.id).startsWith("sb:")) return null;
    const r = reports.find(x => "sb:" + x.id === p.id);
    const pu = photoUrl(p.photo || (r && r.photo));
    return el("div", {}, [pu ? el("a", {href: pu, target: "_blank", rel: "noopener"}, [el("img", {src: pu, alt: "Foto bij de meting", cls: "rphoto", loading: "lazy"})]) : null,
      r ? modButtons("reports", r, loadReports) : null]);
  };

  function modButtons(table, row, after) {
    if (!user) return null;
    const own = row.user_id === user.id;
    if (!own && !admin) return null;
    const box = el("div", {cls: "modbtns"});
    if (admin && !own) box.append(el("button", {type: "button", cls: "linkbtn", text: row.hidden ? "tonen" : "verbergen", onclick: async () => {
      await sb.from(table).update({hidden: !row.hidden}).eq("id", row.id); after();
    }}));
    box.append(el("button", {type: "button", cls: "linkbtn", text: "verwijderen", onclick: async () => {
      if (!confirm("Weet je zeker dat je dit wilt verwijderen?")) return;
      if (row.photo) await sb.storage.from("fotos").remove([row.photo]);
      await sb.from(table).delete().eq("id", row.id); after();
    }}));
    return box;
  }

  // ---------------- forum
  async function loadForum() {
    if (!sb) return;
    const {data: threads} = await sb.from("posts").select("*").is("parent_id", null).order("created_at", {ascending: false}).limit(40);
    const ids = (threads || []).map(t => t.id);
    let replies = [];
    if (ids.length) {
      const r = await sb.from("posts").select("*").in("parent_id", ids).order("created_at", {ascending: true}).limit(1000);
      replies = r.data || [];
    }
    renderForum(threads || [], replies);
  }
  const open = new Set();
  function renderForum(threads, replies) {
    const box = $("samenforum"); if (!box) return;
    box.replaceChildren();
    if (!threads.length) box.append(el("p", {cls: "muted", text: "Nog geen berichten. Begin de eerste draad."}));
    // draad met de nieuwste activiteit bovenaan
    const last = t => replies.filter(r => r.parent_id === t.id).reduce((m, r) => r.created_at > m ? r.created_at : m, t.created_at);
    threads.sort((a, b) => last(b).localeCompare(last(a)));
    for (const t of threads) {
      const rs = replies.filter(r => r.parent_id === t.id);
      const det = el("details", {cls: "sthread"});
      if (open.has(t.id)) det.open = true;
      det.ontoggle = () => det.open ? open.add(t.id) : open.delete(t.id);
      det.append(el("summary", {}, [el("strong", {text: t.title || t.body.slice(0, 80)}),
        el("span", {cls: "muted", text: ` · ${t.name} · ${when(last(t))} · ${rs.length} ${rs.length === 1 ? "reactie" : "reacties"}${t.hidden ? " · verborgen" : ""}`})]));
      for (const p of [t, ...rs]) det.append(postEl(p));
      const f = el("form", {cls: "sform"}, [
        el("textarea", {name: "body", rows: "2", maxlength: "4000", required: "", placeholder: "Reageer…", "aria-label": "Reactie"}),
        el("div", {cls: "srow"}, [el("label", {cls: "fileb"}, [document.createTextNode("📷 Foto"), el("input", {type: "file", name: "photo", accept: "image/*"})]),
          el("button", {type: "submit", text: "Plaatsen"})])]);
      f.onsubmit = e => { e.preventDefault(); submitPost(f, t.id); };
      det.append(f);
      box.append(det);
    }
  }
  function postEl(p) {
    const pu = photoUrl(p.photo);
    return el("div", {cls: "spost" + (p.hidden ? " hid" : "")}, [
      el("div", {cls: "muted", text: `${p.name} · ${when(p.created_at)}`}),
      el("p", {text: p.body}),
      pu ? el("a", {href: pu, target: "_blank", rel: "noopener"}, [el("img", {src: pu, alt: "Foto bij het bericht", cls: "rphoto", loading: "lazy"})]) : null,
      modButtons("posts", p, loadForum)]);
  }
  async function submitPost(f, parent) {
    if (!(await needLogin())) return;
    if (!myName()) { $("logindlg").showModal(); return; }
    const btn = f.querySelector("button[type=submit]"); btn.disabled = true;
    try {
      const photo = await upload(f.photo.files[0]);
      const row = {name: myName(), body: f.body.value.trim(), parent_id: parent || null, title: f.title ? f.title.value.trim() || null : null, photo};
      const {error} = await sb.from("posts").insert(row);
      if (error) throw error;
      f.reset();
      if (parent) open.add(parent);
      loadForum();
    } catch (e) { alert("Plaatsen lukte niet: " + (e.message || e)); }
    btn.disabled = false;
  }

  // ---------------- formulieren
  function wireForms() {
    // inloggen met e-mail (link per mail, geen wachtwoord)
    const lf = $("loginform");
    lf.name.value = myName();
    lf.onsubmit = async e => {
      e.preventDefault();
      const name = lf.name.value.trim();
      store.set("samen-name", name);
      if (user) { await saveName(name); $("logindlg").close(); renderAuth(); return; }
      const {error} = await sb.auth.signInWithOtp({email: lf.email.value.trim(), options: {emailRedirectTo: location.href.split("#")[0] + "#kaart", data: {name}}});
      $("loginmsg").textContent = error ? "Dat lukte niet: " + error.message : "Check je mail en tik op de link om in te loggen.";
    };
    $("logincancel").onclick = () => $("logindlg").close();

    // nieuwe draad
    const nf = $("newthread");
    nf.onsubmit = e => { e.preventDefault(); submitPost(nf, null); };

    // meting doorgeven
    const rf = $("reportform"), dlg = $("repdlg");
    $("repopen").onclick = async () => {
      if (!(await needLogin())) return;
      rf.name.value = myName();
      rf.when.value = new Date(Date.now() - new Date().getTimezoneOffset() * 60e3).toISOString().slice(0, 16);
      dlg.showModal();
    };
    $("repcancel").onclick = () => dlg.close();
    $("repgps").onclick = () => {
      $("repwhere").textContent = "Locatie zoeken…";
      navigator.geolocation.getCurrentPosition(p => setPick(p.coords.latitude, p.coords.longitude, "je huidige locatie"),
        () => { $("repwhere").textContent = "Locatie niet beschikbaar. Kies de plek op de kaart."; }, {enableHighAccuracy: true, timeout: 15000});
    };
    $("repmap").onclick = () => {
      pickMode = true; dlg.close();
      $("pickhint").hidden = false;
      if (location.hash !== "#kaart") location.hash = "#kaart";
      $("icemap").scrollIntoView({behavior: "smooth", block: "center"});
    };
    const hook = () => {
      if (!window._icemap || window._icemap._samenHook) return;
      window._icemap._samenHook = true;
      window._icemap.on("click", e => {
        if (!pickMode) return;
        pickMode = false; $("pickhint").hidden = true;
        setPick(e.latlng.lat, e.latlng.lng, "de gekozen plek op de kaart");
        dlg.showModal();
      });
    };
    hook(); window.addEventListener("icemap-rendered", hook);
    rf.onsubmit = async e => {
      e.preventDefault();
      if (!picked) { $("repwhere").textContent = "Kies eerst de plek (GPS of op de kaart)."; return; }
      const btn = rf.querySelector("button[type=submit]"); btn.disabled = true;
      $("repmsg").textContent = "Versturen…";
      try {
        await saveName(rf.name.value.trim());
        const photo = await upload(rf.photo.files[0]);
        const row = {name: rf.name.value.trim(), cm: +String(rf.cm.value).replace(",", "."), lat: picked[0], lon: picked[1],
                     place: rf.place.value.trim() || null, note: rf.note.value.trim() || null, photo,
                     measured_at: new Date(rf.when.value).toISOString()};
        const {error} = await sb.from("reports").insert(row);
        if (error) throw error;
        rf.reset(); picked = null; $("repwhere").textContent = ""; $("repmsg").textContent = "";
        dlg.close();
        await loadReports();
      } catch (err) { $("repmsg").textContent = "Versturen lukte niet: " + (err.message || err); }
      btn.disabled = false;
    };
  }
  function setPick(lat, lon, label) {
    if (lat < 50.6 || lat > 53.7 || lon < 3.2 || lon > 7.3) { $("repwhere").textContent = "Die plek ligt buiten Nederland."; return; }
    picked = [+lat.toFixed(5), +lon.toFixed(5)];
    $("repwhere").textContent = `Plek: ${label} (${picked[0].toFixed(4)}, ${picked[1].toFixed(4)})`;
  }

  boot().catch(e => console.error("samen", e));
})();
