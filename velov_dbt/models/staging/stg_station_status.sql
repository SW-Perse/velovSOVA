{{ config(materialized="view") }}

select
    cast(station.station_id as integer) as station_id,
    to_timestamp(station.last_reported) as reported_at,
    cast(station.num_bikes_available as integer) as bikes_available,
    cast(station.num_docks_available as integer) as docks_available,
    cast(station.num_bikes_disabled as integer) as bikes_disabled,
    cast(station.num_docks_disabled as integer) as docks_disabled,
    cast(station.is_installed as boolean) as is_installed,
    cast(station.is_renting as boolean) as is_renting,
    cast(station.is_returning as boolean) as is_returning
from (
    select unnest(data.stations) as station
    from read_json_auto('{{ var("bronze_path", "../data/bronze") }}/station_status/*.json')
)
qualify row_number() over (
    partition by station_id, reported_at
    order by reported_at desc
) = 1
