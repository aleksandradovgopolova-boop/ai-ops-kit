// Выполняется внутри страницы пульта. Координаты измеряет движок Chrome.
(async () => {
  while (document.readyState !== "complete") await new Promise(resolve => setTimeout(resolve, 20));
  const q = selector => document.querySelector(selector);
  const all = selector => Array.from(document.querySelectorAll(selector));
  const rect = el => el.getBoundingClientRect();
  const visible = el => el && rect(el).height > 0 && rect(el).width > 0;
  const name = el => el.id || el.getAttribute("aria-label") || el.className || el.tagName;
  const within = (r, box) => r.left >= box.left - 1 && r.right <= box.right + 1 &&
    r.top >= box.top - 1 && r.bottom <= box.bottom + 1;
  const panels = all("main > section, header, footer").filter(visible);
  const bounds = {left:0, right:innerWidth, top:0, bottom:innerHeight};
  const boxes = panels.filter(el => !within(rect(el), bounds)).map(name);
  const overlaps = [];
  const clipped = [];
  for (const [i, el] of panels.entries()) {
    const box = rect(el);
    for (const other of panels.slice(i + 1)) {
      const r = rect(other);
      if (Math.min(box.right, r.right) - Math.max(box.left, r.left) > 1 &&
          Math.min(box.bottom, r.bottom) - Math.max(box.top, r.top) > 1) {
        overlaps.push([name(el), name(other)]);
      }
    }
    for (const child of el.querySelectorAll("button, summary, .hp, .mtile, .rh, .node, .preview-title")) {
      if (visible(child) && !within(rect(child), box)) clipped.push([name(el), name(child)]);
    }
  }
  const result = {
    viewport:[innerWidth,innerHeight], document:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],
    publishedReleaseAvailable:!!q('[data-modal="published-release"]'),
    footer:visible(q("footer")), panels:panels.map(name), boxes, overlaps, clipped, dialogs:{}
  };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  function click(el) {
    if (!visible(el)) throw Error("Элемент недоступен: " + el?.outerHTML.slice(0, 90));
    const r = rect(el);
    if (!el.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2))) {
      throw Error("Элемент перекрыт: " + el.dataset.modal + " → " + name(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)));
    }
    el.focus();
    el.click();
  }
  async function until(predicate, message) {
    const deadline = performance.now() + 2000;
    while (!predicate()) {
      if (performance.now() > deadline) throw Error(message);
      await sleep(12);
    }
  }
  const inDialog = () => visible(q("[role=dialog]")) && q("[role=dialog]").contains(document.activeElement);
  async function dialog(key, trigger, returnTo = trigger) {
    click(trigger);
    await until(inDialog, "Фокус не перешёл в диалог: " + key);
    if (key === "panel:release") {
      const summary = q("#modal-body details summary");
      if (summary) {
        summary.scrollIntoView({block:"center", behavior:"instant"});
        click(summary);
      }
    }
    function typography(selector) {
      const el = q("#modal-body " + selector);
      if (!el) return null;
      const css = getComputedStyle(el);
      return {size:css.fontSize, family:css.fontFamily, leading:css.lineHeight, color:css.color};
    }
    result.dialogs[key] = {
      title:q("#modal-title").innerText, text:q("#modal-body").textContent,
      type: {
        lead:typography(".lead"), section:typography(".mh"), detail:typography(".mrow .md"),
        paragraph:typography(".release-notes p"), heading:typography(".release-notes h3"),
        item:typography(".release-notes li"), source:typography(".release-notes .source-link")
      },
      detailsOpen: q("#modal-body details")?.open,
      links:Array.from(q("[role=dialog]").querySelectorAll("a[href]"), a => a.href)
    };
    document.dispatchEvent(new KeyboardEvent("keydown", {key:"Escape", bubbles:true}));
    await until(() => !visible(q("[role=dialog]")), "Диалог не закрылся: " + key);
    result.dialogs[key].closed = !visible(q("[role=dialog]"));
    result.dialogs[key].focusReturned = document.activeElement === returnTo;
  }
  try {
    const trigger = key => q(`[data-modal="${key}"]`);
    for (const key of ["panel:release","published-release"]) await dialog(key, trigger(key));
    const listButton = trigger("panel:artifacts");
    const cards = all("#spine [data-modal]").map(el => el.dataset.modal);
    result.cards = cards;
    for (const key of cards) {
      const selector = `[data-modal="${key}"]`;
      let card = q("#spine " + selector);
      let returnTo = card;
      if (!visible(card)) {
        click(listButton);
        await until(inDialog, "Не открыт список артефактов");
        card = q("#modal-body " + selector);
        returnTo = listButton;
        if (visible(card)) card.scrollIntoView({block:"center", behavior:"instant"});
      }
      await dialog(key, card, returnTo);
    }
  } catch (error) {
    result.error = String(error);
  }
  return result;
})();
