// Hidden acceptance grader for MCB-23 (the TypeScript todo CLI).
//
// This is the ground truth — NEVER shown to Mosaera; injected into the delivered
// workspace only at grade time. Self-contained: Node built-ins only, with no
// dependency on the delivered package's own test framework. It drives the CLI as a
// black box via `npm start --silent -- <args>` (a fresh TODO_FILE per test) and
// prints the shared `N passed, N failed` summary the harness parses. Runs with the
// delivered workspace as cwd.
import { spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const isWin = process.platform === "win32";

function cli(args, todoFile) {
  const opts = {
    encoding: "utf8",
    env: { ...process.env, TODO_FILE: todoFile },
    timeout: 60000,
  };
  // In the Linux sandbox (where this runs in production) `npm` spawns directly. On
  // a Windows host (soundness self-test) npm is npm.cmd and needs a shell, so pass
  // the whole command as a quoted string. Both run: npm start --silent -- <args>.
  if (isWin) {
    const quoted = args.map((a) => `"${a}"`).join(" ");
    return spawnSync(`npm start --silent -- ${quoted}`, { ...opts, shell: true });
  }
  return spawnSync("npm", ["start", "--silent", "--", ...args], opts);
}

function freshTodo() {
  return join(mkdtempSync(join(tmpdir(), "mcb23-")), "tasks.json");
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

test("add prints id and list shows it", () => {
  const f = freshTodo();
  const added = cli(["add", "buy milk"], f);
  assert(added.status === 0, "add should exit 0");
  assert(added.stdout.trim().length > 0, "add should print the new id");
  const listed = cli(["list"], f);
  assert(listed.status === 0, "list should exit 0");
  assert(listed.stdout.includes("buy milk"), "list should show the task");
  assert(listed.stdout.includes("[ ]"), "a new task is not done");
});

test("list empty is blank and exit 0", () => {
  const f = freshTodo();
  const listed = cli(["list"], f);
  assert(listed.status === 0, "list should exit 0");
  assert(listed.stdout.trim() === "", "an empty list prints nothing");
});

test("done marks the task", () => {
  const f = freshTodo();
  const id = cli(["add", "walk dog"], f).stdout.trim().split(/\s+/).pop();
  assert(cli(["done", id], f).status === 0, "done should exit 0");
  const listed = cli(["list"], f);
  assert(
    listed.stdout.includes("walk dog") && listed.stdout.includes("[x]"),
    "the task should be marked done"
  );
});

test("delete removes the task", () => {
  const f = freshTodo();
  const id = cli(["add", "temporary"], f).stdout.trim().split(/\s+/).pop();
  assert(cli(["delete", id], f).status === 0, "delete should exit 0");
  assert(!cli(["list"], f).stdout.includes("temporary"), "the task should be gone");
});

test("ids are stable across add and done", () => {
  const f = freshTodo();
  cli(["add", "first"], f);
  const second = cli(["add", "second"], f).stdout.trim().split(/\s+/).pop();
  cli(["done", second], f);
  const lines = cli(["list"], f).stdout.split("\n").filter((l) => l.trim());
  assert(lines.some((l) => l.includes("first") && l.includes("[ ]")), "first stays not-done");
  assert(lines.some((l) => l.includes("second") && l.includes("[x]")), "second is done");
});

test("persistence across processes", () => {
  const f = freshTodo();
  cli(["add", "persist me"], f);
  const listed = cli(["list"], f); // a separate process must see it
  assert(listed.stdout.includes("persist me"), "the task should persist across processes");
});

test("unknown command exits nonzero", () => {
  const r = cli(["frobnicate"], freshTodo());
  assert(r.status !== 0, "an unknown command should exit nonzero");
});

test("operation on missing id exits nonzero", () => {
  const r = cli(["done", "9999"], freshTodo());
  assert(r.status !== 0, "an operation on a non-existent id should exit nonzero");
});

let passed = 0;
let failed = 0;
for (const [name, fn] of tests) {
  try {
    fn();
    passed++;
  } catch (e) {
    failed++;
    console.log(`FAIL: ${name}: ${e.message}`);
  }
}
console.log(`${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
