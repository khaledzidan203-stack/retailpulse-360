let
    Source = fnLoadCsv("analytics/fact_sales_daily.csv", {
        {"store_key", type text},
        {"date_key", Int64.Type},
        {"channel_key", type text},
        {"gross_sales_cents", Int64.Type},
        {"returns_amount_cents", Int64.Type},
        {"net_sales_cents", Int64.Type},
        {"transactions", Int64.Type},
        {"units", Int64.Type},
        {"source_snapshot_id", type text},
        {"lineage_hash", type text}
    })
in
    Source
