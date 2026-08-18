/* Холст конструктора сценариев (F75).
 *
 * БЕЗ СБОРКИ И БЕЗ БИБЛИОТЕК. У админки нет ни npm, ни шага сборки, и заводить
 * их ради одной страницы значило бы, что владелец не сможет починить опечатку
 * в разметке без установки инструментов. Узлы — обычные элементы с абсолютными
 * координатами, связи — линии в SVG под ними.
 *
 * СХЕМА ПОЛЕЙ ПРИХОДИТ С СЕРВЕРА. Движок читает конфигурацию узла по именам
 * ключей; вторая копия описания здесь однажды разошлась бы с первой, и узел
 * молча перестал бы работать. Здесь только отрисовка того, что прислали.
 *
 * СВЯЗЬ РИСУЕТСЯ В ДВА КЛИКА, А НЕ ПРОТЯГИВАНИЕМ. Протягивание требует точного
 * попадания в маленькую точку и ломается на тачпаде; два клика работают
 * одинаково и мышью, и пальцем.
 */
(function () {
  "use strict";

  var KINDS = JSON.parse(document.getElementById("flow-kinds").textContent);
  var TEXT = JSON.parse(document.getElementById("flow-text").textContent);
  var graph = JSON.parse(document.getElementById("flow-graph").textContent);

  var canvas = document.getElementById("flow-canvas");
  var edgesLayer = document.getElementById("flow-edges");
  var palette = document.getElementById("flow-palette");
  var inspector = document.getElementById("flow-inspector");
  var statusLine = document.getElementById("flow-status");
  var problemsList = document.getElementById("flow-problems");

  var selected = null;      // ключ выделенного узла
  var connectFrom = null;   // ключ узла, от которого тянем связь
  var pending = null;       // связь, у которой осталось выбрать условие
  var dirty = false;
  /* Стопка прошлых состояний схемы. Настроенный узел собирают минутами, а
     удаляют одним промахом мыши; без отмены это значит собрать заново. Глубина
     ограничена: схема на полсотни узлов весит немного, но держать её историю
     бесконечно незачем. */
  var history = [];
  var HISTORY_LIMIT = 30;
  var kindByName = {};
  KINDS.forEach(function (item) { kindByName[item.kind] = item; });

  // --- утилиты ---

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function nextKey() {
    var used = {};
    graph.nodes.forEach(function (n) { used[n.node_key] = true; });
    for (var i = 1; i < 1000; i += 1) {
      if (!used["n" + i]) { return "n" + i; }
    }
    return "n" + Date.now();
  }

  function nodeByKey(key) {
    for (var i = 0; i < graph.nodes.length; i += 1) {
      if (graph.nodes[i].node_key === key) { return graph.nodes[i]; }
    }
    return null;
  }

  function remember() {
    history.push(JSON.stringify(graph));
    if (history.length > HISTORY_LIMIT) { history.shift(); }
  }

  function undo() {
    var previous = history.pop();
    if (!previous) {
      statusLine.textContent = TEXT.nothing_to_undo;
      statusLine.className = "flow-status muted";
      return;
    }
    graph = JSON.parse(previous);
    selected = null;
    connectFrom = null;
    pending = null;
    dirty = true;
    statusLine.textContent = TEXT.undone;
    statusLine.className = "flow-status warn";
    render();
  }

  function markDirty() {
    dirty = true;
    statusLine.textContent = TEXT.unsaved;
    statusLine.className = "flow-status warn";
  }

  // Уход со страницы с несохранённой схемой — потерянный труд владельца.
  window.addEventListener("beforeunload", function (event) {
    if (!dirty) { return undefined; }
    event.preventDefault();
    event.returnValue = "";
    return "";
  });

  // --- палитра ---

  function buildPalette() {
    var byCategory = {};
    KINDS.forEach(function (item) {
      (byCategory[item.category] = byCategory[item.category] || []).push(item);
    });
    Object.keys(byCategory).forEach(function (category) {
      palette.appendChild(el("h3", "flow-palette-title", TEXT["category_" + category]));
      byCategory[category].forEach(function (item) {
        var button = el("button", "flow-palette-item", item.label);
        button.type = "button";
        button.addEventListener("click", function () { addNode(item.kind); });
        palette.appendChild(button);
      });
    });
  }

  function addNode(kind) {
    var config = {};
    var defaults = kindByName[kind].defaults || {};
    Object.keys(defaults).forEach(function (name) { config[name] = defaults[name]; });
    // Новый узел ставится ниже последнего, а не в одну точку: иначе первые
    // добавленные оказываются друг под другом и их не видно.
    var y = 20;
    graph.nodes.forEach(function (n) { y = Math.max(y, n.y + 130); });
    var node = { node_key: nextKey(), kind: kind, config: config, x: 30, y: y };
    remember();
    graph.nodes.push(node);
    selected = node.node_key;
    markDirty();
    render();
  }

  // --- узлы на холсте ---

  function summary(node) {
    var config = node.config || {};
    var text = config.text || config.question || config.caption || config.tag || "";
    if (!text && config.variable) { text = config.variable; }
    if (!text && config.hours) { text = TEXT.hours_n.replace("{n}", config.hours); }
    if (!text && config.points) { text = "+" + config.points; }
    return String(text).slice(0, 70);
  }

  function renderNodes() {
    Array.prototype.slice.call(canvas.querySelectorAll(".flow-node")).forEach(
      function (old) { old.remove(); },
    );
    graph.nodes.forEach(function (node) {
      var card = el("div", "flow-node flow-node-" + kindByName[node.kind].category);
      card.style.left = node.x + "px";
      card.style.top = node.y + "px";
      card.dataset.key = node.node_key;
      if (node.node_key === selected) { card.classList.add("is-selected"); }
      if (node.node_key === connectFrom) { card.classList.add("is-connecting"); }

      card.appendChild(el("div", "flow-node-kind", kindByName[node.kind].label));
      card.appendChild(el("div", "flow-node-text", summary(node)));

      var link = el("button", "flow-node-link", "→");
      link.type = "button";
      link.title = TEXT.connect;
      link.addEventListener("click", function (event) {
        event.stopPropagation();
        startConnect(node.node_key);
      });
      card.appendChild(link);

      card.addEventListener("pointerdown", onNodePointerDown);
      card.addEventListener("click", function () { onNodeClick(node.node_key); });
      canvas.appendChild(card);
    });
  }

  function onNodeClick(key) {
    if (connectFrom && connectFrom !== key) {
      finishConnect(key);
      return;
    }
    selected = key;
    connectFrom = null;
    render();
  }

  function startConnect(key) {
    connectFrom = key;
    selected = key;
    statusLine.textContent = TEXT.connecting_hint;
    statusLine.className = "flow-status";
    render();
  }

  function finishConnect(toKey) {
    var from = nodeByKey(connectFrom);
    var conditions = kindByName[from.kind].conditions;
    if (conditions.length > 1) {
      // Условие выбирается КНОПКАМИ, а не вводом номера в системном окошке.
      // Ветвление — главное, зачем нужен конструктор; спрашивать «введите
      // номер» в том месте, где владелец решает судьбу диалога, значит
      // отдавать самое важное действие самому неудобному элементу.
      pending = { from: connectFrom, to: toKey, conditions: conditions };
      connectFrom = null;
      render();
      return;
    }
    addEdge(connectFrom, toKey, conditions[0].value);
  }

  function addEdge(fromKey, toKey, condition) {
    remember();
    graph.edges.push({
      from_key: fromKey, to_key: toKey,
      condition: condition, condition_value: null,
    });
    connectFrom = null;
    pending = null;
    markDirty();
    render();
  }

  function renderPending() {
    if (!pending) { return; }
    var box = el("div", "flow-chooser");
    box.appendChild(el("p", null, TEXT.choose_condition));
    pending.conditions.forEach(function (condition) {
      var button = el("button", "flow-chooser-item", condition.label);
      button.type = "button";
      button.addEventListener("click", function () {
        addEdge(pending.from, pending.to, condition.value);
      });
      box.appendChild(button);
    });
    var cancel = el("button", "secondary", TEXT.cancel);
    cancel.type = "button";
    cancel.addEventListener("click", function () { pending = null; render(); });
    box.appendChild(cancel);
    inspector.appendChild(box);
  }

  // --- перетаскивание ---

  var drag = null;

  function onNodePointerDown(event) {
    if (event.target.classList.contains("flow-node-link")) { return; }
    var card = event.currentTarget;
    var node = nodeByKey(card.dataset.key);
    drag = {
      key: node.node_key,
      startX: event.clientX, startY: event.clientY,
      originX: node.x, originY: node.y, moved: false,
    };
    // Захват указателя: без него узел «отлипает», стоит курсору выйти за
    // карточку, и человек роняет его в случайном месте.
    card.setPointerCapture(event.pointerId);
    card.addEventListener("pointermove", onNodePointerMove);
    card.addEventListener("pointerup", onNodePointerUp);
  }

  function onNodePointerMove(event) {
    if (!drag) { return; }
    var node = nodeByKey(drag.key);
    node.x = Math.max(0, drag.originX + (event.clientX - drag.startX));
    node.y = Math.max(0, drag.originY + (event.clientY - drag.startY));
    if (Math.abs(event.clientX - drag.startX) > 3
        || Math.abs(event.clientY - drag.startY) > 3) {
      drag.moved = true;
    }
    var card = event.currentTarget;
    card.style.left = node.x + "px";
    card.style.top = node.y + "px";
    renderEdges();
  }

  function onNodePointerUp(event) {
    var card = event.currentTarget;
    card.removeEventListener("pointermove", onNodePointerMove);
    card.removeEventListener("pointerup", onNodePointerUp);
    if (drag && drag.moved) { markDirty(); }
    drag = null;
  }

  // --- связи ---

  function centerOf(key) {
    var card = canvas.querySelector('.flow-node[data-key="' + key + '"]');
    if (!card) { return null; }
    return {
      x: card.offsetLeft + card.offsetWidth / 2,
      y: card.offsetTop + card.offsetHeight / 2,
      h: card.offsetHeight / 2,
    };
  }

  function renderEdges() {
    edgesLayer.innerHTML = "";
    var height = 400;
    graph.nodes.forEach(function (n) { height = Math.max(height, n.y + 200); });
    canvas.style.height = height + "px";
    edgesLayer.setAttribute("height", height);

    graph.edges.forEach(function (edge) {
      var from = centerOf(edge.from_key);
      var to = centerOf(edge.to_key);
      if (!from || !to) { return; }
      var line = document.createElementNS("http://www.w3.org/2000/svg", "path");
      var midY = (from.y + to.y) / 2;
      line.setAttribute(
        "d",
        "M " + from.x + " " + (from.y + from.h)
          + " C " + from.x + " " + midY + ", " + to.x + " " + midY
          + ", " + to.x + " " + (to.y - to.h),
      );
      line.setAttribute("class", "flow-edge flow-edge-" + edge.condition);
      edgesLayer.appendChild(line);

      var label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", (from.x + to.x) / 2);
      label.setAttribute("y", midY);
      label.setAttribute("class", "flow-edge-label");
      label.textContent = conditionLabel(nodeByKey(edge.from_key), edge.condition);
      edgesLayer.appendChild(label);
    });
  }

  function conditionLabel(node, condition) {
    if (!node) { return condition; }
    var found = kindByName[node.kind].conditions.filter(function (c) {
      return c.value === condition;
    });
    return found.length ? found[0].label : condition;
  }

  // --- правая колонка: поля узла ---

  function renderInspector() {
    inspector.innerHTML = "";
    if (pending) { renderPending(); return; }
    var node = selected ? nodeByKey(selected) : null;
    if (!node) {
      inspector.appendChild(el("p", "muted", TEXT.select_hint));
      return;
    }
    var meta = kindByName[node.kind];
    inspector.appendChild(el("h3", null, meta.label));
    inspector.appendChild(el("p", "muted", TEXT.node_key + ": " + node.node_key));

    meta.fields.forEach(function (field) {
      inspector.appendChild(buildField(node, field));
    });

    inspector.appendChild(el("h4", null, TEXT.edges_out));
    var outgoing = graph.edges.filter(function (e) { return e.from_key === node.node_key; });
    if (!outgoing.length) {
      inspector.appendChild(el("p", "muted", TEXT.no_edges));
    }
    outgoing.forEach(function (edge) {
      var row = el("div", "flow-edge-row");
      row.appendChild(el(
        "span", null,
        conditionLabel(node, edge.condition) + " → " + edge.to_key,
      ));
      // Значение кнопки: точный переход на конкретный ответ. Без него связь
      // работает как «на любую кнопку».
      if (edge.condition === "button") {
        var value = el("input", "flow-edge-value");
        value.type = "text";
        value.placeholder = TEXT.condition_value;
        value.value = edge.condition_value || "";
        value.addEventListener("change", function () {
          edge.condition_value = value.value.trim() || null;
          markDirty();
          renderEdges();
        });
        row.appendChild(value);
      }
      var remove = el("button", "secondary", TEXT.delete_edge);
      remove.type = "button";
      remove.addEventListener("click", function () {
        remember();
        graph.edges = graph.edges.filter(function (e) { return e !== edge; });
        markDirty();
        render();
      });
      row.appendChild(remove);
      inspector.appendChild(row);
    });

    var copy = el("button", "secondary flow-copy-node", TEXT.copy_node);
    copy.type = "button";
    copy.addEventListener("click", function () {
      // Копия БЕЗ связей: куда вести новый узел, знает только владелец, а
      // унаследованные переходы увели бы людей туда же, куда исходный.
      remember();
      var clone = JSON.parse(JSON.stringify(node));
      clone.node_key = nextKey();
      clone.x = node.x + 30;
      clone.y = node.y + 40;
      graph.nodes.push(clone);
      selected = clone.node_key;
      markDirty();
      render();
    });
    inspector.appendChild(copy);

    var removeNode = el("button", "secondary flow-delete-node", TEXT.delete_node);
    removeNode.type = "button";
    removeNode.addEventListener("click", function () {
      remember();
      graph.nodes = graph.nodes.filter(function (n) { return n !== node; });
      // Висящая связь ведёт в пустоту, и человек в такой ветке застревает —
      // связи удаляются вместе с узлом, а не оставляются владельцу на память.
      graph.edges = graph.edges.filter(function (e) {
        return e.from_key !== node.node_key && e.to_key !== node.node_key;
      });
      selected = null;
      markDirty();
      render();
    });
    inspector.appendChild(removeNode);
  }

  function buildField(node, field) {
    var wrap = el("label", "flow-field");
    wrap.appendChild(el("span", null, field.label + (field.required ? " *" : "")));
    var current = node.config[field.name];
    var input;

    if (field.type === "text") {
      input = el("textarea");
      input.rows = 3;
      input.value = current === undefined || current === null ? "" : current;
      input.addEventListener("input", function () {
        node.config[field.name] = input.value;
        markDirty();
        renderNodes();
      });
    } else if (field.type === "choice") {
      input = el("select");
      field.choices.forEach(function (choice) {
        var option = el("option", null, choice.label);
        option.value = choice.value;
        if (choice.value === current) { option.selected = true; }
        input.appendChild(option);
      });
      input.addEventListener("change", function () {
        node.config[field.name] = input.value;
        markDirty();
      });
    } else if (field.type === "list" || field.type === "buttons") {
      input = el("textarea");
      input.rows = 4;
      input.placeholder = field.type === "buttons" ? TEXT.buttons_hint : TEXT.list_hint;
      input.value = serializeList(field.type, current);
      input.addEventListener("input", function () {
        node.config[field.name] = parseList(field.type, input.value);
        markDirty();
        renderNodes();
      });
    } else {
      input = el("input");
      input.type = field.type === "number" ? "number" : "text";
      input.value = current === undefined || current === null ? "" : current;
      input.addEventListener("input", function () {
        var raw = input.value.trim();
        node.config[field.name] = field.type === "number" && raw !== ""
          ? Number(raw) : raw;
        markDirty();
        renderNodes();
      });
    }
    wrap.appendChild(input);
    return wrap;
  }

  /* Списки правятся ТЕКСТОМ, строка за строкой. Кнопки «добавить вариант» с
   * собственными полями — это ещё один слой состояния ради того же результата;
   * строчка на вариант понятна сразу и правится с клавиатуры. */
  function serializeList(type, value) {
    if (!value) { return ""; }
    if (type === "buttons") {
      return (value || []).map(function (b) {
        return b.label + (b.value ? " | " + b.value : "");
      }).join("\n");
    }
    return (value || []).join("\n");
  }

  function parseList(type, raw) {
    var lines = raw.split("\n").map(function (line) { return line.trim(); })
      .filter(function (line) { return line.length > 0; });
    if (type !== "buttons") { return lines; }
    return lines.map(function (line) {
      var parts = line.split("|");
      var label = parts[0].trim();
      return { label: label, value: (parts[1] || label).trim() };
    });
  }

  // --- сохранение ---

  function render() {
    renderNodes();
    renderEdges();
    renderInspector();
  }

  function showProblems(problems) {
    problemsList.innerHTML = "";
    (problems || []).forEach(function (problem) {
      problemsList.appendChild(el("li", "badge warn", problem));
    });
  }

  document.getElementById("flow-undo").addEventListener("click", undo);

  document.addEventListener("keydown", function (event) {
    // Ctrl+Z — то, что рука делает сама. Внутри поля ввода не перехватываем:
    // там отмена браузера отменяет набранный текст, и это правильнее.
    var inField = event.target && /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName);
    if ((event.ctrlKey || event.metaKey) && event.key === "z" && !inField) {
      event.preventDefault();
      undo();
    }
  });

  document.getElementById("flow-save").addEventListener("click", function () {
    statusLine.textContent = TEXT.saving;
    statusLine.className = "flow-status muted";
    fetch(window.FLOW_SAVE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nodes: graph.nodes, edges: graph.edges }),
    }).then(function (response) {
      return response.json().then(function (data) {
        return { ok: response.ok, data: data };
      });
    }).then(function (result) {
      if (!result.ok || !result.data.ok) {
        statusLine.textContent = TEXT.save_failed + " " + (result.data.error || "");
        statusLine.className = "flow-status warn";
        return;
      }
      dirty = false;
      statusLine.textContent = TEXT.saved;
      statusLine.className = "flow-status";
      // Проблемы графа показываются СРАЗУ после сохранения, а не только при
      // публикации: узнать о тупике через неделю, когда в сценарий пойдут
      // люди, — поздно.
      showProblems(result.data.problems);
    }).catch(function () {
      statusLine.textContent = TEXT.save_failed;
      statusLine.className = "flow-status warn";
    });
  });

  buildPalette();
  // На широком экране палитра всегда открыта: место есть, а лишний щелчок
  // перед каждым узлом — это лишний щелчок перед каждым узлом.
  if (window.matchMedia("(min-width: 901px)").matches) {
    document.getElementById("flow-palette-box").open = true;
  }
  render();
})();
