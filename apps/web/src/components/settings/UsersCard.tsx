import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, UserPlus } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { useAuth } from "../../api/authContext";
import { api } from "../../api/client";
import { ConsoleLabel, EmptyNote } from "../overview/bits";
import { SettingsSection } from "./SettingsSection";

function detailOf(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  const m = msg.match(/\{"detail":"(.*?)"\}/);
  return m ? m[1] : msg;
}

/** Admin-only: manage the instance's accounts (capped seats). Not rendered for
 *  non-admins — the API also enforces the admin gate server-side. */
export function UsersCard() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const { data } = useQuery({ queryKey: ["users"], queryFn: () => api.listUsers() });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["users"] });

  const add = useMutation({
    mutationFn: () => api.createUser(username.trim(), password, isAdmin),
    onSuccess: () => {
      setUsername("");
      setPassword("");
      setIsAdmin(false);
      setError(null);
      invalidate();
    },
    onError: (e) => setError(detailOf(e)),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteUser(id),
    onSuccess: invalidate,
    onError: (e) => setError(detailOf(e)),
  });

  const users = data?.users ?? [];
  const max = data?.max_users ?? 5;
  const full = users.length >= max;

  return (
    <SettingsSection
      title="Users"
      action={
        <span className="shrink-0 font-mono text-[11px] text-muted-foreground/70">
          {users.length} / {max} seats
        </span>
      }
    >
      {users.length === 0 ? (
        <EmptyNote>No accounts yet.</EmptyNote>
      ) : (
        <ul className="flex flex-col items-stretch gap-1">
          {users.map((u) => (
            <li
              key={u.id}
              className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted/30"
            >
              <span className="min-w-0 flex-1 truncate text-sm text-foreground/90">
                {u.username}
                {u.id === user?.id && <span className="text-muted-foreground/60"> (you)</span>}
              </span>
              {u.is_admin && (
                <Badge className="border-transparent bg-primary/15 font-mono text-[10px] uppercase text-primary">
                  admin
                </Badge>
              )}
              <button
                onClick={() => remove.mutate(u.id)}
                // You cannot delete your own account. The server only refuses the LAST admin, so
                // with a second admin present this button was a one-click self-lockout — and the
                // "(you)" marker beside it was purely cosmetic.
                disabled={remove.isPending || u.id === user?.id}
                aria-label={`Remove ${u.username}`}
                title={u.id === user?.id ? "You can't remove your own account" : "Remove user"}
                className="flex size-6 items-center justify-center rounded border-0 bg-transparent p-0 text-muted-foreground/70 hover:bg-destructive/10 hover:text-destructive disabled:pointer-events-none disabled:opacity-40"
              >
                <Trash2 className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-col items-stretch gap-2 border-t border-border/40 pt-3">
        <ConsoleLabel>Add a user</ConsoleLabel>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="New username"
            placeholder="username"
            autoComplete="off"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-40 text-sm"
          />
          <Input
            type="password"
            aria-label="New password"
            placeholder="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-40 text-sm"
          />
          <label className="flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
            <input
              type="checkbox"
              checked={isAdmin}
              onChange={(e) => setIsAdmin(e.target.checked)}
              aria-label="Admin"
            />
            admin
          </label>
          <Button
            size="sm"
            onClick={() => add.mutate()}
            disabled={add.isPending || full || !username.trim() || !password}
          >
            <UserPlus className={cn("size-3.5", add.isPending && "opacity-50")} /> Add
          </Button>
        </div>
        {full && (
          <p className="font-mono text-[11px] text-muted-foreground/70">
            All {max} seats are used — remove one to add another.
          </p>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
    </SettingsSection>
  );
}
