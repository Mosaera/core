import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { api } from "../api/client";
import { Spinner } from "../components/AgentStatus";
import { ConsoleLabel } from "../components/overview/bits";

const CARD = "flex flex-col gap-4 rounded-lg bg-card p-5 ring-1 ring-white/12";

/** Ad-hoc (project-less) run dispatch. Mirrors NewProjectPage's form language. */
export function SubmitPage() {
  const navigate = useNavigate();
  const [repo, setRepo] = useState("");
  const [task, setTask] = useState("");
  const [sandbox, setSandbox] = useState("docker");
  const [scan, setScan] = useState(true);
  const [maxIterations, setMaxIterations] = useState("3");
  const [testCmd, setTestCmd] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const snap = await api.submitRun({
        repo: repo.trim(),
        task: task.trim(),
        scan,
        sandbox,
        max_iterations: maxIterations ? Number(maxIterations) : null,
        test_cmd: testCmd.trim() || null,
      });
      navigate(`/runs/${snap.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight">Commission a run</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          The team works on an isolated clone of the target repository, runs tests in a sandbox,
          scans for secrets, and pauses for your approval before anything is delivered. Your
          source is never touched.
        </p>
      </div>

      <form className={CARD} onSubmit={submit}>
        <div className="flex flex-col gap-1.5">
          <ConsoleLabel>Target repository — path or URL</ConsoleLabel>
          <Input
            aria-label="Target repository"
            placeholder="/path/to/repo  or  https://github.com/org/repo.git"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            required
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <ConsoleLabel>Task</ConsoleLabel>
          <textarea
            aria-label="Task"
            placeholder="e.g. The test suite has one failing test. Find the bug and fix it."
            value={task}
            onChange={(e) => setTask(e.target.value)}
            required
            rows={4}
            className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none transition-[color,box-shadow] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <ConsoleLabel>Sandbox</ConsoleLabel>
            <Select value={sandbox} onValueChange={(v) => setSandbox(v ?? "docker")}>
              <SelectTrigger aria-label="Sandbox">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="docker">docker — hardened container</SelectItem>
                <SelectItem value="subprocess">subprocess — no-Docker fallback</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <ConsoleLabel>Max iterations</ConsoleLabel>
            <Input
              type="number"
              aria-label="Max iterations"
              min={1}
              max={10}
              value={maxIterations}
              onChange={(e) => setMaxIterations(e.target.value)}
            />
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <ConsoleLabel>Test command (optional)</ConsoleLabel>
          <Input
            aria-label="Test command"
            placeholder="default: python -m pytest -q · use 'true' to skip"
            value={testCmd}
            onChange={(e) => setTestCmd(e.target.value)}
            className="font-mono text-xs"
          />
        </div>

        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={scan}
            onChange={(e) => setScan(e.target.checked)}
          />
          <span className="font-mono text-[12.5px]">Run security scanners (Gitleaks + Semgrep)</span>
        </label>

        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}

        <div className="flex justify-end">
          <Button type="submit" disabled={busy || !repo || !task}>
            {busy ? <Spinner className="text-primary-foreground" /> : "Dispatch run →"}
          </Button>
        </div>
      </form>
    </div>
  );
}
