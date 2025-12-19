FROM nginx:alpine

# 必要なパッケージのインストール（gettext for envsubst）
RUN apk add --no-cache ruby ruby-dev ruby-bundler build-base gettext

# 作業ディレクトリの作成
WORKDIR /app

# Gemfileのコピーと依存関係のインストール
COPY Gemfile Gemfile.lock ./
RUN bundle install

# アプリケーションファイルのコピー
COPY app.rb ./
COPY public ./public

# nginx設定のコピー
COPY nginx.conf /etc/nginx/nginx.conf

# スタートアップスクリプト
COPY start.sh ./
RUN chmod +x start.sh

EXPOSE 8000

CMD ["./start.sh"]
