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
    // inloglink kwam eerder terug als "#kaart#access_token=…"; dat kan supabase-js niet lezen
    const h = location.hash, at = h.indexOf("access_token=");
    const fromLink = at > 0 || /error_description=/.test(h);
    if (at > 1) history.replaceState(null, "", location.pathname + location.search + "#" + h.slice(at));
    sb = window.supabase.createClient(cfg.supabase_url, cfg.supabase_key);
    document.querySelectorAll("[data-samen]").forEach(n => n.hidden = false);
    sb.auth.onAuthStateChange((_e, session) => { user = session ? session.user : null; checkAdmin().then(() => { renderAuth(); loadForum(); }); });
    const {data} = await sb.auth.getSession();
    user = data.session ? data.session.user : null;
    await checkAdmin();
    syncPrefsFromAccount();
    renderAuth();
    wirePrefs();
    if (fromLink) {
      // tokens uit de adresbalk halen en naar het forum gaan
      history.replaceState(null, "", location.pathname + location.search + "#" + (getPrefs().tab || "forum"));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
      if (!user) alert("Deze inloglink is verlopen of al gebruikt. Vraag een nieuwe aan via 'Inloggen'.");
    }
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
        box.append(el("span", {cls: "authpill", text: `✓ Ingelogd als ${myName() || user.email}${admin ? " · beheerder" : ""}`}),
          el("button", {type: "button", cls: "linkbtn", text: "⚙ voorkeuren", onclick: openPrefs}),
          el("button", {type: "button", cls: "linkbtn", text: "uitloggen", onclick: () => sb.auth.signOut()}));
      } else {
        box.append(el("button", {type: "button", cls: "linkbtn", text: "Inloggen om mee te doen", onclick: () => $("logindlg").showModal()}),
          el("button", {type: "button", cls: "linkbtn", text: "⚙ voorkeuren", onclick: openPrefs}));
      }
    }
  }
  // ---------------- profielfoto
  const myAvatar = () => (user && user.user_metadata && user.user_metadata.avatar) || null;
  function avatarEl(path, name) {
    const u = photoUrl(path);
    if (u) return el("img", {src: u, alt: "", cls: "avatar", loading: "lazy"});
    return el("span", {cls: "avatar ini", "aria-hidden": "true", text: (name || "?").trim().charAt(0).toUpperCase()});
  }
  // nieuwe kolom 'avatar' bestaat pas na het bijgewerkte database-script; zonder die kolom gewoon zonder plaatsen
  async function insertRow(table, row) {
    let {error} = await sb.from(table).insert(row);
    if (error && row.avatar !== undefined && /avatar/.test(error.message || "")) ({error} = await sb.from(table).insert((({avatar, ...r}) => r)(row)));
    return {error};
  }

  // ---------------- persoonlijke voorkeuren
  const getPrefs = () => { try { return JSON.parse(store.get("prefs") || "{}"); } catch (e) { return {}; } };
  const setPrefs = p => store.set("prefs", JSON.stringify(p));
  function syncPrefsFromAccount() {
    const p = user && user.user_metadata && user.user_metadata.prefs;
    if (p && typeof p === "object") setPrefs(Object.assign(getPrefs(), p));
  }
  function openPrefs() {
    const f = $("prefform"), p = getPrefs();
    f.name.value = myName(); f.home.value = (p.home && p.home.name) || ""; f.zoom.value = String((p.home && p.home.zoom) || 10);
    f.tab.value = p.tab || ""; $("prefmsg").textContent = "";
    f.notifyNear.checked = !!p.notifyNear; f.radius.value = p.radius || 30; f.notifyReplies.checked = !!p.notifyReplies;
    f.hi.value = String(p.hi || 8); f.theme.value = p.theme || "";
    $("prefavatar").replaceChildren(avatarEl(myAvatar(), myName()));
    $("prefphoto").hidden = !user; $("prefpw").hidden = !user; f.password.value = "";
    $("prefdlg").showModal();
  }
  async function geocodeHome(q) {
    const u = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free?rows=1&fq=type:(woonplaats OR gemeente)&q=" + encodeURIComponent(q);
    const d = await (await fetch(u)).json();
    const doc = d.response && d.response.docs && d.response.docs[0];
    const m = doc && /POINT\(([\d.]+) ([\d.]+)\)/.exec(doc.centroide_ll || "");
    return m ? {name: doc.woonplaatsnaam || doc.weergavenaam, lat: +m[2], lon: +m[1]} : null;
  }
  function wirePrefs() {
    const f = $("prefform");
    $("prefcancel").onclick = () => $("prefdlg").close();
    f.onsubmit = async e => {
      e.preventDefault();
      const p = getPrefs(), msg = $("prefmsg");
      p.tab = f.tab.value;
      p.notifyNear = f.notifyNear.checked; p.radius = Math.max(5, Math.min(150, +f.radius.value || 30));
      p.notifyReplies = f.notifyReplies.checked; p.hi = +f.hi.value || 8; p.theme = f.theme.value;
      if (p.theme) document.documentElement.dataset.theme = p.theme; else delete document.documentElement.dataset.theme;
      if ((p.notifyNear || p.notifyReplies) && "Notification" in window && Notification.permission === "default") {
        try { await Notification.requestPermission(); } catch (err) {}
      }
      if (p.notifyNear && !(f.home.value.trim())) { msg.textContent = "Vul eerst je plek in voor meldingen in de buurt."; return; }
      const q = f.home.value.trim();
      if (!q) delete p.home;
      else if (!p.home || p.home.name !== q) {
        msg.textContent = "Plek zoeken…";
        const h = await geocodeHome(q).catch(() => null);
        if (!h) { msg.textContent = "Die plaats vind ik niet. Probeer een woonplaats in Nederland."; return; }
        p.home = h; f.home.value = h.name;
      }
      if (p.home) p.home.zoom = +f.zoom.value;
      setPrefs(p);
      const name = f.name.value.trim();
      if (name) store.set("samen-name", name);
      let avatar;
      if (user && f.avatar.files[0]) {
        msg.textContent = "Foto uploaden…";
        try { avatar = await upload(f.avatar.files[0], 256); } catch (err) { msg.textContent = "Foto uploaden lukte niet: " + (err.message || err); return; }
      }
      const pw = f.password.value;
      if (user && pw) {
        if (pw.length < 8) { msg.textContent = "Kies een wachtwoord van minstens 8 tekens."; return; }
        const {error} = await sb.auth.updateUser({password: pw});
        if (error) { msg.textContent = "Wachtwoord opslaan lukte niet: " + error.message; return; }
        f.password.value = "";
      }
      if (user) {
        const {data} = await sb.auth.updateUser({data: {prefs: p, ...(name ? {name} : {}), ...(avatar ? {avatar} : {})}}).catch(() => ({}));
        if (data && data.user) user = data.user;
      }
      f.avatar.value = "";
      $("prefdlg").close();
      renderAuth();
      if (window._icemap) window.iceHome(window._icemap);
      if (window._icedata && window.renderIcemap) window.renderIcemap();
    };
  }

  async function needLogin() {
    if (user) return true;
    $("logindlg").showModal();
    return false;
  }

  // ---------------- foto verkleinen en uploaden
  async function shrink(file, max = 1600) {
    const img = await createImageBitmap(file).catch(() => null);
    if (!img) throw new Error("Deze foto kan ik niet lezen.");
    const s = Math.min(1, max / Math.max(img.width, img.height));
    const c = document.createElement("canvas");
    c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    return await new Promise(ok => c.toBlob(ok, "image/jpeg", 0.82));
  }
  async function upload(file, max = 1600) {
    if (!file) return null;
    const blob = await shrink(file, max);
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
    replyAlerts(threads, replies);
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
  function replyAlerts(threads, replies) {
    if (!user || !getPrefs().notifyReplies || !window.iceNotify) return;
    const mine = new Set(threads.filter(t => t.user_id === user.id).map(t => t.id));
    const key = "seenReplies-" + user.id;
    let seen; try { seen = JSON.parse(store.get(key) || "null"); } catch (e) { seen = null; }
    const first = !seen; seen = seen || [];
    const fresh = replies.filter(r => mine.has(r.parent_id) && r.user_id !== user.id && !seen.includes(r.id));
    if (!first) for (const r of fresh.slice(0, 3)) {
      const t = threads.find(x => x.id === r.parent_id);
      window.iceNotify(`${r.name} reageerde op "${(t && (t.title || t.body) || "").slice(0, 40)}"`, r.body.slice(0, 120), "reply-" + r.id);
    }
    store.set(key, JSON.stringify([...seen, ...fresh.map(r => r.id)].slice(-300)));
  }
  function postEl(p) {
    const pu = photoUrl(p.photo);
    return el("div", {cls: "spost" + (p.hidden ? " hid" : "")}, [
      el("div", {cls: "muted pby"}, [avatarEl(p.avatar, p.name), el("strong", {text: p.name}), document.createTextNode(` · ${when(p.created_at)}`)]),
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
      if (myAvatar()) row.avatar = myAvatar();
      const {error} = await insertRow("posts", row);
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
    const NL_ERR = m => /rate limit/i.test(m) ? "Er zijn net te veel inlogmails verstuurd. Probeer het over een uur opnieuw, of log in met je wachtwoord."
      : /Invalid login/i.test(m) ? "E-mail of wachtwoord klopt niet. Nog geen wachtwoord? Kies 'Wachtwoord vergeten'."
      : /already registered/i.test(m) ? "Dit e-mailadres heeft al een account. Kies 'Inloggen' of 'Wachtwoord vergeten'."
      : /Email not confirmed/i.test(m) ? "Bevestig eerst je e-mailadres via de mail die je kreeg."
      : "Dat lukte niet: " + m;
    lf.onsubmit = async e => {
      e.preventDefault();
      const mode = (e.submitter && e.submitter.value) || "in", msg = $("loginmsg");
      const name = lf.name.value.trim(), email = lf.email.value.trim(), password = lf.password.value;
      if (name) store.set("samen-name", name);
      if (user) { if (name) await saveName(name); $("logindlg").close(); renderAuth(); return; }
      if (!email) { msg.textContent = "Vul je e-mailadres in."; return; }
      msg.textContent = "Even geduld…";
      let res;
      if (mode === "link") {
        res = await sb.auth.signInWithOtp({email, options: {emailRedirectTo: location.href.split("#")[0], data: name ? {name} : {}}});
        msg.textContent = res.error ? NL_ERR(res.error.message) : "Check je mail en tik op de link. Stel daarna in ⚙ voorkeuren een wachtwoord in.";
        return;
      }
      if (password.length < 8) { msg.textContent = "Kies een wachtwoord van minstens 8 tekens."; return; }
      if (mode === "new") {
        if (!name) { msg.textContent = "Vul ook een bijnaam in."; return; }
        res = await sb.auth.signUp({email, password, options: {emailRedirectTo: location.href.split("#")[0], data: {name}}});
        if (!res.error && !res.data.session) { msg.textContent = "Account gemaakt. Bevestig je e-mailadres via de mail en log daarna in."; return; }
      } else {
        res = await sb.auth.signInWithPassword({email, password});
      }
      if (res.error) { msg.textContent = NL_ERR(res.error.message); return; }
      msg.textContent = ""; lf.password.value = "";
      $("logindlg").close();
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
        if (myAvatar()) row.avatar = myAvatar();
        const {error} = await insertRow("reports", row);
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
