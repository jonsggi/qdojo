# The spectator site is static files: the combat site (index.html), the
# retired riddle arcade kept read-only (legacy.html), and the JSON the house
# exports. Nothing here runs Python, holds a seed, or can sign anything --
# it serves apps/web and nothing else.
FROM nginx:1.27-alpine

COPY apps/web/ /usr/share/nginx/html/

# Every build stamps each page's own script and stylesheet URLs with a
# version, so a CDN in front cannot keep serving last week's app.js beside this
# week's data: a new URL is a new object. Every .html is stamped, and relative
# paths such as combat/app.js count; absolute URLs (fonts) have a ':' and are
# left alone. Both real pages must end up stamped or the build fails.
RUN v=$(date +%s) && for f in /usr/share/nginx/html/*.html; do \
      sed -E -i "s#(src|href)=\"([a-z0-9_-]+(/[a-z0-9_-]+)*\.(js|css))\"#\1=\"\2?v=$v\"#g" "$f"; \
    done && grep -q "combat/app.js?v=$v" /usr/share/nginx/html/index.html \
    && grep -q "app.js?v=$v" /usr/share/nginx/html/legacy.html

# dash.html/dash.js are the LOCAL fighter page, served by `qdojo bot dash` on
# 127.0.0.1 against an API that exists only on the player's own machine. On the
# public site they would be a dead page, so they do not ship in this image.
RUN rm -f /usr/share/nginx/html/dash.html /usr/share/nginx/html/dash.js

# llms.txt (and legacy-llms.txt, the signed riddle briefing) must arrive as
# readable text, not a download, because the whole
# point is that a person or an agent can open it in a browser. The page's own
# files say max-age=300: without an origin header the CDN in front kept an
# old app.js for four hours after a deploy, so the site showed new data with
# old code (2026-09-21).
#
# Live combat data (/data/combat/v1/) is not baked into the image: it is
# proxied to the live devnet's data server, so spectators see fights within
# seconds and main is not flooded with data commits. If that server is down,
# the copy baked into the image answers instead and the page's STALE badge
# shows its age. QDOJO_LIVE_DATA is substituted by the nginx image's template
# step at container start; nothing else in the config is an env variable.
#
# The read API (/api/v1/: full history, pagination, search; docs/api.md §3.2)
# is `qdojo combat api` on the same host. It replaces the static data server
# and also serves /data/combat/v1/, so both usually point at one port. If it is
# down, /api/v1/ answers a JSON 503 and the site falls back to the static
# files. Writes (outside builders joining the demo arena, docs/build-a-bot.md
# §8) are refused here unless QDOJO_JOIN_OPEN=1, whatever the API allows.
ENV QDOJO_LIVE_DATA=http://100.101.145.63:8790
ENV QDOJO_LIVE_API=http://100.101.145.63:8790
ENV QDOJO_JOIN_OPEN=0
RUN mkdir -p /etc/nginx/templates && printf '%s\n' \
    'types { text/plain txt; }' \
    'map $request_method $qdojo_write { default 1; GET 0; HEAD 0; OPTIONS 0; }' \
    '# Client address: walk X-Forwarded-For from the right, skipping only our own proxies' \
    '# (Docker/Traefik private ranges) and Cloudflare edges, so entries a client wrote itself' \
    '# are never trusted. Cloudflare ranges from cloudflare.com/ips (2026-09-26).' \
    'real_ip_header X-Forwarded-For;' \
    'real_ip_recursive on;' \
    'set_real_ip_from 10.0.0.0/8;' \
    'set_real_ip_from 172.16.0.0/12;' \
    'set_real_ip_from 192.168.0.0/16;' \
    'set_real_ip_from 100.64.0.0/10;' \
    'set_real_ip_from 127.0.0.0/8;' \
    'set_real_ip_from fc00::/7;' \
    'set_real_ip_from ::1/128;' \
    'set_real_ip_from 173.245.48.0/20;' \
    'set_real_ip_from 103.21.244.0/22;' \
    'set_real_ip_from 103.22.200.0/22;' \
    'set_real_ip_from 103.31.4.0/22;' \
    'set_real_ip_from 141.101.64.0/18;' \
    'set_real_ip_from 108.162.192.0/18;' \
    'set_real_ip_from 190.93.240.0/20;' \
    'set_real_ip_from 188.114.96.0/20;' \
    'set_real_ip_from 197.234.240.0/22;' \
    'set_real_ip_from 198.41.128.0/17;' \
    'set_real_ip_from 162.158.0.0/15;' \
    'set_real_ip_from 104.16.0.0/13;' \
    'set_real_ip_from 104.24.0.0/14;' \
    'set_real_ip_from 172.64.0.0/13;' \
    'set_real_ip_from 131.0.72.0/22;' \
    'set_real_ip_from 2400:cb00::/32;' \
    'set_real_ip_from 2606:4700::/32;' \
    'set_real_ip_from 2803:f800::/32;' \
    'set_real_ip_from 2405:b500::/32;' \
    'set_real_ip_from 2405:8100::/32;' \
    'set_real_ip_from 2a06:98c0::/29;' \
    'set_real_ip_from 2c0f:f248::/32;' \
    '# If the walk ends at a Cloudflare edge (the proxy in front replaced X-Forwarded-For),' \
    '# the client is the one Cloudflare names in CF-Connecting-IP, a header it always overwrites.' \
    'geo $qdojo_peer_is_cf { default 0;173.245.48.0/20 1; 103.21.244.0/22 1; 103.22.200.0/22 1; 103.31.4.0/22 1; 141.101.64.0/18 1; 108.162.192.0/18 1; 190.93.240.0/20 1; 188.114.96.0/20 1; 197.234.240.0/22 1; 198.41.128.0/17 1; 162.158.0.0/15 1; 104.16.0.0/13 1; 104.24.0.0/14 1; 172.64.0.0/13 1; 131.0.72.0/22 1; 2400:cb00::/32 1; 2606:4700::/32 1; 2803:f800::/32 1; 2405:b500::/32 1; 2405:8100::/32 1; 2a06:98c0::/29 1; 2c0f:f248::/32 1; }' \
    'map $qdojo_peer_is_cf $qdojo_client { default $remote_addr; 1 $http_cf_connecting_ip; }' \
    'map $request_method $qdojo_write_key { default $qdojo_client; GET ""; HEAD ""; OPTIONS ""; }' \
    'limit_req_zone $qdojo_write_key zone=qdojo_join:1m rate=5r/s;' \
    'server {' \
    '  listen 80;' \
    '  root /usr/share/nginx/html;' \
    '  index index.html;' \
    '  charset utf-8;' \
    '  location = /llms.txt { default_type text/plain; }' \
    '  location = /legacy-llms.txt { default_type text/plain; }' \
    '  location ~ \.py$ { default_type text/plain; }' \
    '  location /data/combat/v1/ {' \
    '    proxy_pass ${QDOJO_LIVE_DATA}/;' \
    '    proxy_connect_timeout 2s;' \
    '    proxy_read_timeout 5s;' \
    '    proxy_intercept_errors on;' \
    '    error_page 404 502 503 504 = @baked;' \
    '    add_header Cache-Control "public, max-age=5" always;' \
    '  }' \
    '  location /api/v1/ {' \
    '    default_type application/json;' \
    '    set $qdojo_gate "${qdojo_write}${QDOJO_JOIN_OPEN}";' \
    '    if ($qdojo_gate = "10") { return 403 "{\"schema\":\"qdojo.combat.api.error.v1\",\"error\":{\"status\":403,\"code\":\"join_closed\",\"message\":\"this arena does not accept writes\"}}"; }' \
    '    limit_req zone=qdojo_join burst=20 nodelay;' \
    '    client_max_body_size 8k;' \
    '    proxy_pass ${QDOJO_LIVE_API};' \
    '    proxy_set_header X-Forwarded-For $qdojo_client;' \
    '    proxy_set_header X-Real-Client-IP $qdojo_client;' \
    '    proxy_connect_timeout 2s;' \
    '    proxy_read_timeout 10s;' \
    '    proxy_intercept_errors on;' \
    '    error_page 502 503 504 = @apidown;' \
    '  }' \
    '  location @apidown { default_type application/json; add_header Cache-Control "no-store" always; return 503 "{\"schema\":\"qdojo.combat.api.error.v1\",\"error\":{\"status\":503,\"code\":\"api_down\",\"message\":\"read API unavailable; the site uses the static export\"}}"; }' \
    '  location @baked { add_header Cache-Control "public, max-age=30"; try_files $uri =404; }' \
    '  location /data/ { add_header Cache-Control "public, max-age=30"; }' \
    '  location ~* \.(js|css|html)$ { add_header Cache-Control "public, max-age=300, must-revalidate"; }' \
    '  location / { try_files $uri $uri/ /index.html; }' \
    '}' > /etc/nginx/templates/default.conf.template && rm -f /etc/nginx/conf.d/default.conf

EXPOSE 80
