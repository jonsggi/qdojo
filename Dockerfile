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
ENV QDOJO_LIVE_DATA=http://100.101.145.63:8790
RUN mkdir -p /etc/nginx/templates && printf '%s\n' \
    'types { text/plain txt; }' \
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
    '  location @baked { add_header Cache-Control "public, max-age=30"; try_files $uri =404; }' \
    '  location /data/ { add_header Cache-Control "public, max-age=30"; }' \
    '  location ~* \.(js|css|html)$ { add_header Cache-Control "public, max-age=300, must-revalidate"; }' \
    '  location / { try_files $uri $uri/ /index.html; }' \
    '}' > /etc/nginx/templates/default.conf.template && rm -f /etc/nginx/conf.d/default.conf

EXPOSE 80
