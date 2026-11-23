// Persistent browser bridge for record_playbook.py: one Node process per run instead of one per step.
// record_playbook_bridge.py prepends `const BRIDGE = {...};` and feeds the whole module through stdin,
// so neither the session token nor page data appear in process arguments. The bridge connects back to
// the Python side's loopback listener, says hello with the token, then answers one JSON line per request.
// Hosts: "stage" (the isolated WKWebView stage), "browser" (ego-browser task space) and "cdp"
// (any Chromium browser the user started with --remote-debugging-port; no automation overlay).
const net = await import("node:net");

const MSG = BRIDGE.messages;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

function sameURL(actual, target) {
  try {
    const a = new URL(actual), b = new URL(target);
    return (a.protocol === b.protocol || (b.protocol === "http:" && a.protocol === "https:"))
      && a.hostname === b.hostname && a.port === b.port && a.username === b.username && a.password === b.password
      && (a.pathname || "/") === (b.pathname || "/") && a.search === b.search && a.hash === b.hash;
  } catch { return false; }
}

// Wheel fallback for hosts without native wheel input: scrolls the nearest scrollable ancestor of the
// element under the pointer. It cannot reach into cross-origin frames; the cdp and browser hosts can.
const scrollAtPoint = ({ x, y, deltaX, deltaY }) => {
  const root = document.scrollingElement || document.documentElement;
  let node = document.elementFromPoint(x, y);
  for (; node && node !== root; node = node.parentElement) {
    const style = getComputedStyle(node);
    if ((node.scrollHeight > node.clientHeight + 1 && /auto|scroll/.test(style.overflowY))
      || (node.scrollWidth > node.clientWidth + 1 && /auto|scroll/.test(style.overflowX))) break;
  }
  (node && node !== root ? node : root).scrollBy({ left: deltaX, top: deltaY, behavior: "instant" });
  return true;
};

async function stageHost() {
  const base = BRIDGE.stageURL;
  const token = process.env.OILSTUDIO_PLAYBOOK_STAGE_TOKEN;
  const request = async (path, payload) => {
    const headers = { authorization: `Bearer ${token}` };
    if (payload) headers["content-type"] = "application/json";
    const response = await fetch(base + path, { method: payload ? "POST" : "GET", headers,
      body: payload ? JSON.stringify(payload) : undefined });
    const value = await response.json();
    if (!value.ok) throw new Error(value.error || MSG.stageRequestFailed);
    return value.result;
  };
  const waitState = async (predicate, timeout = 20000) => {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      const state = await request("/state");
      if (predicate(state)) return state;
      await sleep(100);
    }
    throw new Error(MSG.stageWaitTimeout);
  };
  let pointer = { x: 0, y: 0 };
  const page = {
    label: "stage-window", targetId: "stage-window",
    goto: async url => { await request("/goto", { url });
      return await waitState(state => sameURL(state.url, url) && ["interactive", "complete"].includes(state.readyState)); },
    waitForLoadState: async () => await waitState(state => ["interactive", "complete"].includes(state.readyState)),
    waitForTimeout: async ms => await sleep(ms),
    url: async () => (await request("/state")).url,
    title: async () => (await request("/state")).title,
    evaluate: async (fn, argument) => {
      const isFunction = typeof fn === "function";
      const value = await request("/evaluate", { script: isFunction ? fn.toString() : String(fn),
        mode: isFunction ? "function" : "script", argument: argument ?? null });
      if (value && typeof value === "object" && value.innerWidth > 0 && value.outerWidth === 0) value.outerWidth = value.innerWidth;
      if (value && typeof value === "object" && value.innerHeight > 0 && value.outerHeight === 0) value.outerHeight = value.innerHeight;
      return value;
    },
    click: async selector => await request("/selector", { selector, action: "click" }),
    hover: async selector => await request("/selector", { selector, action: "hover" }),
    cdp: async () => ({}),
    mouse: {
      click: async (x, y) => { pointer = { x, y }; return await request("/point", { x, y, action: "click" }); },
      move: async (x, y) => { pointer = { x, y }; return await request("/point", { x, y, action: "move" }); },
      wheel: async (deltaX, deltaY) => await page.evaluate(scrollAtPoint, { ...pointer, deltaX, deltaY }),
    },
  };
  const task = {
    tabs: async () => [{ active: true, targetId: "stage-window", label: "stage-window" }],
    cdp: async () => ({}),
    finish: async () => ({}),
  };
  return { task, main: page, open: null, activate: async () => {} };
}

async function egoHost() {
  const task = await taskSpace(BRIDGE.space);
  let main;
  if (BRIDGE.page === "user") {
    const userPage = task.userPage();
    if (!userPage) throw new Error(MSG.noUserPage);
    main = userPage.label ? userPage : await task.adopt(userPage);
  } else {
    const pages = await task.pages();
    if (!pages.some(item => item.label === BRIDGE.page)) throw new Error(MSG.pageNotManagedPrefix + BRIDGE.page);
    main = task.page(BRIDGE.page);
  }
  return {
    task, main,
    open: async url => { const page = await task.newPage(); await page.goto(url); return page; },
    activate: async page => { await page.cdp("Page.bringToFront"); },
  };
}

async function cdpHost() {
  if (typeof WebSocket !== "function") throw new Error(MSG.cdpNeedsNode);
  const endpoint = BRIDGE.cdpURL.replace(/\/+$/, "");
  const http = async path => {
    let response;
    try { response = await fetch(endpoint + path); } catch { throw new Error(MSG.cdpUnavailable); }
    if (!response.ok) throw new Error(MSG.cdpUnavailable);
    return await response.json();
  };
  const connect = async url => {
    const socket = new WebSocket(url);
    await new Promise((resolve, reject) => {
      socket.addEventListener("open", resolve, { once: true });
      socket.addEventListener("error", () => reject(new Error(MSG.cdpUnavailable)), { once: true });
    });
    let next = 0;
    const pending = new Map(), waiters = [];
    socket.addEventListener("message", event => {
      const message = JSON.parse(event.data);
      if (message.id && pending.has(message.id)) {
        const { resolve, reject } = pending.get(message.id);
        pending.delete(message.id);
        if (message.error) reject(new Error(message.error.message)); else resolve(message.result ?? {});
      } else if (message.method) {
        for (const waiter of waiters.filter(item => item.method === message.method)) {
          waiters.splice(waiters.indexOf(waiter), 1); waiter.resolve(message.params ?? {});
        }
      }
    });
    socket.addEventListener("close", () => {
      for (const { reject } of pending.values()) reject(new Error(MSG.cdpClosed));
      pending.clear();
    });
    return {
      send: (method, params = {}) => new Promise((resolve, reject) => {
        const id = ++next; pending.set(id, { resolve, reject });
        socket.send(JSON.stringify({ id, method, params }));
      }),
      // Registered before the command that triggers it, so a fast event is not missed.
      event: (method, timeout) => new Promise((resolve, reject) => {
        const waiter = { method, resolve };
        waiters.push(waiter);
        setTimeout(() => { const index = waiters.indexOf(waiter);
          if (index >= 0) { waiters.splice(index, 1); reject(new Error(MSG.cdpLoadTimeout)); } }, timeout);
      }),
      close: () => socket.close(),
    };
  };
  const browser = await connect((await http("/json/version")).webSocketDebuggerUrl);
  const pageTargets = async () => (await http("/json/list")).filter(target => target.type === "page");
  const makePage = async target => {
    const session = await connect(target.webSocketDebuggerUrl);
    await session.send("Page.enable");
    let pointer = { x: 0, y: 0 };
    const evaluate = async (fn, argument) => {
      const expression = typeof fn === "function" ? `(${fn.toString()})(${JSON.stringify(argument ?? null)})` : String(fn);
      const result = await session.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true, userGesture: true });
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result?.value;
    };
    const readyState = async () => { try { return await evaluate("document.readyState"); } catch { return "loading"; } };
    const input = (type, x, y, extra = {}) => session.send("Input.dispatchMouseEvent", { type, x, y, ...extra });
    const center = async selector => {
      const point = await evaluate(value => {
        const element = document.querySelector(value);
        if (!element) return null;
        let rect = element.getBoundingClientRect();
        if (rect.bottom < 0 || rect.top > innerHeight || rect.right < 0 || rect.left > innerWidth) {
          element.scrollIntoView({ block: "center", inline: "center" }); rect = element.getBoundingClientRect();
        }
        return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
      }, selector);
      if (!point) throw new Error(MSG.noElementPrefix + selector);
      return point;
    };
    const click = async ({ x, y }) => {
      pointer = { x, y };
      await input("mouseMoved", x, y);
      await input("mousePressed", x, y, { button: "left", buttons: 1, clickCount: 1 });
      await input("mouseReleased", x, y, { button: "left", buttons: 0, clickCount: 1 });
    };
    const move = async ({ x, y }) => { pointer = { x, y }; await input("mouseMoved", x, y); };
    return {
      label: target.id, targetId: target.id,
      goto: async url => {
        const loaded = session.event("Page.domContentEventFired", 30000);
        const navigation = await session.send("Page.navigate", { url });
        if (navigation.errorText) throw new Error(navigation.errorText);
        if (navigation.loaderId) await loaded; else loaded.catch(() => {});
        return { url: await evaluate("location.href"), title: await evaluate("document.title") };
      },
      waitForLoadState: async () => {
        const start = Date.now();
        while (!["interactive", "complete"].includes(await readyState())) {
          if (Date.now() - start > 30000) throw new Error(MSG.cdpLoadTimeout);
          await sleep(100);
        }
      },
      waitForTimeout: async ms => await sleep(ms),
      url: async () => await evaluate("location.href"),
      title: async () => await evaluate("document.title"),
      evaluate,
      click: async selector => await click(await center(selector)),
      hover: async selector => await move(await center(selector)),
      cdp: async (method, params) => await session.send(method, params),
      mouse: {
        click: async (x, y) => await click({ x, y }),
        move: async (x, y) => await move({ x, y }),
        wheel: async (deltaX, deltaY) => await input("mouseWheel", pointer.x, pointer.y, { deltaX, deltaY }),
      },
    };
  };
  const pages = new Map();
  const pageFor = async target => {
    if (!pages.has(target.id)) pages.set(target.id, await makePage(target));
    return pages.get(target.id);
  };
  // A tab the user already opened at the same address keeps its sign-in and scroll position.
  const findOrCreate = async (url, background) => {
    let target = (await pageTargets()).find(item => sameURL(item.url, url));
    if (!target) {
      const { targetId } = await browser.send("Target.createTarget", { url, background });
      for (let attempt = 0; attempt < 50 && !target; attempt++) {
        target = (await pageTargets()).find(item => item.id === targetId);
        if (!target) await sleep(100);
      }
      if (!target) throw new Error(MSG.cdpUnavailable);
    }
    return await pageFor(target);
  };
  let active = null;
  const main = await findOrCreate(BRIDGE.firstURL, false);
  const activate = async page => { await browser.send("Target.activateTarget", { targetId: page.targetId }); active = page; };
  await activate(main);
  const task = {
    tabs: async () => (await pageTargets()).map(target => ({ targetId: target.id, label: target.id, url: target.url,
      title: target.title, active: active?.targetId === target.id })),
    cdp: async (method, params) => await browser.send(method, params),
    // The user's browser and tabs stay as they are.
    finish: async () => ({}),
  };
  return { task, main, open: async url => await findOrCreate(url, true), activate };
}

const socket = net.connect(BRIDGE.port, "127.0.0.1");
socket.setEncoding("utf8");
await new Promise((resolve, reject) => { socket.once("connect", resolve); socket.once("error", reject); });
// Without the Python side there is nothing to answer; don't linger holding browser connections.
socket.on("close", () => process.exit(0));
socket.on("error", () => process.exit(1));
const send = value => socket.write(JSON.stringify(value) + "\n");
send({ hello: BRIDGE.token });

let host = null, current = null;
const tabs = new Map();
try {
  host = await (BRIDGE.mode === "stage" ? stageHost() : BRIDGE.mode === "cdp" ? cdpHost() : egoHost());
  current = host.main;
  tabs.set("main", host.main);
  send({ ready: true });
} catch (error) {
  send({ ready: false, error: String(error?.message || error) });
}

async function handle(request) {
  if (request.op === "openTab") {
    if (!host.open) throw new Error(MSG.tabsUnsupported);
    tabs.set(request.tab, await host.open(request.url));
    return { tab: request.tab, page: tabs.get(request.tab).label };
  }
  if (request.op === "switchTab") {
    const page = tabs.get(request.tab);
    if (!page) throw new Error(MSG.tabUnknownPrefix + request.tab);
    await host.activate(page);
    current = page;
    return { tab: request.tab, page: page.label };
  }
  const body = new AsyncFunction("page", "task", request.body);
  return await body(current, host.task);
}

let buffer = "", queue = Promise.resolve();
await new Promise(resolve => {
  socket.on("data", chunk => {
    buffer += chunk;
    let index;
    while ((index = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, index); buffer = buffer.slice(index + 1);
      if (!line.trim()) continue;
      const request = JSON.parse(line);
      if (request.op === "close") { socket.end(); resolve(); return; }
      queue = queue.then(async () => {
        try { send({ id: request.id, ok: true, value: (await handle(request)) ?? null }); }
        catch (error) { send({ id: request.id, ok: false, error: String(error?.stack || error?.message || error) }); }
      });
    }
  });
});
process.exit(0);
