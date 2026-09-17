# The spectator page is static files: the arcade, and the JSON the house
# exports. Nothing here runs Python, holds a seed, or can sign anything --
# it serves apps/web and nothing else.
FROM nginx:1.27-alpine

COPY apps/web/ /usr/share/nginx/html/

# dash.html/dash.js are the LOCAL fighter page, served by `qdojo bot dash` on
# 127.0.0.1 against an API that exists only on the player's own machine. On the
# public site they would be a dead page, so they do not ship in this image.
RUN rm -f /usr/share/nginx/html/dash.html /usr/share/nginx/html/dash.js

# llms.txt must arrive as readable text, not a download, because the whole
# point is that a person or an agent can open it in a browser.
RUN printf '%s\n' \
    'types { text/plain txt; }' \
    'server {' \
    '  listen 80;' \
    '  root /usr/share/nginx/html;' \
    '  index index.html;' \
    '  charset utf-8;' \
    '  location = /llms.txt { default_type text/plain; }' \
    '  location /data/ { add_header Cache-Control "public, max-age=30"; }' \
    '  location / { try_files $uri $uri/ /index.html; }' \
    '}' > /etc/nginx/conf.d/default.conf

EXPOSE 80
