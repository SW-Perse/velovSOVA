{{ config(materialized="table") }}

with hourly_status as (
    select
        s.station_id,
        date_trunc('hour', s.reported_at - interval 1 microsecond) + interval 1 hour as timestamp,
        i.capacity,
        s.bikes_available,
        row_number() over (
            partition by s.station_id,
                date_trunc('hour', s.reported_at - interval 1 microsecond) + interval 1 hour
            order by s.reported_at desc
        ) as row_number
    from {{ ref("stg_station_status") }} s
    inner join {{ ref("stg_station_information") }} i using (station_id)
),
latest_status as (
    select station_id, timestamp, capacity, bikes_available
    from hourly_status
    where row_number = 1
)
select
    cast(s.station_id as integer) as station_id,
    cast(s.timestamp as timestamptz) as timestamp,
    cast(s.capacity as integer) as capacity,
    cast(s.bikes_available as integer) as bikes_available,
    cast(w.temperature as double) as temperature,
    cast(w.is_raining as boolean) as is_raining
from latest_status s
inner join {{ ref("stg_weather") }} w
    on w.hour_ts = s.timestamp
