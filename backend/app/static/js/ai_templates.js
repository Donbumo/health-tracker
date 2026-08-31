((root, factory) => {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root && root.document) api.init(root.document, root.location);
})(typeof window !== "undefined" ? window : null, () => {
  "use strict";

  const normalizeText = (value) => String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("es");

  const choosePeriod = (allowedPeriods, defaultPeriod, requestedPeriod) => {
    const allowed = String(allowedPeriods || "").split(",").filter(Boolean);
    return allowed.includes(requestedPeriod) ? requestedPeriod : defaultPeriod;
  };

  const matchesTemplate = (text, category, query, activeCategory) => {
    const categoryMatches = activeCategory === "all" || category === activeCategory;
    return categoryMatches && normalizeText(text).includes(normalizeText(query).trim());
  };

  const matchesCapability = (domain, activeDomain, intent, activeIntent) => (
    domain === activeDomain && (!activeIntent || intent === activeIntent)
  );

  const updateStructuredPeriod = (href, location, selectedPeriod) => {
    const target = new URL(href, location.origin);
    target.searchParams.set("period", selectedPeriod);
    return `${target.pathname}${target.search}`;
  };

  const initAdaptiveCatalog = (document, location) => {
    const catalog = document.querySelector("[data-ai-adaptive-catalog]");
    if (!catalog) return;

    const cards = Array.from(catalog.querySelectorAll("[data-ai-capability-card]"));
    const domainButtons = Array.from(catalog.querySelectorAll("[data-ai-domain]"));
    const metricGroups = Array.from(catalog.querySelectorAll("[data-ai-domain-metrics]"));
    const intentGroups = Array.from(catalog.querySelectorAll("[data-ai-domain-intents]"));
    const periodSelect = catalog.querySelector("[data-ai-capability-period]");
    const results = catalog.querySelector("[data-ai-capability-results]");
    let activeDomain = catalog.dataset.defaultDomain || domainButtons[0]?.dataset.aiDomain || "";
    let activeIntent = "";

    const selectFirstIntent = () => {
      const group = intentGroups.find((item) => item.dataset.aiDomainIntents === activeDomain);
      const buttons = group ? Array.from(group.querySelectorAll("[data-ai-intent]")) : [];
      const selected = buttons.find((button) => button.getAttribute("aria-pressed") === "true") || buttons[0];
      activeIntent = selected ? selected.dataset.aiIntent : "";
      buttons.forEach((button) => {
        const active = button === selected;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", String(active));
      });
    };

    selectFirstIntent();

    const update = () => {
      const requestedPeriod = periodSelect ? periodSelect.value : "30d";
      let visible = 0;
      cards.forEach((card) => {
        const show = matchesCapability(
          card.dataset.domain,
          activeDomain,
          card.dataset.intent,
          activeIntent,
        );
        card.hidden = !show;
        if (show) visible += 1;

        const selectedPeriod = choosePeriod(
          card.dataset.periods,
          card.dataset.defaultPeriod,
          requestedPeriod,
        );
        const link = card.querySelector("[data-ai-capability-use]");
        if (link) link.href = updateStructuredPeriod(link.href, location, selectedPeriod);
      });
      metricGroups.forEach((group) => {
        group.hidden = group.dataset.aiDomainMetrics !== activeDomain;
      });
      intentGroups.forEach((group) => {
        group.hidden = group.dataset.aiDomainIntents !== activeDomain;
      });
      if (results) results.textContent = `${visible} ${visible === 1 ? "capacidad" : "capacidades"}`;
    };

    domainButtons.forEach((button) => {
      button.addEventListener("click", () => {
        activeDomain = button.dataset.aiDomain;
        domainButtons.forEach((candidate) => {
          const selected = candidate === button;
          candidate.classList.toggle("is-active", selected);
          candidate.setAttribute("aria-pressed", String(selected));
        });
        intentGroups.forEach((group) => {
          Array.from(group.querySelectorAll("[data-ai-intent]")).forEach((candidate) => {
            candidate.classList.remove("is-active");
            candidate.setAttribute("aria-pressed", "false");
          });
        });
        selectFirstIntent();
        update();
      });
    });
    intentGroups.forEach((group) => {
      Array.from(group.querySelectorAll("[data-ai-intent]")).forEach((button) => {
        button.addEventListener("click", () => {
          activeIntent = button.dataset.aiIntent;
          Array.from(group.querySelectorAll("[data-ai-intent]")).forEach((candidate) => {
            const selected = candidate === button;
            candidate.classList.toggle("is-active", selected);
            candidate.setAttribute("aria-pressed", String(selected));
          });
          update();
        });
      });
    });
    if (periodSelect) periodSelect.addEventListener("change", update);
    update();
  };

  const init = (document, location) => {
    initAdaptiveCatalog(document, location);
    const catalog = document.querySelector("[data-ai-template-catalog]");
    if (!catalog) return;

    const cards = Array.from(catalog.querySelectorAll("[data-ai-template-card]"));
    const categoryButtons = Array.from(catalog.querySelectorAll("[data-ai-category]"));
    const search = catalog.querySelector("[data-ai-template-search]");
    const periodSelect = catalog.querySelector("[data-ai-template-period]");
    const results = catalog.querySelector("[data-ai-template-results]");
    const empty = catalog.querySelector("[data-ai-template-empty]");
    let activeCategory = catalog.dataset.defaultCategory || "all";

    const update = () => {
      const query = search ? search.value : "";
      const requestedPeriod = periodSelect ? periodSelect.value : "30d";
      let visible = 0;
      cards.forEach((card) => {
        const show = matchesTemplate(
          card.textContent,
          card.dataset.category,
          query,
          activeCategory,
        );
        card.hidden = !show;
        if (show) visible += 1;

        const selectedPeriod = choosePeriod(
          card.dataset.periods,
          card.dataset.defaultPeriod,
          requestedPeriod,
        );
        const link = card.querySelector("[data-ai-template-use]");
        if (link) {
          const target = new URL(link.href, location.origin);
          target.searchParams.set("template", link.dataset.templateId);
          target.searchParams.set("period", selectedPeriod);
          link.href = `${target.pathname}${target.search}`;
        }
        const periodLabel = card.querySelector("[data-ai-period-label]");
        if (periodLabel) {
          const matchingOption = periodSelect
            ? Array.from(periodSelect.options).find((option) => option.value === selectedPeriod)
            : null;
          periodLabel.textContent = matchingOption ? matchingOption.textContent : selectedPeriod;
        }
      });
      if (results) results.textContent = `${visible} ${visible === 1 ? "plantilla" : "plantillas"}`;
      if (empty) empty.hidden = visible !== 0;
    };

    categoryButtons.forEach((button) => {
      button.addEventListener("click", () => {
        activeCategory = button.dataset.aiCategory;
        categoryButtons.forEach((candidate) => {
          const selected = candidate === button;
          candidate.classList.toggle("is-active", selected);
          candidate.setAttribute("aria-pressed", String(selected));
        });
        update();
      });
    });
    if (search) search.addEventListener("input", update);
    if (periodSelect) periodSelect.addEventListener("change", update);
    update();
  };

  return {
    choosePeriod,
    init,
    initAdaptiveCatalog,
    matchesCapability,
    matchesTemplate,
    normalizeText,
    updateStructuredPeriod,
  };
});
