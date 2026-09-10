// The chooser. Built from config.js so the five cards cannot drift out of step
// with the pages they link to -- the title and tagline on a card are the same
// strings the page itself uses.

import * as cfg from "./config.js";

const card = (href, thumb, title, tagline, alt) => `
  <a class="card" href="${href}">
    <img src="docs/${thumb}" alt="${alt}" loading="lazy" width="560">
    <div class="card-text">
      <strong>${title}</strong>
      <span>${tagline}</span>
    </div>
  </a>`;

document.getElementById("title").textContent = cfg.SITE_TITLE;
document.title = cfg.SITE_TITLE;
document.getElementById("blurb").textContent = cfg.SITE_BLURB;
document.getElementById("note").textContent = cfg.SITE_CAVEAT;
document.getElementById("credit").innerHTML =
  `${cfg.DATA_CREDIT}${cfg.REPO_URL ? ` &middot; <a href="${cfg.REPO_URL}">${cfg.REPO_LABEL}</a>` : ""}`;

document.getElementById("cards").innerHTML =
  Object.entries(cfg.MODELS).map(([key, m]) => card(
    `map.html?model=${key}`,
    `thumb-${key}.png`,
    m.title.split(" — ")[0],
    m.tagline,
    `The United States with every state divided into congressional districts by the ${key} rule`,
  )).join("") +
  card("illinois.html", "thumb-illinois.png",
    "Illinois", cfg.ILLINOIS.tagline,
    "Five maps of Illinois shaded from red to blue by the partisan lean of each district");
