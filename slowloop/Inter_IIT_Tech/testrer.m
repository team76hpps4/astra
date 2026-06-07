clear; close all;clc;

%% ===============================================================
%  TEST SCRIPT: RRM WITH VIRTUAL SENSING RADIO
%  Features: 
%  1. High Tx Power (23dBm) & Loosened CCA (-70dBm)
%  2. 40MHz Channel Width
%  3. New Output: 4-Metric Spectral Sensing per AP
%  4. Filtering: Results shown ONLY for Network 1
% ================================================================

%% 1. CONFIGURATION
config = struct();
config.random_seed = 123;
config.sim_duration_s = 5;  % Sufficient for sensing statistics
config.dt_ms = 10;
config.channel_width_mhz = 40; % As requested (CW)

% Noise & Shadowing
config.noise_floor_dbm = -95;
config.noise_variation_frac = 0.03;
config.short_term_shadowing_sigma = 6;
config.shadowing_sigma = 4;

% CCA/PD: Loosened for more TX
config.cca_threshold_dbm = -80; 

% Geometry (N Rooms)
config.room_size = [20,20];
config.num_rooms = 12; 
config.ap_per_room = 3;
config.client_grid_spacing = 5;

% Non-WiFi: Low duty cycle
config.bt.count = 1;
config.bt.tx_power_dbm = 4;
config.bt.duty_cycle = 0.2;
config.zb.count = 1;
config.zb.tx_power_dbm = 3;
config.zb.duty_cycle = 0.1;

% Channels & MCS
config.channels = 1:13;
config.MCS_SINR_Required = [0,1.5,3.5,5,8,10,12,13,15,17,18,20];
config.MCS_Rates_20MHz = [6.5,13,19.5,26,39,52,58.5,65,78,86.7,97.5,108.3];

% Path Loss
config.pathloss.n_exp = 3.8;
config.pathloss.wall_loss_db = 15;
config.pathloss.PL_d0_dB = 40;
config.pathloss.d0 = 1;

%% 2. BUILD AP CONFIGS (RADIAL DISTRIBUTION)
TX = 25 ;
PD = -88; 
CW = 40;  
CH_CYCLE = [1, 6, 11]; 

ap_configs = struct([]);
idx = 1;

fprintf('Building Environment: %d Rooms, %d APs total...\n', config.num_rooms, config.num_rooms * config.ap_per_room);

% Center of the simulation world
center_x = 50;
center_y = 50;
% Distance between 'layers' of rooms (Must be > Room Size to avoid overlap)
spread_factor = 45; 
% The Golden Angle (approx 2.399 rads) prevents rooms from lining up
golden_angle = pi * (3 - sqrt(5)); 

for r = 1:config.num_rooms
    % --- CALCULATE ROOM ORIGIN (GOLDEN SPIRAL) ---
    % Radius grows with sqrt(r) to keep density constant
    radius = spread_factor * sqrt(r); 
    % Angle increments by golden ratio
    theta = r * golden_angle; 
    
    % Add slight random jitter so it's not a "perfect" mathematical spiral
    theta_jit = theta + (rand - 0.5) * 0.5; 
    radius_jit = radius + (rand - 0.5) * 5;

    % Convert Polar to Cartesian to get Room Bottom-Left Corner
    room_x = center_x + radius_jit * cos(theta_jit);
    room_y = center_y + radius_jit * sin(theta_jit);
    
    % Channel Selection Cycle
    ch_idx = mod(r-1, 3) + 1;
    
    % --- PLACE 3 APs INSIDE THE ROOM (TRIANGULAR FORMATION) ---
    % We place them relative to the room origin so they stay together
    
    % AP 1 (Bottom Left)
    ap_configs(idx).pos = [room_x + 5, room_y + 5];
    ap_configs(idx).tx_power_dbm = TX;
    ap_configs(idx).channel_width_mhz = CW;
    ap_configs(idx).channel = CH_CYCLE(ch_idx);
    ap_configs(idx).obss_pd_dbm = PD;
    ap_configs(idx).network_id = mod(idx-1, 3) + 1;
    idx = idx + 1;
    
    % AP 2 (Top Center)
    ap_configs(idx).pos = [room_x + 15, room_y + 25];
    ap_configs(idx).tx_power_dbm = TX;
    ap_configs(idx).channel_width_mhz = CW;
    ap_configs(idx).channel = CH_CYCLE(mod(ch_idx, 3) + 1);
    ap_configs(idx).obss_pd_dbm = PD;
    ap_configs(idx).network_id = mod(idx-1, 3) + 1;
    idx = idx + 1;
    
    % AP 3 (Bottom Right)
    ap_configs(idx).pos = [room_x + 25, room_y + 5]; 
    ap_configs(idx).tx_power_dbm = TX;
    ap_configs(idx).channel_width_mhz = CW;
    ap_configs(idx).channel = CH_CYCLE(mod(ch_idx + 1, 3) + 1);
    ap_configs(idx).obss_pd_dbm = PD;
    ap_configs(idx).network_id = mod(idx-1, 3) + 1;
    idx = idx + 1;
end

%% 3. RUN SIMULATION
disp("Running simulation...");
tic;
results = simulate_environment(config, ap_configs); 
toc;

%% 4. VISUALIZE RESULTS (FILTERED FOR NETWORK 1)

% --- Part A: Standard Throughput Metrics ---
fprintf('\n================================================================\n');
fprintf('   PERFORMANCE REPORT (NETWORK 1 ONLY)\n');
fprintf('================================================================\n');

num_AP = length(ap_configs);
for a = 1:num_AP
    % --- FILTER: SHOW ONLY NETWORK 1 ---
    if ap_configs(a).network_id ~= 1
        continue;
    end
    % -----------------------------------
    
    if ~isfield(results, 'time')
        error('results.time field is missing. Ensure simulate_environment.m is updated.');
    end
    
    util = mean(results.time.AP_airtime(a,:)) * 100;
    
    % Re-calculate Mean Throughput for this AP
    [~, AP2Cl] = precompute_rssi_test(results.env, config, ap_configs);
    [~, assoc] = max(AP2Cl, [], 2);
    my_clients = find(assoc == a);
    
    if ~isempty(my_clients)
        ap_thr_ts = sum(results.time.Client_throughput_mbps_ts(my_clients, :), 1);
        med_thr = median(ap_thr_ts);
        mean_thr = mean(ap_thr_ts);
    else
        med_thr = 0; mean_thr = 0;
    end
    
    % Retry Rate
    retry_rate = results.perAP(a).avg_retry_percent;
    
    fprintf('AP %02d (Ch %d): Util=%.1f%% | Retry=%.1f%% | Median Tput=%.2f Mbps | Mean Tput=%.2f Mbps\n', ...
        a, ap_configs(a).channel, util, retry_rate, med_thr, mean_thr);
end

% --- Part B: THE NEW SENSING METRICS ---
fprintf('\n================================================================\n');
fprintf('   VIRTUAL SPECTRUM ANALYZER REPORT (NETWORK 1 ONLY)\n');
fprintf('================================================================\n');

if isfield(results, 'Sensing_Data')
    for a = 1:num_AP
        % --- FILTER: SHOW ONLY NETWORK 1 ---
        if ap_configs(a).network_id ~= 1
            continue;
        end
        % -----------------------------------
        
        fprintf('\n--- Sensing Report: AP %d (Operating on Ch %d) ---\n', a, ap_configs(a).channel);
        T = results.Sensing_Data(a).Metrics_Table;
        
        fprintf('%-8s | %-15s | %-15s | %-15s | %-15s\n', ...
            'Channel', 'Interf P95(dBm)', 'DutyCycle P50', 'Prob Non-WiFi', 'NoiseFloor(dBm)');
        fprintf('------------------------------------------------------------------------------\n');
        
        for i = 1:height(T)
            fprintf('%-8d | %-15.2f | %-15.2f | %-15.4f | %-15.2f', ...
                T.Channel(i), ...
                T.Interf_P95_dBm(i), ...
                T.DutyCycle_P50(i), ...
                T.Prob_NonWiFi(i), ...
                T.NoiseFloor_P95_dBm(i));
                
            if T.Channel(i) == ap_configs(a).channel
                fprintf(' <--- OPERATING CH');
            end
            fprintf('\n');
        end
    end
else
    warning('Sensing_Data field is missing in results.');
end

%% --- HELPER FOR REPORTING ---
function [ap2ap, ap2cl] = precompute_rssi_test(env, cfg, ap_cfg)
    n_ap = numel(ap_cfg); n_cl = size(env.client_positions,1);
    ap2ap = zeros(n_ap, n_ap); ap2cl = zeros(n_cl, n_ap);
    for i=1:n_ap
        for c=1:n_cl
            d = max(norm(ap_cfg(i).pos - env.client_positions(c,:)), 1);
            walls = floor(abs(ap_cfg(i).pos(1) - env.client_positions(c,1))/10);
            pl = cfg.pathloss.PL_d0_dB + 10*cfg.pathloss.n_exp*log10(d) + walls*cfg.pathloss.wall_loss_db;
            ap2cl(c,i) = ap_cfg(i).tx_power_dbm - pl;
        end
    end
end