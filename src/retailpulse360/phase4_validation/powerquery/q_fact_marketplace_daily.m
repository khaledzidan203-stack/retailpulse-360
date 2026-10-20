let
    Source = fnLoadCsv("analytics/fact_marketplace_daily.csv", {
        {"store_key", type text},
        {"account_key", type text},
        {"date_key", Int64.Type},
        {"attributed_retail_net_sales_cents", Int64.Type},
        {"orders", Int64.Type},
        {"units", Int64.Type},
        {"source_snapshot_id", type text},
        {"lineage_hash", type text}
    })
in
    Source
