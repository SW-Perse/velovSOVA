{{ config(materialized="view") }}

select
    cast(station.station_id as integer) as station_id,
    cast(station.name as varchar) as name,
    cast(station.lat as double) as latitude,
    cast(station.lon as double) as longitude,
    cast(station.address as varchar) as address,
    cast(station.capacity as integer) as capacity
from (
    select unnest(data.stations) as station
    from read_json_auto('{{ var("bronze_path", "../data/bronze") }}/station_information/*.json')
)
qualify row_number() over (
    partition by station_id
    order by capacity desc nulls last
) = 1
