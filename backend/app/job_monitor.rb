require_relative 'db'
require_relative 'prefect'

# Prefectのジョブを監視し、完了/失敗時にマップステータスを自動更新するモジュール
module JobMonitor
  @running = false
  @thread = nil

  # モニタリング開始
  def self.start!
    return if @running

    @running = true
    @thread = Thread.new do
      puts "[JobMonitor] Started monitoring jobs every 5 seconds"
      
      loop do
        begin
          check_jobs
        rescue => e
          puts "[JobMonitor] Error: #{e.message}"
          puts e.backtrace.join("\n")
        end

        sleep 5
        break unless @running
      end
    end
  end

  # モニタリング停止
  def self.stop!
    @running = false
    @thread&.join
    puts "[JobMonitor] Stopped monitoring"
  end

  # 実行中のジョブをチェック
  def self.check_jobs
    # processing状態のマップを取得
    processing_maps = DB.list_maps(status: 'processing')
    
    return if processing_maps.empty?

    processing_maps.each do |map|
      # マップに紐づくジョブを取得
      job = DB.find_job_by_map_id(map[:id])
      next unless job

      begin
        # Prefectのフローラン状態を取得
        state = Prefect.get_flow_run_state(job[:prefect_run_id])
        
        case state
        when 'Completed'
          # 完了: マップステータスをcompletedに更新
          DB.update_map_status(map[:id], 'completed')
          DB.update_map_published_at(map[:id])
          puts "[JobMonitor] Map #{map[:id]} (#{map[:name]}) completed"
          
        when 'Failed', 'Crashed', 'Cancelled'
          # 失敗: マップステータスをfailedに更新
          DB.update_map_status(map[:id], 'failed')
          puts "[JobMonitor] Map #{map[:id]} (#{map[:name]}) failed with state: #{state}"
          
        when 'Running', 'Pending', 'Scheduled'
          # 実行中: 何もしない
          # puts "[JobMonitor] Map #{map[:id]} (#{map[:name]}) is still #{state}"
          
        else
          puts "[JobMonitor] Map #{map[:id]} (#{map[:name]}) has unknown state: #{state}"
        end
        
      rescue => e
        puts "[JobMonitor] Error checking job for map #{map[:id]}: #{e.message}"
      end
    end
  end
end
