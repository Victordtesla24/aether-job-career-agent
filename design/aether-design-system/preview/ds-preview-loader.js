/* Preview-only loader. Consuming projects get components from the compiled
   bundle on window.<Namespace>; inside this project the bundle may not exist
   yet, so this falls back to transpiling the .jsx sources with Babel.
   window.__DS is the resolved component map either way. */
(function () {
  var REG = {};
  window.__DS = REG;
  var COMPONENTS = [
    "components/core/Button.jsx",
    "components/core/StatusBadge.jsx",
    "components/core/Chip.jsx",
    "components/surfaces/Section.jsx",
    "components/surfaces/ListCard.jsx",
    "components/surfaces/StatBlock.jsx",
    "components/navigation/PageHeader.jsx",
    "components/navigation/SegmentedControl.jsx",
    "components/brand/Wordmark.jsx",
    "components/brand/OrnamentDivider.jsx",
    "components/feedback/MetricTooltip.jsx",
    "components/feedback/InlineNotice.jsx"
  ];
  function findNS() {
    var keys = Object.keys(window);
    for (var i = 0; i < keys.length; i++) {
      if (!/DesignSystem/i.test(keys[i])) continue;
      var v = window[keys[i]];
      if (v && typeof v === "object" && v.Button) return v;
    }
    return null;
  }
  async function tryBundle(base) {
    try {
      var r = await fetch(base + "_ds_bundle.js");
      if (!r.ok) return null;
      var s = document.createElement("script");
      s.textContent = await r.text();
      document.head.appendChild(s);
      return findNS();
    } catch (e) {
      return null;
    }
  }
  async function fromSource(base) {
    for (var i = 0; i < COMPONENTS.length; i++) {
      var p = COMPONENTS[i];
      var r = await fetch(base + p);
      if (!r.ok) { console.warn("[ds-preview] missing " + p); continue; }
      var src = await r.text();
      src = src.replace(/^\s*import\s.*$/gm, "").replace(/^\s*export\s+/gm, "");
      var name = p.split("/").pop().replace(/\.jsx?$/, "");
      var code = window.Babel.transform(src, { presets: ["react"] }).code;
      new Function("React", "__REG", code + "\n;__REG." + name + " = " + name + ";")(window.React, REG);
    }
    return REG;
  }
  window.DSPreview = {
    ensure: async function (base) {
      var ns = findNS();
      if (ns) { Object.assign(REG, ns); return REG; }
      var b = await tryBundle(base || "./");
      if (b) { Object.assign(REG, b); return REG; }
      return fromSource(base || "./");
    }
  };
})();
