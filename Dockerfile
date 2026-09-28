# The spectator site is static files: the combat site (index.html) and the
# JSON the arena exports. The riddle arcade was removed on 2026-09-27: its old
# URLs redirect (to / and to the archived briefing at tag riddle-v0-final). Nothing here runs Python, holds a seed, or can sign anything --
# it serves apps/web and nothing else.
FROM nginx:1.27-alpine

COPY apps/web/ /usr/share/nginx/html/

# Every build stamps each page's own script and stylesheet URLs with a
# version, so a CDN in front cannot keep serving last week's app.js beside this
# week's data: a new URL is a new object. Every .html is stamped, and relative
# paths such as combat/app.js count; absolute URLs (fonts) have a ':' and are
# left alone. The combat page must end up stamped or the build fails.
RUN v=$(date +%s) && for f in /usr/share/nginx/html/*.html; do \
      sed -E -i "s#(src|href)=\"([a-z0-9_-]+(/[a-z0-9_-]+)*\.(js|css))\"#\1=\"\2?v=$v\"#g" "$f"; \
    done && grep -q "combat/app.js?v=$v" /usr/share/nginx/html/index.html

# dash.html/dash.js are the LOCAL fighter page, served by `qdojo bot dash` on
# 127.0.0.1 against an API that exists only on the player's own machine. On the
# public site they would be a dead page, so they do not ship in this image.
# anim.html is the sparring bench for the fighter clips and tests/ is the
# site's own test suite: development tools, not pages.
RUN rm -rf /usr/share/nginx/html/dash.html /usr/share/nginx/html/dash.js \
      /usr/share/nginx/html/anim.html /usr/share/nginx/html/tests /usr/share/nginx/html/AVATARS.md

# llms.txt must arrive as
# readable text, not a download, because the whole
# point is that a person or an agent can open it in a browser. The page's own
# files say max-age=300: without an origin header the CDN in front kept an
# old app.js for four hours after a deploy, so the site showed new data with
# old code (2026-09-21).
#
# Live combat data (/data/combat/v1/) is not baked into the image: it is
# proxied to the live arena's data server, so spectators see fights within
# seconds and main is not flooded with data commits. If that server is down,
# the copy baked into the image answers instead and the page's STALE badge
# shows its age. QDOJO_LIVE_DATA is substituted by the nginx image's template
# step at container start (deploy/nginx/default.conf.template).
#
# The read API (/api/v1/: full history, pagination, search; docs/api.md §3.2)
# is `qdojo combat api` on the same host. It replaces the static data server
# and also serves /data/combat/v1/, so both usually point at one port. If it is
# down, /api/v1/ answers a JSON 503 and the site falls back to the static
# files. Writes (outside builders joining the arena, docs/build-a-bot.md
# §8) are refused here unless QDOJO_JOIN_OPEN=1, whatever the API allows.
#
# Per deployment (docs/testnet.md): QDOJO_LIVE_DATA and QDOJO_LIVE_API point at
# that arena's data server and read API; QDOJO_SITE_URL is the public origin
# (no trailing slash) that share links, canonical URL, robots.txt and
# sitemap.xml name. Network labels (DEVNET, TESTNET, currency) are NOT set
# here: the site reads them from the arena's own export (index.json
# deployment.kind), so they cannot disagree with the data.
ENV QDOJO_LIVE_DATA=http://100.101.145.63:8790
ENV QDOJO_LIVE_API=http://100.101.145.63:8790
ENV QDOJO_JOIN_OPEN=0
ENV QDOJO_SITE_URL=https://qdojo.jonsggi.com
COPY deploy/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY deploy/nginx/qdojo-headers.conf /etc/nginx/qdojo-headers.conf
RUN rm -f /etc/nginx/conf.d/default.conf

EXPOSE 80
