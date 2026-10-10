// Veille TLS : journal, favoris, échéances et archives, avec lu / non lu, favoris et articles masqués mémorisés dans le navigateur.
(function () {
  "use strict";
  var CFG = window.VEILLE || {};
  var CATS = CFG.categories || [];
  var CAT = {};
  CATS.forEach(function (c) { CAT[c.key] = c; });
  var MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
  var MOIS_C = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
  var JOURS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
  var PAGE = 40;

  var data = [], episodes = [], weeks = [], weekIdx = 0, latest = "", today = isoLocal(new Date());
  var st = { view: "journal", cat: "all", q: "", period: 7, min: 30, readFilter: "unread", day: "", limit: PAGE };
  var read = loadSet("veilletls.lus"), favs = loadSet("veilletls.favoris"), masked = loadSet("veilletls.masques");
  var toastTimer = 0;

  // ---------- utilitaires ----------
  function $(id) { return document.getElementById(id); }
  function loadSet(key) { try { return new Set(JSON.parse(localStorage.getItem(key) || "[]")); } catch (e) { return new Set(); } }
  function saveSet(key, set) { try { localStorage.setItem(key, JSON.stringify(Array.from(set))); } catch (e) {} }
  function norm(s) { return (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }
  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }
  function isoLocal(d) { return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }
  function days(a, b) { return Math.round((Date.parse(a + "T12:00:00") - Date.parse(b + "T12:00:00")) / 864e5); }
  function prio(s) { return s >= 90 ? ["p1", "P1", "Critique"] : s >= 70 ? ["p2", "P2", "Important"] : s >= 50 ? ["p3", "P3", "Intéressant"] : ["p4", "P4", "Veille"]; }
  function catName(k) { return CAT[k] ? CAT[k].nom : "Autre"; }
  function longDay(iso) { var d = new Date(iso + "T12:00:00"); return JOURS[d.getDay()] + " " + d.getDate() + " " + MOIS[d.getMonth()] + " " + d.getFullYear(); }
  function dayLabel(iso) {
    var diff = days(today, iso), d = new Date(iso + "T12:00:00");
    var txt = JOURS[d.getDay()] + " " + d.getDate() + " " + MOIS[d.getMonth()];
    return diff === 0 ? "Collecte du jour · " + txt : diff === 1 ? "Collecte d'hier · " + txt : "Collecte du " + txt;
  }
  function stamp(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return "";
    var txt = d.getDate() + " " + MOIS[d.getMonth()] + (d.getFullYear() !== new Date().getFullYear() ? " " + d.getFullYear() : "");
    return d.getHours() || d.getMinutes() ? txt + " à " + hour(iso) : txt;
  }
  function journal() { return document.documentElement.dataset.layout === "journal"; }
  function hour(iso) { var d = new Date(iso); return isNaN(d) ? "" : String(d.getHours()).padStart(2, "0") + "h" + String(d.getMinutes()).padStart(2, "0"); }

  // ---------- filtres ----------
  function matches(it, ignoreCat) {
    if (it.score < st.min) return false;
    if (st.day) { if (it.edition !== st.day) return false; }
    else if (days(latest, it.edition) >= st.period) return false;
    if (!ignoreCat && st.cat !== "all" && it.categorie !== st.cat) return false;
    var terms = norm(st.q).split(/\s+/).filter(Boolean);
    if (!terms.length) return true;
    var hay = norm([it.titre, it.resume, it.pourquoi, it.action, it.source, catName(it.categorie)].join(" "));
    return terms.every(function (t) { return hay.indexOf(t) !== -1; });
  }
  function shown(it) { return !masked.has(it.id); }
  function byRead(it) { return st.readFilter === "all" || (st.readFilter === "read") === read.has(it.id); }
  function sortFeed(a, b) { return a.edition !== b.edition ? (a.edition < b.edition ? 1 : -1) : b.score - a.score; }

  // ---------- rendu ----------
  function render() {
    renderTabs();
    renderChannels();
    $("tools").hidden = st.view === "archives" || st.view === "echeances" || st.view === "semaine";
    $("flash").hidden = st.view !== "journal" || !episodes.length;
    renderSide();
    renderPrefs();
    $("v-journal").hidden = st.view !== "journal" && st.view !== "favoris";
    $("v-echeances").hidden = st.view !== "echeances";
    $("v-semaine").hidden = st.view !== "semaine";
    $("v-archives").hidden = st.view !== "archives";
    $("daychip").hidden = !st.day;
    if (st.day) $("daychip-t").textContent = "Édition du " + longDay(st.day);
    if (st.view === "semaine") renderWeek();
    else if (st.view === "echeances") renderDeadlines();
    else if (st.view === "archives") renderArchives();
    else renderFeed();
  }

  // Colonne de droite : prochaines échéances et résumé de la semaine.
  function renderSide() {
    var on = st.view === "journal" || st.view === "favoris";
    var up = data.filter(function (it) { return it.echeance && it.echeance.date >= today; })
      .sort(function (a, b) { return a.echeance.date < b.echeance.date ? -1 : 1; });
    var seen = {}, due = up.filter(function (it) { var k = it.echeance.date + it.echeance.libelle; if (seen[k]) return false; seen[k] = 1; return true; }).slice(0, 4);
    $("side-due").hidden = !on || !due.length;
    $("side-due").innerHTML = '<h2>Prochaines échéances</h2>' + due.map(function (it) {
      var d = new Date(it.echeance.date + "T12:00:00");
      return '<div class="sd"><b>' + d.getDate() + "<small>" + MOIS_C[d.getMonth()] + "</small></b><span>" + esc(it.echeance.libelle) + "</span></div>";
    }).join("") + '<button type="button" class="lnk" data-go="echeances">Toutes les échéances</button>';
    var w = weeks[0], first = w && w.synthese ? (w.synthese.match(/[^.!?]+[.!?]+/g) || [w.synthese]).slice(0, 2).join("").trim() : "";
    $("side-week").hidden = !on || !w;
    if (w) $("side-week").innerHTML = "<h2>La semaine</h2><p>" + esc(first || "Les articles à retenir de la semaine.") + '</p><button type="button" class="lnk" data-go="semaine">Lire le résumé de la semaine</button>';
    var side = !on || ($("flash").hidden && $("side-due").hidden && $("side-week").hidden);
    $("side").hidden = side;
    document.querySelector(".shell").classList.toggle("noside", side);
  }

  function renderPrefs() {
    var light = document.documentElement.dataset.theme === "light";
    $("theme-t").textContent = light ? "Mode sombre" : "Mode clair";
    $("theme-btn").setAttribute("aria-label", light ? "Passer en mode sombre" : "Passer en mode clair");
    var t = longDay(today); $("mast-d").textContent = t.charAt(0).toUpperCase() + t.slice(1);
  }
  function setPref(key, attr, value) {
    document.documentElement.dataset[attr] = value;
    try { localStorage.setItem(key, value); } catch (e) {}
    render();
  }

  function renderTabs() {
    var unread = data.filter(function (it) { return shown(it) && !read.has(it.id); }).length;
    var upcoming = data.filter(function (it) { return it.echeance && it.echeance.date >= today; }).length;
    $("t-journal-n").textContent = unread;
    $("t-favoris-n").textContent = data.filter(function (it) { return favs.has(it.id); }).length;
    $("t-echeances-n").textContent = upcoming;
    document.querySelectorAll(".tab").forEach(function (t) { t.setAttribute("aria-selected", t.dataset.view === st.view); });
  }

  function renderChannels() {
    var pool = data.filter(function (it) { return st.view === "favoris" ? favs.has(it.id) : shown(it) && matches(it, true); });
    var html = '<p class="lbl">Canaux</p>' + channel("all", "Tous les canaux", "", pool);
    CATS.forEach(function (c) {
      html += channel(c.key, c.nom, "Priorité " + c.priorite, pool.filter(function (it) { return it.categorie === c.key; }));
    });
    $("rail").innerHTML = html;
  }
  function channel(key, name, sub, items) {
    var unread = items.filter(function (it) { return !read.has(it.id); }).length;
    var color = key === "all" ? "var(--accent)" : "var(--c-" + key + ")";
    return '<button type="button" class="ch" data-cat="' + key + '" aria-pressed="' + (st.cat === key) + '" style="--cc:' + color + '"><i></i><span>' +
      esc(name) + (sub ? "<small>" + esc(sub) + "</small>" : "") + '</span><em class="' + (unread ? "hot" : "") + '" title="' + unread +
      ' non lu(s) sur ' + items.length + '">' + unread + "</em></button>";
  }


  function renderFeed() {
    var fav = st.view === "favoris";
    var pool = data.filter(function (it) {
      if (fav) return favs.has(it.id) && (st.cat === "all" || it.categorie === st.cat) && (!st.q || matches(Object.assign({}, it, { edition: latest, score: 100 })));
      return shown(it) && matches(it);
    });
    var items = (fav ? pool : pool.filter(byRead)).sort(sortFeed);
    var nRead = pool.filter(function (it) { return read.has(it.id); }).length;
    $("rf-unread").textContent = pool.length - nRead;
    $("rf-read").textContent = nRead;
    document.querySelectorAll("[data-rf]").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.rf === st.readFilter); });
    $("readf").hidden = fav;
    $("unmask").hidden = fav || !masked.size;
    $("unmask").textContent = masked.size > 1 ? "Réafficher les " + masked.size + " articles masqués" : "Réafficher l'article masqué";
    var feed = $("feed");
    if (!items.length) {
      feed.innerHTML = fav ? '<div class="empty">Aucun favori pour l\'instant. Utilisez l\'étoile d\'un article pour le retrouver ici.</div>' :
        st.readFilter === "unread" && !st.q ? allRead(pool) :
        st.readFilter === "read" ? '<div class="empty">Aucun article lu sur ce canal pour cette période.</div>' :
        '<div class="empty">Aucun article ne correspond à ces critères.</div>';
      return;
    }
    var html = "", day = "", n = 0;
    items.slice(0, st.limit).forEach(function (it) {
      if (it.edition !== day) { day = it.edition; html += '<div class="day">' + esc(dayLabel(day)) + "</div>"; }
      html += card(it, n++, n === 1 && journal() && !fav);
    });
    if (items.length > st.limit) html += '<button type="button" class="btn more" data-more>Afficher ' + Math.min(PAGE, items.length - st.limit) + " articles de plus</button>";
    feed.innerHTML = journal() ? '<div class="paper">' + html + "</div>" : html;
  }

  // Plus rien à lire : on propose les favoris et les articles les plus importants de la période.
  function allRead(pool) {
    var html = '<div class="empty ok"><b>✓ Tout est lu.</b> Plus aucun article à lire ici. La prochaine édition arrive demain matin.</div>', n = 0;
    var mine = data.filter(function (it) { return favs.has(it.id) && shown(it) && (st.cat === "all" || it.categorie === st.cat); }).sort(sortFeed).slice(0, 5);
    if (mine.length) html += '<h2 class="done-h">Vos favoris</h2>' + wrap(mine.map(function (it) { return card(it, n++); }).join(""));
    var top = pool.filter(function (it) { return it.score >= 70 && !favs.has(it.id); })
      .sort(function (a, b) { return b.score - a.score || (a.edition < b.edition ? 1 : -1); }).slice(0, 5);
    if (top.length) html += '<h2 class="done-h">Relisez les plus importants<small>Les articles les mieux notés de la période, au cas où un détail vous aurait échappé.</small></h2>' +
      wrap(top.map(function (it) { return card(it, n++); }).join(""));
    return html;
  }

  function wrap(html) { return journal() ? '<div class="paper">' + html + "</div>" : html; }
  function actions(isRead, isFav) {
    return '<div class="act"><button type="button" data-read>' + (isRead ? "Marquer non lu" : "✓ Marquer comme lu") + "</button>" +
      '<button type="button" data-fav aria-pressed="' + isFav + '">' + (isFav ? "★ Favori" : "☆ Favori") + "</button>" +
      '<button type="button" class="np" data-np title="Masquer cet article et apprendre à l\'IA à éviter ce genre de sujet">✕ Non pertinent</button></div>';
  }

  // Affichage « Journal » : présentation de presse, le premier article en une, résumés complets.
  function paperCard(it, une) {
    var p = prio(it.score), isRead = read.has(it.id), isFav = favs.has(it.id);
    return '<article class="ev pa ' + p[0] + (une ? " une" : "") + (isRead ? " read" : "") + '" style="--cc:var(--c-' + esc(it.categorie) + ");--pc:var(--" + p[0] + ')" data-id="' + it.id + '">' +
      '<div class="kick"><span class="tag">' + esc(catName(it.categorie)) + "</span><span>" + p[2] + " · Pertinence : " + it.score + "\u00a0%</span>" +
      (isRead ? '<span class="state lu">Lu</span>' : "") +
      (it.payant ? '<span class="state pay" title="Article payant : non consultable sans abonnement">🔒 Réservé aux abonnés</span>' : "") + "</div>" +
      '<h3><a href="' + esc(it.url) + '" target="_blank" rel="noopener" data-open>' + esc(it.titre) + "</a></h3>" +
      (it.resume ? '<p class="lede">' + esc(it.resume) + "</p>" : "") +
      '<p class="why">' + esc(it.pourquoi) + "</p>" +
      (it.action ? '<p class="todo">' + esc(it.action) + "</p>" : "") +
      (it.echeance ? '<p class="due">Échéance : ' + esc(shortDate(it.echeance.date)) + " · " + esc(it.echeance.libelle) + "</p>" : "") +
      '<p class="src">' + esc(it.source) + (stamp(it.date) ? " · publié le " + stamp(it.date) : "") + "</p>" + actions(isRead, isFav) + "</article>";
  }

  function card(it, n, une) {
    if (journal()) return paperCard(it, une);
    var p = prio(it.score), isRead = read.has(it.id), isFav = favs.has(it.id);
    var due = it.echeance ? '<span class="due">Échéance : ' + esc(shortDate(it.echeance.date)) + " · " + esc(it.echeance.libelle) + "</span>" : "";
    return '<article class="ev ' + p[0] + (isRead ? " read" : "") + '" style="--cc:var(--c-' + esc(it.categorie) + ");--pc:var(--" + p[0] + ");animation-delay:" + Math.min(n, 12) * 30 + 'ms" data-id="' + it.id + '">' +
      '<div class="prio"><span class="led" aria-hidden="true"></span><b>' + it.score + "</b><small>" + p[1] + "<br>" + p[2].toUpperCase() + "</small></div>" +
      '<div class="body"><div class="meta"><span class="tag">' + esc(catName(it.categorie)) + "</span><span>" + esc(it.source) + "</span><span>" + stamp(it.date) + "</span>" +
      (isRead ? '<span class="state lu">LU</span>' : '<span class="state new">NON LU</span>') +
      (it.payant ? '<span class="state pay" title="Article payant : non consultable sans abonnement">🔒 RÉSERVÉ AUX ABONNÉS</span>' : "") + "</div>" +
      '<h3><a href="' + esc(it.url) + '" target="_blank" rel="noopener" data-open>' + esc(it.titre) + "</a></h3>" +
      (it.resume ? "<p>" + esc(it.resume) + "</p>" : "") +
      '<p class="why">' + esc(it.pourquoi) + "</p>" +
      (it.action ? '<p class="todo">' + esc(it.action) + "</p>" : "") + due + actions(isRead, isFav) + "</div></article>";
  }
  function shortDate(iso) { var d = new Date(iso + "T12:00:00"); return d.getDate() + " " + MOIS_C[d.getMonth()] + " " + d.getFullYear(); }

  function renderDeadlines() {
    var items = data.filter(function (it) { return it.echeance; }).sort(function (a, b) { return a.echeance.date < b.echeance.date ? -1 : 1; });
    var up = items.filter(function (it) { return it.echeance.date >= today; });
    var past = items.filter(function (it) { return it.echeance.date < today; }).reverse();
    var html = '<div class="ics">S\'abonner au calendrier dans Google Agenda, Outlook ou sur téléphone : <code>' + esc(CFG.ics || "") +
      '</code><button type="button" class="btn" data-copy="' + esc(CFG.ics || "") + '">Copier le lien</button></div>';
    if (!items.length) html += '<div class="empty">Aucune échéance repérée pour l\'instant. L\'IA les ajoute dès qu\'un texte annonce une date d\'entrée en vigueur ou une date limite.</div>';
    if (up.length) html += '<div class="day">À venir</div>' + up.map(deadline).join("");
    if (past.length) html += '<div class="day">Passées</div>' + past.map(deadline).join("");
    $("v-echeances").innerHTML = html;
  }
  function deadline(it) {
    var d = new Date(it.echeance.date + "T12:00:00"), left = days(it.echeance.date, today);
    var when = left > 0 ? "J-" + left : left === 0 ? "Aujourd'hui" : "Passée";
    return '<article class="dl' + (left < 0 ? " past" : "") + '" style="--cc:var(--c-' + esc(it.categorie) + ')"><div class="date"><b>' + d.getDate() + "</b><span>" +
      MOIS_C[d.getMonth()] + " " + d.getFullYear() + "</span><em>" + when + '</em></div><div class="body"><div class="meta"><span class="tag">' + esc(catName(it.categorie)) +
      "</span><span>" + esc(it.source) + "</span></div><h3>" + esc(it.echeance.libelle) + '</h3><p><a href="' + esc(it.url) + '" target="_blank" rel="noopener">' +
      esc(it.titre) + "</a></p>" + (it.action ? '<p class="todo">' + esc(it.action) + "</p>" : "") + "</div></article>";
  }

  // Résumé de la semaine : synthèse de l'IA, articles à retenir et échéances à venir.
  function renderWeek() {
    var box = $("v-semaine");
    if (!weeks.length) { box.innerHTML = '<div class="empty">Le premier résumé de la semaine sera publié lors du prochain passage du matin.</div>'; return; }
    var w = weeks[weekIdx], byId = {};
    data.forEach(function (it) { byId[it.id] = it; });
    var pick = weeks.length > 1 ? '<select id="week-pick" aria-label="Choisir une semaine">' + weeks.map(function (x, i) {
      return '<option value="' + i + '"' + (i === weekIdx ? " selected" : "") + ">" + esc(x.titre) + (x.en_cours ? " (en cours)" : "") + "</option>"; }).join("") + "</select>" : "";
    var html = '<section class="week"><div class="week-h"><span class="onair"><i></i>' + (w.en_cours ? "Semaine en cours" : "Bilan de la semaine") +
      "</span><h2>" + esc(w.titre) + "</h2>" + pick + "</div>" +
      (w.synthese ? '<div class="week-s">' + w.synthese.split(/\n\s*\n/).map(function (p) { return "<p>" + esc(p.trim()) + "</p>"; }).join("") + "</div>" : "") +
      (w.en_cours ? '<p class="week-n">Mis à jour chaque matin jusqu\'à dimanche. Dernière mise à jour : ' + esc(longDay(w.maj)) + ".</p>" : "") + "</section>";
    var items = w.articles.map(function (id) { return byId[id]; }).filter(Boolean);
    html += '<div class="day">Les ' + items.length + " articles à retenir</div>";
    html += items.length ? wrap(items.map(function (it, n) { return card(it, n); }).join("")) : '<div class="empty">Aucun article important cette semaine.</div>';
    var due = w.echeances.map(function (id) { return byId[id]; }).filter(Boolean);
    if (due.length) html += '<div class="day">Échéances à venir</div>' + due.map(deadline).join("");
    box.innerHTML = html;
    var sel = $("week-pick");
    if (sel) sel.addEventListener("change", function () { weekIdx = +sel.value; renderWeek(); });
  }

  function renderArchives() {
    var byDay = {};
    data.forEach(function (it) { (byDay[it.edition] = byDay[it.edition] || []).push(it); });
    var keys = Object.keys(byDay).sort().reverse(), html = "", month = "";
    keys.forEach(function (k) {
      var m = k.slice(0, 7);
      if (m !== month) {
        if (month) html += "</ul>";
        month = m; var d = new Date(k + "T12:00:00");
        html += '<h2 class="month">' + MOIS[d.getMonth()].replace(/^./, function (c) { return c.toUpperCase(); }) + " " + d.getFullYear() + '</h2><ul class="arch">';
      }
      var counts = [0, 0, 0, 0], unread = 0;
      byDay[k].forEach(function (it) { counts[["p1", "p2", "p3", "p4"].indexOf(prio(it.score)[0])]++; if (!read.has(it.id)) unread++; });
      var parts = ["Critique", "Important", "Intéressant", "Veille"].map(function (l, i) {
        return counts[i] ? '<span style="--pc:var(--p' + (i + 1) + ')"><i>●</i> ' + counts[i] + " " + l.toLowerCase() + "</span>" : "";
      }).join("");
      html += '<li><button type="button" data-day="' + k + '"><span class="d">' + esc(longDay(k)) + '</span><span class="n">' + parts +
        "<span>" + unread + " non lu" + (unread > 1 ? "s" : "") + "</span></span></button></li>";
    });
    $("v-archives").innerHTML = keys.length ? html + "</ul>" : '<div class="empty">Les archives se rempliront au fil des éditions.</div>';
  }



  // Flash audio : le dernier épisode en lecture, les précédents au choix.
  function renderFlash() {
    if (!episodes.length) return;
    var ep = episodes[0], min = Math.max(1, Math.round(ep.duree / 60));
    var older = episodes.length > 1 ? '<select id="flash-ep" aria-label="Choisir un épisode">' + episodes.map(function (e, i) {
      return '<option value="' + i + '">' + esc(longDay(e.date)) + "</option>"; }).join("") + "</select>" : "";
    $("flash").innerHTML = '<div class="flash-h"><span class="onair"><i></i>Flash audio</span><b id="flash-t">' + esc(longDay(ep.date)) +
      '</b><span id="flash-d">' + min + " min</span></div>" +
      '<audio id="flash-a" controls preload="none" src="' + esc(ep.fichier) + '"></audio>' +
      '<p class="flash-s" id="flash-s">Au sommaire : ' + esc(ep.sujets.join(" · ")) + "</p>" +
      '<div class="flash-f">' + older + '<button type="button" class="btn" data-copy="' + esc(CFG.podcast || "") +
      '">Copier le lien du podcast</button></div>';
    var sel = $("flash-ep");
    if (sel) sel.addEventListener("change", function () {
      var e = episodes[+sel.value];
      $("flash-a").src = e.fichier; $("flash-t").textContent = longDay(e.date);
      $("flash-d").textContent = Math.max(1, Math.round(e.duree / 60)) + " min";
      $("flash-s").textContent = "Au sommaire : " + e.sujets.join(" · ");
    });
  }

  // ---------- interactions ----------
  function setView(v) { st.view = v; st.limit = PAGE; if (v !== "journal") st.day = ""; render(); window.scrollTo({ top: 0 }); }
  document.addEventListener("click", function (e) {
    var t = e.target;
    var tab = t.closest(".tab"); if (tab) return setView(tab.dataset.view);
    var go = t.closest("[data-go]"); if (go) return setView(go.dataset.go);
    if (t.closest("#theme-btn")) return setPref("veilletls.theme", "theme", document.documentElement.dataset.theme === "light" ? "dark" : "light");
    var ch = t.closest(".ch");
    if (ch) { st.cat = ch.dataset.cat; st.limit = PAGE; if (st.view !== "journal" && st.view !== "favoris") st.view = "journal"; return render(); }
    var dayBtn = t.closest("[data-day]"); if (dayBtn) { st.day = dayBtn.dataset.day; st.view = "journal"; st.limit = PAGE; render(); return window.scrollTo({ top: 0 }); }
    if (t.closest("[data-more]")) { st.limit += PAGE; return render(); }
    var copy = t.closest("[data-copy]");
    if (copy) {
      var done = function () { copy.textContent = "Lien copié"; };
      try { navigator.clipboard.writeText(copy.dataset.copy).then(done, function () {}); } catch (err) {}
      return;
    }
    var rf = t.closest("[data-rf]"); if (rf) { st.readFilter = rf.dataset.rf; st.limit = PAGE; return render(); }
    if (t.closest("[data-undo]")) { masked.delete(t.closest("[data-undo]").dataset.undo); saveSet("veilletls.masques", masked); hideToast(); return render(); }
    var ev = t.closest(".ev"); if (!ev) return;
    var id = ev.dataset.id;
    if (t.closest("[data-read]")) {
      if (read.has(id)) read.delete(id); else { read.add(id); ev.classList.add("flash"); }
      saveSet("veilletls.lus", read);
      var leaves = st.view === "journal" && st.readFilter !== "all";
      if (leaves) setTimeout(function () { ev.classList.add("gone"); }, read.has(id) ? 300 : 0);
      setTimeout(render, leaves ? (read.has(id) ? 650 : 350) : 0);
    } else if (t.closest("[data-np]")) {
      masked.add(id); saveSet("veilletls.masques", masked);
      ev.classList.add("gone"); setTimeout(render, 350);
      showToast(data.filter(function (it) { return it.id === id; })[0]);
    } else if (t.closest("[data-fav]")) {
      if (favs.has(id)) favs.delete(id); else favs.add(id);
      saveSet("veilletls.favoris", favs); render();
    } else if (t.closest("[data-open]")) {
      read.add(id); saveSet("veilletls.lus", read); setTimeout(render, 300);
    }
  });
  $("q").addEventListener("input", function (e) { st.q = e.target.value; st.limit = PAGE; render(); });
  $("period").addEventListener("change", function (e) { st.period = +e.target.value; st.day = ""; st.limit = PAGE; render(); });
  $("min").addEventListener("change", function (e) { st.min = +e.target.value; st.limit = PAGE; render(); });
  $("unmask").addEventListener("click", function () { masked.clear(); saveSet("veilletls.masques", masked); render(); });
  $("daychip-x").addEventListener("click", function () { st.day = ""; render(); });
  $("ack-all").addEventListener("click", function () {
    data.forEach(function (it) { if (st.view === "favoris" ? favs.has(it.id) : shown(it) && matches(it)) read.add(it.id); });
    saveSet("veilletls.lus", read); render();
  });

  // « Non pertinent » : l'article est masqué ici, et l'administrateur peut transmettre l'avis à l'IA
  // (un ticket GitHub pré-rempli, lu par le passage du matin).
  function avisUrl(it) {
    var body = "Article jugé non pertinent depuis le site Veille TLS.\n\nIdentifiant : " + it.id + "\nTitre : " + it.titre +
      "\nSource : " + it.source + "\nCatégorie : " + catName(it.categorie) + "\nPertinence donnée par l'IA : " + it.score + " %" + "\nLien : " + it.url +
      "\n\nPourquoi (facultatif, une phrase) : ";
    return CFG.avis + "?labels=non-pertinent&title=" + encodeURIComponent("Non pertinent : " + it.titre.slice(0, 120)) + "&body=" + encodeURIComponent(body);
  }
  function showToast(it) {
    if (!it) return;
    var el = $("toast");
    el.innerHTML = "<span>Article masqué.</span>" + (CFG.avis ? '<a href="' + esc(avisUrl(it)) + '" target="_blank" rel="noopener" title="Réservé à l\'administrateur du site (compte GitHub)">Apprendre à l\'IA</a>' : "") +
      '<button type="button" data-undo="' + esc(it.id) + '">Annuler</button>';
    el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(hideToast, 15000);
  }
  function hideToast() { $("toast").hidden = true; }




  function start(articles) {
    data = articles;
    latest = data.reduce(function (m, it) { return it.edition > m ? it.edition : m; }, "") || today;
    if (CFG.updated) $("last").textContent = CFG.updated;
    render();
  }

  if (window.VEILLE_ARTICLES) start(window.VEILLE_ARTICLES);
  else fetch("articles.json", { cache: "no-cache" }).then(function (r) { return r.json(); }).then(start)
    .catch(function () { $("feed").innerHTML = '<div class="empty">Impossible de charger les articles. Vérifie ta connexion puis recharge la page.</div>'; });

  if (!window.VEILLE_ARTICLES) fetch("semaines.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : []; })
    .then(function (list) { weeks = list || []; render(); }).catch(function () {});

  if (!window.VEILLE_ARTICLES) fetch("podcast.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : []; })
    .then(function (list) { episodes = list || []; renderFlash(); render(); }).catch(function () {});

  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("sw.js").catch(function () {});
  }
})();
