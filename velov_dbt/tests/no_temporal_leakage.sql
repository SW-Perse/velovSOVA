select s.station_id, s.reported_at, h.timestamp
from {{ ref("stg_station_status") }} s
inner join {{ ref("station_hourly") }} h
    on h.station_id = s.station_id
    and h.timestamp = date_trunc('hour', s.reported_at - interval 1 microsecond) + interval 1 hour
where s.reported_at > h.timestamp
