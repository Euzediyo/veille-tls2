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

  var byId = {}, data = [], episodes = [], weeks = [], weekIdx = 0, latest = "", today = isoLocal(new Date()), groups = {}, eds = [];
  // Journal au jour le jour : « day » vide = aujourd'hui (ou la dernière édition si la collecte du jour n'a pas eu lieu).
  // Presse française par défaut ; « readFilter » suit les deux cases : non lus, lus, les deux (all) ou aucune (none).
  var DEFAULTS = { press: "fr", cat: "all", q: "", period: 7, min: 30, readFilter: "unread", day: "" };
  var st = Object.assign({ view: "journal", limit: PAGE }, DEFAULTS);
  // Fiches développées en vue compacte (le temps de la visite).
  var opened = new Set();
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
  // Dimensions de l'analyse, jugées séparément : la pertinence ne dit pas l'urgence.
  var LBL = {
    pertinence: { directe: "Pertinence directe", indirecte: "Pertinence indirecte", faible: "Pertinence faible" },
    urgence: { immediate: "Action immédiate", a_anticiper: "À anticiper", information: "Information" },
    statut: { texte_publie: "Texte publié", proposition: "Proposition", negociation: "Négociation", annonce: "Annonce", rumeur: "Rumeur" },
    perimetre: { france: "France", union_europeenne: "Union européenne", autre_pays: "Autre pays" },
    contenu: { article: "début de l'article analysé", extrait: "extrait uniquement", titre: "titre uniquement" }
  };
  var DUE_TYPES = [["obligation", "Obligations"], ["consultation", "Consultations"], ["evenement", "Événements"],
    ["annonce_non_confirmee", "Annonces non confirmées"], ["", "Dates à vérifier"]];
  // Couleur de la fiche : d'après l'urgence quand l'IA l'a jugée, sinon neutre.
  function tone(it) { return { immediate: "p1", a_anticiper: "p2", information: "p3" }[it.urgence] || "p4"; }
  function catName(k) { return CAT[k] ? CAT[k].nom : "Autre"; }
  function inCat(it, key) { return key === "all" || it.categorie === key; }
  function tagHtml(it) { return '<span class="tag">' + esc(catName(it.categorie)) + "</span>"; }
  // Origine de l'article, à côté du titre, là où les deux presses sont mélangées (favoris, semaine, ressources).
  function pressTag(it) { if (st.view === "journal") return ""; return ' <span class="press-t' + (it.international ? " intl" : "") + '">' + (it.international ? "Presse internationale" : "Presse française") + "</span>"; }
  // Presse française (par défaut) ou presse internationale.
  function inPress(it, press) { return press === "all" || (press === "intl") === !!it.international; }
  // Articles qui relatent le même événement : une seule fiche, lue dès qu'un de ses articles est lu.
  function members(it) { return groups[it.groupe || it.id] || [it]; }
  function isRead(it) { return members(it).some(function (m) { return read.has(m.id); }); }
  function collapse(list) {
    var seen = {};
    return list.filter(function (it) { var k = it.groupe || it.id; if (seen[k]) return false; seen[k] = 1; return true; });
  }
  function unreadCount(list) { return collapse(list.filter(function (it) { return !isRead(it); })).length; }
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
  // Date de publication donnée par la source ; certaines sources ne la donnent pas.
  function published(it) {
    var s = stamp(it.date);
    var txt = s ? "publié le " + s : "date de publication inconnue";
    return it.fond ? txt + " · repéré le " + shortDate(it.edition) : txt;
  }
  function journal() { return document.documentElement.dataset.layout === "journal"; }
  function compact() { return document.documentElement.dataset.density === "compacte"; }
  // Poids d'un article pour la une et « L'essentiel » : impact (pertinence et score), urgence,
  // fiabilité (statut) et qualité de l'information réellement lue.
  function weight(it) {
    var w = it.score;
    w += { directe: 20, indirecte: 0, faible: -30 }[it.pertinence] || 0;
    w += { immediate: 30, a_anticiper: 15 }[it.urgence] || 0;
    w += { texte_publie: 10, rumeur: -15 }[it.statut] || 0;
    w += { article: 10, extrait: 4, titre: -15 }[it.contenu] || 0;
    return w + Math.min(6, (members(it).length - 1) * 3);
  }
  function byWeight(a, b) { return weight(b) - weight(a) || b.score - a.score; }
  function hour(iso) { var d = new Date(iso); return isNaN(d) ? "" : String(d.getHours()).padStart(2, "0") + "h" + String(d.getMinutes()).padStart(2, "0"); }

  // ---------- filtres ----------
  function matches(it, ignoreCat, ignorePress, ignoreLevel) {
    if (it.score < st.min) return false;
    if (st.view === "fond") { if (!it.fond) return false; }
    else {
      // Les ressources de fond (articles anciens) ne sont pas présentées comme des actualités.
      if (it.fond) return false;
      if (!ignorePress && !inPress(it, st.press)) return false;
      // Une recherche porte sur la période choisie ; sinon, on lit le journal d'un seul jour.
      if (st.q.trim()) { if (days(latest, it.edition) >= st.period) return false; }
      else if (it.edition !== curDay()) return false;
    }
    if (!ignoreCat && !inCat(it, st.cat)) return false;
    return searched(it);
  }
  function searched(it) {
    var terms = norm(st.q).split(/\s+/).filter(Boolean);
    if (!terms.length) return true;
    var hay = norm([it.titre, it.resume, it.pourquoi, it.action, it.source, catName(it.categorie), it.international ? "international" : ""].join(" "));
    return terms.every(function (t) { return hay.indexOf(t) !== -1; });
  }
  function shown(it) { return !masked.has(it.id); }
  function byRead(it) { if (st.readFilter === "none") return false; return st.readFilter === "all" || (st.readFilter === "read") === isRead(it); }
  function curDay() { return st.day || (latest && eds.indexOf(today) === -1 ? latest : today); }
  function byScore(a, b) { return b.score - a.score || weight(b) - weight(a); }
  function sortFeed(a, b) { return a.edition !== b.edition ? (a.edition < b.edition ? 1 : -1) : b.score - a.score; }
  function sortPublished(a, b) { return (a.date || "") !== (b.date || "") ? ((a.date || "") < (b.date || "") ? 1 : -1) : b.score - a.score; }

  // ---------- rendu ----------
  function render() {
    renderTabs();
    renderChannels();
    $("tools").hidden = st.view === "archives" || st.view === "echeances" || st.view === "semaine";
    $("period").hidden = st.view !== "journal" || !st.q.trim();
    $("flash").hidden = st.view !== "journal" || !episodes.length;
    renderSide();
    renderPrefs();
    renderActive();
    renderDayNav();
    $("rub-h").hidden = st.view !== "journal" || st.cat === "all";
    $("rub-h").textContent = catName(st.cat);
    $("v-journal").hidden = st.view !== "journal" && st.view !== "favoris" && st.view !== "fond";
    $("v-echeances").hidden = st.view !== "echeances";
    $("v-semaine").hidden = st.view !== "semaine";
    $("v-archives").hidden = st.view !== "archives";
    if (st.view === "semaine") renderWeek();
    else if (st.view === "echeances") renderDeadlines();
    else if (st.view === "archives") renderArchives();
    else renderFeed();
  }

  // Colonne de droite : prochaines échéances et résumé de la semaine.
  function renderSide() {
    var on = st.view === "journal" || st.view === "favoris" || st.view === "fond";
    var due = uniqueDue(data).filter(function (it) { return it.echeance.date && upcoming(it.echeance); }).slice(0, 4);
    $("side-due").hidden = !on || !due.length;
    $("side-due").innerHTML = '<h2>Prochaines échéances</h2>' + due.map(function (it) {
      var e = it.echeance, d = new Date(e.date.slice(0, 7) + "-15T12:00:00"), exact = e.precision === "jour";
      return '<div class="sd' + (exact ? "" : " approx") + '"><b>' + (exact ? +e.date.slice(8, 10) : "?") + "<small>" + MOIS_C[d.getMonth()] + "</small></b><span>" +
        esc(e.libelle) + (exact ? "" : "<small>" + esc(dueWhen(e)) + "</small>") + "</span></div>";
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
    document.querySelectorAll("button[data-density]").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.density === (compact() ? "compacte" : "detaillee")); });
  }
  function setPref(key, attr, value) {
    document.documentElement.dataset[attr] = value;
    try { localStorage.setItem(key, value); } catch (e) {}
    render();
  }

  function renderTabs() {
    var unread = unreadCount(data.filter(function (it) { return shown(it) && !it.fond; }));
    var nextDue = uniqueDue(data).filter(function (it) { return it.echeance.date && upcoming(it.echeance); }).length;
    $("t-journal-n").textContent = unread;
    $("t-favoris-n").textContent = data.filter(function (it) { return favs.has(it.id); }).length;
    $("t-echeances-n").textContent = nextDue;
    $("t-fond-n").textContent = data.filter(function (it) { return it.fond && shown(it) && !read.has(it.id); }).length;
    $("t-journal-n").title = unread + " article" + (unread > 1 ? "s" : "") + " non lu" + (unread > 1 ? "s" : "") + " au total";
    document.querySelectorAll(".tab").forEach(function (t) { if (t.dataset.view === st.view) t.setAttribute("aria-current", "page"); else t.removeAttribute("aria-current"); });
  }

  // Rubriques : « Toutes » (tous les canaux) puis un canal par rubrique, avec le nombre d'articles non lus.
  function renderChannels() {
    var pool = data.filter(function (it) { return shown(it) && matches(it, true); });
    var html = channel("all", "Toutes", pool);
    CATS.forEach(function (c) { html += channel(c.key, c.nom, pool.filter(function (it) { return inCat(it, c.key); })); });
    $("rail").innerHTML = html;
  }
  function channel(key, name, items) {
    var unread = unreadCount(items), on = st.view === "journal" && st.cat === key;
    var color = key === "all" ? "var(--accent)" : "var(--c-" + key + ")";
    return '<button type="button" class="ch" data-cat="' + key + '" aria-pressed="' + on + '"' + (on ? ' aria-current="page"' : "") + ' style="--cc:' + color + '">' +
      esc(name) + (unread ? ' <em title="' + unread + ' non lu' + (unread > 1 ? "s" : "") + '">' + unread + "</em>" : "") + "</button>";
  }

  function renderFeed() {
    var fav = st.view === "favoris", fond = st.view === "fond";
    var pool = data.filter(function (it) {
      if (fav) return favs.has(it.id) && inCat(it, st.cat) && searched(it);
      return shown(it) && matches(it);
    });
    // Une seule fiche par événement (la mieux classée), les reprises sont consultables dessous.
    var groupsPool = fav ? pool : collapse(pool.sort(fond ? sortPublished : byScore));
    var items = fav ? pool.sort(sortFeed) : groupsPool.filter(byRead);
    var nRead = groupsPool.filter(isRead).length;
    $("rf-unread").textContent = groupsPool.length - nRead;
    $("rf-read").textContent = nRead;
    $("show-unread").checked = st.readFilter === "unread" || st.readFilter === "all";
    $("show-read").checked = st.readFilter === "read" || st.readFilter === "all";
    $("readf").hidden = fav;
    $("unmask").hidden = fav || !masked.size;
    $("unmask").textContent = masked.size > 1 ? "Réafficher les " + masked.size + " articles masqués" : "Réafficher l'article masqué";
    $("press").hidden = fav || fond;
    ["fr", "intl"].forEach(function (k) {
      var n = unreadCount(data.filter(function (it) { return inPress(it, k) && shown(it) && matches(it, false, true); }));
      var b = document.querySelector('[data-press="' + k + '"]');
      $("pr-" + k).textContent = n;
      $("pr-" + k).className = n ? "hot" : "";
      b.setAttribute("aria-label", (k === "fr" ? "Presse française" : "Presse internationale") + ", " + n + " non lu" + (n > 1 ? "s" : ""));
      b.setAttribute("aria-pressed", st.press === k);
    });
    // Compteurs : ce qui correspond à la sélection, puis le total général de la rubrique.
    var total = fav ? data.filter(function (it) { return favs.has(it.id); }).length
      : collapse(data.filter(function (it) { return shown(it) && !!it.fond === fond; })).length;
    var where = fav ? "dans vos favoris" : fond ? "dans les ressources de fond" : "dans le journal";
    // Le compteur ne s'affiche que s'il apporte quelque chose : filtres actifs, favoris ou ressources.
    $("count").hidden = st.view === "journal" && !activeFilters().length;
    $("count").innerHTML = "<b>" + items.length + "</b> article" + (items.length > 1 ? "s" : "") + " pour cette sélection, sur <b>" + total + "</b> au total " + where + ".";
    var feed = $("feed"), head = fond ? '<div class="intro">Articles anciens repérés tardivement, avec leur date de publication réelle. Utiles pour comprendre le contexte, ils ne sont pas présentés comme l\'actualité du jour ni repris dans la synthèse de la semaine.</div>' : "";
    if (!fav && st.readFilter === "none") {
      feed.innerHTML = head + '<div class="empty">Cochez « Afficher les articles non lus » ou « Afficher les articles déjà lus » pour voir des articles.</div>';
      return;
    }
    if (!items.length) {
      // « Tout est lu » seulement si des articles correspondent aux filtres et qu'ils sont tous lus.
      feed.innerHTML = head + (fav && !favs.size ? '<div class="empty">Aucun favori pour l\'instant. Utilisez l\'étoile d\'un article pour le retrouver ici.</div>' :
        fond && !total ? '<div class="empty">Aucune ressource de fond pour l\'instant.</div>' :
        !fav && st.readFilter === "unread" && groupsPool.length ? allRead(groupsPool) :
        !fav && st.readFilter === "read" && groupsPool.length ? '<div class="empty">Aucun article lu pour l\'instant parmi les ' + groupsPool.length + " de cette sélection.</div>" :
        st.view === "journal" && !st.q.trim() && eds.indexOf(curDay()) === -1 ? '<div class="empty">Aucune édition le ' + esc(longDay(curDay())) + ". Utilisez les flèches pour passer à un autre jour.</div>" :
        noResult());
      return;
    }
    // Journal : tous les articles du jour (ou de la recherche), du plus pertinent au moins pertinent.
    feed.innerHTML = head + wrap(list(items, false, st.view === "journal" || fond));
  }
  // Navigation au jour le jour : jour précédent / suivant parmi les éditions, ou une date précise.
  function renderDayNav() {
    var on = st.view === "journal" && !st.q.trim();
    $("daynav").hidden = !on;
    $("day-note").hidden = true;
    if (!on) return;
    var d = curDay(), prev = "", next = "";
    eds.forEach(function (x) { if (x < d) prev = x; else if (x > d && !next) next = x; });
    var t = longDay(d);
    $("day-t").textContent = t.charAt(0).toUpperCase() + t.slice(1);
    $("day-pick").value = d; $("day-pick").max = today; $("day-pick").min = eds[0] || today;
    $("day-prev").disabled = !prev; $("day-prev").dataset.to = prev;
    $("day-next").disabled = !next; $("day-next").dataset.to = next;
    $("day-today").hidden = d === today || !st.day;
    if (!st.day && d !== today) {
      $("day-note").hidden = false;
      $("day-note").textContent = "La collecte d'aujourd'hui n'a pas encore eu lieu : voici la dernière édition.";
    }
  }
  // Liste d'articles par jour de collecte ; « une » met en tête l'article le plus important de la première édition.
  function list(items, une, noDays) {
    if (une && items.length) {
      var first = items.filter(function (it) { return it.edition === items[0].edition; }).sort(byWeight)[0];
      items = [first].concat(items.filter(function (it) { return it !== first; }));
    }
    var html = "", day = "", n = 0;
    items.slice(0, st.limit).forEach(function (it) {
      if (!noDays && it.edition !== day) { day = it.edition; html += '<div class="day">' + esc(dayLabel(day)) + "</div>"; }
      html += card(it, n++, une && n === 1);
    });
    if (items.length > st.limit) html += '<button type="button" class="btn more" data-more>Afficher ' + Math.min(PAGE, items.length - st.limit) + " articles de plus</button>";
    return html;
  }
  function noResult() {
    return '<div class="empty"><b>Aucun résultat pour ces filtres.</b>' + (activeFilters().length ? '<button type="button" class="btn" data-reset>Réinitialiser les filtres</button>' : "") + "</div>";
  }

  // ---------- filtres actifs ----------
  var PERIODS = { 1: "dernière édition", 7: "7 jours", 30: "30 jours", 100000: "toute la période" };
  function activeFilters() {
    var v = st.view, out = [];
    if (v !== "journal" && v !== "favoris" && v !== "fond") return out;
    // La rubrique choisie se lit dans le menu des rubriques : ce n'est pas un filtre à retirer.
    if (st.q.trim()) out.push(["q", "Recherche : « " + st.q.trim() + " »"]);
    if (v === "favoris") return out;
    if (st.min !== DEFAULTS.min) out.push(["min", "Pertinence ≥ " + st.min + " %"]);
    if (v === "fond") return out;
    if (st.q.trim() && st.period !== DEFAULTS.period) out.push(["period", "Période : " + PERIODS[st.period]]);
    return out;
  }
  function renderActive() {
    var list = activeFilters();
    $("active").hidden = !list.length;
    $("filt-n").hidden = !list.length;
    $("filt-n").textContent = list.length;
    $("filt-btn").setAttribute("aria-label", "Rechercher et affiner" + (list.length ? ", " + list.length + " filtre" + (list.length > 1 ? "s" : "") + " actif" + (list.length > 1 ? "s" : "") : ""));
    $("active").innerHTML = list.length ? '<span class="active-l">Filtres actifs :</span>' + list.map(function (f) {
      return '<button type="button" class="chip" data-unfilter="' + f[0] + '" aria-label="Retirer le filtre ' + esc(f[1]) + '">' + esc(f[1]) + ' <span aria-hidden="true">✕</span></button>';
    }).join("") + '<button type="button" class="btn reset" data-reset>Réinitialiser les filtres</button>' : "";
  }
  function unfilter(key) {
    st[key] = DEFAULTS[key];
    if (key === "q") $("q").value = "";
    if (key === "period") { st.period = DEFAULTS.period; $("period").value = String(DEFAULTS.period); }
    if (key === "min") $("min").value = String(DEFAULTS.min);
    st.limit = PAGE;
  }
  function resetFilters() { Object.keys(DEFAULTS).forEach(function (k) { if (k !== "day" && k !== "press" && k !== "readFilter") unfilter(k); }); }

  // Impact concret : l'action recommandée, sinon qui est concerné, sinon pourquoi c'est important.
  function impact(it) { return it.action || (it.qui_concerne ? "Concerne : " + it.qui_concerne : it.pourquoi); }

  // Plus rien à lire : on propose les favoris et les articles les plus importants de la période.
  function allRead(pool) {
    var byDay = st.view === "journal" && !st.q.trim();
    var html = '<div class="empty ok"><b>✓ Tout est lu.</b> Plus aucun article à lire ici.' + (!byDay || curDay() === latest ? " La prochaine édition arrive demain matin." : "") + "</div>", n = 0;
    // Au jour le jour : les 4 articles les plus pertinents de la journée, déjà lus, pour une relecture rapide.
    if (byDay) {
      var best = pool.slice().sort(byScore).slice(0, 4);
      return html + '<h2 class="done-h">Relisez les plus importants<small>Les articles les mieux notés de la journée, au cas où un détail vous aurait échappé.</small></h2>' +
        wrap(best.map(function (it) { return card(it, n++); }).join(""));
    }
    var mine = data.filter(function (it) { return favs.has(it.id) && shown(it) && inCat(it, st.cat); }).sort(sortFeed).slice(0, 5);
    if (mine.length) html += '<h2 class="done-h">Vos favoris</h2>' + wrap(mine.map(function (it) { return card(it, n++); }).join(""));
    var top = pool.filter(function (it) { return it.score >= 70 && !favs.has(it.id); })
      .sort(function (a, b) { return b.score - a.score || (a.edition < b.edition ? 1 : -1); }).slice(0, 5);
    if (top.length) html += '<h2 class="done-h">Relisez les plus importants<small>Les articles les mieux notés de la période, au cas où un détail vous aurait échappé.</small></h2>' +
      wrap(top.map(function (it) { return card(it, n++); }).join(""));
    return html;
  }

  function wrap(html) { return journal() ? '<div class="paper">' + html + "</div>" : html; }
  function actions(isRead, isFav, extra) {
    return '<div class="act">' + (extra || "") + '<button type="button" data-read>' + (isRead ? "Marquer non lu" : "✓ Marquer comme lu") + "</button>" +
      '<button type="button" data-fav aria-pressed="' + isFav + '">' + (isFav ? "★ Favori" : "☆ Favori") + "</button>" +
      '<button type="button" class="np" data-np title="Masquer cet article et apprendre à l\'IA à éviter ce genre de sujet">✕ Non pertinent</button></div>';
  }

  // Affichage « Journal » : présentation de presse, le premier article en une.
  // Vue détaillée : résumés complets. Vue compacte : titre, source, date, badges et résumé court,
  // le détail s'ouvre à la demande (la une reste toujours développée).
  // En tête de page (lead), la une compacte garde le résumé entier et l'action, le reste s'ouvre à la demande.
  function paperCard(it, une, lead) {
    var p = tone(it), done = isRead(it), isFav = favs.has(it.id);
    var short = compact() && (!une || !!lead), open = !short || opened.has(it.id);
    var dims = it.pertinence ? LBL.pertinence[it.pertinence] + " (" + it.score + " %)" : "Pertinence : " + it.score + " %";
    var src = '<p class="src">' + esc(it.source) + " · " + published(it) + (open && it.contenu ? " · analyse : " + esc(LBL.contenu[it.contenu]) : "") + "</p>";
    var detail = (it.resume && (!short || open) ? '<p class="lede">' + esc(it.resume) + "</p>" : "") +
      '<p class="why">' + esc(it.pourquoi) + "</p>" +
      (it.qui_concerne ? '<p class="who">' + esc(it.qui_concerne) + "</p>" : "") +
      (it.action ? '<p class="todo">' + esc(it.action) + "</p>" : "") +
      (it.verifications ? '<p class="check">' + esc(it.verifications) + "</p>" : "") +
      (it.echeance ? '<p class="due">' + esc(dueLabel(it.echeance)) + "</p>" : "") + reprises(it);
    return '<article class="ev pa ' + p + (une ? " une" : "") + (done ? " read" : "") + (short ? " short" : "") + '" style="--cc:var(--c-' + esc(it.categorie) + ");--pc:var(--" + p + ')" data-id="' + it.id + '">' +
      '<div class="kick">' + (done ? '<span class="state lu">Lu</span>' : '<span class="state nonlu">Non lu</span>') + tagHtml(it) + "<span>" + esc(dims) + "</span>" +
      (it.urgence ? '<span class="dim u-' + esc(it.urgence) + '">' + esc(LBL.urgence[it.urgence]) + "</span>" : "") +
      (it.statut ? '<span class="dim s-' + esc(it.statut) + '">' + esc(LBL.statut[it.statut]) + "</span>" : "") +
      (it.perimetre ? '<span class="dim">' + esc(LBL.perimetre[it.perimetre]) + "</span>" : "") +
      (it.payant ? '<span class="state pay" title="Article payant : non consultable sans abonnement">🔒 Réservé aux abonnés</span>' : "") + "</div>" +
      (une ? '<p class="une-l">À la une</p>' : "") +
      '<h3><a href="' + esc(it.url) + '" target="_blank" rel="noopener" data-open>' + esc(it.titre) + "</a>" + pressTag(it) + "</h3>" +
      (short ? src + (it.resume && !open ? '<p class="lede">' + esc(lead ? it.resume : brief(it.resume)) + "</p>" : "") +
        (lead && !open && it.action ? '<p class="todo">' + esc(it.action) + "</p>" : "") +
        (open ? '<div class="more-d" id="d-' + esc(it.id) + '">' + detail + "</div>" : "") +
        actions(done, isFav, '<button type="button" class="tgl" data-detail aria-expanded="' + open + '" aria-controls="d-' + esc(it.id) + '">' + (open ? "Masquer le détail" : "Voir le détail") + "</button>")
        : detail + src + actions(done, isFav)) + "</article>";
  }
  // Résumé court : la première phrase, coupée proprement si elle est longue.
  function brief(s) {
    var first = (s.match(/^.+?[.!?](\s|$)/) || [s])[0].trim();
    if (first.length <= 200) return first.length < s.length ? first : s;
    return first.slice(0, 190).replace(/\s+\S*$/, "") + "…";
  }

  // ---------- échéances ----------
  // Une date n'est jamais affichée plus précise que la source : jour exact, mois, période ou inconnue.
  function dueWhen(e) {
    if (e.precision === "jour") return shortDate(e.date);
    if (e.precision === "mois" && e.date) { var m = MOIS[+e.date.slice(5, 7) - 1]; return m.charAt(0).toUpperCase() + m.slice(1) + " " + e.date.slice(0, 4) + " — date à confirmer"; }
    if (e.precision === "periode") return (e.periode || e.date) + " (période approximative)";
    if (e.precision === "a_verifier" && e.date) return shortDate(e.date) + " (date non vérifiée)";
    return "Date inconnue";
  }
  function dueType(e) { for (var i = 0; i < DUE_TYPES.length; i++) if (DUE_TYPES[i][0] === (e.type || "")) return DUE_TYPES[i][1]; return "Dates à vérifier"; }
  function dueLabel(e) { return "Échéance : " + dueWhen(e) + " · " + e.libelle + (e.type === "annonce_non_confirmee" ? " (non confirmée)" : ""); }
  // Fin de la période couverte par la date : un mois reste « à venir » jusqu'à son dernier jour.
  function dueEnd(e) { return !e.date ? "" : e.date.length === 7 ? e.date + "-31" : e.date; }
  function upcoming(e) { return !e.date || dueEnd(e) >= today; }
  // Une seule fois chaque échéance (même date, même libellé), quel que soit le nombre d'articles.
  function uniqueDue(list) {
    var seen = {}, out = [];
    list.filter(function (it) { return it.echeance; })
      .sort(function (a, b) { return (a.statut !== "texte_publie") - (b.statut !== "texte_publie") || b.score - a.score; })
      .forEach(function (it) { var k = it.echeance.cle || it.echeance.date + it.echeance.libelle; if (!seen[k]) { seen[k] = 1; out.push(it); } });
    return out.sort(function (a, b) { return (a.echeance.date || "9999") < (b.echeance.date || "9999") ? -1 : 1; });
  }

  // Autres médias qui relatent le même événement : consultables, mais comptés comme une seule information.
  function reprises(it) {
    var others = members(it).filter(function (m) { return m.id !== it.id; }).sort(sortPublished);
    if (!others.length) return "";
    var n = others.length, pl = n > 1 ? "s" : "";
    return '<details class="rep"><summary>Même information reprise par ' + n + " autre" + pl + " source" + pl + "</summary>" +
      '<p class="rep-n">Ce sont des reprises de la même information, pas des confirmations indépendantes.</p><ul>' +
      others.map(function (m) {
        return '<li><a href="' + esc(m.url) + '" target="_blank" rel="noopener">' + esc(m.source) + "</a> · " + esc(published(m)) + "<br>" + esc(m.titre) + "</li>";
      }).join("") + "</ul></details>";
  }

  function card(it, n, une) { return paperCard(it, une); }
  function shortDate(iso) { var d = new Date(iso + "T12:00:00"); return d.getDate() + " " + MOIS_C[d.getMonth()] + " " + d.getFullYear(); }

  function renderDeadlines() {
    var items = uniqueDue(data);
    var html = '<div class="ics">S\'abonner au calendrier dans Google Agenda, Outlook ou sur téléphone : <code>' + esc(CFG.ics || "") +
      '</code><button type="button" class="btn" data-copy="' + esc(CFG.ics || "") + '">Copier le lien</button>' +
      '<small>Seules les dates exactes sont envoyées au calendrier ; un mois seul ou une date à vérifier reste ici.</small></div>';
    if (!items.length) html += '<div class="empty">Aucune échéance repérée pour l\'instant. L\'IA les ajoute dès qu\'un texte annonce une date d\'entrée en vigueur ou une date limite.</div>';
    // Obligations, consultations, événements et annonces non confirmées sont séparés.
    DUE_TYPES.forEach(function (t) {
      var up = items.filter(function (it) { return (it.echeance.type || "") === t[0] && upcoming(it.echeance); });
      if (up.length) html += '<div class="day">' + esc(t[1]) + " à venir</div>" + up.map(deadline).join("");
    });
    var past = items.filter(function (it) { return !upcoming(it.echeance); }).reverse();
    if (past.length) html += '<div class="day">Passées</div>' + past.map(deadline).join("");
    $("v-echeances").innerHTML = html;
  }
  function deadline(it) {
    var e = it.echeance, exact = e.precision === "jour", left = exact ? days(e.date, today) : null;
    var when = !exact ? "" : left > 0 ? "J-" + left : left === 0 ? "Aujourd'hui" : "Passée";
    var d = e.date ? new Date(e.date.slice(0, 7) + "-15T12:00:00") : null;
    var big = exact ? +e.date.slice(8, 10) : "?", small = d ? MOIS_C[d.getMonth()] + " " + d.getFullYear() : "date inconnue";
    var src = e.url && e.url !== it.url ? '<a href="' + esc(e.url) + '" target="_blank" rel="noopener">' + esc(e.source) + "</a>" : esc(e.source || it.source);
    return '<article class="dl' + (upcoming(e) ? "" : " past") + (exact ? "" : " approx") + '" style="--cc:var(--c-' + esc(it.categorie) + ')"><div class="date"><b>' + big + "</b><span>" +
      esc(small) + "</span>" + (when ? "<em>" + when + "</em>" : "") + '</div><div class="body"><div class="meta"><span class="tag">' + esc(dueType(e)) +
      '</span><span class="tag">' + esc(catName(it.categorie)) + "</span></div><h3>" + esc(e.libelle) + '</h3><p class="when">' + esc(dueWhen(e)) + "</p>" +
      (e.justification ? '<p class="just">' + esc(e.justification) + "</p>" : "") +
      '<p class="srcd">Source : ' + src + ' · <a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.titre) + "</a></p>" +
      (it.action ? '<p class="todo">' + esc(it.action) + "</p>" : "") + "</div></article>";
  }

  // Résumé de la semaine : synthèse de l'IA, articles à retenir et échéances à venir.
  function renderWeek() {
    var box = $("v-semaine");
    if (!weeks.length) { box.innerHTML = '<div class="empty">Le premier résumé de la semaine sera publié lors du prochain passage du matin.</div>'; return; }
    var w = weeks[weekIdx];
    var pick = weeks.length > 1 ? '<select id="week-pick" aria-label="Choisir une semaine">' + weeks.map(function (x, i) {
      return '<option value="' + i + '"' + (i === weekIdx ? " selected" : "") + ">" + esc(x.titre) + (x.en_cours ? " (en cours)" : "") + "</option>"; }).join("") + "</select>" : "";
    var html = '<section class="week"><div class="week-h"><span class="onair"><i></i>' + (w.en_cours ? "Semaine en cours" : "Bilan de la semaine") +
      "</span><h2>" + esc(w.titre) + "</h2>" + pick + "</div>" +
      (w.synthese ? '<div class="week-s">' + w.synthese.split(/\n\s*\n/).map(function (p) { return "<p>" + esc(p.trim()) + "</p>"; }).join("") + "</div>" : "") +
      (w.en_cours ? '<p class="week-n">Mis à jour chaque matin jusqu\'à dimanche. Dernière mise à jour : ' + esc(longDay(w.maj)) + ".</p>" : "") + "</section>";
    var items = w.articles.map(function (id) { return byId[id]; }).filter(Boolean);
    html += '<div class="day">Les ' + items.length + " articles à retenir</div>";
    html += items.length ? wrap(items.map(function (it, n) { return card(it, n); }).join("")) : '<div class="empty">Aucune nouvelle information majeure cette semaine.</div>';
    var due = w.echeances.map(function (id) { return byId[id]; }).filter(Boolean);
    if (due.length) html += '<div class="day">Échéances à venir</div>' + due.map(deadline).join("");
    box.innerHTML = html;
    var sel = $("week-pick");
    if (sel) sel.addEventListener("change", function () { weekIdx = +sel.value; renderWeek(); });
  }

  function renderArchives() {
    var byDay = {};
    data.forEach(function (it) { if (!it.fond) (byDay[it.edition] = byDay[it.edition] || []).push(it); });
    var keys = Object.keys(byDay).sort().reverse(), html = "", month = "";
    keys.forEach(function (k) {
      var m = k.slice(0, 7);
      if (m !== month) {
        if (month) html += "</ul>";
        month = m; var d = new Date(k + "T12:00:00");
        html += '<h2 class="month">' + MOIS[d.getMonth()].replace(/^./, function (c) { return c.toUpperCase(); }) + " " + d.getFullYear() + '</h2><ul class="arch">';
      }
      var n = byDay[k].length, unread = 0;
      byDay[k].forEach(function (it) { if (!read.has(it.id)) unread++; });
      var parts = "<span>" + n + " article" + (n > 1 ? "s" : "") + "</span>";
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
    if (ch) { st.cat = ch.dataset.cat; st.view = "journal"; st.limit = PAGE; render(); return window.scrollTo({ top: 0 }); }
    var dnav = t.closest("[data-to]"); if (dnav && !dnav.disabled) { st.day = dnav.dataset.to === today ? "" : dnav.dataset.to; st.limit = PAGE; return render(); }
    if (t.closest("#day-today")) { st.day = ""; st.limit = PAGE; return render(); }
    var dayBtn = t.closest("[data-day]"); if (dayBtn) { st.day = dayBtn.dataset.day; st.view = "journal"; st.limit = PAGE; render(); return window.scrollTo({ top: 0 }); }
    if (t.closest("[data-more]")) { st.limit += PAGE; return render(); }
    var copy = t.closest("[data-copy]");
    if (copy) {
      var done = function () { copy.textContent = "Lien copié"; };
      try { navigator.clipboard.writeText(copy.dataset.copy).then(done, function () {}); } catch (err) {}
      return;
    }
    var pr = t.closest("[data-press]"); if (pr) { st.press = pr.dataset.press; st.limit = PAGE; return render(); }
    var dn = t.closest("button[data-density]"); if (dn) { opened.clear(); return setPref("veilletls.vue", "density", dn.dataset.density); }
    if (t.closest("[data-reset]")) { resetFilters(); render(); return focusAfter($("q").offsetParent ? $("q") : $("count")); }
    var uf = t.closest("[data-unfilter]"); if (uf) { unfilter(uf.dataset.unfilter); render(); return focusAfter(document.querySelector(".chip") || $("count")); }
    var dt = t.closest("[data-detail]");
    if (dt) {
      var did = dt.closest(".ev").dataset.id;
      if (opened.has(did)) opened.delete(did); else opened.add(did);
      render();
      return focusAfter(document.querySelector('.ev[data-id="' + did + '"] [data-detail]'));
    }
    if (t.closest("[data-undo]")) { members(byId[t.closest("[data-undo]").dataset.undo] || { id: t.closest("[data-undo]").dataset.undo }).forEach(function (m) { masked.delete(m.id); }); saveSet("veilletls.masques", masked); hideToast(); return render(); }
    var ev = t.closest(".ev"); if (!ev) return;
    var id = ev.dataset.id;
    var it0 = byId[id] || { id: id };
    if (t.closest("[data-read]")) {
      // Une fiche regroupe parfois plusieurs articles : « non lu » les remet tous à lire.
      var nowRead = !isRead(it0);
      if (nowRead) { read.add(id); ev.classList.add("flash"); } else members(it0).forEach(function (m) { read.delete(m.id); });
      saveSet("veilletls.lus", read);
      var leaves = (st.view === "journal" || st.view === "fond") && st.readFilter !== "all";
      if (leaves) setTimeout(function () { ev.classList.add("gone"); }, nowRead ? 300 : 0);
      setTimeout(render, leaves ? (nowRead ? 650 : 350) : 0);
    } else if (t.closest("[data-np]")) {
      members(it0).forEach(function (m) { masked.add(m.id); }); saveSet("veilletls.masques", masked);
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
  $("period").addEventListener("change", function (e) { st.period = +e.target.value; st.limit = PAGE; render(); });
  $("day-pick").addEventListener("change", function (e) { var v = e.target.value; if (!v) return; st.day = v === today ? "" : v; st.limit = PAGE; render(); });
  $("filt-btn").addEventListener("click", function () {
    var open = $("tools").classList.toggle("open");
    $("filt-btn").setAttribute("aria-expanded", open);
    if (open) $("q").focus();
  });
  // Cases « non lus » / « déjà lus » : chacune s'ajoute à l'autre.
  function readBoxes() {
    var u = $("show-unread").checked, r = $("show-read").checked;
    st.readFilter = u && r ? "all" : u ? "unread" : r ? "read" : "none"; st.limit = PAGE; render();
  }
  $("show-unread").addEventListener("change", readBoxes);
  $("show-read").addEventListener("change", readBoxes);
  $("min").addEventListener("change", function (e) { st.min = +e.target.value; st.limit = PAGE; render(); });
  $("unmask").addEventListener("click", function () { masked.clear(); saveSet("veilletls.masques", masked); render(); });
  // Après un nouveau rendu, le focus clavier revient sur un élément proche au lieu de se perdre.
  function focusAfter(el) { if (el && el.focus) el.focus({ preventScroll: true }); }
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
    groups = {}; byId = {};
    data.forEach(function (it) { byId[it.id] = it; if (it.groupe) (groups[it.groupe] = groups[it.groupe] || []).push(it); });
    latest = data.reduce(function (m, it) { return it.edition > m ? it.edition : m; }, "") || today;
    eds = Object.keys(data.reduce(function (m, it) { if (!it.fond && it.edition) m[it.edition] = 1; return m; }, {})).sort();
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
