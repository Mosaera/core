# The install endpoint: serve the mirror, never a copy of it

`install.mosaera.dev` is the URL in the one-liner. It served a **static copy** of `install.sh`,
deployed once, and on **2026-09-02** it was six commits and 8,832 bytes behind the mirror:

```
install.mosaera.dev : f8d29a680448   Last-Modified: Fri, 28 Aug 2026
mirror main         : 5fb84c2026d5
```

Four installer fixes had shipped, been verified against the mirror, and reported as delivered —
while every operator kept running the 28 August script. Two of those were the terminal faults that
were re-reported on every single run, and the reason "it is fixed" and "it is still broken" were
both true at once. **A copy is a claim about a file somewhere else, and nothing was checking it.**

## The rule

**The endpoint proxies the mirror. It does not hold a copy.** Deploying the installer stops being a
step, so it cannot be a step that is forgotten. `install.sh` is a few kilobytes of text with a
5-minute upstream cache; there is nothing here worth the drift a copy costs.

## nginx / openresty

The endpoint runs openresty, so this is nginx configuration. In `http {}`:

```nginx
proxy_cache_path /var/cache/nginx/install levels=1:2 keys_zone=install:1m max_size=16m inactive=1h;
```

Then the server block:

```nginx
location = / {
    resolver 1.1.1.1 8.8.8.8 valid=300s ipv6=off;
    resolver_timeout 5s;

    # A variable upstream forces nginx to resolve at request time rather than pinning the IP it
    # saw at start-up — a GitHub CDN address that moved would otherwise fail until a reload.
    set $mirror "raw.githubusercontent.com";
    proxy_pass https://$mirror/Mosaera/core/main/scripts/install.sh;

    # VERIFY THE UPSTREAM. nginx does NOT verify proxied TLS by default, and this endpoint's whole
    # output is piped into `bash` on someone else's machine: without this, anything that can
    # intercept the proxy's connection to GitHub chooses what they execute.
    proxy_ssl_verify              on;
    proxy_ssl_verify_depth        2;
    proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
    proxy_ssl_server_name         on;
    proxy_ssl_name                raw.githubusercontent.com;
    proxy_set_header Host         raw.githubusercontent.com;

    # Short cache, and serve stale ONLY when upstream is unreachable — an install that runs a
    # slightly old script beats an install that cannot start, but staleness is never the norm.
    proxy_cache            install;
    proxy_cache_valid      200 60s;
    proxy_cache_use_stale  error timeout updating http_500 http_502 http_503 http_504;
    proxy_cache_lock       on;

    proxy_hide_header Cache-Control;
    add_header Cache-Control "no-cache" always;
    add_header X-Install-Source "raw.githubusercontent.com/Mosaera/core/main" always;
    default_type text/plain;
}
```

`X-Install-Source` is not decoration: it makes the answer to "what is this serving" readable from
the response, rather than something to infer from a byte count.

## If a proxy is not an option

A timer that pulls is second best, and it must **fail loudly** rather than leave the old file:

```bash
*/10 * * * * curl -fsSL --max-time 20 https://raw.githubusercontent.com/Mosaera/core/main/scripts/install.sh \
  -o /srv/install/install.sh.new && mv /srv/install/install.sh.new /srv/install/install.sh
```

`-f` so an error page is never written, a temp file plus `mv` so a truncated download never replaces
a working script, and no `|| true` — a silent failure here is exactly what this document exists
about.

## Check it, do not assume it

Whichever you choose, the endpoint is a second origin for a file, and this repo's rule is that a
second origin gets an independent check:

```bash
sh scripts/check-install-endpoint.sh
```

Exit `0` in sync, `1` drifted, `2` could not tell — that third one deliberately not folded into
either of the others. Run it after deploying and on a timer; it compares what the endpoint actually
serves against what the mirror actually serves, and cares about neither one's opinion of itself.
