FROM debian:trixie-slim

RUN apt-get update && apt-get install -y \
    nginx \
    ruby \
    ruby-dev \
    build-essential \
    libpq-dev \
    curl \
    gettext-base \
    && gem install bundler \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /dev/stdout /var/log/nginx/access.log \
    && ln -sf /dev/stderr /var/log/nginx/error.log

WORKDIR /app/app

COPY app/Gemfile app/Gemfile.lock ./
RUN bundle install

WORKDIR /app

COPY app ./app
COPY public ./public

COPY nginx.conf /etc/nginx/nginx.conf

COPY start.sh ./
RUN chmod +x start.sh

EXPOSE 8000

CMD ["./start.sh"]
