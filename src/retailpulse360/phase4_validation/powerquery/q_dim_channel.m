let
    Source = fnLoadCsv("analytics/dim_channel.csv", {
        {"channel_key", type text},
        {"channel_name", type text},
        {"is_additive", Int64.Type}
    })
in
    Source
