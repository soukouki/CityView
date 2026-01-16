#!/bin/sh

# 環境変数が設定されていない場合はデフォルト値を使用
export STORAGE_HOST=${STORAGE_HOST:-storage}

# nginx設定ファイルで環境変数を展開
envsubst '${STORAGE_HOST}' < /etc/nginx/nginx.conf > /etc/nginx/nginx.conf.tmp
mv /etc/nginx/nginx.conf.tmp /etc/nginx/nginx.conf

# Sinatraアプリケーションをバックグラウンドで起動
cd /app/app
bundle exec ruby app.rb &

# nginxをフォアグラウンドで起動
nginx -g 'daemon off;'
