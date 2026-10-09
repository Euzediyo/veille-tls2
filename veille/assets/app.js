// Filtres par catégorie (pages d'édition) et recherche dans les archives.
(function () {
  var chips = document.querySelectorAll(".chip");
  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      var f = chip.dataset.filter;
      chips.forEach(function (c) { c.classList.toggle("on", c === chip); });
      document.querySelectorAll(".card").forEach(function (card) {
        card.hidden = f !== "all" && card.dataset.cat !== f;
      });
      document.querySelectorAll(".group").forEach(function (g) {
        g.hidden = !g.querySelector(".card:not([hidden])");
      });
    });
  });

  var results = document.getElementById("results");
  if (!results) return;
  var cats = JSON.parse(results.dataset.cats || "{}");
  var q = document.getElementById("q"), min = document.getElementById("min");
  var levels = [[90, "crit", "Critique"], [70, "imp", "Important"], [50, "int", "Intéressant"], [30, "veil", "Veille"]];
  var data = [];
  function norm(s) { return (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }
  function esc(s) { var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }
  function lvl(score) { for (var i = 0; i < levels.length; i++) if (score >= levels[i][0]) return levels[i]; return [0, "ign", "Ignoré"]; }
  function render() {
    var terms = norm(q.value).split(/\s+/).filter(Boolean), m = +min.value;
    var hits = data.filter(function (it) {
      if (it.score < m) return false;
      var hay = norm(it.titre + " " + it.resume + " " + it.pourquoi + " " + it.source);
      return terms.every(function (t) { return hay.indexOf(t) !== -1; });
    }).sort(function (a, b) { return a.edition < b.edition ? 1 : a.edition > b.edition ? -1 : b.score - a.score; }).slice(0, 60);
    if (!terms.length && m < 70) { hits = hits.slice(0, 30); }
    results.innerHTML = '<p class="note">' + hits.length + (hits.length === 60 ? "+" : "") + " article(s)</p>" + hits.map(function (it) {
      var l = lvl(it.score);
      return '<article class="card lvl-' + l[1] + '"><div class="meta"><span class="pill">' + it.score + " · " + l[2] +
        "</span><span>" + esc(cats[it.categorie] || "Autre") + "</span><span>" + esc(it.source) + "</span><span>" + esc(it.edition) +
        '</span></div><h3><a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.titre) + "</a></h3>" +
        (it.resume ? '<p class="resume">' + esc(it.resume) + "</p>" : "") +
        '<p class="why"><span>Pourquoi ce score</span> ' + esc(it.pourquoi) + "</p></article>";
    }).join("");
  }
  document.getElementById("search-form").addEventListener("submit", function (e) { e.preventDefault(); });
  q.addEventListener("input", render); min.addEventListener("change", render);
  fetch("articles.json").then(function (r) { return r.json(); }).then(function (d) { data = d; render(); })
    .catch(function () { results.innerHTML = '<p class="note">La recherche n\'a pas pu charger les articles.</p>'; });
})();
