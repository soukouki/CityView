FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# System deps:
# - ruby: Sinatra
# - xvfb: virtual display
# - xdotool: key/mouse automation
# - scrot: screenshot
# - imagemagick: pixel check / cropping backend for MiniMagick
# - curl: debug / health checks
# - tini: proper PID 1 reaping
# - libminiupnpc-dev: Simutrans
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ruby-full \
      build-essential \
      xvfb \
      xdotool \
      scrot \
      imagemagick \
      ca-certificates \
      curl \
      tini \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Simutrans deps:
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      autoconf \
      build-essential \
      libbz2-dev \
      libpng-dev \
      libz-dev \
      subversion \
      unzip \
      miniupnpc \
      libsdl2-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# create libminiupnpc.so.18 symlink for Simutrans
RUN ln -s /usr/lib/x86_64-linux-gnu/libminiupnpc.so.18 /usr/lib/x86_64-linux-gnu/libminiupnpc.so.17 && \
    ldconfig

# Bundler
RUN gem install bundler -N

# App deps
COPY Gemfile Gemfile.lock ./
RUN bundle config set without 'development test' && \
    bundle install --jobs 4 --retry 3

# App code
COPY . .

# Runtime defaults
ENV RACK_ENV=production \
    PORT=5000 \
    DISPLAY=:99 \
    XDG_RUNTIME_DIR=/tmp/xdg-runtime

EXPOSE 5000

# Use tini as PID1; start Xvfb then Puma.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "-lc", "Xvfb ${DISPLAY} -screen 0 ${CAPTURE_SCREEN_WIDTH}x${CAPTURE_SCREEN_HEIGHT}x24 -ac +extension GLX +render -noreset & bundle exec puma -C config/puma.rb"]
