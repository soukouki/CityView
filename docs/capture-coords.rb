
MAP_X = ARGV[0].to_i
MAP_Y = ARGV[1].to_i
DELTA = ARGV[2].to_i

# ゲーム座標(x, y)からスクショ座標で左側に移動する
# ただしマップの範囲外には出ないようにする
def left(x, y)
  ideal_x = x - DELTA
  ideal_y = y + DELTA
  # マップ範囲外チェック
  # y=MAP_Yの右下の辺と、 x=0の左上の辺で制限
  if ideal_y > MAP_Y
    ideal_y = MAP_Y
    ideal_x = x - (MAP_Y - y)  # yだけしか上がれないので、その分しか左に行けない
  end
  if ideal_x < 0
    ideal_x = 0
    ideal_y = y + (x)  # xだけしか左に行けないので、その分しか上に行けない
  end
  [ideal_x, ideal_y]
end

# ゲーム座標(x, y)からスクショ座標で右側に移動する
# ただしマップの範囲外には出ないようにする
def right(x, y)
  ideal_x = x + DELTA
  ideal_y = y - DELTA
  # マップ範囲外チェック
  # y=0の左上の辺と、 x=MAP_Xの右下の辺で制限
  if ideal_y < 0
    ideal_y = 0
    ideal_x = x + (y)  # yだけしか下がれないので、その分しか右に行けない
  end
  if ideal_x > MAP_X
    ideal_x = MAP_X
    ideal_y = y - (MAP_X - x)  # xだけしか右に行けないので、その分しか下がれない
  end
  [ideal_x, ideal_y]
end

# ゲーム座標(x, y)からスクショ座標で下側に移動する
def down(x, y)
  ideal_x = x + DELTA
  ideal_y = y + DELTA
  # マップ範囲外チェック
  if ideal_x > MAP_X
    ideal_x = MAP_X
    ideal_y = y + (MAP_X - x)  # xだけしか右に行けないので、その分しか下に行けない
  end
  if ideal_y > MAP_Y
    ideal_y = MAP_Y
    ideal_x = x + (MAP_Y - y)  # yだけしか上がれないので、その分しか右に行けない
  end
  [ideal_x, ideal_y]
end

#　[{x: Integer, y: Integer, compare: [{x: Integer, y: Integer}]}]
screenshots = []

if MAP_X >= MAP_Y

  # PHASE 1 : ジグザグにマップ長辺のスクショを撮影する
  current_x = 0
  current_y = 0
  screenshots << {x: current_x, y: current_y, compare: []} # 最初のスクショなので比較対象はない。このスクショの左上の座標は(0,0)
  # 次のフェーズでどこから左に向かうのかを記録しておくための変数
  flag1 = [] # [{x: Integer, y: Integer}]
  loop do
    # 下に移動
    new_x, new_y = down(current_x, current_y)
    screenshots << {x: new_x, y: new_y, compare: [{x: current_x, y: current_y}]}
    current_x = new_x
    current_y = new_y
    flag1 << {x: current_x, y: current_y}
    break if current_y == MAP_Y
    # 右に移動
    new_x, new_y = right(current_x, current_y)
    screenshots << {x: new_x, y: new_y, compare: [{x: current_x, y: current_y}]}
    current_x = new_x
    current_y = new_y
    break if current_x == MAP_X
  end

  # PHASE 2 : flag1から左に向かってスクショを撮影する
  flag1.each do |start_point|
    current_x = start_point[:x]
    current_y = start_point[:y]
    loop do
      # 左に移動
      new_x, new_y = left(current_x, current_y)
      break if new_x == current_x && new_y == current_y  # もう左に行けない場合は終了
      screenshots << {x: new_x, y: new_y, compare: [{x: current_x, y: current_y}]}
      current_x = new_x
      current_y = new_y
    end
  end

  # PHASE 3 : PHASE 2の最後の行での各列を下向きにスクショ撮影する
  last_line = flag1.last
  start_points = []
  current_x = last_line[:x]
  current_y = last_line[:y]
  loop do
    start_points << {x: current_x, y: current_y}
    # 左に移動
    new_x, new_y = left(current_x, current_y)
    break if new_x == current_x && new_y == current_y  # もう左に行けない場合は終了
    current_x = new_x
    current_y = new_y
  end
  start_points.each do |start_point|
    current_x = start_point[:x]
    current_y = start_point[:y]
    loop do
      # 下に移動
      new_x, new_y = down(current_x, current_y)
      break if new_x == current_x && new_y == current_y  # もう下に行けない場合は終了
      screenshots << {x: new_x, y: new_y, compare: [{x: current_x, y: current_y}]}
      current_x = new_x
      current_y = new_y
    end
  end

else # MAP_X < MAP_Y

  # PHASE 1 : ジグザグにマップ長辺のスクショを撮影する
  current_x = 0
  current_y = 0
  screenshots << {x: current_x, y: current_y, compare: []} # 最初のスクショなので比較対象はない。このスクショの左上の座標は(0,0)
  # 次のフェーズでどこから上に向かうのかを記録しておくための変数
  flag1 = [] # [{x: Integer, y: Integer}]
  loop do
    # 下に移動
    new_x, new_y = down(current_x, current_y)
    screenshots << {x: new_x, y: new_y, compare: [{x: current_x, y: current_y}]}
    current_x = new_x
    current_y = new_y
    flag1 << {x: current_x, y: current_y}
    break if current_y == MAP_Y
    # 左に移動
    new_x, new_y = left(current_x, current_y)
    screenshots << {x: new_x, y: new_y, compare: [{x: current_x, y: current_y}]}
    current_x = new_x
    current_y = new_y
    break if current_x == MAP_X
  end

  # PHASE 2 : flag1から右に向かってスクショを撮影する
  flag1.each do |start_point|
    current_x = start_point[:x]
    current_y = start_point[:y]
    loop do
      # 右に移動
      new_x, new_y = right(current_x, current_y)
      break if new_x == current_x && new_y == current_y  # もう右に行けない場合は終了
      screenshots << {x: new_x, y: new_y, compare: [{x: current_x, y: current_y}]}
      current_x = new_x
      current_y = new_y
    end
  end

  # PHASE 3 : PHASE 2の最後の行での各列を下向きにスクショ撮影する
  last_line = flag1.last
  start_points = []
  current_x = last_line[:x]
  current_y = last_line[:y]
  loop do
    start_points << {x: current_x, y: current_y}
    # 右に移動
    new_x, new_y = right(current_x, current_y)
    break if new_x == current_x && new_y == current_y  # もう右に行けない場合は終了
    current_x = new_x
    current_y = new_y
  end
  start_points.each do |start_point|
    current_x = start_point[:x]
    current_y = start_point[:y]
    loop do
      # 下に移動
      new_x, new_y = down(current_x, current_y)
      break if new_x == current_x && new_y == current_y  # もう下に行けない場合は終了
      screenshots << {x: new_x, y: new_y, compare: [{x: current_x, y: current_y}]}
      current_x = new_x
      current_y = new_y
    end
  end
end

# 結果出力
pp screenshots
