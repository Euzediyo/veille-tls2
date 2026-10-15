// Veille TLS : comptes lecteurs (facultatifs). Sans compte, tout reste mémorisé dans ce navigateur.
// Avec un compte, les articles lus, les favoris et les articles masqués sont synchronisés entre appareils.
// Le service de comptes (Supabase) n'est chargé que pour un lecteur qui se connecte ou l'est déjà.
(function () {
  "use strict";
  var C = (window.VEILLE || {}).compte;
  var btn = document.getElementById("acct-btn");
  if (!C || !btn) return;

  var LISTS = { lus: "veilletls.lus", favoris: "veilletls.favoris", masques: "veilletls.masques" };
  var LIMITS = { lus: 20000, favoris: 5000, masques: 5000 };
  var OWNER = "veilletls.compte"; // compte dont ce navigateur a déjà reçu les listes
  var ref = C.url.replace(/^https:\/\//, "").split(".")[0];
  var SESSION = "sb-" + ref + "-auth-token";
  var client = null, user = null, timer = 0, ready = false, pulling = false, dlg = null;

  // ---------- utilitaires ----------
  function get(key, fallback) { try { var v = localStorage.getItem(key); return v == null ? fallback : v; } catch (e) { return fallback; } }
  function put(key, value) { try { if (value == null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch (e) {} }
  function list(key) { try { return JSON.parse(get(key, "[]")) || []; } catch (e) { return []; } }
  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }
  function union(a, b) { var seen = {}, out = []; a.concat(b).forEach(function (x) { if (!seen[x]) { seen[x] = 1; out.push(x); } }); return out; }
  function lastN(arr, n) { return arr.length > n ? arr.slice(arr.length - n) : arr; }

  function sdk() {
    if (client) return Promise.resolve(client);
    return new Promise(function (ok, ko) {
      var s = document.createElement("script");
      s.src = C.sdk; s.onload = ok; s.onerror = function () { ko(new Error("chargement")); };
      document.head.appendChild(s);
    }).then(function () {
      client = window.supabase.createClient(C.url, C.cle, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } });
      client.auth.onAuthStateChange(function (event, session) {
        if (event === "PASSWORD_RECOVERY") { user = session && session.user; open("nouveau"); }
        else if (session && session.user) { var first = !user || user.id !== session.user.id; user = session.user; if (first) pull(); }
        else if (event === "SIGNED_OUT") user = null;
        label();
      });
      return client;
    });
  }

  // ---------- synchronisation ----------
  // Première connexion sur ce navigateur : les listes locales et celles du compte sont réunies.
  // Ensuite, le compte fait foi : ce qui a été fait sur un autre appareil s'affiche ici.
  function pull() {
    if (!user || pulling) return;
    pulling = true;
    client.from("preferences").select("lus,favoris,masques").eq("user_id", user.id).maybeSingle().then(function (res) {
      pulling = false;
      if (res.error) return;
      var row = res.data, merge = get(OWNER, "") !== user.id;
      Object.keys(LISTS).forEach(function (k) {
        var remote = (row && row[k]) || [];
        var value = !row ? list(LISTS[k]) : merge ? union(remote, list(LISTS[k])) : remote;
        put(LISTS[k], JSON.stringify(lastN(value, LIMITS[k])));
      });
      put(OWNER, user.id);
      ready = true;
      if (window.VeilleApp) window.VeilleApp.reload();
      if (!row || merge) push();
    });
  }
  function push() {
    if (!user || !client) return;
    var row = { user_id: user.id, maj: new Date().toISOString() };
    Object.keys(LISTS).forEach(function (k) { row[k] = lastN(list(LISTS[k]), LIMITS[k]); });
    client.from("preferences").upsert(row).then(function () {});
  }
  // Appelé par le journal à chaque changement : envoi groupé une seconde et demie plus tard.
  window.VeilleCompte = { changed: function () { if (user && ready) { clearTimeout(timer); timer = setTimeout(push, 1500); } } };
  window.addEventListener("pagehide", function () { if (timer) { clearTimeout(timer); timer = 0; push(); } });

  // ---------- fenêtre « Mon compte » ----------
  function label() {
    btn.hidden = false;
    btn.querySelector("span").textContent = user ? "Mon compte" : "Se connecter";
    btn.classList.toggle("on", !!user);
  }
  var ERRORS = [
    [/invalid login credentials/i, "E-mail ou mot de passe incorrect."],
    [/email not confirmed/i, "Confirmez d'abord votre adresse : cliquez sur le lien reçu par e-mail."],
    [/already registered|already been registered/i, "Un compte existe déjà avec cette adresse. Connectez-vous, ou utilisez « Mot de passe oublié »."],
    [/rate limit|too many/i, "Trop de demandes en peu de temps. Réessayez dans une heure."],
    [/password/i, "Mot de passe refusé : choisissez-en un d'au moins 10 caractères, avec lettres et chiffres."],
    [/chargement|fetch|network/i, "Connexion impossible pour le moment. Vérifiez votre réseau puis réessayez."]
  ];
  function message(err) {
    var text = (err && err.message) || "";
    for (var i = 0; i < ERRORS.length; i++) if (ERRORS[i][0].test(text)) return ERRORS[i][1];
    return "Une erreur est survenue. Réessayez dans un instant.";
  }
  var PRIVACY = '<p class="acct-small">Vos données : votre e-mail et la liste des articles lus, favoris et masqués, pour les retrouver sur tous vos appareils. Rien d\'autre, et jamais revendu. <a href="confidentialite.html">Politique de confidentialité</a></p>';
  var VIEWS = {
    connexion: function () {
      return '<h2>Se connecter</h2><p>Retrouvez vos articles lus et vos favoris sur tous vos appareils.</p>' +
        '<form data-do="connexion"><label>E-mail<input type="email" name="email" autocomplete="email" required></label>' +
        '<label>Mot de passe<input type="password" name="mdp" autocomplete="current-password" required></label>' +
        '<button type="submit" class="btn primary">Se connecter</button></form>' +
        '<p class="acct-links"><button type="button" class="lnk" data-go="oubli">Mot de passe oublié ?</button> · <button type="button" class="lnk" data-go="inscription">Créer un compte</button></p>' + PRIVACY;
    },
    inscription: function () {
      return '<h2>Créer un compte</h2><p>Gratuit. Un e-mail de confirmation vous sera envoyé.</p>' +
        '<form data-do="inscription"><label>E-mail<input type="email" name="email" autocomplete="email" required></label>' +
        '<label>Mot de passe <small>(10 caractères minimum)</small><input type="password" name="mdp" autocomplete="new-password" minlength="10" required></label>' +
        '<button type="submit" class="btn primary">Créer mon compte</button></form>' +
        '<p class="acct-links"><button type="button" class="lnk" data-go="connexion">J\'ai déjà un compte</button></p>' + PRIVACY;
    },
    oubli: function () {
      return '<h2>Mot de passe oublié</h2><p>Indiquez votre e-mail : vous recevrez un lien pour en choisir un nouveau.</p>' +
        '<form data-do="oubli"><label>E-mail<input type="email" name="email" autocomplete="email" required></label>' +
        '<button type="submit" class="btn primary">Recevoir le lien</button></form>' +
        '<p class="acct-links"><button type="button" class="lnk" data-go="connexion">Retour</button></p>';
    },
    nouveau: function () {
      return '<h2>Nouveau mot de passe</h2>' +
        '<form data-do="nouveau"><label>Nouveau mot de passe <small>(10 caractères minimum)</small><input type="password" name="mdp" autocomplete="new-password" minlength="10" required></label>' +
        '<button type="submit" class="btn primary">Enregistrer</button></form>';
    },
    compte: function () {
      return '<h2>Mon compte</h2><p>Connecté avec <b>' + esc(user && user.email) + '</b>. Vos articles lus, favoris et articles masqués sont synchronisés sur tous les appareils où vous êtes connecté.</p>' +
        '<div class="acct-actions"><button type="button" class="btn" data-act="sortie">Se déconnecter</button>' +
        '<button type="button" class="btn" data-act="export">Télécharger mes données</button></div>' +
        '<details class="acct-del"><summary>Supprimer mon compte</summary><p>Votre compte et vos listes enregistrées sont effacés définitivement. Ce navigateur garde sa copie locale.</p>' +
        '<button type="button" class="btn danger" data-act="suppression">Supprimer définitivement</button></details>' + PRIVACY;
    }
  };
  function build() {
    dlg = document.createElement("dialog");
    dlg.className = "acct";
    dlg.setAttribute("aria-label", "Mon compte");
    dlg.innerHTML = '<button type="button" class="acct-x" aria-label="Fermer">✕</button><div class="acct-body"></div><p class="acct-msg" role="status"></p>';
    document.body.appendChild(dlg);
    dlg.addEventListener("click", function (e) {
      if (e.target === dlg || e.target.closest(".acct-x")) return dlg.close();
      var go = e.target.closest("[data-go]"); if (go) return show(go.dataset.go);
      var act = e.target.closest("[data-act]"); if (act) return action(act.dataset.act);
    });
    dlg.addEventListener("submit", function (e) { e.preventDefault(); submit(e.target); });
  }
  function show(view, msg, ok) {
    dlg.querySelector(".acct-body").innerHTML = VIEWS[view]();
    say(msg || "", ok);
    var first = dlg.querySelector("input"); if (first) first.focus();
  }
  function say(text, ok) { var m = dlg.querySelector(".acct-msg"); m.textContent = text; m.className = "acct-msg" + (ok ? " ok" : text ? " ko" : ""); }
  function busy(form, on) { var b = form.querySelector("[type=submit]"); if (b) b.disabled = on; }
  function open(view) {
    if (!dlg) build();
    show(view || (user ? "compte" : "connexion"));
    if (!dlg.open) dlg.showModal();
  }
  function back() { return location.origin + location.pathname; }

  function submit(form) {
    var f = form.elements, kind = form.dataset.do;
    busy(form, true); say("");
    sdk().then(function (sb) {
      if (kind === "connexion") return sb.auth.signInWithPassword({ email: f.email.value.trim(), password: f.mdp.value }).then(function (r) {
        if (r.error) throw r.error;
        user = r.data.user; label(); if (!ready) pull(); show("compte", "Vous êtes connecté. Vos listes se synchronisent.", true);
      });
      if (kind === "inscription") return sb.auth.signUp({ email: f.email.value.trim(), password: f.mdp.value, options: { emailRedirectTo: back() } }).then(function (r) {
        if (r.error) throw r.error;
        show("connexion", "Presque fini : cliquez sur le lien envoyé à " + f.email.value.trim() + " pour confirmer votre adresse (pensez aux courriers indésirables).", true);
      });
      if (kind === "oubli") return sb.auth.resetPasswordForEmail(f.email.value.trim(), { redirectTo: back() }).then(function (r) {
        if (r.error) throw r.error;
        say("Si un compte existe avec cette adresse, un lien vient de lui être envoyé.", true);
      });
      if (kind === "nouveau") return sb.auth.updateUser({ password: f.mdp.value }).then(function (r) {
        if (r.error) throw r.error;
        user = r.data.user; label(); if (!ready) pull(); show("compte", "Mot de passe enregistré.", true);
      });
    }).catch(function (err) { pulling = false; say(message(err)); }).then(function () { if (form.isConnected) busy(form, false); });
  }

  function action(kind) {
    if (kind === "sortie") return client.auth.signOut().then(function () { user = null; ready = false; put(OWNER, null); label(); dlg.close(); });
    if (kind === "export") {
      var data = { email: user.email, inscription: user.created_at, derniere_connexion: user.last_sign_in_at };
      Object.keys(LISTS).forEach(function (k) { data[k] = list(LISTS[k]); });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      a.download = "veille-tls-mes-donnees.json";
      document.body.appendChild(a); a.click(); a.remove();
      return;
    }
    if (kind === "suppression") return client.rpc("supprimer_mon_compte").then(function (r) {
      if (r.error) return say(message(r.error));
      return client.auth.signOut({ scope: "local" }).then(function () {
        user = null; ready = false; put(OWNER, null); label(); show("connexion", "Votre compte a été supprimé.", true);
      });
    });
  }

  btn.addEventListener("click", function () {
    if (user || !get(SESSION, "")) return open();
    sdk().then(function () { return client.auth.getSession(); }).then(function () { open(); }, function () { open(); });
  });
  label();
  // Lecteur déjà connecté, ou retour depuis un lien reçu par e-mail : le service de comptes est chargé tout de suite.
  if (get(SESSION, "") || /access_token|error_description|type=recovery/.test(location.hash)) sdk().catch(function () {});
})();
