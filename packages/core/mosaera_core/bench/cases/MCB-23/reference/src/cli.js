// Reference solution for MCB-23 — a minimal, dependency-free todo CLI. Used only to
// prove the hidden grader is winnable (soundness self-test); Mosaera never sees it.
// Plain ESM JS so it runs on any Node with no install; the brief asks the agent for
// a TypeScript implementation with tsc + tests, which the live run validates.
import { existsSync, readFileSync, writeFileSync } from "node:fs";

const file = process.env.TODO_FILE || "tasks.json";

function load() {
  if (!existsSync(file)) return [];
  try {
    const data = JSON.parse(readFileSync(file, "utf8"));
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

function save(tasks) {
  writeFileSync(file, JSON.stringify(tasks), "utf8");
}

function nextId(tasks) {
  return tasks.reduce((m, t) => Math.max(m, t.id), 0) + 1;
}

function fail(msg) {
  console.error(msg);
  process.exit(1);
}

const [cmd, ...rest] = process.argv.slice(2);
const tasks = load();

switch (cmd) {
  case "add": {
    const title = rest[0];
    if (title === undefined) fail("usage: add <title>");
    const id = nextId(tasks);
    tasks.push({ id, title, done: false });
    save(tasks);
    console.log(String(id));
    break;
  }
  case "list": {
    for (const t of [...tasks].sort((a, b) => a.id - b.id)) {
      console.log(`${t.id} [${t.done ? "x" : " "}] ${t.title}`);
    }
    break;
  }
  case "done":
  case "delete": {
    const id = Number(rest[0]);
    if (!Number.isInteger(id)) fail(`usage: ${cmd} <id>`);
    const idx = tasks.findIndex((t) => t.id === id);
    if (idx === -1) fail(`no task with id ${id}`);
    if (cmd === "done") tasks[idx].done = true;
    else tasks.splice(idx, 1);
    save(tasks);
    break;
  }
  default:
    fail(`unknown command: ${cmd ?? "(none)"}`);
}
