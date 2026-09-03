`decide("publish", ctx)` returns "allow" when `ctx` has `role: editor`, and returns "deny"
otherwise. `decide` still returns "deny" for any action that is not registered.
